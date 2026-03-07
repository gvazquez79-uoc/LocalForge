import { useEffect, useRef } from "react";
import { AlertTriangle, AlertCircle, Info, Trash2, X } from "lucide-react";

export interface ConfirmDialogOptions {
  title: string;
  message: string;
  detail?: string;          // optional secondary text (e.g. model name / path)
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "info";
}

interface ConfirmDialogProps extends ConfirmDialogOptions {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

const VARIANTS = {
  danger: {
    icon: Trash2,
    iconClass: "text-red-500",
    headerClass: "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800/60",
    confirmClass: "bg-red-600 hover:bg-red-500 focus-visible:ring-red-500",
  },
  warning: {
    icon: AlertTriangle,
    iconClass: "text-amber-500",
    headerClass: "bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800/60",
    confirmClass: "bg-amber-500 hover:bg-amber-400 focus-visible:ring-amber-500",
  },
  info: {
    icon: Info,
    iconClass: "text-blue-500",
    headerClass: "bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800/60",
    confirmClass: "bg-blue-600 hover:bg-blue-500 focus-visible:ring-blue-500",
  },
} as const;

export function ConfirmDialog({
  open,
  title,
  message,
  detail,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "danger",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const v = VARIANTS[variant];
  const Icon = v.icon;

  // Close on Escape, focus confirm button when opened
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", handler);
    // Auto-focus cancel button (safer default for destructive actions)
    const frame = requestAnimationFrame(() => {
      confirmRef.current?.closest("[data-dialog]")
        ?.querySelector<HTMLButtonElement>("[data-cancel]")
        ?.focus();
    });
    return () => {
      window.removeEventListener("keydown", handler);
      cancelAnimationFrame(frame);
    };
  }, [open, onCancel, onConfirm]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Dialog */}
      <div
        data-dialog
        className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden
                   ring-1 ring-black/10 dark:ring-white/10
                   animate-[dialog-pop_0.15s_ease-out]"
        style={{ animation: "dialog-pop 0.15s ease-out" }}
      >
        {/* Header */}
        <div className={`flex items-center gap-3 px-5 py-4 border-b ${v.headerClass}`}>
          <div className={`shrink-0 ${v.iconClass}`}>
            <Icon className="w-5 h-5" />
          </div>
          <span className="font-semibold text-gray-900 dark:text-gray-100 flex-1">
            {title}
          </span>
          <button
            onClick={onCancel}
            className="shrink-0 p-1 rounded-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300
                       hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-2">
          <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
            {message}
          </p>
          {detail && (
            <p className="text-xs font-mono bg-gray-100 dark:bg-zinc-800 text-gray-600 dark:text-gray-400
                          px-3 py-2 rounded-sm truncate">
              {detail}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2 px-5 py-4 border-t border-gray-100 dark:border-zinc-800">
          <button
            data-cancel
            onClick={onCancel}
            className="flex-1 px-4 py-2 rounded-xl text-sm font-medium
                       border border-gray-300 dark:border-zinc-600
                       text-gray-700 dark:text-gray-300
                       hover:bg-gray-100 dark:hover:bg-zinc-800
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gray-400
                       transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`flex-1 px-4 py-2 rounded-xl text-sm font-medium text-white
                        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
                        transition-colors ${v.confirmClass}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>

      {/* Keyframe injected inline so it doesn't need a global CSS file */}
      <style>{`
        @keyframes dialog-pop {
          from { opacity: 0; transform: scale(0.95) translateY(4px); }
          to   { opacity: 1; transform: scale(1)    translateY(0); }
        }
      `}</style>
    </div>
  );
}
