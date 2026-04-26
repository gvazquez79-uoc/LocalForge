import { useState, useEffect, useCallback } from "react";
import { RefreshCw, X, ChevronDown, ChevronUp, Loader2, CheckCircle } from "lucide-react";
import { checkUpdate, applyUpdate } from "../api/client";
import type { UpdateCheckResult } from "../api/client";

const CHECK_INTERVAL_MS = 10 * 60 * 1000; // 10 minutes

export function UpdateBanner() {
  const [status, setStatus] = useState<UpdateCheckResult | null>(null);
  const [showCommits, setShowCommits] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const check = useCallback(async () => {
    try {
      const result = await checkUpdate();
      setStatus(result);
      if (result.update_available) setDismissed(false);
    } catch {
      // silently ignore — backend might be starting up
    }
  }, []);

  useEffect(() => {
    // Initial check after 30s (give backend time to start)
    const initial = setTimeout(check, 30_000);
    const interval = setInterval(check, CHECK_INTERVAL_MS);
    return () => { clearTimeout(initial); clearInterval(interval); };
  }, [check]);

  const handleApply = async () => {
    setApplying(true);
    try {
      const result = await applyUpdate();
      if (result.ok) {
        setApplied(true);
        // Backend will restart — reload the page after 3s
        setTimeout(() => window.location.reload(), 3000);
      } else {
        alert(`Error al actualizar: ${result.error}`);
        setApplying(false);
      }
    } catch (e) {
      alert(`Error: ${e}`);
      setApplying(false);
    }
  };

  if (!status?.update_available || dismissed) return null;

  if (applied) {
    return (
      <div className="fixed bottom-4 right-4 z-50 flex items-center gap-2 bg-emerald-600 text-white text-sm px-4 py-2.5 rounded-xl shadow-lg">
        <CheckCircle size={16} />
        <span>¡Actualizado! Recargando…</span>
      </div>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm w-full bg-white dark:bg-zinc-900 border border-emerald-500 rounded-xl shadow-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 bg-emerald-50 dark:bg-emerald-950/40 border-b border-emerald-200 dark:border-emerald-800">
        <RefreshCw size={15} className="text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
        <span className="text-sm font-semibold text-emerald-700 dark:text-emerald-300 flex-1">
          Actualización disponible
        </span>
        <button
          onClick={() => setDismissed(true)}
          className="text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-300 transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* Commits */}
      <div className="px-4 py-2">
        <p className="text-xs text-gray-500 dark:text-zinc-400 mb-1">
          {status.commits?.length ?? 0} cambio{(status.commits?.length ?? 0) !== 1 ? "s" : ""} nuevo{(status.commits?.length ?? 0) !== 1 ? "s" : ""}
          {" "}· <span className="font-mono">{status.local_commit}</span> → <span className="font-mono">{status.remote_commit}</span>
        </p>

        {(status.commits?.length ?? 0) > 0 && (
          <>
            <button
              onClick={() => setShowCommits(v => !v)}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300 transition-colors mb-1"
            >
              {showCommits ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {showCommits ? "Ocultar cambios" : "Ver cambios"}
            </button>
            {showCommits && (
              <ul className="text-xs font-mono text-gray-600 dark:text-zinc-400 space-y-0.5 mb-2 max-h-32 overflow-y-auto">
                {status.commits!.map((c, i) => (
                  <li key={i} className="truncate">• {c}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 px-4 pb-3">
        <button
          onClick={() => setDismissed(true)}
          className="flex-1 py-1.5 text-xs border border-gray-300 dark:border-zinc-600 text-gray-600 dark:text-zinc-400 rounded-lg hover:bg-gray-50 dark:hover:bg-zinc-800 transition-colors"
        >
          Ahora no
        </button>
        <button
          onClick={handleApply}
          disabled={applying}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-xs bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white rounded-lg transition-colors font-medium"
        >
          {applying ? (
            <><Loader2 size={12} className="animate-spin" /> Actualizando…</>
          ) : (
            <><RefreshCw size={12} /> Actualizar ahora</>
          )}
        </button>
      </div>
    </div>
  );
}
