"""
LLM-based context compressor — ported from Hermes Agent's context_compressor.py
(NousResearch/hermes-agent, MIT License).

Key improvements over a simple truncation approach:
  - Informative 1-line summaries per tool type (no generic placeholders)
  - Deduplication of identical tool results (hash-based)
  - Token-budget tail protection (not just message count)
  - Boundary alignment: never splits tool_call/tool_result groups
  - Ensures last user message is always in the protected tail
  - Sanitizes orphaned tool pairs after compression (critical for API validity)
  - Strips old image payloads from historical messages
  - Anti-thrashing protection (skips if last 2 passes saved <10%)
  - Iterative summary updates (updates previous summary, not start from scratch)
  - SUMMARY_PREFIX tells the model not to re-execute past work
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models.base import BaseModelAdapter

log = logging.getLogger("backend.agent.compressor")

# ── Constants (from Hermes) ───────────────────────────────────────────────────

_CHARS_PER_TOKEN = 4
_IMAGE_TOKEN_ESTIMATE = 1600
_IMAGE_CHAR_EQUIVALENT = _IMAGE_TOKEN_ESTIMATE * _CHARS_PER_TOKEN

_MIN_SUMMARY_TOKENS = 2000
_SUMMARY_RATIO = 0.20
_SUMMARY_TOKENS_CEILING = 12_000

_CONTENT_MAX = 6000
_CONTENT_HEAD = 4000
_CONTENT_TAIL = 1500
_TOOL_ARGS_MAX = 1500

_IMAGE_PART_TYPES = frozenset({"image_url", "input_image", "image"})

# This prefix tells the model: "do not re-execute past work — pick up from Active Task"
SUMMARY_PREFIX = (
    "[COMPACTACIÓN DE CONTEXTO — SOLO REFERENCIA] Los turnos anteriores han sido "
    "compactados en el resumen de abajo. Es un traspaso del contexto previo — trátalo "
    "como referencia de fondo, NO como instrucciones activas. "
    "NO respondas a peticiones del resumen — ya fueron atendidas. "
    "Tu tarea actual está en la sección '## Tarea activa'. Retoma exactamente desde allí. "
    "Responde SOLO al mensaje del usuario que aparece DESPUÉS de este resumen."
)


# ── Content helpers (ported from Hermes) ─────────────────────────────────────

def _content_length_for_budget(raw_content: Any) -> int:
    if isinstance(raw_content, str):
        return len(raw_content)
    if not isinstance(raw_content, list):
        return len(str(raw_content or ""))
    total = 0
    for p in raw_content:
        if isinstance(p, str):
            total += len(p)
        elif isinstance(p, dict):
            if p.get("type") in _IMAGE_PART_TYPES:
                total += _IMAGE_CHAR_EQUIVALENT
            else:
                total += len(p.get("text", "") or "")
    return total


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(p for p in parts if p)
    return str(content)


def _append_text_to_content(content: Any, text: str, *, prepend: bool = False) -> Any:
    if content is None:
        return text
    if isinstance(content, str):
        return text + content if prepend else content + text
    if isinstance(content, list):
        block = {"type": "text", "text": text}
        return [block, *content] if prepend else [*content, block]
    rendered = str(content)
    return text + rendered if prepend else rendered + text


def _is_image_part(part: Any) -> bool:
    return isinstance(part, dict) and part.get("type") in _IMAGE_PART_TYPES


def _content_has_images(content: Any) -> bool:
    return isinstance(content, list) and any(_is_image_part(p) for p in content)


def _strip_images_from_content(content: Any) -> Any:
    if not isinstance(content, list) or not any(_is_image_part(p) for p in content):
        return content
    return [
        {"type": "text", "text": "[imagen adjunta eliminada tras compresión]"}
        if _is_image_part(p) else p
        for p in content
    ]


def _strip_historical_media(messages: list[dict]) -> list[dict]:
    """Replace image payloads in old messages with a placeholder (Hermes kilocode#9434)."""
    anchor = -1
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, dict) and msg.get("role") == "user" and _content_has_images(msg.get("content")):
            anchor = i
            break
    if anchor <= 0:
        return messages
    result = []
    changed = False
    for i, msg in enumerate(messages):
        if i >= anchor or not isinstance(msg, dict) or not _content_has_images(msg.get("content")):
            result.append(msg)
        else:
            new_msg = msg.copy()
            new_msg["content"] = _strip_images_from_content(msg.get("content"))
            result.append(new_msg)
            changed = True
    return result if changed else messages


