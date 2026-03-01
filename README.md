# LocalForge

Local AI agent with filesystem, terminal, and web search access.
Multi-model: Claude, Ollama, OpenAI-compatible. Includes Telegram bot integration.

## Features

- **Multi-model** — Claude (Anthropic), Ollama (local), any OpenAI-compatible API
- **Filesystem tools** — read, write, list, search files within allowed paths
- **Terminal** — run shell commands with optional confirmation
- **Web search** — DuckDuckGo, no API key required
- **Streaming** — real-time SSE response with tool call visualization
- **Conversation history** — SQLite persistence, inline rename, sidebar navigation
- **Telegram bot** — use the agent from Telegram, configurable from the Settings panel
- **Settings panel** — configure tools, paths, agent prompt, and display preferences
- **Themes** — light / dark mode

## Quick Start

### 1. Configure

```bash
# Copy config templates
cp localforge.example.json localforge.json
cp .env.example .env

# Edit .env and add your API keys (e.g. ANTHROPIC_API_KEY)
# Edit localforge.json to set your default model and allowed paths
```

### 2. Install dependencies

```bash
# Python backend
py -3 -m pip install -e .

# Frontend
cd frontend && npm install
```

### 3. Run

```bash
# Windows — double-click:
start.bat

# Or manually:
# Terminal 1 — Backend
py -3 -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Open **http://localhost:5173** — API docs at **http://localhost:8000/docs**

> **Note:** `localforge.json` is gitignored — it contains your local config and secrets.
> Never commit it. Use `localforge.example.json` as the reference template.

## Configuration (`localforge.json`)

All settings are also editable from the **Settings panel** in the UI.

| Field | Description |
|-------|-------------|
| `default_model` | Model used by default for new conversations |
| `models[].provider` | `anthropic` \| `ollama` \| `openai` |
| `models[].api_key_env` | Environment variable holding the API key |
| `models[].base_url` | Base URL (required for Ollama / OpenAI-compat) |
| `tools.filesystem.allowed_paths` | Directories the agent can access (`~` = home) |
| `tools.filesystem.require_confirmation_for` | Ask before `write_file` / `delete_file` |
| `tools.filesystem.max_file_size_mb` | Max file size the agent can read |
| `tools.terminal.require_confirmation` | Ask before every shell command |
| `tools.terminal.timeout_seconds` | Command timeout |
| `tools.terminal.blocked_patterns` | Commands that are always rejected |
| `tools.web_search.max_results` | Results returned per search |
| `agent.max_iterations` | Max tool-call rounds per message |
| `agent.system_prompt` | Agent persona / instructions |
| `telegram.enabled` | Enable the Telegram bot |
| `telegram.bot_token` | Token from [@BotFather](https://t.me/BotFather) |
| `telegram.allowed_user_ids` | Telegram user IDs allowed to use the bot (empty = anyone) |
| `telegram.default_model` | Model used by the Telegram bot (empty = global default) |

## Using Ollama

1. Install [Ollama](https://ollama.ai) and pull a model: `ollama pull llama3.2`
2. Models are **auto-discovered** — just open the UI and they appear in the selector
3. Optionally pin a model in `localforge.json`:

```json
{
  "name": "llama3.2",
  "display_name": "Llama 3.2 (local)",
  "provider": "ollama",
  "base_url": "http://localhost:11434/v1"
}
```

## Telegram Bot

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token
2. Open Settings → Telegram → enable the toggle and paste the token
3. Click **Save** — the bot starts automatically (no restart needed)
4. Send `/start` to your bot

Commands: `/start` (reset conversation) · `/new` (new conversation)

To restrict access, add your Telegram user ID to **Allowed User IDs**
(get it from [@userinfobot](https://t.me/userinfobot)).

## Settings Panel

Open via the ⚙ icon. Display preferences apply instantly; tool/agent changes require **Save**.

| Setting | Description |
|---------|-------------|
| Theme | Light / Dark |
| Render markdown | Enable markdown + syntax highlighting in responses |
| Show tool steps | Toggle tool call visibility (advanced / simple mode) |
| Filesystem | Enable/disable, set allowed paths and confirmation rules |
| Terminal | Enable/disable, set timeout and blocked patterns |
| Web Search | Enable/disable, set max results |
| Agent | Max iterations and system prompt |
| Telegram | Bot token, allowed users, default model |

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/health` | Health check |
| `GET`  | `/api/config` | Get current config (token masked) |
| `PUT`  | `/api/config` | Update config |
| `GET`  | `/api/config/models` | List available models |
| `POST` | `/api/config/telegram/restart` | Restart Telegram bot with current config |
| `GET`  | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET`  | `/api/conversations/{id}` | Get conversation with messages |
| `DELETE` | `/api/conversations/{id}` | Delete conversation |
| `PATCH` | `/api/conversations/{id}/title` | Rename conversation |
| `POST` | `/api/conversations/{id}/chat` | Send message (SSE stream) |
| `POST` | `/api/conversations/{id}/approve` | Confirm / cancel a tool call |

Full interactive docs: **http://localhost:8000/docs**
