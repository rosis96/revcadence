// Client Profile / Formats / Rules — the old dashboard's config sections,
// per workspace. Formats accepts the same Format JSON the old system used
// ("Paste Format JSON" → fills the editor).
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Spinner } from "../components";

const PROFILE_FIELDS = [
  ["client_name", "Client name"],
  ["service_brief", "Service brief — who the client is and what they sell"],
  ["main_offer", "Main offer"],
  ["what_we_are_pitching", "What we are pitching"],
  ["target_outcome", "Target outcome"],
  ["icp_summary", "ICP summary"],
];

export default function EnrichConfigPage({ tab }) {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formatJson, setFormatJson] = useState("");

  useEffect(() => {
    setCfg(null); setError("");
    if (!wsId) return;
    api(`/api/enrich-lists/config/${wsId}`).then(setCfg).catch((e) => setError(e.message));
  }, [wsId, tab]);

  if (!wsId) return <ErrorBox msg="Pick a specific workspace (top-left) — enrichment config is per client workspace." />;
  if (error) return <ErrorBox msg={error} />;
  if (!cfg) return <Spinner />;

  const save = async (patch) => {
    setBusy(true); setSaved(false);
    try {
      await api(`/api/enrich-lists/config/${wsId}`, { method: "PUT", body: patch });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const fillFromJson = () => {
    try {
      const parsed = JSON.parse(formatJson);
      const items = Array.isArray(parsed) ? parsed : [parsed];
      const norm = items.map((v, i) => ({
        label: v.label || `Variable ${i + 1}`,
        name: v.name || (v.label || `var_${i + 1}`).toLowerCase().replace(/[^a-z0-9]+/g, "_"),
        guidance: v.guidance || "", template: v.template || "",
        min_words: v.min_words ?? null, max_words: v.max_words ?? null,
        placeholders: v.placeholders || [],
      }));
      setCfg({ ...cfg, formats: [...(cfg.formats || []), ...norm] });
      setFormatJson("");
    } catch (e) { alert("Invalid JSON: " + e.message); }
  };

  return (
    <div style={{ maxWidth: 1100 }}>
      {saved && <div className="card" style={{ padding: "8px 14px", marginBottom: 12, color: "var(--ok)", borderColor: "var(--ok)" }}>Saved.</div>}

      {tab === "profile" && (
        <>
          <div className="card" style={{ padding: 18 }}>
            <h2 style={{ fontSize: 15, marginBottom: 4 }}>Client Profile</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 14 }}>
              Who this workspace's client is and what they sell. The writer grounds every line in this + the prospect's site.</p>
            {PROFILE_FIELDS.map(([k, label]) => (
              <div className="field" key={k}><label>{label}</label>
                <textarea rows={k === "service_brief" ? 3 : 2} value={cfg.profile?.[k] || ""}
                          style={{ width: "100%" }}
                          onChange={(e) => setCfg({ ...cfg, profile: { ...cfg.profile, [k]: e.target.value } })} />
              </div>
            ))}
          </div>
          <div className="card" style={{ padding: 18, marginTop: 14 }}>
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={cfg.skip_title_gate}
                     onChange={(e) => setCfg({ ...cfg, skip_title_gate: e.target.checked })} />
              Skip title gate (run ICP on every title, not just senior decision-makers)
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, fontSize: 13 }}>
              <input type="checkbox" checked={cfg.only_safe}
                     onChange={(e) => setCfg({ ...cfg, only_safe: e.target.checked })} />
              Only Safe — catch-all / unknown emails stop as unsafe (recommended; saves writer spend)
            </label>
          </div>
          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn" disabled={busy}
                    onClick={() => save({ profile: cfg.profile, skip_title_gate: cfg.skip_title_gate, only_safe: cfg.only_safe })}>
              Save profile</button>
          </div>
        </>
      )}

      {tab === "icp" && (
        <>
          <div className="card" style={{ padding: 18 }}>
            <h2 style={{ fontSize: 15, marginBottom: 4 }}>ICP / Non-ICP — the single ICP brain</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 10 }}>
              Drives the engine's strict ICP review for both classification and enrichment. Paste
              the ICP JSON (keys: <b>procedure</b> steps, <b>icp_categories</b> allowed fits,
              <b> hard_non_icp</b> auto-rejects, <b>default</b> when unsure) — or plain text.
              Editing here changes how leads are judged immediately.</p>
            <textarea rows={16} style={{ width: "100%", fontFamily: "monospace", fontSize: 12.5 }}
                      value={cfg.icp_definition}
                      onChange={(e) => setCfg({ ...cfg, icp_definition: e.target.value })}
                      placeholder='{"procedure": ["Step 1: ..."], "icp_categories": ["B2B consulting firms."], "hard_non_icp": ["B2C only."], "default": "Needs Review"}' />
          </div>
          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn" disabled={busy} onClick={() => save({ icp_definition: cfg.icp_definition })}>Save ICP JSON</button>
          </div>
        </>
      )}

      {tab === "formats" && (
        <>
          <div className="card" style={{ padding: 18 }}>
            <h2 style={{ fontSize: 15, marginBottom: 4 }}>Paste Format JSON</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 10 }}>
              Same JSON the old Formats editor accepted (label, guidance, template, min/max words, placeholders). Paste, then Fill.</p>
            <textarea rows={6} style={{ width: "100%" }} value={formatJson}
                      onChange={(e) => setFormatJson(e.target.value)}
                      placeholder='{"label": "Personalized First Line", "guidance": "...", "min_words": 12, "max_words": 25}' />
            <div className="toolbar" style={{ marginTop: 10 }}>
              <button className="btn ghost" onClick={fillFromJson}>Fill sections from JSON</button>
            </div>
          </div>
          {(cfg.formats || []).map((f, i) => (
            <div className="card" style={{ padding: 18, marginTop: 14 }} key={i}>
              <div className="toolbar" style={{ marginBottom: 8 }}>
                <b>{f.label}</b> <span className="badge">{f.name}</span>
                <div className="spacer" />
                <button className="btn danger sm"
                        onClick={() => setCfg({ ...cfg, formats: cfg.formats.filter((_, j) => j !== i) })}>Remove</button>
              </div>
              <div className="field"><label>How to write it — rules & guidance</label>
                <textarea rows={3} style={{ width: "100%" }} value={f.guidance}
                          onChange={(e) => setCfg({ ...cfg, formats: cfg.formats.map((x, j) => j === i ? { ...x, guidance: e.target.value } : x) })} /></div>
              <div className="field"><label>Format template (optional, with {"{{placeholders}}"})</label>
                <input style={{ width: "100%" }} value={f.template || ""}
                       onChange={(e) => setCfg({ ...cfg, formats: cfg.formats.map((x, j) => j === i ? { ...x, template: e.target.value } : x) })} /></div>
              <div style={{ display: "flex", gap: 10 }}>
                <div className="field"><label>Min words</label>
                  <input type="number" value={f.min_words ?? ""} style={{ width: 90 }}
                         onChange={(e) => setCfg({ ...cfg, formats: cfg.formats.map((x, j) => j === i ? { ...x, min_words: Number(e.target.value) || null } : x) })} /></div>
                <div className="field"><label>Max words</label>
                  <input type="number" value={f.max_words ?? ""} style={{ width: 90 }}
                         onChange={(e) => setCfg({ ...cfg, formats: cfg.formats.map((x, j) => j === i ? { ...x, max_words: Number(e.target.value) || null } : x) })} /></div>
              </div>
            </div>
          ))}
          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn ghost"
                    onClick={() => setCfg({ ...cfg, formats: [...(cfg.formats || []), { label: "New variable", name: `var_${(cfg.formats || []).length + 1}`, guidance: "", min_words: null, max_words: null }] })}>
              + Add variable</button>
            <button className="btn" disabled={busy} onClick={() => save({ formats: cfg.formats })}>Save formats</button>
          </div>
        </>
      )}

      {tab === "rules" && (
        <>
          <div className="card" style={{ padding: 18 }}>
            <h2 style={{ fontSize: 15, marginBottom: 4 }}>Correction rules</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 10 }}>
              One rule per line, plain English. Every line is injected into the writer on every enrichment —
              use it to correct mistakes without touching code. Example: "Never start two variables with the same word."</p>
            <textarea rows={14} style={{ width: "100%" }} value={cfg.rules}
                      onChange={(e) => setCfg({ ...cfg, rules: e.target.value })} />
          </div>
          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn" disabled={busy} onClick={() => save({ rules: cfg.rules })}>Save rules</button>
          </div>
        </>
      )}
    </div>
  );
}
