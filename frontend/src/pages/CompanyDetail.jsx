import { useState } from "react";
import { useParams } from "react-router-dom";
import { api, money } from "../api";
import { Badge, ErrorBox, Spinner, Timeline, fitTone, scoreTone, useApi } from "../components";

export default function CompanyDetail() {
  const { id } = useParams();
  const { data: c, error, loading, reload } = useApi(`/api/companies/${id}`);
  const [busy, setBusy] = useState("");

  const enrich = async () => {
    setBusy("enrich");
    try {
      await api("/api/enrich", { method: "POST", body: { workspace_id: c.workspace_id, company_ids: [c.id] } });
      alert("Enrichment queued — watch Jobs, then refresh this page.");
    } catch (e) { alert(e.message); }
    setBusy("");
  };
  const blueprint = async () => {
    setBusy("bp");
    try {
      await api("/api/blueprints/generate", { method: "POST", body: { workspace_id: c.workspace_id, company_id: c.id } });
      alert("Blueprint generation queued — it will appear under Blueprints.");
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
        <button className="btn" disabled={!!busy} onClick={blueprint}>{busy === "bp" ? "Queueing…" : "▤ Generate blueprint"}</button>
      </div>

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
