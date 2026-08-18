// `useAppPath()` — the hook every screen mounted at two bases links through.
//
// The arithmetic lives in clientUrl.js, dependency-free and covered by
// `npm run check`. This is only the React seam: read the path the screen is
// currently on, and resolve absolute operator routes against it.
//
//   const to = useAppPath();
//   <Link to={to(`/companies/${id}`)}>…</Link>
//   nav(to(`/deals/${id}`))
//
// Why a hook and not a constant: a screen does not know which shell it is in,
// and must not — asking `me.role` would be wrong twice over. An operator
// previewing at `/w/<slug>` is not a client but IS in the client shell, and the
// answer this needs is about the URL, not the identity.
//
// Hash hrefs (`href="#/deals/5"`) cannot be fixed by this and must become router
// links instead: the client host serves real paths, so the hash is inert there.
import { useCallback } from "react";
import { useLocation } from "react-router-dom";
import { appPath } from "./clientUrl";

export function useAppPath() {
  const { pathname } = useLocation();
  return useCallback((target) => appPath(pathname, target), [pathname]);
}

export default useAppPath;
