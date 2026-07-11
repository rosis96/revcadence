import { useState } from "react";
import { timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";

const KINDS = ["", "email_in", "email_out", "reply_drafted", "stage_change", "enriched", "deal_created", "doc_created", "import"];

export default function ActivityPage() {
  const { wsParam } = useAuth();
  const [kind, setKind] = useState("");
  const { data, error, loading, reload } = useApi("/api/activities", { workspace_id: wsParam, kind, limit: 100 });
  return (
    <>
      <div className="toolbar">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => <option key={k} value={k}>{k || "All activity types"}</option>)}
        </select>
        <button className="btn ghost sm" onClick={reload}>Refresh</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="↺" title="No activity" hint="Events across the workspace appear here." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Event</th><th>Type</th><th style={{ width: 110 }}>When</th></tr></thead>
          <tbody>
            {data.map((a) => (
              <tr key={a.id}>
                <td>
                  <b>{a.title || "—"}</b>
                  {a.body && <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>{a.body.slice(0, 140)}</div>}
                  <div style={{ marginTop: 3, fontSize: 12 }}>
                    {a.company_id && <a href={`#/companies/${a.company_id}`}>company</a>}
                  </div>
                </td>
                <td><Badge>{a.kind}</Badge></td>
                <td>{timeAgo(a.at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
