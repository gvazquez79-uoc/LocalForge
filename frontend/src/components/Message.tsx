import { useMemo } from "react";
import type { UIMessage } from "../store/chat";
import { ToolBlock } from "./ToolBlock";
import { Bot, User } from "lucide-react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { usePrefs } from "../store/prefs";

marked.use({ gfm: true, breaks: true });

interface MessageProps {
  message: UIMessage;
}

// Custom renderer that adds copy buttons to code blocks
const createRenderer = () => {
  const renderer = new marked.Renderer();
  
  renderer.code = function({ text, lang }: { text: string; lang?: string }) {
    const language = lang || 'text';
    const escapedCode = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
    
    return `<pre class="code-block"><code class="language-${language}">${escapedCode}</code><button class="code-copy-btn" data-code="${encodeURIComponent(text)}"><svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg></button></pre>`;
  };
  
  return renderer;
};

// Setup click handler once
if (typeof window !== 'undefined' && !window.codeCopyHandlers) {
  window.codeCopyHandlers = true;
  document.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement).closest('.code-copy-btn') as HTMLElement;
    if (!btn) return;
    
    const code = decodeURIComponent(btn.dataset.code || '');
    navigator.clipboard.writeText(code);
    
    btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    btn.classList.add('copied');
    
    setTimeout(() => {
      btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
      btn.classList.remove('copied');
    }, 2000);
  });
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === "user";
  const { renderMarkdown } = usePrefs();

  const html = useMemo(() => {
    if (!message.content || !renderMarkdown || message.isStreaming) return null;
    
    const renderer = createRenderer();
    const rawHtml = marked.parse(message.content, { renderer }) as string;
    return DOMPurify.sanitize(rawHtml);
  }, [message.content, message.isStreaming, renderMarkdown]);

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"} mb-6`}>
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs ${
          isUser
            ? "bg-indigo-600 text-white"
            : "bg-gray-100 border border-gray-200 text-emerald-600 dark:bg-zinc-800 dark:border-zinc-700 dark:text-emerald-400"
        }`}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      <div className={`flex-1 max-w-[85%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="w-full">
            {message.toolCalls.map((tc) => (
              <ToolBlock key={tc.id} tool={tc} result={message.toolResults?.[tc.id]} />
            ))}
          </div>
        )}

        {(message.content || message.isStreaming) && (
          <div
            className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
              isUser
                ? "bg-indigo-600 text-white rounded-tr-sm"
                : "bg-gray-100 text-gray-900 rounded-tl-sm dark:bg-zinc-800 dark:text-zinc-100"
            }`}
          >
            {message.isStreaming && !message.content ? (
              <span className="inline-flex gap-1">
                <span className="animate-bounce delay-0">.</span>
                <span className="animate-bounce delay-100">.</span>
                <span className="animate-bounce delay-200">.</span>
              </span>
            ) : html ? (
              <div className="prose-chat" dangerouslySetInnerHTML={{ __html: html }} />
            ) : (
              <div className="whitespace-pre-wrap font-sans break-words">{message.content}</div>
            )}

            {message.isStreaming && message.content && (
              <span className="inline-block w-0.5 h-4 bg-gray-400 dark:bg-zinc-400 animate-pulse ml-0.5 align-text-bottom" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
