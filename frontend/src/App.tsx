import { useEffect, useRef, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatWindow } from "./components/ChatWindow";
import { SettingsPanel } from "./components/SettingsPanel";
import { LoginScreen } from "./components/LoginScreen";
import { checkAuth } from "./api/client";

type AuthState = "checking" | "ok" | "required" | "offline";

const RETRY_INTERVAL_MS = 3000;
const MAX_RETRIES = 10; // ~30s before giving up and showing offline message

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [authState, setAuthState]       = useState<AuthState>("checking");
  const [retryCount, setRetryCount]     = useState(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const verify = async (attempt = 0) => {
    const result = await checkAuth();
    if (result === "ok") {
      setAuthState("ok");
    } else if (result === "auth_required") {
      setAuthState("required");
    } else {
      // Backend offline — retry automatically up to MAX_RETRIES
      if (attempt < MAX_RETRIES) {
        setRetryCount(attempt + 1);
        setAuthState("checking");
        retryTimer.current = setTimeout(() => verify(attempt + 1), RETRY_INTERVAL_MS);
      } else {
        setAuthState("offline");
      }
    }
  };

  useEffect(() => {
    verify(0);
    return () => {
      if (retryTimer.current) clearTimeout(retryTimer.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (authState === "checking") {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-zinc-950">
        <div className="flex flex-col items-center gap-3 text-gray-400 dark:text-zinc-500">
          <div className="w-10 h-10 rounded-xl bg-emerald-600 flex items-center justify-center text-xl animate-pulse">
            🔨
          </div>
          <span className="text-sm">Conectando…</span>
          {retryCount > 0 && (
            <span className="text-xs text-zinc-500">Reintento {retryCount}/{MAX_RETRIES}</span>
          )}
        </div>
      </div>
    );
  }

  if (authState === "offline") {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-zinc-950">
        <div className="flex flex-col items-center gap-4 text-gray-400 dark:text-zinc-500 max-w-sm text-center">
          <div className="w-10 h-10 rounded-xl bg-red-600 flex items-center justify-center text-xl">
            🔨
          </div>
          <div>
            <p className="text-sm font-medium text-zinc-300 mb-1">Backend no disponible</p>
            <p className="text-xs text-zinc-500">
              Asegúrate de que el servidor está arrancado en{" "}
              <code className="font-mono text-zinc-400">localhost:8000</code>
            </p>
          </div>
          <button
            onClick={() => { setRetryCount(0); setAuthState("checking"); verify(0); }}
            className="px-4 py-2 text-sm bg-emerald-700 hover:bg-emerald-600 text-white rounded-sm transition-colors"
          >
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  if (authState === "required") {
    return <LoginScreen onSuccess={() => setAuthState("ok")} />;
  }

  return (
    <div className="flex h-screen bg-white dark:bg-zinc-950 overflow-hidden">
      <Sidebar onSettings={() => setSettingsOpen(true)} />
      <main className="flex-1 flex flex-col min-w-0">
        <ChatWindow />
      </main>
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
