# 🔨 LocalForge

Local AI agent system with filesystem, terminal and web search access.
Multi-model support via a unified layer — works with Ollama (native API), Anthropic, Groq, OpenRouter, OpenAI, Mistral, DeepSeek, Together AI and any custom OpenAI-compatible provider.

---

## Features

- **Multi-model** — switch between models from any provider in a single dropdown; Ollama models auto-discovered
- **Agent loop** — multi-turn reasoning with tool use (filesystem, terminal, web search)
- **Tool confirmations** — sensitive actions (write/delete files, run commands) require explicit approval in the UI
- **Image, PDF & text attachments** — drag & drop or paste; the agent reads and analyzes them; text files shown as chips (not dumped into the bubble)
- **Persistent chat history** — conversations stored in SQLite (default) or MySQL
- **Persistent memory** — the agent remembers things across conversations via `~/.localforge_memory.md`
- **Per-model system prompt** — each model can have its own system prompt that overrides the global one
- **Telegram bot** — full agent access from Telegram (same tools, same models), configurable from Settings
- **Developer mode** — live log viewer at `/logs` with level filtering, search and SSE stream
- **Dark / light theme** — persisted per user
- **API key auth** — optional password protection for server deployments
- **Hallucination detection** — catches models that claim to use tools without actually calling them, and models that output inline tool calls as text (`icall {...}`)

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13+ · FastAPI · aiosqlite / aiomysql |
| Frontend | React · Vite · TypeScript · Tailwind CSS v3 · Zustand · lucide-react |
| Agent | Anthropic SDK · OpenAI-compatible SDK · ollama (native API) |
| Bot | python-telegram-bot v20+ |

---

## Project structure

```
LocalForge/
├── backend/
│   ├── main.py                  # FastAPI app, lifespan startup
│   ├── config.py                # Pydantic config, DB sync helpers
│   ├── logging_setup.py         # In-memory log ring-buffer + custom handler
│   ├── agent/
│   │   └── loop.py              # Multi-turn agent loop with SSE streaming
│   ├── models/
│   │   ├── base.py
│   │   ├── anthropic.py
│   │   ├── openai_compat.py
│   │   ├── ollama_native.py     # Ollama /api/chat native adapter
│   │   └── registry.py          # Provider → adapter resolution
│   ├── tools/
│   │   ├── base.py
│   │   ├── filesystem.py
│   │   ├── terminal.py
│   │   └── web_search.py
│   ├── routers/
│   │   ├── chat.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── providers.py
│   │   ├── stats.py
│   │   └── logs.py              # GET /api/logs · SSE /api/logs/stream
│   ├── db/
│   │   ├── connection.py        # SQLite/MySQL abstraction (_Wrapper)
│   │   ├── store.py             # Conversation persistence
│   │   ├── models_store.py      # Model CRUD (includes system_prompt column)
│   │   ├── providers_store.py   # Provider CRUD + builtin seeding
│   │   └── settings_store.py    # App config stored as JSON blob
│   ├── middleware/
│   │   └── auth.py              # API key auth (headers + ?api_key= for SSE)
│   └── telegram/
│       └── bot.py               # Telegram bot (non-blocking, dynamic restart)
├── frontend/src/
│   ├── api/client.ts            # fetch + SSE client
│   ├── store/
│   │   ├── chat.ts              # Zustand chat state
│   │   ├── prefs.ts             # UI preferences (theme, devMode, markdown…)
│   │   └── theme.ts
│   └── components/
│       ├── App.tsx
│       ├── Sidebar.tsx          # Nav, model selector, dev mode toggle
│       ├── ChatWindow.tsx
│       ├── Message.tsx
│       ├── ToolBlock.tsx
│       ├── ModelSelector.tsx
│       ├── SettingsPanel.tsx    # Full settings UI (config, models, providers)
│       ├── StatsBar.tsx         # CPU / RAM / GPU / VRAM stats
│       ├── ConfirmationModal.tsx # Agent tool approval dialog
│       ├── ConfirmDialog.tsx     # Generic reusable confirm dialog
│       └── LogsPage.tsx         # Developer log viewer (route /logs)
├── localforge.json              # Seed config (DB is source of truth after first boot)
├── requirements.txt             # Python dependencies with pinned versions
├── .env                         # Secrets and runtime config — never commit
└── start.bat                    # Windows one-click startup
```

---

## Quick start

### 1. Install dependencies

