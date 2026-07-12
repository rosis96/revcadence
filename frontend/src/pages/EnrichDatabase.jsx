// Outbound → Database: every lead across all lists in the workspace, filterable.
import { useState } from "react";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Spinner, useApi } from "../components";

const CHIPS = [["all", "All"], ["enriched", "Enriched"], ["verified", "Verified"],
  ["nonicp", "Non-ICP"], ["invalid", "Invalid"], ["unsafe", "Unsafe"], ["notrun", "Not run"]];
const st = { done: "green", invalid: "red", unsafe: "red", skipped: "amber", error: "red" };

export default function EnrichDatabase() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [view, setView] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, loading } = useApi(wsId ? `/api/enrich-lists/database/${wsId}` : null,
    { view, q, page });
  if (!wsId) return <ErrorBox msg="Pick a specific workspace (top-left) to see its lead database." />;
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox msg={error} />;
  const pages = Math.max(1, Math.ceil(data.total_in_view / 50));
  return (
    <>
      <div className="chips">
        {CHIPS.map(([v, label]) => (
          <button key={v} className={view === v ? "on" : ""} onClick={() => { setView(v); setPage(1); }}>
            {label} {data.chips[v]?.toLocaleString?.() ?? 0}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <input type="text" placeholder="Search all leads…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      </div>
      <table className="tbl">
        <thead><tr><th>Lead</th><th>List</th><th>ESP</th><th>ICP</th><th>Industry</th><th>Status</th></tr></thead>
        <tbody>
          {data.leads.map((l) => (
            <tr key={l.id}>
              <td><b>{l.name || l.email}</b><div style={{ color: "var(--muted)", fontSize: 12 }}>{l.company} · {l.email}</div></td>
              <td style={{ fontSize: 12.5 }}>{l.list_name}</td>
              <td>{l.esp ? <Badge>{l.esp}</Badge> : "—"}</td>
              <td>{l.icp_decision ? <Badge tone={l.icp_decision === "ICP" ? "green" : l.icp_decision === "Non-ICP" ? "red" : "amber"}>{l.icp_decision}</Badge> : "—"}</td>
              <td style={{ fontSize: 12.5 }}>{l.industry || "—"}</td>
              <td><Badge tone={st[l.status] || ""}>{l.status || "not run"}</Badge></td>
            </tr>
          ))}
          {data.leads.length === 0 && <tr><td colSpan={6} className="empty">Nothing in this view</td></tr>}
        </tbody>
      </table>
      <div className="toolbar" style={{ marginTop: 12 }}>
        <button className="btn ghost sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>← Prev</button>
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>Page {page} / {pages} · {data.total_in_view.toLocaleString()} leads</span>
        <button className="btn ghost sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next →</button>
      </div>
    </>
  );
}
