"""
In-memory log ring-buffer + custom handler.

All log records are captured in a deque (max MAX_ENTRIES) and broadcast
to any active SSE subscribers via per-client asyncio.Queues.

Usage:
  from backend.logging_setup import setup_logging
  setup_logging()          # call once, early in main.py

  from backend.logging_setup import get_buffer
  entries = get_buffer().recent(500)
  q = get_buffer().subscribe()   # asyncio.Queue fed by new records
  get_buffer().unsubscribe(q)
"""
from __future__ import annotations

import logging
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_ENTRIES = 2_000


class _RingBuffer:
    def __init__(self, maxlen: int) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._queues: list[Any] = []          # list[asyncio.Queue]

    def append(self, entry: dict[str, Any]) -> None:
        self._buf.append(entry)
        for q in list(self._queues):           # copy to avoid mutation during iteration
            try:
                q.put_nowait(entry)
            except Exception:
                pass                           # QueueFull or closed — drop silently

    def recent(self, n: int = 500) -> list[dict[str, Any]]:
        entries = list(self._buf)
        return entries[-n:] if n < len(entries) else entries

    def subscribe(self) -> Any:
        """Return an asyncio.Queue that will receive new log entries."""
        import asyncio
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: Any) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass


_buffer = _RingBuffer(MAX_ENTRIES)


class _BufferHandler(logging.Handler):
    """Logging handler that appends records to the global ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[0] is not None:
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
            elif record.exc_text:
                msg += "\n" + record.exc_text

            entry: dict[str, Any] = {
                "ts":      datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level":   record.levelname,
                "logger":  record.name,
                "message": msg,
            }
            _buffer.append(entry)
        except Exception:
            pass   # never let the logging system crash the app


def setup_logging(level: int = logging.DEBUG) -> None:
    """Install the buffer handler on the root logger.
    Safe to call multiple times (idempotent — won't add duplicate handlers)."""
    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, _BufferHandler):
            return   # already installed
    handler = _BufferHandler()
    handler.setLevel(level)
    root.addHandler(handler)
    root.setLevel(min(root.level or logging.DEBUG, level))


def get_buffer() -> _RingBuffer:
    return _buffer
