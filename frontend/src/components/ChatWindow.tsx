import { useEffect, useRef, useState, useCallback } from "react";
import { Send, StopCircle, AlertCircle, X, Upload, File, XCircle, FileText, Paperclip } from "lucide-react";
import { useChatStore } from "../store/chat";
import type { ImagePayload } from "../store/chat";
import { Message } from "./Message";
import { ConfirmationModal } from "./ConfirmationModal";

interface FileAttachment {
  name: string;
  content: string;
  size: number;
  type: string;
}

interface BinaryAttachment {
  name: string;
  dataUrl: string;   // full data:mime/type;base64,... URL
  mimeType: string;
  size: number;
  isPdf: boolean;
}

const MAX_FILE_SIZE   = 512 * 1024;       // 512 KB – text files
const MAX_IMAGE_SIZE  = 5  * 1024 * 1024; // 5 MB  – images
const MAX_PDF_SIZE    = 10 * 1024 * 1024; // 10 MB – PDFs

const SUPPORTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

function isTextFile(file: File): boolean {
  if (file.type.startsWith("text/")) return true;
  if (!file.type) return true; // .py, .ts, .go … often have no MIME
  const textAppTypes = [
    "application/json", "application/javascript", "application/typescript",
    "application/xml",  "application/yaml",       "application/toml",
    "application/x-sh", "application/x-python",   "application/x-yaml",
  ];
  return textAppTypes.includes(file.type);
}

function isImageFile(file: File): boolean {
  return SUPPORTED_IMAGE_TYPES.includes(file.type);
}

