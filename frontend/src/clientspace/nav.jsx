// The Client Space navigation — defined once, rendered by both sidebars.
//
// The admin sidebar and the client's own sidebar must show the same items in the
// same order, because the support call that starts "I can't find it" is only
// answerable if both people are looking at the same list. Two hand-kept copies
// would drift within a month, so there is one list and two base paths:
// `/client-space` for us, `/w` for them.
//
// What is deliberately NOT here: templates. Page, sequence and plan starting
// points are org-level assets we own, and they live under SYSTEM. Putting one
// inside a client-scoped module implies it belongs to that client, which is the
// road that ends with one client's content in another's workspace. Inside this
// module, "Onboarding Form" means send the form to this client and read their
// answers — nothing more.
//
// Client Space is not uniformly client-visible. It has a shared zone and an
// internal one, and a group marked `internal` is ours: the client's sidebar does
// not render those items at all, and the server refuses them the URL. This is
// the same rule an internal page inside Docs already follows — one concept, two
// places it applies, not two mechanisms to keep in agreement.
import {
  Columns2, Gem, Grid3x3, Hourglass, Mail, Rows3, ClipboardList, ShieldCheck, Sparkles,
} from "lucide-react";

export const ADMIN_BASE = "/client-space";

// The client-side URL arithmetic lives in its own dependency-free module so it
// can be tested without a browser. Re-exported here because this file is where
// every screen already looks for a base path.
export {
  CLIENT_BASE, CLIENT_ROUTE_BASE, clientBase, clientBaseFrom, clientRedirectTarget, slugFromPath,
} from "./clientUrl";
import { CLIENT_BASE, clientBaseFrom } from "./clientUrl";

// [slug, label, icon]. An empty slug is the module's landing screen.
// Group `null` renders ungrouped at the top, above the first group label.
// A group's fourth position — `internal` — hides the whole group from clients.
export const CLIENT_SPACE_GROUPS = [
  [null, [
    ["", "Overview", Gem],
    ["plan", "Launch Plan", Hourglass],
  ]],
  ["Shared with client", [
    ["docs", "Docs", Rows3],
    ["whiteboards", "Whiteboards", Columns2],
    ["sequences", "Email Sequences", Mail],
    ["boards", "Boards & Tables", Grid3x3],
    ["library", "Library", Sparkles],
  ]],
  ["Setup", [
    ["onboarding-form", "Onboarding Form", ClipboardList],
    ["sharing", "Sharing & Access", ShieldCheck],
  ], { internal: true }],
];

export const INTERNAL_SLUGS = new Set(
  CLIENT_SPACE_GROUPS.flatMap(([, items, meta]) =>
    (meta?.internal ? items.map(([slug]) => slug) : [])),
);

export const path = (base, slug) => (slug ? `${base}/${slug}` : base);

// Resolve any `[group, items, meta]` list against a base path. Extracted so the
// client's second module (Reply Management, see modules.jsx) renders through the
// same function rather than a copy of it — the drift this file exists to prevent
// applies just as much to a second module as to a second sidebar.
export const groupsFor = (source, base, { internal = true } = {}) =>
  source
    .filter(([, , meta]) => internal || !meta?.internal)
    .map(([group, items]) => [
      group,
      items.map(([slug, label, icon]) => [path(base, slug), label, icon]),
    ]);

// [label, [[to, label, icon], ...]] for a given base — the shape both sidebars
// render. `internal: false` drops our own groups entirely, which is what the
// client's rail asks for: not disabled items, not greyed items — absent ones.
export const navGroups = (base, opts) => groupsFor(CLIENT_SPACE_GROUPS, base, opts);

// The module base for the shell you are in. The client side is workspace-scoped
// and ours is not, so this takes the pathname: dropping the slug here is how a
// client-side link ends up at `/w/docs`, which matches no route.
export const moduleBase = (pathname, isClient) => (isClient ? clientBaseFrom(pathname) : ADMIN_BASE);

// Docs and Whiteboards open a page by id; both shells need the same prefix.
export const docsBase = (pathname, isClient) => path(moduleBase(pathname, isClient), "docs");

// The docs screen is mounted under more than one base — /client-space/docs, /w/docs,
// and CRM's long-standing /workspace/docs. Reading the base off the URL the screen
// was actually opened at keeps an in-page link from teleporting the reader into
// another module's copy of it.
export const docsBaseFrom = (pathname, isClient) =>
  (pathname.includes("/docs")
    ? pathname.slice(0, pathname.indexOf("/docs") + "/docs".length)
    : docsBase(pathname, isClient));
