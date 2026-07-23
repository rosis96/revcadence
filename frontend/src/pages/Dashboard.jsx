// Master Dashboard — the command center (DESIGN_SYSTEM.md Part 4, step 2).
// Not widgets: flat, scannable lists of everything that needs attention today,
// built ONLY from the shared component library.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Calendar, CheckSquare, FileText, Inbox as InboxIcon, Receipt, ScrollText,
  CheckCircle2, Circle,
} from "lucide-react";
import { useAuth } from "../auth";
import { money, timeAgo } from "../api";
import {
  ActivityFeed, ErrorBox, PageHeader, Row, RowCard, Skeleton, StatCard,
  StatusPill, useApi,
} from "../components";

const DOC_TONE = {
  draft: "gray", published: "blue", ready: "blue", sent: "blue", viewed: "amber",
  client_signed: "amber", issued: "blue", partially_paid: "amber", overdue: "red",
};
const INTENT_TONE = (i) =>
  /positive/.test(i || "") ? "green" :
  /pricing|question/.test(i || "") ? "blue" :
  /not_interested|stop|unsub/.test(i || "") ? "red" : "gray";

const fmtTime = (iso) => (iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z"))
  .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "");
const fmtDue = (iso) => (iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z"))
  .toLocaleDateString([], { month: "short", day: "numeric" }) : "no due date");

