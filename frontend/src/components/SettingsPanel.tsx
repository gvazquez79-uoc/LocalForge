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
} from "lucide-react";
import { getConfig, saveConfig } from "../api/client";
import type { LocalForgeConfig } from "../api/client";
import { getStoredTheme, setTheme } from "../store/theme";
import type { Theme } from "../store/theme";

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: SettingsPanelProps) {
  const [config, setConfig] = useState<LocalForgeConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setThemeState] = useState<Theme>(getStoredTheme);

  useEffect(() => {
    if (open) {
      setError(null);
      setSavedOk(false);
      getConfig()
        .then(setConfig)
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

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      await saveConfig({ tools: config.tools, agent: config.agent });
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 2500);
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
          </Section>

          {!config ? (
            <div className="text-gray-400 dark:text-zinc-500 text-sm py-10 text-center">
              {error ?? "Loading…"}
            </div>
          ) : (
            <>
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
