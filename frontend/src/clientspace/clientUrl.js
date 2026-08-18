// Client-workspace URL arithmetic. Deliberately dependency-free — no React, no
// icons — so it can be exercised directly by `node` (see the block at the bottom
// of this comment) rather than only through a browser.
//
// The client's base carries the workspace slug: `/w/acme-inc`. Ours does not,
// because the operator shell already has a workspace switcher and the URL would
// then have two places saying which client is on screen.
//
// The slug is here for the link we email. `app.revcadence.com/w/acme-inc` names
// the client; `/#/w?ws=12` names a row in our database.
//
//   node -e "import('./src/clientspace/clientUrl.js').then(m => console.log(
//     m.clientRedirectTarget('/w', '', 'acme')))"

export const CLIENT_BASE = "/w";

// The pattern the router matches, as opposed to any resolved path. Keeping the
// two apart is what stops a NavLink pointing at the literal `/w/:slug`.
export const CLIENT_ROUTE_BASE = `${CLIENT_BASE}/:slug`;

export const clientBase = (slug) => (slug ? `${CLIENT_BASE}/${slug}` : CLIENT_BASE);

// Read the slug back off whatever URL we are on. Screens deeper in the tree ask
// for it this way rather than threading it through props.
export const slugFromPath = (pathname) => {
  const m = new RegExp(`^${CLIENT_BASE}/([^/?#]+)`).exec(pathname || "");
  return m ? m[1] : "";
};

export const clientBaseFrom = (pathname) => clientBase(slugFromPath(pathname));

/**
 * Resolve an operator route against the shell the caller is running in.
 *
 * The CRM screens are mounted at two bases and are full of absolute links —
 * `/companies/5`, `/deals/12`, `/invoices/3`. In the operator shell those are
 * correct as written. In the client shell the same string matches no route, and
 * the catch-all quietly returns the reader to their Overview, so a link that
 * looks fine is a dead end.
 *
 * Given the path the screen is CURRENTLY on, this prefixes the client base when
 * there is one and returns the target untouched when there is not. Screens call
 * it through `useAppPath()` rather than reaching for the slug themselves.
 *
 *   appPath("/companies", "/deals/12")        → "/deals/12"
 *   appPath("/w/acme/companies", "/deals/12") → "/w/acme/deals/12"
 *
 * Already-resolved targets pass through unchanged, so wrapping one twice — which
 * happens when a helper is threaded through a shared component — is harmless.
 */
export function appPath(pathname, target) {
  const slug = slugFromPath(pathname);
  if (!slug || typeof target !== "string" || !target.startsWith("/")) return target;
  const base = clientBase(slug);
  if (target === base || target.startsWith(`${base}/`)) return target;
  return `${base}${target}`;
}

/**
 * Where the client shell should actually be, given where the browser is.
 *
 * Returns "" when the URL is already correct — the caller must not navigate on
 * "", or it re-navigates to the same place forever.
 *
 * Three things get corrected, all to the same canonical shape:
 *  - a bare `/w`, which has no client in it;
 *  - a legacy `?ws=` invite link, which named the workspace by id;
 *  - a slug this account cannot open, which is a wrong address rather than an
 *    access question — the server decides what they can read either way.
 *
 * A path already inside the base keeps its tail, so a deep link into Docs stays
 * a deep link into Docs. Anything else is a client who typed `/pipeline`, and it
 * goes to the Overview whole: slicing a fixed prefix off a path that never had
 * it produces gibberish (`/pipeline` → `/w/acmeipeline`).
 */
export function clientRedirectTarget(pathname, search, activeSlug) {
  if (!activeSlug) return "";
  const slug = slugFromPath(pathname);
  const inBase = pathname === CLIENT_BASE || pathname.startsWith(`${CLIENT_BASE}/`);
  const rest = inBase
    ? pathname.slice(slug ? clientBase(slug).length : CLIENT_BASE.length)
    : "";

  const query = new URLSearchParams(search || "");
  query.delete("ws");                       // consumed; it never propagates
  const qs = query.toString();

  const target = `${clientBase(activeSlug)}${rest}${qs ? `?${qs}` : ""}`;
  return target === `${pathname}${search || ""}` ? "" : target;
}
