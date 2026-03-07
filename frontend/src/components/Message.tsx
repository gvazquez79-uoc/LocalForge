import { useMemo, useState } from "react";
import type { UIMessage } from "../store/chat";
import { ToolBlock } from "./ToolBlock";
import { Bot, User, FileText, ChevronDown, ChevronRight, BrainCircuit } from "lucide-react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { usePrefs } from "../store/prefs";
import hljs from "highlight.js/lib/core";
import langPython from "highlight.js/lib/languages/python";
import langJavaScript from "highlight.js/lib/languages/javascript";
import langTypeScript from "highlight.js/lib/languages/typescript";
import langBash from "highlight.js/lib/languages/bash";
import langJson from "highlight.js/lib/languages/json";
import langCss from "highlight.js/lib/languages/css";
import langXml from "highlight.js/lib/languages/xml";
import langSql from "highlight.js/lib/languages/sql";
import langRust from "highlight.js/lib/languages/rust";
import langGo from "highlight.js/lib/languages/go";
import langYaml from "highlight.js/lib/languages/yaml";

// Register languages (core build = smaller bundle)
hljs.registerLanguage("python", langPython);
hljs.registerLanguage("javascript", langJavaScript);
hljs.registerLanguage("js", langJavaScript);
hljs.registerLanguage("typescript", langTypeScript);
hljs.registerLanguage("ts", langTypeScript);
hljs.registerLanguage("bash", langBash);
hljs.registerLanguage("sh", langBash);
hljs.registerLanguage("json", langJson);
hljs.registerLanguage("css", langCss);
hljs.registerLanguage("html", langXml);
hljs.registerLanguage("xml", langXml);
hljs.registerLanguage("sql", langSql);
hljs.registerLanguage("rust", langRust);
hljs.registerLanguage("go", langGo);
hljs.registerLanguage("yaml", langYaml);
hljs.registerLanguage("yml", langYaml);

// Extend Window to avoid TS error
declare global {
  interface Window { codeCopyHandlers?: boolean; }
}

marked.use({ gfm: true, breaks: true });

interface MessageProps {
  message: UIMessage;
}

const COPY_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const CHECK_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

// Custom renderer — highlight code + inject copy button
const createRenderer = () => {
  const renderer = new marked.Renderer();

  renderer.code = function({ text, lang }: { text: string; lang?: string }) {
    const language = (lang ?? "").toLowerCase();
    let highlighted: string;
    if (language && hljs.getLanguage(language)) {
      try {
        highlighted = hljs.highlight(text, { language }).value;
      } catch {
        highlighted = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      }
    } else {
      highlighted = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    const label = language || "text";
    return `<pre class="code-block"><span class="code-lang">${label}</span><code class="hljs language-${label}">${highlighted}</code><button class="code-copy-btn" data-code="${encodeURIComponent(text)}">${COPY_SVG}</button></pre>`;
  };

  return renderer;
};

// Setup click handler once
if (typeof window !== "undefined" && !window.codeCopyHandlers) {
  window.codeCopyHandlers = true;
  document.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement).closest('.code-copy-btn') as HTMLElement;
    if (!btn) return;
    
    const code = decodeURIComponent(btn.dataset.code || '');
    navigator.clipboard.writeText(code);
    
    btn.innerHTML = CHECK_SVG;
    btn.classList.add("copied");

    setTimeout(() => {
      btn.innerHTML = COPY_SVG;
      btn.classList.remove("copied");
    }, 2000);
  });
}

