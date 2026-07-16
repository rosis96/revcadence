// Reply Management → Inbox (DESIGN_SYSTEM.md step 5). Gmail-feel, three panes:
// conversation list · thread + composer · AI panel. Status tabs across the top.
// Same backend as before; pinning is a local flag (no engine changes).
import { useEffect, useMemo, useState } from "react";
import { Pin, PinOff, RefreshCw, Send } from "lucide-react";
import { api, timeAgo } from "../api";
import { useAuth } from "../auth";
import {
  Avatar, Badge, Button, ErrorBox, PageHeader, Skeleton, StatusPill, Tabs,
  useApi, useToast,
} from "../components";

const ACTION_TONE = (a) => a === "stop" ? "red" : a === "would_send" ? "amber"
  : a === "send" ? "green" : a === "skip_enrich" ? "blue" : "gray";
const INTENT_TONE = (i) =>
  /positive/.test(i || "") ? "green" :
  /pricing|question/.test(i || "") ? "blue" :
  /not_interested|stop|unsub/.test(i || "") ? "red" : "gray";

const PINS_KEY = "rc_reply_pins";
const getPins = () => { try { return new Set(JSON.parse(localStorage.getItem(PINS_KEY)) || []); } catch { return new Set(); } };

export default function ReplyInbox() {
  const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
  const { wsParam } = useAuth();
  const [tab, setTab] = useState(params.get("status") ?? "needs_review");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState(params.get("open") ? Number(params.get("open")) : null);
  const [pins, setPins] = useState(getPins);
  const status = tab === "pinned" ? "" : tab;
  const { data, error, loading, reload } = useApi("/api/reply/leads", { status, q, workspace_id: wsParam });

  const leads = data?.leads || [];
  const counts = data?.counts || {};
  const shown = useMemo(
    () => (tab === "pinned" ? leads.filter((l) => pins.has(l.id)) : leads),
    [leads, tab, pins]);

  useEffect(() => {
    if (openId && !shown.some((l) => l.id === openId)) setOpenId(shown[0]?.id ?? null);
    else if (!openId && shown.length) setOpenId(shown[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, data]);

  const togglePin = (id) => {
    const next = new Set(pins);
    next.has(id) ? next.delete(id) : next.add(id);
    setPins(next);
    localStorage.setItem(PINS_KEY, JSON.stringify([...next]));
  };

  if (error) return <ErrorBox msg={error} retry={reload} />;

  return (
    <>
      <PageHeader title="Inbox" desc="Every conversation, with the AI's read and your one-click actions."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={reload}>Refresh</Button>} />

      <div style={{ marginBottom: 14 }}>
        <Tabs value={tab} onChange={(t) => { setTab(t); setOpenId(null); }} tabs={[
          { key: "needs_review", label: "Needs Review", count: counts.needs_review ?? 0 },
          { key: "replied", label: "Replied", count: counts.replied ?? 0 },
          { key: "booked", label: "Meeting Booked", count: counts.booked ?? 0 },
          { key: "stopped", label: "Stopped", count: counts.stopped ?? 0 },
          { key: "pinned", label: "Pinned", count: pins.size },
          { key: "draft", label: "Draft", count: counts.draft ?? 0 },
        ]} />
      </div>

      <div className="inbox3">
        <div className="ib-pane ib-list">
          <div className="ib-search">
            <input type="text" placeholder="Search conversations…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="ib-scroll">
            {loading && [...Array(7)].map((_, i) => (
              <div key={i} style={{ padding: "12px 14px", display: "grid", gap: 7 }}>
                <Skeleton w="55%" /><Skeleton w="85%" h={10} />
              </div>
            ))}
            {!loading && shown.length === 0 && (
              <div className="rc-empty" style={{ padding: 30 }}>Nothing here.</div>
            )}
            {shown.map((l) => (
              <button key={l.id} className={`conv ${openId === l.id ? "on" : ""}`} onClick={() => setOpenId(l.id)}>
                <Avatar name={l.name || l.email} size={30} />
                <span className="cv-main">
                  <span className="cv-top">
                    <span className="cv-name">{l.name || l.email}</span>
                    <span className="cv-when">{timeAgo(l.at)}</span>
                  </span>
                  <span className="cv-snip">{l.company ? `${l.company} · ` : ""}{l.email}</span>
                  <span className="cv-meta">
                    {l.intent && <StatusPill tone={INTENT_TONE(l.intent)}>{l.intent.replaceAll("_", " ")}</StatusPill>}
                    {pins.has(l.id) && <Badge tone="indigo">pinned</Badge>}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        {openId
          ? <Thread key={openId} id={openId} pinned={pins.has(openId)} onPin={() => togglePin(openId)} onChanged={reload} />
          : <div className="ib-none">Select a conversation</div>}
      </div>
    </>
  );
}

function Thread({ id, pinned, onPin, onChanged }) {
  const toast = useToast();
  const { data: l, error, loading, reload } = useApi(`/api/reply/leads/${id}`);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState("");

  if (loading) {
    return (
      <div className="ib-pane" style={{ gridColumn: "span 2", padding: 20, display: "grid", gap: 12, alignContent: "start" }}>
        <Skeleton w="40%" /><Skeleton w="90%" h={60} /><Skeleton w="70%" h={40} />
      </div>
    );
  }
  if (error) return <div className="ib-pane" style={{ gridColumn: "span 2", padding: 20 }}><ErrorBox msg={error} /></div>;

  const body = draft ?? l.main_reply;
  const act = async (fn, key, ok) => {
    setBusy(key);
    try { await fn(); reload(); onChanged(); ok && toast(ok); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const save = () => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { main_reply: body } }), "save", "Draft saved");
  const send = () => act(async () => {
    await api(`/api/reply/leads/${id}/action`, { method: "POST", body: { main_reply: body } });
    await api(`/api/reply/leads/${id}/send`, { method: "POST" });
  }, "send", "Reply sent");

  const thread = (l.thread || []).length > 0 ? l.thread
    : (l.reply_text ? [{ direction: "in", text: l.reply_text }] : []);

  return (
    <>
      <div className="ib-pane">
        <div className="ib-thread-head">
          <Avatar name={l.name || l.email} size={30} />
          <h2>{l.name || l.email}</h2>
          <Button size="sm" variant="ghost" icon={pinned ? PinOff : Pin} onClick={onPin}>{pinned ? "Unpin" : "Pin"}</Button>
        </div>
        <div className="ib-msgs">
          {thread.length === 0 && <div className="ib-none" style={{ background: "none" }}>No messages captured.</div>}
          {thread.map((m, i) => (
            <div key={i} className={`msg ${m.direction === "in" ? "in" : "out"}`}>
              <div className="who">{m.direction === "in" ? (l.name || "Prospect") : "Us"}</div>
              {m.text}
            </div>
          ))}
        </div>
        <div className="ib-compose">
          {l.send_error && <div className="error-box" style={{ fontSize: 12.5 }}>Last send failed: {l.send_error}</div>}
          {l.platform === "instantly" && l.can_send_instantly === false && (
            <div className="error-box" style={{ fontSize: 12.5, background: "#FFFAEB", borderColor: "#FEDF89", color: "#B54708" }}>
              Can't send through Instantly: the webhook didn't include the reply target. Point the Instantly
              webhook at the reply-received event so it carries the email id and sending mailbox.
            </div>
          )}
          <textarea value={body} onChange={(e) => setDraft(e.target.value)} placeholder="Your reply…" />
          <div className="row">
            <Button icon={Send} loading={busy === "send"} disabled={!!busy || l.replied} onClick={send}>
              {l.replied ? "Already sent" : "Approve & Send"}</Button>
            <Button variant="secondary" loading={busy === "save"} disabled={!!busy} onClick={save}>Save draft</Button>
            <span style={{ flex: 1 }} />
            <Button size="sm" variant="ghost" disabled={!!busy}
              onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { stage: "booked", reviewed: true } }), "book", "Marked booked")}>Mark booked</Button>
            <Button size="sm" variant="ghost" disabled={!!busy}
              onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { reviewed: true } }), "rev", "Marked reviewed")}>Mark reviewed</Button>
            <Button size="sm" variant="danger" disabled={!!busy}
              onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { action: "stop" } }), "stop", "Stopped")}>Stop</Button>
          </div>
        </div>
      </div>

      <div className="ib-pane ib-ai">
        <div className="ib-ai-h">AI assistant</div>
        <div className="ib-ai-body">
          <div className="ai-block"><div className="lbl">Intent</div>
            <div className="val">{l.intent
              ? <StatusPill tone={INTENT_TONE(l.intent)}>{l.intent.replaceAll("_", " ")}</StatusPill> : "—"}
              {l.confidence && <span style={{ color: "var(--muted2)", fontSize: 12, marginLeft: 6 }}>{l.confidence}</span>}
            </div></div>
          <div className="ai-block"><div className="lbl">Decision</div>
            <div className="val"><StatusPill tone={ACTION_TONE(l.action)}>{l.action || "—"}</StatusPill>
              {l.replied && <Badge tone="green">sent</Badge>}</div></div>
          <div className="ai-block"><div className="lbl">Workspace</div><div className="val">{l.workspace}</div></div>
          {l.lead_details && Object.values(l.lead_details).some(Boolean) && (
            <div className="ai-block"><div className="lbl">Lead details</div>
              <div className="val" style={{ display: "grid", gap: 4, fontSize: 12.5 }}>
                {l.lead_details.title && <span>{l.lead_details.title}</span>}
                {l.lead_details.location && <span>{l.lead_details.location}</span>}
                {l.lead_details.website && <a href={l.lead_details.website.startsWith("http") ? l.lead_details.website : `https://${l.lead_details.website}`} target="_blank" rel="noreferrer">Website ↗</a>}
                {l.lead_details.contact_linkedin && <a href={l.lead_details.contact_linkedin} target="_blank" rel="noreferrer">LinkedIn ↗</a>}
                {l.lead_details.company_linkedin && <a href={l.lead_details.company_linkedin} target="_blank" rel="noreferrer">Company LinkedIn ↗</a>}
              </div></div>
          )}
          {l.followups?.length > 0 && (
            <div className="ai-block"><div className="lbl">Follow-ups queued ({l.followups.length})</div>
              <div className="val" style={{ display: "grid", gap: 8 }}>
                {l.followups.map((f, i) => (
                  <div key={i} className="card" style={{ padding: 10, fontSize: 12.5 }}>
                    <b style={{ fontSize: 11, color: "var(--muted2)" }}>FUP{i + 1}</b>
                    <div style={{ whiteSpace: "pre-wrap", marginTop: 3 }}>{f}</div>
                  </div>
                ))}
              </div></div>
          )}
        </div>
      </div>
    </>
  );
}
