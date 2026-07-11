import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

// Workspace selection: "" = all workspaces (masters only); otherwise an id.
export function AuthProvider({ children }) {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(!!getToken());
  const [workspaceId, setWorkspaceIdRaw] = useState(localStorage.getItem("rc_ws") || "");

  const setWorkspaceId = (id) => { localStorage.setItem("rc_ws", id ?? ""); setWorkspaceIdRaw(id ?? ""); };

  const logout = useCallback(() => { setToken(""); setMe(null); }, []);
  useEffect(() => { setUnauthorizedHandler(() => setMe(null)); }, []);

  const loadMe = useCallback(async () => {
    try {
      const data = await api("/api/auth/me");
      setMe(data);
      // Clients (and members with one workspace) are pinned to it.
      if (!data.is_master && data.workspaces.length >= 1) setWorkspaceId(String(data.workspaces[0].id));
    } catch { setMe(null); }
    setLoading(false);
  }, []);

  useEffect(() => { if (getToken()) loadMe(); }, [loadMe]);

  const login = async (email, password) => {
    const r = await api("/api/auth/login", { method: "POST", body: { email, password } });
    setToken(r.token);
    await loadMe();
  };

  const wsParam = workspaceId ? Number(workspaceId) : undefined;
  return (
    <AuthCtx.Provider value={{ me, loading, login, logout, workspaceId, setWorkspaceId, wsParam }}>
      {children}
    </AuthCtx.Provider>
  );
}
