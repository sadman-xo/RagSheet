import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { PageHeader } from "@/components/ui";
import { cn } from "@/lib/cn";
import UsersTab from "./UsersTab";
import AuditTab from "./AuditTab";
import SystemTab from "./SystemTab";
import RolesTab from "./RolesTab";
import AiQualityTab from "./AiQualityTab";

const TABS = [
  { path: "users", label: "Users" },
  { path: "audit", label: "Audit log" },
  { path: "roles", label: "Role matrix" },
  { path: "system", label: "System" },
  { path: "ai-quality", label: "AI quality" },
];

export default function AdminPage() {
  return (
    <div className="pt-4">
      <PageHeader title="Administration" subtitle="Users, audit, system health, and AI quality" />
      <div className="mb-4 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <NavLink key={t.path} to={`/admin/${t.path}`} data-testid={`admin-tab-${t.path}`}
            className={({ isActive }) => cn("-mb-px border-b-2 px-3 py-2 text-sm font-medium", isActive ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
            {t.label}
          </NavLink>
        ))}
      </div>
      <Routes>
        <Route index element={<Navigate to="users" replace />} />
        <Route path="users" element={<UsersTab />} />
        <Route path="audit" element={<AuditTab />} />
        <Route path="roles" element={<RolesTab />} />
        <Route path="system" element={<SystemTab />} />
        <Route path="ai-quality" element={<AiQualityTab />} />
      </Routes>
    </div>
  );
}
