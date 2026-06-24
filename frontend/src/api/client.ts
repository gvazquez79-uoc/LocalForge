// En desarrollo: http://localhost:8000/api
// En producción con nginx: /api  (misma IP/dominio, proxy inverso)
// Configurable con: VITE_API_BASE=https://tu-servidor.com/api npm run build
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000/api";

// ── Auth token (JWT or legacy API key) ───────────────────────────────────────
const STORAGE_KEY_AUTH = "localforge_api_key";  // kept for compat
const STORAGE_KEY_JWT  = "localforge_jwt";
const STORAGE_KEY_USER = "localforge_user";

export function getApiKey(): string {
  return localStorage.getItem(STORAGE_KEY_JWT)
      ?? localStorage.getItem(STORAGE_KEY_AUTH)
      ?? "";
}

export function setApiKey(key: string): void {
  if (key) localStorage.setItem(STORAGE_KEY_AUTH, key);
  else localStorage.removeItem(STORAGE_KEY_AUTH);
}

export function setJwt(token: string, persist = true): void {
  if (token) {
    // If remember=true → localStorage (survives browser close)
    // If remember=false → sessionStorage (cleared on tab/window close)
    if (persist) localStorage.setItem(STORAGE_KEY_JWT, token);
    else sessionStorage.setItem(STORAGE_KEY_JWT, token);
  } else {
    localStorage.removeItem(STORAGE_KEY_JWT);
    sessionStorage.removeItem(STORAGE_KEY_JWT);
  }
}

export function getJwt(): string {
  return localStorage.getItem(STORAGE_KEY_JWT)
      ?? sessionStorage.getItem(STORAGE_KEY_JWT)
      ?? "";
}

export function getStoredUser(): User | null {
  const raw = localStorage.getItem(STORAGE_KEY_USER);
  if (!raw) return null;
  try { return JSON.parse(raw) as User; } catch { return null; }
}

export function setStoredUser(user: User | null): void {
  if (user) localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user));
  else localStorage.removeItem(STORAGE_KEY_USER);
}

export function clearAuth(): void {
  localStorage.removeItem(STORAGE_KEY_JWT);
  sessionStorage.removeItem(STORAGE_KEY_JWT);
  localStorage.removeItem(STORAGE_KEY_AUTH);
  localStorage.removeItem(STORAGE_KEY_USER);
}

/** Returns auth headers — uses JWT if available, falls back to API key */
function authHeaders(): Record<string, string> {
  const token = getJwt() || getApiKey();
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

async function readErrorMessage(res: Response): Promise<string> {
  const text = await res.text();
  if (!text) return `HTTP ${res.status}`;
  try {
    const data = JSON.parse(text) as { detail?: string; error?: string; message?: string };
    return data.detail || data.error || data.message || text;
  } catch {
    return text;
  }
}

// ── User types ────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  is_admin: number;
  created_at: string;
  totp_enabled?: number;
}

// ── Auth API ──────────────────────────────────────────────────────────────────
export interface LoginResponse {
  token?: string;
  user?: User;
  totp_required?: boolean;
  temp_token?: string;
}

export async function login(email: string, password: string, remember: boolean): Promise<LoginResponse> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, remember }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json();
}

export async function requestPasswordReset(email: string, reset_url_base: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/auth/password-reset/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, reset_url_base }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json();
}

export async function confirmPasswordReset(token: string, password: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/auth/password-reset/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json();
}

