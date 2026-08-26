// Client Profile / ICP / Formats / Rules — the per-workspace enrichment config.
//
// Layout comes from ui/form.jsx (Section / FieldGrid / Field / Area) so this and
// Workspace Training are the same page with different content, rather than two
// screens that happen to both hold inputs. Rules of the road here:
//
//   • A control matches its value. A client name is one line, so it is an
//     <input>; a reading level is a closed set, so it is a <Select>; only
//     genuinely long-form prose gets a textarea.
//   • Textareas are a fixed height and scroll their own overflow, so typing into
//     one never moves the fields — or the Save button — underneath it.
//   • Sections are separated by a rule, not boxed in a card each.
import { useEffect, useState } from "react";
import { Braces } from "lucide-react";
import aiStarSource from "../../../AI Star UI animation.svg?raw";
import { api, getToken } from "../api";
import { useAuth } from "../auth";
import {
  Area, Button, ErrorBox, FieldGrid, FormField as Field, Num, Section,
  Select, Spinner, StickyBar, Text, useToast,
} from "../components";

const aiStar = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(aiStarSource.replaceAll("#ffffff", "#f97316"))}`;

// [key, label, hint, long?] — `long` is the only reason a field gets a textarea.
// `hint` is the field's placeholder; pass a function to derive it from the live
// profile so a field can echo what was typed above it.
const PROFILE_FIELDS = [
  ["client_name", "Client name", "The company this workspace writes for.", false],
  ["main_offer", "Main offer", "What do you sell", false],
  ["service_brief", "Service brief",
    (p) => ((p.main_offer || "").trim()
      ? `Detail about your ${p.main_offer.trim()} Service`
      : "Detail about your main offer"), true],
  ["what_we_are_pitching", "What we are pitching", "The specific offer this campaign leads with.", true],
  ["target_outcome", "Target outcome", "The result the prospect gets — what success looks like for them.", true],
  ["icp_summary", "ICP summary", "One paragraph. The full definition lives on the ICP screen.", true],
];

const READING_LEVELS = [
  ["professional", "Polished professional (C1) — expert copywriter, recommended"],
  ["b2 business", "Clear B2 business English — simpler"],
  ["", "Natural (legacy)"],
  ["5th grade", "5th grade — very simple"],
  ["6th grade", "6th grade"],
  ["7th grade", "7th grade"],
  ["8th grade", "8th grade"],
  ["10th grade", "10th grade"],
  ["plain professional", "Plain professional"],
];
const WRITER_MODELS = [
  ["gpt-5-mini", "gpt-5-mini — recommended cost/quality"],
  ["gpt-5.4-mini", "gpt-5.4-mini — stronger, higher cost"],
  ["gpt-5.6-luna", "gpt-5.6-luna — latest efficient"],
  ["gpt-5.6-terra", "gpt-5.6-terra — premium quality"],
  ["gpt-4o", "gpt-4o — strong, reliable (same as extraction)"],
  ["gpt-4o-mini", "gpt-4o-mini — cost-effective"],
  ["gpt-4.1-mini", "gpt-4.1-mini — legacy"],
  ["gpt-4.1", "gpt-4.1 — legacy premium"],
];
const PIPELINE_TOGGLES = [
  ["skip_title_gate", <>Skip title gate — run ICP on every title, not just senior decision-makers</>],
  ["skip_icp", <>Skip ICP filtering — enrich every verified lead. ICP is still scored for reference.</>],
  ["only_safe", <>Only Safe — catch-all / unknown emails stop as unsafe (recommended; saves writer spend)</>],
  ["require_research_gate", <>Strict research gate — mark a lead “insufficient” and write nothing when the site has
    too little verified evidence. <b>Off by default:</b> the engine writes what it can ground and leaves the rest
    blank (it never fabricates).</>],
];

function Toggle({ checked, onChange, children }) {
  return (
    <label className="fchk">
      <input type="checkbox" checked={!!checked} onChange={onChange} />
      <span>{children}</span>
    </label>
  );
}

// Title filter — free, rule-based gate that runs BEFORE the paid ICP/AI step so
// only the titles you want reach it. Stored on cfg.title_rules as a JSON string
// {mode, include[], exclude[]}. Blank = fall back to the built-in seniority gate.
function TitleFilter({ cfg, setCfg, save, busy }) {
  const parse = (s) => {
    try {
      const d = JSON.parse(s || "{}") || {};
      return {
        mode: d.mode || "allow",
        include: (d.include || []).join(", "),
        exclude: (d.exclude || []).join(", "),
      };
    } catch {
      return { mode: "allow", include: "", exclude: "" };
    }
  };
  const tr = parse(cfg.title_rules);
  const toList = (s) => s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
  const commit = (patch) => {
    const n = { ...tr, ...patch };
    const json = JSON.stringify({ mode: n.mode, include: toList(n.include), exclude: toList(n.exclude) });
    setCfg({ ...cfg, title_rules: json });
  };
  return (
    <Section title="Title filter" hint="Free, rule-based, and instant — no AI. It runs before the ICP step, so only the titles you keep reach the paid classifier. Match is case-insensitive substring: 'vp' matches 'VP of Sales'. Separate entries with commas or new lines. Leave everything blank to use the built-in seniority gate.">
      <FieldGrid>
        <Field label="Mode" hint="How Include and Exclude combine.">
          <Select value={tr.mode} onChange={(e) => commit({ mode: e.target.value })}>
            <option value="allow">Allow list — keep only titles that match Include</option>
            <option value="deny">Deny list — keep everything except titles that match Exclude</option>
            <option value="both">Both — must match Include and must not match Exclude</option>
          </Select>
        </Field>
      </FieldGrid>
      <FieldGrid>
        <Field label="Include titles / keywords" hint="Used in Allow and Both modes. A title passes if it contains any of these." wide>
          <Area size="md" value={tr.include}
            onChange={(e) => commit({ include: e.target.value })}
            placeholder={"CEO, Founder, Co-Founder, Owner, President, Partner\nVP, Vice President, Chief, Head of, Director, Managing Director"} />
        </Field>
      </FieldGrid>
      <FieldGrid>
        <Field label="Exclude titles / keywords" hint="Used in Deny and Both modes. A title is rejected if it contains any of these." wide>
          <Area size="md" value={tr.exclude}
            onChange={(e) => commit({ exclude: e.target.value })}
            placeholder={"assistant, intern, coordinator, student, professor, retired\nsales rep, representative, volunteer, freelance"} />
        </Field>
      </FieldGrid>
      <StickyBar note="Per-list overrides win over this workspace default; lists with their own rules ignore it.">
        <Button loading={busy} onClick={() => save({ title_rules: cfg.title_rules || "" }, "Title filter saved")}>Save title filter</Button>
      </StickyBar>
    </Section>
  );
}

// How this client profile decides fit. Industry mode is the AI classifier (costs
// OpenAI). Ad-spend mode is free and deterministic: it qualifies a company purely
// on evidence that it buys ads and returns ICP (ad spend) / Non-ICP (ad spend).
function AdSpendMode({ cfg, setCfg, save, busy }) {
  const mode = cfg.icp_mode || "industry";
  const cutoff = cfg.ad_spend_cutoff || "possible";
  return (
    <Section first title="How to decide fit"
      hint="Industry ICP uses the AI classifier and your ICP definition below (this is the step that costs OpenAI). Ad-spend only is free and deterministic: it ignores industry and qualifies a company purely on evidence that it buys ads, returning ICP (ad spend) or Non-ICP (ad spend).">
      <FieldGrid>
        <Field label="ICP mode">
          <Select value={mode} onChange={(e) => setCfg({ ...cfg, icp_mode: e.target.value })}>
            <option value="industry">Industry ICP — AI classifier</option>
            <option value="ad_spend">Ad-spend only — free, no AI</option>
          </Select>
        </Field>
        {mode === "ad_spend" && (
          <Field label="Qualify as ICP when" hint="Which spend-confidence tier still counts as a fit.">
            <Select value={cutoff} onChange={(e) => setCfg({ ...cfg, ad_spend_cutoff: e.target.value })}>
              <option value="possible">Likely or possible — lenient, catches more</option>
              <option value="likely">Likely only — strict</option>
            </Select>
          </Field>
        )}
      </FieldGrid>
      <StickyBar note={mode === "ad_spend"
        ? "Ad-spend mode needs the Company Research API enabled in Settings, Integrations, so ad tags can be read. Leads it cannot assess are marked Needs Review, never Non-ICP."
        : ""}>
        <Button loading={busy} onClick={() => save({ icp_mode: mode, ad_spend_cutoff: cutoff }, "Fit mode saved")}>Save fit mode</Button>
      </StickyBar>
    </Section>
  );
}

export default function EnrichConfigPage({ tab }) {
  const { wsParam, me } = useAuth();
  const toast = useToast();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [formatJson, setFormatJson] = useState("");
  const [profileJson, setProfileJson] = useState("");
  const [profileJsonOpen, setProfileJsonOpen] = useState(false);
  const [clientNameError, setClientNameError] = useState("");
  const [reoonKey, setReoonKey] = useState("");
  const [brain, setBrain] = useState({ website: "", material: "", busy: false, done: null, error: "" });
  const [icpB, setIcpB] = useState({ file: null, text: "", website: "", busy: false, done: null });
  const [fmtB, setFmtB] = useState({ instructions: "", busy: false, done: null });
  const [openVars, setOpenVars] = useState(() => new Set());   // which variables are expanded
  const toggleVar = (i) => setOpenVars((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const [varJson, setVarJson] = useState({});                  // index -> { open, text }

  // Paste Client Profile JSON → fills the boxes. Accepts the training-file
  // schema incl. aliases (value_prop → what_we_are_pitching) and keeps extra
  // keys (positioning, core_capabilities) in the stored profile.
  const fillProfileFromJson = () => {
    try {
      const p = JSON.parse(profileJson);
      const merged = { ...(cfg.profile || {}), ...p };
      if (p.value_prop && !p.what_we_are_pitching) merged.what_we_are_pitching = p.value_prop;
      setCfg({ ...cfg, profile: merged, icp_definition: p.icp_definition || cfg.icp_definition });
      setProfileJson(""); setProfileJsonOpen(false);
      toast("Profile fields filled from JSON");
    } catch (e) { toast(`Invalid JSON: ${e.message}`, "bad"); }
  };

  useEffect(() => {
    setCfg(null); setError("");
    if (!wsId) return;
    api(`/api/enrich-lists/config/${wsId}`).then(setCfg).catch((e) => setError(e.message));
  }, [wsId, tab]);

  if (!wsId) return <ErrorBox msg="Pick a specific workspace (top-left) — enrichment config is per client workspace." />;
  if (error) return <ErrorBox msg={error} />;
  if (!cfg) return <Spinner />;

  const save = async (patch, label = "Saved") => {
    setBusy(true);
    try {
      await api(`/api/enrich-lists/config/${wsId}`, { method: "PUT", body: patch });
      toast(label);
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };

  const setProfile = (k, v) => setCfg({ ...cfg, profile: { ...cfg.profile, [k]: v } });
  // A profile placeholder is either a plain string or derived from the profile.
  const ph = (hint) => (typeof hint === "function" ? hint(cfg.profile || {}) : hint);
  const validateClientName = (value) => {
    const length = value.trim().length;
    setClientNameError(length > 0 && length < 3 ? "Client name must be greater than 2 characters." : "");
  };
  const saveProfile = () => {
    const name = cfg.profile?.client_name || "";
    if (name.trim().length > 0 && name.trim().length < 3) {
      validateClientName(name);
      return;
    }
    save({ profile: cfg.profile, skip_title_gate: cfg.skip_title_gate,
      skip_icp: cfg.skip_icp, only_safe: cfg.only_safe, require_research_gate: cfg.require_research_gate,
      reading_level: cfg.reading_level, writer_model: cfg.writer_model,
      research_depth: cfg.research_depth }, "Profile saved");
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
      toast(`${items.length} variable${items.length === 1 ? "" : "s"} loaded`);
    } catch (e) { toast(`Invalid JSON: ${e.message}`, "bad"); }
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
  const addVariable = () => {
    const idx = (cfg.formats || []).length;
    setCfg({ ...cfg, formats: [
      ...(cfg.formats || []),
      { label: "New variable", name: `var_${idx + 1}`, guidance: "",
        template: "", min_words: null, max_words: null, rules: [], examples: [], placeholders: [] }] });
    setOpenVars((s) => new Set(s).add(idx));   // open the new one for editing
  };
  const duplicateVariable = (i) => {
    const src = cfg.formats[i];
    const copy = { ...src, label: `${src.label} (copy)`, name: `${src.name}_copy` };
    const formats = [...cfg.formats]; formats.splice(i + 1, 0, copy);
    setCfg({ ...cfg, formats });
  };
  // Per-variable JSON: clean this ONE variable and refill it from a pasted object.
  // Keeps the current output-key/slug unless the JSON supplies one, so links don't break.
  const fillVarFromJson = (i) => {
    try {
      const parsed = JSON.parse((varJson[i]?.text || "").trim());
      const obj = Array.isArray(parsed) ? parsed[0] : (parsed.variables ? parsed.variables[0] : parsed);
      if (!obj || typeof obj !== "object") throw new Error("No variable object found.");
      const norm = normFormat(obj, i);
      if (!obj.name) norm.name = cfg.formats[i].name;   // preserve existing slug when JSON omits it
      setFmt(i, norm);
      setVarJson((s) => ({ ...s, [i]: { open: false, text: "" } }));
      toast("Variable replaced from JSON");
    } catch (e) { toast(`Invalid JSON: ${e.message}`, "bad"); }
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
    <div className="fpage">
      {tab === "profile" && (
        <>
          <Section first title="Build the client brain from their material"
            hint="Give the AI the client's website and/or paste their case studies & positioning. It reads everything and builds a structured profile — offer, ICP, case studies, and a per-industry problem library. New facts are added, matching records enriched, and pasted corrections update saved fields.">
            <div className="bg-transparent">
              <FieldGrid>
                <Field label="Client website">
                  <input type="url" inputMode="url" value={brain.website}
                    placeholder="Crawled for positioning, services and proof."
                    onChange={(e) => setBrain({ ...brain, website: e.target.value })} />
                </Field>
                <Field label="Extra material" wide>
                  <Area size="lg" value={brain.material}
                    onChange={(e) => setBrain({ ...brain, material: e.target.value })}
                    placeholder="Case studies, decks, positioning — optional." />
                </Field>
              </FieldGrid>
              <div className="fnote-row">
                <div className="flex flex-col items-start gap-1.5">
                  <Button loading={brain.busy} disabled={!brain.website.trim() && !brain.material.trim()}
                    icon={<img src={aiStar} alt="" aria-hidden="true" className="size-8 shrink-0 object-contain" />}
                    onClick={async () => {
                      setBrain((b) => ({ ...b, busy: true, error: "" }));
                      try {
                        const r = await api(`/api/enrich-lists/config/${wsId}/build-profile`,
                          { method: "POST", body: { website: brain.website.trim(), material: brain.material.trim(), merge: true } });
                        setCfg((c) => ({ ...c, profile: r.profile }));
                        setBrain((b) => ({ ...b, busy: false, done: { ...r.counts, pages_crawled: r.pages_crawled, js_rendered: r.js_rendered } }));
                        toast("Profile built — review, then Save");
                      } catch (e) { setBrain((b) => ({ ...b, busy: false, error: e.message })); }
                    }}>
                    {brain.busy ? "Reading & building…" : "Build with AI"}</Button>
                  {brain.error && <>
                    <p role="alert" className="text-xs font-medium text-[color:var(--bad-text)]">{brain.error}</p>
                    <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer"
                      className="text-xs font-medium text-[color:var(--primary)] underline underline-offset-2">AI API integration</a>
                  </>}
                </div>
                {brain.done && (
                  <span className="fstatus ok">
                    ✓ crawled {brain.done.pages_crawled ?? "?"} pages{brain.done.js_rendered ? ` (${brain.done.js_rendered} JS-rendered)` : ""} ·
                    {" "}{brain.done.case_studies} case studies · {brain.done.services ?? 0} services · {brain.done.metrics ?? 0} metrics.
                  </span>
                )}
              </div>
            </div>
          </Section>

          {(() => {
            const p = cfg.profile || {};
            if (!(p.case_studies?.length || p.problem_library?.length || p.services?.length || p.results_metrics?.length)) return null;
            const Row = ({ children }) => <div className="kb-row">{children}</div>;
            return (
              <Section title="Captured knowledge" hint="What the last build read out of their material.">
                {(p.case_studies || []).length > 0 && (
                  <div className="kb-group">
                    <div className="kb-title">Case studies ({p.case_studies.length})</div>
                    {p.case_studies.map((c, i) => (
                      <Row key={i}>
                        <b>{c.client || "—"}</b>{c.industry ? ` · ${c.industry}` : ""}
                        {c.problem ? <div><b>Problem:</b> {c.problem}</div> : null}
                        {c.solution ? <div><b>Solution:</b> {c.solution}</div> : null}
                        {c.outcome ? <div><b>Outcome:</b> {c.outcome}</div> : null}
                        {(c.metrics || []).length ? <div><b>Metrics:</b> {(c.metrics || []).join("; ")}</div> : null}
                      </Row>
                    ))}
                  </div>
                )}
                {(p.services || []).length > 0 && (
                  <div className="kb-group">
                    <div className="kb-title">Services ({p.services.length})</div>
                    <div className="kb-flat">{p.services.join(" · ")}</div>
                  </div>
                )}
                {(p.results_metrics || []).length > 0 && (
                  <div className="kb-group">
                    <div className="kb-title">Key metrics ({p.results_metrics.length})</div>
                    <div className="kb-flat">{p.results_metrics.join(" · ")}</div>
                  </div>
                )}
                {(p.problem_library || []).length > 0 && (
                  <div className="kb-group">
                    <div className="kb-title">Problem library — per industry ({p.problem_library.length})</div>
                    {p.problem_library.map((pl, i) => (
                      <Row key={i}>
                        <b>{pl.industry || "—"}</b>
                        {(pl.pains || []).length ? <div><b>Pains:</b> {(pl.pains || []).join("; ")}</div> : null}
                        {pl.our_angle ? <div><b>Our angle:</b> {pl.our_angle}</div> : null}
                      </Row>
                    ))}
                  </div>
                )}
              </Section>
            );
          })()}

          <Section title="Client Profile"
            hint="Who this workspace's client is and what they sell. The writer grounds every line in this plus the prospect's own site."
            actions={<Button size="sm" variant="ghost" className="border border-[var(--border)] hover:border-[var(--border-strong)]"
              icon={<Braces aria-hidden="true" className="size-3.5 shrink-0" />}
              onClick={() => setProfileJsonOpen((v) => !v)}>
              {profileJsonOpen ? "Hide JSON" : "Paste JSON"}
            </Button>}>
            {profileJsonOpen && (
              <div className="fnote" style={{ marginBottom: 18 }}>
                <Field label="Client Profile JSON" hint="Auto-fills the fields below.">
                  <Area size="md" className="mono" value={profileJson}
                    onChange={(e) => setProfileJson(e.target.value)}
                    placeholder='{"client_name":"Ascendly","service_brief":"…","main_offer":"…","what_we_are_pitching":"…","target_outcome":"…","icp_summary":"…"}' />
                </Field>
                <div className="fnote-row">
                  <Button size="sm" onClick={fillProfileFromJson} disabled={!profileJson.trim()}>Fill fields from JSON</Button>
                </div>
              </div>
            )}
            <FieldGrid>
              {PROFILE_FIELDS.map(([k, label, hint, long]) => (
                <Field key={k} label={label} wide={long}>
                  {long
                    ? <Area size="md" value={cfg.profile?.[k] || ""} placeholder={ph(hint)}
                        onChange={(e) => setProfile(k, e.target.value)} />
                    : <>
                      <Text value={cfg.profile?.[k] || ""} placeholder={ph(hint)}
                        onChange={(e) => {
                          const value = e.target.value;
                          setProfile(k, value);
                          if (k === "client_name" && (value.trim().length === 0 || value.trim().length >= 3)) setClientNameError("");
                        }}
                        onBlur={k === "client_name" ? (e) => validateClientName(e.target.value) : undefined} />
                      {k === "client_name" && clientNameError && (
                        <p role="alert" className="mt-1.5 text-xs font-medium text-[color:var(--bad-text)]">{clientNameError}</p>
                      )}
                    </>}
                </Field>
              ))}
            </FieldGrid>
          </Section>

          <Section title="Pipeline gates" hint="What stops a lead before it reaches the writer.">
            {PIPELINE_TOGGLES.map(([k, text]) => (
              <Toggle key={k} checked={cfg[k]} onChange={(e) => setCfg({ ...cfg, [k]: e.target.checked })}>{text}</Toggle>
            ))}
          </Section>

          <Section title="Writing controls" hint="How the AI writes your personalization, and how deeply it researches each site.">
            <FieldGrid>
              <Field label="Reading level">
                <Select value={cfg.reading_level || "b2 business"}
                  onChange={(e) => setCfg({ ...cfg, reading_level: e.target.value })}>
                  {READING_LEVELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </Select>
              </Field>
              <Field label="Research depth">
                <Select value={cfg.research_depth || "standard"}
                  onChange={(e) => setCfg({ ...cfg, research_depth: e.target.value })}>
                  <option value="standard">Standard (faster, cheaper)</option>
                  <option value="deep">Deep (more pages + more content)</option>
                </Select>
              </Field>
              <Field label="Writer model"
                hint="The default minimizes costly input tokens; upgrade only after comparing the same test leads.">
                <Select value={cfg.writer_model || ""}
                  onChange={(e) => setCfg({ ...cfg, writer_model: e.target.value })}>
                  <option value="">Default ({cfg.writer_model_effective || "server default"})</option>
                  {WRITER_MODELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </Select>
              </Field>
            </FieldGrid>
            <div className={`fstatus ${cfg.ai_enabled ? "" : "bad"}`} style={{ marginTop: 12 }}>
              {cfg.ai_enabled
                ? `● AI on — writing with ${cfg.writer_model_effective}, ICP/extraction with ${cfg.icp_model_effective}.`
                : "● AI is OFF (no OpenAI key) — generation will stop safely instead of producing generic copy. Set OPENAI_API_KEY."}
            </div>
          </Section>

          <Section title="Reoon email verification key"
            hint="Required for real mailbox verification. Without a key, emails are NOT verified and every lead stops as unsafe — they are never falsely marked safe. Find yours under Reoon → API & Integrations.">
            <div className={`fstatus ${cfg.reoon_api_key_set ? "ok" : "bad"}`} style={{ marginBottom: 10 }}>
              {cfg.reoon_api_key_set
                ? `● Key active (${cfg.reoon_key_source === "env" ? "server env" : "workspace"})`
                : "● No key — verification is OFF"}
            </div>
            <FieldGrid>
              <Field label="API key">
                <div className="row">
                  <input type="password" value={reoonKey} placeholder="Paste Reoon API key…"
                    onChange={(e) => setReoonKey(e.target.value)} />
                  <Button disabled={busy || !reoonKey.trim()}
                    onClick={async () => {
                      await save({ reoon_api_key: reoonKey.trim() }, "Reoon key saved");
                      setReoonKey(""); api(`/api/enrich-lists/config/${wsId}`).then(setCfg);
                    }}>Save key</Button>
                  {cfg.reoon_api_key_set && cfg.reoon_key_source === "workspace" && (
                    <Button variant="secondary" disabled={busy}
                      onClick={async () => {
                        await save({ reoon_api_key: "" }, "Reoon key removed");
                        api(`/api/enrich-lists/config/${wsId}`).then(setCfg);
                      }}>Remove</Button>
                  )}
                </div>
              </Field>
            </FieldGrid>
          </Section>

          <StickyBar>
            <Button loading={busy} onClick={saveProfile}>Save profile</Button>
          </StickyBar>
        </>
      )}

      {tab === "icp" && (
        <>
          <AdSpendMode cfg={cfg} setCfg={setCfg} save={save} busy={busy} />

          <Section title="Build the ICP with AI"
            hint="No JSON needed. Click Build ICP with AI to use everything already in the brain — or add more: upload the client's ICP document, paste a description, or give a website.">
            <div className="fnote">
              <FieldGrid>
                <Field label="ICP document" hint="PDF, TXT or Markdown.">
                  <input type="file" accept=".pdf,.txt,.md" onChange={(e) => setIcpB({ ...icpB, file: e.target.files[0] })} />
                </Field>
                <Field label="…or a website">
                  <input type="url" inputMode="url" value={icpB.website} placeholder="https://client.com"
                    onChange={(e) => setIcpB({ ...icpB, website: e.target.value })} />
                </Field>
                <Field label="…or paste a description" hint="Who's a fit, who's not." wide>
                  <Area size="md" value={icpB.text}
                    onChange={(e) => setIcpB({ ...icpB, text: e.target.value })}
                    placeholder="e.g. We target B2B branding agencies with 5–50 staff selling $25k+ projects. Not B2C, not freelancers." />
                </Field>
              </FieldGrid>
              <div className="fnote-row">
                <Button loading={icpB.busy}
                  onClick={async () => {
                    setIcpB((b) => ({ ...b, busy: true }));
                    try {
                      const fd = new FormData();
                      if (icpB.file) fd.append("file", icpB.file);
                      fd.append("text", icpB.text || ""); fd.append("website", icpB.website || "");
                      const res = await fetch(`/api/enrich-lists/config/${wsId}/build-icp`,
                        { method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd });
                      if (!res.ok) throw new Error((await res.json()).detail || "Failed");
                      const r = await res.json();
                      setCfg((c) => ({ ...c, icp_definition: r.icp_json }));
                      setIcpB((b) => ({ ...b, busy: false, done: r.counts }));
                      toast("ICP built — review, then Save");
                    } catch (e) { toast(e.message, "bad"); setIcpB((b) => ({ ...b, busy: false })); }
                  }}>{icpB.busy ? "Reading & building…" : "Build ICP with AI"}</Button>
                {icpB.done && (
                  <span className="fstatus ok">
                    ✓ {icpB.done.categories} fit categories · {icpB.done.rejects} auto-rejects.
                  </span>
                )}
              </div>
            </div>
          </Section>

          <Section title="ICP definition" hint="The source of truth. Plain English works best — describe how to decide fit, what to reject, and what to do when unsure; the classifier reads it as-is. Structured JSON with procedure / icp_categories / hard_non_icp / default also works, but you don't need it. Changes judge leads immediately.">
            <FieldGrid>
              <Field wide>
                <Area size="lg" value={cfg.icp_definition}
                  onChange={(e) => setCfg({ ...cfg, icp_definition: e.target.value })}
                  placeholder={"Describe how to decide fit in plain English, e.g.\n\nWork out what the company SELLS before who they sell to. We're a fit for B2B service providers, agencies, and consultancies whose work needs conversations or proposals. Never reject on the industries they serve. Reject consumer/DTC brands, local consumer services, schools, government, and nonprofits. When the site doesn't say enough, return Needs Review — don't reject on missing info."} />
              </Field>
            </FieldGrid>
          </Section>

          <TitleFilter cfg={cfg} setCfg={setCfg} save={save} busy={busy} />

          <StickyBar>
            <Button loading={busy} onClick={() => save({ icp_definition: cfg.icp_definition }, "ICP saved")}>Save ICP</Button>
          </StickyBar>
        </>
      )}

      {tab === "formats" && (
        <>
          <Section first title="Build formats with AI"
            hint={<>Explain how you want the variables written, in as much or as little detail as you like — it follows
              what you actually said and won't invent rules you didn't give. Train the brain and fill the Client Profile
              first for the best results.
              {(cfg.formats || []).length > 0 && <> With variables already in place it <b>updates just the ones you
              describe and keeps the rest</b>.</>}</>}>
            <div className="fnote">
              <FieldGrid>
                <Field label="Your rules / how you want variables written"
                  hint="Optional — paste your old formats or rules." wide>
                  <Area size="lg" value={fmtB.instructions}
                    onChange={(e) => setFmtB({ ...fmtB, instructions: e.target.value })}
                    placeholder={"e.g. Value proposition = 2 sentences; 2nd starts with 'And, I have seen'. Personalized first line: no more than 1 exclamation, sound natural. Keep it a single connected sentence…"} />
                </Field>
              </FieldGrid>
              <div className="fnote-row">
                <Button loading={fmtB.busy}
                  onClick={async () => {
                    setFmtB((b) => ({ ...b, busy: true }));
                    try {
                      const r = await api(`/api/enrich-lists/config/${wsId}/build-formats`,
                        { method: "POST", body: { instructions: fmtB.instructions, current: cfg.formats || [], merge: fmtB.merge !== false } });
                      setCfg((c) => ({ ...c, formats: r.formats }));
                      setFmtB((b) => ({ ...b, busy: false, done: r.merged ? `updated ${r.updated.length} (${r.updated.join(", ")})` : `${r.count} built` }));
                      toast("Formats built — review, then Save");
                    } catch (e) { toast(e.message, "bad"); setFmtB((b) => ({ ...b, busy: false })); }
                  }}>
                  {fmtB.busy ? "Working…" : ((cfg.formats || []).length > 0 && fmtB.merge !== false ? "Update formats with AI" : "Build formats with AI")}</Button>
                {(cfg.formats || []).length > 0 && (
                  <label className="fchk" style={{ padding: 0, border: "none" }}>
                    <input type="checkbox" checked={fmtB.merge === false}
                      onChange={(e) => setFmtB({ ...fmtB, merge: !e.target.checked })} />
                    <span>Rebuild all from scratch (replace)</span>
                  </label>)}
                {fmtB.done != null && <span className="fstatus ok">✓ {fmtB.done}.</span>}
              </div>
            </div>
          </Section>

          <Section title="Paste Format JSON" hint="Advanced. A bare array of variables, or { variables: [...], global_output_rules: [...] }. Each variable: label, guidance, template, min/max words, rules, examples, and placeholders."
            actions={<Button size="sm" variant="ghost" onClick={downloadFormats}>Download JSON</Button>}>
            <FieldGrid>
              <Field wide>
                <Area size="lg" className="mono" value={formatJson}
                  onChange={(e) => setFormatJson(e.target.value)}
                  placeholder='[{"label":"Value Proposition","guidance":"…","template":"We help {{industry}} {{result}}.","min_words":15,"max_words":30,"placeholders":[{"token":"industry","description":"the prospect category","examples":["marketing agencies"]}]}]' />
              </Field>
            </FieldGrid>
            <div className="fnote-row">
              <Button size="sm" variant="secondary" disabled={!formatJson.trim()} onClick={() => fillFromJson(false)}>Replace with JSON</Button>
              <Button size="sm" variant="ghost" disabled={!formatJson.trim()} onClick={() => fillFromJson(true)}>Add to existing</Button>
            </div>
          </Section>

          <Section title={`Variables (${(cfg.formats || []).length})`}
            hint="One per output column. Collapsed by default — open the one you are working on."
            actions={<>
              <Button size="sm" variant="ghost" onClick={addVariable}>+ Add variable</Button>
              {(cfg.formats || []).length > 1 && (
                <Button size="sm" variant="ghost"
                  onClick={() => setOpenVars((s) => (s.size ? new Set() : new Set((cfg.formats || []).map((_, i) => i))))}>
                  {openVars.size ? "Collapse all" : "Expand all"}</Button>
              )}
            </>}>
            {(cfg.formats || []).length === 0 && (
              <p className="fstatus">No variables yet. Build them with AI above, paste JSON, or add one by hand.</p>
            )}
            {(cfg.formats || []).map((f, i) => {
              const open = openVars.has(i);
              const vj = varJson[i] || {};
              return (
                <div className={`fvar ${open ? "open" : ""}`} key={i}>
                  <div className="fvar-head" onClick={() => toggleVar(i)}>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
                      style={{ transform: open ? "" : "rotate(-90deg)", transition: "transform .15s", flexShrink: 0 }}>
                      <path d="M6 9l6 6 6-6" /></svg>
                    <b>{f.label || "Untitled variable"}</b>
                    <code>{f.name}</code>
                    {f.template ? <span className="badge indigo">template</span> : null}
                    {f.enabled === false && <span className="badge gray">off</span>}
                    <label onClick={(e) => e.stopPropagation()} className="fvar-write">
                      <input type="checkbox" checked={f.enabled !== false}
                        onChange={(e) => setFmt(i, { enabled: e.target.checked })} /> Write
                    </label>
                    <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); duplicateVariable(i); }}>Duplicate</Button>
                    <Button size="sm" variant="danger"
                      onClick={(e) => { e.stopPropagation(); setCfg({ ...cfg, formats: cfg.formats.filter((_, j) => j !== i) }); }}>Remove</Button>
                  </div>

                  {open && (
                    <div className="fvar-body">
                      <FieldGrid>
                        <Field label="Variable name">
                          <Text value={f.label || ""} placeholder="Personalized First Line"
                            onChange={(e) => setFmt(i, { label: e.target.value, name: slug(e.target.value, i) })} />
                        </Field>
                        <Field label="Output key (slug)">
                          <Text className="mono" value={f.name || ""} placeholder="personalized_first_line"
                            onChange={(e) => setFmt(i, { name: e.target.value })} />
                        </Field>

                        <Field label="How to write it — guidance" wide>
                          <Area size="md" value={f.guidance}
                            onChange={(e) => setFmt(i, { guidance: e.target.value })}
                            placeholder="Explain in plain words how this should be written. e.g. One sentence on a specific, real detail from the prospect's site. No pitch. No greeting." />
                        </Field>

                        <Field label="Fallback"
                          hint="Optional — written when the info for this variable isn't available. Leave blank to skip the variable when there's nothing to say."
                          wide>
                          <Area size="sm" value={f.fallback || ""}
                            onChange={(e) => setFmt(i, { fallback: e.target.value })}
                            placeholder="e.g. If no specific site detail, reference their industry and one common goal for that industry." />
                        </Field>

                        <Field label="Rules for this variable" hint="One rule per line — obeyed while writing THIS variable." wide>
                          <Area size="md" value={(f.rules || []).join("\n")}
                            onChange={(e) => setFmt(i, { rules: e.target.value.split("\n") })}
                            placeholder={"Start with a concrete observation, not praise.\nNever end with a question mark.\nDo not use the words 'impressive' or 'world-class'."} />
                        </Field>

                        <Field label="Format template"
                          hint={`Optional — leave blank for free-form variables. Use {{placeholders}} for fill-in-the-blank parts.`} wide>
                          <Area size="sm" value={f.template || ""}
                            onChange={(e) => setTemplate(i, e.target.value)}
                            placeholder="We help {{industry}} get {{ideal_customers}} by {{what_we_do}}." />
                        </Field>

                        <Field label="Word range — minimum">
                          <Num value={f.min_words ?? ""} min={0}
                            onChange={(e) => setFmt(i, { min_words: Number(e.target.value) || null })} />
                        </Field>
                        <Field label="Word range — maximum">
                          <Num value={f.max_words ?? ""} min={0}
                            onChange={(e) => setFmt(i, { max_words: Number(e.target.value) || null })} />
                        </Field>

                        <Field label="Examples" hint="One per line — sample outputs that show the AI what good looks like." wide>
                          <Area size="md" value={(f.examples || []).join("\n")}
                            onChange={(e) => setFmt(i, { examples: e.target.value.split("\n") })}
                            placeholder={"Your work for Acme Dental shows a clear focus on local clinics.\nThe way you bundle SEO with paid search is a sharp combo for B2B teams."} />
                        </Field>
                      </FieldGrid>

                      {/* Placeholders — one explanation per {{token}} in the template. */}
                      <div className="fsub">
                        <div className="fsub-title">Placeholders</div>
                        {(f.placeholders || []).length === 0 ? (
                          <p className="fstatus">Add {"{{placeholders}}"} in the template above to describe them here.</p>
                        ) : f.placeholders.map((p, ti) => (
                          <div className="fph" key={p.token}>
                            <div className="fph-tok">
                              {"{{"}{p.token}{"}}"}
                              {AUTO_TOKENS.has(p.token.toLowerCase()) && <em> · lead field, filled automatically</em>}
                            </div>
                            <FieldGrid>
                              <Field label="How to write this placeholder" wide>
                                <Area size="sm" value={p.description || ""}
                                  onChange={(e) => setPh(i, ti, { description: e.target.value })}
                                  placeholder="What goes here and how to phrase it" />
                              </Field>
                              <Field label="Words — minimum">
                                <Num value={p.min_words ?? ""} min={0}
                                  onChange={(e) => setPh(i, ti, { min_words: Number(e.target.value) || null })} />
                              </Field>
                              <Field label="Words — maximum">
                                <Num value={p.max_words ?? ""} min={0}
                                  onChange={(e) => setPh(i, ti, { max_words: Number(e.target.value) || null })} />
                              </Field>
                              <Field label="Examples" hint="One per line." wide>
                                <Area size="sm" value={(p.examples || []).join("\n")}
                                  onChange={(e) => setPh(i, ti, { examples: e.target.value.split("\n") })}
                                  placeholder={"book more sales calls\ncut response time"} />
                              </Field>
                            </FieldGrid>
                          </div>
                        ))}
                      </div>

                      <div className="fsub">
                        <Button size="sm" variant="ghost"
                          onClick={() => setVarJson((s) => ({ ...s, [i]: { ...vj, open: !vj.open } }))}>
                          {vj.open ? "Hide JSON" : "⤓ Paste JSON for this variable"}</Button>
                        {vj.open && (
                          <>
                            <FieldGrid>
                              <Field wide>
                                <Area size="md" className="mono" value={vj.text || ""}
                                  onChange={(e) => setVarJson((s) => ({ ...s, [i]: { ...vj, text: e.target.value } }))}
                                  placeholder='{"label":"Value Proposition","guidance":"…","template":"We help {{industry}} {{result}}.","min_words":15,"max_words":30,"rules":["…"],"examples":["…"],"placeholders":[{"token":"industry","description":"the prospect category","min_words":2,"max_words":5,"examples":["marketing agencies"]}]}' />
                              </Field>
                            </FieldGrid>
                            <div className="fnote-row">
                              <Button size="sm" onClick={() => fillVarFromJson(i)}>Clean &amp; fill this variable</Button>
                              <span className="fstatus">Replaces only this variable.</span>
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </Section>

          <StickyBar>
            <Button loading={busy} onClick={() => save({ formats: cleanFormats(cfg.formats) }, "Formats saved")}>Save formats</Button>
          </StickyBar>
        </>
      )}

      {tab === "rules" && (
        <>
          <Section first title="Correction rules"
            hint="One rule per line, plain English. Every line is injected into the writer on every enrichment — use it to correct mistakes without touching code. Example: “Never start two variables with the same word.”">
            <FieldGrid>
              <Field wide>
                <Area size="lg" value={cfg.rules}
                  onChange={(e) => setCfg({ ...cfg, rules: e.target.value })}
                  placeholder={"Never start two variables with the same word.\nDon't use the word 'leverage'.\nUK spelling."} />
              </Field>
            </FieldGrid>
          </Section>

          <StickyBar>
            <Button loading={busy} onClick={() => save({ rules: cfg.rules }, "Rules saved")}>Save rules</Button>
          </StickyBar>
        </>
      )}
    </div>
  );
}
