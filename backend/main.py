"""
LocalForge — FastAPI entrypoint.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Load .env before anything else
load_dotenv()

from backend.config import load_config, get_settings, refresh_config_from_db, refresh_models_from_db
from backend.db.connection import init_pool, close_pool
from backend.db.store import init_db
from backend.middleware.auth import api_key_middleware
from backend.routers.chat import router as chat_router
from backend.routers.config import router as config_router
from backend.routers.models import router as models_router
from backend.routers.stats import router as stats_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_config()
    await init_pool()       # no-op for SQLite
    await init_db()

    # Init settings table and load non-model config from DB
    # (seeds DB from localforge.json on first run)
    from backend.db.settings_store import init_settings_table
    await init_settings_table()
    await refresh_config_from_db()

    # Init models table and seed from localforge.json if empty
    # refresh_models_from_db runs AFTER refresh_config_from_db so DB models win
    from backend.db.models_store import init_models_table, seed_from_config
    from backend.config import get_config
    await init_models_table()
    await seed_from_config(get_config().models)
    await refresh_models_from_db()

    # start_telegram_bot() is non-blocking: uses initialize/start/start_polling
    # internally and returns immediately. Do NOT wrap in create_task.
    from backend.telegram.bot import start_telegram_bot, stop_telegram_bot
    await start_telegram_bot()

    yield

    await stop_telegram_bot()
    await close_pool()      # no-op for SQLite


app = FastAPI(
    title="LocalForge",
    description="Local AI agent with filesystem, terminal and web search access",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS_ORIGINS env var: comma-separated list of allowed origins.
# In production behind nginx (same-origin), set to "*" or your domain.
# Default: localhost only (development).
_raw_origins = os.getenv("CORS_ORIGINS", "")
_cors_origins: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["http://localhost:5173", "http://127.0.0.1:5173",
          "http://localhost:3000", "http://127.0.0.1:3000"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(api_key_middleware)

app.include_router(chat_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(stats_router,  prefix="/api")


@app.get("/api/health")
async def health():
    from backend.db.connection import get_db, is_mysql
    db_type = "mysql" if is_mysql() else "sqlite"
    db_ok = False
    try:
        async with get_db() as db:
            await db.execute("SELECT 1")
            db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "version": "0.1.0", "db_ok": db_ok, "db_type": db_type}


# Serve frontend static build if it exists
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


def start():
    import uvicorn
    settings = get_settings()
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    start()
