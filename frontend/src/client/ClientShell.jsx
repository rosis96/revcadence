// The client workspace shell — sidebar only, no top bar.
//
// Deliberately NOT the admin Shell: a client has exactly one workspace, so there
// is nothing to switch between, search across or monitor. Everything the chrome
// would hold (workspace identity, module, profile, theme) collapses into the one
// rail. Layout: workspace at the top · module switcher · the module's nav ·
// profile at the bottom. Palette, spacing and nav states are the admin tokens —
// same theme, fewer parts.
//
// The modules come from `clientspace/modules`, and each one's items resolve
// through the same function the operator's Client Space rail uses. When a client
// rings up and says "I can't find it", both sides are looking at the same list
// in the same order — which is the whole reason the client runs the operator's
// screens rather than client-flavoured copies of them.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  NavLink, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams,
} from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Building2, ChevronDown, LogOut, Moon, MoreHorizontal, Sun } from "lucide-react";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import { EmptyState, GlobalDialogs, InlinePopup, Select, ToastProvider } from "../components";
import clientSpaceRoutes from "../clientspace/routes";
import crmRoutes from "../clientspace/crmRoutes";
import outboundRoutes from "../clientspace/outboundRoutes";
import replyRoutes from "../clientspace/replyRoutes";
import {
  CLIENT_MODULES, MODULE_KEYS, moduleForPath, moduleHome, moduleNav,
} from "../clientspace/modules";
import {
  CLIENT_ROUTE_BASE, clientBase, clientRedirectTarget, slugFromPath,
} from "../clientspace/nav";

const I = 18;

// Collapsed groups persist, so the rail a client shaped for themselves survives
// a reload. Absent key = open, so a group added later shows up rather than
// hiding inside someone's stale preference.
const OPEN_KEY = "rc_client_nav_open";
const readOpen = () => {
  try { return JSON.parse(localStorage.getItem(OPEN_KEY)) || {}; } catch { return {}; }
};

// Which client this shell is showing.
//
// A client has exactly one workspace, so for them this is always that one. It
// matters for everybody else: masters and members open /w to see what a client
// sees, and this rail has no switcher of its own. Without this the shell showed
// `workspaces[0]` — the first client in the org — while the screens below it
// read from the workspace switcher, so the name in the corner could belong to a
// different client than the data on the page.
//
// The slug in the URL wins — `/w/acme-inc` is a statement about which client's
// space this is, and it is what an emailed link carries. `?ws=` is the older
// form of the same intent and is still honoured so invites already in someone's
// inbox keep working; the redirect below then rewrites the address bar to the
// slug form, so the legacy shape never propagates any further.
function useActiveWorkspace() {
  const { me, workspaceId, setWorkspaceId } = useAuth();
  const loc = useLocation();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const slug = slugFromPath(loc.pathname);
  const requested = params.get("ws");
  const list = me.workspaces || [];
  const isClient = me.role === "client";

  const active = useMemo(() => {
    // A client has exactly one workspace and the server decides it regardless,
    // so an unknown or someone else's slug in the URL is not an access question
    // — it is a wrong address, and it gets corrected to theirs below.
    if (isClient) return list[0];
    const find = (id) => list.find((w) => String(w.id) === String(id));
    return list.find((w) => w.slug === slug)
      || (requested && find(requested)) || find(workspaceId) || list[0];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isClient, JSON.stringify(list), slug, requested, workspaceId]);

  // Point the switcher at it too, so every screen inside fetches this client
  // instead of falling back to the all-workspaces rollup and rendering
  // "Choose a client" underneath a header that already names one.
  useEffect(() => {
    if (active && String(active.id) !== String(workspaceId)) setWorkspaceId(String(active.id));
  }, [active, workspaceId, setWorkspaceId]);

  // Keep the address bar in agreement with what is actually on screen: bare
  // `/w`, a stale `?ws=`, or a slug this account cannot open all land on the
  // canonical `/w/<their-slug>` with the rest of the path intact, so a deep link
  // into Docs stays a deep link into Docs. See clientUrl.js for the arithmetic
  // and the cases it has to survive.
  useEffect(() => {
    const target = clientRedirectTarget(loc.pathname, loc.search, active?.slug);
    if (target) nav(target, { replace: true });
  }, [active, loc.pathname, loc.search, nav]);

  return active;
}

function WorkspaceHead({ workspace, moduleLabel }) {
  const name = workspace?.name || "Workspace";
  return (
    <div className="ws-head" title={name}>
      {workspace?.logo_url
        ? <img className="ws-head-mark" src={workspace.logo_url} alt="" />
        : <span className="ws-head-mark">{name.slice(0, 1).toUpperCase()}</span>}
      <span className="ws-head-name">
        <b>{name}</b>
        <span>{moduleLabel}</span>
      </span>
    </div>
  );
}

