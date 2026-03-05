"""
Log viewer endpoints.

GET  /api/logs         — return the last N buffered log entries (JSON)
GET  /api/logs/stream  — SSE stream of new log entries as they arrive
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.logging_setup import get_buffer

router = APIRouter()


MAX_LOG_ENTRIES = 2_000


@router.get("/logs")
async def get_recent_logs(
    n:     int = Query(default=500, ge=1, le=MAX_LOG_ENTRIES),
    level: str = Query(default=""),
) -> list[dict]:
    entries = get_buffer().recent(n)
    if level:
        level_upper = level.upper()
        entries = [e for e in entries if e["level"] == level_upper]
    return entries


@router.get("/logs/stream")
async def stream_logs():
    """SSE stream — pushes each new log entry as a JSON data frame."""
    buf = get_buffer()

    async def generate():
        q = buf.subscribe()
        try:
            # Send a synthetic "connected" ping so the client knows the stream is live
            yield f"data: {json.dumps({'level': '__CONNECTED__', 'message': ''})}\n\n"
            while True:
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"    # SSE comment keeps connection alive
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            buf.unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",     # disable nginx buffering
        },
    )
