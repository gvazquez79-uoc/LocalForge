# LocalForge 🔨

Local AI agent with filesystem, terminal, and web search access.
Multi-model: Claude, Ollama, OpenAI-compatible.

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

Edit `localforge.json` to customize models, tools, and allowed paths.

### 2. Install dependencies

```bash
# Python backend
py -3 -m pip install -e .

# Frontend
cd frontend && npm install
```

### 3. Run

```bash
# Windows — double-click or:
start.bat

# Manual:
# Terminal 1 — Backend
py -3 -m uvicorn backend.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Open **http://localhost:5173**

## Configuration (`localforge.json`)

| Field | Description |
|-------|-------------|
| `default_model` | Model used by default |
| `models[].provider` | `anthropic` \| `ollama` \| `openai` |
| `tools.filesystem.allowed_paths` | Directories the agent can access |
| `tools.terminal.require_confirmation` | Ask before running commands |
| `tools.filesystem.require_confirmation_for` | Ask before write/delete |

## Using Ollama

1. Install [Ollama](https://ollama.ai) and pull a model: `ollama pull llama3.2`
2. Add to `localforge.json`:
```json
{
  "name": "llama3.2",
  "display_name": "Llama 3.2 (local)",
  "provider": "ollama",
  "base_url": "http://localhost:11434/v1"
}
```
3. Select it in the UI model dropdown

## API

- `GET  /api/health` — health check
- `GET  /api/config/models` — list models
- `POST /api/conversations` — create conversation
- `GET  /api/conversations` — list conversations
- `POST /api/conversations/{id}/chat` — send message (SSE stream)
- Full docs: http://localhost:8000/docs
