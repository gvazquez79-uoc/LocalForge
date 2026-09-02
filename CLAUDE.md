# CLAUDE.md — Contexto de LocalForge

Agente de IA local (estilo Claude Code) con acceso a filesystem, terminal, git y web.
Backend FastAPI + frontend React + app móvil Ionic. Repo: `gvazquez79-uoc/LocalForge`.

> Este fichero lo lee Claude Code **y** el propio agente de LocalForge: `run_agent()` busca
> `LOCALFORGE.md` → `localforge.md` → `CLAUDE.md` → `.claude.md` en el working directory y lo
> inyecta en el system prompt (`_load_project_instructions()` en `backend/agent/loop.py`).

---

## Comandos

```bash
py -3 -m uvicorn backend.main:app --reload --port 8000
```

```bash
cd frontend && npm run dev
```

```bash
cd frontend && npm run build
```

En Windows, `start.bat` mata los procesos previos en 8000/5173 y arranca ambos.

URLs: backend `:8000` · Swagger `:8000/docs` · visor de logs `/logs`.

⚠️ **El puerto del frontend en dev es 3000**, no 5173: `frontend/vite.config.ts` fija
`server.port = 3000`. El README, `DEPLOY.md` y `start.bat` siguen diciendo 5173. Funciona porque
la lista CORS por defecto incluye ambos. No hay proxy `/api` en Vite: el frontend habla con
`localhost:8000` directamente.

**Build de producción:** siempre con `VITE_API_BASE` apuntando al dominio real
(`VITE_API_BASE=https://dominio/api npm run build`). Sin esa variable el bundle apunta a
`http://localhost:8000/api` y no funciona en el servidor.

```bash
py -3 -m pytest backend/tests/
```

Entorno local: Python 3.13.2 · Node 22.13 · npm 10.9. No hay `uv`; se usa `py -3` + pip.

**Banco de invariantes** en `backend/tests/` (pytest + pytest-asyncio, `asyncio_mode=auto` en
`pytest.ini`). No busca cobertura: fija los contratos que ya se rompieron en silencio alguna vez
—emparejamiento tool_use/tool_result, validación de argumentos, preservación de indentación y
finales de línea—. `conftest.py` trae un `FakeAdapter` programable y un `ScriptedTool`, e inyecta
tools por `extra_tools` de `run_agent`. Al tocar el loop, los adaptadores o las tools de
filesystem, **ejecútalo**. El frontend web no tiene tests; `LocalForge-App` tiene vitest y cypress
configurados pero solo con el test de scaffold.

---

## Arquitectura

```
backend/
  main.py              lifespan (orden crítico) + CORS + middleware auth + routers
  config.py            modelos Pydantic de config; get_config(); refresh_*_from_db()
  auth.py              JWT (python-jose HS256), bcrypt, get_current_user / require_admin
  email.py             smtplib para el reset de contraseña
  logging_setup.py     ring buffer en memoria (2000 entradas) + fan-out a suscriptores SSE
  agent/loop.py        run_agent(): loop multi-turno, tools, alucinaciones, tool calls inline
  agent/compressor.py  ContextCompressor (port de Hermes Agent, MIT) — resumen vía LLM
  models/              anthropic · openai_compat · ollama_native · copilot + registry
  tools/               filesystem git_tools todo_tool terminal web_search web_fetch video replicate
  routers/             chat config models providers permissions logs stats update auth users github_copilot
  db/                  connection.py (abstracción SQLite/MySQL) + un *_store.py por tabla
  middleware/auth.py   middleware HTTP global de autenticación
  telegram/bot.py      bot (python-telegram-bot v22), arranque no bloqueante
frontend/src/          React 19 + Vite 7 + Tailwind 3 + Zustand 5 + lucide-react
LocalForge-App/        app Ionic React 8 + Capacitor 8 (Android/iOS)
```

### Orden de arranque (lifespan de `main.py`) — no reordenar

1. `load_config()` — lee `localforge.json` (semilla)
2. `init_pool()` (no-op en SQLite) → `init_db()`
3. `init_settings_table()` → `refresh_config_from_db()` — siembra la BD desde el JSON la 1ª vez
4. Migración de system prompt: si contiene un marcador legacy, se reemplaza por el default actual
5. `init_providers_table()` → `seed_providers()` → `refresh_providers_cache()`
6. `init_permissions_table()` → `init_users_table()`
7. `init_models_table()` → `seed_from_config()` → `refresh_models_from_db()`
   — va **después** del paso 3 a propósito: los modelos de la BD ganan a los del JSON
