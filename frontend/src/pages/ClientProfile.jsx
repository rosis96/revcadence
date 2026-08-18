// CRM → Company → Client Profile: the operational source of truth. Structured,
// editable sections (never one giant JSON box); provenance + visibility per field;
// scope-specific onboarding with immutable submissions and conflict review; a Raw
// JSON view lives under Advanced.
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";
import { useAppPath } from "../clientspace/appPath";
import { Area, Badge, Breadcrumbs, ErrorBox, PageHeader, Spinner, StatusPill, useApi } from "../components";
import { alertDialog } from "../components";
import { Select } from "../components";

const TABS = [
  ["overview", "Offer"], ["icp", "ICP"], ["sales_process", "Sales Process"],
  ["delivery_scope", "Delivery Scope"], ["messaging", "Messaging"],
  ["onboarding_info", "Onboarding"], ["_onboarding", "Onboarding Form"],
  ["_docs", "Documents"], ["_raw", "Advanced (Raw)"],
];

export default function ClientProfile() {
  const appTo = useAppPath();
  const { id } = useParams();               // company id
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("overview");

  const load = () => {
    setLoading(true);
    api(`/api/client-profiles/${id}`).then((d) => { setP(d); setErr(""); })
      .catch((e) => setErr(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, [id]);

  const activate = async () => {
    try { setP(await api(`/api/client-profiles/${id}/activate`, { method: "POST", body: {} })); setErr(""); }
    catch (e) { alertDialog(e.message); }
  };

  if (loading) return <Spinner />;
  if (err && err.includes("No client profile")) {
    return (
      <div className="card" style={{ padding: 24, maxWidth: 560 }}>
        <h2 style={{ marginTop: 0 }}>No client profile yet</h2>
        <p style={{ color: "var(--muted)" }}>Created automatically when a deal for this company moves to a
          <b> Won</b> stage. You can also create it now.</p>
        <button className="btn" onClick={activate}>Activate client & build profile</button>
      </div>
    );
  }
  if (err) return <ErrorBox msg={err} retry={load} />;
  if (!p) return <Spinner />;

  const secDef = (p.sections || []).find((s) => s.key === tab);

  const setField = async (section, field, value, visibility) => {
    try { setP(await api(`/api/client-profiles/${id}/field`, { method: "PUT", body: { section, field, value, visibility } })); }
    catch (e) { alertDialog(e.message); }
  };
  const setScope = async (scope_type) => {
    try { setP(await api(`/api/client-profiles/${id}/scope`, { method: "PUT", body: { scope_type } })); }
    catch (e) { alertDialog(e.message); }
  };

  return (
    <div style={{ maxWidth: 1000 }}>
      <Breadcrumbs items={[{ label: "Companies", href: appTo("/companies") }, { label: "Company", href: appTo(`/companies/${id}`) }, { label: "Client Profile" }]} />
      <PageHeader
        title={<span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
          Client Profile
          <StatusPill tone={p.is_active_client ? "green" : "amber"}>{p.is_active_client ? "active client" : "prospect"}</StatusPill>
        </span>}
        desc="The operational source of truth for this engagement."
        actions={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <label style={{ fontSize: 12.5, color: "var(--muted)" }}>Scope</label>
            <Select value={p.scope_type} onChange={(e) => setScope(e.target.value)}>
              <option value="outbound">Outbound</option><option value="inbound">Inbound</option><option value="full">Full engine</option>
            </Select>
            <Link className="btn ghost sm" to={appTo(`/companies/${id}`)}>← Company</Link>
          </span>
        } />

      {/* completeness + onboarding status */}
      <div className="card" style={{ padding: 14, marginBottom: 14, display: "flex", gap: 20, alignItems: "center" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Onboarding completeness · {p.completeness}%</div>
          <div style={{ height: 8, background: "var(--progress-track)", borderRadius: 6, overflow: "hidden" }}>
            <div style={{ width: `${p.completeness}%`, height: "100%", background: "var(--accent, #635BFF)" }} />
          </div>
        </div>
        <Badge tone={p.onboarding_status === "approved" ? "green" : "blue"}>{p.onboarding_status}</Badge>
        {(p.review_flags || []).length > 0 && <Badge tone="amber">{p.review_flags.length} to review</Badge>}
        {p.onboarding_status !== "approved" &&
          <button className="btn sm" onClick={() => api(`/api/client-profiles/${id}/approve`, { method: "POST" }).then(setP)}>Approve</button>}
      </div>

      <div className="tabs" style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {TABS.map(([k, label]) => (
          <button key={k} className={`btn ${tab === k ? "" : "ghost"} sm`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {/* structured section editors */}
      {secDef && (
        <div className="card" style={{ padding: 18 }}>
          <h2 style={{ fontSize: 15, marginBottom: 12 }}>{secDef.label}</h2>
          {secDef.fields.map((f) => {
            const cell = ((p.data || {})[tab] || {})[f.key] || {};
            return (
              <div className="field" key={f.key} style={{ marginBottom: 12 }}>
                <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {f.label}
                  <span className="badge" style={{ background: f.visibility === "client" ? "var(--ok-soft)" : "var(--primary-soft)",
                        color: f.visibility === "client" ? "var(--ok-text)" : "var(--primary)", fontSize: 10.5 }}>
                    {f.visibility === "client" ? "client-visible" : "internal"}</span>
                  {cell.source && <span style={{ fontSize: 11, color: "var(--muted)" }}>· from {cell.source}{cell.at ? ` · ${new Date(cell.at + "Z").toLocaleDateString()}` : ""}</span>}
                </label>
                <Area size="md" style={{ width: "100%" }} defaultValue={cell.value || ""}
                          onBlur={(e) => { if ((e.target.value || "") !== (cell.value || "")) setField(tab, f.key, e.target.value, f.visibility); }} />
              </div>
            );
          })}
        </div>
      )}

      {tab === "_onboarding" && <OnboardingTab p={p} id={id} setP={setP} />}
      {tab === "_docs" && <DocsTab companyId={id} />}
      {tab === "_raw" && (
        <div className="card" style={{ padding: 16 }}>
          <p style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 0 }}>Read-only raw profile data (provenance included).</p>
          <pre style={{ fontSize: 11.5, overflow: "auto", maxHeight: "60vh" }}>{JSON.stringify(p.data, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function OnboardingTab({ p, id, setP }) {
  const [ans, setAns] = useState({});
  const submit = async () => {
    try { const r = await api(`/api/client-profiles/${id}/onboarding-submit`, { method: "POST", body: { answers: ans, submitted_by: "internal" } });
      setP(r); setAns({}); alertDialog(`Saved: ${r.applied} applied, ${r.flagged} flagged for review.`); }
    catch (e) { alertDialog(e.message); }
  };
  const resolve = async (index, accept) => {
    try { setP(await api(`/api/client-profiles/${id}/resolve-flag`, { method: "POST", body: { index, accept } })); }
    catch (e) { alertDialog(e.message); }
  };
  const fields = (p.onboarding_form || {}).fields || [];
  return (
    <>
      {(p.review_flags || []).length > 0 && (
        <div className="card" style={{ padding: 16, marginBottom: 12, borderColor: "var(--amber, #f0b429)" }}>
          <h2 style={{ fontSize: 14, marginTop: 0 }}>Conflicts to review ({p.review_flags.length})</h2>
          {p.review_flags.map((f, i) => (
            <div key={i} style={{ borderTop: i ? "1px solid var(--line, #eee)" : "none", padding: "8px 0", fontSize: 12.5 }}>
              <b>{f.field}</b><br />
              <span style={{ color: "var(--muted)" }}>current:</span> {f.existing}<br />
              <span style={{ color: "var(--muted)" }}>submitted:</span> {f.submitted}
              <div style={{ marginTop: 6 }}>
                <button className="btn sm" onClick={() => resolve(i, true)}>Use submitted</button>{" "}
                <button className="btn ghost sm" onClick={() => resolve(i, false)}>Keep current</button>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ fontSize: 15, marginTop: 0 }}>Onboarding form <span style={{ color: "var(--muted)", fontWeight: 400, fontSize: 12.5 }}>({p.onboarding_form?.scope_type} scope · {p.submissions_count} submissions on file)</span></h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5 }}>Only questions relevant to what they bought are shown. Answers fill empty fields; anything that conflicts with existing data is flagged, never overwritten.</p>
        {fields.map((f) => (
          <div className="field" key={f.target}><label>{f.label}</label>
            <Area size="md" style={{ width: "100%" }} value={ans[f.target] || ""}
                      onChange={(e) => setAns({ ...ans, [f.target]: e.target.value })} /></div>
        ))}
        <button className="btn" style={{ marginTop: 8 }} onClick={submit}>Submit onboarding answers</button>
      </div>
    </>
  );
}

function publicUrl(slug) {
  if (!slug) return "";
  const host = window.location.host;
  const bpHost = host.startsWith("engine.") ? host.replace(/^engine\./, "blueprint.") : "";
  return bpHost ? `https://${bpHost}/${slug}` : `${window.location.origin}/p/${slug}`;
}
const docIcon = { blueprint: "▤", agreement: "✍", proposal: "▧" };

function DocsTab({ companyId }) {
  const appTo = useAppPath();
  const { data: docs, loading } = useApi("/api/documents", { company_id: companyId });
  const { data: ags } = useApi("/api/agreements", { company_id: companyId });
  const { data: invs } = useApi("/api/invoices", { company_id: companyId });
  const [copied, setCopied] = useState("");
  return (
    <>
    {(ags && ags.length > 0) && (
      <div className="card" style={{ padding: 18, marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, marginTop: 0 }}>Agreements</h2>
        {ags.map((ag, i) => (
          <div key={ag.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: i ? "1px solid var(--line,#eee)" : "none" }}>
            <span>✍</span>
            <div style={{ flex: 1 }}><b>{ag.number}</b> <span style={{ color: "var(--muted)", fontSize: 12 }}>v{ag.version}</span></div>
            <Badge tone={ag.status === "executed" ? "green" : "blue"}>{ag.status}</Badge>
            <Link className="btn ghost sm" to={appTo(`/agreements/${ag.id}`)}>Open</Link>
          </div>
        ))}
      </div>
    )}
    {(invs && invs.length > 0) && (
      <div className="card" style={{ padding: 18, marginBottom: 12 }}>
        <h2 style={{ fontSize: 15, marginTop: 0 }}>Invoices</h2>
        {invs.map((iv, i) => (
          <div key={iv.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: i ? "1px solid var(--line,#eee)" : "none" }}>
            <span>▧</span>
            <div style={{ flex: 1 }}><b>{iv.number}</b> <span style={{ color: "var(--muted)", fontSize: 12 }}>{iv.currency} {(iv.total || 0).toLocaleString()}</span></div>
            <Badge tone={iv.status === "paid" ? "green" : "blue"}>{iv.status}</Badge>
            <Link className="btn ghost sm" to={appTo(`/invoices/${iv.id}`)}>Open</Link>
          </div>
        ))}
      </div>
    )}
    <div className="card" style={{ padding: 18 }}>
      <h2 style={{ fontSize: 15, marginTop: 0 }}>Blueprints &amp; documents</h2>
      {loading && <Spinner />}
      {docs && docs.length === 0 && (
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          No blueprints or agreements yet. <Link to={appTo(`/companies/${companyId}`)}>Build or upload one from the company →</Link>
        </span>
      )}
      {docs && docs.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {docs.map((d, i) => {
            const url = publicUrl(d.slug);
            return (
              <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0",
                                       borderTop: i ? "1px solid var(--line,#eee)" : "none" }}>
                <span style={{ fontSize: 16 }}>{docIcon[d.kind] || "▤"}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>{d.title || d.slug}</div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{d.kind}{d.generator === "uploaded" ? " · uploaded" : ""} · {d.view_count} views</div>
                </div>
                <Badge tone={d.published ? "green" : "amber"}>{d.published ? "published" : d.status}</Badge>
                {d.published && d.slug && (
                  <>
                    <button className="btn ghost sm" onClick={() => { navigator.clipboard?.writeText(url); setCopied(d.slug); setTimeout(() => setCopied(""), 1500); }}>
                      {copied === d.slug ? "Copied ✓" : "Copy link"}</button>
                    <a className="btn ghost sm" href={url} target="_blank" rel="noreferrer">Open ↗</a>
                  </>
                )}
                <Link className="btn ghost sm" to={appTo(`/blueprints/${d.id}`)}>Edit</Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
    </>
  );
}
