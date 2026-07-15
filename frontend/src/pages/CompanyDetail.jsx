import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, money } from "../api";
import { Badge, ErrorBox, Modal, Spinner, Timeline, fitTone, scoreTone, useApi } from "../components";
import { StatusPill } from "./Companies";

// Public blueprint/agreement URL — prefer a blueprint.<domain> host on engine.<domain>.
function publicUrl(slug) {
  if (!slug) return "";
  const host = window.location.host;
  const bpHost = host.startsWith("engine.") ? host.replace(/^engine\./, "blueprint.") : "";
  return bpHost ? `https://${bpHost}/${slug}` : `${window.location.origin}/p/${slug}`;
}
const docIcon = { blueprint: "▤", agreement: "✍", proposal: "▧" };

export default function CompanyDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: c, error, loading, reload } = useApi(`/api/companies/${id}`);
  const { data: ags, reload: reloadAgs } = useApi(`/api/agreements`, { company_id: id });
  const { data: invs } = useApi(`/api/invoices`, { company_id: id });
  const [busy, setBusy] = useState("");
  const [fathom, setFathom] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [upload, setUpload] = useState(false);
  const [upTitle, setUpTitle] = useState("");
  const [upHtml, setUpHtml] = useState("");
  const [upFileName, setUpFileName] = useState("");
  const [copied, setCopied] = useState("");

  const enrich = async () => {
    setBusy("enrich");
    try {
      await api("/api/enrich", { method: "POST", body: { workspace_id: c.workspace_id, company_ids: [c.id] } });
      alert("Enrichment queued — watch Jobs, then refresh this page.");
    } catch (e) { alert(e.message); }
    setBusy("");
  };
  const [edit, setEdit] = useState(null);   // edit form when open
  const saveEdit = async () => {
    try { await api(`/api/companies/${id}`, { method: "PUT", body: edit }); setEdit(null); reload(); }
    catch (e) { alert(e.message); }
  };
  const removeCompany = async () => {
    if (!confirm(`Delete "${c.name}" and all its contacts, deals, documents & profile? This can't be undone.`)) return;
    try { await api(`/api/companies/${id}`, { method: "DELETE" }); nav("/companies"); }
    catch (e) { alert(e.message); }
  };
  // Build a blueprint straight from a Fathom call transcript for THIS company.
  const buildFromTranscript = async () => {
    if (!transcript.trim()) { alert("Paste the call transcript first."); return; }
    setBusy("bp");
    try {
      const doc = await api("/api/blueprints/from-transcript", { method: "POST",
        body: { workspace_id: c.workspace_id, company_id: c.id, transcript } });
      nav(`/blueprints/${doc.id}`);
    } catch (e) { alert(e.message); }
    setBusy("");
  };
  // Upload a custom HTML blueprint for THIS company.
  const onUpFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setUpFileName(f.name);
    const r = new FileReader();
    r.onload = () => { setUpHtml(String(r.result || "")); if (!upTitle) setUpTitle(f.name.replace(/\.(html?|htm)$/i, "")); };
    r.readAsText(f);
  };
  const uploadBlueprint = async () => {
    if (!upHtml.trim()) { alert("Choose an HTML file or paste the markup first."); return; }
    setBusy("up");
    try {
      const doc = await api("/api/blueprints/upload", { method: "POST",
        body: { workspace_id: c.workspace_id, company_id: c.id, title: upTitle || null, html: upHtml } });
      nav(`/blueprints/${doc.id}`);
    } catch (e) { alert(e.message); }
    setBusy("");
  };
  const newAgreement = async () => {
    setBusy("agr");
    try {
      const deal = (c.deals || [])[0];
      const ag = await api("/api/agreements/generate", { method: "POST",
        body: { workspace_id: c.workspace_id, company_id: c.id, deal_id: deal ? deal.id : null } });
      nav(`/agreements/${ag.id}`);
    } catch (e) { alert(e.message); }
    setBusy("");
  };
  const newInvoice = async () => {
    setBusy("inv");
    try {
      const inv = await api("/api/invoices", { method: "POST",
        body: { workspace_id: c.workspace_id, company_id: c.id } });
      nav(`/invoices/${inv.id}`);
    } catch (e) { alert(e.message); }
    setBusy("");
  };
  const AGR_TONE = { draft: "", ready: "blue", sent: "blue", viewed: "indigo", client_signed: "amber", countersigned: "amber", executed: "green", voided: "red", archived: "" };
  const INV_TONE = { draft: "", issued: "blue", viewed: "indigo", partially_paid: "amber", paid: "green", overdue: "red", void: "" };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const enrichmentRows = Object.entries(c.enrichment || {}).filter(([k]) => k !== "last_crawl");
  return (
    <>
      <div className="toolbar">
        <h1 style={{ fontSize: 20 }}>{c.name}</h1>
        {c.status && <StatusPill status={c.status} />}
        {c.icp_fit && <Badge tone={fitTone(c.icp_fit)}>ICP: {c.icp_fit}</Badge>}
        <div className="spacer" />
        <button className="btn ghost" onClick={reload}>Refresh</button>
        <button className="btn ghost" onClick={() => setEdit({ name: c.name, website: c.website || "", industry: c.industry || "", location: c.location || "" })}>Edit</button>
        <button className="btn ghost" disabled={!!busy} onClick={enrich}>{busy === "enrich" ? "Queueing…" : "✦ Enrich"}</button>
        <button className="btn ghost" onClick={() => nav(`/companies/${id}/profile`)}>◎ Client Profile</button>
        <button className="btn" onClick={() => setFathom(true)}>▤ Blueprint from transcript</button>
        <button className="btn ghost" onClick={() => setUpload(true)}>⬆ Upload blueprint</button>
        <button className="btn danger" onClick={removeCompany}>Delete</button>
      </div>

      {edit && (
        <Modal title={`Edit ${c.name}`} onClose={() => setEdit(null)}>
          <div className="field"><label>Name</label>
            <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></div>
          <div className="field"><label>Website</label>
            <input value={edit.website} onChange={(e) => setEdit({ ...edit, website: e.target.value })} /></div>
          <div className="field"><label>Industry</label>
            <input value={edit.industry} onChange={(e) => setEdit({ ...edit, industry: e.target.value })} /></div>
          <div className="field"><label>Location</label>
            <input value={edit.location} onChange={(e) => setEdit({ ...edit, location: e.target.value })} /></div>
          <div className="actions">
            <button type="button" className="btn ghost" onClick={() => setEdit(null)}>Cancel</button>
            <button className="btn" onClick={saveEdit}>Save</button>
          </div>
        </Modal>
      )}

      {fathom && (
        <Modal title={`Build a blueprint for ${c.name}`} onClose={() => setFathom(false)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            Paste the Fathom call transcript (or summary). Every section is generated from what was discussed;
            pricing is only used if it came up on the call. You can edit and publish on the next screen.</p>
          <div className="field"><label>Fathom transcript</label>
            <textarea rows={12} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                      value={transcript} onChange={(e) => setTranscript(e.target.value)}
                      placeholder="Paste transcript here…" autoFocus /></div>
          <div className="actions">
            <button type="button" className="btn ghost" onClick={() => setFathom(false)}>Cancel</button>
            <button className="btn" disabled={busy === "bp"} onClick={buildFromTranscript}>
              {busy === "bp" ? "Generating…" : "Generate blueprint"}</button>
          </div>
        </Modal>
      )}

      {upload && (
        <Modal title={`Upload a custom blueprint for ${c.name}`} onClose={() => setUpload(false)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            Bring your own page — upload an HTML file (or paste the markup) you built outside the system.
            It gets its own slug and public link, and publishes exactly like a generated blueprint.</p>
          <div className="field"><label>Title</label>
            <input value={upTitle} onChange={(e) => setUpTitle(e.target.value)}
                   placeholder={`${c.name} — Growth Blueprint`} /></div>
          <div className="field"><label>HTML file</label>
            <input type="file" accept=".html,.htm,text/html" onChange={onUpFile} />
            {upFileName && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Loaded: {upFileName} ({upHtml.length.toLocaleString()} chars)</div>}
          </div>
          <div className="field"><label>…or paste HTML</label>
            <textarea rows={8} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                      value={upHtml} onChange={(e) => { setUpHtml(e.target.value); setUpFileName(""); }}
                      placeholder="<!doctype html> …" /></div>
          <div className="actions">
            <button type="button" className="btn ghost" onClick={() => setUpload(false)}>Cancel</button>
            <button className="btn" disabled={busy === "up"} onClick={uploadBlueprint}>
              {busy === "up" ? "Uploading…" : "Create blueprint"}</button>
          </div>
        </Modal>
      )}

      <div className="grid" style={{ gridTemplateColumns: "1.2fr .8fr", alignItems: "start" }}>
        <div>
          <div className="card" style={{ padding: 16 }}>
            <div className="kv" style={{ margin: 0 }}>
              <div className="k">Website</div><div>{c.website ? <a href={c.website.startsWith("http") ? c.website : `https://${c.website}`} target="_blank" rel="noreferrer">{c.website}</a> : "—"}</div>
              <div className="k">Industry</div><div>{c.industry || "—"}</div>
              <div className="k">Location</div><div>{c.location || "—"}</div>
            </div>
          </div>

          <div className="section">
            <h2>Blueprints &amp; documents</h2>
            {(!c.documents || c.documents.length === 0) ? (
              <div className="card empty">No blueprints or agreements yet — use “Blueprint from transcript” or “Upload blueprint” above.</div>
            ) : (
              <div className="card" style={{ padding: 0 }}>
                {c.documents.map((d, i) => {
                  const url = publicUrl(d.slug);
                  return (
                    <div key={d.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                                             borderTop: i ? "1px solid var(--line,#eee)" : "none" }}>
                      <span style={{ fontSize: 16 }}>{docIcon[d.kind] || "▤"}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 13.5 }}>{d.title || d.slug}</div>
                        <div style={{ fontSize: 11.5, color: "var(--muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {d.kind}{d.generator === "uploaded" ? " · uploaded" : ""} · {d.view_count} views · {url}
                        </div>
                      </div>
                      <Badge tone={d.published ? "green" : "amber"}>{d.published ? "published" : d.status}</Badge>
                      {d.published && d.slug && (
                        <>
                          <button className="btn ghost sm" onClick={() => { navigator.clipboard?.writeText(url); setCopied(d.slug); setTimeout(() => setCopied(""), 1500); }}>
                            {copied === d.slug ? "Copied ✓" : "Copy link"}</button>
                          <a className="btn ghost sm" href={url} target="_blank" rel="noreferrer">Open ↗</a>
                        </>
                      )}
                      <button className="btn ghost sm" onClick={() => nav(`/blueprints/${d.id}`)}>Edit</button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="section">
            <div style={{ display: "flex", alignItems: "center" }}>
              <h2 style={{ flex: 1 }}>Agreements</h2>
              <button className="btn ghost sm" disabled={busy === "agr"} onClick={newAgreement}>{busy === "agr" ? "Generating…" : "+ New agreement"}</button>
            </div>
            {(!ags || ags.length === 0) ? (
              <div className="card empty">No agreements yet — generate one from the blueprint/deal.</div>
            ) : (
              <div className="card" style={{ padding: 0 }}>
                {ags.map((ag, i) => (
                  <div key={ag.id} className="click" onClick={() => nav(`/agreements/${ag.id}`)}
                       style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderTop: i ? "1px solid var(--line,#eee)" : "none" }}>
                    <span style={{ fontSize: 15 }}>✍</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>{ag.number} · {ag.title}</div>
                      <div style={{ fontSize: 11.5, color: "var(--muted)" }}>v{ag.version}{ag.is_current ? "" : " (superseded)"} · {ag.view_count} views{ag.executed_at ? " · executed" : ""}</div>
                    </div>
                    <Badge tone={AGR_TONE[ag.status] || ""}>{ag.status}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="section">
            <div style={{ display: "flex", alignItems: "center" }}>
              <h2 style={{ flex: 1 }}>Invoices</h2>
              <button className="btn ghost sm" disabled={busy === "inv"} onClick={newInvoice}>{busy === "inv" ? "Creating…" : "+ New invoice"}</button>
            </div>
            {(!invs || invs.length === 0) ? (
              <div className="card empty">No invoices yet.</div>
            ) : (
              <div className="card" style={{ padding: 0 }}>
                {invs.map((iv, i) => (
                  <div key={iv.id} className="click" onClick={() => nav(`/invoices/${iv.id}`)}
                       style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderTop: i ? "1px solid var(--line,#eee)" : "none" }}>
                    <span style={{ fontSize: 15 }}>▧</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>{iv.number}</div>
                      <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{iv.currency} {(iv.total || 0).toLocaleString()} · balance {iv.currency} {(iv.balance_due || 0).toLocaleString()}</div>
                    </div>
                    <Badge tone={INV_TONE[iv.status] || ""}>{iv.status}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="section">
            <h2>Enrichment data</h2>
            {enrichmentRows.length === 0 ? (
              <div className="card empty">Not enriched yet — click Enrich above.</div>
            ) : (
              <table className="tbl">
                <thead><tr><th>Field</th><th>Value</th><th>Source</th></tr></thead>
                <tbody>
                  {enrichmentRows.map(([k, v]) => (
                    <tr key={k}>
                      <td style={{ color: "var(--muted)" }}>{k}</td>
                      <td>{Array.isArray(v?.value) ? v.value.join(", ") : String(v?.value ?? v)}</td>
                      <td><Badge>{v?.source || "—"}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="section"><h2>Activity</h2>
            <div className="card" style={{ padding: 16 }}><Timeline items={c.timeline} /></div>
          </div>
        </div>

        <div>
          <div className="section" style={{ marginTop: 0 }}><h2>Contacts ({c.contacts.length})</h2>
            <table className="tbl"><tbody>
              {c.contacts.length === 0 && <tr><td className="empty">No contacts linked</td></tr>}
              {c.contacts.map((p) => (
                <tr key={p.id}>
                  <td><b>{p.name || p.email}</b><br /><span style={{ color: "var(--muted)", fontSize: 12 }}>{p.title || p.email}</span></td>
                  <td style={{ textAlign: "right" }}>{p.revenue_score != null && <Badge tone={scoreTone(p.revenue_score)}>{p.revenue_score}</Badge>}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
          <div className="section"><h2>Deals ({c.deals.length})</h2>
            <table className="tbl"><tbody>
              {c.deals.length === 0 && <tr><td className="empty">No deals yet</td></tr>}
              {c.deals.map((d) => (
                <tr key={d.id} className="click" onClick={() => nav(`/pipeline?open=${d.id}`)}>
                  <td><b>{d.name || "Untitled"}</b>
                    <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                      {d.stage_name || "—"}{d.lead_intent ? ` · ${d.lead_intent}` : ""}</div></td>
                  <td style={{ textAlign: "right", fontWeight: 700 }}>{money(d.value)}</td></tr>
              ))}
            </tbody></table>
          </div>

          <div className="section"><h2>Client profile</h2>
            <div className="card" style={{ padding: 14 }}>
              {c.client_profile ? (
                <>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
                    <Badge tone={c.client_profile.is_active_client ? "green" : "amber"}>
                      {c.client_profile.is_active_client ? "active client" : "prospect"}</Badge>
                    <Badge tone={c.client_profile.onboarding_status === "approved" ? "green" : "blue"}>
                      {c.client_profile.onboarding_status}</Badge>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>{c.client_profile.completeness}% complete</span>
                  </div>
                  <button className="btn ghost sm" onClick={() => nav(`/companies/${id}/profile`)}>Open profile →</button>
                </>
              ) : (
                <div style={{ fontSize: 13, color: "var(--muted)" }}>
                  No profile yet — created automatically on Closed Won, or&nbsp;
                  <a href="#" onClick={(e) => { e.preventDefault(); nav(`/companies/${id}/profile`); }}>open to activate</a>.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
