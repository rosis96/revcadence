import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, fitTone, useApi } from "../components";
import { NewCompanyModal } from "./Companies";

const jobTone = { done: "green", failed: "red", running: "indigo", pending: "amber", cancelled: "" };

export default function Enrichment() {
  const { wsParam, me, workspaceId, setWorkspaceId } = useAuth();
  const nav = useNavigate();
  const [selected, setSelected] = useState({});
  const [modal, setModal] = useState(false);
  const [busy, setBusy] = useState(false);
  const { data: companies, error, loading, reload } = useApi("/api/companies", { workspace_id: wsParam });
  const { data: jobs, reload: reloadJobs } = useApi("/api/jobs", {});

  // auto-refresh jobs while any are active
  useEffect(() => {
    const active = (jobs || []).some((j) => ["pending", "running"].includes(j.status));
    if (!active) return;
    const t = setInterval(() => { reloadJobs(); reload(); }, 4000);
    return () => clearInterval(t);
  }, [jobs, reloadJobs, reload]);

  const ids = Object.keys(selected).filter((k) => selected[k]).map(Number);
  const needWs = me.is_master && !wsParam;

  const runEnrich = async () => {
    setBusy(true);
    try {
      const byWs = {};
      for (const id of ids) {
        const c = companies.find((x) => x.id === id);
        (byWs[c.workspace_id] ||= []).push(id);
      }
      for (const [ws, cids] of Object.entries(byWs)) {
        await api("/api/enrich", { method: "POST", body: { workspace_id: Number(ws), company_ids: cids } });
      }
      setSelected({});
      reloadJobs();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const enrichJobs = (jobs || []).filter((j) => ["enrich_company", "enrich_contact", "generate_blueprint"].includes(j.kind)).slice(0, 25);

  return (
    <>
      {me.is_master && (
        <div className="toolbar">
          <label style={{ fontSize: 13, color: "var(--muted)" }}>Workspace:</label>
          <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
            <option value="">All workspaces</option>
            {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <div className="spacer" />
          <button className="btn ghost" onClick={() => setModal(true)}>+ Add company</button>
          <button className="btn" disabled={ids.length === 0 || busy} onClick={runEnrich}>
            {busy ? "Queueing…" : `✦ Enrich ${ids.length || ""} selected`}
          </button>
        </div>
      )}
      {!me.is_master && (
        <div className="toolbar">
          <div className="spacer" />
          <button className="btn ghost" onClick={() => setModal(true)}>+ Add company</button>
          <button className="btn" disabled={ids.length === 0 || busy} onClick={runEnrich}>
            {busy ? "Queueing…" : `✦ Enrich ${ids.length || ""} selected`}
          </button>
        </div>
      )}

      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {companies && companies.length === 0 && <Empty icon="✦" title="No companies to enrich" hint="Add a company with a website first." />}
      {companies && companies.length > 0 && (
        <table className="tbl">
          <thead>
            <tr>
              <th className="checkbox-cell">
                <input type="checkbox"
                       checked={ids.length === companies.length && companies.length > 0}
                       onChange={(e) => setSelected(Object.fromEntries(companies.map((c) => [c.id, e.target.checked])))} />
              </th>
              <th>Company</th><th>Industry</th><th>ICP fit</th><th></th>
            </tr>
          </thead>
          <tbody>
            {companies.map((c) => (
              <tr key={c.id}>
                <td className="checkbox-cell">
                  <input type="checkbox" checked={!!selected[c.id]}
                         onChange={(e) => setSelected({ ...selected, [c.id]: e.target.checked })} />
                </td>
                <td><b>{c.name}</b> <span style={{ color: "var(--muted)" }}>{c.domain}</span></td>
                <td>{c.industry || "—"}</td>
                <td>{c.icp_fit ? <Badge tone={fitTone(c.icp_fit)}>{c.icp_fit}</Badge> : <Badge>not enriched</Badge>}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn ghost sm" onClick={() => nav(`/companies/${c.id}`)}>Open</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="section">
        <h2>Enrichment jobs</h2>
        {enrichJobs.length === 0 ? <Empty title="No jobs yet" hint="Select companies above and click Enrich." /> : (
          <table className="tbl">
            <thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Progress</th><th>Result / error</th></tr></thead>
            <tbody>
              {enrichJobs.map((j) => <JobRow key={j.id} job={j} />)}
            </tbody>
          </table>
        )}
      </div>

      {modal && (
        <NewCompanyModal workspaceId={wsParam} workspaces={me.workspaces} onClose={() => setModal(false)}
                         onCreated={() => { setModal(false); reload(); }} />
      )}
    </>
  );
}

function JobRow({ job }) {
  const { data: st } = useApi(`/api/jobs/${job.id}/status`, undefined, [job.status]);
  const s = st || job;
  return (
    <tr>
      <td>{job.id}</td>
      <td><Badge>{job.kind}</Badge></td>
      <td><Badge tone={jobTone[s.status] || ""}>{s.status}</Badge></td>
      <td>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className="progressbar"><div style={{ width: `${s.progress || 0}%` }} /></div>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>{s.progress || 0}% {s.progress_note}</span>
        </div>
      </td>
      <td style={{ fontSize: 12, color: s.error ? "var(--bad)" : "var(--muted)" }}>
        {s.error ? s.error.slice(-120) :
          s.result?.document_id ? <a href={`#/blueprints/${s.result.document_id}`}>open blueprint</a> :
          s.result?.icp_fit ? `icp: ${s.result.icp_fit}` : ""}
      </td>
    </tr>
  );
}
