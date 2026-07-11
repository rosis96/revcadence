// API client: same-origin by default (FastAPI serves the built app);
// VITE_API_BASE overrides for local dev against a remote backend.
const BASE = import.meta.env.VITE_API_BASE || "";

export function getToken() { return localStorage.getItem("rc_token") || ""; }
export function setToken(t) { t ? localStorage.setItem("rc_token", t) : localStorage.removeItem("rc_token"); }

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(path, { method = "GET", body, params } = {}) {
  const url = new URL(BASE + path, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  });
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (res.status === 401) { setToken(""); onUnauthorized(); throw new Error("Session expired — please log in again"); }
  if (!res.ok) {
    let detail = `${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch { /* noop */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

export const money = (v) =>
  (v || 0).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const timeAgo = (iso) => {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};
