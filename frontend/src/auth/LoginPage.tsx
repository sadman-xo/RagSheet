import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Lock } from "lucide-react";
import { errorMessage } from "@/api/client";
import { useAuth } from "./AuthProvider";
import { cn } from "@/lib/cn";
import { Wordmark } from "@/components/Logo";

const DEMO_PASSWORD = "Demo@2024";

const DEMO_USERS: { username: string; role: string; scope: string }[] = [
  { username: "admin", role: "Admin", scope: "All data + administration" },
  { username: "exec", role: "Executive", scope: "All data" },
  { username: "rm.namerica", role: "Regional Manager", scope: "North America" },
  { username: "rm.europe", role: "Regional Manager", scope: "Europe" },
  { username: "rm.asia", role: "Regional Manager", scope: "Asia" },
  { username: "rm.mideast", role: "Regional Manager", scope: "Middle East" },
  { username: "cm.electronics", role: "Category Manager", scope: "Electronics" },
  { username: "cm.clothing", role: "Category Manager", scope: "Clothing" },
  { username: "cm.home", role: "Category Manager", scope: "Home & Kitchen" },
  { username: "cm.books", role: "Category Manager", scope: "Books & Media" },
  { username: "cm.beauty", role: "Category Manager", scope: "Beauty & Health" },
  { username: "analyst", role: "Sales Analyst", scope: "All data, customer IDs masked" },
  { username: "ops", role: "Operations / Support", scope: "All data, no cost or profit" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await login(username.trim(), password);
      nav(me.landing, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const groups = DEMO_USERS.reduce<{ role: string; users: typeof DEMO_USERS }[]>((acc, u) => {
    const g = acc.find((x) => x.role === u.role);
    if (g) g.users.push(u);
    else acc.push({ role: u.role, users: [u] });
    return acc;
  }, []);

  return (
    <div className="flex min-h-screen bg-white">
      <aside className="sticky top-0 hidden h-screen w-[42%] max-w-[620px] shrink-0 flex-col justify-between overflow-hidden bg-slate-900 p-10 text-slate-300 lg:flex">
        <Wordmark />
        <HorizonArt />
        <div className="relative">
          <p className="max-w-md text-[28px] font-medium leading-[1.2] tracking-[-0.015em] text-white">
            Sales reporting for 10,000 orders across four regions and five categories.
          </p>
          <dl className="mt-8 grid gap-4 text-[13px]">
            {FACTS.map(([k, v], i) => (
              <div key={k} className="grid grid-cols-[28px_1fr] gap-x-2">
                <dt className="num pt-px text-xs text-slate-500">{String(i + 1).padStart(2, "0")}</dt>
                <dd>
                  <span className="font-medium text-slate-100">{k}.</span> <span className="text-slate-400">{v}</span>
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-8 text-xs text-slate-500">Data from January 2021 to December 2024.</p>
        </div>
      </aside>

      <main className="flex flex-1 justify-center px-6 py-12 lg:py-16">
        <div className="w-full max-w-[440px]">
          <Wordmark tone="dark" className="mb-10 lg:hidden" />
          <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-slate-900">Sign in</h1>
          <p className="mt-1 text-[13px] text-slate-500">Use your account, or select a demo account below.</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-medium text-slate-700">Username</span>
              <input
                className="input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                data-testid="login-username"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-medium text-slate-700">Password</span>
              <input
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                data-testid="login-password"
              />
            </label>
            {error && <p className="rounded-md border border-red-200 bg-red-50/60 px-3 py-2 text-[13px] text-red-800">{error}</p>}
            <button className="btn-primary h-10 w-full" disabled={busy || !username || !password} data-testid="login-submit">
              {busy ? "Signing in…" : "Sign in"}
            </button>
            <p className="flex items-center gap-1.5 text-xs text-slate-500">
              <Lock className="h-3 w-3" /> After 5 failed sign-ins, the account is locked for 5 minutes.
            </p>
          </form>

          <section className="mt-9">
            <div className="flex items-baseline justify-between border-b border-slate-200 pb-2">
              <h2 className="text-[13px] font-semibold text-slate-900">Demo accounts</h2>
              <span className="text-xs text-slate-500">
                Password <code className="num rounded bg-slate-100 px-1 py-px text-slate-700">{DEMO_PASSWORD}</code>
              </span>
            </div>
            <div className="divide-y divide-slate-100">
              {groups.map((g) => (
                <div key={g.role} className="grid grid-cols-[120px_1fr] gap-3 py-1.5">
                  <div className="pt-1 text-xs text-slate-500">{g.role}</div>
                  <div className="space-y-px">
                    {g.users.map((u) => (
                      <button
                        key={u.username}
                        type="button"
                        onClick={() => {
                          setUsername(u.username);
                          setPassword(DEMO_PASSWORD);
                        }}
                        data-testid={`demo-${u.username}`}
                        className={cn(
                          "flex w-full items-center justify-between gap-3 rounded px-2 py-1 text-left transition",
                          username === u.username ? "bg-slate-900 text-white" : "hover:bg-slate-100",
                        )}
                      >
                        <span className="num text-[12.5px] font-medium">{u.username}</span>
                        <span className={cn("truncate text-xs", username === u.username ? "text-slate-300" : "text-slate-500")}>{u.scope}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

const FACTS: [string, string][] = [
  ["Role-based access", "Each role sees only its own rows and columns. The server enforces every rule."],
  ["Exact numbers", "Code calculates every figure. The assistant writes only the explanation."],
  ["Runs locally", "Docker Compose with a local language model. No paid API."],
];

/** Quiet background texture: stacked horizon lines, like a revenue curve seen from far away. */
function HorizonArt() {
  const lines = Array.from({ length: 9 }, (_, i) => {
    const y = 120 + i * 26;
    const a = 18 + i * 3;
    return `M0 ${y} C 120 ${y - a}, 200 ${y + a}, 320 ${y - a * 0.6} S 520 ${y - a * 1.4}, 640 ${y - a * 0.4}`;
  });
  return (
    <svg viewBox="0 0 640 400" className="pointer-events-none absolute inset-x-0 top-24 w-full opacity-60" aria-hidden fill="none">
      {lines.map((d, i) => (
        <path key={d} d={d} stroke={i === 4 ? "#eb6834" : "#42403b"} strokeWidth={i === 4 ? 1.5 : 1} />
      ))}
    </svg>
  );
}
