import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";
import { alertDialog } from "../components";
import { Select } from "../components";

const tone = { done: "green", failed: "red", running: "indigo", pending: "amber" };

export default function Jobs() {
  const [status, setStatus] = useState("");
  const { data, error, loading, reload } = useApi("/api/jobs", { status });

  useEffect(() => {
    const active = (data || []).some((j) => ["pending", "running"].includes(j.status));
    if (!active) return;
    const t = setInterval(reload, 4000);
    return () => clearInterval(t);
  }, [data, reload]);

  const cancel = async (id) => {
    try { await api(`/api/jobs/${id}/cancel`, { method: "POST" }); reload(); }
    catch (e) { alertDialog(e.message); }
  };

  return (
    <>
      <div className="toolbar">
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {["pending", "running", "done", "failed", "cancelled"].map((s) => <option key={s}>{s}</option>)}
        </Select>
        <button className="btn ghost sm" onClick={reload}>Refresh</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="⚙" title="No jobs" hint="Enrichment and automation jobs appear here." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Attempts</th><th>Scheduled</th><th>Error</th><th></th></tr></thead>
          <tbody>
            {data.map((j) => (
              <tr key={j.id}>
                <td>{j.id}</td>
                <td><Badge>{j.kind}</Badge></td>
                <td><Badge tone={tone[j.status] || ""}>{j.status}</Badge></td>
                <td>{j.attempts}</td>
                <td style={{ color: "var(--muted)", fontSize: 12.5 }}>{j.run_at ? new Date(j.run_at + "Z").toLocaleString() : ""}</td>
                <td style={{ color: "var(--bad)", fontSize: 12 }}>{(j.error || "").slice(-90)}</td>
                <td>{["pending", "running"].includes(j.status) &&
                  <button className="btn danger sm" onClick={() => cancel(j.id)}>Cancel</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
