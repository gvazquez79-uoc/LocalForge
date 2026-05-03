import { useEffect, useRef, useState, useCallback } from "react";
import { Send, StopCircle, AlertCircle, X, Upload, File, XCircle, FileText, Paperclip, FolderOpen, FolderX, BookOpen, Wand2, Save } from "lucide-react";
import { useChatStore } from "../store/chat";
import type { ImagePayload } from "../store/chat";
import { getConfig, getProjectInstructions, saveProjectInstructions, getApiKey } from "../api/client";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000/api";
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

// Attachment size limits — loaded from backend config on mount; these are the defaults.
const DEFAULT_MAX_IMAGE_BYTES = 5  * 1024 * 1024;
const DEFAULT_MAX_PDF_BYTES   = 25 * 1024 * 1024;
const DEFAULT_MAX_TEXT_BYTES  = 512 * 1024;

const SUPPORTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp"];

const TEXT_EXTENSIONS = [
  "txt", "md", "csv", "tsv", "log", "ini", "cfg", "conf", "env",
  "json", "jsonl", "yaml", "yml", "toml", "xml", "html", "htm", "css", "scss",
  "js", "jsx", "ts", "tsx", "mjs", "cjs",
  "py", "rb", "go", "rs", "java", "kt", "c", "h", "cpp", "hpp", "cs",
  "php", "sh", "bash", "zsh", "ps1", "bat", "cmd",
  "sql", "graphql", "proto", "dockerfile", "makefile", "gitignore",
];

function isTextFile(file: File): boolean {
  if (file.type.startsWith("text/")) return true;
  if (!file.type) return true; // .py, .ts, .go … often have no MIME
  const textAppTypes = [
    "application/json", "application/javascript", "application/typescript",
    "application/xml",  "application/yaml",       "application/toml",
    "application/x-sh", "application/x-python",   "application/x-yaml",
    // Windows often reports CSV as Excel
    "application/vnd.ms-excel", "application/csv", "application/x-csv",
  ];
  if (textAppTypes.includes(file.type)) return true;
  // Fallback: detect by extension (Windows MIME types are unreliable)
  const ext = file.name.toLowerCase().split(".").pop() ?? "";
  return TEXT_EXTENSIONS.includes(ext);
}

function isImageFile(file: File): boolean {
  return SUPPORTED_IMAGE_TYPES.includes(file.type);
}

