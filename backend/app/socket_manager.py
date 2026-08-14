"""
app/socket_manager.py

Async Socket.IO server used to push real-time job progress updates
(phase transitions, log messages, completion/error) from background
tasks to connected frontend clients.

Each frontend client joins a room keyed by `job_id` via the
"join_job" event, so emits are scoped to only the relevant client.
"""

from __future__ import annotations

import asyncio
import logging

import socketio

logger = logging.getLogger(__name__)

# Create a single shared AsyncServer instance.
# `async_mode="asgi"` lets us mount it alongside FastAPI.
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    logger=False,
    engineio_logger=False,
)


_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


@sio.event
async def connect(sid: str, environ: dict):
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    logger.info("Socket.IO client connected: %s", sid)


@sio.event
async def disconnect(sid: str):
    logger.info("Socket.IO client disconnected: %s", sid)


@sio.event
async def join_job(sid: str, data: dict):
    """Client joins a room for a specific job to receive its updates."""
    global _main_loop
    try:
        _main_loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    job_id = data.get("job_id")
    if not job_id:
        return

    await sio.enter_room(sid, f"job:{job_id}")
    logger.info("Client %s joined room job:%s", sid, job_id)

    # Check current status in DB so late-connecting clients catch up instantly
    try:
        from app.db import SessionLocal
        from app.models.db_models import Job, JobStatus, DiagnosisResult, ImputationResult
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                if job.status == JobStatus.COMPLETE:
                    await sio.emit("job:phase", {"phase": "complete", "message": "Pipeline finished successfully"}, room=sid)
                    await sio.emit("job:complete", {}, room=sid)
                elif job.status == JobStatus.FAILED:
                    await sio.emit("job:error", {"message": job.error_message or "Job failed"}, room=sid)
                elif job.status == JobStatus.RUNNING or job.status == JobStatus.PENDING:
                    has_imp = db.query(ImputationResult).filter(ImputationResult.job_id == job_id).first() is not None
                    has_diag = db.query(DiagnosisResult).filter(DiagnosisResult.job_id == job_id).first() is not None
                    if has_imp:
                        await sio.emit("job:phase", {"phase": "explaining", "message": "Generating plain-language explanation…"}, room=sid)
                    elif has_diag:
                        await sio.emit("job:phase", {"phase": "imputing", "message": "Applying imputation strategies…"}, room=sid)
                    else:
                        await sio.emit("job:phase", {"phase": "diagnosing", "message": "Starting missingness diagnosis…"}, room=sid)
        finally:
            db.close()
    except Exception as exc:
        logger.error("Error sending catch-up state on join_job for %s: %s", job_id, exc)


def emit_to_job(job_id: str, event: str, data: dict) -> None:
    """Synchronous helper for background threads to emit to a job room.

    Background tasks run in a thread (FastAPI's BackgroundTasks), not in
    the async event loop, so we need to bridge via `asyncio.run_coroutine_threadsafe`.
    """
    global _main_loop
    room = f"job:{job_id}"
    try:
        # If called from a thread that already has an active running loop
        loop = asyncio.get_running_loop()
        asyncio.create_task(sio.emit(event, data, room=room))
        return
    except RuntimeError:
        pass

    if _main_loop is not None and _main_loop.is_running():
        try:
            future = asyncio.run_coroutine_threadsafe(
                sio.emit(event, data, room=room), _main_loop
            )
            # Wait briefly to ensure the event loop schedules the emit
            future.result(timeout=5)
        except Exception as exc:
            logger.error("Error emitting Socket.IO event %s to %s: %s", event, room, exc)
    else:
        logger.warning("Main loop not captured or not running, cannot emit %s", event)