8. `start_telegram_bot()` — ya es no bloqueante (`initialize` + `start` + `start_polling`);
   **no** envolver en `create_task` ni usar `run_polling()`

### Flujo de configuración

`localforge.json` es **solo semilla del primer arranque**. A partir de ahí la BD manda (tabla
`settings`, clave `app_config`, blob JSON). Editar el JSON después no tiene ningún efecto.

- `PUT /api/config` → `save_config_to_db()` (guarda todo menos `models`)
- Modelos y providers tienen tabla y endpoints CRUD propios
- Tras cualquier CRUD hay que llamar a `refresh_models_from_db()` / `refresh_providers_cache()`,
  o la config en memoria queda desincronizada
- `.env` gana sobre la config almacenada **solo** para SMTP (`get_smtp_config()` mira
  `settings.model_fields_set`, es decir solo lo declarado explícitamente en el entorno)

### Base de datos

`backend/db/connection.py` abstrae SQLite (default, `./localforge.db`) y MySQL
(`DATABASE_URL=mysql://...`). Si el pool MySQL falla al crearse, cae a SQLite en silencio.

```python
async with get_db() as db:
    cursor = await db.execute("SELECT * FROM t WHERE id = ?", (x,))
    row = await cursor.fetchone()
    await db.commit()
```

Reglas al tocar esquemas (compatibilidad SQLite + MySQL):

- El `_Wrapper` convierte `?` → `%s` para MySQL: escribe siempre `?`
- `VARCHAR(36) PRIMARY KEY`, nunca `TEXT` como PK
- Nada de `FOREIGN KEY ... ON DELETE CASCADE` fuera de `conversations`/`messages`
- `UNIQUE` inline, no sintaxis `UNIQUE KEY`
- Migraciones = `ALTER TABLE ... ADD COLUMN` dentro de `try/except: pass` (idempotentes)
- En MySQL se hace commit siempre al salir del contexto **a propósito**: con REPEATABLE READ, una
  conexión reutilizada del pool mantendría el snapshot de su primera lectura y no vería filas
  recién insertadas por otra conexión

Tablas: `conversations` (+ `working_directory`), `messages`, `models`, `providers`, `settings`,
`project_permissions`, `users`.

---

## Agent loop (`backend/agent/loop.py`, ~1200 líneas)

`run_agent(messages, adapter, request_approval=None, working_directory=None)` — async generator
de `StreamEvent`. `max_iterations` default **40**.

System prompt = (`model.system_prompt` o `cfg.agent.system_prompt`) + memoria persistente +
directorio activo + instrucciones de proyecto. En el primer mensaje con working dir inyecta
además el árbol de directorios.

**Eventos SSE del loop:** `iteration`, `compacting`, `text_delta`, `tool_call`, `tool_result`,
`tool_confirmation_needed`, `clear_content`, `usage`, `done`, `error`. `routers/chat.py` añade
`title_updated`. El cliente también declara `warning`.

⚠️ El `elif` de reenvío del loop solo pasa `text_delta`/`tool_call`/`done`/`usage`/`error`. Los
eventos `warning` (openai_compat) y `clear_content` (ollama_native) que emiten los adaptadores
**se descartan en silencio**. Si añades un tipo de evento en un adaptador, añádelo también ahí.

**Confirmación de tools:** el loop emite `tool_confirmation_needed` y bloquea en
`await request_approval(tool_use_id)` (timeout 300 s → rechaza). El frontend desbloquea con
`POST /api/conversations/{id}/approve`. Si `request_approval` es `None` (caso Telegram) se
aprueba implícitamente. Los permisos "siempre en este proyecto" viven en `project_permissions`
(`execute_command` / `write_file` / `delete_file`).

**Detección de alucinaciones** (`_detect_hallucinated_action`): ~250 frases ES/EN en
`_HALLUCINATION_PATTERNS`. Solo dispara si hay <2 correcciones en el turno, hubo texto, no corrió
ninguna tool en las últimas 6 posiciones y `_is_capability_inquiry()` es falso. Al disparar:
`clear_content` + mensaje `[SISTEMA]` inyectado. **Al tocar esos patrones vigila los falsos
positivos** — los genéricos ("listo.", "done.") ya se eliminaron justo por eso.

**Recuperación de tool calls inline** (`_parse_inline_tool_calls`, solo si NO es Anthropic):

