import { useAuth } from "../auth";
import { money, timeAgo } from "../api";
import { Empty, ErrorBox, Spinner, useApi } from "../components";

const STATS = [
  ["companies", "Companies"],
  ["contacts", "Contacts"],
  ["active_deals", "Active deals"],
  ["meetings_booked", "Meetings booked"],
  ["replies", "Replies"],
  ["positive_replies", "Positive replies"],
  ["stalled_deals", "Stalled deals", "no movement in 14d"],
  ["enrichment_jobs_running", "Jobs running"],
];

export default function Dashboard() {
  const { wsParam } = useAuth();
  const { data, error, loading, reload } = useApi("/api/dashboard/summary", { workspace_id: wsParam });
  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  const maxVal = Math.max(1, ...data.pipeline.map((p) => p.value));
  return (
    <>
      <div className="grid stats">
        <div className="card stat">
          <div className="label">Open pipeline</div>
          <div className="value" style={{ color: "var(--accent)" }}>{money(data.open_value)}</div>
          <div className="sub">won: {money(data.won_value)}</div>
        </div>
        {STATS.map(([k, label, sub]) => (
          <div className="card stat" key={k}>
            <div className="label">{label}</div>
            <div className="value">{data.totals[k]}</div>
            {sub && <div className="sub">{sub}</div>}
          </div>
        ))}
      </div>

      <div className="section">
        <h2>Pipeline by stage</h2>
        <div className="card" style={{ padding: 16 }}>
          {data.pipeline.length === 0 && <div className="empty">No stages yet</div>}
          {data.pipeline.map((p) => (
            <div className="bar-row" key={p.stage}>
              <div className="lbl">{p.stage}</div>
              <div className="bar"><div style={{ width: `${(p.value / maxVal) * 100}%`, background: p.color || "var(--accent)" }} /></div>
              <div className="n">{p.count} · {money(p.value)}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="section">
        <h2>Latest activity</h2>
        {data.recent_activity.length === 0 ? (
          <Empty title="No activity yet" hint="Imported and new events appear here." />
        ) : (
          <table className="tbl">
            <thead><tr><th>Event</th><th>Type</th><th style={{ width: 110 }}>When</th></tr></thead>
            <tbody>
              {data.recent_activity.map((a, i) => (
                <tr key={i}><td>{a.title}</td><td><span className="badge">{a.kind}</span></td><td>{timeAgo(a.at)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
