import { useEffect } from "react";
import { Plus, Trash2, MessageSquare, Hammer, Settings } from "lucide-react";
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
}

function ConvItem({ title, active, onSelect, onDelete }: ConvItemProps) {
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
      <button
        onClick={onDelete}
        className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-400 dark:text-zinc-600 transition-all"
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}
