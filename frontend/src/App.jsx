import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { BrowserRouter, HashRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  LayoutGrid, ListChecks, Database, CircleUser, Target, AlignLeft, CheckCheck, FileText,
  Mail, Inbox, FlaskConical, Settings2, SlidersHorizontal, Flag, Globe, Rows3, Building2,
  Contact, Activity as ActivityIcon, Cog, Wrench, ShieldCheck, ChevronDown, ChevronsUpDown, MoreHorizontal,
  LogOut, Search, ClipboardList, Radar, Briefcase, Bell, KeyRound, Plug, BarChart3, Sparkles, Sun, Moon,
} from "lucide-react";
import { AuthProvider, useAuth } from "./auth";
import { IS_CLIENT_HOST, routePath } from "./host";
import ClientApp from "./client/ClientShell";
import clientSpaceRoutes from "./clientspace/routes";
import { ADMIN_BASE, navGroups } from "./clientspace/nav";
import { ThemeProvider, ThemeToggleButton, useTheme } from "./theme";
import { CommandPalette, GlobalDialogs, InlinePopup, Select, ToastProvider, Toasts, useApi } from "./components";
import KitchenSink from "./pages/KitchenSink";
import Developers from "./pages/Developers";
import CrmSync from "./pages/CrmSync";
import Login from "./pages/Login";
import ChangePassword from "./pages/ChangePassword";
import Dashboard from "./pages/Dashboard";
import Reports from "./pages/Reports";
import Billing from "./pages/Billing";
import BrainChat from "./pages/BrainChat";
import Pipeline from "./pages/Pipeline";
import Companies from "./pages/Companies";
import CompanyDetail from "./pages/CompanyDetail";
import Contacts from "./pages/Contacts";
import ContactDetail from "./pages/ContactDetail";
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
import DocsRoute from "./docs/DocsRoute";

const Forms = lazy(() => import("./pages/Forms"));
const FormBuilder = lazy(() => import("./pages/FormBuilder"));
const FormPreview = lazy(() => import("./pages/FormPreview"));
const FormResponses = lazy(() => import("./pages/FormResponses"));
const FormPage = lazy(() => import("./forms/FormPage"));
const Sequences = lazy(() => import("./pages/Sequences"));
const LazyRoute = ({ children }) => <Suspense fallback={<div className="center" style={{ minHeight: "40vh" }}><div className="spinner" /></div>}>{children}</Suspense>;

// MODES: the sections. Pick a mode → the sidebar shows ONLY that section.
// Master Dashboard + System are always present. Each section is self-contained.
//
// Client Space sits first because it is the only module shared with the client,
// and a mode may declare `groups` — labelled, collapsible sets rendered with the
// same treatment as Build and System. Its items come from clientspace/nav so the
// operator's list and the client's own sidebar cannot drift apart.
const I = 18;
const MODES = {
  client_space: {
    label: "Client Space",
    nav: navGroups(ADMIN_BASE)[0][1],
    groups: navGroups(ADMIN_BASE).slice(1),
  },
  outbound: {
    label: "Outbound",
    nav: [
      ["/enrichment", "Lists", ListChecks],
      ["/enrichment/database", "Database", Database],
    ],
  },
  reply: {
    label: "Reply Management",
    nav: [
      ["/reply", "Dashboard", LayoutGrid],
      ["/reply/inbox", "Inbox", Inbox],
      ["/reply/processing", "Processing", Radar],
      ["/reply/test", "Test Thread", FlaskConical],
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
      ["/workspace/docs", "Shared Documents", FileText],
      ["/sequences", "Email Sequences", Mail],
      ["/blueprints", "Blueprints & Agreements", FileText],
      ["/invoices", "Invoices", ClipboardList],
      ["/clients", "Clients", Briefcase],
      ["/companies", "Companies", Building2],
      ["/contacts", "Contacts", Contact],
      ["/onboarding", "Onboarding", ClipboardList],
    ],
  },
};
const COMMON_NAV = [["/", "Master Dashboard", LayoutGrid]];
// BUILD is the per-workspace "how this section works" config — but scoped to the
// current mode, so CRM doesn't show Outbound/Reply setup and vice-versa.
const BUILD_BY_MODE = {
  outbound: [
    ["/enrichment/profile", "Client Profile", CircleUser],
    ["/enrichment/brain", "Ask the Brain", Sparkles],
    ["/enrichment/icp", "ICP / Non-ICP", Target],
    ["/enrichment/formats", "Formats", AlignLeft],
    ["/enrichment/rules", "Rules", CheckCheck],
    ["/enrichment/training", "Workspace Training", ShieldCheck],
  ],
  reply: [
    ["/reply/setup", "Reply Setup", Settings2],
    ["/reply/settings", "Reply Settings", SlidersHorizontal],
    ["/reply/workspaces", "Extra Channels", Flag],
  ],
  crm: [
    ["/settings/email", "Email Accounts", Mail],
    ["/enrichment/profile", "Client Profile", CircleUser],
  ],
  inbound: [],
  // Client Space carries its own groups; there is nothing to "build" behind it
  // that is not already a screen inside it.
  client_space: [],
};
const BUILD_ALL = Object.values(BUILD_BY_MODE).flat();
// Forms lives here, not under a client module: the builder is an org-level tool
// we own. A form is written once and duplicated per client; the client is chosen
// when an invite is sent, not when the questions are written.
const SYSTEM_NAV = [["/forms", "Forms", ListChecks], ["/activity", "Activity", ActivityIcon],
  ["/jobs", "Jobs", Cog], ["/settings", "Settings", Wrench],
  ["/settings/developers", "Developers", KeyRound], ["/settings/crm", "CRM Integrations", Plug]];
