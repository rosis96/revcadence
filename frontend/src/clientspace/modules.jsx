// The client sidebar's modules — the same switcher the operator rail has.
//
// Until now the client had exactly one module, so the rail could be a flat list
// and the switcher would have been a dropdown with one entry. Reply Management
// is the second, and it is not a section of Client Space: it is the client's own
// operational console, with its own screens and its own Build group.
//
// The shape here is deliberately the operator's `MODES` shape from App.jsx —
// `label` plus a `[group, items, meta]` list — because the two rails must stay
// readable side by side. What differs is the base: ours is a fixed path, theirs
// carries the workspace slug, so every item here is a *slug relative to the
// module base* and `groupsFor` resolves it. See nav.jsx for that arithmetic.
//
// Reply Settings is here, and it is the one screen that had to change shape to
// get here: it wrote org-wide `AppSetting` rows, so a client editing the model or
// the API key would have edited them for every other client. It is now scoped by
// the caller — the org row for a master on "All workspaces", the workspace's own
// reply space for everyone else. Two of its values (the review webhook and the
// Bison trigger tags) still have no reader anywhere in the app; the screen labels
// them as saved-but-inert rather than implying otherwise.
//
// What is NOT here, and why:
//   · Master Dashboard, Forms, Activity, Jobs, Developers, Admin, Billing — the
//     operator's org-level tools.
//
// Adding a module here adds it to the client's rail. It does NOT grant access:
// the server decides that per endpoint, and the two have to be changed together.
import {
  AlignLeft, BarChart3, Briefcase, Building2, CheckCheck, CircleUser,
  ClipboardList, Contact, Database, FileText, Flag, FlaskConical, Globe, Inbox,
  LayoutGrid, ListChecks, Mail, Radar, Rows3, Settings2, ShieldCheck,
  SlidersHorizontal, Sparkles, Target,
} from "lucide-react";
import { CLIENT_SPACE_GROUPS, groupsFor } from "./nav";

// Reply Management, client side. Mirrors the operator's module: the four
// operational screens ungrouped at the top, then Build, exactly as the operator
// rail renders `MODES.reply` followed by `BUILD_BY_MODE.reply`.
export const REPLY_GROUPS = [
  [null, [
    ["reply", "Dashboard", LayoutGrid],
    ["reply/inbox", "Inbox", Inbox],
    ["reply/processing", "Processing", Radar],
    ["reply/test", "Test Thread", FlaskConical],
  ]],
  ["Build · Reply Management", [
    ["reply/setup", "Reply Setup", Settings2],
    ["reply/settings", "Reply Settings", SlidersHorizontal],
    ["reply/channels", "Extra Channels", Flag],
  ]],
];

// Outbound, client side. Same split as the operator's rail: the two operational
// screens from `MODES.outbound`, then `BUILD_BY_MODE.outbound` as the Build
// group — Client Profile through Workspace Training, in that order.
//
// Workspace Training is here and it is the sharpest tool on the rail: an apply
// rewrites the whole brain in one go. It earns its place because every safety it
// needs already exists — a revision snapshot is taken before the write, rollback
// restores it, and evaluation refuses to spend without an explicit confirm. It
// stopped being owner/admin-only server-side to get here; see
// `_training_workspace` in routers/enrich_lists.py for what still guards it.
export const OUTBOUND_GROUPS = [
  [null, [
    ["enrichment", "Lists", ListChecks],
    ["enrichment/database", "Database", Database],
  ]],
  ["Build · Outbound", [
    ["enrichment/profile", "Client Profile", CircleUser],
    ["enrichment/brain", "Ask the Brain", Sparkles],
    ["enrichment/icp", "ICP / Non-ICP", Target],
    ["enrichment/formats", "Formats", AlignLeft],
    ["enrichment/rules", "Rules", CheckCheck],
    ["enrichment/training", "Workspace Training", ShieldCheck],
  ]],
];

// CRM, client side — the operator's module in the operator's order, from
// Pipeline through Onboarding, then `BUILD_BY_MODE.crm` as the Build group.
//
// Two entries need explaining, because both look like duplicates and only one is:
//
//   · Shared Documents opens the SAME component as Client Space's Docs. That is
//     true in the operator rail too — one screen, two ways in — so it is copied
//     rather than corrected.
//   · Email Sequences is NOT the same screen as Client Space's. This is the
//     editor over our `email_sequences` tables; that one is `LiveSequences`, the
//     read-only mirror of what the sending platform is actually going to send.
//     They collide on the slug, so the mirror keeps `sequences` and the editor
//     lives at `sequences/builder`. See crmRoutes.jsx.
//
// Client Profile appears here AND in Build · Outbound. That is the operator's
// arrangement too: `BUILD_BY_MODE` lists it under both `outbound` and `crm`,
// because it is the one screen both jobs start from.
export const CRM_GROUPS = [
  [null, [
    ["pipeline", "Pipeline", Rows3],
    ["reports", "Reports", BarChart3],
    ["revenue-inbox", "Revenue Inbox", Inbox],
    ["workspace/docs", "Shared Documents", FileText],
    ["sequences/builder", "Email Sequences", Mail],
    ["blueprints", "Blueprints & Agreements", FileText],
    ["invoices", "Invoices", ClipboardList],
    ["clients", "Clients", Briefcase],
    ["companies", "Companies", Building2],
    ["contacts", "Contacts", Contact],
    ["onboarding", "Onboarding", ClipboardList],
  ]],
  ["Build · CRM", [
    ["settings/email", "Email Accounts", Mail],
    ["enrichment/profile", "Client Profile", CircleUser],
  ]],
];