function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
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
    rejectConfirmation,
  } = useChatStore();

  const [input, setInput]                           = useState("");
  const [attachments, setAttachments]               = useState<FileAttachment[]>([]);
  const [binaryAttachments, setBinaryAttachments]   = useState<BinaryAttachment[]>([]);
  const [isDragging, setIsDragging]                 = useState(false);
  const [fileErrors, setFileErrors]                 = useState<string[]>([]);
  const bottomRef   = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── File readers ─────────────────────────────────────────────────────────

  const readTextFile = (file: File): Promise<FileAttachment> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = () => resolve({ name: file.name, content: reader.result as string, size: file.size, type: file.type });
      reader.onerror = reject;
      reader.readAsText(file);
    });

  const readBinaryFile = (file: File): Promise<BinaryAttachment> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = () => resolve({
        name:     file.name,
        dataUrl:  reader.result as string,
        mimeType: file.type || (isPdfFile(file) ? "application/pdf" : "application/octet-stream"),
        size:     file.size,
        isPdf:    isPdfFile(file),
      });
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  // ── Shared file processing ────────────────────────────────────────────────

  const processFiles = useCallback(async (files: File[]) => {
    const newText:   FileAttachment[]   = [];
    const newBinary: BinaryAttachment[] = [];
    const errors:    string[]           = [];

    for (const file of files) {
      if (isImageFile(file)) {
        if (file.size > MAX_IMAGE_SIZE) { errors.push(`"${file.name}" — demasiado grande (máx 5 MB)`); continue; }
        try { newBinary.push(await readBinaryFile(file)); }
        catch { errors.push(`"${file.name}" — no se pudo leer`); }
      } else if (isPdfFile(file)) {
        if (file.size > MAX_PDF_SIZE) { errors.push(`"${file.name}" — demasiado grande (máx 10 MB)`); continue; }
        try { newBinary.push(await readBinaryFile(file)); }
        catch { errors.push(`"${file.name}" — no se pudo leer`); }
      } else if (isTextFile(file)) {
        if (file.size > MAX_FILE_SIZE) { errors.push(`"${file.name}" — demasiado grande (máx 512 KB)`); continue; }
        try { newText.push(await readTextFile(file)); }
        catch { errors.push(`"${file.name}" — no se pudo leer`); }
      } else {
        errors.push(`"${file.name}" — tipo no soportado`);
      }
    }

    if (newText.length   > 0) setAttachments     (prev => [...prev, ...newText]);
    if (newBinary.length > 0) setBinaryAttachments(prev => [...prev, ...newBinary]);
    if (errors.length    > 0) { setFileErrors(errors); setTimeout(() => setFileErrors([]), 5000); }
  }, []);

  // ── Drag & drop handlers ──────────────────────────────────────────────────

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current = 0;
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) await processFiles(files);
  }, [processFiles]);

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current++;
    if (dragCounter.current === 1) setIsDragging(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    dragCounter.current--;
    if (dragCounter.current === 0) setIsDragging(false);
  };
  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); e.stopPropagation(); };

  // ── File picker ───────────────────────────────────────────────────────────

  const handleFileInput = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // reset so same file can be picked again
    if (files.length > 0) await processFiles(files);
  }, [processFiles]);

  // ── Remove attachments ────────────────────────────────────────────────────

  const removeAttachment       = (i: number) => setAttachments     (prev => prev.filter((_, idx) => idx !== i));
  const removeBinaryAttachment = (i: number) => setBinaryAttachments(prev => prev.filter((_, idx) => idx !== i));

  // ── Send ──────────────────────────────────────────────────────────────────

  const handleSend = async () => {
    const content = input.trim();
    if (!content && attachments.length === 0 && binaryAttachments.length === 0) return;
    if (isLoading) return;
    if (!activeConvId) await newConversation();

    // Embed text file contents in the message body
    let fullContent = content;
    if (attachments.length > 0) {
      const filesInfo = attachments.map(att => {
        const ext = att.name.split(".").pop() ?? "";
        return `\`\`\`${ext}\n// Archivo: ${att.name}\n${att.content}\n\`\`\``;
      }).join("\n\n");
      fullContent = content ? `${content}\n\n${filesInfo}` : `Aquí están los archivos:\n\n${filesInfo}`;
    }

    // Collect image/PDF payloads
    const images: ImagePayload[] = binaryAttachments.map(a => ({
      name:      a.name,
      data_url:  a.dataUrl,
      mime_type: a.mimeType,
    }));

    setInput("");
    setAttachments([]);
    setBinaryAttachments([]);
    sendMessage(fullContent, images.length > 0 ? images : undefined);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const adjustHeight = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const chatError = error && error !== "backend_offline" ? error : null;
  const canSend   = !!(input.trim() || attachments.length > 0 || binaryAttachments.length > 0);
  const totalAttachments = attachments.length + binaryAttachments.length;

  return (
    <div
      className="flex flex-col h-full relative"
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 z-40 bg-indigo-500/20 border-4 border-dashed border-indigo-500 rounded-none flex items-center justify-center pointer-events-none">
          <div className="bg-white dark:bg-zinc-800 px-6 py-4 rounded-xl shadow-xl flex items-center gap-3">
            <Upload className="w-8 h-8 text-indigo-500" />
            <div>
              <p className="font-semibold text-gray-900 dark:text-zinc-100">Suelta aquí</p>
              <p className="text-xs text-gray-500 dark:text-zinc-400 mt-0.5">
                Imágenes · PDFs · Archivos de texto
              </p>
            </div>
          </div>
        </div>
      )}

      {/* File-error banner */}
      {fileErrors.length > 0 && (
        <div className="flex items-start gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 dark:bg-amber-950/40 dark:border-amber-800 text-amber-700 dark:text-amber-300 text-xs">
          <AlertCircle size={13} className="flex-shrink-0 mt-0.5" />
          <div className="flex-1">{fileErrors.map((err, i) => <div key={i}>{err}</div>)}</div>
          <button onClick={() => setFileErrors([])}><X size={13} /></button>
        </div>
      )}

      {/* Chat error banner */}
      {chatError && (
        <div className="flex items-center gap-2 px-4 py-2 bg-red-50 border-b border-red-200 text-red-600 dark:bg-red-950 dark:border-red-800 dark:text-red-300 text-sm">
          <AlertCircle size={14} className="flex-shrink-0" />
          <span className="flex-1 truncate">{chatError}</span>
          <button onClick={() => useChatStore.setState({ error: null })}><X size={14} /></button>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? <EmptyState /> : messages.map(msg => <Message key={msg.id} message={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* Attachment previews */}
      {totalAttachments > 0 && (
        <div className="px-4 pb-2 flex flex-wrap gap-2">
          {/* Text file chips */}
          {attachments.map((att, i) => (
            <div key={`txt-${i}`} className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-zinc-800 rounded-lg text-sm">
              <File className="w-4 h-4 text-gray-500 flex-shrink-0" />
              <span className="max-w-[140px] truncate">{att.name}</span>
              <button onClick={() => removeAttachment(i)} className="p-0.5 hover:bg-gray-200 dark:hover:bg-zinc-700 rounded">
                <XCircle className="w-4 h-4 text-gray-400" />
              </button>
            </div>
          ))}

          {/* Image thumbnails + PDF chips */}
          {binaryAttachments.map((att, i) =>
            att.isPdf ? (
              <div key={`pdf-${i}`} className="flex items-center gap-2 px-3 py-1.5 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg text-sm">
                <FileText className="w-4 h-4 text-red-500 flex-shrink-0" />
                <span className="max-w-[140px] truncate text-red-700 dark:text-red-300">{att.name}</span>
                <button onClick={() => removeBinaryAttachment(i)} className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900 rounded">
                  <XCircle className="w-4 h-4 text-red-400" />
                </button>
              </div>
            ) : (
              <div key={`img-${i}`} className="relative group rounded-lg overflow-hidden border border-gray-200 dark:border-zinc-700 flex-shrink-0">
                <img src={att.dataUrl} alt={att.name} className="h-16 w-16 object-cover" title={att.name} />
                <button
                  onClick={() => removeBinaryAttachment(i)}
                  className="absolute top-0.5 right-0.5 p-0.5 bg-black/60 hover:bg-black/80 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <X className="w-3 h-3 text-white" />
                </button>
              </div>
            )
          )}
        </div>
      )}

      {/* Input bar */}
      <div className="border-t border-gray-200 dark:border-zinc-800 px-4 py-4 bg-white dark:bg-zinc-950">
        <div className="flex gap-2 items-end max-w-4xl mx-auto">

          {/* File picker button */}
          <label
            className="flex-shrink-0 p-3 bg-gray-100 hover:bg-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 rounded-xl cursor-pointer transition-colors"
            title="Adjuntar archivo (imágenes, PDFs, texto)"
          >
            <Paperclip size={18} className="text-gray-500 dark:text-zinc-400" />
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              multiple
              accept="image/jpeg,image/png,image/gif,image/webp,application/pdf,text/*,.json,.yaml,.yml,.toml,.py,.ts,.js,.tsx,.jsx,.go,.rs,.java,.cpp,.c,.h,.sh,.md"
              onChange={handleFileInput}
            />
          </label>

          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); adjustHeight(); }}
            onKeyDown={handleKeyDown}
            placeholder={
              totalAttachments > 0
                ? "Añade un mensaje... (los archivos se adjuntarán)"
                : "Escribe a LocalForge… (Enter para enviar, Shift+Enter para nueva línea)"
            }
            rows={1}
            className="flex-1 resize-none bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-xl px-4 py-3 text-sm text-gray-900 dark:text-zinc-100 placeholder-gray-400 dark:placeholder-zinc-500 focus:outline-none focus:border-indigo-500 transition-colors"
            style={{ minHeight: "44px", maxHeight: "200px" }}
          />

          {pendingConfirmation ? (
            <button onClick={rejectConfirmation} className="p-3 bg-gray-500 hover:bg-gray-400 rounded-xl text-white transition-colors" title="Cancelar">
              <X size={18} />
            </button>
          ) : isLoading ? (
            <button onClick={() => stopStream?.()} className="p-3 bg-red-600 hover:bg-red-500 rounded-xl text-white transition-colors" title="Detener">
              <StopCircle size={18} />
            </button>
          ) : (
            <button onClick={handleSend} disabled={!canSend} className="p-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-white transition-colors" title="Enviar">
              <Send size={18} />
            </button>
          )}
        </div>
      </div>

      {/* Confirmation modal */}
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
        Tu agente de IA local con acceso a archivos, terminal, web y análisis de imágenes.
        <br />
        Escribe o arrastra archivos para empezar.
      </p>
      <div className="flex flex-wrap gap-2 justify-center mt-2">
        {SUGGESTIONS.map(s => <SuggestionChip key={s} text={s} />)}
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
  "Lista los archivos de mi directorio home",
  "Busca noticias recientes sobre IA",
  "¿Qué procesos están corriendo ahora?",
  "Busca archivos Python en ~/Projects",
];