- Formato A: `icall {...}` · `<tool_call>{...}</tool_call>` · `<functioncall>{...}`
- Formato B: `<function=NAME><parameter=X>valor</parameter>`, con coerción de tipos
- Deduplica por nombre → **una sola llamada por nombre de tool y turno**
- Reescribe el historial como `tool_calls` de OpenAI y emite `clear_content` + `tool_call`

**Auto-retry de terminal:** si `execute_command` devuelve `Exit code: N` con N≠0, inyecta un
mensaje `[SISTEMA]` pidiendo corregir. El exit code se parsea con **regex**, no con substring:
la terminal escribe `Exit code:` en mayúscula y la comparación en minúscula nunca casaba.

### Compresor de contexto

Se dispara al inicio de cada iteración si los mensajes superan `cfg.agent.compact_threshold`
(**default 80.000 caracteres**). Fases: dedup + one-liners de resultados de tool → cálculo de
fronteras head/tail → **resumen generado por el propio modelo** (llamada extra sin tools, 14
secciones en español) → saneado de pares tool_call/tool_result → borrado de imágenes históricas.
Anti-thrashing: se desactiva tras 2 pasadas con <10 % de ahorro.

### Tools (31 con todo habilitado)

| Grupo | Tools | Flag |
|---|---|---|
| Filesystem | `read_file` `write_file` `edit_file` `list_directory` `search_files` `delete_file` `delete_directory` `glob` `grep` | `tools.filesystem.enabled` |
| Terminal | `execute_command` | `tools.terminal.enabled` |
| Git | `git_status` `git_diff` `git_log` `git_add` `git_commit` `git_checkout` `git_branch` `git_pull` `git_push` | siempre |
| Todo | `todo_write` `todo_update` `todo_read` | siempre |
| Web | `web_search` `web_fetch` | `tools.web_search.enabled` (controla ambas) |
| Vídeo | `create_video_from_images` `convert_video` `trim_video` `extract_frames` `add_audio_to_video` | `tools.video.enabled` |
| Replicate | `generate_image` `generate_video` | `tools.replicate.enabled` (default off) |

No hay registro automático ni decoradores: cada módulo exporta una lista módulo-nivel
(`FILESYSTEM_TOOLS`, `GIT_TOOLS`, `TODO_TOOLS`…) y `get_enabled_tools()` las concatena según los
flags. Para añadir una tool: hereda de `BaseTool`, añádela a la lista de su módulo y, si lleva
flag nuevo, tócalo en `ToolsConfig` + `get_enabled_tools()`.

Schemas: Anthropic usa `input_schema`, OpenAI usa `parameters`. El loop decide con
`is_anthropic = "anthropic" in type(adapter).__name__.lower()`.

**Solo las tools de filesystem hacen sandbox de rutas** (`_resolve_and_check` contra
`allowed_paths` + working dir). `execute_command`, los `git_*`, vídeo y Replicate leen y escriben
rutas arbitrarias. `git_commit` y `git_push` no piden confirmación.

### Memoria persistente

`~/.localforge_memory.md` (o `$DATA_DIR/localforge_memory.md` en Docker). **Solo se lee**, en
`_load_memory()`, una vez por `run_agent`. No existe ninguna tool de memoria: el agente solo
puede escribirla llamando a `write_file` con la ruta explícita, y solo si cae dentro de
`allowed_paths`. La UI la gestiona con `GET`/`DELETE /api/config/memory`.

---

## Modelos y providers

`registry.get_adapter(name, cfg)` despacha por `provider`:

| provider | adaptador | notas |
|---|---|---|
| `anthropic` | `AnthropicAdapter` (SDK nativo) | **sin `base_url`** |
| `ollama` | `OllamaNativeAdapter` | `/api/chat` nativo, no la capa OpenAI-compat |
| `copilot` | `CopilotAdapter` | roto, ver deuda técnica |
| cualquier otro | `OpenAICompatAdapter` | `base_url` del modelo → del provider → fallback Ollama |

Un modelo que no esté en la config cae por defecto a Ollama (se asume descubierto en runtime).

`ollama_native.py` existe por bugs del endpoint OpenAI-compat de Ollama (respuestas vacías, p. ej.
gemma3:12b). Puntos clave, todos fruto de la auditoría (`docs/AUDITORIA_TOOL_USE.md`):

