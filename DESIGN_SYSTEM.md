# Prompt: the RevCadence Design System — one system, then every page

**You are working in `revcadence/frontend`** (React 18 + Vite + react-router + lucide-react,
plain CSS in `src/styles.css`, shared components in `src/components.jsx`).

We are NOT redesigning individual pages anymore. We are building ONE premium design
system and then migrating every page onto it, in a fixed order. Apollo.io is the UX
reference for philosophy, not for cloning. The product should feel like Linear, Apollo,
Vercel, Notion, Stripe: calm, never busy, never colorful, never an admin panel. Every
screen must feel like the same product.

**Hard rule: do not migrate ANY page until Phase 0 (the system itself) is complete.**
If pages are redesigned independently we get another inconsistent UI. Build the
foundation, then migrate in the order in Part 4.

---

## Part 0 — Current state (verified against the code, build on it, don't restart)

- `src/styles.css` (319 lines) already defines tokens: `--accent:#635BFF`, `--bg:#F6F7FB`,
  `--card`, `--border:#E6E9F0`, `--text:#101828`, `--muted`, ok/warn/bad/info, radius 12,
  two shadows. KEEP these variable names; evolve values where this spec differs.
- `src/components.jsx` exports: useApi, Spinner, ErrorBox, Empty, Badge, StatusBadge,
  Metric, PageHeader, SkeletonRows, Drawer, Modal, Timeline. Extend this file (or split
  into `src/ui/` if it grows past ~600 lines); never fork per-page variants.
- **Delta 1:** the sidebar is currently DARK (`--sidebar-bg:#0D1324`). The spec below
  makes it LIGHT. No dark sections anywhere in the product.
- **Delta 2:** there is NO shared Table component; pages hand-roll tables. The Table is
  the single most important deliverable of Phase 0.
- Existing routes to migrate (from `App.jsx`): `/` dashboard, `/pipeline`, `/companies(+id,profile)`,
  `/clients`, `/contacts`, `/enrichment(+lists/:id,database,profile,icp,formats,rules,companies)`,
  `/reply(+inbox,processing,test,settings,setup,workspaces)`, `/inbound`, `/blueprints(+:id)`,
  plus jobs/settings/admin/activity.

Allowed new dependencies (only these two): `@tanstack/react-table` (headless table
logic) and `@tanstack/react-virtual` (virtualized rows). Everything else is hand-built.

---

## Part 1 — Design tokens (Phase 0a: update `styles.css` `:root`)

Theme: white and light gray, soft borders, very subtle shadows, rounded corners
(10-12px), lots of whitespace. Avoid: heavy cards, dark sections, gradients (the only
gradient allowed is the tiny logo mark), thick borders, decorative color.

```css
:root {
  /* surfaces */
  --bg: #FAFAFB;            /* app background */
  --card: #FFFFFF;
  --border: #E9EAEE;        /* 1px only, never thicker */
  --border-strong: #DCDEE4; /* hover/focus borders */

  /* text */
  --text: #18181B;
  --muted: #6B7280;
  --muted2: #9CA3AF;

  /* color = meaning only */
  --primary: #2E90FA;       /* primary actions (blue) */
  --ok: #12B76A;            /* success */
  --warn: #F79009;          /* warning */
  --bad: #F04438;           /* error */
  --brand: #635BFF;         /* purple: brand accent ONLY (logo, active nav tick,
                               small highlights). Never for buttons or big surfaces. */

  /* geometry */
  --radius: 10px; --radius-lg: 12px;
  --shadow: 0 1px 2px rgba(16,24,40,.05);
  --shadow-pop: 0 8px 24px rgba(16,24,40,.10);   /* drawers, modals, popovers only */

  /* spacing scale: use ONLY these */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 20px; --s6: 24px; --s8: 32px; --s10: 40px;

  --sidebar-w: 232px; --header-h: 56px;
}
```

Typography (Inter, already loaded): page title 20px/600; page description 13.5px
`--muted` directly under the title; body 14px; table cells 13.5px; section labels 11px
uppercase 0.06em `--muted2`; NO text larger than 22px anywhere in the app. Clear
hierarchy comes from weight and spacing, not size.

---

## Part 2 — Layout & navigation (Phase 0b)

Exactly ONE navigation system. No duplicated nav, no per-page tab bars pretending to be nav.

- **Left sidebar, LIGHT** (`#FFFFFF`, right border `--border`): logo mark + wordmark;
  workspace switcher (existing `.ws-switch`, restyled light); grouped nav with 11px
  uppercase group labels (Prospect & Enrich / Engage / Win & Close / Tools) exactly like
  the current groups but light; icons 18px lucide, 40px row height, active = `#F4F4F6`
  bg + 3px `--brand` left tick + `--text` color. Collapse to icons at <1100px.
- **Top bar (56px, white, bottom border):** global search input (centered, max 560px,
  placeholder "Search or ask… ⌘K"), notifications bell, profile menu. Nothing else.
- **Page shell:** every page = `PageHeader` (title, description, right-side actions) +
  optional breadcrumb (only on detail pages: "Companies / Acme") + content. Max content
  width 1440px, `--s6` page padding. No page invents its own layout.

**Global search / command palette (⌘K):** one `CommandPalette` component. Searches
companies, contacts, deals, replies, blueprints, agreements, invoices, meetings, and
nav actions ("Go to Enrichment"). Backend: one `GET /api/search?q=` endpoint doing
per-entity ILIKE lookups (10 per type) returning `{type, id, title, subtitle, href}`.
Group results by type, arrow-key navigation, Enter to open. Debounce 150ms.

---

## Part 3 — Component library (Phase 0c: all in `src/ui/`, re-exported from `components.jsx`)

