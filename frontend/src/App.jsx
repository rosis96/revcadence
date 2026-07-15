import { useEffect, useRef, useState } from "react";
import { HashRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutGrid, ListChecks, Database, CircleUser, Target, AlignLeft, CheckCheck, FileText,
  Mail, Inbox, FlaskConical, Settings2, SlidersHorizontal, Flag, Globe, Rows3, Building2,
  Contact, Activity as ActivityIcon, Cog, Wrench, ShieldCheck, ChevronDown, MoreHorizontal,
  LogOut, Search, ClipboardList, Radar, Briefcase,
} from "lucide-react";
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
import ClientProfile from "./pages/ClientProfile";
import Clients from "./pages/Clients";
import ActivityPage from "./pages/Activity";
import ReplyDashboard from "./pages/ReplyDashboard";
import ReplyInbox from "./pages/ReplyInbox";
import ReplyProcessing from "./pages/ReplyProcessing";
import ReplyTest from "./pages/ReplyTest";
import ReplySettings from "./pages/ReplySettings";
import ReplySetup from "./pages/ReplySetup";
import ReplyWorkspaces from "./pages/ReplyWorkspaces";
import InboundVisitors from "./pages/InboundVisitors";
import EnrichDatabase from "./pages/EnrichDatabase";
import Jobs from "./pages/Jobs";
import Settings from "./pages/Settings";
import Admin from "./pages/Admin";
import Onboarding from "./pages/Onboarding";
import OnboardingForm from "./pages/OnboardingForm";

// MODES: the four sections. Pick a mode → the sidebar shows ONLY that section.
// Master Dashboard + System are always present. Each section is self-contained.
const I = 18;
const MODES = {
  outbound: {
    label: "Outbound",
    nav: [
      ["/enrichment", "Lists", ListChecks],
      ["/enrichment/database", "Database", Database],
      ["/enrichment/profile", "Client Profile", CircleUser],
      ["/enrichment/icp", "ICP / Non-ICP", Target],
      ["/enrichment/formats", "Formats", AlignLeft],
      ["/enrichment/rules", "Rules", CheckCheck],
    ],
  },
  reply: {
    label: "Reply Management",
    nav: [
      ["/reply", "Dashboard", LayoutGrid],
      ["/reply/inbox", "Inbox", Inbox],
      ["/reply/processing", "Processing", Radar],
      ["/reply/test", "Test Thread", FlaskConical],
      ["/reply/setup", "Setup", Settings2],
      ["/reply/settings", "Reply Settings", SlidersHorizontal],
      ["/reply/workspaces", "Extra Channels", Flag],
    ],
  },
  inbound: {
    label: "Inbound (Visitors)",
    nav: [["/inbound", "Website Visitors", Globe]],
  },
  crm: {
    label: "CRM",
    nav: [
      ["/pipeline", "Pipeline", Rows3],
      ["/blueprints", "Blueprints & Agreements", FileText],
      ["/clients", "Clients", Briefcase],
      ["/companies", "Companies", Building2],
      ["/contacts", "Contacts", Contact],
      ["/onboarding", "Onboarding", ClipboardList],
      ["/activity", "Activity", ActivityIcon],
    ],
  },
};
const MODE_ICON = { outbound: Mail, reply: Inbox, inbound: Globe, crm: Rows3 };
const COMMON_NAV = [["/", "Master Dashboard", LayoutGrid]];
const SYSTEM_NAV = [["/jobs", "Jobs", Cog], ["/settings", "Settings", Wrench]];
const NAV = [...COMMON_NAV, ...Object.values(MODES).flatMap((m) => m.nav), ...SYSTEM_NAV];
const NavIcon = ({ ic: Ic }) => <span className="icon"><Ic size={I} /></span>;

function Sidebar() {
  const { me, logout, workspaceId, setWorkspaceId } = useAuth();
  const [mode, setModeRaw] = useState(localStorage.getItem("rc_mode") || "outbound");
  const nav = useNavigate();
  const setMode = (m) => {
    localStorage.setItem("rc_mode", m);
    setModeRaw(m);
    nav(MODES[m].nav[0][0]);   // land on the mode's first screen
  };
  const [menu, setMenu] = useState(false);
  const initials = (me.user.name || me.user.email).slice(0, 2).toUpperCase();
  return (
    <aside className="sidebar">
      <div className="logo"><span className="mark">R</span>Rev<span>Cadence</span></div>
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
      <div className="ws-switch">
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          {Object.entries(MODES).map(([key, m]) => <option key={key} value={key}>{m.label}</option>)}
        </select>
      </div>
      <nav className="nav">
        {COMMON_NAV.map(([to, label, ic]) => (
          <NavLink key={to} to={to} end><NavIcon ic={ic} /><span>{label}</span></NavLink>
        ))}
        <div className="group">{MODES[mode].label}</div>
        {MODES[mode].nav.map(([to, label, ic]) => (
          <NavLink key={to} to={to} end={to.split("/").length <= 2}><NavIcon ic={ic} /><span>{label}</span></NavLink>
        ))}
        <div className="group">System</div>
        {SYSTEM_NAV.map(([to, label, ic]) => (
          <NavLink key={to} to={to}><NavIcon ic={ic} /><span>{label}</span></NavLink>
        ))}
        {me.is_master && <NavLink to="/admin"><NavIcon ic={ShieldCheck} /><span>Admin</span></NavLink>}
      </nav>
      <div className="foot">
        {menu && (
          <div className="profile-menu">
            <button onClick={logout}><LogOut size={15} /> Sign out</button>
          </div>
        )}
        <div className="profile" onClick={() => setMenu((v) => !v)}>
          <div className="pa">{initials}</div>
          <div className="pn"><b>{me.user.name || me.user.email}</b><span>{me.role}</span></div>
          <MoreHorizontal size={16} className="dots" />
        </div>
      </div>
    </aside>
  );
}

