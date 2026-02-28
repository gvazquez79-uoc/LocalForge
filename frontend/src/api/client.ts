const BASE = "http://localhost:8000/api";

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
  type: "text_delta" | "tool_call" | "tool_result" | "iteration" | "done" | "error" | "title_updated";
  data: Record<string, unknown>;
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listConversations(): Promise<Conversation[]> {
  const res = await fetch(`${BASE}/conversations`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getConversation(id: string): Promise<Conversation> {
  const res = await fetch(`${BASE}/conversations/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await fetch(`${BASE}/conversations/${id}`, { method: "DELETE" });
}

export async function renameConversation(id: string, title: string): Promise<void> {
  await fetch(`${BASE}/conversations/${id}/title`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
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
}

export async function getConfig(): Promise<LocalForgeConfig> {
  const res = await fetch(`${BASE}/config`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function saveConfig(
  data: Partial<Pick<LocalForgeConfig, "tools" | "agent" | "default_model">>
): Promise<void> {
  const res = await fetch(`${BASE}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await res.text());
}

// ── Models ───────────────────────────────────────────────────────────────────

export interface ModelsResponse {
  models: ModelInfo[];
  default_model: string;
}

export async function listModels(): Promise<ModelsResponse> {
  const res = await fetch(`${BASE}/config/models`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── Streaming chat ────────────────────────────────────────────────────────────

export function streamChat(
  convId: string,
  content: string,
  model: string,
  onEvent: (event: StreamEvent) => void,
  onDone: () => void,
  onError: (msg: string) => void
): () => void {
  let aborted = false;
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/conversations/${convId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, model }),
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