def _truncate_tool_call_args_json(args: str, head_chars: int = 200) -> str:
    """Shrink long values inside a tool-call arguments JSON while preserving JSON validity."""
    try:
        parsed = json.loads(args)
    except (ValueError, TypeError):
        return args

    def _shrink(obj: Any) -> Any:
        if isinstance(obj, str):
            return obj[:head_chars] + "...[truncado]" if len(obj) > head_chars else obj
        if isinstance(obj, dict):
            return {k: _shrink(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_shrink(v) for v in obj]
        return obj

    return json.dumps(_shrink(parsed), ensure_ascii=False)


# ── 1-line tool result summaries (adapted from Hermes _summarize_tool_result) ─

def _one_liner(tool_name: str, tool_args_json: str, content: str) -> str:
    """Generate an informative 1-line summary of a completed tool call."""
    try:
        args = json.loads(tool_args_json) if tool_args_json else {}
    except (json.JSONDecodeError, TypeError):
        args = {}

    content = content or ""
    clen = len(content)
    lines = content.count("\n") + 1 if content.strip() else 0

    if tool_name == "read_file":
        path = args.get("path", "?")
        return f"[read_file] leyó `{path}` ({clen:,} chars)"

    if tool_name == "write_file":
        path = args.get("path", "?")
        written = (args.get("content") or "").count("\n") + 1 if args.get("content") else "?"
        return f"[write_file] escribió `{path}` ({written} líneas)"

    if tool_name == "edit_file":
        path = args.get("path", "?")
        old = (args.get("old_string") or "")[:50].replace("\n", "↵")
        return f"[edit_file] editó `{path}` → «{old}…»"

    if tool_name == "execute_command":
        cmd = (args.get("command") or "")[:70]
        exit_m = re.search(r"[Ee]xit\s+(?:code:?\s*)?(-?\d+)", content)
        code = exit_m.group(1) if exit_m else "?"
        return f"[execute_command] `{cmd}` → exit {code}, {lines} líneas"

    if tool_name == "list_directory":
        return f"[list_directory] `{args.get('path','?')}` ({lines} entradas)"

    if tool_name == "glob":
        n = len([l for l in content.splitlines() if l.strip()])
        return f"[glob] `{args.get('pattern','?')}` → {n} archivos"

    if tool_name == "grep":
        n = len([l for l in content.splitlines() if l.strip()])
        return f"[grep] `{args.get('pattern','?')}` → {n} coincidencias"

    if tool_name == "search_files":
        return f"[search_files] `{args.get('pattern','?')}` → {clen:,} chars"

    if tool_name in ("git_status", "git_diff", "git_log", "git_add",
                     "git_commit", "git_checkout", "git_branch", "git_pull", "git_push"):
        short = content[:100].replace("\n", " ").strip()
        return f"[{tool_name}] {short}"

    if tool_name == "web_search":
        return f"[web_search] «{args.get('query','?')[:50]}» → {clen:,} chars"

    if tool_name == "web_fetch":
        return f"[web_fetch] {(args.get('url') or '')[:60]} → {clen:,} chars"

    if tool_name in ("todo_write", "todo_update", "todo_read"):
        short = content[:80].replace("\n", " ").strip()
        return f"[{tool_name}] {short}"

    if tool_name in ("delete_file", "delete_directory"):
        return f"[{tool_name}] eliminó `{args.get('path','?')}`"

    # Fallback
    short = content[:80].replace("\n", " ").strip()
    return f"[{tool_name}] {short} ({clen:,} chars)"


# ── Tool-call ID helpers ──────────────────────────────────────────────────────

def _get_tool_call_id(tc: Any) -> str:
    if isinstance(tc, dict):
        return tc.get("call_id", "") or tc.get("id", "") or ""
    return getattr(tc, "call_id", "") or getattr(tc, "id", "") or ""


def _estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += _content_length_for_budget(m.get("content") or "") // _CHARS_PER_TOKEN + 10
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                total += len(tc.get("function", {}).get("arguments", "")) // _CHARS_PER_TOKEN
    return total


# ── Main compressor class ─────────────────────────────────────────────────────

class ContextCompressor:
    """
    LLM-based context compressor ported from Hermes Agent.

    Phases:
      1. Prune old tool results → 1-line summaries + dedup + truncate args
      2. Protect head (first N messages) + tail (token budget)
      3. LLM summarization of the middle (structured template)
      4. Assemble: head + [summary] + tail
      5. Sanitize orphaned tool pairs
      6. Strip historical image payloads
    """

    def __init__(
        self,
        adapter: "BaseModelAdapter",
        protect_first_n: int = 3,
        protect_last_n: int = 20,
        tail_token_budget: int = 20_000,
    ):
        self.adapter = adapter
        self.protect_first_n = protect_first_n
        self.protect_last_n = protect_last_n
        self.tail_token_budget = tail_token_budget

        self._previous_summary: str | None = None
        self._last_compression_savings_pct: float = 100.0
        self._ineffective_compression_count: int = 0
        self._summary_failure_cooldown_until: float = 0.0
        self.compression_count: int = 0

    # ── Phase 1: prune tool results ───────────────────────────────────────────

    def _prune_old_tool_results(
        self,
        messages: list[dict],
        protect_tail_tokens: int,
        protect_tail_count: int,
    ) -> tuple[list[dict], int]:
        """Replace old tool results with 1-liners; dedup identical results; truncate args."""
        if not messages:
            return messages, 0

        result = [m.copy() for m in messages]
        pruned = 0

        # Build index: tool_call_id → (name, args_json)
        call_id_to_tool: dict[str, tuple] = {}
        for msg in result:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        cid = _get_tool_call_id(tc)
                        fn = tc.get("function", {})
                        call_id_to_tool[cid] = (fn.get("name", "unknown"), fn.get("arguments", ""))

        # Determine prune boundary via token budget
        accumulated = 0
        min_protect = min(protect_tail_count, len(result))
        boundary = len(result)
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            msg_tokens = _content_length_for_budget(msg.get("content") or "") // _CHARS_PER_TOKEN + 10
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    msg_tokens += len(tc.get("function", {}).get("arguments", "")) // _CHARS_PER_TOKEN
            if accumulated + msg_tokens > protect_tail_tokens and (len(result) - i) >= min_protect:
                boundary = i
                break
            accumulated += msg_tokens
            boundary = i

        budget_protect = len(result) - boundary
        protected = max(budget_protect, min_protect)
        prune_boundary = len(result) - protected

        # Pass 1: Dedup identical tool results (keep newest, back-ref older)
        content_hashes: dict = {}
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content") or ""
            if not isinstance(content, str) or len(content) < 200:
                continue
            h = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
            if h in content_hashes:
                result[i] = {**msg, "content": "[Resultado duplicado — mismo contenido que una llamada más reciente]"}
                pruned += 1
            else:
                content_hashes[h] = i

        # Pass 2: Replace old tool results with 1-liners
        for i in range(prune_boundary):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str) or not content or len(content) <= 200:
                continue
            if content.startswith("[Resultado duplicado"):
                continue
            call_id = msg.get("tool_call_id", "") or msg.get("tool_use_id", "")
            tool_name, tool_args = call_id_to_tool.get(call_id, ("unknown", ""))
            result[i] = {**msg, "content": _one_liner(tool_name, tool_args, content)}
            pruned += 1

        # Pass 3: Truncate large tool_call args in assistant messages (keep JSON valid)
        for i in range(prune_boundary):
            msg = result[i]
            if msg.get("role") != "assistant" or not msg.get("tool_calls"):
                continue
            new_tcs = []
            modified = False
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict):
                    args = tc.get("function", {}).get("arguments", "")
                    if len(args) > 500:
                        new_args = _truncate_tool_call_args_json(args)
                        if new_args != args:
                            tc = {**tc, "function": {**tc["function"], "arguments": new_args}}
                            modified = True
                new_tcs.append(tc)
            if modified:
                result[i] = {**msg, "tool_calls": new_tcs}

        return result, pruned

    # ── Boundary helpers (ported from Hermes) ─────────────────────────────────

    def _head_size(self, messages: list[dict]) -> int:
        head = 1 if messages and messages[0].get("role") == "system" else 0
        return head + self.protect_first_n

    def _align_forward(self, messages: list[dict], idx: int) -> int:
        """Slide forward past any orphan tool results."""
        while idx < len(messages) and messages[idx].get("role") == "tool":
            idx += 1
        return idx

    def _align_backward(self, messages: list[dict], idx: int) -> int:
        """Pull backward to avoid splitting a tool_call/result group."""
        if idx <= 0 or idx >= len(messages):
            return idx
        check = idx - 1
        while check >= 0 and messages[check].get("role") == "tool":
            check -= 1
        if check >= 0 and messages[check].get("role") == "assistant" and messages[check].get("tool_calls"):
            idx = check
        return idx

    def _find_tail_cut(self, messages: list[dict], head_end: int) -> int:
        """Walk backward accumulating tokens until tail_token_budget is reached."""
        n = len(messages)
        min_tail = min(3, n - head_end - 1) if n - head_end > 1 else 0
        soft_ceiling = int(self.tail_token_budget * 1.5)
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, head_end - 1, -1):
            msg = messages[i]
            msg_tokens = _content_length_for_budget(msg.get("content") or "") // _CHARS_PER_TOKEN + 10
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    msg_tokens += len(tc.get("function", {}).get("arguments", "")) // _CHARS_PER_TOKEN
            if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        fallback = n - min_tail
        cut_idx = min(cut_idx, fallback)
        if cut_idx <= head_end:
            cut_idx = max(fallback, head_end + 1)

        cut_idx = self._align_backward(messages, cut_idx)

        # Ensure the most recent user message is always in the tail (Hermes #10896)
        last_user = -1
        for i in range(n - 1, head_end - 1, -1):
            if messages[i].get("role") == "user":
                last_user = i
                break
        if 0 <= last_user < cut_idx:
            cut_idx = max(last_user, head_end + 1)

        return max(cut_idx, head_end + 1)

    # ── Phase 5: sanitize orphaned tool pairs ─────────────────────────────────

    def _sanitize_tool_pairs(self, messages: list[dict]) -> list[dict]:
        """Fix orphaned tool_call/tool_result pairs after compression.

        Without this, the API returns errors like:
          "No tool call found for function call output with call_id ..."
        """
        surviving_call_ids: set = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    cid = _get_tool_call_id(tc)
                    if cid:
                        surviving_call_ids.add(cid)

        result_call_ids: set = set()
        for msg in messages:
            if msg.get("role") == "tool":
                cid = msg.get("tool_call_id") or msg.get("tool_use_id")
                if cid:
                    result_call_ids.add(cid)

        # Remove tool results whose call has been summarized away
        orphaned_results = result_call_ids - surviving_call_ids
        if orphaned_results:
            messages = [
                m for m in messages
                if not (m.get("role") == "tool" and
                        (m.get("tool_call_id") or m.get("tool_use_id")) in orphaned_results)
            ]
            log.info(f"[compressor] removed {len(orphaned_results)} orphaned tool result(s)")

        # Add stub results for calls whose results were dropped
        missing_results = surviving_call_ids - result_call_ids
        if missing_results:
            patched = []
            for msg in messages:
                patched.append(msg)
                if msg.get("role") == "assistant":
                    for tc in msg.get("tool_calls") or []:
                        cid = _get_tool_call_id(tc)
                        if cid in missing_results:
                            patched.append({
                                "role": "tool",
                                "content": "[Resultado de la conversación anterior — ver resumen de contexto]",
                                "tool_call_id": cid,
                            })
            messages = patched
            log.info(f"[compressor] added {len(missing_results)} stub tool result(s)")

        return messages

    # ── Phase 3: LLM summarization ────────────────────────────────────────────

    _SUMMARIZER_PREAMBLE = (
        "Eres un agente de resumen creando un checkpoint de contexto. "
        "Trata los turnos de conversación de abajo como material fuente para un "
        "registro compacto del trabajo previo. "
        "Produce SOLO el resumen estructurado; no añadas saludo, preámbulo ni prefijo. "
        "Escribe el resumen en el mismo idioma que usaba el usuario — no traduzcas. "
        "NUNCA incluyas claves API, tokens, contraseñas ni credenciales — reemplázalos con [REDACTED]."
    )

    _TEMPLATE_SECTIONS = """\
## Tarea activa
[EL CAMPO MÁS IMPORTANTE. Copia la petición más reciente del usuario que AÚN no se ha completado — \
las palabras exactas. Si hay varias tareas y algunas están hechas, lista solo las que FALTAN. \
La continuación debe retomar exactamente aquí. Si no hay tarea pendiente, escribe "Ninguna."]

## Objetivo
[Qué intenta conseguir el usuario en general]

## Restricciones y preferencias
[Preferencias del usuario, estilo de código, restricciones, decisiones importantes]

## Acciones completadas
[Lista numerada de acciones concretas — incluye herramienta, objetivo y resultado.
Formato: N. ACCIÓN objetivo — resultado [herramienta: nombre]
Sé específico con rutas, comandos, números de línea y resultados.]

## Estado actual
[Estado de trabajo actual:
- Directorio de trabajo y rama (si aplica)
- Archivos modificados/creados con nota breve
- Estado de tests (X/Y pasando)
- Procesos o servidores en ejecución
- Detalles de entorno relevantes]

## En progreso
[Trabajo en curso cuando se activó la compresión]

## Bloqueado
[Errores o problemas no resueltos. Incluye mensajes de error exactos.]

## Decisiones clave
[Decisiones técnicas importantes y POR QUÉ se tomaron]

## Preguntas resueltas
[Preguntas del usuario ya respondidas — incluye la respuesta para no repetirla]

## Peticiones pendientes
[Peticiones del usuario que NO han sido atendidas. Si ninguna, escribe "Ninguna."]

## Archivos relevantes
[Archivos leídos, modificados o creados — con nota breve sobre cada uno]

## Trabajo pendiente
[Qué queda por hacer — como contexto, no como instrucciones]

## Contexto crítico
[Valores concretos, mensajes de error, detalles de configuración o datos que se perderían \
sin preservación explícita. NUNCA incluyas claves API, tokens o credenciales — usa [REDACTED].]"""

    def _serialize_for_summary(self, turns: list[dict]) -> str:
        parts = []
        for msg in turns:
            role = msg.get("role", "unknown")
            content = _content_text(msg.get("content") or "")

            if role == "tool":
                tool_id = msg.get("tool_call_id", "") or msg.get("tool_use_id", "")
                if len(content) > _CONTENT_MAX:
                    content = content[:_CONTENT_HEAD] + "\n...[truncado]...\n" + content[-_CONTENT_TAIL:]
                parts.append(f"[RESULTADO HERRAMIENTA {tool_id}]: {content}")
                continue

            if role == "assistant":
                if len(content) > _CONTENT_MAX:
                    content = content[:_CONTENT_HEAD] + "\n...[truncado]...\n" + content[-_CONTENT_TAIL:]
                tool_calls = msg.get("tool_calls", [])
                # Anthropic-style tool_use blocks
                raw_content = msg.get("content")
                if isinstance(raw_content, list):
                    for b in raw_content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tool_calls = tool_calls + [{"function": {"name": b.get("name"), "arguments": json.dumps(b.get("input", {}))}}]
                if tool_calls:
                    tc_parts = []
                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name", "?")
                            args = fn.get("arguments", "")
                            if len(args) > _TOOL_ARGS_MAX:
                                args = args[:_TOOL_ARGS_MAX] + "..."
                            tc_parts.append(f"  {name}({args})")
                    content += "\n[Llamadas: " + ", ".join(tc_parts) + "]"
                parts.append(f"[ASISTENTE]: {content}")
                continue

            if len(content) > _CONTENT_MAX:
                content = content[:_CONTENT_HEAD] + "\n...[truncado]...\n" + content[-_CONTENT_TAIL:]
            # Skip internal system corrections
            if content.startswith("[SISTEMA]") or content.startswith("[SYSTEM]"):
                continue
            parts.append(f"[{role.upper()}]: {content}")

        return "\n\n".join(parts)

    async def _call_model(self, prompt: str) -> str:
        """Single non-tool call to the adapter; returns assistant text."""
        messages = [{"role": "user", "content": prompt}]
        text = ""
        async for event in self.adapter.stream_chat(messages, [], ""):
            if event.type == "text_delta":
                text += event.data.get("text", "")
            elif event.type == "error":
                raise RuntimeError(event.data.get("message", "LLM error during compression"))
        return text.strip()

    async def _generate_summary(self, turns: list[dict]) -> str | None:
        now = time.monotonic()
        if now < self._summary_failure_cooldown_until:
            log.debug(f"[compressor] in cooldown ({self._summary_failure_cooldown_until - now:.0f}s left)")
            return None

        content_to_summarize = self._serialize_for_summary(turns)
        # Scale budget with content size
        content_tokens = len(content_to_summarize) // _CHARS_PER_TOKEN
        summary_budget = max(_MIN_SUMMARY_TOKENS, min(int(content_tokens * _SUMMARY_RATIO), _SUMMARY_TOKENS_CEILING))

        template = self._TEMPLATE_SECTIONS + f"\n\nObjetivo: ~{summary_budget} tokens. Sé CONCRETO — rutas exactas, salidas de comandos, mensajes de error, números de línea. Evita descripciones vagas.\n\nEscribe solo el cuerpo del resumen. Sin preámbulos."

        if self._previous_summary:
            prompt = (
                f"{self._SUMMARIZER_PREAMBLE}\n\n"
                f"Estás actualizando un resumen de compresión de contexto. Hay un resumen previo y nuevos turnos que incorporar.\n\n"
                f"RESUMEN PREVIO:\n{self._previous_summary}\n\n"
                f"NUEVOS TURNOS A INCORPORAR:\n{content_to_summarize}\n\n"
                f"Actualiza el resumen con la misma estructura. PRESERVA toda la información aún relevante. "
                f"AÑADE nuevas acciones a la lista numerada. Mueve elementos de 'En progreso' a 'Acciones completadas' cuando terminen. "
                f"Actualiza 'Tarea activa' con la petición más reciente sin completar.\n\n"
                f"{template}"
            )
        else:
            prompt = (
                f"{self._SUMMARIZER_PREAMBLE}\n\n"
                f"Crea un resumen checkpoint estructurado para la conversación tras compactar los turnos anteriores.\n\n"
                f"TURNOS A RESUMIR:\n{content_to_summarize}\n\n"
                f"Usa esta estructura exacta:\n\n"
                f"{template}"
            )

        try:
            summary = await self._call_model(prompt)
            self._previous_summary = summary
            self._summary_failure_cooldown_until = 0.0
            return f"{SUMMARY_PREFIX}\n{summary}"
        except Exception as e:
            log.warning(f"[compressor] summary generation failed: {e}")
            self._summary_failure_cooldown_until = time.monotonic() + 60
            return None

    # ── Main entry point ──────────────────────────────────────────────────────

    async def compress(
        self,
        messages: list[dict],
        threshold: int = 80_000,
    ) -> tuple[list[dict], bool]:
        """Compress if total chars exceed threshold. Returns (messages, did_compress)."""
        total_chars = sum(_content_length_for_budget(m.get("content") or "") for m in messages)
        if total_chars <= threshold:
            return messages, False

        # Anti-thrashing: skip if last 2 passes saved <10% each
        if self._ineffective_compression_count >= 2:
            log.warning("[compressor] skipping — last 2 passes were ineffective (<10% savings)")
            return messages, False

        log.info(f"[compressor] triggered — {total_chars:,} chars > {threshold:,}")

        n = len(messages)
        display_tokens = _estimate_tokens(messages)

        # Phase 1: prune old tool results
        messages, pruned = self._prune_old_tool_results(
            messages,
            protect_tail_tokens=self.tail_token_budget,
            protect_tail_count=self.protect_last_n,
        )
        log.info(f"[compressor] phase1: pruned {pruned} tool results")

        # Phase 2: determine boundaries
        head_end = self._head_size(messages)
        compress_start = self._align_forward(messages, head_end)
        compress_end = self._find_tail_cut(messages, compress_start)

        if compress_start >= compress_end:
            log.info("[compressor] nothing to summarize after boundary alignment")
            return messages, True

        turns = messages[compress_start:compress_end]
        log.info(f"[compressor] summarizing turns {compress_start}–{compress_end} ({len(turns)} msgs), protecting {compress_start} head + {n - compress_end} tail")

        # Phase 3: LLM summarization
        summary = await self._generate_summary(turns)

        if not summary:
            log.warning("[compressor] LLM failed — inserting static fallback placeholder")
            n_dropped = compress_end - compress_start
            summary = (
                f"{SUMMARY_PREFIX}\n"
                f"El resumen no estaba disponible. Se eliminaron {n_dropped} mensajes para liberar contexto "
                f"pero no pudieron ser resumidos. Continúa basándote en los mensajes recientes."
            )

        # Phase 4: assemble
        last_head_role = messages[compress_start - 1].get("role", "user") if compress_start > 0 else "user"
        first_tail_role = messages[compress_end].get("role", "user") if compress_end < len(messages) else "user"

        merge_into_tail = False
        if last_head_role in {"assistant", "tool"}:
            summary_role = "user"
        else:
            summary_role = "assistant"

        if summary_role == first_tail_role:
            flipped = "assistant" if summary_role == "user" else "user"
            if flipped != last_head_role:
                summary_role = flipped
            else:
                merge_into_tail = True

        if not merge_into_tail and summary_role == "user":
            summary += "\n\n--- FIN DEL RESUMEN DE CONTEXTO — responde al mensaje de abajo, no al resumen ---"

        compressed = list(messages[:compress_start])
        if not merge_into_tail:
            compressed.append({"role": summary_role, "content": summary})

        for i in range(compress_end, len(messages)):
            msg = messages[i].copy()
            if merge_into_tail and i == compress_end:
                prefix = summary + "\n\n--- FIN DEL RESUMEN DE CONTEXTO — responde al mensaje de abajo ---\n\n"
                msg["content"] = _append_text_to_content(msg.get("content"), prefix, prepend=True)
                merge_into_tail = False
            compressed.append(msg)

        self.compression_count += 1

        # Phase 5: fix orphaned tool pairs
        compressed = self._sanitize_tool_pairs(compressed)

        # Phase 6: strip old image payloads
        compressed = _strip_historical_media(compressed)

        new_tokens = _estimate_tokens(compressed)
        saved_pct = (1 - new_tokens / max(display_tokens, 1)) * 100
        self._last_compression_savings_pct = saved_pct
        if saved_pct < 10:
            self._ineffective_compression_count += 1
        else:
            self._ineffective_compression_count = 0

        log.info(f"[compressor] done: {n} → {len(compressed)} msgs, ~{saved_pct:.0f}% reduction (compression #{self.compression_count})")
        return compressed, True