/** Strip / split <think> tokens from model output. */
function parseThinking(raw: string): { main: string; isThinking: boolean } {
  // Remove all complete <think>...</think> blocks
  let main = raw.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
  // Detect unclosed <think> (model is still streaming thoughts)
  const openIdx = main.indexOf("<think>");
  const isThinking = openIdx !== -1;
  if (isThinking) main = main.slice(0, openIdx).trim();
  return { main, isThinking };
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === "user";
  const { renderMarkdown, showToolCalls } = usePrefs();
  const [thinkExpanded, setThinkExpanded] = useState(false);

  // Parse thinking tokens out of the content
  const { main: visibleContent, isThinking } = useMemo(
    () => parseThinking(message.content ?? ""),
    [message.content]
  );

  // Extract thinking text for optional display (collapsed by default)
  const thinkingText = useMemo(() => {
    const parts: string[] = [];
    const re = /<think>([\s\S]*?)<\/think>/gi;
    let m: RegExpExecArray | null;
    while ((m = re.exec(message.content ?? "")) !== null) parts.push(m[1].trim());
    return parts.join("\n\n");
  }, [message.content]);

  const html = useMemo(() => {
    if (!visibleContent || !renderMarkdown || message.isStreaming) return null;
    const renderer = createRenderer();
    const rawHtml = marked.parse(visibleContent, { renderer }) as string;
    return DOMPurify.sanitize(rawHtml);
  }, [visibleContent, message.isStreaming, renderMarkdown]);

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"} mb-6`}>
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs ${
          isUser
            ? "bg-emerald-600 text-white"
            : "bg-gray-100 border border-gray-200 text-emerald-600 dark:bg-zinc-800 dark:border-zinc-700 dark:text-emerald-400"
        }`}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>

      <div className={`flex-1 max-w-[85%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        {!isUser && showToolCalls && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="w-full">
            {message.toolCalls.map((tc) => (
              <ToolBlock key={tc.id} tool={tc} result={message.toolResults?.[tc.id]} />
            ))}
          </div>
        )}

        {/* Attachment previews (images + PDFs) — shown above text for user messages */}
        {isUser && message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 justify-end mb-1">
            {message.attachments.map((att, i) =>
              att.isPdf ? (
                <div key={i} className="flex items-center gap-1.5 px-2.5 py-1.5 bg-emerald-500/80 rounded-sm text-xs text-white">
                  <FileText size={13} />
                  <span className="max-w-[160px] truncate">{att.name}</span>
                </div>
              ) : (
                <img
                  key={i}
                  src={att.dataUrl}
                  alt={att.name}
                  title={att.name}
                  className="h-24 max-w-[200px] object-cover rounded-sm border border-emerald-400/50"
                />
              )
            )}
          </div>
        )}

        {/* Thinking indicator — shown while model is reasoning (<think> not yet closed) */}
        {!isUser && message.isStreaming && isThinking && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs text-zinc-500 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700">
            <BrainCircuit size={13} className="animate-pulse text-violet-500" />
            <span>Pensando…</span>
          </div>
        )}

        {/* Collapsed thinking block — shown after model finishes thinking */}
        {!isUser && !message.isStreaming && thinkingText && (
          <button
            onClick={() => setThinkExpanded(v => !v)}
            className="flex items-center gap-1.5 text-xs text-zinc-400 dark:text-zinc-500 hover:text-violet-500 transition-colors"
          >
            {thinkExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <BrainCircuit size={12} />
            <span>{thinkExpanded ? "Ocultar razonamiento" : "Ver razonamiento"}</span>
          </button>
        )}
        {!isUser && thinkExpanded && thinkingText && (
          <div className="text-xs text-zinc-400 dark:text-zinc-500 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl px-3 py-2 whitespace-pre-wrap font-mono leading-relaxed max-h-48 overflow-y-auto">
            {thinkingText}
          </div>
        )}

        {(visibleContent || (message.isStreaming && !isThinking)) && (
          <div
            className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
              isUser
                ? "bg-emerald-600 text-white rounded-tr-sm"
                : "bg-gray-100 text-gray-900 rounded-tl-sm dark:bg-zinc-800 dark:text-zinc-100"
            }`}
          >
            {message.isStreaming && !visibleContent ? (
              <span className="inline-flex gap-1">
                <span className="animate-bounce delay-0">.</span>
                <span className="animate-bounce delay-100">.</span>
                <span className="animate-bounce delay-200">.</span>
              </span>
            ) : html ? (
              <div className="prose-chat" dangerouslySetInnerHTML={{ __html: html }} />
            ) : (
              <div className="whitespace-pre-wrap font-sans break-words">{visibleContent}</div>
            )}

            {message.isStreaming && visibleContent && (
              <span className="inline-block w-0.5 h-4 bg-gray-400 dark:bg-zinc-400 animate-pulse ml-0.5 align-text-bottom" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
