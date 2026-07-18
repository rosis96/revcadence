// Reply Management → Inbox (DESIGN_SYSTEM.md step 5). Gmail-feel, three panes:
// conversation list · thread + composer · AI panel. Status tabs across the top.
// Same backend as before; pinning is a local flag (no engine changes).
import { useEffect, useMemo, useRef, useState } from "react";
import { Ban, Check, Download, MoreHorizontal, PanelRightOpen, Pencil, Pin, PinOff,
  RefreshCw, Send, Tag, Trash2, X } from "lucide-react";
import { api, timeAgo } from "../api";
import { useAuth } from "../auth";
import {
  Avatar, Badge, Button, ErrorBox, Modal, PageHeader, Skeleton, StatusPill, Tabs,
  useApi, useToast,
} from "../components";

// Status labels a user can set from the inbox (mirrors the campaign tool's set).
// The token is what we store on ReplyLead.stage; the backend maps it to the CRM.
const LABELS = [
  ["lead", "Lead"], ["interested", "Interested"], ["booked", "Meeting booked"],
  ["meeting_completed", "Meeting completed"], ["won", "Won"], ["no_show", "No Show"],
  ["out_of_office", "Out of office"], ["wrong_person", "Wrong person"],
  ["not_interested", "Not interested"],
];
const LABEL_OF = Object.fromEntries(LABELS);

const ACTION_TONE = (a) => a === "stop" ? "red" : a === "would_send" ? "amber"
  : a === "send" ? "green" : a === "skip_enrich" ? "blue" : "gray";
// CRM pipeline stage reflected onto the reply lead (two-way sync).
const STAGE_LABEL = { booked: "Meeting Booked", meeting_completed: "Meeting Completed",
  no_show: "No Show", follow_up: "Follow-up", won: "Won", lost: "Lost" };
const STAGE_TONE = { booked: "blue", meeting_completed: "indigo", no_show: "amber",
  follow_up: "amber", won: "green", lost: "red" };
const INTENT_TONE = (i) =>
  /positive/.test(i || "") ? "green" :
  /pricing|question/.test(i || "") ? "blue" :
  /not_interested|stop|unsub/.test(i || "") ? "red" : "gray";

const PINS_KEY = "rc_reply_pins";
const getPins = () => { try { return new Set(JSON.parse(localStorage.getItem(PINS_KEY)) || []); } catch { return new Set(); } };

