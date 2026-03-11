import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal, FileText, Search, Globe, FolderOpen, Trash2, PenLine, Loader2 } from "lucide-react";
import type { ToolCallData } from "../api/client";

interface ToolBlockProps {
  tool: ToolCallData;
  result?: string;
}

const TOOL_META: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  execute_command: { icon: <Terminal size={13} />,   label: "Ejecutando comando",    color: "text-orange-500 dark:text-orange-400" },
  read_file:       { icon: <FileText size={13} />,   label: "Leyendo archivo",       color: "text-blue-500 dark:text-blue-400" },
  write_file:      { icon: <PenLine size={13} />,    label: "Escribiendo archivo",   color: "text-emerald-600 dark:text-emerald-400" },
  list_directory:  { icon: <FolderOpen size={13} />, label: "Listando directorio",   color: "text-violet-500 dark:text-violet-400" },
  search_files:    { icon: <Search size={13} />,     label: "Buscando archivos",     color: "text-cyan-500 dark:text-cyan-400" },
  delete_file:     { icon: <Trash2 size={13} />,     label: "Eliminando archivo",    color: "text-red-500 dark:text-red-400" },
  web_search:      { icon: <Globe size={13} />,      label: "Buscando en internet",  color: "text-sky-500 dark:text-sky-400" },
};

const DEFAULT_META = { icon: <Terminal size={13} />, label: "Ejecutando herramienta", color: "text-gray-500 dark:text-zinc-400" };

export function ToolBlock({ tool, result }: ToolBlockProps) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_META[tool.name] ?? DEFAULT_META;
  const running = !result;
  const summary = formatInputSummary(tool.input);

  return (
    <div className={`my-2 rounded border overflow-hidden text-sm transition-colors ${
      running
        ? "border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-950/30"
        : "border-gray-200 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-900"
    }`}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
      >
        <span className={meta.color}>{meta.icon}</span>
        <span className={`font-medium text-xs ${meta.color}`}>{meta.label}</span>
        <span className="text-gray-400 dark:text-zinc-500 text-xs truncate flex-1 font-mono">
          {summary}
        </span>
        {running ? (
          <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 flex-shrink-0">
            <Loader2 size={12} className="animate-spin" />
            <span className="font-medium">en curso…</span>
          </span>
        ) : (
          open ? <ChevronDown size={13} className="text-gray-400 flex-shrink-0" />
               : <ChevronRight size={13} className="text-gray-400 flex-shrink-0" />
        )}
      </button>

      {open && (
        <div className="border-t border-gray-200 dark:border-zinc-700">
          <div className="px-3 py-2 bg-gray-100 dark:bg-zinc-950">
            <p className="text-gray-400 dark:text-zinc-500 text-[11px] uppercase tracking-wide mb-1">Input</p>
            <pre className="text-gray-700 dark:text-zinc-300 text-xs overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(tool.input, null, 2)}
            </pre>
          </div>
          {result && (
            <div className="px-3 py-2 border-t border-gray-200 dark:border-zinc-800">
              <p className="text-gray-400 dark:text-zinc-500 text-[11px] uppercase tracking-wide mb-1">Output</p>
              <pre className="text-gray-700 dark:text-zinc-300 text-xs overflow-x-auto whitespace-pre-wrap max-h-64">
                {result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatInputSummary(input: Record<string, unknown>): string {
  // Prefer showing path/command/query — most useful at a glance
  const primary = (input.path ?? input.command ?? input.query ?? input.pattern) as string | undefined;
  if (primary) return String(primary).length > 70 ? String(primary).slice(0, 70) + "…" : String(primary);
  const values = Object.values(input).map((v) => String(v)).join(", ");
  return values.length > 70 ? values.slice(0, 70) + "…" : values;
}
