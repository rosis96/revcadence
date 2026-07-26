// Reports — the client-facing ROI view: headline KPIs, the conversion funnel,
// a weekly trend, and the biggest open deals. Scoped to the selected workspace
// (a client sees only their own numbers).
import { useState } from "react";
import { useAuth } from "../auth";
import { ErrorBox, PageHeader, Spinner, useApi } from "../components";

const money = (n) => "$" + (Math.round(n || 0)).toLocaleString();
const RANGES = [[30, "30 days"], [90, "90 days"], [180, "6 months"], [365, "12 months"]];

function Kpi({ label, value, sub, accent }) {
  return (
    <div className="card" style={{ padding: 16, minWidth: 0 }}>
      <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: "-.02em", color: accent || "var(--ink, #16263c)" }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>{sub}</div>}
    </div>
  );
}

export default function Reports() {
  const { wsParam } = useAuth();
  const [days, setDays] = useState(90);
  const { data, error, loading, reload } = useApi("/api/reports/summary", { workspace_id: wsParam, days });

  if (error) return <ErrorBox msg={error} retry={reload} />;
  if (loading && !data) return <Spinner />;
  if (!data) return null;

  const k = data.kpis, c = data.conversion;
  const funnelMax = Math.max(1, ...data.funnel.map((f) => f.count));
  const mtgMax = Math.max(1, ...data.trend.map((t) => t.meetings));
  const wonMax = Math.max(1, ...data.trend.map((t) => t.won_value));

  return (
    <>
      <PageHeader title="Reports" desc="What the revenue engine produced — meetings, pipeline, and revenue."
        actions={
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}
            style={{ padding: "7px 10px", borderRadius: 8, fontSize: 13 }}>
            {RANGES.map(([v, l]) => <option key={v} value={v}>Last {l}</option>)}
          </select>
        } />

      {/* KPI row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 14 }}>
        <Kpi label="Open pipeline" value={money(k.open_pipeline_value)} sub={`${k.active_deals} active deals`} accent="var(--primary)" />
        <Kpi label="Won revenue (in range)" value={money(k.won_revenue_in_range)} sub={`${money(k.won_revenue)} all-time`} accent="#22a06b" />
        <Kpi label="Meetings booked" value={k.meetings_booked} sub="currently in pipeline" />
        <Kpi label="Positive replies" value={k.positive_replies_in_range} sub="in range" />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 18 }}>
        <Kpi label="Opportunities created" value={k.opportunities_in_range} sub="in range" />
        <Kpi label="Deals won" value={k.deals_won_in_range} sub="in range" />
        <Kpi label="Booked → completed" value={`${c.completed_rate}%`} sub="meetings that progressed" />
        <Kpi label="Opportunity → won" value={`${c.opp_to_won_rate}%`} sub="overall close rate" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.1fr .9fr", gap: 14, marginBottom: 18 }}>
        {/* Conversion funnel */}
        <div className="card" style={{ padding: 18 }}>
          <h2 style={{ fontSize: 15, marginBottom: 12 }}>Conversion funnel</h2>
          {data.funnel.map((f, i) => {
            const prev = i > 0 ? data.funnel[i - 1].count : null;
            const stepRate = prev ? Math.round(100 * f.count / prev) : null;
            return (
              <div key={f.label} style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <span>{f.label}</span>
                  <span style={{ color: "var(--muted)" }}>
                    <b style={{ color: "var(--ink, #16263c)" }}>{f.count}</b>
                    {stepRate != null && <span> · {stepRate}%</span>}
                  </span>
                </div>
                <div style={{ height: 12, background: "#eef2f7", borderRadius: 6, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.max(3, 100 * f.count / funnelMax)}%`,
                    background: ["#93b8e6", "#4a95e0", "var(--primary)", "#22a06b"][i] || "var(--primary)", borderRadius: 6 }} />
                </div>
              </div>
            );
          })}
        </div>

        {/* Top open deals */}
        <div className="card" style={{ padding: 18 }}>
          <h2 style={{ fontSize: 15, marginBottom: 12 }}>Biggest open deals</h2>
          {data.top_open_deals.length === 0
            ? <div style={{ color: "var(--muted)", fontSize: 13 }}>No open deals yet.</div>
            : data.top_open_deals.map((d) => (
              <div key={d.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "8px 0", borderBottom: "1px solid #f0f3f7", fontSize: 13 }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{d.name}</div>
                  <div style={{ color: "var(--muted)", fontSize: 12 }}>{d.stage}</div>
                </div>
                <div style={{ fontWeight: 700 }}>{money(d.value)}</div>
              </div>
            ))}
        </div>
      </div>

      {/* Weekly trend */}
      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ fontSize: 15, marginBottom: 4 }}>Weekly trend</h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 14 }}>Meetings booked and revenue won, by week.</p>

        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Meetings booked / week</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 90, marginBottom: 14 }}>
          {data.trend.map((t, i) => (
            <div key={i} title={`${t.week}: ${t.meetings} meetings`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}>
              <div style={{ height: `${Math.max(2, 100 * t.meetings / mtgMax)}%`, background: "var(--primary)", borderRadius: "3px 3px 0 0" }} />
            </div>
          ))}
        </div>

        <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Revenue won / week</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 90 }}>
          {data.trend.map((t, i) => (
            <div key={i} title={`${t.week}: ${money(t.won_value)}`} style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}>
              <div style={{ height: `${Math.max(2, 100 * t.won_value / wonMax)}%`, background: "#22a06b", borderRadius: "3px 3px 0 0" }} />
            </div>
          ))}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
          <span>{data.trend[0]?.week}</span><span>{data.trend[data.trend.length - 1]?.week}</span>
        </div>
      </div>
    </>
  );
}
