// Lazy entry point for the docs screen, in its own module so both shells can
// import it without App and ClientShell importing each other.
//
// Lazy because this route pulls in TipTap/ProseMirror, which nothing else needs.
// The fallback is the empty document frame rather than a spinner — the shell
// stays put and only the body fills in.
import { lazy, Suspense } from "react";

const WorkspaceDocs = lazy(() => import("../pages/WorkspaceDocs"));

export default function DocsRoute() {
  return (
    <Suspense fallback={<div className="doc-screen"><div className="doc-body" /></div>}>
      <WorkspaceDocs />
    </Suspense>
  );
}
