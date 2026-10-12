import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Boxes, ChevronDown, ChevronsLeft, ChevronsRight, CircleDollarSign, Database, FileText, GitCompare,
  Globe2, KeyRound, LayoutDashboard, LogOut, MessageSquare, Search, Settings, ShieldCheck, Truck, TrendingUp, Users,
} from "lucide-react";
import { useAuth, useMe } from "@/auth/AuthProvider";
import { get, post, errorMessage } from "@/api/client";
import { useUi } from "@/state/ui";
import { Badge, Modal } from "@/components/ui";
import { cn } from "@/lib/cn";
import { ChatDrawer } from "@/pages/assistant/ChatDrawer";
import { LogoMark, Wordmark } from "@/components/Logo";

const ICONS: Record<string, typeof LayoutDashboard> = {
  overview: LayoutDashboard, trends: TrendingUp, geography: Globe2, products: Boxes, profitability: CircleDollarSign,
  customers: Users, operations: Truck, compare: GitCompare, explorer: Search, orders: FileText, assistant: MessageSquare,
  "data-notes": Database, admin: Settings,
};

export interface ChatStatus {
  state: "ready" | "downloading" | "loading" | "busy" | "basic" | "unavailable";
  label: string;
  progress?: number | null;
  queue?: number;
  model?: string;
}

export function useChatStatus() {
  return useQuery<ChatStatus>({
    queryKey: ["chat-status"],
    queryFn: async () => {
      try {
        return await get<ChatStatus>("/chat/status");
      } catch {
        return { state: "unavailable", label: "AI not available" };
      }
    },
    refetchInterval: (q) => (q.state.data?.state === "ready" ? 15_000 : 4_000),
  });
}

function MyAccess({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const me = useMe();
  const rows: [string, ReactNode][] = [
    ["Role", me.user.role_label],
    ["Rows", me.scope.label],
    ["Cost, profit, margin", me.scope.financial ? "Visible" : "Hidden for your role"],
    ["Customer ID", me.scope.pii === "raw" ? "Real ID" : "Pseudonym (C-…)"],
    ["Company totals", me.scope.company_totals ? "Yes" : "No (only your scope)"],
    ["Pages", me.navigation.map((n) => n.label).join(", ")],
    ["Features", me.capabilities.join(", ")],
  ];
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="My access">
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-t border-slate-100 first:border-t-0">
              <td className="w-44 py-2 pr-4 align-top text-slate-500">{k}</td>
              <td className="py-2">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-slate-500">The server enforces these rules for every page, export, and chat answer.</p>
    </Modal>
  );
}

function PasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Change password">
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await post("/auth/password", { current_password: cur, new_password: next });
            setMsg("Password changed. Other sessions are signed out.");
            setCur("");
            setNext("");
          } catch (err) {
            setMsg(errorMessage(err));
          }
        }}
      >
        <input className="input" type="password" placeholder="Current password" value={cur} onChange={(e) => setCur(e.target.value)} />
        <input className="input" type="password" placeholder="New password (8+ characters, upper and lower case, a digit)" value={next} onChange={(e) => setNext(e.target.value)} />
        {msg && <p className="text-sm text-slate-600">{msg}</p>}
        <button className="btn-primary" disabled={!cur || !next}>Change password</button>
      </form>
    </Modal>
  );
}