const CLIENT_ONLY = { internal: false };

function ClientSidebar({ workspace, base }) {
  const { me, logout } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const [menu, setMenu] = useState(false);
  const [open, setOpen] = useState(readOpen);
  const profileRef = useRef(null);
  const loc = useLocation();
  const nav = useNavigate();
  const initials = (me.user.name || me.user.email).slice(0, 2).toUpperCase();
  // Which module the rail is showing. Read off the URL rather than remembered:
  // for this shell the two cannot disagree — every path belongs to exactly one
  // module — and a remembered choice would teleport a client away from the
  // Overview their bookmark points at.
  const activeModule = moduleForPath(loc.pathname, base);
  // The active module's rail. Internal groups are not rendered here at all — see
  // clientspace/nav — and it is rebuilt per workspace because every link is
  // slug-scoped.
  const clientNav = useMemo(() => moduleNav(activeModule, base, CLIENT_ONLY), [activeModule, base]);
  // A module's landing screen must not stay lit while you are on a screen below
  // it, so those links match exactly and the rest match by prefix.
  const homes = useMemo(
    () => new Set(MODULE_KEYS.map((key) => moduleHome(key, base, CLIENT_ONLY))), [base],
  );
  const isOpen = (group) => open[group] !== false;
  const toggle = (group) => setOpen((prev) => {
    const next = { ...prev, [group]: !isOpen(group) };
    try { localStorage.setItem(OPEN_KEY, JSON.stringify(next)); } catch { /* storage can be disabled */ }
    return next;
  });
  const link = ([to, label, Ic]) => (
    <NavLink key={to} to={to} end={homes.has(to)}>
      <span className="icon"><Ic size={I} /></span>
      <span>{label}</span>
    </NavLink>
  );
  return (
    <aside className="sidebar">
      <WorkspaceHead workspace={workspace} moduleLabel={CLIENT_MODULES[activeModule].label} />
      {MODULE_KEYS.length > 1 && (
        <div className="ws-switch">
          <Select tone="dark" value={activeModule}
            onChange={(e) => nav(moduleHome(e.target.value, base, CLIENT_ONLY))}>
            {MODULE_KEYS.map((key) => (
              <option key={key} value={key}>{CLIENT_MODULES[key].label}</option>
            ))}
          </Select>
        </div>
      )}
      <nav className="nav">
        {clientNav.map(([group, items]) => (group === null ? items.map(link) : (
          <div key={group}>
            <button className="group-btn" onClick={() => toggle(group)} aria-expanded={isOpen(group)}>
              <span>{group}</span>
              <motion.span className="group-chevron" animate={{ rotate: isOpen(group) ? 0 : -90 }}
                transition={{ duration: 0.2, ease: "easeOut" }}>
                <ChevronDown size={14} />
              </motion.span>
            </button>
            <AnimatePresence initial={false}>
              {isOpen(group) && (
                <motion.div key={group} className="sidebar-subnav"
                  initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
                  {items.map(link)}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )))}
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
          <div className="pn"><b>{me.user.name || me.user.email}</b><span>{me.user.email}</span></div>
          <MoreHorizontal size={16} className="dots" />
        </div>
      </div>
    </aside>
  );
}

export default function ClientApp() {
  const workspace = useActiveWorkspace();
  const base = clientBase(workspace?.slug);
  return (
    <ToastProvider>
      <div className="app client-app">
        <ClientSidebar workspace={workspace} base={base} />
        <div className="main">
          <div className="content">
            {/* Every route below lives under a slug. Without one there is nothing
                to route to, and the catch-all would redirect `/w` to `/w` forever
                — so say what is wrong instead of spinning. */}
            {workspace?.slug ? (
              <Routes>
                {clientSpaceRoutes(CLIENT_ROUTE_BASE, { internal: false })}
                {/* Outbound and Reply Management are their own modules, so each is
                    its own subtree — not a screen inside Client Space. See
                    clientspace/outboundRoutes and clientspace/replyRoutes. */}
                {outboundRoutes(CLIENT_ROUTE_BASE)}
                {replyRoutes(CLIENT_ROUTE_BASE)}
                {crmRoutes(CLIENT_ROUTE_BASE)}
                {/* The catch-all is the URL guard: a client typing /pipeline, /admin or
                    any other module's path lands back on their Overview. The server
                    refuses those calls too — this only keeps the address bar honest. */}
                <Route path="*" element={<Navigate to={base} replace />} />
              </Routes>
            ) : (
              <EmptyState icon={Building2} title="No workspace yet"
                hint="This account is not attached to a client workspace. Ask us to finish the invite." />
            )}
          </div>
        </div>
      </div>
      <GlobalDialogs />
    </ToastProvider>
  );
}
