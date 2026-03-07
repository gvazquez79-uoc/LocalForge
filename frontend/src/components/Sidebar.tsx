import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, MessageSquare, Hammer, Settings, Pencil, Database, ScrollText, Bug, Radar, Check, X, Loader } from "lucide-react";
import { useChatStore } from "../store/chat";
import { ModelSelector } from "./ModelSelector";
import { StatsBar } from "./StatsBar";
import { checkHealth, discoverOllamaModels, createDbModel } from "../api/client";
import type { HealthStatus, DiscoveredModel } from "../api/client";
import { usePrefs } from "../store/prefs";

type ConnStatus = "checking" | "connected" | "disconnected";

function useConnectionStatus() {
  const [health, setHealth] = useState<HealthStatus>({ api_ok: false, db_ok: false, db_type: "unknown" });
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      if (cancelled) return;
      setChecking(true);
      const result = await checkHealth();
      if (!cancelled) {
        setHealth(result);
        setChecking(false);
      }
    };

    check();
    const id = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const apiStatus: ConnStatus = checking ? "checking" : health.api_ok ? "connected" : "disconnected";
  const dbStatus: ConnStatus  = checking ? "checking" : health.db_ok  ? "connected" : "disconnected";

  return { apiStatus, dbStatus, dbType: health.db_type };
}

function StatusLed({ status, title }: { status: ConnStatus; title: string }) {
  if (status === "connected") {
    return (
      <span className="relative flex h-2.5 w-2.5" title={title}>
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
      </span>
    );
  }
  if (status === "disconnected") {
    return (
      <span className="relative flex h-2.5 w-2.5" title={title}>
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-red-500" />
      </span>
    );
  }
  return (
    <span className="relative flex h-2.5 w-2.5" title="Comprobando conexión…">
      <span className="animate-pulse relative inline-flex rounded-full h-2.5 w-2.5 bg-yellow-400 opacity-80" />
    </span>
  );
}

interface SidebarProps {
  onSettings: () => void;
}

