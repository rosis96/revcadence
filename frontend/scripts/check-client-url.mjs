// Cases the client-workspace URL arithmetic has to survive.  `npm run check`
//
// This exists because the redirect in ClientShell is a fixed-point computation
// run inside an effect: get it wrong and the failure is not a wrong page, it is
// a navigation loop or a mangled path, neither of which a build catches. The
// logic lives in clientspace/clientUrl.js with no React and no icon imports
// precisely so it can be run here, by node, in a second.
import {
  appPath, clientBase, clientBaseFrom, clientRedirectTarget, slugFromPath,
} from "../src/clientspace/clientUrl.js";

let failed = 0;
const eq = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(ok ? "✓" : "✗ FAIL", name,
    ok ? "" : `— got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
};

// ---- reading the slug back off a URL
eq("slug from the base", slugFromPath("/w/acme"), "acme");
eq("slug from a deep path", slugFromPath("/w/acme/docs/12"), "acme");
eq("bare /w has no slug", slugFromPath("/w"), "");
eq("a trailing slash is not a slug", slugFromPath("/w/"), "");
eq("another module has no slug", slugFromPath("/client-space/docs"), "");
eq("base from a deep path", clientBaseFrom("/w/acme/library"), "/w/acme");
eq("base with no slug", clientBase(""), "/w");

// ---- already canonical: "" means stay put. Returning a target here would
//      re-navigate to the same URL on every render.
eq("the canonical base is stable", clientRedirectTarget("/w/acme", "", "acme"), "");
eq("a canonical deep path is stable", clientRedirectTarget("/w/acme/docs/12", "", "acme"), "");
eq("an unrelated query is preserved and stable",
  clientRedirectTarget("/w/acme/docs", "?tab=comments", "acme"), "");

// ---- bare /w, and the legacy ?ws= shape still sitting in sent invites
eq("bare /w gains the slug", clientRedirectTarget("/w", "", "acme"), "/w/acme");
eq("a legacy ?ws= invite is consumed", clientRedirectTarget("/w", "?ws=12", "acme"), "/w/acme");
eq("consuming ?ws= keeps its siblings",
  clientRedirectTarget("/w", "?ws=12&tab=plan", "acme"), "/w/acme?tab=plan");

// ---- a slug this account cannot open is a wrong address, not a 403
eq("a wrong slug is corrected", clientRedirectTarget("/w/other", "", "acme"), "/w/acme");
eq("a wrong slug keeps the deep link",
  clientRedirectTarget("/w/other/docs/12", "", "acme"), "/w/acme/docs/12");

// ---- a path outside the base must not be sliced: `/pipeline` once became
//      `/w/acmeipeline` by taking two characters off a prefix it never had.
eq("a foreign path goes to the Overview whole",
  clientRedirectTarget("/pipeline", "", "acme"), "/w/acme");
eq("a path merely starting with the same letters is not sliced",
  clientRedirectTarget("/wombat", "", "acme"), "/w/acme");
eq("an admin path goes to the Overview whole",
  clientRedirectTarget("/admin", "", "acme"), "/w/acme");

// ---- no workspace: never navigate, or `/w` redirects to `/w` forever
eq("no active slug never navigates", clientRedirectTarget("/w", "", ""), "");
eq("no active slug never navigates (undefined)", clientRedirectTarget("/w", "", undefined), "");

// ---- and the property that matters most: one hop, then it settles
for (const [p, s] of [["/w", "?ws=12"], ["/pipeline", ""], ["/w/other/docs/12", ""], ["/w/", ""]]) {
  const [np, nq] = clientRedirectTarget(p, s, "acme").split("?");
  eq(`converges after one hop: ${p}${s}`,
    clientRedirectTarget(np, nq ? `?${nq}` : "", "acme"), "");
}

// ---- appPath: the same absolute link, resolved for whichever shell is running
eq("operator paths are left alone", appPath("/companies", "/deals/12"), "/deals/12");
eq("client paths gain the base", appPath("/w/acme/companies", "/deals/12"), "/w/acme/deals/12");
eq("the base is taken from the URL, not a guess",
  appPath("/w/other/pipeline", "/companies/5"), "/w/other/companies/5");
eq("a bare /w has no slug, so nothing is prefixed", appPath("/w", "/deals/12"), "/deals/12");
eq("an already-resolved target is not prefixed twice",
  appPath("/w/acme/companies", "/w/acme/deals/12"), "/w/acme/deals/12");
eq("the base itself is not doubled", appPath("/w/acme/docs", "/w/acme"), "/w/acme");
eq("a relative target is returned as-is", appPath("/w/acme/docs", "settings"), "settings");
eq("a non-string target is returned as-is", appPath("/w/acme/docs", undefined), undefined);
// A workspace slugged like a route segment must not confuse the prefix test.
eq("a slug that looks like a route still resolves",
  appPath("/w/companies/pipeline", "/companies/5"), "/w/companies/companies/5");

console.log(failed ? `\n${failed} FAILED` : "\nall client-url cases pass");
process.exit(failed ? 1 : 0);
