"""
main.py

FastAPI main application entrypoint. Sets up CORS, imports routers,
initializes database tables on startup, and wraps the app with
python-socketio's ASGIApp for real-time WebSocket support.
"""

from __future__ import annotations

import logging

import socketio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import Base, engine
import app.models.db_models  # Ensure all ORM models (including ValidationDecisionCache) are registered before create_all
# Register routers
from app.api.routes import router as api_router
from app.api.routes_synthetic import router as synthetic_router
from app.socket_manager import sio

# Initialize database tables
Base.metadata.create_all(bind=engine)

# Automatically migrate schema for existing database instances where tables pre-date new columns
try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE diagnosis_results ADD COLUMN IF NOT EXISTS structural_zero_warning JSON;"))
        conn.execute(text("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS validated_storage_path VARCHAR;"))
        conn.execute(text("ALTER TABLE diagnosis_results ADD COLUMN IF NOT EXISTS semantic_role VARCHAR;"))
        conn.execute(text("ALTER TABLE imputation_results ADD COLUMN IF NOT EXISTS semantic_role VARCHAR;"))
        conn.execute(text("ALTER TABLE validation_decision_cache ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'gemini';"))
        conn.execute(text("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS data_dictionary TEXT;"))
        conn.execute(text("ALTER TABLE datasets DROP COLUMN IF EXISTS user_id;"))
        conn.execute(text("DROP TABLE IF EXISTS users;"))
except Exception as e:
    print(f"Schema check notice: {e}")

logger = logging.getLogger(__name__)

app = FastAPI(title="Missing Data Pipeline API")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(api_router)
app.include_router(synthetic_router, prefix="/api/synthetic", tags=["synthetic"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return unhandled errors as a normal JSON response.

    Without this, Starlette's ServerErrorMiddleware produces the 500. That
    middleware sits outside CORSMiddleware, so the response carries no
    Access-Control-Allow-Origin header and the browser reports a CORS failure
    instead of the actual error. Returning a JSONResponse here keeps the
    response inside the middleware stack, so the real cause is visible in the
    network tab rather than being masked.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    import asyncio
    from app.socket_manager import set_main_loop
    set_main_loop(asyncio.get_running_loop())


# Wrap FastAPI with Socket.IO — this is the ASGI app that uvicorn serves.
# Socket.IO handles the /socket.io/ path; everything else falls through to FastAPI.
combined_app = socketio.ASGIApp(sio, other_asgi_app=app)
