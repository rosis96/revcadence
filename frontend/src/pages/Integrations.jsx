/*
 * Settings -> Integrations. A place to plug in external APIs so the system uses
 * them instead of the built-in tools. First provider: the Company Research API,
 * the primary website crawler for enrichment (in-house crawler stays as fallback).
 * Additive page; wired into App.jsx with one nav entry + one route.
 */
import { useEffect, useState } from "react";
import { api } from "../api";
import { notify } from "../components";

const label = { display: "block", fontSize: 11, fontWeight: 800, letterSpacing: ".04em", textTransform: "uppercase", color: "var(--muted)", marginBottom: 5 };
const input = { width: "100%", border: "1px solid var(--border-strong)", borderRadius: 8, padding: "9px 11px", fontFamily: "inherit", fontSize: 13, color: "var(--text)", background: "var(--card)" };

export default function Integrations() {
  const [cfg, setCfg] = useState({ base_url: "", enabled: false, key_set: false });
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => { api("/api/integrations/research").then(setCfg).catch(() => {}); }, []);

  const save = async () => {
    setBusy(true);
    try {
      await api("/api/integrations/research", { method: "PUT", body: { base_url: cfg.base_url, enabled: cfg.enabled, api_key: apiKey } });
      setApiKey("");
      setCfg(await api("/api/integrations/research"));
      notify("Saved", "ok");
    } catch (e) { notify(e.message || "Save failed", "bad"); }
    setBusy(false);
  };
  const test = async () => {
    setTesting(true);
    try {
      const r = await api("/api/integrations/research/test", { method: "POST" });
      notify(r.ok ? "Connected ✓" : `Not reachable (${r.status_code || r.error || "error"})`, r.ok ? "ok" : "bad");
    } catch (e) { notify(e.message || "Test failed", "bad"); }
    setTesting(false);
  };

  return (
    <div style={{ maxWidth: 720 }}>
      <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: "-.02em", margin: "0 0 4px" }}>Integrations</h1>
      <p style={{ color: "var(--muted)", marginTop: 0, fontSize: 13.5 }}>
        Plug in external APIs so the system uses them instead of the built-in tools.
      </p>

      <div className="card" style={{ marginTop: 18 }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Company Research API</div>
            <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 2, maxWidth: 460 }}>
              Primary website crawler used during enrichment. When enabled, every prospect is researched through this API;
              the built-in crawler runs only if the API is unavailable or returns nothing.
            </div>
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} /> Enabled
          </label>
        </div>

        <div style={{ marginTop: 16 }}>
          <label style={label}>Base URL</label>
          <input style={input} placeholder="https://company-research-api-production.up.railway.app"
            value={cfg.base_url} onChange={(e) => setCfg({ ...cfg, base_url: e.target.value })} />
        </div>

        <div style={{ marginTop: 12 }}>
          <label style={label}>API key {cfg.key_set && <span style={{ color: "var(--ok-text)", fontWeight: 700 }}>· saved</span>}</label>
          <input type="password" style={input}
            placeholder={cfg.key_set ? "•••••••• (leave blank to keep the saved key)" : "Bearer key (standard scope)"}
            value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button className="btn" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
          <button className="btn ghost" onClick={test} disabled={testing}>{testing ? "Testing…" : "Test connection"}</button>
        </div>
      </div>

      <p style={{ color: "var(--muted)", fontSize: 12, marginTop: 14 }}>
        The key is encrypted at rest and never shown again after saving. More providers can be added here later.
      </p>
    </div>
  );
}
