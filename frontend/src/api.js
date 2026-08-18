// API client: same-origin by default (FastAPI serves the built app);
// VITE_API_BASE overrides for local dev against a remote backend.
export const API_BASE = import.meta.env.VITE_API_BASE || "";
const BASE = API_BASE;

export function getToken() { return localStorage.getItem("rc_token") || ""; }
export function setToken(t) { t ? localStorage.setItem("rc_token", t) : localStorage.removeItem("rc_token"); }

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

// "Preview as client" is a request header rather than a per-call argument, so
// every screen inside Client Space — including ones written later — is answered
// with the client's field of view without each page remembering to ask. The
// server treats it as a narrowing filter only: it can never grant access.
let clientPreview = false;
export function setClientPreview(on) { clientPreview = !!on; }
export function isClientPreview() { return clientPreview; }

let refreshPromise = null;
export function refreshSession() {
  if (!refreshPromise) {
    const url = new URL(BASE + "/api/auth/refresh", window.location.origin);
    const token = getToken();
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    refreshPromise = fetch(url, { method: "POST", headers, credentials: "include" })
      .then(async (res) => {
        if (!res.ok) return "";
        const data = await res.json();
        if (!data.token) return "";
        setToken(data.token);
        return data.token;
      })
      .catch(() => "")
      .finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export async function api(path, { method = "GET", body, params, auth = true, retryAuth = true } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  });
  const headers = { "Content-Type": "application/json" };
  const token = auth ? getToken() : "";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (clientPreview) headers["X-Client-Preview"] = "1";
  const res = await fetch(url, {
    method, headers, credentials: "include", body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && auth) {
    const current = getToken();
    if (retryAuth && current && current !== token) {
      // A newer login/refresh won a race with this request. Retry with it; an
      // old in-flight 401 must never erase a newer session.
      return api(path, { method, body, params, auth, retryAuth: false });
    }
    if (retryAuth && current === token) {
      const refreshed = await refreshSession();
      if (refreshed) return api(path, { method, body, params, auth, retryAuth: false });
    }
    // Clear only the credential that actually failed. This protects a login in
    // another tab from an older request completing late.
    if (getToken() === token) setToken("");
    onUnauthorized();
    throw new Error("Session expired — please log in again");
  }
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* noop */ }
    const error = new Error(typeof detail === "string" ? detail : (detail?.message || JSON.stringify(detail)));
    error.status = res.status;
    error.detail = detail;
    throw error;
  }
  return res.json();
}

// Authed file download (PDFs). Streams the response to a blob and triggers a
// browser download with the server-provided filename.
export async function download(path, fallbackName = "download.pdf") {
  const url = new URL(BASE + path, window.location.origin);
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* noop */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  const blob = await res.blob();
  const cd = res.headers.get("content-disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
}

export const money = (v) =>
  (v || 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

// Turn an email body (often raw HTML) into clean, readable text — strips tags,
// keeps paragraph/line breaks, decodes entities. Safe: no HTML is rendered.
export const emailText = (s) => {
  if (!s) return "";
  if (!/[<&]/.test(s)) return s;                       // already plain
  let t = String(s)
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|tr|h[1-6])>/gi, "\n")
    .replace(/<li[^>]*>/gi, "• ")
    .replace(/<[^>]+>/g, "");
  if (typeof document !== "undefined") {                // decode entities safely
    const ta = document.createElement("textarea");
    ta.innerHTML = t;
    t = ta.value;
  }
  return t.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
};
// Split a message body into the fresh reply and the quoted trailer, so threads
// read clean like Gmail (quoted history hidden behind a toggle).
export const splitQuoted = (text) => {
  const lines = (text || "").split("\n");
  let cut = -1;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i].trim();
    if (/^On .+wrote:$/.test(l) || /^-{2,}\s*Original Message\s*-{2,}$/i.test(l) ||
        /^_{5,}$/.test(l) || /^From:\s.+/.test(l)) { cut = i; break; }
    if (l.startsWith(">") && i > 0) { cut = i; break; }
  }
  if (cut < 0) return { main: (text || "").trimEnd(), quoted: "" };
  return { main: lines.slice(0, cut).join("\n").trimEnd(), quoted: lines.slice(cut).join("\n").trim() };
};
// Backend timestamps are naive UTC (no timezone). new Date(iso) would read them as
// LOCAL time and show the wrong clock time. Normalize by appending Z, then format
// in the user's locale. Use these instead of new Date(iso).toLocale*() directly.
export const localDateTime = (iso) => iso ? new Date(String(iso) + (String(iso).endsWith("Z") ? "" : "Z")).toLocaleString() : "";
export const localDate = (iso) => iso ? new Date(String(iso) + (String(iso).endsWith("Z") ? "" : "Z")).toLocaleDateString() : "";
export const timeAgo = (iso) => {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};
