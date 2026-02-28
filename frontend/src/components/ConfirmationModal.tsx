import { useState } from "react";
import { AlertTriangle, X, Check, Terminal, FileText, Trash2 } from "lucide-react";

export interface PendingConfirmation {
  tool_use_id: string;
  name: string;
  input: Record<string, unknown>;
  message: string;
}

interface ConfirmationModalProps {
  confirmation: PendingConfirmation;
  onApprove: () => void;
  onReject: () => void;
}

export function ConfirmationModal({ confirmation, onApprove, onReject }: ConfirmationModalProps) {
  const [loading, setLoading] = useState(false);

  const handleApprove = async () => {
    setLoading(true);
    onApprove();
  };

  const getIcon = () => {
    switch (confirmation.name) {
      case "execute_command":
        return <Terminal className="w-5 h-5" />;
      case "write_file":
        return <FileText className="w-5 h-5" />;
      case "delete_file":
        return <Trash2 className="w-5 h-5" />;
      default:
        return <AlertTriangle className="w-5 h-5" />;
    }
  };

  const getColor = () => {
    switch (confirmation.name) {
      case "delete_file":
        return "text-red-500 bg-red-50 dark:bg-red-950/30";
      case "execute_command":
        return "text-orange-500 bg-orange-50 dark:bg-orange-950/30";
      default:
        return "text-yellow-500 bg-yellow-50 dark:bg-yellow-950/30";
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onReject} />
      
      {/* Modal */}
      <div className="relative bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden">
        {/* Header */}
        <div className={`flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-zinc-700 ${getColor()}`}>
          {getIcon()}
          <span className="font-semibold">Confirmation Required</span>
          <button
            onClick={onReject}
            className="ml-auto p-1 hover:bg-black/10 rounded-lg"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4">
          <pre className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap font-mono bg-gray-50 dark:bg-zinc-800 p-3 rounded-lg max-h-48 overflow-y-auto">
            {confirmation.message}
          </pre>
        </div>

        {/* Actions */}
        <div className="flex gap-3 px-4 py-3 border-t border-gray-200 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800/50">
          <button
            onClick={onReject}
            disabled={loading}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-gray-300 dark:border-zinc-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-zinc-700 transition-colors"
          >
            <X className="w-4 h-4" />
            Cancel
          </button>
          <button
            onClick={handleApprove}
            disabled={loading}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-500 text-white transition-colors"
          >
            <Check className="w-4 h-4" />
            {loading ? "Executing..." : "Execute"}
          </button>
        </div>
      </div>
    </div>
  );
}
