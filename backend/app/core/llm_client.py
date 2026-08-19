"""
app/core/llm_client.py

Single point of contact with the language model provider.

Everything that needs the model goes through here, so swapping provider is one
file rather than a hunt through the codebase. Currently Groq.

Two differences from the previous Gemini integration shape the design:

1. Groq's chat completions API has no equivalent of Gemini's `response_schema`,
   so a schema cannot be enforced server-side. JSON mode guarantees syntactic
   JSON and nothing more, which means the shape must be described in the prompt
   and validated locally with Pydantic. `complete_json` does both.
2. Groq revises its model lineup regularly. The model is therefore read from
   GROQ_MODEL rather than pinned in code, and `list_available_models()` exists
   so a wrong name can be diagnosed instead of guessed at.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Overridable so a retired model can be swapped without a code change.
DEFAULT_MODEL = "llama-3.3-70b-versatile"


class LLMUnavailable(RuntimeError):
    """The provider could not be reached, or returned nothing usable.

    Callers are expected to degrade rather than propagate this: every feature
    that uses the model has a local fallback, because an outage or an exhausted
    quota should not take the pipeline down with it.
    """


def get_model_name() -> str:
    return os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def _get_api_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise LLMUnavailable(
            "GROQ_API_KEY is not set. Add it to your environment or .env file."
        )
    return key


def get_client():
    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise LLMUnavailable("The 'groq' package is not installed.") from exc
    return Groq(api_key=_get_api_key())


def list_available_models() -> list[str]:
    """Model ids the current key can use. For diagnosing a bad GROQ_MODEL."""
    try:
        return sorted(m.id for m in get_client().models.list().data)
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(f"Could not list models: {exc}") from exc


def complete_text(prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Plain text completion. Raises LLMUnavailable rather than returning junk.

    The budget is generous because reasoning models spend part of it before
    emitting any content. gpt-oss-120b given a small allowance returns an empty
    message rather than a short answer, which reads as an outage and sends the
    caller to its fallback for no reason.
    """
    try:
        response = get_client().chat.completions.create(
            model=get_model_name(),
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(str(exc)) from exc

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise LLMUnavailable("Model returned an empty response.")
    return text


def complete_json(
    prompt: str,
    schema: Type[T],
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> T:
    """Completion validated against a Pydantic model.

    JSON mode only promises parseable JSON, so the expected shape is included in
    the prompt and the reply is validated here. A structurally valid but
    wrongly-shaped reply raises LLMUnavailable, which puts the caller on its
    fallback path rather than letting a malformed object travel downstream.
    """
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    instructed = (
        f"{prompt}\n\n"
        f"Reply with a single JSON object and nothing else. It must conform to "
        f"this JSON schema:\n{schema_json}"
    )

    try:
        response = get_client().chat.completions.create(
            model=get_model_name(),
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise assistant. You reply only with valid JSON matching the requested schema.",
                },
                {"role": "user", "content": instructed},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(str(exc)) from exc

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        raise LLMUnavailable("Model returned an empty response.")

    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("Model reply did not match %s: %s", schema.__name__, exc)
        raise LLMUnavailable(f"Reply did not match {schema.__name__}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Reply was not valid JSON: {exc}") from exc
