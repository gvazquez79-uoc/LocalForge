import { useEffect, useRef, useState, useCallback } from "react";
import { Send, StopCircle, AlertCircle, X, Upload, File, XCircle } from "lucide-react";
import { useChatStore } from "../store/chat";
import { Message } from "./Message";
import { ConfirmationModal } from "./ConfirmationModal";

interface FileAttachment {
  name: string;
  content: string;
  size: number;
  type: string;
}

export function ChatWindow() {
  const { 
    messages, 
    isLoading, 
    sendMessage, 
    stopStream, 
    activeConvId, 
    newConversation, 
    error,
    pendingConfirmation,
    approveConfirmation,
    rejectConfirmation
  } = useChatStore();
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dragCounter = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Read file content
  const readFile = (file: File): Promise<FileAttachment> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        resolve({
          name: file.name,
          content: reader.result as string,
          size: file.size,
          type: file.type,
        });
      };
      reader.onerror = reject;
      reader.readAsText(file);
    });
  };

  // Handle file drop
  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length === 0) return;

    // Read file contents
    const newAttachments: FileAttachment[] = [];
    for (const file of files) {
      try {
        const attachment = await readFile(file);
        newAttachments.push(attachment);
      } catch (err) {
        console.error("Error reading file:", file.name, err);
      }
    }

    setAttachments((prev) => [...prev, ...newAttachments]);
  }, []);

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current++;
    if (dragCounter.current === 1) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) {
      setIsDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSend = async () => {
    const content = input.trim();
    if (!content && attachments.length === 0) return;
    if (isLoading) return;

    if (!activeConvId) {
      await newConversation();
    }

    // Build message with attachments
    let fullContent = content;
    
    if (attachments.length > 0) {
      // Add file contents to the message
      const filesInfo = attachments.map((att) => {
        const ext = att.name.split('.').pop() || '';
        return `\`\`\`${ext}\n// File: ${att.name}\n${att.content}\n\`\`\``;
      }).join('\n\n');

      if (content) {
        fullContent = `${content}\n\n${filesInfo}`;
      } else {
        fullContent = `Here are the files:\n\n${filesInfo}`;
      }
    }

    setInput("");
    setAttachments([]);
    sendMessage(fullContent);
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

  // Only show chat errors (not backend_offline, that's handled by ModelSelector)
  const chatError = error && error !== "backend_offline" ? error : null;

  const canSend = input.trim() || attachments.length > 0;

  return (
    <div 
      className="flex flex-col h-full"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-40 bg-indigo-500/20 border-4 border-dashed border-indigo-500 flex items-center justify-center">
          <div className="bg-white dark:bg-zinc-800 px-6 py-4 rounded-xl shadow-xl flex items-center gap-3">
            <Upload className="w-8 h-8 text-indigo-500" />
            <span className="text-lg font-medium">Drop files to upload</span>
          </div>
        </div>
      )}

      {/* Error banner */}
      {chatError && (
        <div className="flex items-center gap-2 px-4 py-2 bg-red-50 border-b border-red-200 text-red-600 dark:bg-red-950 dark:border-red-800 dark:text-red-300 text-sm">
          <AlertCircle size={14} className="flex-shrink-0" />
          <span className="flex-1 truncate">{chatError}</span>
          <button onClick={() => useChatStore.setState({ error: null })}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((msg) => <Message key={msg.id} message={msg} />)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Attachments preview */}
      {attachments.length > 0 && (
        <div className="px-4 pb-2 flex flex-wrap gap-2">
          {attachments.map((att, index) => (
            <div
              key={index}
              className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-zinc-800 rounded-lg text-sm"
            >
              <File className="w-4 h-4 text-gray-500" />
              <span className="max-w-[150px] truncate">{att.name}</span>
              <button
                onClick={() => removeAttachment(index)}
                className="p-0.5 hover:bg-gray-200 dark:hover:bg-zinc-700 rounded"
              >
                <XCircle className="w-4 h-4 text-gray-400" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Input bar */}
      <div className="border-t border-gray-200 dark:border-zinc-800 px-4 py-4 bg-white dark:bg-zinc-950">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              adjustHeight();
            }}
            onKeyDown={handleKeyDown}
            placeholder={attachments.length > 0 
              ? "Add a message... (files will be attached)" 
              : "Message LocalForge… (Enter to send, Shift+Enter for newline)"}
            rows={1}
            className="flex-1 resize-none bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-xl px-4 py-3 text-sm text-gray-900 dark:text-zinc-100 placeholder-gray-400 dark:placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
            style={{ minHeight: "44px", maxHeight: "200px" }}
          />
          {pendingConfirmation ? (
            <button
              onClick={rejectConfirmation}
              className="p-3 bg-gray-500 hover:bg-gray-400 rounded-xl text-white transition-colors"
              title="Cancel"
            >
              <X size={18} />
            </button>
          ) : isLoading ? (
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
              disabled={!canSend}
              className="p-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-white transition-colors"
              title="Send"
            >
              <Send size={18} />
            </button>
          )}
        </div>
      </div>

      {/* Confirmation Modal */}
      {pendingConfirmation && (
        <ConfirmationModal
          confirmation={pendingConfirmation}
          onApprove={approveConfirmation}
          onReject={rejectConfirmation}
        />
      )}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 text-center py-20">
      <div className="w-16 h-16 rounded-2xl bg-gray-100 border border-gray-200 dark:bg-zinc-800 dark:border-zinc-700 flex items-center justify-center text-3xl">
        🔨
      </div>
      <h2 className="text-xl font-semibold text-gray-800 dark:text-zinc-200">LocalForge</h2>
      <p className="text-gray-400 dark:text-zinc-500 text-sm max-w-sm">
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
      className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 border border-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 dark:border-zinc-700 rounded-full text-xs text-gray-600 dark:text-zinc-300 transition-colors"
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
