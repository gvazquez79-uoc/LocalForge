"""
Chat API router.
POST /conversations            — create conversation
GET  /conversations            — list all
GET  /conversations/{id}       — get with messages
DELETE /conversations/{id}     — delete
POST /conversations/{id}/chat  — send message (returns SSE stream)
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent.loop import run_agent
from backend.config import get_config
from backend.db.store import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_messages,
    list_conversations,
    update_conversation_title,
)
from backend.models.registry import get_adapter

router = APIRouter(prefix="/conversations", tags=["chat"])


class CreateConversationRequest(BaseModel):
    model: str | None = None
    title: str = "New conversation"


class SendMessageRequest(BaseModel):
    content: str
    model: str | None = None  # override model for this turn


@router.post("")
async def create_conv(body: CreateConversationRequest):
    cfg = get_config()
    model = body.model or cfg.default_model
    return await create_conversation(model=model, title=body.title)


@router.get("")
async def list_convs():
    return await list_conversations()


@router.get("/{conv_id}")
async def get_conv(conv_id: str):
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await get_messages(conv_id)
    return {**conv, "messages": messages}


@router.delete("/{conv_id}")
async def del_conv(conv_id: str):
    await delete_conversation(conv_id)
    return {"ok": True}


@router.patch("/{conv_id}/title")
async def rename_conv(conv_id: str, body: dict):
    title = body.get("title", "")
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    await update_conversation_title(conv_id, title)
    return {"ok": True}


@router.post("/{conv_id}/chat")
async def send_message(conv_id: str, body: SendMessageRequest):
    conv = await get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    cfg = get_config()
    model_name = body.model or conv["model"] or cfg.default_model

    # Persist user message
    await add_message(conv_id, "user", body.content)

    # Load full history
    stored = await get_messages(conv_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in stored
                if m["role"] in ("user", "assistant")]

    adapter = get_adapter(model_name)

    async def event_stream() -> AsyncIterator[str]:
        full_text = ""
        tool_events = []

        async for event in run_agent(messages, adapter):
            payload = json.dumps({"type": event.type, "data": event.data})
            yield f"data: {payload}\n\n"

            if event.type == "text_delta":
                full_text += event.data["text"]
            elif event.type == "tool_call":
                tool_events.append(event.data)

        # Persist assistant message
        if full_text:
            await add_message(
                conv_id,
                "assistant",
                full_text,
                metadata={"tool_calls": tool_events} if tool_events else None,
            )

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
