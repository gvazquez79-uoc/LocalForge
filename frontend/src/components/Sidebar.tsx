import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, MessageSquare, Hammer, Settings, Pencil } from "lucide-react";
import { useChatStore } from "../store/chat";
import { ModelSelector } from "./ModelSelector";

interface SidebarProps {
  onSettings: () => void;
}

export function Sidebar({ onSettings }: SidebarProps) {
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
    <aside className="w-64 flex-shrink-0 flex flex-col bg-gray-50 dark:bg-zinc-900 border-r border-gray-200 dark:border-zinc-800 h-full">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 dark:border-zinc-800">
        <Hammer size={20} className="text-indigo-500 dark:text-indigo-400" />
        <span className="font-semibold text-gray-900 dark:text-zinc-100 tracking-tight">LocalForge</span>
        <span className="ml-auto text-xs text-gray-400 dark:text-zinc-600">v0.1</span>
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
