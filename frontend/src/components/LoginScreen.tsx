import { useState, useRef, useEffect } from "react";
import { confirmPasswordReset, login, requestPasswordReset, verifyTotp, setJwt, setStoredUser } from "../api/client";

interface LoginScreenProps {
  onSuccess: () => void;
  resetToken?: string | null;
  onResetDone?: () => void;
}

export function LoginScreen({ onSuccess, resetToken, onResetDone }: LoginScreenProps) {
  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError]       = useState("");
  const [info, setInfo]         = useState("");
  const [loading, setLoading]   = useState(false);
  const [forgotMode, setForgotMode] = useState(false);
  const [resetPassword, setResetPassword] = useState("");
  const [resetPassword2, setResetPassword2] = useState("");

  // TOTP challenge state
  const [totpRequired, setTotpRequired] = useState(false);
  const [tempToken, setTempToken]       = useState("");
  const [totpCode, setTotpCode]         = useState("");
  const totpInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (totpRequired) totpInputRef.current?.focus();
  }, [totpRequired]);

  useEffect(() => {
    setError("");
    setInfo("");
  }, [forgotMode, resetToken]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;

    setLoading(true);
    setError("");
    setInfo("");

    try {
      const result = await login(email.trim(), password, remember);
      if (result.totp_required && result.temp_token) {
        setTempToken(result.temp_token);
        setTotpRequired(true);
      } else if (result.token && result.user) {
        setJwt(result.token, remember);
        setStoredUser(result.user);
        onSuccess();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error de autenticación";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleTotpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const code = totpCode.replace(/\s/g, "");
    if (code.length !== 6) return;

    setLoading(true);
    setError("");
    setInfo("");

    try {
      const result = await verifyTotp(tempToken, code);
      setJwt(result.token, remember);
      setStoredUser(result.user);
      onSuccess();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Código incorrecto";
      setError(msg);
      setTotpCode("");
      totpInputRef.current?.focus();
    } finally {
      setLoading(false);
    }
  };

  const handleForgotSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const result = await requestPasswordReset(email.trim(), window.location.origin);
      setInfo(result.message);
      setForgotMode(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "No se pudo enviar el correo";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleResetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetToken) return;
    if (resetPassword.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres");
      return;
    }
    if (resetPassword !== resetPassword2) {
      setError("Las contraseñas no coinciden");
      return;
    }
    setLoading(true);
    setError("");
    setInfo("");
    try {
      const result = await confirmPasswordReset(resetToken, resetPassword);
      setInfo(result.message);
      setResetPassword("");
      setResetPassword2("");
      onResetDone?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "No se pudo restablecer la contraseña";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-zinc-950 px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8 gap-3">
          <div className="w-14 h-14 rounded-2xl bg-emerald-600 flex items-center justify-center text-2xl shadow-lg">
            🔨
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-zinc-100">LocalForge</h1>
          <p className="text-sm text-gray-500 dark:text-zinc-400 text-center">
            {totpRequired ? "Verificación en dos pasos" : "Inicia sesión para continuar"}
          </p>
        </div>

        {/* Reset password step */}
        {resetToken ? (
          <form
            onSubmit={handleResetSubmit}
            className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-gray-200 dark:border-zinc-800 p-6 flex flex-col gap-4"
          >
            <p className="text-sm text-gray-600 dark:text-zinc-400 text-center">
              Elige tu nueva contraseña.
            </p>

            <input
              type="password"
              value={resetPassword}
              onChange={e => setResetPassword(e.target.value)}
              placeholder="Nueva contraseña"
              autoComplete="new-password"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
            />

            <input
              type="password"
              value={resetPassword2}
              onChange={e => setResetPassword2(e.target.value)}
              placeholder="Repite la contraseña"
              autoComplete="new-password"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
            />

            {error && (
              <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {info && (
              <p className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-lg px-3 py-2">
                {info}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !resetPassword || !resetPassword2}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors mt-1"
            >
              {loading ? "Guardando…" : "Restablecer contraseña"}
            </button>
          </form>
        ) : totpRequired ? (
          <form
            onSubmit={handleTotpSubmit}
            className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-gray-200 dark:border-zinc-800 p-6 flex flex-col gap-4"
          >
            <p className="text-sm text-gray-600 dark:text-zinc-400 text-center">
              Introduce el código de 6 dígitos de tu aplicación autenticadora.
            </p>

            <input
              ref={totpInputRef}
              type="text"
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              value={totpCode}
              onChange={e => setTotpCode(e.target.value.replace(/\D/g, ""))}
              placeholder="000000"
              autoComplete="one-time-code"
              className="w-full px-3 py-3 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-2xl text-center font-mono tracking-widest focus:outline-none focus:border-emerald-500 transition-colors"
            />

            {error && (
              <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {info && (
              <p className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-lg px-3 py-2">
                {info}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || totpCode.length !== 6}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors mt-1"
            >
              {loading ? "Verificando…" : "Verificar"}
            </button>

            <button
              type="button"
              onClick={() => { setTotpRequired(false); setTotpCode(""); setError(""); }}
              className="text-sm text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300 text-center transition-colors"
            >
              ← Volver al inicio de sesión
            </button>
          </form>
        ) : forgotMode ? (
          <form
            onSubmit={handleForgotSubmit}
            className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-gray-200 dark:border-zinc-800 p-6 flex flex-col gap-4"
          >
            <p className="text-sm text-gray-600 dark:text-zinc-400 text-center">
              Te enviaremos un enlace para restablecer tu contraseña.
            </p>

            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="tu@email.com"
              autoFocus
              autoComplete="email"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
            />

            {error && (
              <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {info && (
              <p className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-lg px-3 py-2">
                {info}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !email.trim()}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors mt-1"
            >
              {loading ? "Enviando…" : "Enviar enlace"}
            </button>

            <button
              type="button"
              onClick={() => setForgotMode(false)}
              className="text-sm text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300 text-center transition-colors"
            >
              ← Volver al inicio de sesión
            </button>
          </form>
        ) : (
          /* Password step */
          <form
            onSubmit={handleSubmit}
            className="bg-white dark:bg-zinc-900 rounded-2xl shadow-sm border border-gray-200 dark:border-zinc-800 p-6 flex flex-col gap-4"
          >
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-zinc-300 mb-1.5">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="tu@email.com"
                autoFocus
                autoComplete="email"
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-zinc-300 mb-1.5">
                Contraseña
              </label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-gray-900 dark:text-zinc-100 text-sm focus:outline-none focus:border-emerald-500 transition-colors"
              />
            </div>

            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={e => setRemember(e.target.checked)}
                className="w-4 h-4 rounded accent-emerald-600"
              />
              <span className="text-sm text-gray-600 dark:text-zinc-400">
                Recordarme 30 días
              </span>
            </label>

            {error && (
              <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {info && (
              <p className="text-sm text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-lg px-3 py-2">
                {info}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !email.trim() || !password}
              className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors mt-1"
            >
              {loading ? "Iniciando sesión…" : "Entrar"}
            </button>

            <button
              type="button"
              onClick={() => setForgotMode(true)}
              className="text-sm text-gray-500 dark:text-zinc-500 hover:text-gray-700 dark:hover:text-zinc-300 text-center transition-colors"
            >
              He olvidado mi contraseña
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
