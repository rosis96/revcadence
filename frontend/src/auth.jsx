import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, getToken, refreshSession, setToken, setUnauthorizedHandler } from "./api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

// Workspace selection: "" = all workspaces (masters only); otherwise an id.
export function AuthProvider({ children }) {
  const [me, setMe] = useState(null);
  // Always check the secure refresh cookie before showing the login page. This
  // restores the session even if localStorage was cleared while the tab closed.
  const [loading, setLoading] = useState(true);
  const [workspaceId, setWorkspaceIdRaw] = useState(localStorage.getItem("rc_ws") || "");

  const setWorkspaceId = (id) => { localStorage.setItem("rc_ws", id ?? ""); setWorkspaceIdRaw(id ?? ""); };

  const logout = useCallback(() => {
    setToken("");
    setMe(null);
    setLoading(false);
    api("/api/auth/logout", { method: "POST", auth: false }).catch(() => {});
  }, []);
  useEffect(() => {
    setUnauthorizedHandler(() => { setMe(null); setLoading(false); });
    return () => setUnauthorizedHandler(() => {});
  }, []);

  const loadMe = useCallback(async (retries = 4) => {
    try {
      const data = await api("/api/auth/me");
      setMe(data);
      // Clients (and members with one workspace) are pinned to it.
      if (!data.is_master && data.workspaces.length >= 1) setWorkspaceId(String(data.workspaces[0].id));
      // A selection that no longer exists — the workspace was archived, or
      // access to it was removed — would otherwise be sent as a filter on every
      // request and answered with 403 across the whole app. Read from storage
      // rather than state: this callback is created once and its closure would
      // hold whatever was selected at boot.
      else {
        const picked = localStorage.getItem("rc_ws") || "";
        if (picked && !data.workspaces.some((w) => String(w.id) === picked)) setWorkspaceId("");
      }
      setLoading(false);
    } catch (e) {
      // Only log out on a real auth failure (401 clears the token). A transient
      // error during a redeploy leaves the token intact — retry, don't bounce.
      if (!getToken()) { setMe(null); setLoading(false); return; }
      if (retries > 0) { setTimeout(() => loadMe(retries - 1), 1500); return; }
      setMe(null); setLoading(false);
    }
  }, []);

  useEffect(() => {
    const restore = async () => {
      // Refresh on every new tab/app boot. Besides renewing the sliding cookie,
      // this migrates old access-token-only sessions without another login.
      await refreshSession();
      if (getToken()) await loadMe();
      else setLoading(false);
    };
    restore();
  }, [loadMe]);

  const login = async (email, password) => {
    // Login is public: a bad password must not erase a valid session belonging
    // to another tab, browser profile, or device.
    const r = await api("/api/auth/login", {
      method: "POST", body: { email, password }, auth: false,
    });
    setToken(r.token);
    await loadMe();
  };

  const wsParam = workspaceId ? Number(workspaceId) : undefined;
  return (
    // reloadMe re-reads the session after something changes what it is allowed to
    // do — today, finishing the forced password change on an invited account.
    <AuthCtx.Provider value={{ me, loading, login, logout, workspaceId, setWorkspaceId, wsParam,
      reloadMe: () => loadMe(0) }}>
      {children}
    </AuthCtx.Provider>
  );
}
