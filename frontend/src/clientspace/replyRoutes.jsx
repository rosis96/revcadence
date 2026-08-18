// Reply Management, mounted at the client's base.
//
// These are the operator's screens — the same five components the operator rail
// opens at `/reply/*`, not client-flavoured rewrites of them. When a client says
// "the Inbox is doing something strange", both people are looking at the same
// file. Where the two sides differ, they differ by a field inside one component
// (see the `is_master` branches in ReplySetup), never by a fork.
//
// The route tree is separate from `routes.jsx` on purpose: that one is mounted
// at BOTH `/client-space` and the client base, so anything added there appears
// in the operator's Client Space module too. Reply Management already has its
// own module in the operator rail at `/reply/*`; a second copy under Client
// Space would be two paths to one screen and two places to fix a link.
//
// Access is not decided here. The server refuses what the client may not have,
// per endpoint — this only decides what the URL resolves to.
import { lazy, Suspense } from "react";
import { Outlet, Route } from "react-router-dom";

const ReplyDashboard = lazy(() => import("../pages/ReplyDashboard"));
const ReplyInbox = lazy(() => import("../pages/ReplyInbox"));
const ReplyProcessing = lazy(() => import("../pages/ReplyProcessing"));
const ReplyTest = lazy(() => import("../pages/ReplyTest"));
const ReplySetup = lazy(() => import("../pages/ReplySetup"));
const ReplySettings = lazy(() => import("../pages/ReplySettings"));
const ReplyWorkspaces = lazy(() => import("../pages/ReplyWorkspaces"));

const Lazy = ({ children }) => (
  <Suspense fallback={<div className="center" style={{ minHeight: "40vh" }}><div className="spinner" /></div>}>
    {children}
  </Suspense>
);

// `cs-body` is the client shell's content padding — the same wrapper
// ClientSpaceFrame puts around a Client Space screen. Reply Management does not
// use the frame itself: the frame's marker counts internal-only *pages* and
// offers Preview as client, and neither statement is true of an inbox.
function ReplyLayout() {
  return <div className="cs-body"><Outlet /></div>;
}

// Returns one <Route> subtree. Callers spread it into their own <Routes>.
export default function replyRoutes(base) {
  return (
    <Route key={`${base}/reply`} path={`${base}/reply`} element={<ReplyLayout />}>
      <Route index element={<Lazy><ReplyDashboard /></Lazy>} />
      <Route path="inbox" element={<Lazy><ReplyInbox /></Lazy>} />
      <Route path="processing" element={<Lazy><ReplyProcessing /></Lazy>} />
      <Route path="test" element={<Lazy><ReplyTest /></Lazy>} />
      <Route path="setup" element={<Lazy><ReplySetup /></Lazy>} />
      <Route path="settings" element={<Lazy><ReplySettings /></Lazy>} />
      <Route path="channels" element={<Lazy><ReplyWorkspaces /></Lazy>} />
    </Route>
  );
}
