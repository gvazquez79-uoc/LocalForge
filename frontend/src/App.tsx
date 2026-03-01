import { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatWindow } from "./components/ChatWindow";
import { SettingsPanel } from "./components/SettingsPanel";
import { LoginScreen } from "./components/LoginScreen";
import { checkAuth, getApiKey } from "./api/client";

type AuthState = "checking" | "ok" | "required";

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [authState, setAuthState]       = useState<AuthState>("checking");

  useEffect(() => {
    // Verify stored key against server.
    // If server has no API_KEY configured (open/dev mode), checkAuth() returns true.
    const verify = async () => {
      // Attempt auth with whatever key is stored (empty = no key)
      const ok = await checkAuth();
      if (ok) {
        setAuthState("ok");
      } else if (!getApiKey()) {
        // Server requires auth but we have no key stored → show login
        setAuthState("required");
      } else {
        // Had a key but it's wrong (e.g. key changed on server) → show login
        setAuthState("required");
      }
    };
    verify();
  }, []);

  if (authState === "checking") {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-zinc-950">
        <div className="flex flex-col items-center gap-3 text-gray-400 dark:text-zinc-500">
          <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center text-xl animate-pulse">
            🔨
          </div>
          <span className="text-sm">Conectando…</span>
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
