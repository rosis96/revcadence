// Reply Management → Dashboard: the dedicated performance overview + recent
// activity, mirroring the legacy Studio dashboard.
import { useLocation, useNavigate } from "react-router-dom";
import { timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";
import { replyBase } from "../clientspace/modules";

const STAT = [
  ["all", "Total Replies", "var(--text)"],
  ["replied", "Replied", "var(--ok)"],
  ["booked", "Meeting Booked", "var(--accent)"],
  ["needs_review", "Needs Review", "var(--warn)"],
  ["stopped", "Stopped", "var(--muted)"],
];
const actionTone = (a) => a === "stop" ? "red" : a === "would_send" ? "amber" : a === "send" ? "green" : a === "skip_enrich" ? "indigo" : "";

export default function ReplyDashboard() {
  const nav = useNavigate();
  // This screen is mounted at two bases — `/reply` for us, `/w/<slug>/reply` for
  // the client — so every link below is resolved from the URL it was opened at.
  const base = replyBase(useLocation().pathname);
  const { wsParam } = useAuth();
  const { data, error, loading, reload } = useApi("/api/reply/leads", { status: "", workspace_id: wsParam });
  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  const c = data.counts;
  return (
    <>
      <div className="grid stats" style={{ marginBottom: 20 }}>
        {STAT.map(([k, label, color]) => (
          <div className="card stat" key={k} style={{ cursor: "pointer" }}
               onClick={() => nav(`${base}/inbox?status=${k === "all" ? "" : k}`)}>
            <div className="label">{label}</div>
            <div className="value" style={{ color }}>{c[k] ?? 0}</div>
          </div>
        ))}
      </div>
      <div className="section" style={{ marginTop: 0 }}>
        <div className="toolbar"><h2 style={{ margin: 0 }}>Recent leads activity</h2><div className="spacer" />
          <button className="btn ghost sm" onClick={() => nav(`${base}/inbox`)}>Open Inbox →</button></div>
        {data.leads.length === 0 ? (
          <Empty icon="✉" title="No replies yet" hint="Replies arrive from Bison/Instantly webhooks pointed at your workspaces." />
        ) : (
          <table className="tbl">
            <thead><tr><th>Lead & Company</th><th>Intent</th><th>Stage</th><th>Decision</th><th>Reply</th><th>When</th></tr></thead>
            <tbody>
              {data.leads.map((l) => (
                <tr key={l.id} className="click" onClick={() => nav(`${base}/inbox?open=${l.id}`)}>
                  <td><b>{l.name || l.email}</b><div style={{ color: "var(--muted)", fontSize: 12 }}>{l.company} · {l.email}</div></td>
                  <td>{l.intent ? <Badge tone="indigo">{l.intent}</Badge> : "—"}</td>
                  <td>{l.stage ? <Badge>{l.stage}</Badge> : "—"}</td>
                  <td><Badge tone={actionTone(l.action)}>{l.action}</Badge></td>
                  <td>{l.replied ? <Badge tone="green">sent</Badge> : <Badge tone="amber">drafted</Badge>}</td>
                  <td>{timeAgo(l.at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
