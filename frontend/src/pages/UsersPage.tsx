import { useEffect, useState } from "react";
import {
  listUsers, createUser, updateUser, deleteUser, generatePassword,
  getStoredUser,
  type User,
} from "../api/client";
import { UserPlus, Pencil, Trash2, RefreshCw, X, Check, Eye, EyeOff, ShieldCheck } from "lucide-react";

interface UsersPageProps {
  onBack: () => void;
}

interface UserForm {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  is_admin: boolean;
}

const emptyForm = (): UserForm => ({
  first_name: "",
  last_name: "",
  email: "",
  password: "",
  is_admin: false,
});

export function UsersPage({ onBack }: UsersPageProps) {
  const [users, setUsers]           = useState<User[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState("");
  const [editingId, setEditingId]   = useState<string | null>(null); // null = create
  const [showForm, setShowForm]     = useState(false);
  const [form, setForm]             = useState<UserForm>(emptyForm());
  const [showPwd, setShowPwd]       = useState(false);
  const [saving, setSaving]         = useState(false);
  const [formError, setFormError]   = useState("");
  const [generatedPwd, setGeneratedPwd] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const me = getStoredUser();

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al cargar usuarios");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm());
    setGeneratedPwd("");
    setFormError("");
    setShowPwd(false);
    setShowForm(true);
  };

  const openEdit = (u: User) => {
    setEditingId(u.id);
    setForm({
      first_name: u.first_name,
      last_name: u.last_name ?? "",
      email: u.email,
      password: "",
      is_admin: !!u.is_admin,
    });
    setGeneratedPwd("");
    setFormError("");
    setShowPwd(false);
    setShowForm(true);
  };

  const handleGenPwd = async () => {
    try {
      const pwd = await generatePassword();
      setForm(f => ({ ...f, password: pwd }));
      setGeneratedPwd(pwd);
      setShowPwd(true);
    } catch { /* ignore */ }
  };

  const handleSave = async () => {
    setFormError("");
    if (!form.first_name.trim()) { setFormError("El nombre es obligatorio"); return; }
    if (!form.email.trim()) { setFormError("El email es obligatorio"); return; }
    if (!editingId && !form.password) { setFormError("La contraseña es obligatoria (o autogenérala)"); return; }

    setSaving(true);
    try {
      if (editingId) {
        await updateUser(editingId, {
          first_name: form.first_name,
          last_name: form.last_name,
          email: form.email,
          password: form.password || undefined,
          is_admin: form.is_admin,
        });
      } else {
        await createUser({
          first_name: form.first_name,
          last_name: form.last_name,
          email: form.email,
          password: form.password,
          is_admin: form.is_admin,
        });
      }
      setShowForm(false);
      await load();
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteUser(id);
      setDeleteConfirm(null);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error al eliminar");
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-zinc-950">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 bg-white dark:bg-zinc-900 border-b border-gray-200 dark:border-zinc-800 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-zinc-200 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors"
            title="Volver"
          >
            <X size={18} />
          </button>
          <div>
            <h1 className="text-base font-semibold text-gray-900 dark:text-zinc-100">Gestión de usuarios</h1>
            <p className="text-xs text-gray-400 dark:text-zinc-500">{users.length} usuario{users.length !== 1 ? "s" : ""}</p>
          </div>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <UserPlus size={15} />
          Nuevo usuario
        </button>
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="mb-4 px-4 py-2.5 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12 text-zinc-400 text-sm">Cargando…</div>
        ) : (
          <div className="grid gap-3">
            {users.map(u => (
              <div
                key={u.id}
                className="flex items-center justify-between bg-white dark:bg-zinc-900 border border-gray-200 dark:border-zinc-800 rounded-xl px-5 py-4"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center text-emerald-700 dark:text-emerald-400 font-semibold text-sm shrink-0">
                    {u.first_name.charAt(0).toUpperCase()}{(u.last_name ?? "").charAt(0).toUpperCase()}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900 dark:text-zinc-100">
                        {u.first_name} {u.last_name}
                      </span>
                      {u.is_admin && (
                        <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 text-xs rounded-full">
                          <ShieldCheck size={11} />
                          Admin
                        </span>
                      )}
                      {u.id === me?.id && (
                        <span className="px-2 py-0.5 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 text-xs rounded-full">
                          Tú
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400 dark:text-zinc-500 mt-0.5">{u.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openEdit(u)}
                    className="p-2 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-zinc-200 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors"
                    title="Editar"
                  >
                    <Pencil size={15} />
                  </button>
                  {u.id !== me?.id && (
                    deleteConfirm === u.id ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(u.id)}
                          className="p-2 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
                          title="Confirmar eliminación"
                        >
                          <Check size={15} />
                        </button>
                        <button
                          onClick={() => setDeleteConfirm(null)}
                          className="p-2 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors"
                        >
                          <X size={15} />
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirm(u.id)}
                        className="p-2 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                        title="Eliminar"
                      >
                        <Trash2 size={15} />
                      </button>
                    )
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create/Edit modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm px-4">
          <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-gray-200 dark:border-zinc-800">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-zinc-800">
              <h2 className="text-base font-semibold text-gray-900 dark:text-zinc-100">
                {editingId ? "Editar usuario" : "Nuevo usuario"}
              </h2>
              <button
                onClick={() => setShowForm(false)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-6 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-zinc-400 mb-1.5">
                    Nombre <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={form.first_name}
                    onChange={e => setForm(f => ({ ...f, first_name: e.target.value }))}
                    placeholder="Ana"
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-sm text-gray-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500 transition-colors"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-zinc-400 mb-1.5">
                    Apellidos
                  </label>
                  <input
                    type="text"
                    value={form.last_name}
                    onChange={e => setForm(f => ({ ...f, last_name: e.target.value }))}
                    placeholder="García"
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-sm text-gray-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500 transition-colors"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-zinc-400 mb-1.5">
                  Email <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  value={form.email}
                  onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                  placeholder="ana@ejemplo.com"
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-sm text-gray-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500 transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-zinc-400 mb-1.5">
                  Contraseña {!editingId && <span className="text-red-500">*</span>}
                  {editingId && <span className="text-zinc-500 font-normal"> (dejar vacío para no cambiar)</span>}
                </label>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <input
                      type={showPwd ? "text" : "password"}
                      value={form.password}
                      onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                      placeholder={editingId ? "••••••••" : "Mínimo 8 caracteres"}
                      className="w-full px-3 py-2 pr-9 rounded-lg border border-gray-300 dark:border-zinc-700 bg-gray-50 dark:bg-zinc-800 text-sm text-gray-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500 transition-colors"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPwd(v => !v)}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-zinc-300"
                    >
                      {showPwd ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleGenPwd}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-gray-300 dark:border-zinc-700 text-xs text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800 transition-colors whitespace-nowrap"
                    title="Autogenerar contraseña fuerte"
                  >
                    <RefreshCw size={12} />
                    Generar
                  </button>
                </div>
                {generatedPwd && (
                  <p className="mt-1.5 text-xs text-emerald-600 dark:text-emerald-400 font-mono bg-emerald-50 dark:bg-emerald-950/30 px-2 py-1.5 rounded select-all">
                    {generatedPwd}
                  </p>
                )}
              </div>

              <label className="flex items-center gap-2.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.is_admin}
                  onChange={e => setForm(f => ({ ...f, is_admin: e.target.checked }))}
                  disabled={editingId === me?.id}
                  className="w-4 h-4 rounded accent-amber-500"
                />
                <span className="text-sm text-gray-700 dark:text-zinc-300 flex items-center gap-1.5">
                  <ShieldCheck size={14} className="text-amber-500" />
                  Administrador
                </span>
              </label>

              {formError && (
                <p className="text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
                  {formError}
                </p>
              )}
            </div>

            <div className="flex justify-end gap-2 px-6 pb-5">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 text-sm text-gray-600 dark:text-zinc-400 hover:bg-gray-100 dark:hover:bg-zinc-800 rounded-lg transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors"
              >
                {saving ? "Guardando…" : (editingId ? "Guardar cambios" : "Crear usuario")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
