import { create } from "zustand";
import type { Conversation, ModelInfo, StreamEvent, ToolCallData } from "../api/client";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  listModels,
  streamChat,
} from "../api/client";


export interface UIMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallData[];
  toolResults?: Record<string, string>; // tool_use_id → result
  isStreaming?: boolean;
}

interface ChatState {
  conversations: Conversation[];
  activeConvId: string | null;
  messages: UIMessage[];
  models: ModelInfo[];
  selectedModel: string;
  isLoading: boolean;
  error: string | null;

  loadConversations: () => Promise<void>;
  loadModels: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  newConversation: () => Promise<void>;
  deleteConv: (id: string) => Promise<void>;
  sendMessage: (content: string) => void;
  setModel: (model: string) => void;
  stopStream: (() => void) | null;
}

const STORAGE_KEY = "localforge_selected_model";

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  activeConvId: null,
  messages: [],
  models: [],
  selectedModel: localStorage.getItem(STORAGE_KEY) ?? "",
  isLoading: false,
  error: null,
  stopStream: null,

  loadConversations: async () => {
    const conversations = await listConversations();
    set({ conversations });
  },

  loadModels: async () => {
    try {
      const { models, default_model } = await listModels();
      const currentSelected = get().selectedModel;
      set({ models, error: null });
      if (!currentSelected) {
        localStorage.setItem(STORAGE_KEY, default_model);
        set({ selectedModel: default_model });
      }
    } catch {
      set({ error: "backend_offline" });
    }
  },

  selectConversation: async (id: string) => {
    const conv = await getConversation(id);
    const messages: UIMessage[] = (conv.messages ?? [])
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({
        id: m.id,
        role: m.role as "user" | "assistant",
        content: typeof m.content === "string" ? m.content : JSON.stringify(m.content),
        toolCalls: m.metadata?.tool_calls,
      }));
    set({ activeConvId: id, messages });
  },

  newConversation: async () => {
    const { selectedModel } = get();
    const conv = await createConversation(selectedModel);
    set((s) => ({
      conversations: [conv, ...s.conversations],
      activeConvId: conv.id,
      messages: [],
    }));
  },

  deleteConv: async (id: string) => {
    await deleteConversation(id);
    const { activeConvId } = get();
    set((s) => ({
      conversations: s.conversations.filter((c) => c.id !== id),
      activeConvId: activeConvId === id ? null : activeConvId,
      messages: activeConvId === id ? [] : s.messages,
    }));
  },

  setModel: (model: string) => {
    localStorage.setItem(STORAGE_KEY, model);
    set({ selectedModel: model });
  },

  sendMessage: (content: string) => {
    const { activeConvId, selectedModel, stopStream } = get();
    if (!activeConvId) return;

    // Stop any existing stream
    stopStream?.();

    const userMsg: UIMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content,
    };

    const assistantMsg: UIMessage = {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      content: "",
      toolCalls: [],
      toolResults: {},
      isStreaming: true,
    };

    set((s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      isLoading: true,
      error: null,
    }));

    const cancel = streamChat(
      activeConvId,
      content,
      selectedModel,
      (event: StreamEvent) => {
        set((s) => {
          const msgs = [...s.messages];
          const last = msgs[msgs.length - 1];
          if (!last || last.role !== "assistant") return {};

          const updated = { ...last };

          if (event.type === "text_delta") {
            updated.content += (event.data as { text: string }).text;
          } else if (event.type === "tool_call") {
            const tc = event.data as unknown as ToolCallData;
            updated.toolCalls = [...(updated.toolCalls ?? []), tc];
          } else if (event.type === "tool_result") {
            const tr = event.data as { tool_use_id: string; result: string };
            updated.toolResults = {
              ...(updated.toolResults ?? {}),
              [tr.tool_use_id]: tr.result,
            };
          }

          msgs[msgs.length - 1] = updated;
          return { messages: msgs };
        });
      },
      () => {
        set((s) => {
          const msgs = [...s.messages];
          const last = msgs[msgs.length - 1];
          if (last?.role === "assistant") {
            msgs[msgs.length - 1] = { ...last, isStreaming: false };
          }
          return { messages: msgs, isLoading: false, stopStream: null };
        });
      },
      (msg: string) => {
        set({ isLoading: false, error: msg, stopStream: null });
      }
    );

    set({ stopStream: cancel });
  },
}));
