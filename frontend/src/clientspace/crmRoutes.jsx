// CRM, mounted at the client's base.
//
// The operator's screens at a second base, same as outboundRoutes and
// replyRoutes. Unlike those two, CRM is not one URL segment — it is a dozen
// (`/pipeline`, `/companies`, `/deals`, `/invoices`, …) — so these are mounted
// as siblings that MIRROR the operator paths under the workspace slug:
//
//   operator  /companies/5/profile
//   client    /w/acme/companies/5/profile
//
// Mirroring rather than inventing a `/crm/` prefix is what lets one helper fix
// every absolute link on these screens: `useAppPath()` prepends the base and
// changes nothing else. See clientUrl.js::appPath.
//
// One collision, and it is a real one. Client Space already owns `sequences` —
// that is `LiveSequences`, the read-only mirror of what Instantly/Bison actually
// sends. The CRM item of the same name is the *editor* over our own
// `email_sequences` tables. Two different screens, one name, and only one can
// have the slug. The mirror keeps it, because it is what a client means by "what
// is going out"; the editor is mounted one level down at `sequences/builder`.
import { lazy, Suspense } from "react";
import { Outlet, Route } from "react-router-dom";
import DocsRoute from "../docs/DocsRoute";

const Pipeline = lazy(() => import("../pages/Pipeline"));
const Reports = lazy(() => import("../pages/Reports"));
const DealRecord = lazy(() => import("../pages/DealRecord"));
const RevenueInbox = lazy(() => import("../pages/RevenueInbox"));
const MailboxConnect = lazy(() => import("../pages/MailboxConnect"));
const Companies = lazy(() => import("../pages/Companies"));
const CompanyDetail = lazy(() => import("../pages/CompanyDetail"));
const ClientProfile = lazy(() => import("../pages/ClientProfile"));
const Clients = lazy(() => import("../pages/Clients"));
const Contacts = lazy(() => import("../pages/Contacts"));
const ContactDetail = lazy(() => import("../pages/ContactDetail"));
const Sequences = lazy(() => import("../pages/Sequences"));
const Blueprints = lazy(() => import("../pages/Blueprints"));
const BlueprintDetail = lazy(() => import("../pages/BlueprintDetail"));
const AgreementDetail = lazy(() => import("../pages/AgreementDetail"));
const Invoices = lazy(() => import("../pages/Invoices"));
const InvoiceDetail = lazy(() => import("../pages/InvoiceDetail"));
const Onboarding = lazy(() => import("../pages/Onboarding"));

const Lazy = ({ children }) => (
  <Suspense fallback={<div className="center" style={{ minHeight: "40vh" }}><div className="spinner" /></div>}>
    {children}
  </Suspense>
);

// `cs-body` is the client shell's content padding. CRM does not use
// ClientSpaceFrame: its marker counts internal-only *pages* and offers Preview
// as client, and neither statement is true of a pipeline board.
function CrmLayout() {
  return <div className="cs-body"><Outlet /></div>;
}

// [path, element] pairs, so the layout wrapper is declared once.
const SCREENS = [
  ["pipeline", <Pipeline />],
  ["reports", <Reports />],
  ["deals/:id", <DealRecord />],
  ["revenue-inbox", <RevenueInbox />],
  ["settings/email", <MailboxConnect />],
  ["companies", <Companies />],
  ["companies/:id", <CompanyDetail />],
  ["companies/:id/profile", <ClientProfile />],
  ["clients", <Clients />],
  ["contacts", <Contacts />],
  ["contacts/:id", <ContactDetail />],
  ["sequences/builder", <Sequences />],
  ["blueprints", <Blueprints />],
  ["blueprints/:id", <BlueprintDetail />],
  ["agreements/:id", <AgreementDetail />],
  ["invoices", <Invoices />],
  ["invoices/:id", <InvoiceDetail />],
  ["onboarding", <Onboarding />],
];

export default function crmRoutes(base) {
  return [
    <Route key={`${base}/crm`} element={<CrmLayout />}>
      {SCREENS.map(([path, element]) => (
        <Route key={path} path={`${base}/${path}`} element={<Lazy>{element}</Lazy>} />
      ))}
    </Route>,
    // Shared Documents is the same component Client Space mounts at `docs`. The
    // operator reaches it from CRM at `/workspace/docs`, so the client's CRM item
    // points here rather than jumping them into another module's copy —
    // `docsBaseFrom` already reads whichever base a page was opened at.
    <Route key={`${base}/workspace/docs`} element={<CrmLayout />}>
      <Route path={`${base}/workspace/docs`} element={<DocsRoute />} />
      <Route path={`${base}/workspace/docs/:pageId`} element={<DocsRoute />} />
    </Route>,
  ];
}