- `num_ctx` configurable (`cfg.agent.ollama_num_ctx`, default 8192). El default de Ollama es 2048
  y **trunca el system prompt en silencio** → el modelo "olvida" que tiene tools
- `temperature` se pasa en `options` (antes se ignoraba por completo)
- Los `tool_call` se emiten todos de golpe al recibir `done`, no en streaming
- Retry sin tools ante error, precedido de `clear_content` para no duplicar el texto ya emitido
- En mensajes `role:"tool"` se descarta el id de correlación (Ollama solo recibe `content`)

Providers builtin sembrados en el primer arranque: ollama, anthropic, openai, groq, openrouter,
together, mistral, deepseek. Las API keys se guardan en la BD (Settings → Providers), con
fallback a variable de entorno vía `api_key_env`.

Resolución de API key (`get_model_api_key`): key del modelo → key del provider en BD →
`model.api_key_env` → env var estándar del provider.

---

## Autenticación

Dos mecanismos coexistiendo, resueltos en `backend/middleware/auth.py`:

1. **JWT de usuario** (`python-jose` HS256 + bcrypt). Claim `type` ∈ `access` / `totp_challenge`
   / `password_reset`. Access 8 h, remember 30 d, reset 30 min. 2FA TOTP opcional (`pyotp` +
   `qrcode`). No hay refresh tokens, ni blacklist, ni logout de servidor.
2. **`API_KEY` legacy** en `.env` — acceso total a todo lo que no exija `require_admin`.

Orden del middleware: `OPTIONS` → rutas públicas → `Authorization: Bearer` / `X-API-Key` /
`?api_key=` → si no hay credencial, **modo abierto** si no hay `API_KEY` *y* hay 0 usuarios.

Rutas públicas: `/api/health`, `/api/auth/login`, `/api/auth/status`, `/api/auth/setup`,
`/api/auth/totp/verify`, `/api/auth/password-reset/{request,confirm}`.

El query param `?api_key=` existe porque `EventSource` no admite cabeceras (lo usa `LogsPage.tsx`
para `/api/logs/stream`). Las respuestas 401 del middleware añaden cabeceras CORS a mano, porque
`CORSMiddleware` no procesa respuestas cortocircuitadas por un middleware posterior.

Roles: solo `users.is_admin` (0/1). Únicamente el router `users` exige `require_admin`. No puedes
quitarte tu propio admin, ni borrarte, ni dejar la instancia con 0 usuarios.

⚠️ `SECRET_KEY` no aparece en `.env.example`: si no se define, se genera aleatoria en cada
arranque y **todas las sesiones se invalidan al reiniciar**.

---

## Frontend

- **Sin router.** `main.tsx` hace `window.location.pathname === '/logs' ? <LogsPage/> : <App/>`.
  Todo lo demás es una máquina de estados en `App.tsx`:
  `checking` → `offline` / `setup` / `required` / `ok`.
- `api/client.ts`: `BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api"`. Esa
  constante está **duplicada literalmente en 4 ficheros** (`client.ts`, `ChatWindow.tsx`,
  `LogsPage.tsx`, `SettingsPanel.tsx`) en lugar de reexportarse.
- Auth en cliente: `authHeaders()` → `Authorization: Bearer <jwt || api_key>`. Storage:
  `localforge_jwt` (localStorage si *remember*, si no sessionStorage), `localforge_api_key`
  (legacy), `localforge_user`. Excepciones que usan `X-API-Key`: `LogsPage`, los endpoints
  `/github/copilot/*` de `SettingsPanel` y `POST /permissions/grant` en `ChatWindow`.
- SSE de chat: **no usa `EventSource`**, hace `fetch` POST + `res.body.getReader()` +
  `TextDecoder`, bufferiza por `\n` y corta en `[DONE]`. Devuelve una función de cancelación
  (`AbortController`).
- Estado: `store/chat.ts` es el único store Zustand real. `store/prefs.ts` persiste
  `renderMarkdown`/`showToolCalls`/`devMode`. `store/theme.ts` **no es un store**, son funciones
  sueltas sobre la clase `dark` de `<html>`.
- Markdown: `marked` + `dompurify` + `highlight.js` (build core, ~17 lenguajes registrados a
  mano). No hay react-markdown ni shiki.
- Iconos: `lucide-react`. No hay Font Awesome instalado.
- TypeScript con `verbatimModuleSyntax`: usa `import type { X }` para imports de solo tipos.

