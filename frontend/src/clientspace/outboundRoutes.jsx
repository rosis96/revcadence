// Outbound, mounted at the client's base.
//
// The operator's own screens at a second base — same reasoning as replyRoutes,
// and the same reason it is not folded into routes.jsx: Outbound already has a
// module in the operator rail at `/enrichment/*`, so putting a second copy under
// Client Space would be two paths to one screen.
//
// EnrichConfig is one component with four tabs, and it is mounted four times
// here exactly as App.jsx mounts it — the tab is the route, so a client can
// bookmark Formats rather than landing on Profile and clicking.
import { lazy, Suspense } from "react";
import { Outlet, Route } from "react-router-dom";

const EnrichLists = lazy(() => import("../pages/EnrichLists"));
const EnrichListDetail = lazy(() => import("../pages/EnrichListDetail"));
const EnrichDatabase = lazy(() => import("../pages/EnrichDatabase"));
const EnrichConfig = lazy(() => import("../pages/EnrichConfig"));
const BrainChat = lazy(() => import("../pages/BrainChat"));
const TrainingBridge = lazy(() => import("../pages/TrainingBridge"));

const Lazy = ({ children }) => (
  <Suspense fallback={<div className="center" style={{ minHeight: "40vh" }}><div className="spinner" /></div>}>
    {children}
  </Suspense>
);

// `cs-body` is the client shell's content padding. Outbound does not use
// ClientSpaceFrame: its marker counts internal-only *pages* and offers Preview
// as client, and neither statement is true of a lead list.
function OutboundLayout() {
  return <div className="cs-body"><Outlet /></div>;
}

export default function outboundRoutes(base) {
  return (
    <Route key={`${base}/enrichment`} path={`${base}/enrichment`} element={<OutboundLayout />}>
      <Route index element={<Lazy><EnrichLists /></Lazy>} />
      <Route path="lists/:id" element={<Lazy><EnrichListDetail /></Lazy>} />
      <Route path="database" element={<Lazy><EnrichDatabase /></Lazy>} />
      <Route path="profile" element={<Lazy><EnrichConfig tab="profile" /></Lazy>} />
      <Route path="brain" element={<Lazy><BrainChat /></Lazy>} />
      <Route path="icp" element={<Lazy><EnrichConfig tab="icp" /></Lazy>} />
      <Route path="formats" element={<Lazy><EnrichConfig tab="formats" /></Lazy>} />
      <Route path="rules" element={<Lazy><EnrichConfig tab="rules" /></Lazy>} />
      <Route path="training" element={<Lazy><TrainingBridge /></Lazy>} />
    </Route>
  );
}
