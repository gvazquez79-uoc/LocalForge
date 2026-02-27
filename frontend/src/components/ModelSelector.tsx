import { useEffect } from "react";
import { Cpu } from "lucide-react";
import { useChatStore } from "../store/chat";

export function ModelSelector() {
  const { models, selectedModel, setModel, loadModels } = useChatStore();

  useEffect(() => {
    loadModels();
  }, []);

  return (
    <div className="flex items-center gap-2">
      <Cpu size={13} className="text-zinc-500 flex-shrink-0" />
      <select
        value={selectedModel}
        onChange={(e) => setModel(e.target.value)}
        className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500 cursor-pointer"
      >
        {models.length === 0 ? (
          <option value={selectedModel}>{selectedModel}</option>
        ) : (
          models.map((m) => (
            <option key={m.name} value={m.name} disabled={!m.available}>
              {m.display_name} {!m.available ? "(no key)" : ""}
            </option>
          ))
        )}
      </select>
    </div>
  );
}