Build/upgrade these. One implementation each, used everywhere:

Button (primary=blue solid / secondary=white+border / ghost / danger; sm+md; loading
state), Input, Select, Textarea, SearchInput (with icon + ⌘K hint variant), Tabs
(underline style, URL-synced), Badge + StatusPill (existing tones: ok/warn/bad/info/
neutral; pill = dot + label), Avatar (initials, brand-tinted bg), Card (padding --s5,
radius-lg, shadow; NEVER nested cards), StatCard (label, value, delta arrow), Drawer
(right, 480px, existing), Modal (existing; use sparingly, prefer Drawer), Toast
(bottom-right, auto-dismiss), Tooltip, EmptyState (icon, one sentence, one action),
Skeleton (existing SkeletonRows + block variant), Pagination, FilterPanel (left rail,
collapsible groups, checkbox/chip filters, active-count badges, Clear all), Timeline
(existing), ActivityFeed, CommandPalette, PageHeader (existing, add actions slot +
breadcrumbs), ConfirmDialog.

### THE Table (the centerpiece — Apollo's biggest strength)

One `<DataTable>` component (TanStack Table headless + our markup) used by EVERY list
in the product. Features, all standard: instant client search; column sorting;
filtering (wired to FilterPanel); column chooser (show/hide, persisted per view in
localStorage); saved views (name + filters + columns + sort, persisted server-side per
user); bulk actions (checkbox column, sticky action bar appears at bottom when >0
selected); sticky header; resizable columns; pagination AND infinite scroll modes
(virtualized via @tanstack/react-virtual when >200 rows); loading skeletons; designed
empty state; row click → Drawer or detail route (consistent per entity: list rows open
Drawers for quick view, "Open" goes to the full page).

Visual: 13.5px cells, 44px rows, header 12px/500 `--muted` uppercase-free, row hover
`#FAFAFB`, no zebra, no vertical gridlines, 1px row separators only.

---

## Part 4 — Migration order (one page per step; do NOT skip ahead)

1. **Global layout + navigation** (light sidebar, top bar, ⌘K palette, page shell).
2. **Dashboard `/`** — not widgets: a command center like Apollo Home. Sections:
   Today's meetings, Tasks, Recent activity, Revenue + pipeline stat row, Recent
   clients, Recent replies, Blueprints awaiting action, Agreements awaiting signature,
   Invoices awaiting payment. Each section = flat list rows with "View all →", max 5
   rows, everything clickable, everything also reachable from ⌘K.
3. **CRM** (`/pipeline`, `/companies`, `/contacts`, deals) — feel: HubSpot + Apollo.
   Companies/Contacts/Deals/Meetings/Activities/Tasks interconnected. Company detail =
   ONE page with tabs: Overview / Contacts / Deals / Blueprints / Agreements / Invoices
   / Emails / Activity Timeline / Client Profile. Never separate pages unnecessarily.
4. **Lead Enrichment** (`/enrichment/*`) — complete redesign, Apollo Find-People UX:
   left FilterPanel (live counts, instant apply, no modals), middle DataTable, top bar
   with Search / Save search / Import / Export / Columns / Views. Every filter updates
   the table instantly.
5. **Reply Management** (`/reply/*`) — inbox feels like Gmail: conversation list left,
   message thread center, AI panel right (draft, intent, confidence, actions). Status
   tabs: Needs Review / Replied / Meeting Booked / Stopped / Pinned / Draft. Instant
   search + filters.
6. **Blueprint** (`/blueprints/:id`) — editor feels like Notion: large calm editor,
   auto-save with "Saved" indicator, version history, comments, publishing status,
   Preview, Share. (The client-facing render stays in the portals service; this is the
   internal editor/workspace.)
7. **Agreement** — same Notion feel: editor with live preview beside it, signing
   timeline, version history, status, Download PDF, Client view link.
8. **Invoice** — professional accounting UI: invoice list + detail, payments, status
   pills, download, email, timeline. No clutter.
9. **Settings / Admin / Jobs** — same shell, cards + tables, nothing special.

Each step ends with: `npm run build` green, the page using ONLY system components
(zero page-local CSS beyond layout tweaks), and visual QA against the consistency
rules below.

---

## Part 5 — Consistency & performance rules (enforced on every PR/step)

- Same spacing scale, same table, same filters, same buttons, same inputs, same cards,
  same typography, same PageHeader, same breadcrumbs, same loading skeletons, same
  empty states. A page that invents its own version of any of these is a bug.
- Color only for meaning: blue=action, green=success, orange=warning, red=error,
  purple=brand accent only. Gray everything else.
- No full page reloads; optimistic updates on status changes (update UI, rollback on
  error + toast); virtualize tables >200 rows; lazy-load routes (`React.lazy` per page);
  skeletons within 100ms, never spinners on whole pages.
- Desktop-first; tablet usable (sidebar collapses); mobile secondary (no breakage,
  no optimization work).
- Every interactive element keyboard-reachable; visible focus rings (3px primary at
  14% opacity, already the pattern).

## Definition of done (Phase 0 before ANY page migration)

1. Tokens updated; light sidebar shell + top bar + ⌘K palette working.
2. `src/ui/` component library complete, including the full DataTable.
3. A `/dev/kitchen-sink` route (dev-only) rendering every component in every state,
   used for visual QA.
4. Then, and only then, migrate pages in the Part 4 order, one at a time.

The goal: someone logging into RevCadence for the first time immediately feels a
premium B2B SaaS platform at the level of Apollo, HubSpot, Linear, or Vercel. Not
because it looks copied, but because it has the same polish, consistency, and
usability everywhere.
