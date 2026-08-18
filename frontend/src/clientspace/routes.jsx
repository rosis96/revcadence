// The Client Space route tree, defined once and mounted at two bases:
// `/client-space` inside the admin shell, `/w` inside the client's own shell.
// One definition means an operator and a client are always looking at the same
// screen when they are looking at the same item.
//
// A layout route carries the frame, so the marker and the Preview-as-client
// toggle stay mounted while you move between screens inside the module — the
// preview does not silently switch itself off when you click Docs.
import { lazy, Suspense } from "react";
import { Outlet, Route } from "react-router-dom";
import ClientSpaceFrame from "./frame";
import DocsRoute from "../docs/DocsRoute";
// One canvas per workspace, so this route opens a board rather than a list of them.
import Whiteboard from "../docs/Whiteboard";
import Overview from "./pages/Overview";
import LaunchPlan from "./pages/LaunchPlan";
import Boards from "./pages/Boards";
import OnboardingForm from "./pages/OnboardingForm";
import Sharing from "./pages/Sharing";

const FormFill = lazy(() => import("../forms/FormPage"));

// Read-only, and mirrored from the sending platform rather than from our own
// email_sequences tables — the client is a reader here, so the editor screen is
// not mounted at this base at all. See pages/LiveSequences.jsx for why.
const LiveSequences = lazy(() => import("../pages/LiveSequences"));
// Inbound capture: the client's own form URL and the leads it brought in. Only
// mounted at the client's base — see the note by the route below.
const InboundVisitors = lazy(() => import("../pages/InboundVisitors"));
const Library = lazy(() => import("../client/pages/Library"));
const Lazy = ({ children }) => (
  <Suspense fallback={<div className="center" style={{ minHeight: "40vh" }}><div className="spinner" /></div>}>
    {children}
  </Suspense>
);

function ClientSpaceLayout() {
  return <ClientSpaceFrame><Outlet /></ClientSpaceFrame>;
}

// Returns one <Route> subtree. Callers spread it into their own <Routes>.
//
// `internal` is false for the client's own base: the Setup screens are ours, so
// they are not mounted there at all. Leaving them mounted but hidden from the
// rail would make the sidebar the security boundary, which it is not — the
// server refuses them too, and this keeps the three in agreement.
export default function clientSpaceRoutes(base, { internal = true } = {}) {
  return (
    <Route key={base} path={base} element={<ClientSpaceLayout />}>
      <Route index element={<Overview />} />
      <Route path="plan" element={<LaunchPlan />} />
      <Route path="docs" element={<DocsRoute />} />
      <Route path="docs/:pageId" element={<DocsRoute />} />
      <Route path="whiteboards" element={<Whiteboard />} />
      <Route path="sequences" element={<Lazy><LiveSequences /></Lazy>} />
      <Route path="boards" element={<Boards />} />
      <Route path="boards/:dataset" element={<Boards />} />
      <Route path="library" element={<Lazy><Library /></Lazy>} />
      {/* The client's own side of the onboarding form — the same page the
          emailed link opens, resolved from the session instead of a token. */}
      <Route path="form" element={<Lazy><FormFill /></Lazy>} />
      {internal && <Route path="onboarding-form" element={<OnboardingForm />} />}
      {internal && <Route path="sharing" element={<Sharing />} />}
      {/* The mirror of the two above: ours-only becomes theirs-only. The operator
          reaches this same screen from the Inbound module at `/inbound`, so
          mounting it here as well would give them two URLs for one page. */}
      {!internal && <Route path="visitors" element={<Lazy><InboundVisitors /></Lazy>} />}
    </Route>
  );
}