Componentes clave: `Sidebar` (conversaciones, LEDs API/DB con polling de `checkHealth` cada 30 s,
toggle devMode), `ChatWindow` (input, adjuntos, working dir, instrucciones de proyecto),
`Message` (memoizado), `ToolBlock` (colapsable, icono y etiqueta en español por nombre de tool,
spinner mientras no hay resultado), `SettingsPanel` (~1900 líneas, el fichero más grande del
repo), `ConfirmationModal`, `StatsBar` (polling `/stats` cada 3 s, pausa si la pestaña está
oculta), `UpdateBanner`, `LogsPage`, `pages/UsersPage`.

### App móvil

Ionic React 8 + Capacitor 8, `react-router-dom` v5 vía `IonReactRouter` (`/chat`,
`/conversations`, `/` → Login). Config del servidor en localStorage con claves propias
(`lf_server_url`, `lf_api_key`, `lf_model`). Autentica con `X-API-Key`, no con Bearer.
`src/pages/Home.tsx` es la plantilla del scaffold de Ionic y no está enrutada.

---

## Convenciones

- Comentarios, mensajes de commit y textos de UI en español. El system prompt del agente fuerza
  respuestas en español.
- Commits recientes en estilo convencional (`feat:`, `docs:`, `chore:`); el histórico antiguo es
  libre ("Actualizando", "Sincro").
- Rama principal `main`. Las ramas `luamodel/v1…v4.2` están todas ya fusionadas en `main`.
- Varios imports pesados (adaptadores, stores) se hacen **lazy dentro de la función** para evitar
  ciclos con `config.py`. Respétalo.

---

## Deuda técnica y trampas conocidas

Auditado sobre `main` (`15b9056`, 2026-06-24) y parcialmente reparado el 2026-09-02.

Hoja de ruta completa (auditoría en 7 dimensiones + 8 fases priorizadas):
https://claude.ai/code/artifact/f547723c-af69-470e-9f41-769df59c7949

### Reparado en el motor del agente (2026-09-02)

Los seis defectos que hacían descarrilar cualquier tarea de programación larga. Los 12 tests que
los cubren fallan contra `15b9056` y pasan ahora:

- **`openai_compat` perdía `tool_calls`** al reconstruir el historial, así que los `role:"tool"`
  siguientes apuntaban a un `tool_call_id` inexistente → 400 en la iteración 2. Y
  `_convert_content_for_openai(None)` devolvía la cadena literal `"None"`.
- **La corrección `[SISTEMA]` del auto-retry se inyectaba DENTRO del `for tc in tool_calls`**: si
  la primera de varias tools fallaba, un mensaje `role:"user"` quedaba entre dos `tool_result`.
  Anthropic lo rechaza de plano. Ahora se inyecta una sola vez, después del bucle.
- **Las tools se ejecutaban sin validar argumentos.** `validate_tool_input()` en `tools/base.py`
  comprueba `required`, claves desconocidas y tipos primitivos contra el propio JSON Schema de la
  tool, y devuelve un mensaje accionable en vez de un `TypeError` que el modelo lee como "la
  herramienta está rota".
- **El parser de tool calls inline hacía `.strip()` a cada parámetro**, destruyendo la indentación
  de cualquier `old_string`. Ahora `_trim_param_value()` quita solo los saltos de línea de las
  etiquetas XML.
- **La deduplicación del parser inline era por nombre de tool**, así que un turno con tres
  `edit_file` distintos ejecutaba uno. Ahora la clave es (nombre, argumentos).
- **`_messages_char_count` no veía los payloads de las tool calls**: un `write_file` de 200 KB
  contaba 0 caracteres y la compactación se disparaba a ciegas. Ahora cuenta `tool_use`,
  `tool_calls` y adjuntos.

### Reparado en la edición de ficheros (2026-09-02)

- **`read_text`/`write_text` convertían todo fichero LF a CRLF en Windows** — una edición de una
  línea producía un diff del fichero entero. `_read_source`/`_write_source` leen y escriben bytes,
  preservan el EOL dominante y el BOM, y escriben de forma atómica (`os.replace`).
- **`edit_file` respondía `old_string not found` y nada más.** Ahora `_match_failure_report()`
  diagnostica la causa probable (indentación, espacios finales, saltos de línea) y muestra el
  fragmento real del fichero con números de línea. La ambigüedad dice en qué líneas está.
- **`write_file` creaba árboles enteros por una errata** (`src/componets/x.ts`) y respondía
  `Success`. Ahora crea como mucho un nivel y lo dice.
