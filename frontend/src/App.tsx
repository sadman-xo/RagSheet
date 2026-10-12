import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import LoginPage from "@/auth/LoginPage";
import AppShell from "@/layout/AppShell";
import { Loading } from "@/components/ui";

const Overview = lazy(() => import("@/pages/Overview"));
const Trends = lazy(() => import("@/pages/Trends"));
const Geography = lazy(() => import("@/pages/Geography"));
const Products = lazy(() => import("@/pages/Products"));
const Profitability = lazy(() => import("@/pages/Profitability"));
const Customers = lazy(() => import("@/pages/Customers"));
const Operations = lazy(() => import("@/pages/Operations"));
const Compare = lazy(() => import("@/pages/Compare"));
const Explorer = lazy(() => import("@/pages/Explorer"));
const Orders = lazy(() => import("@/pages/Orders"));
const Assistant = lazy(() => import("@/pages/assistant/AssistantPage"));
const DataNotes = lazy(() => import("@/pages/DataNotes"));
const Admin = lazy(() => import("@/pages/admin/AdminPage"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading label="Starting…" className="h-screen" />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

function Page({ id, children }: { id: string; children: ReactNode }) {
  const { me } = useAuth();
  if (me && !me.pages.includes(id)) {
    return (
      <div className="mx-auto mt-20 max-w-md text-center">
        <h2 className="text-lg font-semibold">This page is not available for your role</h2>
        <p className="mt-2 text-sm text-slate-500">Your role ({me.user.role_label}) cannot open this page. Use “My access” to see what you can open.</p>
      </div>
    );
  }
  return <Suspense fallback={<Loading />}>{children}</Suspense>;
}

function Landing() {
  const { me } = useAuth();
  return <Navigate to={me?.landing ?? "/overview"} replace />;
}

export default function App() {
  const { me, loading } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={loading ? <Loading className="h-screen" /> : me ? <Navigate to={me.landing} replace /> : <LoginPage />} />
      <Route element={<RequireAuth><AppShell /></RequireAuth>}>
        <Route index element={<Landing />} />
        <Route path="overview" element={<Page id="overview"><Overview /></Page>} />
        <Route path="trends" element={<Page id="trends"><Trends /></Page>} />
        <Route path="geography" element={<Page id="geography"><Geography /></Page>} />
        <Route path="products" element={<Page id="products"><Products /></Page>} />
        <Route path="profitability" element={<Page id="profitability"><Profitability /></Page>} />
        <Route path="customers" element={<Page id="customers"><Customers /></Page>} />
        <Route path="operations" element={<Page id="operations"><Operations /></Page>} />
        <Route path="compare" element={<Page id="compare"><Compare /></Page>} />
        <Route path="explorer" element={<Page id="explorer"><Explorer /></Page>} />
        <Route path="orders" element={<Page id="orders"><Orders /></Page>} />
        <Route path="assistant" element={<Page id="assistant"><Assistant /></Page>} />
        <Route path="data-notes" element={<Page id="data-notes"><DataNotes /></Page>} />
        <Route path="admin/*" element={<Page id="admin"><Admin /></Page>} />
        <Route path="*" element={<Landing />} />
      </Route>
    </Routes>
  );
}