// Website Visitors joins Client Space rather than getting a module of its own:
// one screen does not earn a switcher entry, and it is not Outbound — an inbound
// form-fill is the opposite direction of travel. It sits next to Boards & Tables
// because both answer "what arrived", one from the campaigns and one from the
// website.
//
// It is added HERE and not in nav.jsx's `CLIENT_SPACE_GROUPS` because that list
// is also the operator's Client Space rail, and the operator already opens this
// screen from Inbound at `/inbound`. A second entry there would be two paths to
// one screen and two places to fix a link.
const SHARED_GROUP = "Shared with client";
const VISITORS_ITEM = ["visitors", "Website Visitors", Globe];

const withVisitors = (items) => {
  const at = items.findIndex(([slug]) => slug === "boards");
  const next = [...items];
  next.splice(at < 0 ? next.length : at + 1, 0, VISITORS_ITEM);
  return next;
};

const CLIENT_SPACE_CLIENT_GROUPS = CLIENT_SPACE_GROUPS.map(
  ([group, items, meta]) => (group === SHARED_GROUP ? [group, withVisitors(items), meta]
    : [group, items, meta]));

// Ungrouped Client Space items keep their landing-screen behaviour: an empty
// slug is the module base itself.
//
// Order matters — this is the order the switcher lists them in, and Client Space
// stays first because it is where a client lands.
export const CLIENT_MODULES = {
  client_space: { label: "Client Space", groups: CLIENT_SPACE_CLIENT_GROUPS, home: "" },
  outbound: { label: "Outbound", groups: OUTBOUND_GROUPS, home: "enrichment" },
  reply: { label: "Reply Management", groups: REPLY_GROUPS, home: "reply" },
  crm: { label: "CRM", groups: CRM_GROUPS, home: "pipeline" },
};

// CRM is the one module whose screens are not all under its home segment — it
// spans `/pipeline`, `/companies`, `/deals` and nine more. `moduleForPath` walks
// homes, so it needs the full set to recognise a CRM screen as CRM rather than
// falling through to Client Space and lighting the wrong rail.
//
// `enrichment/profile` is deliberately absent: it belongs to Outbound, which
// owns that segment. Opening Client Profile from CRM's Build group therefore
// switches the rail to Outbound — the same thing the operator's sidebar does,
// for the same reason.
const CRM_SEGMENTS = [
  "pipeline", "reports", "revenue-inbox", "workspace/docs", "sequences/builder",
  "blueprints", "invoices", "clients", "companies", "contacts", "onboarding",
  "deals", "agreements", "settings/email",
];

export const MODULE_KEYS = Object.keys(CLIENT_MODULES);

// Which module a path belongs to. Longest prefix wins, so `reply/inbox` picks
// Reply Management rather than falling through to the default. Client Space is
// the default precisely because it owns the module base itself — every path that
// is not claimed by another module is one of its screens.
const owns = (tail, segment) => tail === segment || tail.startsWith(`${segment}/`);

export const moduleForPath = (pathname, base) => {
  const tail = (pathname || "").startsWith(base) ? pathname.slice(base.length).replace(/^\//, "") : "";
  if (CRM_SEGMENTS.some((segment) => owns(tail, segment))) return "crm";
  const hit = MODULE_KEYS.filter((key) => key !== "client_space" && key !== "crm")
    .find((key) => owns(tail, CLIENT_MODULES[key].home));
  return hit || "client_space";
};

// A module's base for whatever URL a screen was opened at: `/reply` in the
// operator shell, `/w/<slug>/reply` in the client's. Screens inside a module
// link through this rather than writing `/reply/...`, or a client clicking
// through to their own Inbox lands on the operator path, matches no route and
// gets bounced to their Overview by the catch-all.
//
// Last occurrence, not first, so a workspace whose slug is literally "reply" or
// "enrichment" resolves to its own base instead of swallowing the segment.
const sectionBase = (pathname, segment) => {
  const at = (pathname || "").lastIndexOf(segment);
  return at >= 0 ? pathname.slice(0, at + segment.length) : segment;
};

export const replyBase = (pathname) => sectionBase(pathname, "/reply");
export const enrichBase = (pathname) => sectionBase(pathname, "/enrichment");

// `[label, [[to, label, icon], ...]]` for one module against the client's base.
export const moduleNav = (key, base, opts) =>
  groupsFor(CLIENT_MODULES[key]?.groups || [], base, opts);

// Where switching to a module should land. Its first ungrouped item if it has
// one, else its first item of any kind — the operator switcher's rule.
export const moduleHome = (key, base, opts) => {
  const groups = moduleNav(key, base, opts);
  const ungrouped = groups.find(([group]) => group === null);
  return (ungrouped || groups[0])?.[1]?.[0]?.[0] || base;
};
