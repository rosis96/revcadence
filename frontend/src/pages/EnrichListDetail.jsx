// The list grid: chips (live full-list counts), views, selection incl.
// select-all-in-view, Verify / Verify→Enrich with test-first-N cap, hard Stop,
// two-column verification display, per-view export — the old dashboard, re-skinned.
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, getToken } from "../api";
import { Badge, ErrorBox, Modal, Spinner, useApi } from "../components";

const CHIP_ORDER = [["all", "All"], ["processed", "Processed"], ["verified", "Verified"],
  ["enriched", "Enriched"], ["nonicp", "Non-ICP"], ["no_website", "No website"],
  ["invalid", "Invalid"], ["unsafe", "Unsafe"], ["notrun", "Not run"],
  ["title_rejected", "Title-rejected"]];

const stTone = { done: "green", invalid: "red", unsafe: "red", skipped: "amber", error: "red" };
const vTone = (v) => v === "ok" || v === "safe" || v === "valid" ? "green"
  : v === "role" || v === "catch_all" || v === "unknown" ? "amber"
  : v === "skipped" || !v ? "" : "red";

export default function EnrichListDetail() {
  const { id } = useParams();
  const [view, setView] = useState("all");
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState({});
  const [allInView, setAllInView] = useState(false);
  const [limit, setLimit] = useState(10);   // test-first-N credit safeguard
  const [job, setJob] = useState(null);
  const [openLead, setOpenLead] = useState(null);
  const { data, error, loading, reload } = useApi(`/api/enrich-lists/${id}/leads`,
    { view, page, q, page_size: 50 });
  const { data: reoon } = useApi("/api/enrich-lists/reoon/balance");
  const [outputs, setOutputs] = useState(null);   // null = all; else selected var names
  const cfg = useApi(data ? `/api/enrich-lists/config/${data.list.workspace_id}` : null);

  // reconnect to a run already in progress (survives page reload — Stop persists)
  useEffect(() => {
    if (!data || job) return;
    api(`/api/enrich-lists/${id}/active-job`).then((r) => { if (r.job_id) setJob(r.job_id); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.list?.id]);

  // live job progress poll
  useEffect(() => {
    if (!job) return;
    const t = setInterval(async () => {
      try {
        const s = await api(`/api/jobs/${job}/status`);
        setJobStatus(s);
        if (["done", "failed", "cancelled"].includes(s.status)) { clearInterval(t); setJob(null); reload(); }
      } catch { clearInterval(t); setJob(null); }
    }, 2500);
    return () => clearInterval(t);
  }, [job, reload]);
  const [jobStatus, setJobStatus] = useState(null);

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const ids = Object.keys(sel).filter((k) => sel[k]).map(Number);
  const selectedCount = allInView ? data.total_in_view : ids.length;

  const run = async (steps) => {
    // An explicit selection (individual rows or select-all-in-view) runs EVERY
    // selected lead. The "Test first" cap is only a safety net for the default,
    // nothing-selected run — otherwise a leftover cap of 10 would silently
    // truncate a big selection.
    const explicit = allInView || ids.length > 0;
    const body = { steps, limit: explicit ? 0 : Number(limit) || 0 };
    if (outputs) body.enrichments = outputs;
    if (allInView || ids.length === 0) body.view = view === "all" ? "notrun" : view;
    else body.lead_ids = ids;
    const n = selectedCount || data.chips.notrun;
    if (n > 50 && !confirm(`Run ${steps} on ${n.toLocaleString()} leads${body.limit ? ` (capped at ${body.limit})` : ""}?`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/run`, { method: "POST", body });
      setJob(r.job_id); setSel({}); setAllInView(false);
    } catch (e) { alert(e.message); }
  };
  const stop = async () => { if (job) { try { await api(`/api/jobs/${job}/cancel`, { method: "POST" }); } catch (e) { alert(e.message); } } };
  const findCompetitors = async () => {
    const body = {};
    if (allInView || ids.length === 0) body.view = view;
    else body.lead_ids = ids;
    try {
      const r = await api(`/api/enrich-lists/${id}/find-competitors`, { method: "POST", body });
      setJob(r.job_id); setSel({}); setAllInView(false);
    } catch (e) { alert(e.message); }
  };
  const splitByIndustry = async () => {
    if (!confirm("Create '<List> — <Industry>' lists and move classified leads into them?")) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/split-by-industry`, { method: "POST" });
      alert(`Moved ${r.moved} leads into ${r.lists_created.length} industry lists.`);
      reload();
    } catch (e) { alert(e.message); }
  };
  const clearAction = async (what) => {
    if (!confirm(`${what === "clear-results" ? "Clear enrichment results" : "Clear verification"} for view "${view}"?`)) return;
    try { await api(`/api/enrich-lists/${id}/${what}?view=${view}`, { method: "POST" }); reload(); }
    catch (e) { alert(e.message); }
  };
  const deleteSelected = async () => {
    const body = {};
    if (allInView || ids.length === 0) body.view = view;
    else body.lead_ids = ids;
    const n = selectedCount || data.chips[view] || 0;
    if (!confirm(`Delete ${n.toLocaleString()} lead(s)? This cannot be undone.`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/delete-leads`, { method: "POST", body });
      alert(`Deleted ${r.deleted} lead(s).`); setSel({}); setAllInView(false); reload();
    } catch (e) { alert(e.message); }
  };
  const exportCsv = async () => {
    const res = await fetch(`/api/enrich-lists/${id}/export?view=${view}`,
      { headers: { Authorization: `Bearer ${getToken()}` } });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `${data.list.name}-${view}.csv`; a.click();
    URL.revokeObjectURL(a.href);
  };

  const pages = Math.max(1, Math.ceil(data.total_in_view / data.page_size));

  return (
    <>
      <div className="toolbar">
        <h1 style={{ fontSize: 18 }}>{data.list.name}</h1>
        <span style={{ color: "var(--muted)", fontSize: 12.5 }}>{data.chips.all.toLocaleString()} leads</span>
        {reoon && <span className="badge" style={{ background: "#f4f5f7" }}>
          Reoon: {reoon.demo ? "demo" : (reoon.credits != null ? `${reoon.credits.toLocaleString()} credits` : "connected")}
        </span>}
        <div className="spacer" />
        {selectedCount > 0 ? (
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Runs all <b>{selectedCount.toLocaleString()}</b> selected
          </span>
        ) : (
          <>
            <label style={{ fontSize: 12.5, color: "var(--muted)" }}>Test first</label>
            <input type="number" min="0" value={limit} onChange={(e) => setLimit(e.target.value)} style={{ width: 70 }}
                   title="Caps the default run when nothing is selected. 0 = no cap. Select leads to run all of them." />
          </>
        )}
        <button className="btn ghost" disabled={!!job} onClick={() => run("verify")}>Verify</button>
        <button className="btn" disabled={!!job} onClick={() => run("pipeline")}>▶ Verify → Enrich</button>
        {job && <button className="btn danger" onClick={stop}>■ Stop</button>}
      </div>

      {job && jobStatus && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12, display: "flex", alignItems: "center", gap: 12 }}>
          <div className="spinner" style={{ width: 16, height: 16 }} />
          <div className="progressbar" style={{ width: 220 }}><div style={{ width: `${jobStatus.progress || 0}%` }} /></div>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{jobStatus.progress || 0}% · {jobStatus.progress_note}</span>
        </div>
      )}

      {cfg.data?.formats?.length > 0 && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 12 }}>
          <span style={{ fontSize: 12, color: "var(--muted)", marginRight: 8 }}>Output variables:</span>
          <button className={`badge ${!outputs ? "indigo" : ""}`} style={{ cursor: "pointer", marginRight: 6 }}
                  onClick={() => setOutputs(null)}>All</button>
          {cfg.data.formats.map((f) => {
            const on = outputs?.includes(f.name);
            return (
              <button key={f.name} className={`badge ${on ? "indigo" : ""}`} style={{ cursor: "pointer", marginRight: 6 }}
                      onClick={() => setOutputs((o) => {
                        const cur = o || [];
                        return cur.includes(f.name) ? cur.filter((x) => x !== f.name) : [...cur, f.name];
                      })}>{f.label}</button>
            );
          })}
        </div>
      )}
      <div className="chips">
        {CHIP_ORDER.map(([v, label]) => (
          <button key={v} className={view === v ? "on" : ""}
                  onClick={() => { setView(v); setPage(1); setSel({}); setAllInView(false); }}>
            {label} {data.chips[v]?.toLocaleString?.() ?? 0}
          </button>
        ))}
      </div>

      <div className="toolbar">
        <input type="text" placeholder="Search name, email, company…" value={q}
               onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        {selectedCount > 0 && <Badge tone="indigo">{selectedCount.toLocaleString()} selected</Badge>}
        {!allInView && data.total_in_view > data.leads.length && (
          <button className="btn ghost sm" onClick={() => setAllInView(true)}>
            Select all {data.total_in_view.toLocaleString()} in view</button>
        )}
        {allInView && <button className="btn ghost sm" onClick={() => setAllInView(false)}>Clear selection</button>}
        <div className="spacer" />
        <button className="btn ghost sm" disabled={!!job} onClick={findCompetitors}>◎ Find competitors</button>
        <button className="btn ghost sm" disabled={!!job} onClick={splitByIndustry}>⑃ Split by industry</button>
        <button className="btn ghost sm" onClick={() => clearAction("clear-results")}>Clear results</button>
        <button className="btn ghost sm" onClick={() => clearAction("clear-verification")}>Clear verification</button>
        <button className="btn danger sm" disabled={!!job} onClick={deleteSelected}>Delete</button>
        <button className="btn ghost sm" onClick={exportCsv}>⇓ Export view</button>
      </div>

      <table className="tbl">
        <thead><tr>
          <th className="checkbox-cell"><input type="checkbox"
            checked={allInView || (data.leads.length > 0 && ids.length === data.leads.length)}
            onChange={(e) => { setAllInView(false); setSel(Object.fromEntries(data.leads.map((l) => [l.id, e.target.checked]))); }} /></th>
          <th>Lead</th><th>System check</th><th>Reoon</th><th>Title gate</th><th>ICP</th><th>Industry</th><th>Competitors</th><th>Status</th>
        </tr></thead>
        <tbody>
          {data.leads.map((l) => (
            <tr key={l.id} className="click" onClick={() => setOpenLead(l)}>
              <td className="checkbox-cell" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={allInView || !!sel[l.id]}
                       onChange={(e) => { setAllInView(false); setSel({ ...sel, [l.id]: e.target.checked }); }} /></td>
              <td><b>{l.name || l.email}</b>
                <div style={{ color: "var(--muted)", fontSize: 12 }}>{l.company}{l.title ? ` · ${l.title}` : ""}</div></td>
              <td><Badge tone={vTone(l.free_status)}>{l.free_status || "—"}</Badge></td>
              <td><Badge tone={vTone(l.email_status)}>{l.email_status || "—"}</Badge></td>
              <td>{l.title_status ? <Badge tone={l.title_status === "pass" ? "green" : "red"}>{l.title_status}</Badge> : "—"}</td>
              <td>{l.icp_decision ? <Badge tone={l.icp_decision === "ICP" ? "green" : l.icp_decision === "Non-ICP" ? "red" : "amber"}>
                {l.icp_decision}{l.icp_score != null ? ` ${l.icp_score}` : ""}</Badge> : "—"}</td>
              <td style={{ fontSize: 12.5 }}>{l.industry || "—"}</td>
              <td style={{ fontSize: 12 }}>
                {(l.competitors || []).length === 0 ? "—" :
                  l.competitors.map((c, i) => (
                    <span key={i} title={c.why} style={{ display: "block" }}>{c.name}</span>))}
              </td>
              <td><Badge tone={stTone[l.status] || ""}>{l.status || "not run"}</Badge></td>
            </tr>
          ))}
          {data.leads.length === 0 && <tr><td colSpan={9} className="empty">Nothing in this view</td></tr>}
        </tbody>
      </table>

      <div className="toolbar" style={{ marginTop: 12 }}>
        <button className="btn ghost sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>Page {page} / {pages} · {data.total_in_view.toLocaleString()} in view</span>
        <button className="btn ghost sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
      </div>

      {openLead && (
        <Modal title={openLead.name || openLead.email} onClose={() => setOpenLead(null)}>
          <div className="kv">
            <div className="k">Email</div><div>{openLead.email}</div>
            <div className="k">Company</div><div>{openLead.company} {openLead.website && <a href={openLead.website.startsWith("http") ? openLead.website : `https://${openLead.website}`} target="_blank" rel="noreferrer">↗</a>}</div>
            <div className="k">ICP reason</div><div>{openLead.icp_reason || "—"}</div>
          </div>
          <h3 style={{ fontSize: 13, margin: "10px 0 8px" }}>Enrichment variables</h3>
          {Object.keys(openLead.vars || {}).length === 0
            ? <div className="empty" style={{ padding: 12 }}>Not enriched yet</div>
            : Object.entries(openLead.vars).map(([k, v]) => (
              <div key={k} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{k}</div>
                <div style={{ fontSize: 13.5 }}>{String(v)}</div>
              </div>))}
          {Object.keys(openLead.imported || {}).length > 0 && (
            <>
              <h3 style={{ fontSize: 13, margin: "16px 0 8px" }}>Uploaded columns</h3>
              <div className="kv" style={{ margin: 0 }}>
                {Object.entries(openLead.imported).map(([k, v]) => (
                  <><div className="k" key={k + "k"}>{k}</div><div key={k + "v"}>{String(v) || "—"}</div></>
                ))}
              </div>
            </>
          )}
        </Modal>
      )}
    </>
  );
}
