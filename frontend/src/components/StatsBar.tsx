import { useEffect, useState } from "react";
import { Cpu, MemoryStick, Layers, BrainCircuit } from "lucide-react";
import { getStats } from "../api/client";
import type { SystemStats, OllamaModel } from "../api/client";
import { useChatStore } from "../store/chat";

// ── Shared bar ────────────────────────────────────────────────────────────────

function Bar({ percent, color }: { percent: number; color: string }) {
  return (
    <div className="flex-1 h-1 rounded-full bg-gray-200 dark:bg-zinc-700 overflow-hidden">
      <div
        className={`h-full rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${Math.min(percent, 100)}%` }}
      />
    </div>
  );
}

function StatRow({
  icon,
  label,
  percent,
  detail,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  percent: number;
  detail: string;
  color: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-gray-400 dark:text-zinc-500 flex-shrink-0">{icon}</span>
      <span className="text-[10px] text-gray-400 dark:text-zinc-500 w-7 flex-shrink-0">{label}</span>
      <Bar percent={percent} color={color} />
      <span className="text-[10px] text-gray-400 dark:text-zinc-500 w-14 text-right flex-shrink-0 tabular-nums">
        {detail}
      </span>
    </div>
  );
}

function barColor(percent: number): string {
  if (percent >= 90) return "bg-red-500";
  if (percent >= 70) return "bg-yellow-400";
  return "bg-emerald-500";
}

// ── Ollama model row ──────────────────────────────────────────────────────────

function processorLabel(gpuPct: number): string {
  if (gpuPct === 100) return "GPU";
  if (gpuPct === 0)   return "CPU";
  return `${gpuPct}% GPU`;
}

function processorColor(gpuPct: number): string {
  if (gpuPct >= 80) return "text-emerald-500 dark:text-emerald-400";
  if (gpuPct >= 30) return "text-yellow-500 dark:text-yellow-400";
  return "text-red-500 dark:text-red-400";
}

function OllamaRow({ model }: { model: OllamaModel }) {
  const shortName = model.name.split(":")[0];
  const tag       = model.name.split(":")[1] ?? "latest";
  const detail    = [model.params, model.quant].filter(Boolean).join(" · ");

  return (
    <div className="flex items-start gap-1.5 py-0.5">
      <BrainCircuit size={11} className="text-emerald-400 dark:text-lime-500 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1 min-w-0">
          <span className="text-[10px] font-medium text-gray-600 dark:text-zinc-300 truncate">{shortName}</span>
          <span className="text-[9px] text-gray-400 dark:text-zinc-600 flex-shrink-0">{tag}</span>
        </div>
        {detail && (
          <div className="text-[9px] text-gray-400 dark:text-zinc-600">{detail}</div>
        )}
      </div>
      <div className="flex flex-col items-end flex-shrink-0 gap-0.5">
        <span className={`text-[10px] font-medium ${processorColor(model.gpu_percent)}`}>
          {processorLabel(model.gpu_percent)}
        </span>
        <span className="text-[9px] text-gray-400 dark:text-zinc-600 tabular-nums">
          {model.vram_gb}GB VRAM
        </span>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function StatsBar() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const selectedModel = useChatStore(s => s.selectedModel);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      if (cancelled || document.visibilityState === "hidden") return;
      const s = await getStats();
      if (!cancelled) setStats(s);
    };

    poll();
    const id = setInterval(poll, 3_000);
    document.addEventListener("visibilitychange", poll);

    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener("visibilitychange", poll);
    };
  }, []);

  // Trigger an extra immediate fetch whenever the selected model changes
  // (so VRAM/Ollama info updates right away instead of waiting up to 3s)
  useEffect(() => {
    if (!selectedModel) return;
    getStats().then(s => setStats(s)).catch(() => {});
  }, [selectedModel]);

  if (!stats) return null;

  const vramPercent = stats.gpu
    ? Math.round((stats.gpu.vram_used_gb / stats.gpu.vram_total_gb) * 100)
    : 0;

  return (
    <div className="px-4 py-2.5 border-t border-gray-200 dark:border-zinc-800 flex flex-col gap-1.5">
      {/* System resources */}
      <StatRow
        icon={<Cpu size={11} />}
        label="CPU"
        percent={stats.cpu_percent}
        detail={`${Math.round(stats.cpu_percent)}%`}
        color={barColor(stats.cpu_percent)}
      />
      <StatRow
        icon={<MemoryStick size={11} />}
        label="RAM"
        percent={stats.ram_percent}
        detail={`${stats.ram_used_gb}/${stats.ram_total_gb}G`}
        color={barColor(stats.ram_percent)}
      />
      {stats.gpu && (
        <StatRow
          icon={<Layers size={11} />}
          label="VRAM"
          percent={vramPercent}
          detail={`${stats.gpu.vram_used_gb}/${stats.gpu.vram_total_gb}G`}
          color={barColor(vramPercent)}
        />
      )}

      {/* Ollama loaded models — only shown when at least one is in memory */}
      {stats.ollama_models.length > 0 && (
        <div className="border-t border-gray-200 dark:border-zinc-800 mt-0.5 pt-1.5 flex flex-col gap-0.5">
          <div className="flex items-center gap-1 mb-0.5">
            <BrainCircuit size={10} className="text-emerald-400 dark:text-lime-500" />
            <span className="text-[9px] uppercase tracking-wide text-gray-400 dark:text-zinc-600 font-medium">Ollama</span>
          </div>
          {stats.ollama_models.map((m) => (
            <OllamaRow key={m.name} model={m} />
          ))}
        </div>
      )}
    </div>
  );
}
