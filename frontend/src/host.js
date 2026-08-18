// Which face of the app is this bundle being served as?
//
// One deploy, one bundle, two hosts. `engine.revcadence.com` is ours and keeps
// the hash router: every bookmark, every `#/w` preview link and every invite
// already sitting in somebody's inbox stays valid. The client portal serves
// real paths at `/client/<workspace-slug>`, so its address remains on the
// deployed RevCadence origin instead of becoming a localhost/hash URL.
//
// The `app.` prefix test mirrors `app/main.py::_public_host_router`, which
// already recognises `blueprint.` / `agreement.` / `invoice.` the same way, with
// the same comma-separated env escape hatch for hosts that do not fit the
// prefix. Keeping the two in the same shape matters: the server decides which
// hosts get an SPA fallback, and this decides which router can survive one.
//
// `?client-host=1` is the local-dev switch (`?client-host=0` turns it off). It
// is remembered for the tab, because a router that changes on the first
// navigation is worse than no switch at all.
const EXTRA = (import.meta.env.VITE_CLIENT_HOSTS || "")
  .split(",")
  .map((h) => h.trim().toLowerCase())
  .filter(Boolean);

const DEV_KEY = "rc_client_host";

function devOverride() {
  try {
    const asked = new URLSearchParams(window.location.search).get("client-host");
    if (asked !== null) sessionStorage.setItem(DEV_KEY, asked === "0" ? "" : "1");
    return sessionStorage.getItem(DEV_KEY) === "1";
  } catch {
    return false;   // storage can be disabled; the prefix test still decides
  }
}

const host = (window.location.hostname || "").toLowerCase();
const clientPath = /^\/client(?:\/|$)/.test(window.location.pathname || "");

export const IS_CLIENT_HOST = clientPath || host.startsWith("app.") || EXTRA.includes(host) || devOverride();

// The route the browser is on, whichever router is mounted. Code that reads the
// URL before the router exists — the public-route branch in App.jsx — has to ask
// this rather than `location.hash`, which is empty on the client host.
export const routePath = () => (IS_CLIENT_HOST
  ? window.location.pathname
  : (window.location.hash || "").replace(/^#/, ""));