- `edit_file` y `write_file` devuelven un **diff unificado** en vez de `Success: N characters`.

### Reparado antes

- `models/copilot.py`: importaba `BaseAdapter` (inexistente) → `ImportError`; convertía los tools
  asumiendo schema Anthropic aunque el loop le pasa OpenAI; nunca emitía `done`; perdía el primer
  fragmento de `arguments` de cada tool call; el tercer parámetro se llamaba `system_prompt` y
  rompía las llamadas con `system=`. Ahora también reutiliza `_convert_content_for_openai` para
  imágenes/PDF y emite `error` en vez de lanzar excepciones a mitad del stream.
- Fuga de `totp_secret`: `routers/users.py` ya no define su propio `_safe()`, importa el de
  `routers/auth.py` — una sola fuente de verdad, que es lo que evitó el bug original.
- `POST /api/update/apply` exige admin vía `require_admin_or_system`, que deja pasar el modo
  `API_KEY` legacy y el modo abierto de desarrollo. `/update/check` sigue abierto a cualquier
  autenticado porque el banner lo consulta en bucle.
- Los enlaces de reseteo son de un solo uso: el token lleva un `pwh` (hash del `password_hash`
  vigente) y el confirm lo revalida, así que cambiar la contraseña invalida cualquier enlace.
- `_is_open_mode_async()` ahora falla cerrado y deja un `logging.warning` si no puede consultar la
  BD.
- App móvil: `client.ts` habla con `POST /api/conversations/{id}/chat` (creando antes la
  conversación), respeta el centinela `[DONE]` en vez de tratar cada `done` de iteración como fin
  de stream, normaliza los mensajes del historial y trata `created_at`/`updated_at` como unix
  **segundos**. `Chat.tsx` pinta tool calls y rechaza automáticamente las que piden confirmación
  (no hay UI de aprobación en móvil) para no colgarse los 300 s del timeout.
- `node_modules/` de la raíz desindexado y añadido al `.gitignore`, junto con
  `LocalForge-App/node_modules|dist`. La línea basura en UTF-16 del final del `.gitignore`
  eliminada.
- Docs: puerto 3000 y defaults reales (`max_iterations` 40, `compact_threshold` 80000, adjuntos de
  texto 2 MB) en `README.md`; `start.bat` mata ahora 3000 y 5173.

### Pendiente

- **La URL de la API de Copilot no está verificada.** `COPILOT_API_BASE` apunta a
  `https://api.githubcopilot.com/v1` mientras que `routers/github_copilot.py` usa la misma sin
  `/v1`. Hace falta una suscripción real de Copilot para saber cuál responde; si da 404, quitar el
  `/v1`.
- `exchange_copilot_token()` en `routers/github_copilot.py` no la llama nadie.
- Los `display_name` de los modelos Copilot auto-registrados están desalineados
  (`claude-sonnet-4-5` se etiqueta "Claude Sonnet 3.5").
- `permissions`, `logs`, `stats` y `github_copilot` siguen sin control de rol (solo middleware).
  `permissions` **no debe** exigir admin: `ChatWindow` llama a `POST /permissions/grant` como
  usuario normal.
- `reset_url_base` lo aporta el cliente sin allowlist.
- `POST /api/auth/setup` y `POST /api/users` no validan formato de email ni longitud mínima de
  contraseña (solo `password-reset/confirm` exige ≥8).
- `SECRET_KEY` no está en `.env.example`; sin definirla, las sesiones mueren en cada reinicio.
- `App.tsx` y `client.ts` dejan `console.log` de depuración de auth (`[verify]`, `[checkAuth]`).
- **Los endpoints de memoria ignoran `DATA_DIR`:** `routers/config.py` usa `cfg.agent.memory_file`
  directamente, mientras `loop.py::_get_memory_path()` prioriza `$DATA_DIR`. En Docker la UI opera
  sobre un fichero distinto del que lee el agente.
- `create_directory` se contabiliza como escritura en el loop pero no existe como tool registrada.
- Código muerto en `loop.py`: `_is_task_request()` y `_user_wants_multiple_files()` están
  definidas pero no se usan en el gate actual.
- El `package.json` de la raíz declara `shiki`, que no usa nadie (el frontend usa `highlight.js`).
- `README.md` sigue sin cubrir auth/usuarios/2FA, las tools de git/todo/vídeo/Replicate ni el
  compresor de contexto.
