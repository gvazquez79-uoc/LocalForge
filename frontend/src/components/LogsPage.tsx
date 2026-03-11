import { useEffect, useRef, useState, useCallback } from "react";
import {
  Hammer, Circle, Wifi, WifiOff, Pause, Play,
  Trash2, ChevronDown, Search, X,
} from "lucide-react";
import { getApiKey } from "../api/client";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000/api";

// ── Types ─────────────────────────────────────────────────────────────────────

type Level = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

interface LogEntry {
  ts: string;
  level: string;
  logger: string;
  message: string;
}

// ── Level styling ─────────────────────────────────────────────────────────────

const LEVEL_STYLE: Record<string, { badge: string; row: string; dot: string }> = {
  DEBUG:    { badge: "bg-zinc-700 text-zinc-300",            row: "",                                     dot: "bg-zinc-500" },
  INFO:     { badge: "bg-blue-900/70 text-blue-300",         row: "",                                     dot: "bg-blue-400" },
  WARNING:  { badge: "bg-amber-900/60 text-amber-300",       row: "bg-amber-950/20",                      dot: "bg-amber-400" },
  ERROR:    { badge: "bg-red-900/70 text-red-300",           row: "bg-red-950/20",                        dot: "bg-red-500"  },
  CRITICAL: { badge: "bg-red-600 text-white font-bold",      row: "bg-red-950/40 border-l-2 border-red-500", dot: "bg-red-500" },
};

const fallbackStyle = { badge: "bg-zinc-700 text-zinc-300", row: "", dot: "bg-zinc-500" };

function levelStyle(level: string) {
  return LEVEL_STYLE[level] ?? fallbackStyle;
}

// ── Level filter tabs ─────────────────────────────────────────────────────────

const FILTERS: Array<{ label: string; value: string }> = [
  { label: "ALL",      value: "" },
  { label: "DEBUG",    value: "DEBUG" },
  { label: "INFO",     value: "INFO" },
  { label: "WARNING",  value: "WARNING" },
  { label: "ERROR",    value: "ERROR" },
];

// ── Format timestamp ──────────────────────────────────────────────────────────

function fmtTs(iso: string): string {
  try {
    const d = new Date(iso);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    const ss = String(d.getSeconds()).padStart(2, "0");
    const ms = String(d.getMilliseconds()).padStart(3, "0");
    return `${hh}:${mm}:${ss}.${ms}`;
  } catch {
    return iso;
  }
}

// ── Main component ────────────────────────────────────────────────────────────