export default function AppShell() {
  const me = useMe();
  const { logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const { sidebarCollapsed, toggleSidebar, openChat } = useUi();
  const [accessOpen, setAccessOpen] = useState(false);
  const [pwOpen, setPwOpen] = useState(false);
  const scopeTone = me.scope.scope_key.startsWith("region") ? "green" : me.scope.scope_key.startsWith("category") ? "amber" : "blue";

  const groups = groupNav(me.navigation);
  const initials = me.user.display_name.split(" ").map((x) => x[0]).join("").slice(0, 2);

  return (
    <div className="flex h-full">
      <aside className={cn("flex shrink-0 flex-col bg-slate-900 text-slate-400 transition-all", sidebarCollapsed ? "w-14" : "w-14 lg:w-[220px]")}>
        <div className="flex h-14 items-center px-4">
          {sidebarCollapsed ? <LogoMark /> : <><LogoMark className="lg:hidden" /><Wordmark className="hidden lg:flex" /></>}
        </div>
        <nav className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-2" data-testid="sidebar">
          {groups.map((g) => (
            <div key={g.label} className="mt-4 first:mt-2">
              {!sidebarCollapsed && <div className="mb-1 hidden px-2.5 text-[11px] font-medium text-slate-500 lg:block">{g.label}</div>}
              <div className="space-y-px">
                {g.items.map((n) => {
                  const Icon = ICONS[n.id] ?? LayoutDashboard;
                  return (
                    <NavLink
                      key={n.id}
                      to={n.path + (["admin", "assistant", "data-notes", "orders"].includes(n.id) ? "" : keepFilters(loc.search))}
                      data-testid={`nav-${n.id}`}
                      className={({ isActive }) =>
                        cn(
                          "relative flex items-center gap-2.5 rounded px-2.5 py-[7px] text-[13px] transition",
                          isActive
                            ? "bg-white/[0.08] font-medium text-white before:absolute before:inset-y-1.5 before:-left-2 before:w-[3px] before:rounded-r before:bg-[#eb6834]"
                            : "hover:bg-white/[0.04] hover:text-slate-100",
                        )
                      }
                      title={n.label}
                    >
                      <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                      {!sidebarCollapsed && <span className="hidden lg:inline">{n.label}</span>}
                    </NavLink>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <button
          type="button"
          className="m-2 inline-flex items-center gap-2 rounded px-2.5 py-1.5 text-[13px] text-slate-500 transition hover:bg-white/[0.04] hover:text-slate-200"
          onClick={toggleSidebar}
          aria-label="Collapse sidebar"
        >
          {sidebarCollapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> <span className="hidden lg:inline">Collapse</span></>}
        </button>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* No overflow-hidden on the header: it clipped the user menu (the menu opens below the header). */}
        <header className="relative z-30 flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 lg:px-8">
          <div className="hidden min-w-0 flex-wrap items-center gap-1.5 overflow-hidden md:flex" data-testid="scope-badges">
            {me.scope.badges.map((b, i) => (
              <Badge key={b} tone={i === 0 ? scopeTone : b.includes("hidden") || b.includes("masked") ? "amber" : "slate"}>
                {i === 0 && <ShieldCheck className="h-3 w-3" />} {b}
              </Badge>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            {me.capabilities.includes("chat") && loc.pathname !== "/assistant" && (
              <button type="button" className="btn mr-1" onClick={() => openChat()} data-testid="open-chat">
                <MessageSquare className="h-3.5 w-3.5" /> <span className="hidden whitespace-nowrap sm:inline">Ask a question</span>
              </button>
            )}
            <button type="button" className="btn-ghost" onClick={() => setAccessOpen(true)} data-testid="my-access">
              <ShieldCheck className="h-3.5 w-3.5" /> <span className="hidden whitespace-nowrap sm:inline">My access</span>
            </button>
            <div className="mx-1 hidden h-6 w-px bg-slate-200 sm:block" />
            <div className="group relative">
              <button type="button" className="flex items-center gap-2.5 rounded-md px-1.5 py-1 hover:bg-slate-100" data-testid="user-menu">
                <span className="flex h-7 w-7 items-center justify-center rounded bg-slate-800 text-[11px] font-semibold text-white">
                  {initials}
                </span>
                <span className="hidden text-left leading-tight md:block">
                  <span className="block text-[13px] font-medium text-slate-900">{me.user.display_name}</span>
                  <span className="block text-[11.5px] text-slate-500">{me.user.role_label}</span>
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-slate-400" aria-hidden />
              </button>
              <div className="menu invisible absolute right-0 top-full w-48 opacity-0 transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
                <button type="button" className="menu-item" onClick={() => setPwOpen(true)}>
                  <KeyRound className="h-3.5 w-3.5" /> Change password
                </button>
                <button
                  type="button"
                  className="menu-item"
                  data-testid="logout"
                  onClick={async () => {
                    await logout();
                    nav("/login");
                  }}
                >
                  <LogOut className="h-3.5 w-3.5" /> Sign out
                </button>
              </div>
            </div>
          </div>
        </header>
        <main className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 pb-12 lg:px-8">
          <Outlet />
        </main>
      </div>
      <MyAccess open={accessOpen} onOpenChange={setAccessOpen} />
      <PasswordDialog open={pwOpen} onOpenChange={setPwOpen} />
      {me.capabilities.includes("chat") && <ChatDrawer />}
    </div>
  );
}

const NAV_GROUPS: { label: string; ids: string[] }[] = [
  { label: "Reports", ids: ["overview", "trends", "geography", "products", "profitability", "customers", "operations"] },
  { label: "Analysis", ids: ["compare", "explorer", "orders"] },
  { label: "Assistant and data", ids: ["assistant", "data-notes"] },
];

type NavItem = ReturnType<typeof useMe>["navigation"][number];

function groupNav(items: NavItem[]): { label: string; items: NavItem[] }[] {
  const out = NAV_GROUPS.map((g) => ({ label: g.label, items: items.filter((n) => g.ids.includes(n.id)) }));
  const rest = items.filter((n) => !NAV_GROUPS.some((g) => g.ids.includes(n.id)));
  if (rest.length) out.push({ label: "Administration", items: rest });
  return out.filter((g) => g.items.length);
}

function keepFilters(search: string): string {
  const sp = new URLSearchParams(search);
  const keep = new URLSearchParams();
  for (const k of ["period", "from", "to", "rev", "region", "country", "category", "sub", "product", "segment", "gender", "status", "ship", "pay", "disc"]) {
    const v = sp.get(k);
    if (v) keep.set(k, v);
  }
  const s = keep.toString();
  return s ? `?${s}` : "";
}
