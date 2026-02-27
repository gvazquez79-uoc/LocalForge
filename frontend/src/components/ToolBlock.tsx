import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal, FileText, Search, Globe } from "lucide-react";
import type { ToolCallData } from "../api/client";

interface ToolBlockProps {
  tool: ToolCallData;
  result?: string;
}

const TOOL_ICONS: Record<string, React.ReactNode> = {
  execute_command: <Terminal size={14} />,
  read_file: <FileText size={14} />,
  write_file: <FileText size={14} />,
  list_directory: <FileText size={14} />,
  search_files: <Search size={14} />,
  delete_file: <FileText size={14} />,
  web_search: <Globe size={14} />,
};

export function ToolBlock({ tool, result }: ToolBlockProps) {
  const [open, setOpen] = useState(false);
  const icon = TOOL_ICONS[tool.name] ?? <Terminal size={14} />;

  return (
    <div className="my-2 rounded-lg border border-zinc-700 bg-zinc-900 text-sm overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-zinc-400 hover:bg-zinc-800 transition-colors"
      >
        <span className="text-emerald-400">{icon}</span>
        <span className="font-mono text-emerald-400">{tool.name}</span>
        <span className="text-zinc-500 text-xs truncate flex-1">
          {formatInputSummary(tool.input)}
        </span>
        {result ? (
          open ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        ) : (
          <span className="text-xs text-yellow-400 animate-pulse">running…</span>
        )}
      </button>

      {open && (
        <div className="border-t border-zinc-700">
          <div className="px-3 py-2 bg-zinc-950">
            <p className="text-zinc-500 text-xs mb-1">Input</p>
            <pre className="text-zinc-300 text-xs overflow-x-auto whitespace-pre-wrap">
              {JSON.stringify(tool.input, null, 2)}
            </pre>
          </div>
          {result && (
            <div className="px-3 py-2 border-t border-zinc-800">
              <p className="text-zinc-500 text-xs mb-1">Output</p>
              <pre className="text-zinc-300 text-xs overflow-x-auto whitespace-pre-wrap max-h-64">
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
  const values = Object.values(input)
    .map((v) => String(v))
    .join(", ");
  return values.length > 60 ? values.slice(0, 60) + "…" : values;
}
