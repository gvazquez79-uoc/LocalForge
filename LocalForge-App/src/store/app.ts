import { create } from "zustand";
import type { Message, Model, Conversation } from "../api/client";

interface AppState {
  // Auth
  isLoggedIn: boolean;
  serverUrl: string;
  setLoggedIn: (v: boolean, url?: string) => void;

  // Models
  models: Model[];
  activeModel: string;
  setModels: (m: Model[]) => void;
  setActiveModel: (name: string) => void;

  // Conversations
  conversations: Conversation[];
  activeConvId: string | null;
  setConversations: (c: Conversation[]) => void;
  setActiveConvId: (id: string | null) => void;

  // Messages (current conversation)
  messages: Message[];
  setMessages: (msgs: Message[]) => void;
  appendChunk: (chunk: string) => void;
  addUserMessage: (content: string) => void;
  startAssistantMessage: () => void;
  clearPendingAssistant: () => void;

  // Loading state
  isStreaming: boolean;
  setStreaming: (v: boolean) => void;
}

let _msgId = 0;
const nextId = () => `msg_${++_msgId}_${Date.now()}`;

export const useAppStore = create<AppState>((set, get) => ({
  isLoggedIn: false,
  serverUrl: "",
  setLoggedIn: (v, url) => set({ isLoggedIn: v, serverUrl: url ?? get().serverUrl }),

  models: [],
  activeModel: "",
  setModels: (models) => set({ models }),
  setActiveModel: (name) => set({ activeModel: name }),

  conversations: [],
  activeConvId: null,
  setConversations: (conversations) => set({ conversations }),
  setActiveConvId: (id) => set({ activeConvId: id }),

  messages: [],
  setMessages: (messages) => set({ messages }),

  addUserMessage: (content) => set((s) => ({
    messages: [...s.messages, {
      id: nextId(), role: "user", content, timestamp: Date.now(),
    }],
  })),

  startAssistantMessage: () => set((s) => ({
    messages: [...s.messages, {
      id: nextId(), role: "assistant", content: "", timestamp: Date.now(),
    }],
  })),

  appendChunk: (chunk) => set((s) => {
    const msgs = [...s.messages];
    const last = msgs[msgs.length - 1];
    if (last?.role === "assistant") {
      msgs[msgs.length - 1] = { ...last, content: last.content + chunk };
    }
    return { messages: msgs };
  }),

  clearPendingAssistant: () => set((s) => {
    const msgs = [...s.messages];
    if (msgs[msgs.length - 1]?.role === "assistant" && msgs[msgs.length - 1].content === "") {
      msgs.pop();
    }
    return { messages: msgs };
  }),

  isStreaming: false,
  setStreaming: (v) => set({ isStreaming: v }),
}));
