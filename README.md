# 🔨 LocalForge

Local AI agent system with filesystem, terminal and web search access.
Multi-model support via a unified layer — works with Ollama (native API), Anthropic, Groq, OpenRouter, OpenAI, Mistral, DeepSeek, Together AI and any custom OpenAI-compatible provider.

---

## Features

- **Multi-model** — switch between models from any provider in a single dropdown; Ollama models auto-discovered
- **Agent loop** — multi-turn reasoning with tool use (filesystem, terminal, web search)
- **Per-model temperature** — configure creativity vs. precision per model from Settings (default 0.3)
- **Tool confirmations** — sensitive actions (write/delete files, run commands) can require explicit approval; per-project permissions remembered permanently
- **Image, PDF & text attachments** — drag & drop, file picker or **Ctrl+V paste from clipboard** (including Windows Snipping Tool); the agent reads and analyzes them
- **Memory optimisation** — when the conversation grows large, old tool results are automatically compacted and a notice appears in the chat; threshold configurable in Settings
- **Auto-update** — check and apply updates from GitHub directly from Settings, with branch detection and commit list
- **Persistent chat history** — conversations stored in SQLite (default) or MySQL
- **Persistent memory** — the agent remembers things across conversations via `~/.localforge_memory.md`
- **Per-model system prompt** — each model can have its own system prompt that overrides the global one
- **Telegram bot** — full agent access from Telegram (same tools, same models), configurable from Settings
- **Developer mode** — live log viewer at `/logs` with level filtering, search and SSE stream
- **Dark / light theme** — persisted per user
- **API key auth** — optional password protection for server deployments
- **Hallucination detection** — catches models that claim to use tools without actually calling them, and models that output inline tool calls as text (`icall {...}`)
- **Mobile app** — Ionic React companion app (`LocalForge-App/`) for Android and iOS

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13+ · FastAPI · aiosqlite / aiomysql |
| Frontend | React · Vite · TypeScript · Tailwind CSS v3 · Zustand · lucide-react |
| Mobile | Ionic React · Capacitor (Android + iOS) |
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
│   │   ├── filesystem.py        # read_file, write_file, delete_file, delete_directory, list_directory
│   │   ├── terminal.py
│   │   └── web_search.py
│   ├── routers/
│   │   ├── chat.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── providers.py
│   │   ├── permissions.py       # Per-project tool permissions
│   │   ├── update.py            # GitHub auto-update (check + apply)
│   │   ├── stats.py
│   │   └── logs.py              # GET /api/logs · SSE /api/logs/stream
│   ├── db/
│   │   ├── connection.py        # SQLite/MySQL abstraction (_Wrapper)
│   │   ├── store.py             # Conversation persistence
│   │   ├── models_store.py      # Model CRUD (system_prompt + temperature columns)
│   │   ├── providers_store.py   # Provider CRUD + builtin seeding
│   │   ├── permissions_store.py # Per-project permission persistence
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
│       ├── UpdateBanner.tsx     # GitHub update checker + apply
│       ├── StatsBar.tsx         # CPU / RAM / GPU / VRAM stats
│       ├── ConfirmationModal.tsx # Agent tool approval dialog (with "always allow" option)
│       ├── ConfirmDialog.tsx     # Generic reusable confirm dialog
│       └── LogsPage.tsx         # Developer log viewer (route /logs)
├── LocalForge-App/              # Ionic React mobile app
│   └── src/
│       ├── api/client.ts        # Mobile API client (SSE streaming)
│       ├── store/app.ts         # Zustand state
│       ├── pages/
│       │   ├── Login.tsx        # Server URL + API key setup
│       │   ├── Chat.tsx         # Streaming chat with model picker
│       │   └── Conversations.tsx # Conversation list with swipe-to-delete
│       └── components/
│           ├── MessageBubble.tsx
│           └── ModelPicker.tsx
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

