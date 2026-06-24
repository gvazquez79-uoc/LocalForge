"""
TodoList tool: lets the agent maintain a task checklist within a session.
The todo list lives in memory (per-conversation context var) so each
conversation has its own isolated list. The agent uses this to plan and
track multi-step coding tasks — equivalent to Claude Code's TodoWrite/TodoRead.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from backend.tools.base import BaseTool


# Per-async-task todo list (isolated per conversation, same as _conv_working_dir)
_todo_store: ContextVar[list[dict]] = ContextVar("_todo_store", default=[])


def _get_todos() -> list[dict]:
    return list(_todo_store.get())


def _set_todos(items: list[dict]) -> None:
    _todo_store.set(items)


def _render_todos(items: list[dict]) -> str:
    if not items:
        return "(lista vacía)"
    lines = []
    for i, item in enumerate(items):
        status = item.get("status", "pending")
        icon = {"pending": "⬜", "in_progress": "🔄", "done": "✅", "cancelled": "❌"}.get(status, "⬜")
        lines.append(f"{i+1}. {icon} [{status}] {item['task']}")
    return "\n".join(lines)


class TodoWriteTool(BaseTool):
    name = "todo_write"
    description = (
        "Create or completely replace the task list for the current session. "
        "Use this at the START of any multi-step task to plan your approach before coding. "
        "Each item should be a concrete, actionable step. "
        "Replace the entire list when you need to restructure the plan."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "Complete list of tasks to set (replaces existing list)",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Description of the task"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "done", "cancelled"],
                            "description": "Task status",
                            "default": "pending",
                        },
                    },
                    "required": ["task"],
                },
            },
        },
        "required": ["tasks"],
    }

    async def run(self, tasks: list[dict], **_: Any) -> str:
        normalized = [
            {"task": t["task"], "status": t.get("status", "pending")}
            for t in tasks
        ]
        _set_todos(normalized)
        return f"Lista de tareas actualizada ({len(normalized)} tareas):\n{_render_todos(normalized)}"


class TodoUpdateTool(BaseTool):
    name = "todo_update"
    description = (
        "Update the status of a specific task by its number (1-based). "
        "Call this as you complete each step so you always know what's left. "
        "Statuses: pending → in_progress → done (or cancelled)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_number": {"type": "integer", "description": "Task number (1-based index)"},
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "done", "cancelled"],
                "description": "New status for the task",
            },
        },
        "required": ["task_number", "status"],
    }

    async def run(self, task_number: int, status: str, **_: Any) -> str:
        items = _get_todos()
        idx = task_number - 1
        if idx < 0 or idx >= len(items):
            return f"Error: tarea #{task_number} no existe (hay {len(items)} tareas)"
        items[idx]["status"] = status
        _set_todos(items)
        return f"Tarea #{task_number} → {status}\n\n{_render_todos(items)}"


class TodoReadTool(BaseTool):
    name = "todo_read"
    description = (
        "Read the current task list to check what's pending, in progress, or done. "
        "Use this to stay oriented during long multi-step tasks."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def run(self, **_: Any) -> str:
        items = _get_todos()
        return _render_todos(items)


TODO_TOOLS: list[BaseTool] = [
    TodoWriteTool(),
    TodoUpdateTool(),
    TodoReadTool(),
]