export async function setupFirstUser(data: { first_name: string; last_name: string; email: string; password: string }): Promise<{ token: string; user: User }> {
  const res = await fetch(`${BASE}/auth/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getMe(): Promise<User> {
  const res = await fetch(`${BASE}/auth/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── 2FA / TOTP API ────────────────────────────────────────────────────────────

/** Exchange a TOTP challenge token + 6-digit code for a full JWT. */
export async function verifyTotp(temp_token: string, code: string): Promise<{ token: string; user: User }> {
  const res = await fetch(`${BASE}/auth/totp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ temp_token, code }),
  });
  if (!res.ok) throw new Error(await readErrorMessage(res));
  return res.json();
}

/** Generate a new TOTP secret and return the QR code (base64 PNG). */
export async function setupTotp(): Promise<{ secret: string; qr_uri: string; qr_image_b64: string }> {
  const res = await fetch(`${BASE}/auth/totp/setup`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Confirm the first TOTP code to activate 2FA. */
export async function confirmTotp(code: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/auth/totp/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Disable 2FA after verifying the current TOTP code. */
export async function disableTotp(code: string): Promise<{ ok: boolean; message: string }> {
  const res = await fetch(`${BASE}/auth/totp/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Users CRUD ────────────────────────────────────────────────────────────────
export async function listUsers(): Promise<User[]> {
  const res = await fetch(`${BASE}/users`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createUser(data: {
  first_name: string; last_name: string; email: string;
  password?: string; is_admin?: boolean;
}): Promise<User & { generated_password?: string }> {
  const res = await fetch(`${BASE}/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateUser(id: string, data: Partial<{
  first_name: string; last_name: string; email: string;
  password: string; is_admin: boolean;
}>): Promise<User> {
  const res = await fetch(`${BASE}/users/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteUser(id: string): Promise<void> {
  const res = await fetch(`${BASE}/users/${id}`, {
    method: "DELETE", headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function generatePassword(): Promise<string> {
  const res = await fetch(`${BASE}/users/generate-password`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.password;
}

export type AuthCheckResult = "ok" | "auth_required" | "setup_required" | "offline";

/** fetch with an AbortController timeout so it never hangs indefinitely */
async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 5000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** Check if the current token is valid (or if auth is disabled on the server) */
export async function checkAuth(): Promise<AuthCheckResult> {
  try {
    // 1. Ask the server if auth is required at all
    const statusRes = await fetchWithTimeout(`${BASE}/auth/status`);
    console.log("[checkAuth] /auth/status →", statusRes.status);
    if (!statusRes.ok) return "offline";
    const status = await statusRes.json() as { required: boolean; setup?: boolean };
    console.log("[checkAuth] status =", status);

    if (!status.required) return "ok";

    // No users yet — show setup screen
    if (status.setup) return "setup_required";

    // 2. Auth is required — validate stored JWT
    const token = getJwt();
    console.log("[checkAuth] token presente =", !!token);
    if (!token) return "auth_required";

    const meRes = await fetchWithTimeout(`${BASE}/auth/me`, { headers: authHeaders() });
    console.log("[checkAuth] /auth/me →", meRes.status);
    if (meRes.ok) return "ok";

    // JWT invalid/expired — clear it
    setJwt("");
    return "auth_required";
  } catch (err) {
    console.error("[checkAuth] excepción:", err);
    return "offline";
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
  working_directory?: string | null;
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
  type: "text_delta" | "tool_call" | "tool_result" | "iteration" | "done" | "error" | "warning" | "title_updated" | "tool_confirmation_needed" | "clear_content" | "usage" | "compacting";
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

export async function setWorkingDirectory(id: string, working_directory: string | null): Promise<void> {
  await fetch(`${BASE}/conversations/${id}/working_directory`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ working_directory }),
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
    video: {
      enabled: boolean;
      ffmpeg_path: string;
    };
    replicate: {
      enabled: boolean;
      api_key: string;
      default_image_model: string;
      default_video_model: string;
    };
    attachments: {
      max_image_mb: number;
      max_pdf_mb: number;
      max_text_kb: number;
    };
  };
  agent: {
    max_iterations: number;
    memory_file: string;
    system_prompt: string;
    compact_threshold: number;
  };
  telegram: {
    enabled: boolean;
    bot_token: string;
    allowed_user_ids: number[];
    default_model: string;
  };
  smtp: {
    enabled: boolean;
    host: string;
    port: number;
    username: string;
    password: string;
    from_email: string;
    from_name: string;
    use_tls: boolean;
    use_ssl: boolean;
  };
}

export async function getConfig(): Promise<LocalForgeConfig> {
  const res = await fetch(`${BASE}/config`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveConfig(
  data: Partial<Pick<LocalForgeConfig, "tools" | "agent" | "default_model" | "telegram" | "smtp">>
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

export async function getMemory(): Promise<{ content: string; path: string }> {
  const res = await fetch(`${BASE}/config/memory`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function clearMemory(): Promise<void> {
  const res = await fetch(`${BASE}/config/memory`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export interface ProjectInstructions {
  content: string;
  filename: string;
  path: string;
  exists: boolean;
}

export async function getProjectInstructions(workingDirectory: string): Promise<ProjectInstructions> {
  const res = await fetch(
    `${BASE}/config/project-instructions?working_directory=${encodeURIComponent(workingDirectory)}`,
    { headers: authHeaders() }
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveProjectInstructions(
  workingDirectory: string,
  content: string,
  filename = "LOCALFORGE.md"
): Promise<void> {
  const res = await fetch(`${BASE}/config/project-instructions`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ working_directory: workingDirectory, content, filename }),
  });
  if (!res.ok) throw new Error(await res.text());
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

export interface DiscoveredModel {
  name: string;
  display_name: string;
  provider: string;
  available: boolean;
  base_url: string;
  already_configured: boolean;
}

export async function discoverOllamaModels(): Promise<DiscoveredModel[]> {
  const res = await fetch(`${BASE}/config/models/discover`, { headers: authHeaders() });
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
  system_prompt: string | null;
  temperature: number | null;
}

export interface DbModelCreate {
  name: string;
  display_name: string;
  provider: string;
  api_key?: string;
  base_url?: string;
  is_default?: boolean;
  system_prompt?: string | null;
  temperature?: number | null;
}

export interface DbModelUpdate {
  name?: string;
  display_name?: string;
  provider?: string;
  api_key?: string | null;     // null = keep, "" = clear
  base_url?: string | null;
  is_default?: boolean;
  system_prompt?: string | null; // null = keep, "" = clear
  temperature?: number | null;
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

export interface DiscoverModelsResult {
  ok: boolean;
  discovered: number;
  saved: number;
  models: Array<{ name: string; display_name: string }>;
}

export async function discoverProviderModels(providerName: string): Promise<DiscoverModelsResult> {
  const res = await fetch(`${BASE}/config/providers/${providerName}/discover-models`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Providers (CRUD) ──────────────────────────────────────────────────────────

export interface DbProvider {
  id: string;
  name: string;
  display_name: string;
  base_url: string;
  api_key_env: string;
  api_key_masked: string | null;  // e.g. "****abcd" — null if no key set
  is_builtin: boolean;
}

export interface DbProviderCreate {
  name: string;
  display_name: string;
  base_url?: string;
  api_key_env?: string;
  api_key?: string;
}

export interface DbProviderUpdate {
  name?: string;
  display_name?: string;
  base_url?: string;
  api_key_env?: string;
  api_key?: string;  // empty string = keep existing key unchanged
}

export async function listProviders(): Promise<DbProvider[]> {
  const res = await fetch(`${BASE}/providers`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createProvider(data: DbProviderCreate): Promise<DbProvider> {
  const res = await fetch(`${BASE}/providers`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function updateProvider(id: string, data: DbProviderUpdate): Promise<DbProvider> {
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

// ── Auto-update ───────────────────────────────────────────────────────────────

export interface UpdateCheckResult {
  update_available: boolean;
  local_commit?: string;
  remote_commit?: string;
  commits?: string[];
  error?: string;
}

export async function checkUpdate(): Promise<UpdateCheckResult> {
  const res = await fetch(`${BASE}/update/check`, { headers: authHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function applyUpdate(): Promise<{ ok: boolean; output?: string; error?: string }> {
  const res = await fetch(`${BASE}/update/apply`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
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