```bash
# Python backend
py -3 -m pip install -r requirements.txt

# Or manually:
py -3 -m pip install fastapi uvicorn anthropic openai duckduckgo-search aiosqlite aiomysql pydantic-settings python-telegram-bot psutil pynvml ollama pypdf

# Frontend
cd frontend && npm install
```

### 2. Configure

Create `.env` in the project root:

```env
# Optional — leave empty to disable auth (open dev mode)
API_KEY=your-secret-key

# Optional — use MySQL instead of SQLite
# DATABASE_URL=mysql://user:pass@localhost:3306/localforge

# Optional — override bind host/port
# LOCALFORGE_HOST=127.0.0.1
# LOCALFORGE_PORT=8000
```

Provider API keys (Anthropic, Groq, OpenRouter…) are configured in **Settings → Providers** and stored in the database. Alternatively set them as environment variables (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, etc.) and reference them in the provider's `api_key_env` field.

### 3. Run

**Windows — double-click `start.bat`**, or manually:

```bash
# Terminal 1 — backend
py -3 -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend && npm run dev
```

| Service | URL |
|---|---|
| Frontend (chat) | http://localhost:5173 |
| Log viewer | http://localhost:5173/logs |
| Backend API | http://localhost:8000 |
| Swagger docs | http://localhost:8000/docs |

---

## Configuration

### `localforge.json` (seed only)

Used **only on first boot** to seed the database. After that, all config is managed via the **Settings** panel and stored in the DB. Editing this file after first boot has no effect.

```jsonc
{
  "version": "1.0",
  "default_model": "",           // set via Settings → Models
  "models": [],                  // add models via Settings → Models
  "tools": {
    "filesystem": {
      "enabled": true,
      "allowed_paths": ["~"],    // directories the agent can access
      "require_confirmation_for": ["write_file", "delete_file"],
      "max_file_size_mb": 10
    },
    "terminal": {
      "enabled": true,
      "require_confirmation": true,
      "timeout_seconds": 30,
      "blocked_patterns": ["rm -rf /", "format c:"]
    },
    "web_search": { "enabled": true, "max_results": 5 }
  },
  "agent": {
    "max_iterations": 20,
    "system_prompt": "..."
  },
  "telegram": {
    "enabled": false,
    "bot_token": "",             // token from @BotFather
    "allowed_user_ids": [],      // empty = allow all users
    "default_model": ""          // empty = use global default
  }
}
```

---

## Providers & Models

Providers and models are fully managed from **Settings → Providers** and **Settings → Models**. Changes take effect immediately without restarting the server.

### Builtin providers

| Provider | Base URL | Notes |
|---|---|---|
| Ollama (local) | `http://localhost:11434` | Uses native `/api/chat`; no API key needed |
| Anthropic | _(native SDK)_ | No base URL needed; set API key in provider |
| OpenAI | `https://api.openai.com/v1` | OpenAI-compatible |
| Groq | `https://api.groq.com/openai/v1` | OpenAI-compatible |
| OpenRouter | `https://openrouter.ai/api/v1` | Model names: `provider/model-name` |
| Together AI | `https://api.together.xyz/v1` | OpenAI-compatible |
| Mistral | `https://api.mistral.ai/v1` | OpenAI-compatible |
| DeepSeek | `https://api.deepseek.com/v1` | OpenAI-compatible |

> **Ollama** uses the native `/api/chat` API (not the OpenAI-compat layer), which avoids empty-response bugs on some models. Models are auto-discovered from the running Ollama instance.
>
> **Anthropic** uses the native Anthropic SDK — do not set a base URL.

### Per-model system prompt

Each model can have its own system prompt that overrides the global one. Set it in **Settings → Models → Edit → System Prompt**. Useful for specialized agents (e.g. a coding-only model, a model that always replies in a specific language).

---

## Database schema

```
conversations  (id, title, created_at, updated_at)
messages       (id, conversation_id, role, content, created_at, metadata)
models         (id, name, display_name, provider, api_key, base_url, is_default, system_prompt, created_at)
providers      (id, name, display_name, base_url, api_key_env, api_key, is_builtin, created_at)
settings       (setting_key, value)   ← app config as JSON blob
```

SQLite (`localforge.db`) is used by default. Set `DATABASE_URL=mysql://...` in `.env` to use MySQL.

---

