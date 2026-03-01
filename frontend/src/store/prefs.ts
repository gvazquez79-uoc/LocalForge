import { create } from "zustand";

const KEY = "localforge_prefs";

interface PrefsState {
  renderMarkdown: boolean;
  setRenderMarkdown: (v: boolean) => void;
  showToolCalls: boolean;
  setShowToolCalls: (v: boolean) => void;
}

function load(): Partial<PrefsState> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

function save(patch: Partial<PrefsState>) {
  localStorage.setItem(KEY, JSON.stringify({ ...load(), ...patch }));
}

export const usePrefs = create<PrefsState>((set) => ({
  renderMarkdown: (load().renderMarkdown as boolean) ?? true,
  setRenderMarkdown: (v) => {
    save({ renderMarkdown: v });
    set({ renderMarkdown: v });
  },
  showToolCalls: (load().showToolCalls as boolean) ?? true,
  setShowToolCalls: (v) => {
    save({ showToolCalls: v });
    set({ showToolCalls: v });
  },
}));
