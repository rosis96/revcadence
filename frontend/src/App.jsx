import { HashRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { useApi } from "./components";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Pipeline from "./pages/Pipeline";
import Companies from "./pages/Companies";
import CompanyDetail from "./pages/CompanyDetail";
import Contacts from "./pages/Contacts";
import Enrichment from "./pages/Enrichment";
import Blueprints from "./pages/Blueprints";
import BlueprintDetail from "./pages/BlueprintDetail";
import ActivityPage from "./pages/Activity";
import Jobs from "./pages/Jobs";
import Settings from "./pages/Settings";
import Admin from "./pages/Admin";

const NAV = [
  ["/", "Dashboard", "▦"],
  ["/pipeline", "Pipeline", "☰"],
  ["/companies", "Companies", "◫"],
  ["/contacts", "Contacts", "◔"],
  ["/enrichment", "Enrichment", "✦"],
  ["/blueprints", "Blueprints", "▤"],
  ["/activity", "Activity", "↺"],
  ["/jobs", "Jobs", "⚙"],
  ["/settings", "Settings", "⚒"],
];

function Sidebar() {
  const { me, logout, workspaceId, setWorkspaceId } = useAuth();
  return (
    <aside className="sidebar">
      <div className="logo">Rev<span>Cadence</span></div>
      {me.is_master ? (
        <div className="ws-switch">
          <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
            <option value="">All workspaces</option>
            {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
      ) : (
        <div className="ws-badge">◫ {me.workspaces[0]?.name || "Workspace"}</div>
      )}
      <nav className="nav">
        {NAV.map(([to, label, icon]) => (
          <NavLink key={to} to={to} end={to === "/"}>
            <span className="icon">{icon}</span>{label}
          </NavLink>
        ))}
        {me.is_master && <NavLink to="/admin"><span className="icon">⛭</span>Admin</NavLink>}
      </nav>
      <div className="foot">
        <div className="who">{me.user.name || me.user.email}<br />
          <span style={{ color: "#7b8499" }}>{me.role}</span></div>
        <button onClick={logout}>Sign out</button>
      </div>
    </aside>
  );
}

function Topbar() {
  const loc = useLocation();
  const { data: health } = useApi("/healthz", undefined, [loc.pathname]);
  const title = (NAV.find(([to]) => to === loc.pathname)?.[1]) ||
    (loc.pathname.startsWith("/admin") ? "Admin" :
     loc.pathname.startsWith("/companies") ? "Companies" :
     loc.pathname.startsWith("/blueprints") ? "Blueprints" : "RevCadence");
  const workerOk = health?.worker?.alive;
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="right">
        <span><span className={`dot ${workerOk ? "ok" : "bad"}`} /> worker {workerOk ? "online" : "offline"}</span>
        <span><span className={`dot ${health?.ok ? "ok" : "bad"}`} /> api</span>
      </div>
    </header>
  );
}

function Shell({ children }) {
  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <Topbar />
        <div className="content">{children}</div>
      </div>
    </div>
  );
}

function Protected() {
  const { me, loading } = useAuth();
  if (loading) return <div className="center" style={{ minHeight: "100vh" }}><div className="spinner" /></div>;
  if (!me) return <Login />;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/companies/:id" element={<CompanyDetail />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/enrichment" element={<Enrichment />} />
        <Route path="/blueprints" element={<Blueprints />} />
        <Route path="/blueprints/:id" element={<BlueprintDetail />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </Shell>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <HashRouter><Protected /></HashRouter>
    </AuthProvider>
  );
}