function Topbar() {
  const loc = useLocation();
  const { data: health } = useApi("/healthz", undefined, [loc.pathname]);
  const [statusOpen, setStatusOpen] = useState(false);
  const popRef = useRef(null);
  useEffect(() => {
    const h = (e) => { if (popRef.current && !popRef.current.contains(e.target)) setStatusOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const title = (NAV.find(([to]) => to === loc.pathname)?.[1]) ||
    (loc.pathname.startsWith("/admin") ? "Admin" :
     loc.pathname.startsWith("/companies") ? "Companies" :
     loc.pathname.startsWith("/blueprints") ? "Blueprints" : "RevCadence");
  const workerOk = health?.worker?.alive;
  const allOk = workerOk && health?.ok;
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="right">
        <button className="cmdbtn" title="Search (coming soon)" disabled>
          <Search size={15} /> Search <kbd>⌘K</kbd>
        </button>
        <div ref={popRef} style={{ position: "relative" }}>
          <button className="iconbtn" title="System status" onClick={() => setStatusOpen((v) => !v)}>
            <span className={`dot ${allOk ? "ok" : "bad"}`} />
          </button>
          {statusOpen && (
            <div className="status-pop">
              <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".4px", marginBottom: 6 }}>System status</div>
              <div className="row"><span>API</span><span><span className={`dot ${health?.ok ? "ok" : "bad"}`} /> {health?.ok ? "online" : "down"}</span></div>
              <div className="row"><span>Worker</span><span><span className={`dot ${workerOk ? "ok" : "bad"}`} /> {workerOk ? "online" : "offline"}</span></div>
              <div className="row"><span>Database</span><span style={{ color: "var(--muted)" }}>{health?.db || "—"}</span></div>
            </div>
          )}
        </div>
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
        <Route path="/companies/:id/profile" element={<ClientProfile />} />
        <Route path="/clients" element={<Clients />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/enrichment" element={<EnrichLists />} />
        <Route path="/enrichment/lists/:id" element={<EnrichListDetail />} />
        <Route path="/enrichment/database" element={<EnrichDatabase />} />
        <Route path="/enrichment/profile" element={<EnrichConfigPage tab="profile" />} />
        <Route path="/enrichment/icp" element={<EnrichConfigPage tab="icp" />} />
        <Route path="/enrichment/formats" element={<EnrichConfigPage tab="formats" />} />
        <Route path="/enrichment/rules" element={<EnrichConfigPage tab="rules" />} />
        <Route path="/enrichment/companies" element={<Enrichment />} />
        <Route path="/reply" element={<ReplyDashboard />} />
        <Route path="/reply/inbox" element={<ReplyInbox />} />
        <Route path="/reply/processing" element={<ReplyProcessing />} />
        <Route path="/reply/test" element={<ReplyTest />} />
        <Route path="/reply/settings" element={<ReplySettings />} />
        <Route path="/reply/setup" element={<ReplySetup />} />
        <Route path="/reply/workspaces" element={<ReplyWorkspaces />} />
        <Route path="/inbound" element={<InboundVisitors />} />
        <Route path="/blueprints" element={<Blueprints />} />
        <Route path="/blueprints/:id" element={<BlueprintDetail />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </Shell>
  );
}

// Public routes render OUTSIDE the auth gate (the onboarding form the client fills).
function Root() {
  const hash = window.location.hash || "";
  if (hash.startsWith("#/onboard/")) {
    return (
      <Routes>
        <Route path="/onboard/:token" element={<OnboardingForm />} />
        <Route path="*" element={<OnboardingForm />} />
      </Routes>
    );
  }
  return (
    <AuthProvider>
      <Protected />
    </AuthProvider>
  );
}

export default function App() {
  return (
    <HashRouter><Root /></HashRouter>
  );
}