function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export function ChatWindow() {
  const messages           = useChatStore(s => s.messages);
  const isLoading          = useChatStore(s => s.isLoading);
  const sendMessage        = useChatStore(s => s.sendMessage);
  const stopStream         = useChatStore(s => s.stopStream);
  const activeConvId       = useChatStore(s => s.activeConvId);
  const newConversation    = useChatStore(s => s.newConversation);
  const error              = useChatStore(s => s.error);
  const pendingConfirmation = useChatStore(s => s.pendingConfirmation);
  const approveConfirmation = useChatStore(s => s.approveConfirmation);
  const rejectConfirmation  = useChatStore(s => s.rejectConfirmation);
  const workingDirectory    = useChatStore(s => s.workingDirectory);
  const setWorkingDir       = useChatStore(s => s.setWorkingDir);

  const [showDirInput, setShowDirInput]     = useState(false);
  const [dirInputValue, setDirInputValue]   = useState("");
  const [showInstructions, setShowInstructions] = useState(false);
  const [instructionsContent, setInstructionsContent] = useState("");
  const [instructionsFilename, setInstructionsFilename] = useState("LOCALFORGE.md");
  const [instructionsExists, setInstructionsExists] = useState(false);
  const [instructionsSaving, setInstructionsSaving] = useState(false);

  const [input, setInput]                           = useState("");
  const [attachments, setAttachments]               = useState<FileAttachment[]>([]);
  const [binaryAttachments, setBinaryAttachments]   = useState<BinaryAttachment[]>([]);
  const [isDragging, setIsDragging]                 = useState(false);
  const [fileErrors, setFileErrors]                 = useState<string[]>([]);
  const bottomRef   = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  // Attachment size limits — loaded from backend config; fall back to defaults if unavailable
  const [maxImageBytes, setMaxImageBytes] = useState(DEFAULT_MAX_IMAGE_BYTES);
  const [maxPdfBytes,   setMaxPdfBytes]   = useState(DEFAULT_MAX_PDF_BYTES);
  const [maxTextBytes,  setMaxTextBytes]  = useState(DEFAULT_MAX_TEXT_BYTES);

  useEffect(() => {
    getConfig()
      .then(cfg => {
        const att = cfg.tools?.attachments;
        if (att) {
          setMaxImageBytes(att.max_image_mb * 1024 * 1024);
          setMaxPdfBytes  (att.max_pdf_mb   * 1024 * 1024);
          setMaxTextBytes (att.max_text_kb  * 1024);
        }
      })
      .catch(() => { /* keep defaults */ });
  }, []);

  // Track only the last message ID for auto-scroll — avoids re-running on every text_delta
  const lastMsgId = useChatStore(s => s.messages[s.messages.length - 1]?.id);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lastMsgId]);

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
        if (file.size > maxImageBytes) {
          errors.push(`"${file.name}" — demasiado grande (máx ${maxImageBytes / 1024 / 1024} MB)`);
          continue;
        }
        try { newBinary.push(await readBinaryFile(file)); }
        catch { errors.push(`"${file.name}" — no se pudo leer`); }
      } else if (isPdfFile(file)) {
        if (file.size > maxPdfBytes) {
          errors.push(`"${file.name}" — demasiado grande (máx ${maxPdfBytes / 1024 / 1024} MB)`);
          continue;
        }
        try { newBinary.push(await readBinaryFile(file)); }
        catch { errors.push(`"${file.name}" — no se pudo leer`); }
      } else if (isTextFile(file)) {
        if (file.size > maxTextBytes) {
          errors.push(`"${file.name}" — demasiado grande (máx ${maxTextBytes / 1024} KB)`);
          continue;
        }
        try { newText.push(await readTextFile(file)); }
        catch { errors.push(`"${file.name}" — no se pudo leer`); }
      } else {
        errors.push(`"${file.name}" — tipo no soportado`);
      }
    }

    if (newText.length   > 0) setAttachments     (prev => [...prev, ...newText]);
    if (newBinary.length > 0) setBinaryAttachments(prev => [...prev, ...newBinary]);
    if (errors.length    > 0) { setFileErrors(errors); setTimeout(() => setFileErrors([]), 5000); }
  }, [maxImageBytes, maxPdfBytes, maxTextBytes]);

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

  // ── Paste image from clipboard (Ctrl+V / Cmd+V) ───────────────────────────
  // Listen at window level — more reliable than textarea onPaste for images.

  useEffect(() => {
    const onWindowPaste = async (e: ClipboardEvent) => {
      if (!e.clipboardData) return;
      const items = Array.from(e.clipboardData.items);

      // Strategy 1: items explicitly typed as images
      let imageItems = items.filter(item => item.type.startsWith("image/"));

      // Strategy 2: items with kind==="file" but no/unknown MIME (Windows Snipping Tool, etc.)
      if (imageItems.length === 0) {
        const fileItems = items.filter(item => item.kind === "file" && item.getAsFile() !== null);
        // Only intercept if they look like images (check actual file type after extraction)
        const extracted = fileItems
          .map(item => item.getAsFile())
          .filter((f): f is File => f !== null)
          .filter(f => f.type.startsWith("image/") || f.type === "" || f.type === "application/octet-stream");
        if (extracted.length > 0) {
          e.preventDefault();
          const files = extracted.map(f => {
            const mimeType = f.type || "image/png";
            const ext = mimeType.split("/")[1]?.split("+")[0] ?? "png";
            return new window.File([f as BlobPart], `captura_${Date.now()}.${ext}`, { type: mimeType });
          });
          await processFiles(files);
          return;
        }
      }

      if (imageItems.length === 0) return; // no image → let normal paste happen
      e.preventDefault();
      const files = imageItems
        .map(item => item.getAsFile())
        .filter((f): f is File => f !== null)
        .map(f => {
          const ext = f.type.split("/")[1]?.split("+")[0] ?? "png";
          return new window.File([f as BlobPart], `captura_${Date.now()}.${ext}`, { type: f.type });
        });
      if (files.length > 0) await processFiles(files);
    };
    window.addEventListener("paste", onWindowPaste);
    return () => window.removeEventListener("paste", onWindowPaste);
  }, [processFiles]);

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
    if (!activeConvId) {
      try {
        await newConversation();
      } catch {
        useChatStore.setState({ error: "No se pudo iniciar la conversación. ¿Está el backend activo?" });
        return;
      }
    }

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
    sendMessage(
      fullContent,
      images.length > 0 ? images : undefined,
      content,                                     // display text (no file contents)
      attachments.length > 0 ? attachments.map(a => a.name) : undefined,
    );
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
        <div className="absolute inset-0 z-40 bg-emerald-500/20 border-4 border-dashed border-emerald-500 rounded-none flex items-center justify-center pointer-events-none">
          <div className="bg-white dark:bg-zinc-800 px-6 py-4 rounded-xl shadow-xl flex items-center gap-3">
            <Upload className="w-8 h-8 text-lime-500" />
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
            <div key={`txt-${i}`} className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 dark:bg-zinc-800 rounded-sm text-sm">
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
              <div key={`pdf-${i}`} className="flex items-center gap-2 px-3 py-1.5 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-sm text-sm">
                <FileText className="w-4 h-4 text-red-500 flex-shrink-0" />
                <span className="max-w-[140px] truncate text-red-700 dark:text-red-300">{att.name}</span>
                <button onClick={() => removeBinaryAttachment(i)} className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900 rounded">
                  <XCircle className="w-4 h-4 text-red-400" />
                </button>
              </div>
            ) : (
              <div key={`img-${i}`} className="relative group rounded-sm overflow-hidden border border-gray-200 dark:border-zinc-700 flex-shrink-0">
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

        {/* Project directory popover */}
        {showDirInput && (
          <div className="max-w-4xl mx-auto mb-2">
            <form
              className="flex items-center gap-2 bg-gray-50 dark:bg-zinc-900 border border-emerald-400 rounded-xl px-3 py-2"
              onSubmit={(e) => {
                e.preventDefault();
                const val = dirInputValue.trim();
                setWorkingDir(val || null);
                setShowDirInput(false);
              }}
            >
              <FolderOpen size={14} className="text-emerald-500 flex-shrink-0" />
              <input
                autoFocus
                type="text"
                value={dirInputValue}
                onChange={(e) => setDirInputValue(e.target.value)}
                placeholder="Ruta del proyecto, ej: G:\proyectos\MiApp"
                className="flex-1 bg-transparent text-sm text-gray-800 dark:text-zinc-100 placeholder-gray-400 dark:placeholder-zinc-500 focus:outline-none"
              />
              <button type="submit" className="px-3 py-1 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-medium">
                Aceptar
              </button>
              <button type="button" onClick={() => setShowDirInput(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300">
                <X size={14} />
              </button>
            </form>
          </div>
        )}

        {/* Active project badge */}
        {workingDirectory && !showDirInput && (
          <div className="max-w-4xl mx-auto mb-2 flex items-center gap-2 px-3 py-1.5 bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 rounded-lg text-xs">
            <FolderOpen size={12} className="text-emerald-500 flex-shrink-0" />
            <span className="flex-1 font-mono text-emerald-700 dark:text-emerald-400 truncate" title={workingDirectory}>{workingDirectory}</span>
            <button onClick={() => { setDirInputValue(workingDirectory); setShowDirInput(true); }} className="text-emerald-500 hover:text-emerald-700 transition-colors" title="Cambiar">
              <FolderOpen size={12} />
            </button>
            <button onClick={() => setWorkingDir(null)} className="text-emerald-400 hover:text-red-500 transition-colors" title="Quitar">
              <FolderX size={12} />
            </button>
          </div>
        )}

        <div className="flex gap-2 items-end max-w-4xl mx-auto">

          {/* Folder / file picker buttons */}
          <div className="flex flex-col gap-1 flex-shrink-0">
            {/* Project folder button */}
            <button
              onClick={() => { setDirInputValue(workingDirectory ?? ""); setShowDirInput(s => !s); }}
              title={workingDirectory ? `Proyecto: ${workingDirectory}` : "Establecer directorio de proyecto"}
              className={`p-2.5 rounded-xl transition-colors ${
                workingDirectory
                  ? "bg-emerald-100 hover:bg-emerald-200 dark:bg-emerald-900/40 dark:hover:bg-emerald-800/60 text-emerald-600 dark:text-emerald-400"
                  : "bg-gray-100 hover:bg-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-gray-500 dark:text-zinc-400"
              }`}
            >
              <FolderOpen size={16} />
            </button>
            {/* Attach file button */}
            <label
              className="p-2.5 bg-gray-100 hover:bg-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 rounded-xl cursor-pointer transition-colors"
              title="Adjuntar archivo"
            >
              <Paperclip size={16} className="text-gray-500 dark:text-zinc-400" />
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                multiple
                accept="image/jpeg,image/png,image/gif,image/webp,application/pdf,text/*,.json,.yaml,.yml,.toml,.py,.ts,.js,.tsx,.jsx,.go,.rs,.java,.cpp,.c,.h,.sh,.md"
                onChange={handleFileInput}
              />
            </label>

            {/* LOCALFORGE.md button — only shown when project dir is set */}
            {workingDirectory && (
              <button
                onClick={async () => {
                  if (!showInstructions) {
                    try {
                      const data = await getProjectInstructions(workingDirectory);
                      setInstructionsContent(data.content);
                      setInstructionsFilename(data.filename);
                      setInstructionsExists(data.exists);
                    } catch { /* keep current state */ }
                  }
                  setShowInstructions(v => !v);
                }}
                title={instructionsExists ? "Editar LOCALFORGE.md" : "Crear LOCALFORGE.md"}
                className={`p-2.5 rounded-xl transition-colors ${
                  instructionsExists
                    ? "bg-violet-100 hover:bg-violet-200 dark:bg-violet-900/30 dark:hover:bg-violet-800/50 text-violet-600 dark:text-violet-400"
                    : "bg-gray-100 hover:bg-gray-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-gray-400 dark:text-zinc-500"
                }`}
              >
                <BookOpen size={16} />
              </button>
            )}
          </div>

          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); adjustHeight(); }}
            onKeyDown={handleKeyDown}
            placeholder={
              totalAttachments > 0
                ? "Añade un mensaje... (los archivos se adjuntarán)"
                : "Escribe a LocalForge… (Enter para enviar, Shift+Enter para nueva línea, Ctrl+V para pegar imagen)"
            }
            rows={1}
            className="flex-1 resize-none bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-xl px-4 py-3 text-sm text-gray-900 dark:text-zinc-100 placeholder-gray-400 dark:placeholder-zinc-500 focus:outline-none focus:border-emerald-500 transition-colors"
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
            <button onClick={handleSend} disabled={!canSend} className="p-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-xl text-white transition-colors" title="Enviar">
              <Send size={18} />
            </button>
          )}
        </div>
      </div>

      {/* Confirmation modal */}
      {pendingConfirmation && (
        <ConfirmationModal
          confirmation={pendingConfirmation}
          onApprove={async (saveForProject) => {
            if (saveForProject && pendingConfirmation.permission_type && pendingConfirmation.project_path) {
              try {
                const apiKey = getApiKey();
                await fetch(`${API_BASE}/permissions/grant`, {
                  method: "POST",
                  headers: {
                    "Content-Type": "application/json",
                    ...(apiKey ? { "X-API-Key": apiKey } : {}),
                  },
                  body: JSON.stringify({
                    project_path: pendingConfirmation.project_path,
                    permission_type: pendingConfirmation.permission_type,
                  }),
                });
              } catch (_) { /* silently ignore */ }
            }
            approveConfirmation();
          }}
          onReject={rejectConfirmation}
        />
      )}

      {/* LOCALFORGE.md editor modal */}
      {showInstructions && workingDirectory && (
        <div className="absolute inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col max-h-[80vh]">
            {/* Header */}
            <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-200 dark:border-zinc-700">
              <BookOpen size={16} className="text-emerald-500" />
              <div className="flex-1">
                <h3 className="font-semibold text-gray-900 dark:text-zinc-100 text-sm">
                  {instructionsFilename}
                </h3>
                <p className="text-xs text-gray-400 dark:text-zinc-500 truncate">{workingDirectory}</p>
              </div>
              <button
                onClick={() => {
                  const msg = `Explora el proyecto en ${workingDirectory} (estructura de archivos, dependencias, tecnologías) y genera un archivo LOCALFORGE.md completo con: descripción del proyecto, stack tecnológico, estructura de directorios, cómo ejecutar, convenciones de código y cualquier información relevante para trabajar en él.`;
                  setShowInstructions(false);
                  useChatStore.getState().sendMessage(msg);
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-100 hover:bg-violet-200 dark:bg-violet-900/30 dark:hover:bg-violet-800/50 text-violet-600 dark:text-violet-400 text-xs font-medium transition-colors"
                title="El agente explorará el proyecto y generará el archivo automáticamente"
              >
                <Wand2 size={12} />
                Generar automáticamente
              </button>
              <button onClick={() => setShowInstructions(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300 ml-1">
                <X size={16} />
              </button>
            </div>

            {/* Textarea */}
            <textarea
              value={instructionsContent}
              onChange={(e) => setInstructionsContent(e.target.value)}
              placeholder={`# Mi Proyecto\n\n## Stack\n- ...\n\n## Estructura\n- src/ — código fuente\n- ...\n\n## Cómo ejecutar\n...\n\n## Convenciones\n...`}
              className="flex-1 resize-none px-5 py-4 text-sm font-mono text-gray-800 dark:text-zinc-100 bg-transparent placeholder-gray-300 dark:placeholder-zinc-600 focus:outline-none min-h-[300px]"
            />

            {/* Footer */}
            <div className="flex items-center justify-between px-5 py-3 border-t border-gray-200 dark:border-zinc-700">
              <p className="text-xs text-gray-400 dark:text-zinc-500">
                Se inyecta en el system prompt de cada mensaje de esta conversación.
              </p>
              <button
                disabled={instructionsSaving}
                onClick={async () => {
                  setInstructionsSaving(true);
                  try {
                    await saveProjectInstructions(workingDirectory, instructionsContent, instructionsFilename);
                    setInstructionsExists(true);
                    setShowInstructions(false);
                  } catch (e) {
                    alert(`Error al guardar: ${e}`);
                  } finally {
                    setInstructionsSaving(false);
                  }
                }}
                className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm font-medium transition-colors"
              >
                <Save size={13} />
                {instructionsSaving ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </div>
        </div>
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
    if (!activeConvId) {
      try { await newConversation(); } catch { return; }
    }
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
