import { useEffect } from "react";
import { Cpu, WifiOff, Settings } from "lucide-react";
import { useChatStore } from "../store/chat";

export function ModelSelector({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const { models, selectedModel, setModel, loadModels, error, modelsLoading } = useChatStore();

  useEffect(() => {
    loadModels();
    // Retry every 5s if backend is offline
    const interval = setInterval(() => {
      if (useChatStore.getState().error === "backend_offline") {
        loadModels();
      }
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  if (error === "backend_offline") {
    return (
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-sm bg-red-50 border border-red-200 dark:bg-red-950 dark:border-red-800">
        <WifiOff size={13} className="text-red-500 dark:text-red-400 flex-shrink-0" />
        <span className="text-xs text-red-500 dark:text-red-400">Backend offline</span>
      </div>
    );
  }

  // Still fetching on first load
  if (modelsLoading && models.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <Cpu size={13} className="text-gray-400 dark:text-zinc-500 flex-shrink-0" />
        <span className="text-xs text-gray-400 dark:text-zinc-500 italic">Cargando…</span>
      </div>
    );
  }

  // Loaded but no models configured
  if (!modelsLoading && models.length === 0) {
    return (
      <button
        onClick={onOpenSettings}
        className="flex items-center gap-2 w-full px-2 py-1.5 rounded-sm border border-dashed border-gray-300 dark:border-zinc-700 text-gray-400 dark:text-zinc-500 hover:border-emerald-400 hover:text-lime-500 dark:hover:text-emerald-400 transition-colors"
      >
        <Settings size={13} className="flex-shrink-0" />
        <span className="text-xs">Sin modelos — añadir en Settings</span>
      </button>
    );
  }

  // Group models by provider for better organization
  const groupedModels = models.reduce((acc, m) => {
    const provider = m.provider || "otro";
    if (!acc[provider]) acc[provider] = [];
    acc[provider].push(m);
    return acc;
  }, {} as Record<string, typeof models>);

  const providerLabels: Record<string, string> = {
    anthropic: "🤖 Anthropic (Claude)",
    ollama: "🦙 Ollama (Local)",
    openai: "🔵 OpenAI",
    groq: "⚡ Groq",
    openrouter: "🌐 OpenRouter",
    together: "👥 Together.ai",
    mistral: "🟠 Mistral",
    deepseek: "🧠 DeepSeek",
    otro: "📌 Otro",
  };

  return (
    <div className="flex items-center gap-2">
      <Cpu size={13} className="text-gray-400 dark:text-zinc-500 flex-shrink-0" />
      <select
        value={selectedModel}
        onChange={(e) => setModel(e.target.value)}
        className="flex-1 bg-white border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-sm px-2 py-1.5 text-xs text-gray-700 dark:text-zinc-300 focus:outline-none focus:border-emerald-500 cursor-pointer"
      >
        {Object.entries(groupedModels).map(([provider, providerModels]) => (
          <optgroup key={provider} label={providerLabels[provider] || provider}>
            {providerModels.map((m) => (
              <option key={m.name} value={m.name} disabled={!m.available}>
                {m.display_name}{!m.available ? " (sin clave)" : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