export function Sidebar({ onSettings }: SidebarProps) {
  const { apiStatus, dbStatus, dbType } = useConnectionStatus();
  const { devMode, setDevMode } = usePrefs();
  const {
    conversations,
    activeConvId,
    loadConversations,
    selectConversation,
    newConversation,
    deleteConv,
    renameConv,
    loadModels,
  } = useChatStore();

  // ── Ollama discover state ──────────────────────────────────────────────────
  const [discoverOpen, setDiscoverOpen]         = useState(false);
  const [discovering, setDiscovering]           = useState(false);
  const [discovered, setDiscovered]             = useState<DiscoveredModel[]>([]);
  const [addingModel, setAddingModel]           = useState<string | null>(null);
  const [discoverError, setDiscoverError]       = useState<string | null>(null);

  const handleDiscover = async () => {
    if (discoverOpen) { setDiscoverOpen(false); return; }
    setDiscoverOpen(true);
    setDiscovering(true);
    setDiscoverError(null);
    try {
      const models = await discoverOllamaModels();
      setDiscovered(models);
    } catch {
      setDiscoverError("Ollama not reachable");
    } finally {
      setDiscovering(false);
    }
  };

  const handleAddModel = async (m: DiscoveredModel) => {
    setAddingModel(m.name);
    try {
      await createDbModel({
        name: m.name,
        display_name: m.display_name,
        provider: "ollama",
      });
      // Mark as configured in local state
      setDiscovered(prev => prev.map(d => d.name === m.name ? { ...d, already_configured: true } : d));
      await loadModels();
    } catch {
      // ignore — model may already exist
      setDiscovered(prev => prev.map(d => d.name === m.name ? { ...d, already_configured: true } : d));
    } finally {
      setAddingModel(null);
    }
  };

  useEffect(() => {
    loadConversations();
  }, []);

  return (
    <aside className="w-100 flex-shrink-0 flex flex-col bg-gray-50 dark:bg-zinc-900 border-r border-gray-200 dark:border-zinc-800 h-full">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 dark:border-zinc-800">
        <Hammer size={20} className="text-lime-500 dark:text-emerald-400" />
        <span className="font-semibold text-gray-900 dark:text-zinc-100 tracking-tight">LocalForge</span>
        <div className="ml-auto flex items-center gap-2">
          <StatusLed status={apiStatus} title={apiStatus === "connected" ? "API conectada" : "API desconectada"} />
          <span className="flex items-center gap-0.5" title={`DB (${dbType}): ${dbStatus === "connected" ? "conectada" : "desconectada"}`}>
            <Database size={10} className={
              dbStatus === "connected"    ? "text-emerald-500" :
              dbStatus === "disconnected" ? "text-red-500"   : "text-yellow-400"
            } />
            <StatusLed status={dbStatus} title={`DB (${dbType}): ${dbStatus === "connected" ? "conectada" : "desconectada"}`} />
          </span>
          <span className="text-xs text-gray-400 dark:text-zinc-600">v0.1</span>
        </div>
      </div>

      {/* Model selector */}
      <div className="px-3 pt-3 pb-2 border-b border-gray-200 dark:border-zinc-800">
        <ModelSelector onOpenSettings={onSettings} />

        {/* Discover Ollama button */}
        <button
          onClick={handleDiscover}
          className="mt-2 flex items-center gap-1.5 text-[11px] text-gray-400 dark:text-zinc-600 hover:text-emerald-600 dark:hover:text-emerald-400 transition-colors w-full px-1"
        >
          <Radar size={11} />
          <span>Discover Ollama models</span>
          {discoverOpen && <X size={10} className="ml-auto" />}
        </button>

        {/* Discover panel */}
        {discoverOpen && (
          <div className="mt-2 border border-gray-200 dark:border-zinc-700 rounded-sm bg-gray-50 dark:bg-zinc-800/50 overflow-hidden">
            {discovering ? (
              <div className="flex items-center gap-2 px-3 py-2 text-[11px] text-gray-400 dark:text-zinc-500">
                <Loader size={11} className="animate-spin" />
                Scanning Ollama…
              </div>
            ) : discoverError ? (
              <div className="px-3 py-2 text-[11px] text-red-400">{discoverError}</div>
            ) : discovered.length === 0 ? (
              <div className="px-3 py-2 text-[11px] text-gray-400 dark:text-zinc-500">No Ollama models found</div>
            ) : (
              <div className="max-h-48 overflow-y-auto divide-y divide-gray-100 dark:divide-zinc-700/50">
                {discovered.map(m => (
                  <div key={m.name} className="flex items-center gap-2 px-3 py-1.5">
                    <span className="flex-1 text-[11px] text-gray-700 dark:text-zinc-300 font-mono truncate" title={m.name}>
                      {m.name}
                    </span>
                    {m.already_configured ? (
                      <span className="flex items-center gap-0.5 text-[10px] text-emerald-500 flex-shrink-0">
                        <Check size={10} /> Added
                      </span>
                    ) : (
                      <button
                        onClick={() => handleAddModel(m)}
                        disabled={addingModel === m.name}
                        className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-50 flex-shrink-0 transition-colors"
                      >
                        {addingModel === m.name
                          ? <Loader size={9} className="animate-spin" />
                          : <Plus size={9} />}
                        Add
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* New chat button */}
      <div className="px-3 py-2">
        <button
          onClick={newConversation}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-sm bg-emerald-600 hover:bg-emerald-500 text-white text-sm transition-colors"
        >
          <Plus size={16} />
          New conversation
        </button>
      </div>

      {/* Conversations list */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {conversations.length === 0 ? (
          <p className="text-gray-400 dark:text-zinc-600 text-xs text-center py-6">No conversations yet</p>
        ) : (
          conversations.map((conv) => (
            <ConvItem
              key={conv.id}
              id={conv.id}
              title={conv.title}
              active={conv.id === activeConvId}
              onSelect={() => selectConversation(conv.id)}
              onDelete={(e) => {
                e.stopPropagation();
                deleteConv(conv.id);
              }}
              onRename={(title) => renameConv(conv.id, title)}
            />
          ))
        )}
      </div>

      {/* Resource usage */}
      <StatsBar />

      {/* Footer: Settings + Developer mode ─────────────────────────────── */}
      <div className="border-t border-gray-200 dark:border-zinc-800 px-3 py-3 space-y-1">
        <button
          onClick={onSettings}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-sm text-gray-500 hover:text-gray-800 hover:bg-gray-100 dark:text-zinc-500 dark:hover:text-zinc-200 dark:hover:bg-zinc-800 text-sm transition-colors"
        >
          <Settings size={15} />
          Settings
        </button>

        {/* Developer mode toggle */}
        <label className="flex items-center gap-2 px-3 py-2 rounded-sm cursor-pointer
                          hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors group">
          <Bug
            size={15}
            className={devMode
              ? "text-amber-500"
              : "text-gray-400 dark:text-zinc-600 group-hover:text-gray-600 dark:group-hover:text-zinc-400"}
          />
          <span className="flex-1 text-sm text-gray-500 dark:text-zinc-500 group-hover:text-gray-800 dark:group-hover:text-zinc-200 transition-colors">
            Developer mode
          </span>
          {/* Mini toggle */}
          <button
            role="switch"
            aria-checked={devMode}
            onClick={() => setDevMode(!devMode)}
            className={`relative inline-flex h-4 w-7 flex-shrink-0 rounded-full transition-colors ${
              devMode ? "bg-amber-500" : "bg-gray-200 dark:bg-zinc-700"
            }`}
          >
            <span className={`inline-block h-3 w-3 rounded-full bg-white shadow transition-transform mt-0.5 ${
              devMode ? "translate-x-3.5" : "translate-x-0.5"
            }`} />
          </button>
        </label>

        {/* App logs button — only visible in dev mode */}
        {devMode && (
          <button
            onClick={() => window.open("/logs", "_blank")}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-sm
                       text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30
                       text-sm transition-colors"
          >
            <ScrollText size={15} />
            View app logs
          </button>
        )}
      </div>
    </aside>
  );
}

interface ConvItemProps {
  id: string;
  title: string;
  active: boolean;
  onSelect: () => void;
  onDelete: (e: React.MouseEvent) => void;
  onRename: (title: string) => void;
}

function ConvItem({ title, active, onSelect, onDelete, onRename }: ConvItemProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDraft(title);
    setEditing(true);
    // Focus after render
    setTimeout(() => {
      inputRef.current?.select();
    }, 0);
  };

  const commit = () => {
    setEditing(false);
    if (draft.trim() && draft.trim() !== title) {
      onRename(draft.trim());
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") commit();
    if (e.key === "Escape") setEditing(false);
  };

  if (editing) {
    return (
      <div className={`flex items-center gap-1 px-2 py-1.5 rounded-sm ${
        active ? "bg-gray-200 dark:bg-zinc-700" : "bg-gray-100 dark:bg-zinc-800"
      }`}>
        <MessageSquare size={14} className="flex-shrink-0 text-gray-400 dark:text-zinc-500" />
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
          className="flex-1 text-sm bg-white dark:bg-zinc-900 text-gray-900 dark:text-zinc-100 border border-emerald-400 dark:border-emerald-500 rounded px-1.5 py-0.5 outline-none min-w-0"
          autoFocus
        />
      </div>
    );
  }

  return (
    <div
      onClick={onSelect}
      className={`group flex items-center gap-2 px-3 py-2 rounded-sm cursor-pointer transition-colors ${
        active
          ? "bg-gray-200 text-gray-900 dark:bg-zinc-700 dark:text-zinc-100"
          : "hover:bg-gray-100 text-gray-500 dark:hover:bg-zinc-800 dark:text-zinc-400"
      }`}
    >
      <MessageSquare size={14} className="flex-shrink-0" />
      <span className="flex-1 text-sm truncate">{title}</span>
      {/* Action buttons — visible on hover */}
      <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 transition-all">
        <button
          onClick={startEdit}
          className="p-0.5 text-gray-300 hover:text-emerald-400 dark:text-zinc-600 dark:hover:text-emerald-400"
          title="Rename"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={onDelete}
          className="p-0.5 text-gray-300 hover:text-red-400 dark:text-zinc-600 dark:hover:text-red-400"
          title="Delete"
        >
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  );
}
