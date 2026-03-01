import { create } from "zustand";
import type { Conversation, ModelInfo, StreamEvent, ToolCallData } from "../api/client";
import type { PendingConfirmation } from "../components/ConfirmationModal";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  listModels,
  renameConversation,
  streamChat,
  approveTool,
} from "../api/client";

// Exported so ChatWindow can use it
export interface ImagePayload {
  name: string;
  data_url: string;   // full data:mime;base64,... string
  mime_type: string;
}

export interface UIMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallData[];
  toolResults?: Record<string, string>; // tool_use_id → result
  isStreaming?: boolean;
  /** Binary attachments shown in the message bubble (images / PDFs) */
  attachments?: Array<{ name: string; dataUrl: string; isPdf: boolean }>;
}

interface ChatState {
  conversations: Conversation[];
  activeConvId: string | null;
  messages: UIMessage[];
  models: ModelInfo[];
  selectedModel: string;
  isLoading: boolean;
  error: string | null;
  pendingConfirmation: PendingConfirmation | null;

  loadConversations: () => Promise<void>;
  loadModels: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  newConversation: () => Promise<void>;
  deleteConv: (id: string) => Promise<void>;
  renameConv: (id: string, title: string) => Promise<void>;
  sendMessage: (content: string, images?: ImagePayload[]) => void;
  setModel: (model: string) => void;
  stopStream: (() => void) | null;
  approveConfirmation: () => void;
  rejectConfirmation: () => void;
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
  pendingConfirmation: null,

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
      .filter(m => m.role === "user" || m.role === "assistant")
      .map(m => ({
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
    set(s => ({
      conversations: [conv, ...s.conversations],
      activeConvId: conv.id,
      messages: [],
    }));
  },

  deleteConv: async (id: string) => {
    await deleteConversation(id);
    const { activeConvId } = get();
    set(s => ({
      conversations: s.conversations.filter(c => c.id !== id),
      activeConvId: activeConvId === id ? null : activeConvId,
      messages: activeConvId === id ? [] : s.messages,
    }));
  },

  renameConv: async (id: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    await renameConversation(id, trimmed);
    set(s => ({
      conversations: s.conversations.map(c => c.id === id ? { ...c, title: trimmed } : c),
    }));
  },

  setModel: (model: string) => {
    localStorage.setItem(STORAGE_KEY, model);
    set({ selectedModel: model });
  },

  approveConfirmation: async () => {
    const { pendingConfirmation, activeConvId } = get();
    if (pendingConfirmation && activeConvId) {
      await approveTool(activeConvId, pendingConfirmation.tool_use_id, true);
    }
    set({ pendingConfirmation: null });
  },

  rejectConfirmation: async () => {
    const { pendingConfirmation, activeConvId } = get();
    if (pendingConfirmation && activeConvId) {
      await approveTool(activeConvId, pendingConfirmation.tool_use_id, false);
    }
    set({ pendingConfirmation: null, isLoading: false });
  },

  sendMessage: (content: string, images?: ImagePayload[]) => {
    const { activeConvId, selectedModel, stopStream } = get();
    if (!activeConvId) return;

    stopStream?.();

    // Build attachment display info for the bubble
    const attachments = images?.map(img => ({
      name:    img.name,
      dataUrl: img.data_url,
      isPdf:   img.mime_type === "application/pdf",
    }));

    const userMsg: UIMessage = {
      id:   `user-${Date.now()}`,
      role: "user",
      content,
      attachments: attachments && attachments.length > 0 ? attachments : undefined,
    };

    const assistantMsg: UIMessage = {
      id:          `assistant-${Date.now()}`,
      role:        "assistant",
      content:     "",
      toolCalls:   [],
      toolResults: {},
      isStreaming: true,
    };

    set(s => ({
      messages: [...s.messages, userMsg, assistantMsg],
      isLoading: true,
      error: null,
    }));

    const cancel = streamChat(
      activeConvId,
      content,
      selectedModel,
      images,
      (event: StreamEvent) => {
        if (event.type === "title_updated") {
          const newTitle = (event.data as { title: string }).title;
          set(s => ({
            conversations: s.conversations.map(c =>
              c.id === activeConvId ? { ...c, title: newTitle } : c
            ),
          }));
          return;
        }

        if (event.type === "tool_confirmation_needed") {
          const confirmation = event.data as PendingConfirmation;
          set({ pendingConfirmation: confirmation, isLoading: false });
          return;
        }

        if (event.type === "tool_result") {
          const { pendingConfirmation } = get();
          if (pendingConfirmation) set({ pendingConfirmation: null });
        }

        set(s => {
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
            updated.toolResults = { ...(updated.toolResults ?? {}), [tr.tool_use_id]: tr.result };
          }

          msgs[msgs.length - 1] = updated;
          return { messages: msgs };
        });
      },
      () => {
        set(s => {
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
