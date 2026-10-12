import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { get } from "@/api/client";
import { Card, Loading } from "@/components/ui";

interface RoleRow {
  role: string;
  label: string;
  rows: string;
  financial: boolean;
  customer_id: string;
  company_totals: boolean;
  pages: string[];
  capabilities: string[];
  landing: string;
}

const PAGES = ["overview", "trends", "geography", "products", "profitability", "customers", "operations", "compare", "explorer", "orders", "assistant", "data-notes", "admin"];

function Yes({ v }: { v: boolean }) {
  return v ? <Check className="mx-auto h-4 w-4 text-emerald-600" /> : <X className="mx-auto h-4 w-4 text-red-500" />;
}

export default function RolesTab() {
  const q = useQuery<{ roles: RoleRow[] }>({ queryKey: ["roles"], queryFn: () => get("/admin/roles"), staleTime: Infinity });
  if (!q.data) return <Loading />;
  const roles = q.data.roles;
  const rows: [string, (r: RoleRow) => ReactNode][] = [
    ["Rows", (r) => r.rows],
    ["Cost, profit, margin", (r) => <Yes v={r.financial} />],
    ["Customer ID", (r) => r.customer_id],
    ["Company totals", (r) => <Yes v={r.company_totals} />],
    ["Landing page", (r) => r.landing],
    ...PAGES.map((p) => [`Page: ${p}`, (r: RoleRow) => <Yes v={r.pages.includes(p)} />] as [string, (r: RoleRow) => ReactNode]),
    ["CSV export", (r) => <Yes v={r.capabilities.includes("export")} />],
    ["AI chat", (r) => <Yes v={r.capabilities.includes("chat")} />],
  ];
  return (
    <Card title="Role matrix" subtitle="Read-only. The server enforces every rule.">
      <div className="overflow-auto">
        <table className="w-full text-sm" data-testid="roles-table">
          <thead>
            <tr>
              <th className="table-head">Access item</th>
              {roles.map((r) => <th key={r.role} className="table-head text-center">{r.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, f]) => (
              <tr key={label} className="border-t border-slate-100">
                <td className="table-cell font-medium">{label}</td>
                {roles.map((r) => <td key={r.role} className="table-cell text-center">{f(r)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
