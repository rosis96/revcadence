import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, money } from "../api";
import { Badge, ErrorBox, Modal, Spinner, Timeline, fitTone, scoreTone, useApi } from "../components";

export default function CompanyDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: c, error, loading, reload } = useApi(`/api/companies/${id}`);
  const [busy, setBusy] = useState("");
  const [fathom, setFathom] = useState(false);
  const [transcript, setTranscript] = useState("");

  const enrich = async () => {
    setBusy("enrich");
    try {
      await api("/api/enrich", { method: "POST", body: { workspace_id: c.workspace_id, company_ids: [c.id] } });
      alert("Enrichment queued — watch Jobs, then refresh this page.");
    } catch (e) { alert(e.message); }
    setBusy("");
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

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const enrichmentRows = Object.entries(c.enrichment || {}).filter(([k]) => k !== "last_crawl");
  return (
    <>
      <div className="toolbar">
        <h1 style={{ fontSize: 20 }}>{c.name}</h1>
        {c.icp_fit && <Badge tone={fitTone(c.icp_fit)}>ICP: {c.icp_fit}</Badge>}
        <div className="spacer" />
        <button className="btn ghost" onClick={reload}>Refresh</button>
        <button className="btn ghost" disabled={!!busy} onClick={enrich}>{busy === "enrich" ? "Queueing…" : "✦ Enrich"}</button>
        <button className="btn ghost" onClick={() => nav(`/companies/${id}/profile`)}>◎ Client Profile</button>
        <button className="btn" onClick={() => setFathom(true)}>▤ Blueprint from transcript</button>
      </div>

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
                <tr key={d.id}><td>{d.name || "Untitled"}</td><td style={{ textAlign: "right", fontWeight: 700 }}>{money(d.value)}</td></tr>
              ))}
            </tbody></table>
          </div>
        </div>
      </div>
    </>
  );
}
