"""
Anthropic (Claude) model adapter.
Uses the official anthropic SDK with streaming tool use.
"""
from __future__ import annotations

from typing import AsyncIterator, Any

from backend.models.base import BaseModelAdapter, StreamEvent


class AnthropicAdapter(BaseModelAdapter):
    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self._api_key = api_key

    async def stream_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str,
    ) -> AsyncIterator[StreamEvent]:
        import logging
        logger = logging.getLogger(__name__)

        try:
            import anthropic
        except ImportError:
            yield StreamEvent(type="error", data={"message": "anthropic package not installed"})
            return

        logger.info(f"AnthropicAdapter.stream_chat: model={self.model_name}, api_key_set={bool(self._api_key)}")

        if not self._api_key:
            logger.error("API key is empty!")
            yield StreamEvent(type="error", data={"message": "❌ API key vacía. Configura tu Anthropic API key en Settings → Providers → Anthropic"})
            return

        try:
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
        except Exception as e:
            logger.error(f"Failed to create Anthropic client: {e}")
            yield StreamEvent(type="error", data={"message": f"Failed to create Anthropic client: {e}"})
            return

        # Convert messages to Anthropic format
        anthropic_messages = _to_anthropic_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": 8096,
            "system": system,
            "messages": anthropic_messages,
        }
        if tools:
            kwargs["tools"] = tools

        logger.info(f"Sending to Anthropic: model={self.model_name} tools={len(tools)} msgs={len(messages)}")

        try:
            async with client.messages.stream(**kwargs) as stream:
                # Stream text deltas in real time
                async for text_chunk in stream.text_stream:
                    yield StreamEvent(type="text_delta", data={"text": text_chunk})

                # Get the complete final message (all tool calls fully parsed)
                final = await stream.get_final_message()
                block_summary = [(b.type, getattr(b, 'name', '')) for b in final.content]
                logger.info(
                    f"Final message: stop_reason={final.stop_reason} "
                    f"content_blocks={block_summary} usage={final.usage}"
                )

                # Emit tool calls from the final message
                for block in final.content:
                    if block.type == "tool_use":
                        logger.info(f"Tool call: {block.name} input={block.input}")
                        yield StreamEvent(
                            type="tool_call",
                            data={
                                "id": block.id,
                                "name": block.name,
                                "input": block.input,
                            },
                        )

                yield StreamEvent(type="done", data={"stop_reason": final.stop_reason})
                if final.usage:
                    yield StreamEvent(type="usage", data={
                        "input_tokens": final.usage.input_tokens,
                        "output_tokens": final.usage.output_tokens,
                    })
        except anthropic.AuthenticationError as e:
            logger.error(f"AuthenticationError: {e}")
            yield StreamEvent(type="error", data={"message": "🔐 API key inválida. Verifica tu Anthropic API key en Settings → Providers"})
        except anthropic.BadRequestError as e:
            msg = str(e)
            logger.error(f"BadRequestError: {e}")
            if "credit balance" in msg or "too low" in msg:
                yield StreamEvent(type="error", data={"message": "💳 Sin créditos en Anthropic. Ve a console.anthropic.com → Plans & Billing para recargar."})
            else:
                yield StreamEvent(type="error", data={"message": f"❌ Petición inválida: {msg[:200]}"})
        except anthropic.RateLimitError as e:
            msg = str(e)
            logger.error(f"RateLimitError: {e}")
            yield StreamEvent(type="error", data={"message": "⏱️ Rate limit alcanzado. Usa Sonnet en lugar de Opus (límites mucho más altos), o espera un minuto e inténtalo de nuevo."})
        except anthropic.NotFoundError as e:
            logger.error(f"NotFoundError (modelo no existe): {e}")
            yield StreamEvent(type="error", data={"message": f"❌ El modelo '{self.model_name}' no existe en Anthropic. Verifica el nombre exacto."})
        except anthropic.APIConnectionError as e:
            logger.error(f"APIConnectionError: {e}")
            yield StreamEvent(type="error", data={"message": f"🌐 Error de conexión con Anthropic API. ¿Tienes internet? Detalles: {str(e)[:100]}"})
        except Exception as e:
            logger.error(f"Unexpected error in Anthropic stream: {type(e).__name__}: {e}", exc_info=True)
            yield StreamEvent(type="error", data={"message": f"⚠️ Error: {str(e)[:200]}"})


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert internal message format to Anthropic API format."""
    result = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "tool":
            # Tool result — becomes a user message with tool_result blocks
            result.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_use_id", ""),
                    "content": str(content),
                }],
            })
        elif isinstance(content, list):
            result.append({"role": role, "content": content})
        else:
            result.append({"role": role, "content": str(content)})

    return result