const NavIcon = ({ ic: Ic }) => <span className="icon"><Ic size={I} /></span>;
// One collapsible sidebar group. Build, System and every module group render
// through it, so "same collapse behaviour as the existing groups" is the same
// component rather than a resemblance that drifts.
function NavGroup({ label, open, onToggle, children }) {
  return (
    <>
      <button className="group-btn" onClick={onToggle} aria-expanded={open}>
        <span>{label}</span>
        <motion.span className="group-chevron" animate={{ rotate: open ? 0 : -90 }} transition={{ duration: 0.2, ease: "easeOut" }}>
          <ChevronDown size={14} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div className="sidebar-subnav" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
// Collapsed module groups persist, the way the client's own rail does. An absent
// key means open, so a group added later shows up instead of hiding inside
// somebody's stale preference.
const CS_OPEN_KEY = "rc_module_nav_open";
const readGroupOpen = () => {
  try { return JSON.parse(localStorage.getItem(CS_OPEN_KEY)) || {}; } catch { return {}; }
};
// The wordmark is now mark-only and lives at the far end of the top bar, where it
// doubles as the system-status control.
const RcWave = () => (
  <svg className="rc-wave" viewBox="80 20 560 235" aria-hidden="true"><path d="M104 235 L121 235 C134 235 134 204 147 204 C160 204 160 235 173 235 C186 235 186 197 199 197 C212 197 212 235 225 235 C238 235 238 177 251 177 C264 177 264 235 277 235 C290 235 290 154 303 154 C316 154 316 235 329 235 C342 235 342 129 355 129 C368 129 368 235 381 235 C394 235 394 101 407 101 C420 101 420 235 433 235 C446 235 446 72 459 72 C472 72 472 235 485 235 C498 235 498 42 511 42 C524 42 524 235 537 235 L553 235" fill="none" stroke="currentColor" strokeWidth="20" strokeLinecap="round" strokeLinejoin="round" /></svg>
);

// Lives at the left of the top bar, so its width is independent of the sidebar.
// Non-masters get the same box as a static label.
function WorkspaceSwitcher({ me, workspaceId, setWorkspaceId }) {
  if (!me?.is_master) {
    return (
      <span className="ws-top ws-top-static" title="Workspace">
        <span className="ws-top-name">{me?.workspaces?.[0]?.name || "Workspace"}</span>
      </span>
    );
  }
  return (
    <div className="ws-top" title="Active workspace" data-sel-anchor>
      <Select tone="ghost" caret={ChevronsUpDown} value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
        <option value="">All workspaces</option>
        {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </Select>
    </div>
  );
}

// A handed-over client workspace stays clean: clients only see their results —
// dashboard/reports, the reply inbox, and pipeline/CRM. Everything operational
// (lists, enrichment config, training, settings, developers, integrations,
// billing, admin) is owner/admin-only. Owners, admins and members are unaffected.
const CLIENT_PREFIXES = ["/reports", "/reply/inbox", "/pipeline", "/revenue-inbox", "/companies", "/contacts", "/deals"];
const clientAllowed = (path) => path === "/" || CLIENT_PREFIXES.some((p) => path === p || path.startsWith(p + "/"));

function Sidebar() {
  const { me, logout } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const isClient = me.role === "client";
  // For clients, drop any nav item and any whole mode they shouldn't see.
  const modeEntries = Object.entries(MODES)
    .map(([key, m]) => [key, { ...m, nav: isClient ? m.nav.filter(([to]) => clientAllowed(to)) : m.nav }])
    .filter(([, m]) => m.nav.length > 0);
  const modeMap = Object.fromEntries(modeEntries);
  const [mode, setModeRaw] = useState(localStorage.getItem("rc_mode") || "outbound");
  const loc = useLocation();
  // Client Space is reachable by link from Master Dashboard, which is
  // cross-module — so arriving at one of its screens selects it in the switcher.
  // Scoped to this module on purpose: every other module keeps the stored-mode
  // behaviour it has always had.
  const inClientSpace = loc.pathname === ADMIN_BASE || loc.pathname.startsWith(`${ADMIN_BASE}/`);
  // A workspace row opens its configuration at Client Profile. Keep the sidebar
  // on the owning module so its dropdown and highlighted destination agree with
  // the page that just opened.
  const routeMode = loc.pathname === "/enrichment/profile" ? "outbound" : null;
  const storedMode = modeMap[mode] ? mode : (modeEntries[0]?.[0] || "crm");
  const activeMode = inClientSpace && modeMap.client_space
    ? "client_space"
    : routeMode && modeMap[routeMode] ? routeMode : storedMode;
  const buildItems = BUILD_BY_MODE[activeMode] || [];   // config scoped to the current mode
  const nav = useNavigate();
  const setMode = (m) => {
    localStorage.setItem("rc_mode", m);
    setModeRaw(m);
    nav(modeMap[m].nav[0][0]);   // land on the mode's first screen
  };
  // Build + System are collapsible: hidden until clicked, but auto-open when the
  // current page lives inside them so you can see where you are.
  const inGroup = (items) => items.some(([to]) => loc.pathname === to || loc.pathname.startsWith(to + "/"));
  const [buildOpen, setBuildOpen] = useState(() => inGroup(BUILD_ALL));
  const [systemOpen, setSystemOpen] = useState(() =>
    inGroup(SYSTEM_NAV) || loc.pathname.startsWith("/admin") || loc.pathname.startsWith("/billing"));
  const modeGroups = modeMap[activeMode].groups || [];
  const [groupOpen, setGroupOpen] = useState(readGroupOpen);
  useEffect(() => {
    if (routeMode && mode !== routeMode) {
      localStorage.setItem("rc_mode", routeMode);
      setModeRaw(routeMode);
    }
  }, [mode, routeMode]);
  useEffect(() => {
    if (inGroup(BUILD_ALL)) setBuildOpen(true);
  }, [loc.pathname]);
  const isGroupOpen = (label) => groupOpen[label] !== false;
  const toggleGroup = (label) => setGroupOpen((prev) => {
    const next = { ...prev, [label]: !isGroupOpen(label) };
    try { localStorage.setItem(CS_OPEN_KEY, JSON.stringify(next)); } catch { /* storage can be disabled */ }
    return next;
  });
  const [menu, setMenu] = useState(false);
  const profileRef = useRef(null);
  const initials = (me.user.name || me.user.email).slice(0, 2).toUpperCase();
  return (
    <aside className="sidebar">
      {modeEntries.length > 1 && (
        <div className="ws-switch">
          <Select tone="dark" value={activeMode} onChange={(e) => setMode(e.target.value)}>
            {modeEntries.map(([key, m]) => <option key={key} value={key}>{m.label}</option>)}
          </Select>
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
        {modeGroups.map(([label, items]) => (
          <NavGroup key={label} label={label} open={isGroupOpen(label)} onToggle={() => toggleGroup(label)}>
            {items.map(([to, text, ic]) => (
              <NavLink key={to} to={to} end={to.split("/").length <= 2}><NavIcon ic={ic} /><span>{text}</span></NavLink>
            ))}
          </NavGroup>
        ))}
        {!isClient && (
          <>
            {buildItems.length > 0 && (
              <NavGroup label={`Build · ${modeMap[activeMode].label}`} open={buildOpen}
                onToggle={() => setBuildOpen((v) => !v)}>
                {buildItems.map(([to, label, ic]) => (
                  <NavLink key={to} to={to} end={to.split("/").length <= 2}><NavIcon ic={ic} /><span>{label}</span></NavLink>
                ))}
              </NavGroup>
            )}
            <NavGroup label="System" open={systemOpen} onToggle={() => setSystemOpen((v) => !v)}>
              {SYSTEM_NAV.map(([to, label, ic]) => (
                <NavLink key={to} to={to}><NavIcon ic={ic} /><span>{label}</span></NavLink>
              ))}
              {me.is_master && <NavLink to="/billing"><NavIcon ic={BarChart3} /><span>Billing</span></NavLink>}
              {me.is_master && <NavLink to="/admin"><NavIcon ic={ShieldCheck} /><span>Admin</span></NavLink>}
            </NavGroup>
          </>
        )}
      </nav>
      <div className="foot">
        <InlinePopup open={menu} onClose={() => setMenu(false)} anchorRef={profileRef} side="top" className="profile-menu">
          <button onClick={() => { toggleTheme(); setMenu(false); }}>
            {isDark ? <Sun size={15} /> : <Moon size={15} />}
            {isDark ? "Light mode" : "Dark mode"}
          </button>
          <div className="profile-menu-sep" />
          <button onClick={logout}><LogOut size={15} /> Sign out</button>
        </InlinePopup>
        <div ref={profileRef} className="profile" onClick={() => setMenu((v) => !v)}>
          <div className="pa">{initials}</div>
          <div className="pn"><b>{me.user.name || me.user.email}</b><span>{me.role}</span></div>
          <MoreHorizontal size={16} className="dots" />
        </div>
      </div>
    </aside>
  );
}

function Topbar({ inlineSearchOpen, onInlineSearchChange, inlineSearchQuery, onInlineSearchQueryChange, searchRef }) {
  const loc = useLocation();
  const { me, workspaceId, setWorkspaceId } = useAuth();
  const { data: health } = useApi("/healthz", undefined, [loc.pathname]);
  const [statusOpen, setStatusOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const statusRef = useRef(null);
  const bellRef = useRef(null);
  const workerOk = health?.worker?.alive;
  const allOk = workerOk && health?.ok;
  return (
    <header className="topbar">
      <WorkspaceSwitcher me={me} workspaceId={workspaceId} setWorkspaceId={setWorkspaceId} />
      <div ref={searchRef} className="cmdbtn global top-search">
        <Search size={15} />
        <input
          value={inlineSearchQuery}
          placeholder="Search or ask…"
          aria-label="Search or ask"
          onFocus={() => onInlineSearchChange(true)}
          onChange={(event) => { onInlineSearchQueryChange(event.target.value); onInlineSearchChange(true); }}
          onKeyDown={(event) => event.key === "Escape" && onInlineSearchChange(false)}
        />
        <kbd>⌘K</kbd>
      </div>
      <CommandPalette variant="inline" open={inlineSearchOpen} onClose={() => onInlineSearchChange(false)} anchorRef={searchRef}
        query={inlineSearchQuery} onQueryChange={onInlineSearchQueryChange} showInput={false} />
      <div className="right">
        <button ref={bellRef} className="iconbtn" title="Notifications" onClick={() => setBellOpen((v) => !v)}>
          <Bell size={16} />
        </button>
        <InlinePopup open={bellOpen} onClose={() => setBellOpen(false)} anchorRef={bellRef} align="end" className="status-pop">
          <div className="pop-title">Notifications</div>
          <div style={{ color: "var(--muted)", fontSize: 13, padding: "8px 0" }}>You're all caught up.</div>
        </InlinePopup>
        <button
          ref={statusRef}
          className={`rc-status ${allOk ? "ok" : "bad"}`}
          title={allOk ? "System status — all systems go" : "System status — needs attention"}
          aria-label="System status"
          onClick={() => setStatusOpen((v) => !v)}
        >
          <RcWave />
        </button>
        <InlinePopup open={statusOpen} onClose={() => setStatusOpen(false)} anchorRef={statusRef} align="end" className="status-pop">
          <div className="pop-title">System status</div>
          <div className="row"><span>API</span><span><span className={`dot ${health?.ok ? "ok" : "bad"}`} /> {health?.ok ? "online" : "down"}</span></div>
          <div className="row"><span>Worker</span><span><span className={`dot ${workerOk ? "ok" : "bad"}`} /> {workerOk ? "online" : "offline"}</span></div>
          <div className="row"><span>Database</span><span style={{ color: "var(--muted)" }}>{health?.db || "—"}</span></div>
        </InlinePopup>
      </div>
    </header>
  );
}

function Shell({ children }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [inlineSearchOpen, setInlineSearchOpen] = useState(false);
  const [inlineSearchQuery, setInlineSearchQuery] = useState("");
  const searchRef = useRef(null);
  useEffect(() => {
    const h = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setInlineSearchOpen(false);
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  return (
    <ToastProvider>
      <div className="app">
        <Sidebar />
        <div className="main">
          <Topbar inlineSearchOpen={inlineSearchOpen} onInlineSearchChange={setInlineSearchOpen}
            inlineSearchQuery={inlineSearchQuery} onInlineSearchQueryChange={setInlineSearchQuery} searchRef={searchRef} />
          <div className="content">{children}</div>
        </div>
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </div>
      <GlobalDialogs />
    </ToastProvider>
  );
}

function Protected() {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="center" style={{ minHeight: "100vh" }}><div className="spinner" /></div>;
  if (!me) return <><ThemeToggleButton className="theme-float" /><Login /></>;
  // An account still on the temporary password from its invite gets this screen
  // and nothing else. It is not the guard — the server refuses every other route
  // — it is the only screen that can do anything useful until the change is made.
  if (me.must_change_password) return <><ThemeToggleButton className="theme-float" /><ChangePassword /></>;
  // The client workspace is its own shell — sidebar only, no top bar. Clients land
  // there and never leave it (its catch-all route absorbs every other path).
  // Masters and members can open #/w to see exactly what the client sees.
  //
  // On the client host that is the *only* thing served. An operator who signs in
  // at app.revcadence.com gets the client's view of the client's workspace, which
  // is what that address means; the operator app is at the engine host. This is
  // presentation, not a permission — the server decides what either of them can
  // read, and it decides it the same way on both hosts.
  if (IS_CLIENT_HOST || me.role === "client"
      || loc.pathname === "/w" || loc.pathname.startsWith("/w/")) return <ClientApp />;
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        {clientSpaceRoutes(ADMIN_BASE)}
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
        <Route path="/contacts/:id" element={<ContactDetail />} />
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
        <Route path="/workspace/docs" element={<DocsRoute />} />
        <Route path="/workspace/docs/:pageId" element={<DocsRoute />} />
        <Route path="/sequences" element={<LazyRoute><Sequences /></LazyRoute>} />
        <Route path="/blueprints" element={<Blueprints />} />
        <Route path="/blueprints/:id" element={<BlueprintDetail />} />
        <Route path="/agreements/:id" element={<AgreementDetail />} />
        <Route path="/invoices" element={<Invoices />} />
        <Route path="/invoices/:id" element={<InvoiceDetail />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/forms" element={<LazyRoute><Forms /></LazyRoute>} />
        <Route path="/forms/:id/edit" element={<LazyRoute><FormBuilder /></LazyRoute>} />
        <Route path="/forms/:id/preview" element={<LazyRoute><FormPreview /></LazyRoute>} />
        <Route path="/forms/:id/responses" element={<LazyRoute><FormResponses /></LazyRoute>} />
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
//
// Read through `routePath()`: on the engine host the route lives in the hash, on
// the client host it is a real path, and these three branches have to fire in
// both places or a form link opens the login screen.
function Root() {
  const hash = routePath();
  if (hash.startsWith("/f/")) {
    return (
      <Routes>
        <Route path="/f/:token" element={<LazyRoute><FormPage /></LazyRoute>} />
        <Route path="*" element={<LazyRoute><FormPage /></LazyRoute>} />
      </Routes>
    );
  }
  if (hash.startsWith("/onboard/")) {
    return (
      <Routes>
        <Route path="/onboard/:token" element={<><ThemeToggleButton className="theme-float" /><OnboardingForm /></>} />
        <Route path="*" element={<><ThemeToggleButton className="theme-float" /><OnboardingForm /></>} />
      </Routes>
    );
  }
  if (hash.startsWith("/reset/")) {
    return (
      <Routes>
        <Route path="/reset/:token" element={<><ThemeToggleButton className="theme-float" /><ResetPassword /></>} />
        <Route path="*" element={<><ThemeToggleButton className="theme-float" /><ResetPassword /></>} />
      </Routes>
    );
  }
  return (
    <AuthProvider>
      <Protected />
    </AuthProvider>
  );
}

// The engine host keeps the hash router — every link we have already sent, and
// every bookmark an operator has, is a `#/…` one. The client host gets real
// paths, which is the whole point of it: see frontend/src/host.js, and
// `_public_host_router` in app/main.py for the server-side half that makes a
// hard refresh on one of those paths return the app instead of a 404.
const Router = IS_CLIENT_HOST ? BrowserRouter : HashRouter;

// <Toasts/> is mounted ONCE, here, above the router: every screen — the operator
// app, the client shell, login, and the public form/reset routes — shares the
// one container, so a toast fired during a route change is not lost with it.
export default function App() {
  return (
    <ThemeProvider><Router><Root /></Router><Toasts /></ThemeProvider>
  );
}
