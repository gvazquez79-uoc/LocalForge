"""
OpenAI-compatible adapter.
Works with Ollama (http://localhost:11434/v1), OpenAI, and any compatible endpoint.
Compatible with openai SDK v2.x.

Handles multimodal content (image / PDF) stored in Anthropic-format blocks:
  {"type": "image",    "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}
  {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "..."}}

Images are converted to OpenAI image_url format.
PDFs are converted to extracted text (requires 'pypdf'; graceful fallback if missing).
"""
from __future__ import annotations

import json
from typing import AsyncIterator

from backend.models.base import BaseModelAdapter, StreamEvent


def _extract_pdf_text(b64_data: str) -> str:
    """Extract plain text from a base64-encoded PDF via pypdf."""
    try:
        import base64
        import io
        pdf_bytes = base64.b64decode(b64_data)
        try:
            from pypdf import PdfReader  # pip install pypdf
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            extracted = "\n\n".join(t for t in pages_text if t.strip())
            if extracted:
                return f"[Contenido del PDF extraído]\n{extracted}"
            return "[PDF adjunto: no se pudo extraer texto (PDF escaneado o protegido)]"
        except ImportError:
            return (
                "[PDF adjunto: para extracción de texto instala pypdf → "
                "`pip install pypdf`]"
            )
    except Exception as exc:
        return f"[PDF: error al procesar — {exc}]"


def _convert_content_for_openai(content: str | list) -> str | list:
    """
    Convert Anthropic-format content blocks to OpenAI-compatible format.

    Anthropic → OpenAI conversions:
      text     → {"type": "text", "text": "..."}
      image    → {"type": "image_url", "image_url": {"url": "data:mime;base64,..."}}
      document → extracted text block
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    result: list[dict] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "text":
            result.append({"type": "text", "text": block.get("text", "")})

        elif btype == "image":
            source = block.get("source", {})
            if source.get("type") == "base64":
                mime = source.get("media_type", "image/jpeg")
                data = source.get("data", "")
                result.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{data}"},
                })

        elif btype == "document":
            # PDFs – extract text for non-vision models
            source = block.get("source", {})
            if source.get("type") == "base64":
                extracted = _extract_pdf_text(source.get("data", ""))
                result.append({"type": "text", "text": extracted})

        elif btype == "tool_result":
            result.append({"type": "text", "text": str(block.get("content", ""))})

    if not result:
        return ""
    # If single plain-text block, return as string (better model compatibility)
    if len(result) == 1 and result[0].get("type") == "text":
        return result[0]["text"]
    return result


class OpenAICompatAdapter(BaseModelAdapter):
    def __init__(self, model_name: str, base_url: str, api_key: str = "ollama"):
        self.model_name = model_name
        self._base_url  = base_url
        self._api_key   = api_key

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            yield StreamEvent(type="error", data={"message": "openai package not installed"})
            return

        client = AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)

        # Build message list with system prompt prepended
        openai_messages: list[dict] = [{"role": "system", "content": system}]
        for msg in messages:
            if msg["role"] == "tool":
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_use_id", msg.get("tool_call_id", "")),
                    "content": str(msg["content"]),
                })
            else:
                converted = _convert_content_for_openai(msg["content"])
                openai_messages.append({"role": msg["role"], "content": converted})

        kwargs: dict = {
            "model":    self.model_name,
            "messages": openai_messages,
            "stream":   True,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            tool_calls_acc: dict[int, dict] = {}
            emitted_done = False

            # If the model doesn't support tools, retry once without them
            try:
                stream = await client.chat.completions.create(**kwargs)
            except Exception as e:
                if "does not support tools" in str(e).lower() and "tools" in kwargs:
                    kwargs.pop("tools")
                    stream = await client.chat.completions.create(**kwargs)
                else:
                    raise

            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta  = choice.delta

                if delta.content:
                    yield StreamEvent(type="text_delta", data={"text": delta.content})

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_acc[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                if choice.finish_reason == "tool_calls":
                    for tc in tool_calls_acc.values():
                        try:
                            tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield StreamEvent(
                            type="tool_call",
                            data={"id": tc["id"], "name": tc["name"], "input": tool_input},
                        )
                    tool_calls_acc = {}
                    yield StreamEvent(type="done", data={"stop_reason": "tool_calls"})
                    emitted_done = True

                elif choice.finish_reason in ("stop", "length", "end_turn"):
                    for tc in tool_calls_acc.values():
                        try:
                            tool_input = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except json.JSONDecodeError:
                            tool_input = {}
                        if tc["name"]:
                            yield StreamEvent(
                                type="tool_call",
                                data={"id": tc["id"], "name": tc["name"], "input": tool_input},
                            )
                    tool_calls_acc = {}
                    yield StreamEvent(type="done", data={"stop_reason": choice.finish_reason})
                    emitted_done = True

            if not emitted_done:
                yield StreamEvent(type="done", data={"stop_reason": "stop"})

        except Exception as e:
            yield StreamEvent(type="error", data={"message": str(e)})