function csvCell(v) { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; }
function exportLeadsCsv(rows) {
  const head = ["first_name", "last_name", "email", "company", "intent", "decision", "stage", "workspace"];
  const lines = [head.join(",")].concat(rows.map((l) => {
    const [fn, ...rest] = (l.name || "").split(" ");
    return [fn || "", rest.join(" ") || "", l.email || "", l.company || "", l.intent || "",
            l.action || "", l.stage || "", l.workspace || ""].map(csvCell).join(",");
  }));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `reply-leads-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
}

export default function ReplyInbox() {
  const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
  const { wsParam } = useAuth();
  const [tab, setTab] = useState(params.get("status") ?? "needs_review");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState(params.get("open") ? Number(params.get("open")) : null);
  const [pins, setPins] = useState(getPins);
  const [intent, setIntent] = useState("");
  const [sel, setSel] = useState({});
  const [aiOpen, setAiOpen] = useState(localStorage.getItem("rc_ai_panel") === "1");
  const toggleAi = () => setAiOpen((v) => { localStorage.setItem("rc_ai_panel", v ? "0" : "1"); return !v; });
  const toast = useToast();
  const status = tab === "pinned" ? "" : tab;
  const { data, error, loading, reload } = useApi("/api/reply/leads", { status, q, workspace_id: wsParam });

  const leads = data?.leads || [];
  const counts = data?.counts || {};
  const intents = useMemo(() => [...new Set(leads.map((l) => l.intent).filter(Boolean))].sort(), [leads]);
  const shown = useMemo(() => {
    let s = tab === "pinned" ? leads.filter((l) => pins.has(l.id)) : leads;
    if (intent) s = s.filter((l) => l.intent === intent);
    return s;
  }, [leads, tab, pins, intent]);
  const selIds = Object.keys(sel).filter((k) => sel[k]);
  const exportSel = () => {
    const rows = leads.filter((l) => sel[l.id]);
    if (!rows.length) { toast("Select some leads first (checkboxes)", "bad"); return; }
    exportLeadsCsv(rows);
  };

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
        actions={<>
          {intents.length > 0 && (
            <select value={intent} onChange={(e) => setIntent(e.target.value)}
              style={{ padding: "7px 10px", borderRadius: 8, fontSize: 13, maxWidth: 200 }}>
              <option value="">All intents</option>
              {intents.map((i) => <option key={i} value={i}>{i.replaceAll("_", " ")}</option>)}
            </select>
          )}
          <Button variant="secondary" icon={Download} disabled={!selIds.length} onClick={exportSel}>
            Export{selIds.length ? ` (${selIds.length})` : ""}</Button>
          <Button variant="secondary" icon={RefreshCw} onClick={reload}>Refresh</Button>
        </>} />

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

      <div className={`inbox3 ${aiOpen ? "" : "no-ai"}`}>
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
                <input type="checkbox" checked={!!sel[l.id]} onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setSel({ ...sel, [l.id]: e.target.checked })}
                  style={{ alignSelf: "center", marginRight: 2 }} />
                <Avatar name={l.name || l.email} size={30} />
                <span className="cv-main">
                  <span className="cv-top">
                    <span className="cv-name">{l.name || l.email}</span>
                    <span className="cv-when">{timeAgo(l.at)}</span>
                  </span>
                  <span className="cv-snip">{l.company ? `${l.company} · ` : ""}{l.email}</span>
                  <span className="cv-meta">
                    {l.intent && <StatusPill tone={INTENT_TONE(l.intent)}>{l.intent.replaceAll("_", " ")}</StatusPill>}
                    {STAGE_LABEL[l.stage] && <Badge tone={STAGE_TONE[l.stage] || "gray"}>{STAGE_LABEL[l.stage]}</Badge>}
                    {pins.has(l.id) && <Badge tone="indigo">pinned</Badge>}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </div>

        {openId
          ? <Thread key={openId} id={openId} pinned={pins.has(openId)} onPin={() => togglePin(openId)}
              aiOpen={aiOpen} onToggleAi={toggleAi} onChanged={reload} />
          : <div className="ib-none">Select a conversation</div>}
      </div>
    </>
  );
}

function Thread({ id, pinned, onPin, aiOpen, onToggleAi, onChanged }) {
  const toast = useToast();
  const { data: l, error, loading, reload } = useApi(`/api/reply/leads/${id}`);
  const [draft, setDraft] = useState(null);
  const [followup, setFollowup] = useState("");
  const [busy, setBusy] = useState("");
  const [menu, setMenu] = useState(false);
  const [edit, setEdit] = useState(null);
  const menuRef = useRef(null);
  useEffect(() => {
    const h = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenu(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  if (loading) {
    return (
      <div className="ib-pane" style={{ padding: 20, display: "grid", gap: 12, alignContent: "start" }}>
        <Skeleton w="40%" /><Skeleton w="90%" h={60} /><Skeleton w="70%" h={40} />
      </div>
    );
  }
  if (error) return <div className="ib-pane" style={{ padding: 20 }}><ErrorBox msg={error} /></div>;

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
  // Follow up in the SAME thread after the first reply — sent via the platform (Instantly/Bison).
  const sendFollowup = () => {
    if (!followup.trim()) return;
    act(async () => { await api(`/api/reply/leads/${id}/send`, { method: "POST", body: { body: followup } }); setFollowup(""); },
      "fup", "Follow-up sent");
  };
  const setLabel = (token) => act(() => api(`/api/reply/leads/${id}/action`,
    { method: "POST", body: { stage: token, reviewed: true } }), "label", `Marked ${LABEL_OF[token] || token}`);
  const removeLead = (block) => {
    if (!confirm(block ? "Delete this lead and block the sender?" : "Delete this lead?")) return;
    act(async () => { await api(`/api/reply/leads/${id}?block=${block ? "true" : "false"}`, { method: "DELETE" }); onChanged(); },
      "del", block ? "Lead deleted & sender blocked" : "Lead deleted");
    setMenu(false);
  };

  // clean thread (tolerate key variants, drop empty bubbles, always show the inbound)
  const msgText = (m) => (m.text || m.body || m.message || m.text_body || "").trim();
  let thread = (l.thread || [])
    .map((m) => ({ direction: m.direction === "out" ? "out" : "in", text: msgText(m) }))
    .filter((m) => m.text);
  if (!thread.some((m) => m.direction === "in") && (l.reply_text || "").trim()) {
    thread = [{ direction: "in", text: l.reply_text.trim() }, ...thread];
  }
  if (thread.length === 0 && (l.reply_text || "").trim()) thread = [{ direction: "in", text: l.reply_text.trim() }];

  // The composer is for review only: show it when the reply hasn't been sent yet.
  const needsReview = !l.replied && l.action !== "stop";

  return (
    <>
      <div className="ib-pane">
        <div className="ib-thread-head">
          <Avatar name={l.name || l.email} size={30} />
          <h2>{l.name || l.email}{STAGE_LABEL[l.stage] && <Badge tone={STAGE_TONE[l.stage] || "gray"} style={{ marginLeft: 8 }}>{STAGE_LABEL[l.stage]}</Badge>}</h2>
          <Button size="sm" variant="ghost" icon={pinned ? PinOff : Pin} onClick={onPin}>{pinned ? "Unpin" : "Pin"}</Button>
          <Button size="sm" variant={aiOpen ? "secondary" : "ghost"} icon={PanelRightOpen} onClick={onToggleAi}>Details</Button>
          <div className="ib-menu-wrap" ref={menuRef}>
            <Button size="sm" variant="ghost" icon={MoreHorizontal} onClick={() => setMenu((v) => !v)} />
            {menu && (
              <div className="ib-menu">
                <div className="mlabel">Set status (syncs to CRM)</div>
                {LABELS.map(([token, label]) => (
                  <button key={token} onClick={() => { setLabel(token); setMenu(false); }}>
                    {l.stage === token ? <Check size={15} /> : <Tag size={15} style={{ opacity: 0.5 }} />}{label}</button>
                ))}
                <div className="sep" />
                <button onClick={() => { setEdit({
                  name: l.name || "", email: l.email || "", company: l.company || "",
                  title: l.lead_details?.title || "", location: l.lead_details?.location || "",
                  website: l.lead_details?.website || "", contact_linkedin: l.lead_details?.contact_linkedin || "",
                  company_linkedin: l.lead_details?.company_linkedin || "" }); setMenu(false); }}>
                  <Pencil size={15} /> Edit lead</button>
                <button onClick={() => removeLead(false)}><Trash2 size={15} /> Delete lead</button>
                <button onClick={() => removeLead(true)} style={{ color: "var(--bad)" }}><Ban size={15} /> Delete &amp; block sender</button>
              </div>
            )}
          </div>
        </div>

        <div className="ib-msgs">
          {thread.length === 0 && <div className="ib-none" style={{ background: "none" }}>No messages captured.</div>}
          {thread.map((m, i) => (
            <div key={i} className={`msg ${m.direction === "in" ? "in" : "out"}`}>
              <div className="who">{m.direction === "in" ? (l.name || "Prospect") : "Us"}</div>
              <div style={{ whiteSpace: "pre-wrap" }}>{m.text}</div>
            </div>
          ))}
        </div>

        {needsReview ? (
          <div className="ib-compose">
            {l.send_error && <div className="error-box" style={{ fontSize: 12.5 }}>Last send failed: {l.send_error}</div>}
            {l.platform === "instantly" && l.can_send_instantly === false && (
              <div className="error-box" style={{ fontSize: 12.5, background: "#FFFAEB", borderColor: "#FEDF89", color: "#B54708" }}>
                Can't send through Instantly: the webhook didn't include the reply target. Point the Instantly
                webhook at the reply-received event so it carries the email id and sending mailbox.
              </div>
            )}
            <textarea value={body} onChange={(e) => setDraft(e.target.value)} placeholder="Review, edit, then approve…" />
            <div className="row">
              <Button icon={Send} loading={busy === "send"} disabled={!!busy} onClick={send}>Approve &amp; Send</Button>
              <Button variant="secondary" loading={busy === "save"} disabled={!!busy} onClick={save}>Save draft</Button>
              <span style={{ flex: 1 }} />
              <Button size="sm" variant="ghost" disabled={!!busy}
                onClick={() => act(() => api(`/api/reply/leads/${id}/action`, { method: "POST", body: { reviewed: true } }), "rev", "Marked reviewed")}>Mark reviewed</Button>
            </div>
          </div>
        ) : l.replied ? (
          <div className="ib-compose">
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--muted)", marginBottom: 2 }}>
              <Check size={15} style={{ color: "var(--ok)" }} /> Replied — sent. Send a follow-up in the same thread:
            </div>
            {l.platform === "instantly" && l.can_send_instantly === false && (
              <div className="error-box" style={{ fontSize: 12.5, background: "#FFFAEB", borderColor: "#FEDF89", color: "#B54708" }}>
                Can't send through Instantly: the webhook didn't include the reply target.
              </div>
            )}
            <textarea value={followup} onChange={(e) => setFollowup(e.target.value)} placeholder="Write a follow-up… (sent via the same thread)" />
            <div className="row">
              <Button icon={Send} loading={busy === "fup"} disabled={!followup.trim() || !!busy} onClick={sendFollowup}>Send follow-up</Button>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 11.5, color: "var(--muted2)" }}>Sent from {l.workspace} via {l.platform}</span>
            </div>
          </div>
        ) : (
          <div className="ib-sent-note">
            <Ban size={16} /> Stopped — no reply will be sent. Use ⋯ to change status.
          </div>
        )}
      </div>

      {aiOpen && (
        <div className="ib-pane ib-ai">
          <div className="ib-ai-h" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            AI assistant <button className="iconbtn" style={{ width: 28, height: 28 }} onClick={onToggleAi}><X size={14} /></button>
          </div>
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
      )}

      {edit && <EditLeadModal id={id} form={edit} setForm={setEdit} onClose={() => setEdit(null)}
        onSaved={() => { setEdit(null); reload(); onChanged(); toast("Lead updated & synced to CRM"); }} />}
    </>
  );
}

function EditLeadModal({ id, form, setForm, onClose, onSaved }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const F = (k, label, ph) => (
    <div className="field"><label>{label}</label>
      <input value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} placeholder={ph} /></div>
  );
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try { await api(`/api/reply/leads/${id}`, { method: "PUT", body: form }); onSaved(); }
    catch (err) { toast(err.message, "bad"); }
    setBusy(false);
  };
  return (
    <Modal title="Edit lead" onClose={onClose}>
      <form onSubmit={submit}>
        <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>Everything the webhook captured. Saving syncs these to the matching CRM contact/company.</p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {F("name", "Name", "Full name")}
          {F("email", "Email", "name@company.com")}
          {F("company", "Company", "Company name")}
          {F("title", "Title", "Head of Growth")}
          {F("location", "Location", "City, Country")}
          {F("website", "Website", "company.com")}
          {F("contact_linkedin", "Contact LinkedIn", "linkedin.com/in/…")}
          {F("company_linkedin", "Company LinkedIn", "linkedin.com/company/…")}
        </div>
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{busy ? "Saving…" : "Save & sync"}</button>
        </div>
      </form>
    </Modal>
  );
}
