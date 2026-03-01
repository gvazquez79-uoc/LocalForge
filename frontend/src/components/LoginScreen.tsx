import { useState } from "react";
import { checkAuth, setApiKey } from "../api/client";

interface LoginScreenProps {
  onSuccess: () => void;
}

export function LoginScreen({ onSuccess }: LoginScreenProps) {
  const [key, setKey]         = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;

    setLoading(true);
    setError("");

    // Store the key temporarily and try the health check
    setApiKey(key.trim());
    const ok = await checkAuth();

    if (ok) {
      onSuccess();
    } else {
      setApiKey(""); // clear wrong key
      setError("Clave incorrecta. Comprueba el valor de API_KEY en tu servidor.");
    }
    setLoading(false);
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-zinc-950 px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8 gap-3">
          <div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center text-2xl shadow-lg">
            🔨
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-zinc-100">LocalForge</h1>
          <p className="text-sm text-gray-500 dark:text-zinc-400 text-center">
            Introduce tu clave de acceso para continuar
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-gray-200 dark:border-zinc-800 p-6 flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-zinc-300 mb-1.5">
              API Key
            </label>
            <input
              type="password"
              value={key}
              onChange={e => setKey(e.target.value)}
              placeholder="tu-clave-secreta"
              autoFocus
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-sm focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>

          {error && (
            <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !key.trim()}
            className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? "Verificando…" : "Entrar"}
          </button>
        </form>

        <p className="text-xs text-center text-gray-400 dark:text-zinc-600 mt-4">
          Configura <code className="font-mono">API_KEY</code> en el <code className="font-mono">.env</code> del servidor
        </p>
      </div>
    </div>
  );
}
