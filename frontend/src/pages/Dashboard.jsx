// Master Dashboard — one rollup across ALL sections (Outbound, Reply
// Management, Inbound, CRM). Each section also has its own focused screens.
import { useAuth } from "../auth";
import { money, timeAgo } from "../api";
import { Empty, ErrorBox, Spinner, useApi } from "../components";

function Section({ title, icon, stats, accent }) {
  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".5px", marginBottom: 12 }}>{icon} {title}</div>
      <div style={{ display: "flex", gap: 22, flexWrap: "wrap" }}>
        {stats.map(([label, value, color]) => (
          <div key={label}>
            <div style={{ fontSize: 22, fontWeight: 700, fontVariantNumeric: "tabular-nums", color: color || (accent ? "var(--accent)" : "var(--text)") }}>{value}</div>
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { wsParam } = useAuth();
  const { data, error, loading, reload } = useApi("/api/dashboard/master", { workspace_id: wsParam });
  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  const maxVal = Math.max(1, ...data.pipeline.map((p) => p.value));
  return (
    <>
      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
        <Section title="Outbound · Enrichment" icon="✦" accent stats={[
          ["Lists", data.outbound.lists], ["Leads", data.outbound.leads.toLocaleString()],
          ["Enriched", data.outbound.enriched.toLocaleString()], ["ICP fit", data.outbound.icp.toLocaleString()]]} />
        <Section title="Reply Management" icon="✉" stats={[
          ["Replies", data.reply.total], ["Needs review", data.reply.needs_review, "var(--warn)"],
          ["Replied", data.reply.replied, "var(--ok)"], ["Booked", data.reply.booked]]} />
        <Section title="Inbound · Visitors" icon="◍" stats={[
          ["Visitors identified", data.inbound.visitors]]} />
        <Section title="CRM" icon="☰" stats={[
          ["Open pipeline", money(data.open_value), "var(--accent)"], ["Active deals", data.crm.active_deals],
          ["Meetings booked", data.crm.meetings_booked], ["Won", money(data.won_value), "var(--ok)"]]} />
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
        <h2>Latest activity — all sections</h2>
        {data.recent_activity.length === 0 ? (
          <Empty title="No activity yet" hint="Events from every section appear here." />
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
