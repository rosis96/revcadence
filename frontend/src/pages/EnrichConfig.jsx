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
  const [profileJson, setProfileJson] = useState("");
  const [reoonKey, setReoonKey] = useState("");

  // Paste Client Profile JSON → fills the boxes. Accepts the training-file
  // schema incl. aliases (value_prop → what_we_are_pitching) and keeps extra
  // keys (positioning, core_capabilities) in the stored profile.
  const fillProfileFromJson = () => {
    try {
      const p = JSON.parse(profileJson);
      const merged = { ...(cfg.profile || {}), ...p };
      if (p.value_prop && !p.what_we_are_pitching) merged.what_we_are_pitching = p.value_prop;
      setCfg({ ...cfg, profile: merged, icp_definition: p.icp_definition || cfg.icp_definition });
      setProfileJson("");
    } catch (e) { alert("Invalid JSON: " + e.message); }
  };

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

  const slug = (s, i) => (s || `var_${i + 1}`).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  const asArr = (v) => (Array.isArray(v) ? v : v == null ? [] : [v]);
  // {{tokens}} inside a template — deduped, in order.
  const tokensIn = (tpl) => [...new Set([...(tpl || "").matchAll(/\{\{\s*([^}]+?)\s*\}\}/g)].map((m) => m[1].trim()).filter(Boolean))];
  // Placeholders may arrive as an array OR as an object map keyed by token
  // (the two shapes the old dashboard used) — normalize to an array.
  const normPh = (ph) => {
    if (!ph) return [];
    const arr = Array.isArray(ph) ? ph : Object.entries(ph).map(([token, p]) => ({ token, ...(p || {}) }));
    return arr.filter((p) => p && p.token).map((p) => ({
      token: p.token, description: p.description || "",
      min_words: p.min_words ?? null, max_words: p.max_words ?? null,
      examples: asArr(p.examples).filter(Boolean),
    }));
  };
  const normFormat = (v, i) => ({
    label: v.label || v.name || `Variable ${i + 1}`,
    name: v.name || slug(v.label, i),
    guidance: v.guidance || v.purpose || "",
    template: v.template || "",
    min_words: v.min_words ?? null, max_words: v.max_words ?? null,
    rules: asArr(v.rules || v.writing_rules).filter(Boolean),
    examples: asArr(v.examples || v.example_outputs).filter(Boolean),
    placeholders: normPh(v.placeholders),
  });
  // Fill = LOAD the pasted set into the editor (replace), so re-pasting never
  // duplicates. Accepts a bare array, a single object, or {variables, global_output_rules}.
  const fillFromJson = (append = false) => {
    try {
      const parsed = JSON.parse(formatJson);
      const arr = Array.isArray(parsed) ? parsed : parsed.variables || [parsed];
      const items = arr.map(normFormat);
      const patch = { ...cfg, formats: append ? [...(cfg.formats || []), ...items] : items };
      if (!Array.isArray(parsed) && Array.isArray(parsed.global_output_rules) && parsed.global_output_rules.length)
        patch.rules = parsed.global_output_rules.join("\n");
      setCfg(patch);
      setFormatJson("");
    } catch (e) { alert("Invalid JSON: " + e.message); }
  };
  const setFmt = (i, patch) => setCfg({ ...cfg, formats: cfg.formats.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  // Editing the template re-syncs placeholder boxes: keep the ones whose token
  // still appears (with their description/range/examples), add a fresh box for
  // each new {{token}}, drop the ones no longer referenced.
  const setTemplate = (i, template) => {
    const existing = cfg.formats[i].placeholders || [];
    const byTok = Object.fromEntries(existing.map((p) => [p.token, p]));
    const placeholders = tokensIn(template).map(
      (t) => byTok[t] || { token: t, description: "", min_words: null, max_words: null, examples: [] });
    setFmt(i, { template, placeholders });
  };
  const setPh = (i, ti, patch) =>
    setFmt(i, { placeholders: cfg.formats[i].placeholders.map((p, k) => (k === ti ? { ...p, ...patch } : p)) });
  const addVariable = () => setCfg({ ...cfg, formats: [
    ...(cfg.formats || []),
    { label: "New variable", name: `var_${(cfg.formats || []).length + 1}`, guidance: "",
      template: "", min_words: null, max_words: null, rules: [], examples: [], placeholders: [] }] });
  const duplicateVariable = (i) => {
    const src = cfg.formats[i];
    const copy = { ...src, label: `${src.label} (copy)`, name: `${src.name}_copy` };
    const formats = [...cfg.formats]; formats.splice(i + 1, 0, copy);
    setCfg({ ...cfg, formats });
  };
  // Trim blank lines out of the newline-edited arrays right before saving.
  const cleanFormats = (formats) => (formats || []).map((f) => ({
    ...f,
    rules: (f.rules || []).map((s) => s.trim()).filter(Boolean),
    examples: (f.examples || []).map((s) => s.trim()).filter(Boolean),
    placeholders: (f.placeholders || []).map((p) => ({ ...p, examples: (p.examples || []).map((s) => s.trim()).filter(Boolean) })),
  }));
  const downloadFormats = () => {
    const blob = new Blob([JSON.stringify({ variables: cleanFormats(cfg.formats) }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "formats.json";
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
  };
  // Lead fields the pipeline fills automatically — flagged so users don't think
  // they must describe them.
  const AUTO_TOKENS = new Set(["company_name", "first_name", "last_name", "company", "title", "email", "website", "firstname", "lastname"]);

  return (
    <div style={{ maxWidth: 1100 }}>
      {saved && <div className="card" style={{ padding: "8px 14px", marginBottom: 12, color: "var(--ok)", borderColor: "var(--ok)" }}>Saved.</div>}

      {tab === "profile" && (
        <>
          <div className="card" style={{ padding: 14, marginBottom: 14 }}>
            <label style={{ fontSize: 12.5, fontWeight: 600 }}>Paste Client Profile JSON (auto-fills the boxes below)</label>
            <textarea rows={2} style={{ width: "100%", fontFamily: "monospace", fontSize: 12, marginTop: 4 }}
                      value={profileJson} onChange={(e) => setProfileJson(e.target.value)}
                      placeholder='{"client_name":"Ascendly","service_brief":"…","main_offer":"…","what_we_are_pitching":"…","target_outcome":"…","icp_summary":"…"}' />
            <button className="btn ghost sm" style={{ marginTop: 6 }} onClick={fillProfileFromJson}>Fill boxes from JSON</button>
          </div>
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
              <input type="checkbox" checked={cfg.skip_icp}
                     onChange={(e) => setCfg({ ...cfg, skip_icp: e.target.checked })} />
              Skip ICP filtering — enrich every verified lead (don’t reject Non-ICP). ICP is still scored for reference.
            </label>
            <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, fontSize: 13 }}>
              <input type="checkbox" checked={cfg.only_safe}
                     onChange={(e) => setCfg({ ...cfg, only_safe: e.target.checked })} />
              Only Safe — catch-all / unknown emails stop as unsafe (recommended; saves writer spend)
            </label>
          </div>

          <div className="card" style={{ padding: 18, marginTop: 14 }}>
            <h2 style={{ fontSize: 15, marginBottom: 4 }}>Reoon email verification key</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 10 }}>
              Required for real mailbox verification. <b>Without a key, emails are NOT verified</b> and
              every lead stops as unsafe (they are never falsely marked safe). Paste your Reoon API key
              (Reoon → API &amp; Integrations).
            </p>
            <div style={{
              display: "inline-block", fontSize: 12, fontWeight: 600, marginBottom: 10,
              color: cfg.reoon_api_key_set ? "#15803d" : "#b91c1c",
            }}>
              {cfg.reoon_api_key_set
                ? `● Key active (${cfg.reoon_key_source === "env" ? "server env" : "workspace"})`
                : "● No key — verification is OFF"}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <input type="password" value={reoonKey} placeholder="Paste Reoon API key…"
                     onChange={(e) => setReoonKey(e.target.value)} style={{ flex: 1 }} />
              <button className="btn" disabled={busy || !reoonKey.trim()}
                      onClick={async () => { await save({ reoon_api_key: reoonKey.trim() });
                        setReoonKey(""); api(`/api/enrich-lists/config/${wsId}`).then(setCfg); }}>
                Save key</button>
              {cfg.reoon_api_key_set && cfg.reoon_key_source === "workspace" && (
                <button className="btn secondary" disabled={busy}
                        onClick={async () => { await save({ reoon_api_key: "" });
                          api(`/api/enrich-lists/config/${wsId}`).then(setCfg); }}>
                  Remove</button>
              )}
            </div>
          </div>
          <div className="card" style={{ padding: 18, marginTop: 14 }}>
            <h2 style={{ fontSize: 15, marginBottom: 4 }}>Writing controls</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 12 }}>
              How the AI writes your personalization, and how deeply it researches each site.
            </p>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              <div className="field" style={{ margin: 0, minWidth: 190 }}>
                <label>Reading level</label>
                <select style={{ width: "100%" }} value={cfg.reading_level || ""}
                        onChange={(e) => setCfg({ ...cfg, reading_level: e.target.value })}>
                  <option value="">Natural (default)</option>
                  <option value="5th grade">5th grade — very simple</option>
                  <option value="6th grade">6th grade</option>
                  <option value="7th grade">7th grade</option>
                  <option value="8th grade">8th grade</option>
                  <option value="10th grade">10th grade</option>
                  <option value="plain professional">Plain professional</option>
                </select>
              </div>
              <div className="field" style={{ margin: 0, minWidth: 190 }}>
                <label>Research depth</label>
                <select style={{ width: "100%" }} value={cfg.research_depth || "standard"}
                        onChange={(e) => setCfg({ ...cfg, research_depth: e.target.value })}>
                  <option value="standard">Standard (faster, cheaper)</option>
                  <option value="deep">Deep (more pages + more content)</option>
                </select>
              </div>
              <div className="field" style={{ margin: 0, minWidth: 200 }}>
                <label>Writer model</label>
                <select style={{ width: "100%" }} value={cfg.writer_model || ""}
                        onChange={(e) => setCfg({ ...cfg, writer_model: e.target.value })}>
                  <option value="">Default ({cfg.writer_model_effective || "server default"})</option>
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                  <option value="gpt-4o">gpt-4o (higher quality)</option>
                  <option value="gpt-4.1">gpt-4.1 (highest)</option>
                </select>
              </div>
            </div>
            <div style={{ marginTop: 10, fontSize: 12, color: cfg.ai_enabled ? "var(--muted)" : "#b91c1c" }}>
              {cfg.ai_enabled
                ? `● AI on — writing with ${cfg.writer_model_effective}, ICP/extraction with ${cfg.icp_model_effective}.`
                : "● AI is OFF (no OpenAI key) — enrichment would fall back to templated demo copy. Set OPENAI_API_KEY."}
            </div>
          </div>

          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn" disabled={busy}
                    onClick={() => save({ profile: cfg.profile, skip_title_gate: cfg.skip_title_gate,
                      skip_icp: cfg.skip_icp, only_safe: cfg.only_safe, reading_level: cfg.reading_level,
                      writer_model: cfg.writer_model, research_depth: cfg.research_depth })}>
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
              Same JSON the old Formats editor accepted — a bare array of variables, or
              {" "}<code>{"{ variables: [...], global_output_rules: [...] }"}</code>. Each variable:
              label, guidance, template, min/max words, rules, examples, and placeholders
              (each with its own description, word range & examples). Paste, then Fill.</p>
            <textarea rows={6} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }} value={formatJson}
                      onChange={(e) => setFormatJson(e.target.value)}
                      placeholder='[{"label":"Value Proposition","guidance":"…","template":"We help {{industry}} {{result}}.","min_words":15,"max_words":30,"placeholders":[{"token":"industry","description":"the prospect category","examples":["marketing agencies"]}]}]' />
            <div className="toolbar" style={{ marginTop: 10 }}>
              <button className="btn ghost" onClick={() => fillFromJson(false)}>Fill sections from JSON (replace)</button>
              <button className="btn ghost sm" onClick={() => fillFromJson(true)}>Add to existing</button>
              <div className="spacer" />
              <button className="btn ghost sm" onClick={downloadFormats}>Download JSON</button>
            </div>
          </div>

          {(cfg.formats || []).map((f, i) => (
            <div className="card" style={{ padding: 18, marginTop: 14 }} key={i}>
              <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 10 }}>
                <div className="field" style={{ flex: 1, margin: 0 }}>
                  <label>Variable name</label>
                  <input style={{ width: "100%" }} value={f.label || ""}
                         onChange={(e) => setFmt(i, { label: e.target.value, name: slug(e.target.value, i) })}
                         placeholder="Personalized First Line" />
                </div>
                <div className="field" style={{ width: 240, margin: 0 }}>
                  <label>Output key (slug)</label>
                  <input style={{ width: "100%", fontFamily: "monospace", fontSize: 12.5 }} value={f.name || ""}
                         onChange={(e) => setFmt(i, { name: e.target.value })} placeholder="personalized_first_line" />
                </div>
                <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12.5, whiteSpace: "nowrap" }}>
                  <input type="checkbox" checked={f.enabled !== false}
                         onChange={(e) => setFmt(i, { enabled: e.target.checked })} />
                  Write this
                </label>
                <button className="btn ghost sm" onClick={() => duplicateVariable(i)}>Duplicate</button>
                <button className="btn danger sm"
                        onClick={() => setCfg({ ...cfg, formats: cfg.formats.filter((_, j) => j !== i) })}>Remove</button>
              </div>

              <div className="field"><label>How to write it — guidance</label>
                <textarea rows={3} style={{ width: "100%" }} value={f.guidance}
                          onChange={(e) => setFmt(i, { guidance: e.target.value })}
                          placeholder="Explain in plain words how this should be written. e.g. One sentence on a specific, real detail from the prospect's site. No pitch. No greeting." /></div>

              <div className="field"><label>Fallback <span style={{ color: "var(--muted)", fontWeight: 400 }}>(optional — if the info for this variable isn't available, write this instead. Leave blank to skip the variable when there's nothing to say)</span></label>
                <textarea rows={2} style={{ width: "100%" }} value={f.fallback || ""}
                          onChange={(e) => setFmt(i, { fallback: e.target.value })}
                          placeholder="e.g. If no specific site detail, reference their industry and one common goal for that industry." /></div>

              <div className="field"><label>Rules for this variable <span style={{ color: "var(--muted)", fontWeight: 400 }}>(one rule per line — obeyed while writing THIS variable)</span></label>
                <textarea rows={3} style={{ width: "100%" }} value={(f.rules || []).join("\n")}
                          onChange={(e) => setFmt(i, { rules: e.target.value.split("\n") })}
                          placeholder={"Start with a concrete observation, not praise.\nNever end with a question mark.\nDo not use the words 'impressive' or 'world-class'."} /></div>

              <div className="field"><label>Format template <span style={{ color: "var(--muted)", fontWeight: 400 }}>(optional — leave blank for free-form variables. Use {"{{placeholders}}"} for fill-in-the-blank parts)</span></label>
                <textarea rows={2} style={{ width: "100%" }} value={f.template || ""}
                          onChange={(e) => setTemplate(i, e.target.value)}
                          placeholder="We help {{industry}} get {{ideal_customers}} by {{what_we_do}}." /></div>

              <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
                <div className="field" style={{ margin: 0 }}><label>Whole-variable word range — min</label>
                  <input type="number" value={f.min_words ?? ""} style={{ width: 90 }}
                         onChange={(e) => setFmt(i, { min_words: Number(e.target.value) || null })} /></div>
                <div className="field" style={{ margin: 0 }}><label>max</label>
                  <input type="number" value={f.max_words ?? ""} style={{ width: 90 }}
                         onChange={(e) => setFmt(i, { max_words: Number(e.target.value) || null })} /></div>
              </div>

              {/* Placeholders — one explanation box per {{token}} in the template. */}
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>Placeholders</div>
                {(f.placeholders || []).length === 0 ? (
                  <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
                    Add {"{{placeholders}}"} in the template above to describe them here.</div>
                ) : (
                  f.placeholders.map((p, ti) => (
                    <div className="card" style={{ padding: 12, marginBottom: 8, background: "var(--bg-soft, transparent)" }} key={p.token}>
                      <div style={{ fontFamily: "monospace", fontSize: 12.5, color: "var(--accent, #635BFF)", marginBottom: 6 }}>
                        {"{{"}{p.token}{"}}"}
                        {AUTO_TOKENS.has(p.token.toLowerCase()) &&
                          <span style={{ color: "var(--muted)", fontFamily: "inherit", marginLeft: 8 }}>· lead field, filled automatically</span>}
                      </div>
                      <div className="field" style={{ margin: 0 }}><label>How to write this placeholder</label>
                        <textarea rows={2} style={{ width: "100%" }} value={p.description || ""}
                                  onChange={(e) => setPh(i, ti, { description: e.target.value })}
                                  placeholder="What goes here and how to phrase it" /></div>
                      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginTop: 8 }}>
                        <div className="field" style={{ margin: 0 }}><label>words — min</label>
                          <input type="number" value={p.min_words ?? ""} style={{ width: 80 }}
                                 onChange={(e) => setPh(i, ti, { min_words: Number(e.target.value) || null })} /></div>
                        <div className="field" style={{ margin: 0 }}><label>max</label>
                          <input type="number" value={p.max_words ?? ""} style={{ width: 80 }}
                                 onChange={(e) => setPh(i, ti, { max_words: Number(e.target.value) || null })} /></div>
                      </div>
                      <div className="field" style={{ margin: "8px 0 0" }}><label>Examples <span style={{ color: "var(--muted)", fontWeight: 400 }}>(one per line)</span></label>
                        <textarea rows={2} style={{ width: "100%" }} value={(p.examples || []).join("\n")}
                                  onChange={(e) => setPh(i, ti, { examples: e.target.value.split("\n") })}
                                  placeholder={"book more sales calls\ncut response time"} /></div>
                    </div>
                  ))
                )}
              </div>

              <div className="field" style={{ marginTop: 14 }}><label>Examples <span style={{ color: "var(--muted)", fontWeight: 400 }}>(one per line — sample outputs that show the AI what good looks like)</span></label>
                <textarea rows={3} style={{ width: "100%" }} value={(f.examples || []).join("\n")}
                          onChange={(e) => setFmt(i, { examples: e.target.value.split("\n") })}
                          placeholder={"Your work for Acme Dental shows a clear focus on local clinics.\nThe way you bundle SEO with paid search is a sharp combo for B2B teams."} /></div>
            </div>
          ))}

          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn ghost" onClick={addVariable}>+ Add variable</button>
            <button className="btn" disabled={busy} onClick={() => save({ formats: cleanFormats(cfg.formats) })}>Save formats</button>
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
