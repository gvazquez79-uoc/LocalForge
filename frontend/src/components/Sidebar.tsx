import { useEffect } from "react";
import { Plus, Trash2, MessageSquare, Hammer } from "lucide-react";
import { useChatStore } from "../store/chat";
import { ModelSelector } from "./ModelSelector";

export function Sidebar() {
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
    <aside className="w-64 flex-shrink-0 flex flex-col bg-zinc-900 border-r border-zinc-800 h-full">
      {/* Logo */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-zinc-800">
        <Hammer size={20} className="text-indigo-400" />
        <span className="font-semibold text-zinc-100 tracking-tight">LocalForge</span>
        <span className="ml-auto text-xs text-zinc-600">v0.1</span>
      </div>

      {/* Model selector */}
      <div className="px-3 py-3 border-b border-zinc-800">
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
          <p className="text-zinc-600 text-xs text-center py-6">No conversations yet</p>
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
        active ? "bg-zinc-700 text-zinc-100" : "hover:bg-zinc-800 text-zinc-400"
      }`}
    >
      <MessageSquare size={14} className="flex-shrink-0" />
      <span className="flex-1 text-sm truncate">{title}</span>
      <button
        onClick={onDelete}
        className="opacity-0 group-hover:opacity-100 text-zinc-600 hover:text-red-400 transition-all"
      >
        <Trash2 size={13} />
      </button>
    </div>
  );
}