function GettingStarted({ wsParam, nav }) {
  const { data } = useApi("/api/setup/checklist", { workspace_id: wsParam });
  const key = `rc_setup_dismissed_${wsParam || "all"}`;
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(key) === "1");
  if (!data || data.complete || dismissed) return null;
  return (
    <div className="card" style={{ padding: 18, marginBottom: 16, borderColor: "#bfdcf6",
      background: "linear-gradient(180deg,#fff,#f4f9ff)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <h2 style={{ fontSize: 16, margin: 0 }}>Getting started</h2>
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
            {data.done} of {data.total} steps done — finish setup to get the engine running.</div>
        </div>
        <button className="btn ghost sm" onClick={() => { localStorage.setItem(key, "1"); setDismissed(true); }}>Dismiss</button>
      </div>
      <div style={{ height: 8, background: "#e6eef8", borderRadius: 6, overflow: "hidden", marginBottom: 14 }}>
        <div style={{ height: "100%", width: `${100 * data.done / data.total}%`, background: "#1f8fe6" }} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
        {data.steps.map((s) => (
          <div key={s.key} onClick={() => !s.done && nav(s.href)}
            style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 10px", borderRadius: 8,
              cursor: s.done ? "default" : "pointer", background: s.done ? "transparent" : "#fff",
              border: `1px solid ${s.done ? "transparent" : "#e6edf5"}` }}>
            {s.done
              ? <CheckCircle2 size={18} style={{ color: "#22a06b", flexShrink: 0, marginTop: 1 }} />
              : <Circle size={18} style={{ color: "#9fb0c0", flexShrink: 0, marginTop: 1 }} />}
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: s.done ? "var(--muted)" : "inherit",
                textDecoration: s.done ? "line-through" : "none" }}>{s.label}</div>
              {!s.done && <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{s.hint}</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/dashboard/command", { workspace_id: wsParam });

  if (error) return <ErrorBox msg={error} retry={reload} />;

  if (loading || !data) {
    return (
      <>
        <PageHeader title="Dashboard" desc="Everything that needs your attention today." />
        <div className="metrics">{[...Array(4)].map((_, i) => (
          <div className="metric" key={i}><Skeleton w="50%" /><Skeleton w="70%" h={26} style={{ marginTop: 10 }} /></div>
        ))}</div>
        <div className="cc-grid">{[...Array(6)].map((_, i) => (
          <div className="card rowcard" key={i} style={{ padding: 16, display: "grid", gap: 12 }}>
            <Skeleton w="40%" /><Skeleton /><Skeleton w="85%" /><Skeleton w="70%" />
          </div>
        ))}</div>
      </>
    );
  }

  const t = data.totals || {};
  const maxVal = Math.max(1, ...(data.pipeline || []).map((p) => p.value));

  return (
    <>
      <PageHeader title="Dashboard" desc="Everything that needs your attention today. Press ⌘K to find anything." />

      <GettingStarted wsParam={wsParam} nav={nav} />

      <div className="metrics">
        <StatCard label="Open pipeline" value={money(data.open_value)} sub={`${t.active_deals ?? 0} active deals`} />
        <StatCard label="Won revenue" value={money(data.won_value)} sub="all time" />
        <StatCard label="Meetings booked" value={t.meetings_booked ?? 0} sub={`${(data.meetings_today || []).length} today`} />
        <StatCard label="Needs review" value={data.needs_review ?? 0} sub={`${t.replies ?? 0} total replies`} />
      </div>

      <div className="cc-grid">
        <RowCard title="Today's meetings" count={(data.meetings_today || []).length}
          viewAll="/pipeline" empty="No meetings today. Enjoy the focus time.">
                    {(data.meetings_today || []).map((m) => (
            <Row key={m.id} icon={Calendar} title={m.title} sub={m.kind === "meeting_held" ? "held" : "booked"}
              right={fmtTime(m.at)} onClick={() => nav("/pipeline")} />
          ))}
        </RowCard>

        <RowCard title="Tasks" count={(data.tasks || []).length} viewAll="/pipeline" empty="No open tasks.">
                    {(data.tasks || []).map((tk) => (
            <Row key={tk.id} icon={CheckSquare} title={tk.title} right={fmtDue(tk.due_at)}
              onClick={() => nav("/pipeline")} />
          ))}
        </RowCard>

        <RowCard title="Recent replies" viewAll="/reply/inbox" empty="No replies yet.">
                    {(data.recent_replies || []).map((r) => (
            <Row key={r.id} avatar={r.name} title={r.name}
              sub={r.at ? timeAgo(r.at) : ""}
              right={r.intent && <StatusPill tone={INTENT_TONE(r.intent)}>{r.intent.replaceAll("_", " ")}</StatusPill>}
              onClick={() => nav("/reply/inbox")} />
          ))}
        </RowCard>

        <RowCard title="Pipeline" className="span2" viewAll="/pipeline" empty="No stages yet.">
                    {(data.pipeline || []).map((p) => (
            <div className="bar-row" key={p.stage} style={{ padding: "4px 10px" }}>
              <div className="lbl">{p.stage}</div>
              <div className="bar"><div style={{ width: `${(p.value / maxVal) * 100}%`, background: p.color || "var(--primary)" }} /></div>
              <div className="n">{p.count} · {money(p.value)}</div>
            </div>
          ))}
        </RowCard>

        <RowCard title="Recent clients" viewAll="/clients" empty="No clients yet. Promote a won deal to create one.">
                    {(data.recent_clients || []).map((c) => (
            <Row key={c.id} avatar={c.company} title={c.company}
              right={<StatusPill tone={c.active ? "green" : "gray"}>{c.active ? "Active" : "Setup"}</StatusPill>}
              onClick={() => nav(`/companies/${c.company_id}`)} />
          ))}
        </RowCard>

        <RowCard title="Blueprints waiting" count={(data.blueprints_waiting || []).length}
          viewAll="/blueprints" empty="Nothing waiting.">
                    {(data.blueprints_waiting || []).map((d) => (
            <Row key={d.id} icon={FileText} title={d.title}
              right={<StatusPill tone={DOC_TONE[d.status] || "gray"}>{d.status.replaceAll("_", " ")}</StatusPill>}
              onClick={() => nav(`/blueprints/${d.id}`)} />
          ))}
        </RowCard>

        <RowCard title="Agreements waiting" count={(data.agreements_waiting || []).length}
          viewAll="/blueprints" empty="Nothing waiting for signature.">
                    {(data.agreements_waiting || []).map((a) => (
            <Row key={a.id} icon={ScrollText} title={a.title}
              right={<StatusPill tone={DOC_TONE[a.status] || "gray"}>{a.status.replaceAll("_", " ")}</StatusPill>}
              onClick={() => nav(`/agreements/${a.id}`)} />
          ))}
        </RowCard>

        <RowCard title="Invoices waiting" count={(data.invoices_waiting || []).length}
          viewAll="/blueprints" empty="Nothing outstanding.">
                    {(data.invoices_waiting || []).map((i) => (
            <Row key={i.id} icon={Receipt} title={i.title}
              right={<StatusPill tone={DOC_TONE[i.status] || "gray"}>{i.status.replaceAll("_", " ")}</StatusPill>}
              onClick={() => nav(`/invoices/${i.id}`)} />
          ))}
        </RowCard>

        <RowCard title="Recent activity" className="span2" viewAll="/activity" empty="Events from every section appear here.">
          {(data.recent_activity || []).length > 0 && (
            <div style={{ padding: "0 6px" }}>
              <ActivityFeed items={(data.recent_activity || []).map((a, i) => ({
                id: i, actor: a.kind, title: a.title || a.kind, subtitle: a.kind.replaceAll("_", " "), at: a.at,
              }))} />
            </div>
          )}
        </RowCard>

        <RowCard title="Replies snapshot" viewAll="/reply">
          <Row icon={InboxIcon} title="Total replies" right={t.replies ?? 0} onClick={() => nav("/reply")} />
          <Row icon={InboxIcon} title="Positive replies" right={t.positive_replies ?? 0} onClick={() => nav("/reply/inbox")} />
          <Row icon={InboxIcon} title="Needs review" right={data.needs_review ?? 0} onClick={() => nav("/reply/inbox")} />
          <Row icon={InboxIcon} title="Stalled deals (14d+)" right={t.stalled_deals ?? 0} onClick={() => nav("/pipeline")} />
        </RowCard>
      </div>
    </>
  );
}
