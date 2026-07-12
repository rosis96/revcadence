import { useState } from "react";
import { HashRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { useApi } from "./components";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Pipeline from "./pages/Pipeline";
import Companies from "./pages/Companies";
import CompanyDetail from "./pages/CompanyDetail";
import Contacts from "./pages/Contacts";
import Enrichment from "./pages/Enrichment";
import EnrichLists from "./pages/EnrichLists";
import EnrichListDetail from "./pages/EnrichListDetail";
import EnrichConfigPage from "./pages/EnrichConfig";
import Blueprints from "./pages/Blueprints";
import BlueprintDetail from "./pages/BlueprintDetail";
import ActivityPage from "./pages/Activity";
import ReplyInbox from "./pages/ReplyInbox";
import ReplyWorkspaces from "./pages/ReplyWorkspaces";
import InboundVisitors from "./pages/InboundVisitors";
import EnrichDatabase from "./pages/EnrichDatabase";
import Jobs from "./pages/Jobs";
import Settings from "./pages/Settings";
import Admin from "./pages/Admin";

// MODES: the four sections. Pick a mode → the sidebar shows ONLY that section.
// Master Dashboard + System are always present. Each section is self-contained.
const MODES = {
  outbound: {
    label: "Outbound", icon: "✦",
    nav: [
      ["/enrichment", "Lists", "▦"],
      ["/enrichment/database", "Database", "▤"],
      ["/enrichment/profile", "Client Profile", "◐"],
      ["/enrichment/icp", "ICP / Non-ICP", "◎"],
      ["/enrichment/formats", "Formats", "≡"],
      ["/enrichment/rules", "Rules", "✓"],
      ["/blueprints", "Blueprints", "▧"],
    ],
  },
  reply: {
    label: "Reply Management", icon: "✉",
    nav: [
      ["/reply", "Inbox", "✉"],
      ["/reply/workspaces", "Workspaces", "⚑"],
    ],
  },
  inbound: {
    label: "Inbound (Visitors)", icon: "◍",
    nav: [
      ["/inbound", "Website Visitors", "◍"],
    ],
  },
  crm: {
    label: "CRM", icon: "☰",
    nav: [
      ["/pipeline", "Pipeline", "☰"],
      ["/companies", "Companies", "◫"],
      ["/contacts", "Contacts", "◔"],
      ["/activity", "Activity", "↺"],
    ],
  },
};
const COMMON_NAV = [["/", "Master Dashboard", "▦"]];
const SYSTEM_NAV = [["/jobs", "Jobs", "⚙"], ["/settings", "Settings", "⚒"]];
const NAV = [...COMMON_NAV, ...Object.values(MODES).flatMap((m) => m.nav), ...SYSTEM_NAV];

function Sidebar() {
  const { me, logout, workspaceId, setWorkspaceId } = useAuth();
  const [mode, setModeRaw] = useState(localStorage.getItem("rc_mode") || "outbound");
  const nav = useNavigate();
  const setMode = (m) => {
    localStorage.setItem("rc_mode", m);
    setModeRaw(m);
    nav(MODES[m].nav[0][0]);   // land on the mode's first screen
  };
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
      {/* Mode switcher — same clean dropdown pattern as the workspace switcher */}
      <div className="ws-switch">
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          {Object.entries(MODES).map(([key, m]) => (
            <option key={key} value={key}>{m.icon}  {m.label}</option>
          ))}
        </select>
      </div>
      <nav className="nav">
        {COMMON_NAV.map(([to, label, icon]) => (
          <NavLink key={to} to={to} end><span className="icon">{icon}</span>{label}</NavLink>
        ))}
        <div className="group">{MODES[mode].label}</div>
        {MODES[mode].nav.map(([to, label, icon]) => (
          <NavLink key={to} to={to} end={to.split("/").length <= 2}>
            <span className="icon">{icon}</span>{label}
          </NavLink>
        ))}
        <div className="group">System</div>
        {SYSTEM_NAV.map(([to, label, icon]) => (
          <NavLink key={to} to={to}><span className="icon">{icon}</span>{label}</NavLink>
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
        <Route path="/enrichment" element={<EnrichLists />} />
        <Route path="/enrichment/lists/:id" element={<EnrichListDetail />} />
        <Route path="/enrichment/database" element={<EnrichDatabase />} />
        <Route path="/enrichment/profile" element={<EnrichConfigPage tab="profile" />} />
        <Route path="/enrichment/icp" element={<EnrichConfigPage tab="icp" />} />
        <Route path="/enrichment/formats" element={<EnrichConfigPage tab="formats" />} />
        <Route path="/enrichment/rules" element={<EnrichConfigPage tab="rules" />} />
        <Route path="/enrichment/companies" element={<Enrichment />} />
        <Route path="/reply" element={<ReplyInbox />} />
        <Route path="/reply/workspaces" element={<ReplyWorkspaces />} />
        <Route path="/inbound" element={<InboundVisitors />} />
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
