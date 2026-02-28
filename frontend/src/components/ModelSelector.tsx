import { useEffect } from "react";
import { Cpu, WifiOff } from "lucide-react";
import { useChatStore } from "../store/chat";

export function ModelSelector() {
  const { models, selectedModel, setModel, loadModels, error } = useChatStore();

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
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-red-950 border border-red-800">
        <WifiOff size={13} className="text-red-400 flex-shrink-0" />
        <span className="text-xs text-red-400">Backend offline</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Cpu size={13} className="text-zinc-500 flex-shrink-0" />
      <select
        value={selectedModel}
        onChange={(e) => setModel(e.target.value)}
        disabled={models.length === 0}
        className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500 cursor-pointer disabled:opacity-50"
      >
        {models.length === 0 ? (
          <option value="">Cargando modelos…</option>
        ) : (
          models.map((m) => (
            <option key={m.name} value={m.name} disabled={!m.available}>
              {m.display_name}{!m.available ? " (sin clave)" : ""}
            </option>
          ))
        )}
      </select>
    </div>
  );
}