export function LogsPage() {
  const [entries, setEntries]         = useState<LogEntry[]>([]);
  const [filter, setFilter]           = useState("");
  const [search, setSearch]           = useState("");
  const [paused, setPaused]           = useState(false);
  const [connected, setConnected]     = useState(false);
  const [autoScroll, setAutoScroll]   = useState(true);

  const bottomRef   = useRef<HTMLDivElement>(null);
  const listRef     = useRef<HTMLDivElement>(null);
  const pauseRef    = useRef(paused);
  pauseRef.current  = paused;

  // ── Load historical entries on mount ───────────────────────────────────────
  useEffect(() => {
    const key = getApiKey();
    const headers: Record<string, string> = key ? { "X-API-Key": key } : {};
    fetch(`${BASE}/logs?n=2000`, { headers })
      .then(r => r.json())
      .then((data: LogEntry[]) => {
        setEntries(data.filter(e => e.level !== "__CONNECTED__"));
      })
      .catch(() => {});
  }, []);

  // ── SSE live stream ────────────────────────────────────────────────────────
  useEffect(() => {
    const key = getApiKey();
    const url = key
      ? `${BASE}/logs/stream?api_key=${encodeURIComponent(key)}`
      : `${BASE}/logs/stream`;

    const es = new EventSource(url);

    es.onopen = () => setConnected(true);

    es.onmessage = (e) => {
      try {
        const entry: LogEntry = JSON.parse(e.data);
        if (entry.level === "__CONNECTED__") {
          setConnected(true);
          return;
        }
        if (!pauseRef.current) {
          setEntries(prev => {
            const next = [...prev, entry];
            return next.length > 5_000 ? next.slice(-5_000) : next;
          });
        }
      } catch { /* ignore */ }
    };

    es.onerror = () => setConnected(false);

    return () => es.close();
  }, []);

  // ── Auto-scroll ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (autoScroll && !paused) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
    }
  }, [entries, autoScroll, paused]);

  const handleScroll = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    setAutoScroll(atBottom);
  }, []);

  // ── Filter logic ───────────────────────────────────────────────────────────
  const visible = entries.filter(e => {
    if (filter && e.level !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      return e.message.toLowerCase().includes(q) || e.logger.toLowerCase().includes(q);
    }
    return true;
  });

  const clearLog = () => setEntries([]);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setAutoScroll(true);
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen bg-zinc-950 text-zinc-100 font-mono text-xs select-text">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header className="flex-shrink-0 flex items-center gap-3 px-4 py-3
                         bg-zinc-900 border-b border-zinc-800 shadow-md">
        <Hammer size={18} className="text-emerald-400" />
        <span className="text-sm font-semibold tracking-tight text-zinc-100">
          LocalForge — App Logs
        </span>

        {/* Connection status */}
        <span className={`flex items-center gap-1.5 text-[11px] ml-1 ${connected ? "text-emerald-400" : "text-red-400"}`}>
          {connected
            ? <><Wifi size={12} /><span>Live</span></>
            : <><WifiOff size={12} /><span>Disconnected</span></>}
        </span>

        <div className="flex-1" />

        {/* Entry count */}
        <span className="text-zinc-500 text-[11px]">
          {visible.length.toLocaleString()} / {entries.length.toLocaleString()} entries
        </span>

        {/* Pause/Resume */}
        <button
          onClick={() => setPaused(p => !p)}
          title={paused ? "Resume" : "Pause"}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-sm text-[11px] transition-colors
                      ${paused
                        ? "bg-emerald-600/30 text-amber-300 hover:bg-emerald-600/50"
                        : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"}`}
        >
          {paused ? <><Play size={11} /> Resume</> : <><Pause size={11} /> Pause</>}
        </button>

        {/* Clear */}
        <button
          onClick={clearLog}
          title="Clear"
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-sm text-[11px]
                     bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-red-400 transition-colors"
        >
          <Trash2 size={11} /> Clear
        </button>
      </header>

      {/* ── Filter bar ────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 flex items-center gap-2 px-4 py-2
                      bg-zinc-900/80 border-b border-zinc-800/60">
        {/* Level pills */}
        <div className="flex items-center gap-1">
          {FILTERS.map(f => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={`px-2.5 py-1 rounded-sm text-[11px] font-medium transition-colors ${
                filter === f.value
                  ? "bg-emerald-600 text-white"
                  : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="w-px h-4 bg-zinc-700 mx-1" />

        {/* Search */}
        <div className="flex items-center gap-2 flex-1 bg-zinc-800 rounded-sm px-3 py-1.5 max-w-xs">
          <Search size={11} className="text-zinc-500 shrink-0" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search message / logger…"
            className="flex-1 bg-transparent outline-none text-zinc-200 placeholder-zinc-600 text-[11px]"
          />
          {search && (
            <button onClick={() => setSearch("")} className="text-zinc-500 hover:text-zinc-300">
              <X size={10} />
            </button>
          )}
        </div>
      </div>

      {/* ── Log entries ───────────────────────────────────────────────────── */}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {visible.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-zinc-600">
            {entries.length === 0 ? "No log entries yet…" : "No entries match filter"}
          </div>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {visible.map((e, i) => {
                const s = levelStyle(e.level);
                return (
                  <tr
                    key={i}
                    className={`border-b border-zinc-800/40 hover:bg-zinc-800/30 transition-colors ${s.row}`}
                  >
                    {/* Timestamp */}
                    <td className="px-3 py-1 whitespace-nowrap text-zinc-500 align-top w-[100px]">
                      {fmtTs(e.ts)}
                    </td>
                    {/* Level badge */}
                    <td className="px-2 py-1 whitespace-nowrap align-top w-[80px]">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${s.badge}`}>
                        {e.level}
                      </span>
                    </td>
                    {/* Logger name */}
                    <td className="px-2 py-1 whitespace-nowrap text-zinc-500 align-top max-w-[180px] truncate">
                      {e.logger}
                    </td>
                    {/* Message */}
                    <td className="px-2 py-1 text-zinc-200 align-top break-all whitespace-pre-wrap">
                      {e.message}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div ref={bottomRef} />
      </div>

      {/* ── Footer / scroll-to-bottom hint ────────────────────────────────── */}
      {!autoScroll && (
        <div className="flex-shrink-0 flex justify-center py-2 bg-zinc-900/80 border-t border-zinc-800">
          <button
            onClick={scrollToBottom}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-sm text-[11px]
                       bg-emerald-600/30 text-emerald-300 hover:bg-emerald-600/50 transition-colors"
          >
            <ChevronDown size={12} /> Jump to latest
          </button>
        </div>
      )}

      {/* Paused banner */}
      {paused && (
        <div className="flex-shrink-0 flex justify-center py-2 bg-amber-950/40 border-t border-amber-800/40">
          <span className="text-amber-400 text-[11px] flex items-center gap-2">
            <Circle size={8} className="fill-amber-400" /> Stream paused — new entries are not shown
          </span>
        </div>
      )}
    </div>
  );
}
