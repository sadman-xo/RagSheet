import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus } from "lucide-react";
import { errorMessage, get, patch, post } from "@/api/client";
import { Badge, Card, ErrorState, Loading, Modal } from "@/components/ui";
import { shortDate } from "@/lib/format";

interface User {
  id: number;
  username: string;
  display_name: string;
  role: string;
  role_label: string;
  region: string | null;
  category: string | null;
  is_active: boolean;
  is_synthetic: boolean;
  failed_logins: number;
  locked_until: string | null;
  created_at: string;
  last_login_at: string | null;
}

const ROLES = [
  ["admin", "Admin"], ["executive", "Executive"], ["regional_manager", "Regional Manager"],
  ["category_manager", "Category Manager"], ["analyst", "Sales Analyst"], ["operations", "Operations / Support"],
];
const REGIONS = ["Asia", "Europe", "Middle East", "North America"];
const CATEGORIES = ["Beauty & Health", "Books & Media", "Clothing", "Electronics", "Home & Kitchen"];

function UserForm({ user, onDone }: { user: User | null; onDone: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    username: user?.username ?? "", display_name: user?.display_name ?? "", role: user?.role ?? "executive",
    region: user?.region ?? "Asia", category: user?.category ?? "Electronics", password: "", is_active: user?.is_active ?? true,
  });
  const [err, setErr] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: async () => {
      const scope = { region: f.role === "regional_manager" ? f.region : null, category: f.role === "category_manager" ? f.category : null };
      if (user) return patch(`/admin/users/${user.id}`, { display_name: f.display_name, role: f.role, ...scope, is_active: f.is_active });
      return post("/admin/users", { username: f.username, display_name: f.display_name, role: f.role, ...scope, password: f.password });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); onDone(); },
    onError: (e) => setErr(errorMessage(e)),
  });
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      {!user && <input className="input" placeholder="username (lower case)" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />}
      <input className="input" placeholder="Display name" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} />
      <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
        {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
      {f.role === "regional_manager" && (
        <select className="input" value={f.region} onChange={(e) => setF({ ...f, region: e.target.value })}>{REGIONS.map((r) => <option key={r}>{r}</option>)}</select>
      )}
      {f.role === "category_manager" && (
        <select className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
      )}
      {!user && <input className="input" type="password" placeholder="Password (8+ characters, upper and lower case, a digit)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />}
      {user && (
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} /> Active</label>
      )}
      {user && <p className="text-xs text-slate-500">A change of role, scope, or status ends the user's open sessions.</p>}
      {err && <ErrorState message={err} className="min-h-0" />}
      <button className="btn-primary" disabled={m.isPending}>{user ? "Save" : "Create user"}</button>
    </form>
  );
}

export default function UsersTab() {
  const [synthetic, setSynthetic] = useState(false);
  const q = useQuery<{ users: User[] }>({ queryKey: ["admin-users", synthetic], queryFn: () => get(`/admin/users?include_synthetic=${synthetic}`) });
  const [edit, setEdit] = useState<User | null | "new">(null);
  const [resetMsg, setResetMsg] = useState<string | null>(null);
  async function reset(u: User) {
    if (!confirm(`Reset the password of ${u.username}? Their sessions end.`)) return;
    try {
      const r = await post<{ temporary_password: string }>(`/admin/users/${u.id}/reset-password`, {});
      setResetMsg(`Temporary password for ${u.username}: ${r.temporary_password}`);
    } catch (e) {
      setResetMsg(errorMessage(e));
    }
  }
  return (
    <Card
      title="Users"
      actions={
        <>
          <label className="mr-2 flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} /> load-test users</label>
          <button className="btn" onClick={() => setEdit("new")} data-testid="add-user"><Plus className="h-4 w-4" /> Add user</button>
        </>
      }
    >
      {resetMsg && <p className="mb-2 rounded-md border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm text-amber-800">{resetMsg}</p>}
      {q.isLoading ? <Loading /> : q.error ? <ErrorState message={errorMessage(q.error)} /> : (
        <div className="scrollbar-thin max-h-[600px] overflow-auto">
          <table className="w-full text-sm" data-testid="users-table">
            <thead>
              <tr>{["User", "Role", "Scope", "Status", "Last login", ""].map((h) => <th key={h} className="table-head">{h}</th>)}</tr>
            </thead>
            <tbody>
              {q.data?.users.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="table-cell"><div className="font-medium">{u.display_name}</div><div className="font-mono text-xs text-slate-500">{u.username}</div></td>
                  <td className="table-cell">{u.role_label}</td>
                  <td className="table-cell">{u.region ?? u.category ?? "All"}</td>
                  <td className="table-cell">
                    {u.is_active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}
                    {u.locked_until && new Date(u.locked_until) > new Date() && <Badge tone="red" className="ml-1">locked</Badge>}
                  </td>
                  <td className="table-cell text-slate-500">{u.last_login_at ? shortDate(u.last_login_at.slice(0, 10)) : "never"}</td>
                  <td className="table-cell text-right">
                    <button className="btn-ghost" onClick={() => setEdit(u)} aria-label="Edit"><Pencil className="h-3.5 w-3.5" /></button>
                    <button className="btn-ghost" onClick={() => reset(u)} aria-label="Reset password"><KeyRound className="h-3.5 w-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={edit !== null} onOpenChange={(v) => !v && setEdit(null)} title={edit === "new" ? "Add user" : `Edit ${edit?.username ?? ""}`}>
        {edit !== null && <UserForm user={edit === "new" ? null : edit} onDone={() => setEdit(null)} />}
      </Modal>
    </Card>
  );
}
