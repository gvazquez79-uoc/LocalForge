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

export interface HealthStatus {
  api_ok: boolean;
  db_ok: boolean;
  db_type: string;
}

/** Full health check including DB status */
export async function checkHealth(): Promise<HealthStatus> {
  try {
    const res = await fetch(`${BASE}/health`, { headers: authHeaders() });
    if (!res.ok) return { api_ok: false, db_ok: false, db_type: "unknown" };
    const data = await res.json();
    return { api_ok: true, db_ok: data.db_ok ?? false, db_type: data.db_type ?? "unknown" };
  } catch {
    return { api_ok: false, db_ok: false, db_type: "unknown" };
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
  type: "text_delta" | "tool_call" | "tool_result" | "iteration" | "done" | "error" | "warning" | "title_updated" | "tool_confirmation_needed";
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

// ── Models (selector) ────────────────────────────────────────────────────────

export interface ModelsResponse {
  models: ModelInfo[];
  default_model: string;
}

export async function listModels(): Promise<ModelsResponse> {
  const res = await fetch(`${BASE}/config/models`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── DB Models (CRUD) ──────────────────────────────────────────────────────────

export interface DbModel {
  id: string;
  name: string;
  display_name: string;
  provider: string;
  api_key_masked: string | null;
  base_url: string | null;
  is_default: boolean;
}

export interface DbModelCreate {
  name: string;
  display_name: string;
  provider: string;
  api_key?: string;
  base_url?: string;
  is_default?: boolean;
}

export interface DbModelUpdate {
  name?: string;
  display_name?: string;
  provider?: string;
  api_key?: string | null;  // null = keep, "" = clear
  base_url?: string | null;
  is_default?: boolean;
}

export async function listDbModels(): Promise<DbModel[]> {
  const res = await fetch(`${BASE}/models`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createDbModel(data: DbModelCreate): Promise<DbModel> {
  const res = await fetch(`${BASE}/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateDbModel(id: string, data: DbModelUpdate): Promise<DbModel> {
  const res = await fetch(`${BASE}/models/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteDbModel(id: string): Promise<void> {
  const res = await fetch(`${BASE}/models/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function setDefaultDbModel(id: string): Promise<DbModel> {
  const res = await fetch(`${BASE}/models/${id}/default`, {
    method: "PATCH",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface TestModelResult {
  ok: boolean;
  response?: string;
  error?: string;
}

export async function testDbModel(id: string): Promise<TestModelResult> {
  const res = await fetch(`${BASE}/models/${id}/test`, {
    method: "POST",
    headers: authHeaders(),
  });
  return res.json();
}

// ── Providers (CRUD) ──────────────────────────────────────────────────────────

export interface DbProvider {
  id: string;
  name: string;
  display_name: string;
  base_url: string;
  api_key_env: string;
  is_builtin: boolean;
}

export async function listProviders(): Promise<DbProvider[]> {
  const res = await fetch(`${BASE}/providers`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createProvider(data: { name: string; display_name: string; base_url?: string; api_key_env?: string }): Promise<DbProvider> {
  const res = await fetch(`${BASE}/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateProvider(id: string, data: Partial<{ name: string; display_name: string; base_url: string; api_key_env: string }>): Promise<DbProvider> {
  const res = await fetch(`${BASE}/providers/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteProvider(id: string): Promise<void> {
  const res = await fetch(`${BASE}/providers/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── System stats ──────────────────────────────────────────────────────────────

export interface GpuStats {
  name: string;
  percent: number;
  vram_used_gb: number;
  vram_total_gb: number;
}

export interface OllamaModel {
  name: string;
  size_gb: number;
  vram_gb: number;
  gpu_percent: number;  // 100 = full GPU, 0 = full CPU
  params: string;
  quant: string;
}

export interface SystemStats {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  ram_percent: number;
  gpu: GpuStats | null;
  ollama_models: OllamaModel[];
}

export async function getStats(): Promise<SystemStats | null> {
  try {
    const res = await fetch(`${BASE}/stats`, { headers: authHeaders() });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
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
