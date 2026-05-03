// LocalForge API client for the mobile app

export interface ServerConfig {
  url: string;       // e.g. http://192.168.1.10:8000
  apiKey: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Model {
  id: string;
  name: string;
  display_name: string;
  provider: string;
  is_default: boolean;
}

// ── Storage keys ──────────────────────────────────────────────────────────────
const KEY_URL    = "lf_server_url";
const KEY_APIKEY = "lf_api_key";
const KEY_MODEL  = "lf_model";

export function saveServerConfig(cfg: ServerConfig) {
  localStorage.setItem(KEY_URL, cfg.url.replace(/\/$/, ""));
  localStorage.setItem(KEY_APIKEY, cfg.apiKey);
}

export function loadServerConfig(): ServerConfig | null {
  const url    = localStorage.getItem(KEY_URL);
  const apiKey = localStorage.getItem(KEY_APIKEY);
  if (!url) return null;
  return { url, apiKey: apiKey ?? "" };
}

export function clearServerConfig() {
  localStorage.removeItem(KEY_URL);
  localStorage.removeItem(KEY_APIKEY);
  localStorage.removeItem(KEY_MODEL);
}

export function saveModel(name: string) {
  localStorage.setItem(KEY_MODEL, name);
}

export function loadModel(): string | null {
  return localStorage.getItem(KEY_MODEL);
}

// ── API helpers ───────────────────────────────────────────────────────────────
function base(): string {
  return localStorage.getItem(KEY_URL) ?? "";
}

function headers(): Record<string, string> {
  const key = localStorage.getItem(KEY_APIKEY) ?? "";
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (key) h["X-API-Key"] = key;
  return h;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${base()}/api/health`, {
      headers: headers(),
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function listModels(): Promise<Model[]> {
  const res = await fetch(`${base()}/api/models`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

export async function listConversations(): Promise<Conversation[]> {
  const res = await fetch(`${base()}/api/conversations`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch conversations");
  return res.json();
}

export async function getConversation(id: string): Promise<{ messages: Message[] }> {
  const res = await fetch(`${base()}/api/conversations/${id}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch conversation");
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${base()}/api/conversations/${id}`, {
    method: "DELETE",
    headers: headers(),
  });
}

// ── SSE Streaming chat ────────────────────────────────────────────────────────
export type StreamCallback = (event: { type: string; data: Record<string, unknown> }) => void;

export function sendMessage(
  messages: Array<{ role: string; content: string }>,
  model: string,
  conversationId: string | null,
  onEvent: StreamCallback,
  onDone: (convId: string) => void,
  onError: (err: string) => void,
): () => void {
  const controller = new AbortController();

  const h = headers();
  delete h["Content-Type"]; // fetch sets it for SSE

  fetch(`${base()}/api/chat`, {
    method: "POST",
    headers: { ...headers() },
    body: JSON.stringify({
      messages,
      model,
      conversation_id: conversationId,
      stream: true,
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`Server error ${res.status}`);
        return;
      }
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let newConvId = conversationId ?? "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.type === "conversation_id") {
                newConvId = payload.data.id ?? newConvId;
              }
              onEvent(payload);
              if (payload.type === "done") {
                onDone(newConvId);
              }
            } catch {
              // ignore malformed lines
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return () => controller.abort();
}
