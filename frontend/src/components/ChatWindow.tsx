import { useEffect, useRef, useState } from "react";
import { Send, StopCircle } from "lucide-react";
import { useChatStore } from "../store/chat";
import { Message } from "./Message";

export function ChatWindow() {
  const { messages, isLoading, sendMessage, stopStream, activeConvId, newConversation } =
    useChatStore();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const content = input.trim();
    if (!content || isLoading) return;

    if (!activeConvId) {
      await newConversation();
    }

    setInput("");
    sendMessage(content);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((msg) => <Message key={msg.id} message={msg} />)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="border-t border-zinc-800 px-4 py-4 bg-zinc-950">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              adjustHeight();
            }}
            onKeyDown={handleKeyDown}
            placeholder="Message LocalForge… (Enter to send, Shift+Enter for newline)"
            rows={1}
            className="flex-1 resize-none bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
            style={{ minHeight: "44px", maxHeight: "200px" }}
          />
          {isLoading ? (
            <button
              onClick={() => stopStream?.()}
              className="p-3 bg-red-600 hover:bg-red-500 rounded-xl text-white transition-colors"
              title="Stop"
            >
              <StopCircle size={18} />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="p-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-white transition-colors"
              title="Send"
            >
              <Send size={18} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center py-20">
      <div className="w-16 h-16 rounded-2xl bg-zinc-800 border border-zinc-700 flex items-center justify-center text-3xl">
        🔨
      </div>
      <h2 className="text-xl font-semibold text-zinc-200">LocalForge</h2>
      <p className="text-zinc-500 text-sm max-w-sm">
        Your local AI agent with access to files, terminal, and web search.
        <br />
        Ask anything — or give it a task.
      </p>
      <div className="flex flex-wrap gap-2 justify-center mt-2">
        {SUGGESTIONS.map((s) => (
          <SuggestionChip key={s} text={s} />
        ))}
      </div>
    </div>
  );
}

function SuggestionChip({ text }: { text: string }) {
  const { sendMessage, activeConvId, newConversation } = useChatStore();
  const handleClick = async () => {
    if (!activeConvId) await newConversation();
    sendMessage(text);
  };
  return (
    <button
      onClick={handleClick}
      className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 rounded-full text-xs text-zinc-300 transition-colors"
    >
      {text}
    </button>
  );
}

const SUGGESTIONS = [
  "List files in my home directory",
  "Search for Python files in ~/Projects",
  "What's the latest news in AI?",
  "Run 'git status' in ~/Projects",
];