# SMTP para "He olvidado mi contraseña"
LOCALFORGE_SMTP_ENABLED=true
LOCALFORGE_SMTP_HOST=smtp.tudominio.com
LOCALFORGE_SMTP_PORT=587
LOCALFORGE_SMTP_USERNAME=usuario
LOCALFORGE_SMTP_PASSWORD=tu_password
LOCALFORGE_SMTP_FROM_EMAIL=no-reply@tudominio.com
LOCALFORGE_SMTP_FROM_NAME=LocalForge
LOCALFORGE_SMTP_USE_TLS=true
LOCALFORGE_SMTP_USE_SSL=false

# Optional — use MySQL instead of SQLite
# DATABASE_URL=mysql://user:pass@localhost:3306/localforge

# Optional — override bind host/port
# LOCALFORGE_HOST=127.0.0.1
# LOCALFORGE_PORT=8000
```

Provider API keys (Anthropic, Groq, OpenRouter…) are configured in **Settings → Providers** and stored in the database. Alternatively set them as environment variables (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, etc.) and reference them in the provider's `api_key_env` field. Para SMTP, usa `.env` si no quieres guardar credenciales en la configuración.

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
      "require_confirmation_for": [],  // empty = use project permissions
      "max_file_size_mb": 10
    },
    "terminal": {
      "enabled": true,
      "require_confirmation": false,   // off by default — use project permissions
      "timeout_seconds": 30,
      "blocked_patterns": ["rm -rf /", "format c:"]
    },
    "web_search": { "enabled": true, "max_results": 5 }
  },
  "agent": {
    "max_iterations": 20,
    "compact_threshold": 40000,  // chars — compacts old tool results above this limit
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

### Per-model configuration

Each model supports two optional overrides set in **Settings → Models → Edit**:

| Field | Default | Description |
|---|---|---|
| **System Prompt** | _(global)_ | Overrides the global system prompt for this model only |
| **Temperature** | `0.3` | Controls creativity: `0` = deterministic, `1` = creative |

---

## Memory optimisation

When a conversation grows large (default threshold: **40,000 characters**), LocalForge automatically truncates old tool results — the biggest contributors to context size — while keeping recent messages intact. A notice appears in the chat:

> `🗜️ Optimizando memoria… 23K liberados`

The threshold is configurable in **Settings → Agent → Umbral de optimización de memoria**. Recommended values:
- Small context models (8K tokens): `20000`
- Standard models (32K): `40000` _(default)_
- Large context models (128K+): `80000–100000`

---

## Per-project permissions

When the agent requests a sensitive action (write file, delete file/directory, run command), a confirmation dialog appears. You can:

- **Allow once** — approve this single action
- **Allow always in this project** — saves permission permanently for the current working directory; the agent will not ask again for the same action type in that project

Saved permissions are stored in the `project_permissions` table and can be managed via `GET/POST/DELETE /api/permissions`.

---

## Auto-update

LocalForge can update itself from GitHub without leaving the browser:

1. Go to **Settings** — an update banner appears automatically when a new version is available
2. The banner shows the current branch, the list of new commits and their authors
3. Click **Actualizar ahora** — runs `git pull` and reloads the frontend

Requires the project to be a git clone with a configured remote (`origin`). Works on any branch.

---

## Database schema

```
conversations      (id, title, created_at, updated_at)
messages           (id, conversation_id, role, content, created_at, metadata)
models             (id, name, display_name, provider, api_key, base_url, is_default, system_prompt, temperature, created_at)
providers          (id, name, display_name, base_url, api_key_env, api_key, is_builtin, created_at)
project_permissions (id, project_path, permission_type, created_at)
settings           (setting_key, value)   ← app config as JSON blob
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
| `GET` | `/api/permissions` | List permissions for a project (`?project_path=...`) |
| `POST` | `/api/permissions/grant` | Grant a permission |
| `POST` | `/api/permissions/revoke` | Revoke a permission |
| `DELETE` | `/api/permissions` | Clear all permissions for a project |
| `GET` | `/api/update/check` | Check for available updates (git fetch + compare) |
| `POST` | `/api/update/apply` | Apply update (`git pull`) |
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
| Images (JPEG, PNG, GIF, WebP) | Drag & drop, 📎 button or **Ctrl+V** | Full image via vision API |
| PDFs | Drag & drop or 📎 button | Extracted text via pypdf (supports page ranges) |
| Text files (`.txt`, `.py`, `.ts`, `.json`…) | Drag & drop or 📎 button | Full file contents embedded in the message |

