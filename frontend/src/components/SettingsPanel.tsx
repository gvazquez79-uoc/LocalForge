import { useState, useEffect } from "react";
import {
  X,
  FolderOpen,
  Terminal,
  Globe,
  Bot,
  Plus,
  Trash2,
  Check,
  AlertCircle,
  Sun,
  Moon,
  Send,
  Cpu,
  Edit2,
  Star,
} from "lucide-react";
import {
  getConfig, saveConfig, restartTelegramBot,
  listDbModels, createDbModel, updateDbModel, deleteDbModel, setDefaultDbModel, testDbModel,
  listProviders, createProvider, updateProvider, deleteProvider,
} from "../api/client";
import type { LocalForgeConfig, DbModel, DbProvider } from "../api/client";
import { getStoredTheme, setTheme } from "../store/theme";
import type { Theme } from "../store/theme";
import { usePrefs } from "../store/prefs";
import { useChatStore } from "../store/chat";
import { ConfirmDialog } from "./ConfirmDialog";
import type { ConfirmDialogOptions } from "./ConfirmDialog";

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const [config, setConfig] = useState<LocalForgeConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [telegramStatus, setTelegramStatus] = useState<"idle" | "restarting" | "ok" | "error">("idle");
  const [tokenAlreadySet, setTokenAlreadySet] = useState(false);
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  // ── Models state ──────────────────────────────────────────────────────────
  const [dbModels, setDbModels] = useState<DbModel[]>([]);
  const [modelFormOpen, setModelFormOpen] = useState(false);
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [modelForm, setModelForm] = useState({ name: "", display_name: "", provider: "ollama", base_url: "" });
  const [overrideUrl, setOverrideUrl] = useState(false);  // show base_url input even when provider has URL
  const [modelSaving, setModelSaving] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; ok: boolean; msg: string } | null>(null);
  const { renderMarkdown, setRenderMarkdown, showToolCalls, setShowToolCalls } = usePrefs();
  const { models, loadModels } = useChatStore();

  // ── Confirm dialog state ──────────────────────────────────────────────────
  const [confirmDialog, setConfirmDialog] = useState<(ConfirmDialogOptions & { onConfirm: () => void }) | null>(null);

  const openConfirm = (opts: ConfirmDialogOptions, onConfirm: () => void) =>
    setConfirmDialog({ ...opts, onConfirm });
  const closeConfirm = () => setConfirmDialog(null);

  // ── Providers state ───────────────────────────────────────────────────────
  const [providers, setProviders] = useState<DbProvider[]>([]);
  const [providerFormOpen, setProviderFormOpen] = useState(false);
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState({ name: "", display_name: "", base_url: "", api_key_env: "" });
  const [providerSaving, setProviderSaving] = useState(false);
  const [providerError, setProviderError] = useState<string | null>(null);

  // Build base_url lookup from loaded providers
  const providerUrlMap: Record<string, string> = Object.fromEntries(
    providers.map(p => [p.name, p.base_url])
  );

  const openModelCreate = () => {
    setEditingModelId(null);
    const defaultProvider = providers[0]?.name ?? "ollama";
    setModelForm({ name: "", display_name: "", provider: defaultProvider, base_url: "" });
    setOverrideUrl(false);
    setModelError(null);
    setModelFormOpen(true);
  };

  const openModelEdit = (m: DbModel) => {
    setEditingModelId(m.id);
    const modelBaseUrl = m.base_url ?? "";
    const providerDefaultUrl = providerUrlMap[m.provider] ?? "";
    // Only show override if model has a URL that differs from its provider's URL
    const hasCustomUrl = !!modelBaseUrl && modelBaseUrl !== providerDefaultUrl;
    setModelForm({ name: m.name, display_name: m.display_name, provider: m.provider, base_url: hasCustomUrl ? modelBaseUrl : "" });
    setOverrideUrl(hasCustomUrl);
    setModelError(null);
    setModelFormOpen(true);
  };

  const closeModelForm = () => { setModelFormOpen(false); setEditingModelId(null); setOverrideUrl(false); setTestResult(null); };

  const handleTestModel = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const res = await testDbModel(id);
      setTestResult({ id, ok: res.ok, msg: res.ok ? (res.response ?? "OK") : (res.error ?? "Error") });
    } catch (e) {
      setTestResult({ id, ok: false, msg: String(e) });
    } finally {
      setTestingId(null);
    }
  };

  const handleModelProviderChange = (provider: string) => {
    // When provider changes, reset any URL override — the new provider's URL will be inherited
    setModelForm(f => ({ ...f, provider, base_url: "" }));
    setOverrideUrl(false);
  };

  // ── Provider handlers ────────────────────────────────────────────────────
  const openProviderCreate = () => {
    setEditingProviderId(null);
    setProviderForm({ name: "", display_name: "", base_url: "", api_key_env: "" });
    setProviderError(null);
    setProviderFormOpen(true);
  };

  const openProviderEdit = (p: DbProvider) => {
    setEditingProviderId(p.id);
    setProviderForm({ name: p.name, display_name: p.display_name, base_url: p.base_url, api_key_env: p.api_key_env });
    setProviderError(null);
    setProviderFormOpen(true);
  };

  const closeProviderForm = () => { setProviderFormOpen(false); setEditingProviderId(null); };

  const handleProviderSave = async () => {
    if (!providerForm.name.trim() || !providerForm.display_name.trim()) {
      setProviderError("Name and display name are required.");
      return;
    }
    setProviderSaving(true);
    setProviderError(null);
    try {
      if (editingProviderId) {
        const updated = await updateProvider(editingProviderId, {
          name: providerForm.name,
          display_name: providerForm.display_name,
          base_url: providerForm.base_url,
          api_key_env: providerForm.api_key_env,
        });
        setProviders(ps => ps.map(p => p.id === editingProviderId ? updated : p));
      } else {
        const created = await createProvider({
          name: providerForm.name,
          display_name: providerForm.display_name,
          base_url: providerForm.base_url,
          api_key_env: providerForm.api_key_env,
        });
        setProviders(ps => [...ps, created]);
      }
      closeProviderForm();
    } catch (e) {
      setProviderError(String(e));
    } finally {
      setProviderSaving(false);
    }
  };

  const handleProviderDelete = (id: string) => {
    const prov = providers.find(p => p.id === id);
    openConfirm(
      {
        title: "Delete provider",
        message: "This provider will be permanently removed. Models that use it may stop working.",
        detail: prov ? `${prov.display_name} (${prov.name})` : id,
        confirmLabel: "Delete",
        variant: "danger",
      },
      async () => {
        closeConfirm();
        await deleteProvider(id);
        setProviders(ps => ps.filter(p => p.id !== id));
      },
    );
  };

  const handleModelSave = async () => {
    if (!modelForm.name.trim() || !modelForm.display_name.trim()) {
      setModelError("Nombre técnico y nombre visible son obligatorios.");
      return;
    }
    setModelSaving(true);
    setModelError(null);
    // Only persist base_url if user explicitly overrode it; otherwise null = inherit from provider
    const effectiveBaseUrl = overrideUrl && modelForm.base_url ? modelForm.base_url : null;
    try {
      if (editingModelId) {
        const updated = await updateDbModel(editingModelId, {
          name: modelForm.name,
          display_name: modelForm.display_name,
          provider: modelForm.provider,
          base_url: effectiveBaseUrl,
        });
        setDbModels(ms => ms.map(m => m.id === editingModelId ? updated : m));
      } else {
        const created = await createDbModel({
          name: modelForm.name,
          display_name: modelForm.display_name,
          provider: modelForm.provider,
          base_url: effectiveBaseUrl ?? undefined,
          is_default: dbModels.length === 0,
        });
        setDbModels(ms => [...ms, created]);
      }
      closeModelForm();
      void loadModels(); // refresh ModelSelector dropdown
    } catch (e) {
      // Extract the "detail" field from FastAPI JSON error responses
      const raw = String(e);
      const m = raw.match(/"detail"\s*:\s*"([^"]+)"/);
      setModelError(m ? m[1] : raw.replace(/^Error:\s*/, ""));
    } finally {
      setModelSaving(false);
    }
  };

  const handleModelDelete = (id: string) => {
    const model = dbModels.find(m => m.id === id);
    openConfirm(
      {
        title: "Delete model",
        message: "This model will be permanently removed from the database.",
        detail: model ? `${model.display_name} · ${model.provider}` : id,
        confirmLabel: "Delete",
        variant: "danger",
      },
      async () => {
        closeConfirm();
        await deleteDbModel(id);
        setDbModels(ms => ms.filter(m => m.id !== id));
        void loadModels(); // refresh ModelSelector dropdown
      },
    );
  };

  const handleSetDefault = async (id: string) => {
    const updated = await setDefaultDbModel(id);
    setDbModels(ms => ms.map(m => ({ ...m, is_default: m.id === id })));
    if (updated && config) setConfig(c => c ? { ...c, default_model: updated.name } : c);
    void loadModels(); // refresh ModelSelector dropdown
  };

  useEffect(() => {
    if (open) {
      setError(null);
      setSavedOk(false);
      setTelegramStatus("idle");
      listProviders().then(setProviders).catch(() => {});
      listDbModels().then(setDbModels).catch(() => {});
      getConfig()
        .then((cfg) => {
          // If server masked the token with ***, show empty field so user knows to re-enter
          const masked = cfg.telegram.bot_token === "***";
          setTokenAlreadySet(masked);
          setConfig({
            ...cfg,
            telegram: { ...cfg.telegram, bot_token: masked ? "" : cfg.telegram.bot_token },
          });
        })
        .catch(() => setError("Failed to load config from backend."));
    }
  }, [open]);

  const handleThemeToggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };

  const updateFilesystem = (patch: Partial<LocalForgeConfig["tools"]["filesystem"]>) =>
    setConfig((c) =>
      c ? { ...c, tools: { ...c.tools, filesystem: { ...c.tools.filesystem, ...patch } } } : c
    );

  const updateTerminal = (patch: Partial<LocalForgeConfig["tools"]["terminal"]>) =>
    setConfig((c) =>
      c ? { ...c, tools: { ...c.tools, terminal: { ...c.tools.terminal, ...patch } } } : c
    );

  const updateWebSearch = (patch: Partial<LocalForgeConfig["tools"]["web_search"]>) =>
    setConfig((c) =>
      c ? { ...c, tools: { ...c.tools, web_search: { ...c.tools.web_search, ...patch } } } : c
    );

  const updateAgent = (patch: Partial<LocalForgeConfig["agent"]>) =>
    setConfig((c) => (c ? { ...c, agent: { ...c.agent, ...patch } } : c));

  const updateTelegram = (patch: Partial<LocalForgeConfig["telegram"]>) => {
    setTelegramStatus("idle");
    setConfig((c) =>
      c ? { ...c, telegram: { ...c.telegram, ...patch } } : c
    );
  };

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      await saveConfig({ tools: config.tools, agent: config.agent, telegram: config.telegram });
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 3000);

      // Auto-restart Telegram bot only when it is enabled (no point restarting a disabled bot)
      if (config.telegram.enabled) {
        setTelegramStatus("restarting");
        try {
          const result = await restartTelegramBot();
          setTelegramStatus(result.running ? "ok" : "idle");
        } catch {
          setTelegramStatus("error");
        }
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-40"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 h-full w-[420px] max-w-full bg-white dark:bg-zinc-900 border-l border-gray-200 dark:border-zinc-800 z-50 flex flex-col shadow-2xl transition-transform duration-300 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-zinc-800 flex-shrink-0">
          <h2 className="text-base font-semibold text-gray-900 dark:text-zinc-100">Settings</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:text-zinc-500 dark:hover:text-zinc-300 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
          {/* ── Appearance ── */}
          <Section icon={theme === "dark" ? <Moon size={15} /> : <Sun size={15} />} title="Appearance">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-gray-600 dark:text-zinc-300">Theme</span>
              <button
                onClick={handleThemeToggle}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-xs text-gray-700 dark:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-700 transition-colors"
              >
                {theme === "dark" ? (
                  <>
                    <Moon size={13} className="text-indigo-400" />
                    Dark
                  </>
                ) : (
                  <>
                    <Sun size={13} className="text-amber-500" />
                    Light
                  </>
                )}
              </button>
            </div>
            <Toggle
              label="Render markdown in messages"
              checked={renderMarkdown}
              onChange={setRenderMarkdown}
            />
            <Toggle
              label="Show tool steps (advanced mode)"
              checked={showToolCalls}
              onChange={setShowToolCalls}
            />
          </Section>

          {!config ? (
            <div className="text-gray-400 dark:text-zinc-500 text-sm py-10 text-center">
              {error ?? "Loading…"}
            </div>
          ) : (
            <>
              {/* ── Models ── */}
              <Section icon={<Cpu size={15} />} title="Models">
                <div className="space-y-2">
                  {dbModels.map((m) => (
                    <div key={m.id}>
                      <div className="flex items-start gap-2 bg-gray-100 dark:bg-zinc-800 rounded-lg px-3 py-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-gray-800 dark:text-zinc-200 truncate">{m.display_name}</span>
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 flex-shrink-0">{m.provider}</span>
                          </div>
                          <p className="text-[10px] text-gray-400 dark:text-zinc-500 font-mono truncate mt-0.5">{m.name}</p>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <button
                            title="Test connection"
                            onClick={() => handleTestModel(m.id)}
                            disabled={testingId === m.id}
                            className="p-1 rounded text-gray-400 hover:text-green-500 dark:text-zinc-500 dark:hover:text-green-400 transition-colors disabled:opacity-40"
                          >
                            {testingId === m.id
                              ? <span className="inline-block w-3 h-3 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                              : <Send size={12} />}
                          </button>
                          <button
                            title={m.is_default ? "Default model" : "Set as default"}
                            onClick={() => !m.is_default && handleSetDefault(m.id)}
                            className={`p-1 rounded transition-colors ${m.is_default ? "text-amber-500" : "text-gray-300 dark:text-zinc-600 hover:text-amber-400"}`}
                          >
                            <Star size={12} fill={m.is_default ? "currentColor" : "none"} />
                          </button>
                          <button
                            title="Edit"
                            onClick={() => openModelEdit(m)}
                            className="p-1 rounded text-gray-400 hover:text-indigo-500 dark:text-zinc-500 dark:hover:text-indigo-400 transition-colors"
                          >
                            <Edit2 size={12} />
                          </button>
                          <button
                            title="Delete"
                            onClick={() => handleModelDelete(m.id)}
                            className="p-1 rounded text-gray-400 hover:text-red-400 dark:text-zinc-500 transition-colors"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                      {testResult?.id === m.id && (
                        <p className={`text-[10px] mt-1 px-1 ${testResult.ok ? "text-green-500" : "text-red-500"}`}>
                          {testResult.ok ? "✓ " : "✗ "}{testResult.msg}
                        </p>
                      )}
                    </div>
                  ))}
                </div>

                {/* Add/Edit form */}
                {modelFormOpen ? (
                  <div className="border border-indigo-200 dark:border-indigo-800/50 rounded-lg p-3 space-y-2.5 bg-indigo-50/50 dark:bg-indigo-950/20">
                    <p className="text-xs font-medium text-indigo-700 dark:text-indigo-300">
                      {editingModelId ? "Edit model" : "Add model"}
                    </p>
                    <FieldInput label="Technical name (e.g. llama-3.3-70b-versatile)" value={modelForm.name} onChange={v => setModelForm(f => ({ ...f, name: v }))} placeholder="model-name" mono />
                    <FieldInput label="Display name" value={modelForm.display_name} onChange={v => setModelForm(f => ({ ...f, display_name: v }))} placeholder="Llama 3.3 70B (Groq)" />
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">Provider</label>
                      <select
                        value={modelForm.provider}
                        onChange={(e) => handleModelProviderChange(e.target.value)}
                        className="w-full bg-white border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-gray-800 dark:text-zinc-200 focus:outline-none focus:border-indigo-500"
                      >
                        {providers.map(p => (
                          <option key={p.name} value={p.name}>{p.display_name}</option>
                        ))}
                        {/* Allow typing a custom provider not yet in DB */}
                        {modelForm.provider && !providers.find(p => p.name === modelForm.provider) && (
                          <option value={modelForm.provider}>{modelForm.provider} (custom)</option>
                        )}
                      </select>
                    </div>
                    {/* Base URL — inherited from provider unless overridden */}
                    {(() => {
                      const providerUrl = providerUrlMap[modelForm.provider] ?? "";
                      if (providerUrl && !overrideUrl) {
                        return (
                          <div className="space-y-1">
                            <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">Base URL</label>
                            <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 dark:bg-zinc-900 border border-gray-200 dark:border-zinc-700 rounded-lg">
                              <span className="flex-1 text-[10px] font-mono text-gray-400 dark:text-zinc-500 truncate">{providerUrl}</span>
                              <span className="text-[9px] text-gray-400 dark:text-zinc-600 flex-shrink-0">del provider</span>
                              <button
                                type="button"
                                onClick={() => { setOverrideUrl(true); setModelForm(f => ({ ...f, base_url: providerUrl })); }}
                                className="text-[10px] text-indigo-500 hover:text-indigo-600 dark:text-indigo-400 flex-shrink-0 transition-colors"
                              >
                                Cambiar
                              </button>
                            </div>
                          </div>
                        );
                      }
                      return (
                        <div className="space-y-1">
                          <div className="flex items-center justify-between">
                            <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">Base URL</label>
                            {providerUrl && overrideUrl && (
                              <button
                                type="button"
                                onClick={() => { setOverrideUrl(false); setModelForm(f => ({ ...f, base_url: "" })); }}
                                className="text-[10px] text-gray-400 hover:text-gray-600 dark:text-zinc-500 transition-colors"
                              >
                                ← usar URL del provider
                              </button>
                            )}
                          </div>
                          <input
                            type="text"
                            value={modelForm.base_url}
                            onChange={(e) => setModelForm(f => ({ ...f, base_url: e.target.value }))}
                            placeholder={providerUrl || "https://api.example.com/v1"}
                            className="w-full bg-white border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-gray-800 dark:text-zinc-200 placeholder-gray-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500 font-mono"
                          />
                        </div>
                      );
                    })()}
                    {modelError && <p className="text-[10px] text-red-500">{modelError}</p>}
                    <div className="flex gap-2 pt-1">
                      <button onClick={handleModelSave} disabled={modelSaving} className="flex-1 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg transition-colors">
                        {modelSaving ? "Saving…" : "Save"}
                      </button>
                      <button onClick={closeModelForm} className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 dark:text-zinc-400 transition-colors">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={openModelCreate}
                    className="flex items-center gap-2 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 transition-colors"
                  >
                    <Plus size={13} />
                    Add model
                  </button>
                )}
              </Section>

              {/* ── Providers ── */}
              <Section icon={<Globe size={15} />} title="Providers">
                <div className="space-y-2">
                  {providers.map((p) => (
                    <div key={p.id} className="flex items-start gap-2 bg-gray-100 dark:bg-zinc-800 rounded-lg px-3 py-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-medium text-gray-800 dark:text-zinc-200">{p.display_name}</span>
                          <span className="text-[10px] font-mono text-gray-500 dark:text-zinc-400">{p.name}</span>
                          {p.is_builtin && (
                            <span className="text-[9px] px-1 rounded bg-gray-200 dark:bg-zinc-700 text-gray-500 dark:text-zinc-400">builtin</span>
                          )}
                        </div>
                        {p.base_url && (
                          <p className="text-[10px] text-gray-400 dark:text-zinc-500 font-mono truncate mt-0.5">{p.base_url}</p>
                        )}
                        {p.api_key_env && (
                          <p className="text-[10px] text-indigo-400 dark:text-indigo-500 mt-0.5">env: {p.api_key_env}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <button
                          title="Edit"
                          onClick={() => openProviderEdit(p)}
                          className="p-1 rounded text-gray-400 hover:text-indigo-500 dark:text-zinc-500 dark:hover:text-indigo-400 transition-colors"
                        >
                          <Edit2 size={12} />
                        </button>
                        {!p.is_builtin && (
                          <button
                            title="Delete"
                            onClick={() => handleProviderDelete(p.id)}
                            className="p-1 rounded text-gray-400 hover:text-red-400 dark:text-zinc-500 transition-colors"
                          >
                            <Trash2 size={12} />
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {providerFormOpen ? (
                  <div className="border border-indigo-200 dark:border-indigo-800/50 rounded-lg p-3 space-y-2.5 bg-indigo-50/50 dark:bg-indigo-950/20">
                    <p className="text-xs font-medium text-indigo-700 dark:text-indigo-300">
                      {editingProviderId ? "Edit provider" : "Add provider"}
                    </p>
                    <FieldInput label="Slug (e.g. myapi)" value={providerForm.name} onChange={v => setProviderForm(f => ({ ...f, name: v }))} placeholder="my-provider" mono />
                    <FieldInput label="Display name" value={providerForm.display_name} onChange={v => setProviderForm(f => ({ ...f, display_name: v }))} placeholder="My Provider" />
                    <FieldInput label="Base URL" value={providerForm.base_url} onChange={v => setProviderForm(f => ({ ...f, base_url: v }))} placeholder="https://api.example.com/v1" mono />
                    <FieldInput label="API key env var (optional)" value={providerForm.api_key_env} onChange={v => setProviderForm(f => ({ ...f, api_key_env: v }))} placeholder="MY_PROVIDER_API_KEY" mono />
                    {providerError && <p className="text-[10px] text-red-500">{providerError}</p>}
                    <div className="flex gap-2 pt-1">
                      <button onClick={handleProviderSave} disabled={providerSaving} className="flex-1 py-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg transition-colors">
                        {providerSaving ? "Saving…" : "Save"}
                      </button>
                      <button onClick={closeProviderForm} className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 dark:text-zinc-400 transition-colors">
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={openProviderCreate}
                    className="flex items-center gap-2 text-xs text-indigo-600 dark:text-indigo-400 hover:text-indigo-500 transition-colors"
                  >
                    <Plus size={13} />
                    Add provider
                  </button>
                )}
              </Section>

              {/* ── Filesystem ── */}
              <Section icon={<FolderOpen size={15} />} title="Filesystem">
                <Toggle
                  label="Enable filesystem tool"
                  checked={config.tools.filesystem.enabled}
                  onChange={(v) => updateFilesystem({ enabled: v })}
                />
                {config.tools.filesystem.enabled && (
                  <>
                    <PathList
                      label="Allowed paths"
                      paths={config.tools.filesystem.allowed_paths}
                      onChange={(paths) => updateFilesystem({ allowed_paths: paths })}
                    />
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">
                        Require confirmation for
                      </label>
                      {["write_file", "delete_file"].map((op) => (
                        <CheckRow
                          key={op}
                          label={op}
                          checked={config.tools.filesystem.require_confirmation_for.includes(op)}
                          onChange={(checked) => {
                            const list = config.tools.filesystem.require_confirmation_for;
                            updateFilesystem({
                              require_confirmation_for: checked
                                ? [...list, op]
                                : list.filter((x) => x !== op),
                            });
                          }}
                        />
                      ))}
                    </div>
                    <NumberField
                      label="Max file size (MB)"
                      value={config.tools.filesystem.max_file_size_mb}
                      min={1}
                      max={500}
                      onChange={(v) => updateFilesystem({ max_file_size_mb: v })}
                    />
                  </>
                )}
              </Section>

              {/* ── Terminal ── */}
              <Section icon={<Terminal size={15} />} title="Terminal">
                <Toggle
                  label="Enable terminal tool"
                  checked={config.tools.terminal.enabled}
                  onChange={(v) => updateTerminal({ enabled: v })}
                />
                {config.tools.terminal.enabled && (
                  <>
                    <Toggle
                      label="Require confirmation before every command"
                      checked={config.tools.terminal.require_confirmation}
                      onChange={(v) => updateTerminal({ require_confirmation: v })}
                    />
                    <NumberField
                      label="Command timeout (seconds)"
                      value={config.tools.terminal.timeout_seconds}
                      min={1}
                      max={300}
                      onChange={(v) => updateTerminal({ timeout_seconds: v })}
                    />
                    <PathList
                      label="Blocked command patterns"
                      placeholder="e.g. rm -rf /"
                      paths={config.tools.terminal.blocked_patterns}
                      onChange={(patterns) => updateTerminal({ blocked_patterns: patterns })}
                    />
                  </>
                )}
              </Section>

              {/* ── Web Search ── */}
              <Section icon={<Globe size={15} />} title="Web Search">
                <Toggle
                  label="Enable web search tool"
                  checked={config.tools.web_search.enabled}
                  onChange={(v) => updateWebSearch({ enabled: v })}
                />
                {config.tools.web_search.enabled && (
                  <NumberField
                    label="Max results per search"
                    value={config.tools.web_search.max_results}
                    min={1}
                    max={20}
                    onChange={(v) => updateWebSearch({ max_results: v })}
                  />
                )}
              </Section>

              {/* ── Agent ── */}
              <Section icon={<Bot size={15} />} title="Agent">
                <NumberField
                  label="Max iterations per message"
                  value={config.agent.max_iterations}
                  min={1}
                  max={100}
                  onChange={(v) => updateAgent({ max_iterations: v })}
                />
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">System prompt</label>
                  <textarea
                    value={config.agent.system_prompt}
                    onChange={(e) => updateAgent({ system_prompt: e.target.value })}
                    rows={5}
                    className="w-full bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-2 text-xs text-gray-800 dark:text-zinc-200 focus:outline-none focus:border-indigo-500 resize-y"
                  />
                </div>
              </Section>

              {/* ── Telegram ── */}
              <Section icon={<Send size={15} />} title="Telegram">
                <Toggle
                  label="Enable Telegram bot"
                  checked={config.telegram.enabled}
                  onChange={(v) => updateTelegram({ enabled: v })}
                />
                {telegramStatus === "restarting" && (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-50 border border-blue-200 dark:bg-blue-950/40 dark:border-blue-800/50">
                    <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                    <p className="text-[11px] text-blue-700 dark:text-blue-400">Restarting Telegram bot…</p>
                  </div>
                )}
                {telegramStatus === "ok" && (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 border border-green-200 dark:bg-green-950/40 dark:border-green-800/50">
                    <Check size={13} className="text-green-500 flex-shrink-0" />
                    <p className="text-[11px] text-green-700 dark:text-green-400">Telegram bot running — send /start to your bot</p>
                  </div>
                )}
                {telegramStatus === "error" && (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 dark:bg-red-950/40 dark:border-red-800/50">
                    <AlertCircle size={13} className="text-red-500 flex-shrink-0" />
                    <p className="text-[11px] text-red-700 dark:text-red-400">Bot failed to start — check token and backend logs</p>
                  </div>
                )}
                {config.telegram.enabled && (
                  <>
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">
                        Bot Token
                      </label>
                      <input
                        type="password"
                        value={config.telegram.bot_token}
                        onChange={(e) => updateTelegram({ bot_token: e.target.value })}
                        placeholder={tokenAlreadySet ? "Token already set — enter new one to change" : "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"}
                        className="w-full bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-2 text-xs text-gray-800 dark:text-zinc-200 placeholder-gray-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">
                        Allowed User IDs
                      </label>
                      <textarea
                        value={config.telegram.allowed_user_ids.join("\n")}
                        onChange={(e) => {
                          const ids = e.target.value
                            .split("\n")
                            .map((s) => parseInt(s.trim(), 10))
                            .filter((n) => !isNaN(n));
                          updateTelegram({ allowed_user_ids: ids });
                        }}
                        placeholder="Leave empty to allow any user&#10;123456789&#10;987654321"
                        rows={3}
                        className="w-full bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-2 text-xs text-gray-800 dark:text-zinc-200 placeholder-gray-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500 font-mono resize-y"
                      />
                      <p className="text-[10px] text-gray-400 dark:text-zinc-500">
                        Leave empty to allow any user. Get your ID from @userinfobot
                      </p>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">
                        Default Model (optional)
                      </label>
                      <select
                        value={config.telegram.default_model}
                        onChange={(e) => updateTelegram({ default_model: e.target.value })}
                        className="w-full bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-2 text-xs text-gray-800 dark:text-zinc-200 focus:outline-none focus:border-indigo-500 cursor-pointer"
                      >
                        <option value="">Use global default</option>
                        {models.map((m) => (
                          <option key={m.name} value={m.name} disabled={!m.available}>
                            {m.display_name}{!m.available ? " (no key)" : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  </>
                )}
              </Section>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 border-t border-gray-200 dark:border-zinc-800 px-5 py-4 flex items-center gap-3">
          {error && (
            <div className="flex items-center gap-1.5 text-xs text-red-500 dark:text-red-400 flex-1 truncate">
              <AlertCircle size={13} />
              <span className="truncate">{error}</span>
            </div>
          )}
          {savedOk && (
            <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400 flex-1">
              <Check size={13} />
              Saved!
            </div>
          )}
          {!error && !savedOk && <div className="flex-1" />}
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700 dark:text-zinc-400 dark:hover:text-zinc-200 transition-colors"
          >
            Close
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !config}
            className="px-4 py-2 text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Global confirm dialog (model/provider delete, etc.) */}
      <ConfirmDialog
        open={confirmDialog !== null}
        title={confirmDialog?.title ?? ""}
        message={confirmDialog?.message ?? ""}
        detail={confirmDialog?.detail}
        confirmLabel={confirmDialog?.confirmLabel}
        cancelLabel={confirmDialog?.cancelLabel}
        variant={confirmDialog?.variant}
        onConfirm={() => confirmDialog?.onConfirm()}
        onCancel={closeConfirm}
      />
    </>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-indigo-500 dark:text-indigo-400">{icon}</span>
        <h3 className="text-sm font-medium text-gray-800 dark:text-zinc-200">{title}</h3>
      </div>
      <div className="space-y-3 pl-1">{children}</div>
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer group">
      <span className="text-xs text-gray-600 group-hover:text-gray-900 dark:text-zinc-300 dark:group-hover:text-zinc-100 transition-colors">
        {label}
      </span>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors ${
          checked ? "bg-indigo-600" : "bg-gray-200 dark:bg-zinc-700"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform mt-0.5 ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}

function CheckRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-3.5 h-3.5 accent-indigo-500"
      />
      <span className="text-xs text-gray-600 dark:text-zinc-300">{label}</span>
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="text-xs text-gray-600 dark:text-zinc-300">{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-20 bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-2 py-1 text-xs text-gray-800 dark:text-zinc-200 text-right focus:outline-none focus:border-indigo-500"
      />
    </div>
  );
}

function PathList({
  label,
  paths,
  onChange,
  placeholder = "e.g. ~/Documents",
}: {
  label: string;
  paths: string[];
  onChange: (paths: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const trimmed = draft.trim();
    if (!trimmed || paths.includes(trimmed)) return;
    onChange([...paths, trimmed]);
    setDraft("");
  };

  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">{label}</label>
      <div className="space-y-1">
        {paths.map((p) => (
          <div key={p} className="flex items-center gap-2 bg-gray-100 dark:bg-zinc-800 rounded-lg px-3 py-1.5">
            <span className="flex-1 text-xs text-gray-700 dark:text-zinc-300 font-mono truncate">{p}</span>
            <button
              onClick={() => onChange(paths.filter((x) => x !== p))}
              className="text-gray-400 hover:text-red-400 dark:text-zinc-600 transition-colors flex-shrink-0"
            >
              <Trash2 size={12} />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          className="flex-1 bg-gray-100 border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-gray-800 dark:text-zinc-200 placeholder-gray-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500"
        />
        <button
          onClick={add}
          className="p-1.5 bg-gray-200 hover:bg-gray-300 dark:bg-zinc-700 dark:hover:bg-zinc-600 rounded-lg text-gray-600 dark:text-zinc-300 transition-colors"
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  );
}

function FieldInput({
  label,
  value,
  onChange,
  placeholder = "",
  mono = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-gray-500 dark:text-zinc-400">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full bg-white border border-gray-300 dark:bg-zinc-800 dark:border-zinc-700 rounded-lg px-3 py-1.5 text-xs text-gray-800 dark:text-zinc-200 placeholder-gray-400 dark:placeholder-zinc-600 focus:outline-none focus:border-indigo-500 ${mono ? "font-mono" : ""}`}
      />
    </div>
  );
}
