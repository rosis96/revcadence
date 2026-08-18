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
eq("slug from the base", slugFromPath("/client/acme"), "acme");
eq("slug from a deep path", slugFromPath("/client/acme/docs/12"), "acme");
eq("bare /client has no slug", slugFromPath("/client"), "");
eq("a trailing slash is not a slug", slugFromPath("/client/"), "");
eq("another module has no slug", slugFromPath("/client-space/docs"), "");
eq("base from a deep path", clientBaseFrom("/client/acme/library"), "/client/acme");
eq("base with no slug", clientBase(""), "/client");

// ---- already canonical: "" means stay put. Returning a target here would
//      re-navigate to the same URL on every render.
eq("the canonical base is stable", clientRedirectTarget("/client/acme", "", "acme"), "");
eq("a canonical deep path is stable", clientRedirectTarget("/client/acme/docs/12", "", "acme"), "");
eq("an unrelated query is preserved and stable",
  clientRedirectTarget("/client/acme/docs", "?tab=comments", "acme"), "");

// ---- bare /w, and the legacy ?ws= shape still sitting in sent invites
eq("bare /client gains the slug", clientRedirectTarget("/client", "", "acme"), "/client/acme");
eq("a legacy ?ws= invite is consumed", clientRedirectTarget("/client", "?ws=12", "acme"), "/client/acme");
eq("consuming ?ws= keeps its siblings",
  clientRedirectTarget("/client", "?ws=12&tab=plan", "acme"), "/client/acme?tab=plan");

// ---- a slug this account cannot open is a wrong address, not a 403
eq("a wrong slug is corrected", clientRedirectTarget("/client/other", "", "acme"), "/client/acme");
eq("a wrong slug keeps the deep link",
  clientRedirectTarget("/client/other/docs/12", "", "acme"), "/client/acme/docs/12");

// ---- a path outside the base must not be sliced: `/pipeline` once became
//      `/client/acmeipeline` by taking two characters off a prefix it never had.
eq("a foreign path goes to the Overview whole",
  clientRedirectTarget("/pipeline", "", "acme"), "/client/acme");
eq("a path merely starting with the same letters is not sliced",
  clientRedirectTarget("/wombat", "", "acme"), "/client/acme");
eq("an admin path goes to the Overview whole",
  clientRedirectTarget("/admin", "", "acme"), "/client/acme");

// ---- no workspace: never navigate, or `/w` redirects to `/w` forever
eq("no active slug never navigates", clientRedirectTarget("/client", "", ""), "");
eq("no active slug never navigates (undefined)", clientRedirectTarget("/client", "", undefined), "");

// ---- and the property that matters most: one hop, then it settles
for (const [p, s] of [["/client", "?ws=12"], ["/pipeline", ""], ["/client/other/docs/12", ""], ["/client/", ""]]) {
  const [np, nq] = clientRedirectTarget(p, s, "acme").split("?");
  eq(`converges after one hop: ${p}${s}`,
    clientRedirectTarget(np, nq ? `?${nq}` : "", "acme"), "");
}

// ---- appPath: the same absolute link, resolved for whichever shell is running
eq("operator paths are left alone", appPath("/companies", "/deals/12"), "/deals/12");
eq("client paths gain the base", appPath("/client/acme/companies", "/deals/12"), "/client/acme/deals/12");
eq("the base is taken from the URL, not a guess",
  appPath("/client/other/pipeline", "/companies/5"), "/client/other/companies/5");
eq("a bare /client has no slug, so nothing is prefixed", appPath("/client", "/deals/12"), "/deals/12");
eq("an already-resolved target is not prefixed twice",
  appPath("/client/acme/companies", "/client/acme/deals/12"), "/client/acme/deals/12");
eq("the base itself is not doubled", appPath("/client/acme/docs", "/client/acme"), "/client/acme");
eq("a relative target is returned as-is", appPath("/client/acme/docs", "settings"), "settings");
eq("a non-string target is returned as-is", appPath("/client/acme/docs", undefined), undefined);
// A workspace slugged like a route segment must not confuse the prefix test.
eq("a slug that looks like a route still resolves",
  appPath("/client/companies/pipeline", "/companies/5"), "/client/companies/companies/5");

console.log(failed ? `\n${failed} FAILED` : "\nall client-url cases pass");
process.exit(failed ? 1 : 0);
