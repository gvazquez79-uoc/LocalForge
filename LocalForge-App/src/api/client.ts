// LocalForge API client for the mobile app

export interface ServerConfig {
  url: string;       // e.g. http://192.168.1.10:8000
  apiKey: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;   // epoch milliseconds
}

export interface Conversation {
  id: string;
  title: string;
  model: string;
  created_at: number;  // the backend stores unix SECONDS, not an ISO string
  updated_at: number;
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

// The backend middleware accepts the credential via X-API-Key, Authorization
// Bearer or ?api_key=, and tries to decode it as a JWT before falling back to
// the legacy API_KEY — so a single header works for both auth modes.
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

export async function createConversation(model: string): Promise<Conversation> {
  const res = await fetch(`${base()}/api/conversations`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ model, title: "Nueva conversación" }),
  });
  if (!res.ok) throw new Error(`No se pudo crear la conversación (${res.status})`);
  return res.json();
}

interface ApiMessage {
  id: string;
  role: string;
  content: unknown;
  created_at: number;
}

/** Flatten whatever the backend stored into plain text for the bubble list. */
function messageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((block) => {
        if (typeof block === "string") return block;
        if (block && typeof block === "object") {
          const b = block as Record<string, unknown>;
          if (b.type === "text") return String(b.text ?? "");
          if (b.type === "image") return "🖼️ [imagen]";
          if (b.type === "document") return "📄 [documento]";
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return content == null ? "" : String(content);
}

export async function getConversation(id: string): Promise<{ messages: Message[] }> {
  const res = await fetch(`${base()}/api/conversations/${id}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch conversation");
  const data = await res.json();
  const messages: Message[] = (data.messages as ApiMessage[])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      id: m.id,
      role: m.role as "user" | "assistant",
      content: messageText(m.content),
      timestamp: (m.created_at ?? 0) * 1000,
    }));
  return { messages };
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${base()}/api/conversations/${id}`, {
    method: "DELETE",
    headers: headers(),
  });
}

export async function approveTool(
  conversationId: string,
  toolUseId: string,
  approved: boolean,
): Promise<void> {
  await fetch(`${base()}/api/conversations/${conversationId}/approve`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ tool_use_id: toolUseId, approved }),
  });
}

// ── SSE Streaming chat ────────────────────────────────────────────────────────
export type StreamCallback = (event: { type: string; data: Record<string, unknown> }) => void;

/**
 * Stream one turn of a conversation.
 *
 * The backend exposes this per conversation — POST /api/conversations/{id}/chat
 * with { content, model, images } — and reads the history from the database, so
 * there is no need to replay it from the client. The stream terminates with a
 * literal `data: [DONE]` line; the `done` events that arrive before it are
 * emitted once per agent iteration and must NOT be treated as the end.
 */
export function sendMessage(
  conversationId: string,
  content: string,
  model: string,
  onEvent: StreamCallback,
  onDone: () => void,
  onError: (err: string) => void,
): () => void {
  const controller = new AbortController();

  fetch(`${base()}/api/conversations/${conversationId}/chat`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ content, model, images: [] }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`Server error ${res.status}`);
        return;
      }
      if (!res.body) {
        onError("El servidor no devolvió un stream");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();

          if (raw === "[DONE]") {
            finished = true;
            onDone();
            continue;
          }

          try {
            const payload = JSON.parse(raw);
            onEvent(payload);
          } catch {
            // ignore malformed lines
          }
        }
      }

      if (!finished) onDone();
    })
    .catch((err) => {
      if (err.name !== "AbortError") onError(String(err));
    });

  return () => controller.abort();
}
