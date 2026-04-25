import { useState, useEffect } from "react";
import { AlertTriangle, X, Check, Terminal, FileText, Trash2, FolderLock } from "lucide-react";

export interface PendingConfirmation {
  tool_use_id: string;
  name: string;
  input: Record<string, unknown>;
  message: string;
  permission_type?: string;
  project_path?: string;
}

interface ConfirmationModalProps {
  confirmation: PendingConfirmation;
  onApprove: (saveForProject: boolean) => void;
  onReject: () => void;
}

export function ConfirmationModal({ confirmation, onApprove, onReject }: ConfirmationModalProps) {
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onReject();
      if (e.key === "Enter" && !loading) { setLoading(true); onApprove(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [loading, onApprove, onReject]);

  const handleOnce = () => {
    setLoading(true);
    onApprove(false);
  };

  const handleForProject = () => {
    setLoading(true);
    onApprove(true);
  };

  const getIcon = () => {
    switch (confirmation.name) {
      case "execute_command": return <Terminal className="w-5 h-5" />;
      case "write_file":
      case "edit_file":       return <FileText className="w-5 h-5" />;
      case "delete_file":     return <Trash2 className="w-5 h-5" />;
      default:                return <AlertTriangle className="w-5 h-5" />;
    }
  };

  const getColor = () => {
    switch (confirmation.name) {
      case "delete_file":     return "text-red-500 bg-red-50 dark:bg-red-950/30";
      case "execute_command": return "text-orange-500 bg-orange-50 dark:bg-orange-950/30";
      default:                return "text-yellow-500 bg-yellow-50 dark:bg-yellow-950/30";
    }
  };

  const projectName = confirmation.project_path
    ? confirmation.project_path.split(/[\\/]/).filter(Boolean).pop()
    : null;

  const canSaveForProject = !!(confirmation.permission_type && confirmation.project_path);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onReject} />

      {/* Modal */}
      <div className="relative bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden">
        {/* Header */}
        <div className={`flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-zinc-700 ${getColor()}`}>
          {getIcon()}
          <span className="font-semibold">Confirmación requerida</span>
          <button onClick={onReject} className="ml-auto p-1 hover:bg-black/10 rounded-sm">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4">
          <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono bg-gray-50 dark:bg-zinc-800 p-3 rounded-sm max-h-48 overflow-y-auto">
            {confirmation.message}
          </pre>
        </div>

        {/* Actions */}
        <div className="flex flex-col gap-2 px-4 py-3 border-t border-gray-200 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800/50">
          <div className="flex gap-2">
            <button
              onClick={onReject}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-sm border border-gray-300 dark:border-zinc-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-zinc-700 transition-colors text-sm"
            >
              <X className="w-4 h-4" />
              Cancelar <span className="text-xs opacity-50 ml-1">Esc</span>
            </button>
            <button
              onClick={handleOnce}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-sm bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-60 text-sm"
            >
              <Check className="w-4 h-4" />
              {loading ? "Ejecutando…" : <>Solo esta vez <span className="text-xs opacity-70 ml-1">Enter</span></>}
            </button>
          </div>

          {canSaveForProject && (
            <button
              onClick={handleForProject}
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-sm bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-60 text-sm"
            >
              <FolderLock className="w-4 h-4" />
              Permitir siempre en <strong className="mx-1">{projectName ?? "este proyecto"}</strong>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
