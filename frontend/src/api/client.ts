// En desarrollo: http://localhost:8000/api
// En producción con nginx: /api  (misma IP/dominio, proxy inverso)
// Configurable con: VITE_API_BASE=https://tu-servidor.com/api npm run build
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000/api";

// ── API Key auth ──────────────────────────────────────────────────────────────
const STORAGE_KEY_AUTH = "localforge_api_key";

export function getApiKey(): string {
  return localStorage.getItem(STORAGE_KEY_AUTH) ?? "";
}

export function setApiKey(key: string): void {
  if (key) localStorage.setItem(STORAGE_KEY_AUTH, key);
  else localStorage.removeItem(STORAGE_KEY_AUTH);
}

/** Returns auth headers if a key is stored, empty object otherwise */
function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key } : {};
}

/** Check if the current key is valid (or if auth is disabled on the server) */
export async function checkAuth(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { headers: authHeaders() });
    return res.ok; // 200 = ok, 401 = wrong key
  } catch {
    return false; // backend offline
  }
}

export interface Conversation {
  id: string;
  title: string;
  model: string;
  created_at: number;
  updated_at: number;
  messages?: Message[];
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  metadata?: { tool_calls?: ToolCallData[] };
  created_at: number;
}

export interface ModelInfo {
  name: string;
  display_name: string;
  provider: string;
  available: boolean;
}

export interface StreamEvent {
  type: "text_delta" | "tool_call" | "tool_result" | "iteration" | "done" | "error" | "title_updated" | "tool_confirmation_needed";
  data: Record<string, unknown>;
}

export interface ToolConfirmationNeeded {
  tool_use_id: string;
  name: string;
  input: Record<string, unknown>;
  message: string;
}

export interface ToolCallData {
  id: string;
  name: string;
  input: Record<string, unknown>;
}

// ── Conversations ────────────────────────────────────────────────────────────

export async function createConversation(model: string): Promise<Conversation> {
  const res = await fetch(`${BASE}/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listConversations(): Promise<Conversation[]> {
  const res = await fetch(`${BASE}/conversations`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getConversation(id: string): Promise<Conversation> {
  const res = await fetch(`${BASE}/conversations/${id}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${BASE}/conversations/${id}`, { method: "DELETE", headers: authHeaders() });
}

export async function renameConversation(id: string, title: string): Promise<void> {
  await fetch(`${BASE}/conversations/${id}/title`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title }),
  });
}

export async function approveTool(convId: string, toolUseId: string, approved: boolean): Promise<void> {
  await fetch(`${BASE}/conversations/${convId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ tool_use_id: toolUseId, approved }),
  });
}

// ── Config ───────────────────────────────────────────────────────────────────

export interface LocalForgeConfig {
  version: string;
  default_model: string;
  tools: {
    filesystem: {
      enabled: boolean;
      allowed_paths: string[];
      require_confirmation_for: string[];
      max_file_size_mb: number;
    };
    terminal: {
      enabled: boolean;
      require_confirmation: boolean;
      timeout_seconds: number;
      blocked_patterns: string[];
    };
    web_search: {
      enabled: boolean;
      max_results: number;
    };
  };
  agent: {
    max_iterations: number;
    system_prompt: string;
  };
  telegram: {
    enabled: boolean;
    bot_token: string;
    allowed_user_ids: number[];
    default_model: string;
  };
}

export async function getConfig(): Promise<LocalForgeConfig> {
  const res = await fetch(`${BASE}/config`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveConfig(
  data: Partial<Pick<LocalForgeConfig, "tools" | "agent" | "default_model" | "telegram">>
): Promise<void> {
  const res = await fetch(`${BASE}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function restartTelegramBot(): Promise<{ ok: boolean; running: boolean }> {
  const res = await fetch(`${BASE}/config/telegram/restart`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Models ───────────────────────────────────────────────────────────────────

export interface ModelsResponse {
  models: ModelInfo[];
  default_model: string;
}

export async function listModels(): Promise<ModelsResponse> {
  const res = await fetch(`${BASE}/config/models`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Streaming chat ────────────────────────────────────────────────────────────

export interface ImagePayload {
  name: string;
  data_url: string;
  mime_type: string;
}

export function streamChat(
  convId: string,
  content: string,
  model: string,
  images: ImagePayload[] | undefined,
  onEvent: (event: StreamEvent) => void,
  onDone: () => void,
  onError: (msg: string) => void
): () => void {
  let aborted = false;
  const controller = new AbortController();

  (async () => {
    try {
      const body: Record<string, unknown> = { content, model };
      if (images && images.length > 0) body.images = images;

      const res = await fetch(`${BASE}/conversations/${convId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!res.ok) {
        onError(await res.text());
        return;
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!aborted) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (payload === "[DONE]") {
            onDone();
            return;
          }
          try {
            const event: StreamEvent = JSON.parse(payload);
            onEvent(event);
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e: unknown) {
      if (!aborted) onError(String(e));
    }
  })();

  return () => {
    aborted = true;
    controller.abort();
  };
}
