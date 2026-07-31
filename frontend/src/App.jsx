import { useEffect, useRef, useState } from "react";
import { HashRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutGrid, ListChecks, Database, CircleUser, Target, AlignLeft, CheckCheck, FileText,
  Mail, Inbox, FlaskConical, Settings2, SlidersHorizontal, Flag, Globe, Rows3, Building2,
  Contact, Activity as ActivityIcon, Cog, Wrench, ShieldCheck, ChevronDown, MoreHorizontal,
  LogOut, Search, ClipboardList, Radar, Briefcase, Bell, KeyRound, Plug, BarChart3, Sparkles,
} from "lucide-react";
import { AuthProvider, useAuth } from "./auth";
import { CommandPalette, ToastProvider, useApi, useClickOutside } from "./components";
import KitchenSink from "./pages/KitchenSink";
import Developers from "./pages/Developers";
import CrmSync from "./pages/CrmSync";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Reports from "./pages/Reports";
import Billing from "./pages/Billing";
import BrainChat from "./pages/BrainChat";
import Pipeline from "./pages/Pipeline";
import Companies from "./pages/Companies";
import CompanyDetail from "./pages/CompanyDetail";
import Contacts from "./pages/Contacts";
import Enrichment from "./pages/Enrichment";
import EnrichLists from "./pages/EnrichLists";
import EnrichListDetail from "./pages/EnrichListDetail";
import EnrichConfigPage from "./pages/EnrichConfig";
import TrainingBridge from "./pages/TrainingBridge";
import Blueprints from "./pages/Blueprints";
import BlueprintDetail from "./pages/BlueprintDetail";
import AgreementDetail from "./pages/AgreementDetail";
import InvoiceDetail from "./pages/InvoiceDetail";
import DealRecord from "./pages/DealRecord";
import MailboxConnect from "./pages/MailboxConnect";
import RevenueInbox from "./pages/RevenueInbox";
import Invoices from "./pages/Invoices";
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
import ResetPassword from "./pages/ResetPassword";

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
      ["/enrichment/brain", "Ask the Brain", Sparkles],
      ["/enrichment/icp", "ICP / Non-ICP", Target],
      ["/enrichment/formats", "Formats", AlignLeft],
      ["/enrichment/rules", "Rules", CheckCheck],
      ["/enrichment/training", "Workspace Training", ShieldCheck],
    ],
  },
  reply: {
    label: "Reply Management",
    nav: [
      ["/reply", "Dashboard", LayoutGrid],
      ["/reply/inbox", "Inbox", Inbox],
      ["/reply/processing", "Processing", Radar],
      ["/reply/test", "Test Thread", FlaskConical],
      ["/settings/email", "Email Accounts", Mail],
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
      ["/reports", "Reports", BarChart3],
      ["/revenue-inbox", "Revenue Inbox", Inbox],
      ["/blueprints", "Blueprints & Agreements", FileText],
      ["/invoices", "Invoices", ClipboardList],
      ["/clients", "Clients", Briefcase],
      ["/companies", "Companies", Building2],
      ["/contacts", "Contacts", Contact],
      ["/onboarding", "Onboarding", ClipboardList],
      ["/activity", "Activity", ActivityIcon],
    ],
  },
};
const COMMON_NAV = [["/", "Master Dashboard", LayoutGrid]];
const SYSTEM_NAV = [["/jobs", "Jobs", Cog], ["/settings", "Settings", Wrench],
  ["/settings/developers", "Developers", KeyRound], ["/settings/crm", "CRM Integrations", Plug]];
const NAV = [...COMMON_NAV, ...Object.values(MODES).flatMap((m) => m.nav), ...SYSTEM_NAV];
const NavIcon = ({ ic: Ic }) => <span className="icon"><Ic size={I} /></span>;