## API reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Health check — always public |
| `GET/PUT` | `/api/config` | Get / update app config |
| `GET` | `/api/config/models` | List models available for the selector (includes Ollama discovery) |
| `POST` | `/api/config/telegram/restart` | Restart Telegram bot |
| `GET` | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/{id}` | Get conversation with messages |
| `DELETE` | `/api/conversations/{id}` | Delete conversation |
| `PATCH` | `/api/conversations/{id}/title` | Rename conversation |
| `POST` | `/api/conversations/{id}/chat` | Send message (SSE stream) |
| `POST` | `/api/conversations/{id}/approve` | Confirm / cancel a tool call |
| `GET/POST` | `/api/models` | List / create models |
| `PUT/DELETE` | `/api/models/{id}` | Update / delete model |
| `PATCH` | `/api/models/{id}/default` | Set default model |
| `POST` | `/api/models/{id}/test` | Test model connectivity |
| `GET/POST` | `/api/providers` | List / create providers |
| `PUT/DELETE` | `/api/providers/{id}` | Update / delete provider |
| `GET` | `/api/stats` | System stats (CPU, RAM, GPU/VRAM via pynvml + Ollama) |
| `GET` | `/api/logs` | Recent log entries — `?n=500&level=ERROR` |
| `GET` | `/api/logs/stream` | Live log stream (SSE) — `?api_key=...` |

Full interactive docs: **http://localhost:8000/docs**

---

## Developer mode

Enable **Developer mode** via the toggle at the bottom of the sidebar. A **View app logs** button appears that opens a live log viewer at `/logs` in a new tab.

The viewer captures all Python logging output in real time via SSE:

- Filter by level: DEBUG / INFO / WARNING / ERROR
- Text search across message and logger name
- Pause / Resume stream, auto-scroll with "Jump to latest"
- Loads last 2000 entries on open, then streams new ones live

To add custom log output from any backend module:

```python
import logging
logger = logging.getLogger(__name__)
logger.info("This appears in the log viewer automatically")
```

---

## Attachments

| Type | How to attach | What the agent sees |
|---|---|---|
| Images (JPEG, PNG, GIF, WebP) | Drag & drop or 📎 button | Full image via vision API |
| PDFs | Drag & drop or 📎 button | Extracted text via pypdf |
| Text files (`.txt`, `.py`, `.ts`, `.json`…) | Drag & drop or 📎 button | Full file contents embedded in the message |

Text files are shown as a small chip above the message bubble — the raw file content is not displayed in the chat.

PDF text extraction requires `pypdf`:
```bash
py -3 -m pip install pypdf
```

Attachment size limits are configurable in **Settings → Attachments** (defaults: images 5 MB, PDFs 25 MB, text 512 KB).

---

## Persistent memory

The agent can remember information across conversations. Ask it to:

- **Save:** "recuerda que mi proyecto usa Laravel" → appends to `~/.localforge_memory.md`
- **Recall:** "qué recuerdas de mí?" → reads the memory file
- **Clear:** "borra tu memoria" → empties the file

The memory file is automatically injected into the system prompt at the start of every conversation.

---

## API key authentication

To protect LocalForge when running on a network, set `API_KEY` in `.env`:

```env
API_KEY=your-secret-password
```

- The frontend shows a login screen on first visit; the key is stored in `localStorage`
- `/api/health` is always public
- SSE endpoints accept the key via `?api_key=` query param (required for `EventSource`)
- If `API_KEY` is not set, the server is open (suitable for local use)

---

## Telegram bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token
2. Go to **Settings → Telegram**, enable the bot and paste the token
3. Optionally add your Telegram user ID to **Allowed user IDs** (get it from [@userinfobot](https://t.me/userinfobot))
4. Click **Save** — the bot restarts automatically

Commands: `/start` (reset conversation) · `/new` (new conversation)

---

## Settings panel

| Section | Description |
|---|---|
| **Appearance** | Light / dark theme, render markdown, show tool steps |
| **Filesystem** | Enable/disable, allowed paths, confirmation rules, max file size |
| **Terminal** | Enable/disable, timeout, blocked command patterns |
| **Web Search** | Enable/disable, max results |
| **Attachments** | Max size limits for images, PDFs and text files |
| **Agent** | Max iterations, global system prompt |
| **Telegram** | Bot token, allowed user IDs, default model |
| **Models** | Add, edit, delete, set default; per-model system prompt; test connectivity |
| **Providers** | Add, edit, delete provider definitions (base URL + API key) |

---

## License

MIT
