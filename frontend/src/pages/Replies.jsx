// Inbound → Replies: client-visible reporting on cold-email replies.
// Data source: reply activities (kind=email_in) migrated/bridged from the
// Reply Manager, with intent classification.
import { useMemo, useState } from "react";
import { timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";

const intentTone = (i) =>
  /positive/.test(i || "") ? "green" :
  /pricing|question/.test(i || "") ? "indigo" :
  /unsub|not_interested|stop/.test(i || "") ? "red" : "";

export default function Replies() {
  const { wsParam } = useAuth();
  const [intent, setIntent] = useState("");
  const { data, error, loading, reload } = useApi("/api/activities",
    { workspace_id: wsParam, kind: "email_in", limit: 200 });
  const { data: summary } = useApi("/api/dashboard/summary", { workspace_id: wsParam });

  const intents = useMemo(
    () => [...new Set((data || []).map((a) => a.intent).filter(Boolean))].sort(), [data]);
  const rows = (data || []).filter((a) => !intent || a.intent === intent);

  return (
    <>
      <div className="grid stats" style={{ marginBottom: 18 }}>
        <div className="card stat"><div className="label">Total replies</div>
          <div className="value">{summary?.totals?.replies ?? "—"}</div></div>
        <div className="card stat"><div className="label">Positive replies</div>
          <div className="value" style={{ color: "var(--ok)" }}>{summary?.totals?.positive_replies ?? "—"}</div></div>
        <div className="card stat"><div className="label">Meetings booked</div>
          <div className="value">{summary?.totals?.meetings_booked ?? "—"}</div></div>
      </div>

      <div className="toolbar">
        <select value={intent} onChange={(e) => setIntent(e.target.value)}>
          <option value="">All intents</option>
          {intents.map((i) => <option key={i}>{i}</option>)}
        </select>
        <button className="btn ghost sm" onClick={reload}>Refresh</button>
      </div>

      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {!loading && rows.length === 0 && (
        <Empty icon="✉" title="No replies" hint="Replies flow in from the Reply Manager (imported today; live bridge is the next build)." />
      )}
      {rows.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Reply</th><th>Intent</th><th style={{ width: 110 }}>When</th></tr></thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id}>
                <td>
                  <b>{a.title}</b>
                  {a.body && <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 3 }}>{a.body.slice(0, 180)}</div>}
                  <div style={{ marginTop: 3, fontSize: 12 }}>
                    {a.company_id && <a href={`#/companies/${a.company_id}`}>view company</a>}
                  </div>
                </td>
                <td>{a.intent ? <Badge tone={intentTone(a.intent)}>{a.intent}</Badge> : <Badge>unclassified</Badge>}</td>
                <td>{timeAgo(a.at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