// A handed-over client workspace stays clean: clients only see their results —
// dashboard/reports, the reply inbox, and pipeline/CRM. Everything operational
// (lists, enrichment config, training, settings, developers, integrations,
// billing, admin) is owner/admin-only. Owners, admins and members are unaffected.
const CLIENT_PREFIXES = ["/reports", "/reply/inbox", "/pipeline", "/revenue-inbox", "/companies", "/contacts", "/deals"];
const clientAllowed = (path) => path === "/" || CLIENT_PREFIXES.some((p) => path === p || path.startsWith(p + "/"));

function Sidebar() {
  const { me, logout } = useAuth();
  const isClient = me.role === "client";
  // For clients, drop any nav item and any whole mode they shouldn't see.
  const modeEntries = Object.entries(MODES)
    .map(([key, m]) => [key, { ...m, nav: isClient ? m.nav.filter(([to]) => clientAllowed(to)) : m.nav }])
    .filter(([, m]) => m.nav.length > 0);
  const modeMap = Object.fromEntries(modeEntries);
  const [mode, setModeRaw] = useState(localStorage.getItem("rc_mode") || "outbound");
  const activeMode = modeMap[mode] ? mode : (modeEntries[0]?.[0] || "crm");
  const nav = useNavigate();
  const setMode = (m) => {
    localStorage.setItem("rc_mode", m);
    setModeRaw(m);
    nav(modeMap[m].nav[0][0]);   // land on the mode's first screen
  };
  const [menu, setMenu] = useState(false);
  const initials = (me.user.name || me.user.email).slice(0, 2).toUpperCase();
  return (
    <aside className="sidebar">
      <div className="logo"><svg className="rc-wave" viewBox="80 20 560 235" aria-hidden="true"><path d="M104 235 L121 235 C134 235 134 204 147 204 C160 204 160 235 173 235 C186 235 186 197 199 197 C212 197 212 235 225 235 C238 235 238 177 251 177 C264 177 264 235 277 235 C290 235 290 154 303 154 C316 154 316 235 329 235 C342 235 342 129 355 129 C368 129 368 235 381 235 C394 235 394 101 407 101 C420 101 420 235 433 235 C446 235 446 72 459 72 C472 72 472 235 485 235 C498 235 498 42 511 42 C524 42 524 235 537 235 L553 235" fill="none" stroke="currentColor" strokeWidth="20" strokeLinecap="round" strokeLinejoin="round" /></svg><span>revcadence</span></div>
      {modeEntries.length > 1 && (
        <div className="ws-switch">
          <select value={activeMode} onChange={(e) => setMode(e.target.value)}>
            {modeEntries.map(([key, m]) => <option key={key} value={key}>{m.label}</option>)}
          </select>
        </div>
      )}
      <nav className="nav">
        {COMMON_NAV.map(([to, label, ic]) => (
          <NavLink key={to} to={to} end><NavIcon ic={ic} /><span>{label}</span></NavLink>
        ))}
        <div className="group">{modeMap[activeMode].label}</div>
        {modeMap[activeMode].nav.map(([to, label, ic]) => (
          <NavLink key={to} to={to} end={to.split("/").length <= 2}><NavIcon ic={ic} /><span>{label}</span></NavLink>
        ))}
        {!isClient && (
          <>
            <div className="group">System</div>
            {SYSTEM_NAV.map(([to, label, ic]) => (
              <NavLink key={to} to={to}><NavIcon ic={ic} /><span>{label}</span></NavLink>
            ))}
          </>
        )}
        {me.is_master && <NavLink to="/billing"><NavIcon ic={BarChart3} /><span>Billing</span></NavLink>}
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

function Topbar({ onSearch }) {
  const loc = useLocation();
  const { me, workspaceId, setWorkspaceId } = useAuth();
  const { data: health } = useApi("/healthz", undefined, [loc.pathname]);
  const [statusOpen, setStatusOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const popRef = useRef(null);
  const bellRef = useRef(null);
  useClickOutside(popRef, () => setStatusOpen(false));
  useClickOutside(bellRef, () => setBellOpen(false));
  const title = (NAV.find(([to]) => to === loc.pathname)?.[1]) ||
    (loc.pathname.startsWith("/admin") ? "Admin" :
     loc.pathname.startsWith("/companies") ? "Companies" :
     loc.pathname.startsWith("/dev") ? "Kitchen sink" :
     loc.pathname.startsWith("/blueprints") ? "Blueprints" : "RevCadence");
  const workerOk = health?.worker?.alive;
  const allOk = workerOk && health?.ok;
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <button className="cmdbtn global" onClick={onSearch}>
        <Search size={15} /> Search or ask… <kbd>⌘K</kbd>
      </button>
      <div className="right">
        {me?.is_master ? (
          <div className="ws-top" title="Active workspace">
            <Building2 size={14} style={{ opacity: 0.6 }} />
            <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
              <option value="">All workspaces</option>
              {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        ) : (
          <span className="ws-top ws-top-static"><Building2 size={14} style={{ opacity: 0.6 }} />{me?.workspaces?.[0]?.name || "Workspace"}</span>
        )}
        <div ref={bellRef} style={{ position: "relative" }}>
          <button className="iconbtn" title="Notifications" onClick={() => setBellOpen((v) => !v)}>
            <Bell size={16} />
          </button>
          {bellOpen && (
            <div className="status-pop">
              <div className="pop-title">Notifications</div>
              <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>You're all caught up.</div>
            </div>
          )}
        </div>
        <div ref={popRef} style={{ position: "relative" }}>
          <button className="iconbtn" title="System status" onClick={() => setStatusOpen((v) => !v)}>
            <span className={`dot ${allOk ? "ok" : "bad"}`} />
          </button>
          {statusOpen && (
            <div className="status-pop">
              <div className="pop-title">System status</div>
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  useEffect(() => {
    const h = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((v) => !v); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  return (
    <ToastProvider>
      <div className="app">
        <Sidebar />
        <div className="main">
          <Topbar onSearch={() => setPaletteOpen(true)} />
          <div className="content">{children}</div>
        </div>
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </div>
    </ToastProvider>
  );
}

function Protected() {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="center" style={{ minHeight: "100vh" }}><div className="spinner" /></div>;
  if (!me) return <Login />;
  // Belt-and-suspenders: a client typing a hidden URL is sent back to their dashboard.
  if (me.role === "client" && !clientAllowed(loc.pathname)) return <Shell><Navigate to="/" replace /></Shell>;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/pipeline" element={<Pipeline />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/deals/:id" element={<DealRecord />} />
        <Route path="/revenue-inbox" element={<RevenueInbox />} />
        <Route path="/settings/email" element={<MailboxConnect />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/companies/:id" element={<CompanyDetail />} />
        <Route path="/companies/:id/profile" element={<ClientProfile />} />
        <Route path="/clients" element={<Clients />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/enrichment" element={<EnrichLists />} />
        <Route path="/enrichment/lists/:id" element={<EnrichListDetail />} />
        <Route path="/enrichment/database" element={<EnrichDatabase />} />
        <Route path="/enrichment/profile" element={<EnrichConfigPage tab="profile" />} />
        <Route path="/enrichment/brain" element={<BrainChat />} />
        <Route path="/enrichment/icp" element={<EnrichConfigPage tab="icp" />} />
        <Route path="/enrichment/formats" element={<EnrichConfigPage tab="formats" />} />
        <Route path="/enrichment/rules" element={<EnrichConfigPage tab="rules" />} />
        <Route path="/enrichment/training" element={<TrainingBridge />} />
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
        <Route path="/agreements/:id" element={<AgreementDetail />} />
        <Route path="/invoices" element={<Invoices />} />
        <Route path="/invoices/:id" element={<InvoiceDetail />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/settings/developers" element={<Developers />} />
        <Route path="/settings/crm" element={<CrmSync />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/billing" element={<Billing />} />
        <Route path="/dev/kitchen-sink" element={<KitchenSink />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </Shell>
  );
}

// Public routes render OUTSIDE the auth gate (the onboarding form + password reset).
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
  if (hash.startsWith("#/reset/")) {
    return (
      <Routes>
        <Route path="/reset/:token" element={<ResetPassword />} />
        <Route path="*" element={<ResetPassword />} />
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
