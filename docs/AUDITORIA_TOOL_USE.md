# Auditoría: comunicación plataforma ↔ modelos (tool use)

Fecha: 2026-06-23
Rama: `luamodel/v4.2`
Alcance: flujo de tools entre el agente y los modelos Anthropic, OpenAI-compat y Ollama.

Archivos revisados:
- `backend/agent/loop.py` — loop multi-turno con SSE
- `backend/models/anthropic.py` — adaptador Claude (SDK nativo)
- `backend/models/openai_compat.py` — adaptador OpenAI/Groq/OpenRouter/etc.
- `backend/models/ollama_native.py` — adaptador Ollama `/api/chat`
- `backend/models/registry.py` — selección de adaptador
- `backend/routers/chat.py` — endpoint SSE y aprobación de tools
- `backend/tools/*` — terminal, filesystem, git, todo

---

## Resumen de hallazgos

| # | Severidad | Problema | Estado |
|---|-----------|----------|--------|
| 1 | 🔴 Crítico | Anthropic: varios `tool_use` en un turno → mensajes `user` consecutivos → 400 de la API | ✅ |
| 2 | 🔴 Crítico | Ollama: sin `num_ctx` → se trunca el system prompt (default 2048) | ✅ |
| 3 | 🟠 Alto | Temperatura por modelo ignorada en Ollama | ✅ |
| 4 | 🟠 Alto | Detección de comando fallido rota por mayúsculas + falsos positivos | ✅ |
| 5 | 🟠 Alto | Inline tool-call (XML) parsea todos los parámetros como string | ✅ |
| 6 | 🟠 Alto | openai_compat: sin `max_tokens` y `stream_options` siempre activo | ✅ |
| 7 | 🟡 Medio | Patrones de alucinación demasiado amplios → falsos positivos | ✅ |
| 8 | 🟡 Medio | Ollama retry-sin-tools duplica texto ya emitido | ✅ |
| 9 | 🟡 Medio | `finish_reason == "length"` tratado como parada limpia | ✅ |
| 10 | 🟡 Medio | Mensajes assistant vacíos pueden ser rechazados | ✅ |

---

## Detalle

### 1. 🔴 Anthropic: tool_result en mensajes `user` consecutivos
**Archivo:** `backend/agent/loop.py` (append de tool results), `backend/models/anthropic.py` (`_to_anthropic_messages`).

Cada resultado de tool se añadía como un mensaje `{"role":"tool"}` independiente, y cada uno se convertía en un mensaje `user` separado. Cuando Claude emite varios `tool_use` en un mismo turno (paralelo), se generan dos mensajes `user` seguidos, que la API rechaza (`roles must alternate` / `tool_use ids without tool_result`).

**Fix:** en `_to_anthropic_messages`, fusionar bloques `tool_result` consecutivos en un único mensaje `user`.

### 2. 🔴 Ollama: contexto truncado por `num_ctx` por defecto
**Archivo:** `backend/models/ollama_native.py`.

Ollama usa `num_ctx=2048` por defecto. Con system prompt grande + memoria + árbol del proyecto, el principio del contexto (instrucciones de uso de tools) se descarta silenciosamente, causando alucinaciones y "olvido" de capacidades.

**Fix:** pasar `options={"num_ctx": ...}` configurable (default 8192) en `client.chat`.

### 3. 🟠 Temperatura por modelo ignorada en Ollama
**Archivo:** `backend/models/ollama_native.py`, `backend/agent/loop.py`.

El loop hace `adapter.temperature = matched.temperature` pero el adaptador Ollama nunca lo leía ni lo enviaba.

**Fix:** añadir `self.temperature` y pasar `options.temperature`.

### 4. 🟠 Detección de comando fallido rota
**Archivo:** `backend/agent/loop.py`, `backend/tools/terminal.py`.

La terminal devuelve `"Exit code: 0"` (mayúscula) pero el loop comparaba el literal minúsculo `"exit code"`, por lo que nunca coincidía; además `"error:" in result[:200]` daba falsos positivos en comandos exitosos.

**Fix:** parsear el exit code real con regex en lugar de subcadenas.

### 5. 🟠 Inline tool-call (Formato B XML) parsea todo como string
**Archivo:** `backend/agent/loop.py` (`_parse_inline_tool_calls`).

Los `<parameter=...>` se guardaban siempre como string → herramientas que esperan int/bool fallan (`todo_update`, `git_log`).

**Fix:** coerción de valores (intento de `json.loads` por valor).

### 6. 🟠 openai_compat: sin `max_tokens`, `stream_options` siempre activo
**Archivo:** `backend/models/openai_compat.py`.

Sin `max_tokens` algunos servidores locales truncan; `stream_options` siempre enviado puede ser rechazado por servidores que no lo soportan.

**Fix:** fijar `max_tokens` y enviar `stream_options` con tolerancia a fallo (reintento sin él).

### 7. 🟡 Patrones de alucinación demasiado amplios
**Archivo:** `backend/agent/loop.py` (`_HALLUCINATION_PATTERNS`).

Frases genéricas (`"listo."`, `"done."`, `"i've created"`) disparan `clear_content` en respuestas conversacionales legítimas.

**Fix:** eliminar los patrones más ambiguos que causan falsos positivos.

### 8. 🟡 Ollama retry-sin-tools duplica texto
**Archivo:** `backend/models/ollama_native.py`.

Si falla a mitad del stream tras emitir texto, el retry reemite desde cero.

**Fix:** emitir `clear_content` antes de reintentar.

### 9. 🟡 `finish_reason == "length"` tratado como parada limpia
**Archivo:** `backend/models/openai_compat.py`.

Salidas truncadas (incluido JSON de tool-call cortado) se aceptan sin avisar.

**Fix:** emitir warning cuando `finish_reason == "length"`.

### 10. 🟡 Mensajes assistant vacíos
**Archivo:** `backend/agent/loop.py`.

`content=[]` (Anthropic) o `None` (OpenAI) sin tool_calls pueden ser rechazados.

**Fix:** no añadir el mensaje assistant cuando no hay ni texto ni tool_calls.
