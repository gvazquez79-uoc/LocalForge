import type { UIMessage } from "../store/chat";
import { ToolBlock } from "./ToolBlock";
import { Bot, User } from "lucide-react";

interface MessageProps {
  message: UIMessage;
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"} mb-6`}>
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs ${
          isUser
            ? "bg-indigo-600 text-white"
            : "bg-zinc-800 text-emerald-400 border border-zinc-700"
        }`}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      {/* Content */}
      <div className={`flex-1 max-w-[85%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        {/* Tool calls */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="w-full">
            {message.toolCalls.map((tc) => (
              <ToolBlock
                key={tc.id}
                tool={tc}
                result={message.toolResults?.[tc.id]}
              />
            ))}
          </div>
        )}

        {/* Text bubble */}
        {(message.content || message.isStreaming) && (
          <div
            className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
              isUser
                ? "bg-indigo-600 text-white rounded-tr-sm"
                : "bg-zinc-800 text-zinc-100 rounded-tl-sm"
            }`}
          >
            <pre className="whitespace-pre-wrap font-sans break-words">
              {message.content}
              {message.isStreaming && !message.content && (
                <span className="inline-flex gap-1">
                  <span className="animate-bounce delay-0">.</span>
                  <span className="animate-bounce delay-100">.</span>
                  <span className="animate-bounce delay-200">.</span>
                </span>
              )}
              {message.isStreaming && message.content && (
                <span className="inline-block w-0.5 h-4 bg-zinc-400 animate-pulse ml-0.5 align-text-bottom" />
              )}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
