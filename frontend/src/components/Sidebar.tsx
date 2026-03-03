import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, MessageSquare, Hammer, Settings, Pencil, Database } from "lucide-react";
import { useChatStore } from "../store/chat";
import { ModelSelector } from "./ModelSelector";
import { StatsBar } from "./StatsBar";
import { checkHealth } from "../api/client";
import type { HealthStatus } from "../api/client";

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
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
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
  const {
    conversations,
    activeConvId,
    loadConversations,
    selectConversation,
    newConversation,
    deleteConv,
    renameConv,
  } = useChatStore();

  useEffect(() => {
    loadConversations();
  }, []);

  return (
    <aside className="w-100 flex-shrink-0 flex flex-col bg-gray-50 dark:bg-zinc-900 border-r border-gray-200 dark:border-zinc-800 h-full">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 dark:border-zinc-800">
        <Hammer size={20} className="text-indigo-500 dark:text-indigo-400" />
        <span className="font-semibold text-gray-900 dark:text-zinc-100 tracking-tight">LocalForge</span>
        <div className="ml-auto flex items-center gap-2">
          <StatusLed status={apiStatus} title={apiStatus === "connected" ? "API conectada" : "API desconectada"} />
          <span className="flex items-center gap-0.5" title={`DB (${dbType}): ${dbStatus === "connected" ? "conectada" : "desconectada"}`}>
            <Database size={10} className={
              dbStatus === "connected"    ? "text-green-500" :
              dbStatus === "disconnected" ? "text-red-500"   : "text-yellow-400"
            } />
            <StatusLed status={dbStatus} title={`DB (${dbType}): ${dbStatus === "connected" ? "conectada" : "desconectada"}`} />
          </span>
          <span className="text-xs text-gray-400 dark:text-zinc-600">v0.1</span>
        </div>
      </div>

      {/* Model selector */}
      <div className="px-3 py-3 border-b border-gray-200 dark:border-zinc-800">
        <ModelSelector />
      </div>

      {/* New chat button */}
      <div className="px-3 py-2">
        <button
          onClick={newConversation}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm transition-colors"
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

      {/* Settings button */}
      <div className="border-t border-gray-200 dark:border-zinc-800 px-3 py-3">
        <button
          onClick={onSettings}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-gray-500 hover:text-gray-800 hover:bg-gray-100 dark:text-zinc-500 dark:hover:text-zinc-200 dark:hover:bg-zinc-800 text-sm transition-colors"
        >
          <Settings size={15} />
          Settings
        </button>
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
      <div className={`flex items-center gap-1 px-2 py-1.5 rounded-lg ${
        active ? "bg-gray-200 dark:bg-zinc-700" : "bg-gray-100 dark:bg-zinc-800"
      }`}>
        <MessageSquare size={14} className="flex-shrink-0 text-gray-400 dark:text-zinc-500" />
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={commit}
          className="flex-1 text-sm bg-white dark:bg-zinc-900 text-gray-900 dark:text-zinc-100 border border-indigo-400 dark:border-indigo-500 rounded px-1.5 py-0.5 outline-none min-w-0"
          autoFocus
        />
      </div>
    );
  }

  return (
    <div
      onClick={onSelect}
      className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
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
          className="p-0.5 text-gray-300 hover:text-indigo-400 dark:text-zinc-600 dark:hover:text-indigo-400"
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
