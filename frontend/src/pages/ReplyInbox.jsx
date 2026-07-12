// Reply Management → Inbox: the review console (Needs Review queue, drawer with
// editable draft + Approve & Send). Its OWN section — nothing else shown.
import { useState } from "react";
import { api, timeAgo } from "../api";
import { Badge, Drawer, Empty, ErrorBox, Spinner, useApi } from "../components";

const CHIPS = [["", "All"], ["needs_review", "Needs Review"], ["replied", "Replied"],
  ["booked", "Meeting Booked"], ["stopped", "Stopped"]];
const actionTone = (a) => a === "stop" ? "red" : a === "would_send" ? "amber"
  : a === "send" ? "green" : a === "skip_enrich" ? "indigo" : "";

function LeadDrawer({ id, onClose, onChanged }) {
  const { data: l, error, loading, reload } = useApi(`/api/reply/leads/${id}`);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState("");
  if (loading) return <Drawer title="Loading…" onClose={onClose}><Spinner /></Drawer>;
  if (error) return <Drawer title="Error" onClose={onClose}><ErrorBox msg={error} /></Drawer>;
  const body = draft ?? l.main_reply;
  const act = async (fn, key) => { setBusy(key); try { await fn(); reload(); onChanged(); } catch (e) { alert(e.message); } setBusy(""); };
  return (
    <Drawer title={l.name || l.email} onClose={onClose}>
      <div className="kv">
        <div className="k">Workspace</div><div>{l.workspace}</div>
        <div className="k">Intent</div><div>{l.intent ? <Badge tone="indigo">{l.intent}</Badge> : "—"} {l.confidence}</div>
        <div className="k">Decision</div><div><Badge tone={actionTone(l.action)}>{l.action}</Badge> {l.replied && <Badge tone="green">sent</Badge>}</div>
      </div>
      <h3 style={{ fontSize: 13, margin: "12px 0 6px" }}>Prospect's reply</h3>
      <div className="card" style={{ padding: 12, fontSize: 13, background: "#fafbfc" }}>{l.reply_text || "—"}</div>
      <h3 style={{ fontSize: 13, margin: "14px 0 6px" }}>Reply to send</h3>
      <textarea rows={8} style={{ width: "100%" }} value={body} onChange={(e) => setDraft(e.target.value)} />
      <div className="toolbar" style={{ marginTop: 10 }}>
        <button className="btn ghost sm" disabled={busy} onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { main_reply: body } }), "save")}>Save draft</button>
        <button className="btn sm" disabled={busy || l.replied} onClick={() => act(async () => { await api(`/api/reply/leads/${id}/action`, { method: "POST", body: { main_reply: body } }); await api(`/api/reply/leads/${id}/send`, { method: "POST" }); }, "send")}>
          {busy === "send" ? "Sending…" : "✓ Approve & Send"}</button>
      </div>
      <div className="toolbar" style={{ marginTop: 6 }}>
        <button className="btn ghost sm" disabled={busy} onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { stage: "booked", reviewed: true } }), "book")}>Mark booked</button>
        <button className="btn ghost sm" disabled={busy} onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { reviewed: true } }), "rev")}>Mark reviewed</button>
        <button className="btn danger sm" disabled={busy} onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { action: "stop" } }), "stop")}>Stop</button>
      </div>
      {l.followups?.length > 0 && (
        <>
          <h3 style={{ fontSize: 13, margin: "16px 0 6px" }}>Follow-ups ({l.followups.length})</h3>
          {l.followups.map((f, i) => <div key={i} className="card" style={{ padding: 10, marginBottom: 6, fontSize: 12.5 }}><b>FUP{i + 1}</b><br />{f}</div>)}
        </>
      )}
    </Drawer>
  );
}

export default function ReplyInbox() {
  const [status, setStatus] = useState("needs_review");
  const [open, setOpen] = useState(null);
  const { data, error, loading, reload } = useApi("/api/reply/leads", { status });
  return (
    <>
      <div className="chips">
        {CHIPS.map(([v, label]) => (
          <button key={v} className={status === v ? "on" : ""} onClick={() => setStatus(v)}>
            {label} {data?.counts?.[v || "all"] ?? ""}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <button className="btn ghost sm" onClick={reload}>Refresh</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.leads.length === 0 && <Empty icon="✉" title="Nothing here" hint="Replies arrive from Bison/Instantly webhooks pointed at this workspace." />}
      {data && data.leads.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Lead</th><th>Workspace</th><th>Intent</th><th>Decision</th><th>When</th></tr></thead>
          <tbody>
            {data.leads.map((l) => (
              <tr key={l.id} className="click" onClick={() => setOpen(l.id)}>
                <td><b>{l.name || l.email}</b><div style={{ color: "var(--muted)", fontSize: 12 }}>{l.company} · {l.email}</div></td>
                <td style={{ fontSize: 12.5 }}>{l.workspace}</td>
                <td>{l.intent ? <Badge tone="indigo">{l.intent}</Badge> : "—"}</td>
                <td><Badge tone={actionTone(l.action)}>{l.action}</Badge>{l.replied && " ✓"}</td>
                <td>{timeAgo(l.at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && <LeadDrawer id={open} onClose={() => setOpen(null)} onChanged={reload} />}
    </>
  );
}
