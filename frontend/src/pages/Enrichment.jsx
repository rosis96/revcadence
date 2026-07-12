import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, getToken } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, fitTone, useApi } from "../components";
import { NewCompanyModal } from "./Companies";

const jobTone = { done: "green", failed: "red", running: "indigo", pending: "amber", cancelled: "" };

// Minimal CSV parser (handles quoted fields) + forgiving header mapping.
function parseCsv(text) {
  const rows = [];
  let cur = [""], inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"' && text[i + 1] === '"') { cur[cur.length - 1] += '"'; i++; }
      else if (ch === '"') inQ = false;
      else cur[cur.length - 1] += ch;
    } else if (ch === '"') inQ = true;
    else if (ch === ",") cur.push("");
    else if (ch === "\n" || ch === "\r") {
      if (cur.length > 1 || cur[0] !== "") rows.push(cur);
      cur = [""];
      if (ch === "\r" && text[i + 1] === "\n") i++;
    } else cur[cur.length - 1] += ch;
  }
  if (cur.length > 1 || cur[0] !== "") rows.push(cur);
  return rows;
}

const HEADER_MAP = {
  first_name: ["first_name", "firstname", "first name", "first"],
  last_name: ["last_name", "lastname", "last name", "last"],
  email: ["email", "email address", "e-mail"],
  title: ["title", "job title", "position", "role"],
  company: ["company", "company_name", "company name", "organization"],
  website: ["website", "company website", "domain", "url", "company_website"],
};

function mapRows(csvRows) {
  const headers = csvRows[0].map((h) => h.toLowerCase().trim());
  const idx = {};
  for (const [field, names] of Object.entries(HEADER_MAP)) {
    const i = headers.findIndex((h) => names.includes(h));
    if (i >= 0) idx[field] = i;
  }
  return csvRows.slice(1).map((r) =>
    Object.fromEntries(Object.entries(idx).map(([f, i]) => [f, (r[i] || "").trim()])));
}

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
  const fileRef = useRef(null);

  const importCsv = async (file) => {
    if (!wsParam && me.is_master) { alert("Pick a specific workspace before importing."); return; }
    const targetWs = wsParam || me.workspaces[0]?.id;
    const text = await file.text();
    const rows = mapRows(parseCsv(text));
    if (rows.length === 0) { alert("No rows found. Expected headers like: first_name, last_name, email, title, company, website"); return; }
    const auto = confirm(`Import ${rows.length} rows into this workspace?\n\nOK = import + auto-enrich every contact\nCancel = abort`);
    if (!auto) return;
    setBusy(true);
    try {
      const r = await api("/api/import/contacts", { method: "POST",
        body: { workspace_id: Number(targetWs), rows, auto_enrich: true } });
      alert(`Imported: ${r.contacts_created} new contacts, ${r.contacts_merged} merged, ` +
            `${r.companies_created} companies, ${r.enrich_jobs_queued} enrichment jobs queued.`);
      reload(); reloadJobs();
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const exportCsv = async () => {
    const url = new URL("/api/export/leads", window.location.origin);
    if (wsParam) url.searchParams.set("workspace_id", wsParam);
    const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) { alert("Export failed"); return; }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "revcadence-leads.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

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
      <div className="toolbar">
        {me.is_master && (
          <>
            <label style={{ fontSize: 13, color: "var(--muted)" }}>Workspace:</label>
            <select value={workspaceId} onChange={(e) => setWorkspaceId(e.target.value)}>
              <option value="">All workspaces</option>
              {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </>
        )}
        <div className="spacer" />
        <input type="file" accept=".csv,text/csv" ref={fileRef} style={{ display: "none" }}
               onChange={(e) => { if (e.target.files[0]) importCsv(e.target.files[0]); e.target.value = ""; }} />
        <button className="btn ghost" disabled={busy} onClick={() => fileRef.current.click()}>⇪ Import CSV</button>
        <button className="btn ghost" onClick={exportCsv}>⇓ Export CSV</button>
        <button className="btn ghost" onClick={() => setModal(true)}>+ Add company</button>
        <button className="btn" disabled={ids.length === 0 || busy} onClick={runEnrich}>
          {busy ? "Queueing…" : `✦ Enrich ${ids.length || ""} selected`}
        </button>
      </div>

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