Text files are shown as a small chip above the message bubble — the raw file content is not displayed in the chat.

**Ctrl+V paste** works with any image in the clipboard, including screenshots from Windows Snipping Tool (`Win+Shift+S`).

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
| **Agent** | Max iterations, memory optimisation threshold, global system prompt |
| **Telegram** | Bot token, allowed user IDs, default model |
| **Models** | Add, edit, delete, set default; per-model system prompt; temperature slider; test connectivity |
| **Providers** | Add, edit, delete provider definitions (base URL + API key) |

---

## Mobile app (Ionic)

The `LocalForge-App/` directory contains an Ionic React app for Android and iOS.

### Setup

```bash
cd LocalForge-App
npm install
```

### Run in browser (dev)

```bash
npm run dev
```

### Build for Android / iOS

```bash
npm run build
npx cap sync
npx cap open android   # opens Android Studio
npx cap open ios       # opens Xcode
```

On first launch, enter your LocalForge server URL (e.g. `http://192.168.1.x:8000`) and API key. The config is saved locally and reconnects automatically on next open.

---

## Despliegue en producción (Ubuntu + Plesk)

### Requisitos

- Ubuntu 24.04, Python 3.12+, Node.js 18+, Git
- Plesk Obsidian (gestiona dominios, SSL y proxy Nginx)
- MySQL/MariaDB (opcional; SQLite por defecto)

### 1. Clonar e instalar dependencias

```bash
cd /var/www/vhosts/<tu-dominio>/httpdocs
git clone https://github.com/gvazquez79-uoc/LocalForge.git .
apt install python3.12-venv -y
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Build del frontend

```bash
cd frontend && npm install && npm run build && cd ..
```

### 3. Configurar `.env`

```bash
cat > .env << 'EOF'
DATABASE_URL=mysql+aiomysql://usuario:password@localhost/nombre_db
API_KEY=tu_clave_secreta_larga
LOCALFORGE_HOST=127.0.0.1
LOCALFORGE_PORT=8000
EOF
```

- Si usas **SQLite** omite `DATABASE_URL` — se crea automáticamente.
- `API_KEY` protege el acceso al backend; el frontend la gestiona de forma transparente.
- Las API keys de los modelos (Anthropic, Groq, etc.) se configuran desde la interfaz en Settings → Providers.

### 4. Servicio systemd

```bash
cat > /etc/systemd/system/localforge.service << 'EOF'
[Unit]
Description=LocalForge
After=network.target mysql.service

[Service]
WorkingDirectory=/var/www/vhosts/<tu-dominio>/httpdocs
ExecStart=/var/www/vhosts/<tu-dominio>/httpdocs/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
User=root
EnvironmentFile=/var/www/vhosts/<tu-dominio>/httpdocs/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now localforge
systemctl status localforge
```

### 5. Proxy en Plesk

En el panel de Plesk, ve al dominio → **Apache & nginx Settings** y añade en "Additional nginx directives":

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 300s;
    proxy_buffering off;
}

location / {
    root /var/www/vhosts/<tu-dominio>/httpdocs/frontend/dist;
    try_files $uri $uri/ /index.html;
}
```

Activa **Let's Encrypt** desde Plesk para HTTPS automático.

### Actualizar

```bash
cd /var/www/vhosts/<tu-dominio>/httpdocs
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
systemctl restart localforge
```

---

## License

MIT
