"""
main.py

FastAPI main application entrypoint. Sets up CORS, imports routers,
initializes database tables on startup, and wraps the app with
python-socketio's ASGIApp for real-time WebSocket support.
"""

from __future__ import annotations

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import Base, engine
import app.models.db_models  # Ensure all ORM models (including ValidationDecisionCache) are registered before create_all
# Register routers
from app.api.routes import router as api_router
from app.api.routes_synthetic import router as synthetic_router
from app.api.routes_sensitivity import router as sensitivity_router
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
        conn.execute(text("ALTER TABLE datasets DROP COLUMN IF EXISTS user_id;"))
        conn.execute(text("DROP TABLE IF EXISTS users;"))
except Exception as e:
    print(f"Schema check notice: {e}")

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
app.include_router(sensitivity_router, prefix="/api/sensitivity", tags=["sensitivity"])


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
