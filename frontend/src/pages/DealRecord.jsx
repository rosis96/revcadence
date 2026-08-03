// Deal Workspace — the center of RevCadence. A deal card opens this full page.
// Tabs: Overview (dashboard) · Conversation (same-thread) · Timeline · Blueprint ·
// Agreement · Invoice · Tasks · Files · Notes. Overview answers "what's happening
// with this deal right now?" without opening another tab.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Send, Sparkles, RefreshCw, Mail, Plus, Check, Trash2, Download, FileText, FileSignature, Receipt, PanelRightClose } from "lucide-react";
import { api, download, emailText, money, splitQuoted, timeAgo } from "../api";
import {
  Avatar, Badge, Breadcrumbs, Button, ErrorBox, Modal, Spinner, StatusPill, Timeline,
  useApi, useToast,
} from "../components";

// Grouped record navigation: 5 primary destinations map onto the 9 existing leaf
// tabs. Nothing is removed — Activity/Documents just expose their leaves through a
// secondary segmented control. Leaf keys are unchanged so setTab() and every tab
// body keep working exactly as before.
const PRIMARY = [
  { key: "overview", label: "Overview", leaves: ["overview"] },
  { key: "conversation", label: "Conversation", leaves: ["conversation"] },
  { key: "activity", label: "Activity", leaves: ["timeline", "tasks", "notes"] },
  { key: "documents", label: "Documents", leaves: ["blueprint", "agreement", "invoice", "files"] },
];
const LEAF_LABEL = {
  overview: "Overview", conversation: "Conversation", timeline: "Timeline",
  tasks: "Tasks", notes: "Notes", blueprint: "Blueprint", agreement: "Agreement",
  invoice: "Invoice", files: "Files",
};
const WORKSPACE_TABS = new Set(["conversation"]);   // full-bleed, viewport-height tabs
const primaryFor = (leaf) => (PRIMARY.find((p) => p.leaves.includes(leaf)) || PRIMARY[0]).key;

const HEALTH_TONE = { healthy: "green", cooling: "amber", ghosted: "red", unknown: "gray" };
const RISK_TONE = { low: "green", medium: "amber", high: "red", unknown: "gray" };
const INTENT_TONE = { high: "green", medium: "amber", low: "gray" };

function MessageBubble({ m, contact }) {
  const [open, setOpen] = useState(false);
  const who = m.direction === "in" ? (contact?.name || "Prospect") : "You";
  const { main, quoted } = splitQuoted(emailText(m.body_text));
  return (
    <div className={`msg-row ${m.direction === "in" ? "in" : "out"}`}>
      <Avatar name={who} size={28} />
      <div className={`msg ${m.direction === "in" ? "in" : "out"}`}>
        <div className="who">{who}{m.ai_generated ? " · AI" : ""}{m.status === "cancelled" ? " · cancelled" : ""}</div>
        <div style={{ whiteSpace: "pre-wrap" }}>{main || <span style={{ color: "var(--muted2)" }}>(no text)</span>}</div>
        {quoted && (
          <div style={{ marginTop: 6 }}>
            <button className="quote-toggle" onClick={() => setOpen(!open)}>{open ? "Hide quoted text" : "•••  Show quoted text"}</button>
            {open && <div className="quoted-block">{quoted}</div>}
          </div>
        )}
        <div style={{ fontSize: 10.5, color: "var(--muted2)", marginTop: 5 }}>{timeAgo(m.sent_at || m.created_at)}</div>
      </div>
    </div>
  );
}

// Grouped record navigation: primary row + a secondary segmented control when the
// active primary owns several leaves. Sticky under the global header while scrolling.
function RecordNav({ leaf, setTab }) {
  const activePrimary = primaryFor(leaf);
  const group = PRIMARY.find((p) => p.key === activePrimary);
  const openPrimary = (p) => { if (!p.leaves.includes(leaf)) setTab(p.leaves[0]); };
  return (
    <div className="record-nav">
      <div className="ui-tabs" role="tablist">
        {PRIMARY.map((p) => (
          <button key={p.key} role="tab" aria-selected={activePrimary === p.key}
            className={`ui-tab ${activePrimary === p.key ? "on" : ""}`} onClick={() => openPrimary(p)}>
            {p.label}
          </button>
        ))}
      </div>
      {group && group.leaves.length > 1 && (
        <div className="record-subnav" role="tablist" aria-label={`${group.label} sections`}>
          {group.leaves.map((lf) => (
            <button key={lf} role="tab" aria-selected={leaf === lf}
              className={`seg-btn ${leaf === lf ? "on" : ""}`} onClick={() => setTab(lf)}>
              {LEAF_LABEL[lf]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function DealRecord() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: d, error, loading } = useApi(`/api/deals/${id}`);
  const [tab, setTab] = useState("overview");

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} />;
  if (!d) return <Spinner />;

  const isWorkspace = WORKSPACE_TABS.has(tab);

  return (
    <div className={`deal-record ${isWorkspace ? "is-workspace" : ""}`}>
      <div className="deal-record-head">
        <Breadcrumbs items={[{ label: "Pipeline", href: "/pipeline" }, { label: d.name || "Deal" }]} />
        <div className="page-head" style={{ marginBottom: 10 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-.01em" }}>{d.name || "Untitled deal"}</h1>
            <p style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {d.stage && <StatusPill tone="blue">{d.stage.name}</StatusPill>}
              <span style={{ fontWeight: 700 }}>{money(d.value)}</span>
              {d.company && <Link to={`/companies/${d.company.id}`} style={{ fontSize: 12.5 }}>{d.company.name} →</Link>}
            </p>
          </div>
        </div>
        <RecordNav leaf={tab} setTab={setTab} />
      </div>

      <div className="deal-record-body">
        {tab === "overview" && <OverviewTab dealId={id} deal={d} nav={nav} setTab={setTab} />}
        {tab === "conversation" && <ConversationTab dealId={id} deal={d} contact={d.contact} setTab={setTab} />}
        {tab === "timeline" && <div className="card" style={{ padding: 18 }}><Timeline items={d.timeline || []} /></div>}
        {tab === "blueprint" && <DocTab endpoint={d.company?.id ? "/api/documents" : null} params={{ company_id: d.company?.id }} to="blueprints"
          empty={d.company?.id ? "No blueprint yet." : "Link this deal to a company to see its blueprints."} nav={nav} label={(x) => x.title || x.slug} />}
        {tab === "agreement" && <DocTab endpoint="/api/agreements" params={{ deal_id: id }} to="agreements"
          empty="No agreement yet." nav={nav} label={(x) => `${x.number} · ${x.status}`} />}
        {tab === "invoice" && <DocTab endpoint={d.company?.id ? "/api/invoices" : null} params={{ company_id: d.company?.id }} to="invoices"
          empty={d.company?.id ? "No invoice yet." : "Link this deal to a company to see its invoices."} nav={nav} label={(x) => `${x.number} · ${x.currency} ${(x.total || 0).toLocaleString()}`} />}
        {tab === "tasks" && <TasksTab dealId={id} />}
        {tab === "files" && <FilesTab deal={d} />}
        {tab === "notes" && <NotesTab dealId={id} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Overview
function OverviewTab({ dealId, deal, nav, setTab }) {
  const { data: b, loading } = useApi(`/api/deals/${dealId}/conversation/briefing`);
  if (loading || !b) return <Spinner />;
  const recent = (deal.timeline || []).slice(0, 6);
  return (
    <div className="deal-grid">
      <div style={{ display: "grid", gap: 14 }}>
        {/* AI briefing */}
        <div className="card" style={{ padding: 18, background: "var(--primary-soft)", borderColor: "#D6E7FD" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <Sparkles size={16} style={{ color: "var(--primary)" }} />
            <b style={{ fontSize: 14 }}>What's happening with this deal</b>
            <span style={{ flex: 1 }} />
            <Badge tone={HEALTH_TONE[b.health] || "gray"}>{(b.health || "unknown")[0].toUpperCase() + (b.health || "unknown").slice(1)}</Badge>
          </div>
          <div style={{ fontSize: 14, marginBottom: 6 }}>{b.summary}</div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}><b>Next action:</b> {b.next_action}</div>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <Button size="sm" icon={Send} onClick={() => setTab("conversation")}>Open Conversation</Button>
          </div>
        </div>

        {/* the facts grid */}
        <div className="card" style={{ padding: 18 }}>
          <div className="fact-grid">
            <Fact k="Stage" v={b.stage} />
            <Fact k="Deal value" v={money(deal.value)} />
            <Fact k="Expected close" v={deal.close_date || "—"} />
            <Fact k="Company">{deal.company ? <Link to={`/companies/${deal.company.id}`}>{deal.company.name}</Link> : "—"}</Fact>
            <Fact k="Primary contact" v={b.contact ? b.contact.name || b.contact.email : "—"} />
            <Fact k="Last contact" v={b.last_contact_days == null ? "—" : `${b.last_contact_days}d ago`} />
            <Fact k="Intent"><Badge tone={INTENT_TONE[b.intent] || "gray"}>{b.intent}</Badge></Fact>
            <Fact k="Risk"><Badge tone={RISK_TONE[b.risk] || "gray"}>{b.risk}</Badge></Fact>
            <Fact k="Next follow-up" v={b.next_followup_at ? new Date(b.next_followup_at + "Z").toLocaleDateString() : "none scheduled"} />
          </div>
        </div>

        {/* revenue documents status */}
        <div className="card" style={{ padding: 18 }}>
          <div className="fact-grid">
            <Fact k="Proposal / Blueprint" v={b.blueprint ? (b.blueprint_viewed ? "Viewed" : "Sent") : "None"} />
            <Fact k="Agreement" v={b.agreement_status || "None"} />
            <Fact k="Invoice" v={b.invoice_status || "None"} />
          </div>
        </div>
      </div>

      {/* recent activity */}
      <div className="card" style={{ padding: 18 }}>
        <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Recent activity</h3>
        {recent.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>No activity yet.</div>}
        {recent.map((a) => (
          <div key={a.id} style={{ fontSize: 12.5, padding: "7px 0", borderTop: "1px solid var(--border)" }}>
            {a.title}<div style={{ color: "var(--muted2)", fontSize: 11 }}>{timeAgo(a.at)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Fact({ k, v, children }) {
  return (
    <div><div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted2)", fontWeight: 700 }}>{k}</div>
      <div style={{ marginTop: 3, fontSize: 13.5 }}>{children ?? v}</div></div>
  );
}

// ---------------------------------------------------------------- doc lists
function DocTab({ endpoint, params, to, empty, nav, label }) {
  const { data, loading } = useApi(endpoint, params);
  if (loading) return <Spinner />;
  const rows = data || [];
  return (
    <div className="card" style={{ padding: 0 }}>
      {rows.length === 0 && <div className="rc-empty" style={{ padding: 24 }}>{empty}</div>}
      {rows.map((x, i) => (
        <div key={x.id} className="click" onClick={() => nav(`/${to}/${x.id}`)}
          style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", borderTop: i ? "1px solid var(--border)" : "none" }}>
          <div style={{ flex: 1, fontSize: 13.5, fontWeight: 600 }}>{label(x)}</div>
          <span style={{ color: "var(--muted)" }}>→</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Tasks
function TasksTab({ dealId }) {
  const toast = useToast();
  const { data, loading, reload } = useApi(`/api/deals/${dealId}/tasks`);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const add = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try { await api(`/api/deals/${dealId}/tasks`, { method: "POST", body: { title } }); setTitle(""); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const toggle = async (t) => { try { await api(`/api/deals/${dealId}/tasks/${t.id}`, { method: "PATCH", body: { done: !t.done } }); reload(); } catch (e) { toast(e.message, "bad"); } };
  const del = async (t) => { try { await api(`/api/deals/${dealId}/tasks/${t.id}`, { method: "DELETE" }); reload(); } catch (e) { toast(e.message, "bad"); } };
  if (loading) return <Spinner />;
  const rows = data || [];
  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder="Add a task…" style={{ flex: 1 }} />
        <Button icon={Plus} loading={busy} onClick={add}>Add</Button>
      </div>
      {rows.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>No tasks yet.</div>}
      {rows.map((t) => (
        <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: "1px solid var(--border)" }}>
          <button className="iconbtn" style={{ width: 26, height: 26, border: t.done ? "none" : "1px solid var(--border)", background: t.done ? "var(--ok,#12b76a)" : "#fff", color: "#fff" }} onClick={() => toggle(t)}>
            {t.done && <Check size={14} />}</button>
          <span style={{ flex: 1, fontSize: 13.5, textDecoration: t.done ? "line-through" : "none", color: t.done ? "var(--muted)" : "var(--ink)" }}>{t.title}</span>
          {t.due_at && <span style={{ fontSize: 12, color: "var(--muted2)" }}>{new Date(t.due_at + "Z").toLocaleDateString()}</span>}
          <button className="iconbtn" style={{ width: 26, height: 26 }} onClick={() => del(t)}><Trash2 size={14} /></button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Files
function FilesTab({ deal }) {
  const { data: ags } = useApi("/api/agreements", { deal_id: deal.id });
  const { data: invs } = useApi(deal.company?.id ? "/api/invoices" : null, { company_id: deal.company?.id });
  const { data: bps } = useApi(deal.company?.id ? "/api/documents" : null, { company_id: deal.company?.id });
  const rows = [
    ...(bps || []).map((x) => ({ id: `b${x.id}`, icon: FileText, label: x.title || x.slug, sub: "Blueprint", href: x.public_path ? `${window.location.origin}${x.public_path}` : null })),
    ...(ags || []).map((x) => ({ id: `a${x.id}`, icon: FileSignature, label: `${x.number} — ${x.title || "Agreement"}`, sub: x.status,
      dl: x.executed_at ? `/api/agreements/${x.id}/pdf?mode=executed` : `/api/agreements/${x.id}/pdf?mode=draft` })),
    ...(invs || []).map((x) => ({ id: `i${x.id}`, icon: Receipt, label: `${x.number}`, sub: `${x.currency} ${(x.total || 0).toLocaleString()} · ${x.status}`, dl: `/api/invoices/${x.id}/pdf` })),
  ];
  return (
    <div className="card" style={{ padding: 0 }}>
      {rows.length === 0 && <div className="rc-empty" style={{ padding: 24 }}>No files yet. Blueprints, agreements and invoices for this deal appear here.</div>}
      {rows.map((r, i) => (
        <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderTop: i ? "1px solid var(--border)" : "none" }}>
          <r.icon size={18} style={{ color: "var(--muted)" }} />
          <div style={{ flex: 1 }}><div style={{ fontWeight: 600, fontSize: 13.5 }}>{r.label}</div>
            <div style={{ fontSize: 11.5, color: "var(--muted)" }}>{r.sub}</div></div>
          {r.dl && <Button size="sm" variant="secondary" icon={Download} onClick={() => download(r.dl)}>PDF</Button>}
          {r.href && <a className="btn ghost sm" href={r.href} target="_blank" rel="noreferrer">Open ↗</a>}
        </div>
      ))}
      <div style={{ padding: "10px 16px", fontSize: 11.5, color: "var(--muted2)", borderTop: "1px solid var(--border)" }}>
        Email attachments will appear here once mailbox sync captures them.</div>
    </div>
  );
}

// ---------------------------------------------------------------- Notes
function NotesTab({ dealId }) {
  const toast = useToast();
  const { data, loading, reload } = useApi(`/api/deals/${dealId}/notes`);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const add = async () => {
    if (!body.trim()) return;
    setBusy(true);
    try { await api(`/api/deals/${dealId}/notes`, { method: "POST", body: { body } }); setBody(""); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  if (loading) return <Spinner />;
  const rows = data || [];
  return (
    <div className="card" style={{ padding: 18 }}>
      <div style={{ marginBottom: 14 }}>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Internal note (not shared with the client)…" style={{ width: "100%", minHeight: 70 }} />
        <div style={{ marginTop: 8 }}><Button icon={Plus} loading={busy} onClick={add}>Add note</Button></div>
      </div>
      {rows.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>No notes yet.</div>}
      {rows.map((n) => (
        <div key={n.id} style={{ padding: "10px 0", borderTop: "1px solid var(--border)" }}>
          <div style={{ fontSize: 13.5, whiteSpace: "pre-wrap" }}>{n.body}</div>
          <div style={{ fontSize: 11, color: "var(--muted2)", marginTop: 3 }}>{timeAgo(n.created_at)}</div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- Conversation
function ConversationTab({ dealId, deal, contact, setTab }) {
  const toast = useToast();
  const { data, loading, error, reload, refresh } = useApi(`/api/deals/${dealId}/conversation`);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
  const [plan, setPlan] = useState(null);   // follow-up plan modal state (hook must be before any early return)
  const [focus, setFocus] = useState(false); // full-width focus mode (context panel collapsed)
  // Live-ish: quietly re-sync the thread every 15s while the conversation is open.
  // refresh() updates in place (no spinner) so the view never blanks while you read.
  useEffect(() => {
    const t = setInterval(() => refresh(), 15000);
    return () => clearInterval(t);
  }, [refresh]);
  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  const msgs = data?.messages || [];
  const connected = data?.mailbox_connected;
  const aiDraft = async () => {
    setBusy("draft");
    try { const r = await api(`/api/deals/${dealId}/conversation/draft`, { method: "POST" }); setDraft(r.body); toast("AI drafted a reply — review and send"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const send = async () => {
    if (!draft.trim()) { toast("Write or draft a message first", "bad"); return; }
    setBusy("send");
    try { await api(`/api/deals/${dealId}/conversation/send`, { method: "POST", body: { body: draft } }); setDraft(""); await refresh(); toast("Sent in the same thread"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const syncNow = async () => { setBusy("sync"); await refresh(); setBusy(""); toast("Synced with the mailbox"); };
  const conv = data?.conversation || {};
  const lastInbound = [...msgs].reverse().find((m) => m.direction === "in");
  const toggleAutopilot = async () => {
    setBusy("auto");
    try {
      await api(`/api/deals/${dealId}/conversation/autopilot`, { method: "POST", body: { enabled: !conv.autopilot } });
      await refresh();
      toast(conv.autopilot ? "Follow-ups off" : "Follow-ups on");
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const openPlan = async () => {
    try {
      const r = await api(`/api/deals/${dealId}/conversation/followup-plan`);
      setPlan({ guidance: r.guidance || "", steps: r.plan?.length || 3,
        interval: conv.followup_interval_days || 4, items: r.plan || [] });
    } catch { setPlan({ guidance: "", steps: 3, interval: conv.followup_interval_days || 4, items: [] }); }
  };
  const previewPlan = async () => {
    setBusy("preview");
    try { const r = await api(`/api/deals/${dealId}/conversation/followup-plan/preview`, { method: "POST",
        body: { guidance: plan.guidance, steps: Number(plan.steps) || 3, interval_days: Number(plan.interval) || 4 } });
      setPlan((p) => ({ ...p, items: r.plan || [] })); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const savePlan = async (enabled) => {
    setBusy("saveplan");
    try { await api(`/api/deals/${dealId}/conversation/followup-plan`, { method: "PUT",
        body: { guidance: plan.guidance, enabled, plan: plan.items } });
      setPlan(null); await refresh(); toast(enabled ? "Follow-up sequence scheduled" : "Plan saved"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  return (
    <div className={`conv-workspace ${focus ? "focus" : ""}`}>
      <main className="conv-main">
        <div className="conv-toolbar">
          <div className="ct-who">
            <Avatar name={contact?.name || contact?.email || "?"} size={32} />
            <div style={{ minWidth: 0 }}>
              <div className="ct-name">{contact?.name || contact?.email || "Prospect"}</div>
              <div className="ct-sub">
                {contact?.email || "no email on file"}
                {lastInbound && <> · last reply {timeAgo(lastInbound.sent_at || lastInbound.created_at)}</>}
              </div>
            </div>
          </div>
          <div className="ct-actions">
            <span className={`ct-status ${connected ? "ok" : "off"}`}><span className="dot" />{connected ? "Live thread" : "Not connected"}</span>
            <Button size="sm" variant="ghost" icon={RefreshCw} loading={busy === "sync"} disabled={!!busy} onClick={syncNow}>Sync</Button>
            {focus && <Button size="sm" variant="secondary" onClick={() => setFocus(false)}>Show details</Button>}
          </div>
        </div>

        {!connected && (
          <div className="conv-banner warn">
            <Mail size={16} />
            <span style={{ flex: 1 }}>Connect a mailbox to send from your own address, in the same thread.</span>
            <Link className="btn sm" to="/settings/email">Connect email</Link>
          </div>
        )}
        {connected && (
          <div className={`conv-banner followup ${conv.autopilot ? "on" : ""}`}>
            <Sparkles size={16} style={{ color: conv.autopilot ? "var(--primary)" : "var(--muted)", flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <b style={{ fontSize: 12.5 }}>Follow-up autopilot {conv.autopilot ? "· Active" : "· Off"}</b>
              <span className="fu-sub">
                {conv.autopilot
                  ? ` Next ${conv.next_followup_at ? new Date(conv.next_followup_at).toLocaleDateString() : "when due"} · ${conv.followups_sent}/${conv.max_followups} sent · stops when they reply`
                  : " Preview and edit each email, set timing, then turn it on. Stops when they reply."}
              </span>
            </div>
            <Button size="sm" variant="secondary" disabled={!!busy} onClick={openPlan}>{conv.autopilot ? "Edit plan" : "Set up follow-ups"}</Button>
            {conv.autopilot && <Button size="sm" variant="ghost" loading={busy === "auto"} disabled={!!busy} onClick={toggleAutopilot}>Turn off</Button>}
          </div>
        )}

        <div className="ib-msgs conv-stream" role="log" aria-label="Conversation messages" aria-live="polite">
          {msgs.length === 0 && <div className="rc-empty" style={{ padding: 24 }}>No messages yet. Start the conversation below — it stays in one email thread until the deal is won or lost.</div>}
          {msgs.map((m) => <MessageBubble key={m.id} m={m} contact={contact} />)}
        </div>

        <div className="ib-compose conv-composer">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Reply message"
            placeholder={connected ? "Reply in the same thread…" : "Connect a mailbox to send…"} />
          <div className="row">
            <Button icon={Send} loading={busy === "send"} disabled={!connected || !!busy} onClick={send}>Send in thread</Button>
            <Button variant="secondary" icon={Sparkles} loading={busy === "draft"} disabled={!!busy} onClick={aiDraft}>AI draft</Button>
            <span style={{ flex: 1 }} />
            <Button variant="ghost" icon={RefreshCw} loading={busy === "sync"} disabled={!!busy} onClick={syncNow}>Sync replies</Button>
          </div>
        </div>
      </main>

      {!focus && <LeadContextPanel deal={deal} conv={conv} contact={contact} setTab={setTab} onCollapse={() => setFocus(true)} />}

      {plan && (
        <Modal title="Follow-up sequence" onClose={() => setPlan(null)}>
          <div className="field"><label>What should the follow-ups say?</label>
            <textarea rows={3} value={plan.guidance}
              placeholder="e.g. Reference the Revenue Blueprint, keep it warm and brief, and by the last one ask for a quick call."
              onChange={(e) => setPlan({ ...plan, guidance: e.target.value })} /></div>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <div className="field" style={{ margin: 0 }}><label>How many</label>
              <input type="number" min="1" max="8" value={plan.steps} style={{ width: 80 }}
                onChange={(e) => setPlan({ ...plan, steps: e.target.value })} /></div>
            <div className="field" style={{ margin: 0 }}><label>Days between (default)</label>
              <input type="number" min="1" max="60" value={plan.interval} style={{ width: 110 }}
                onChange={(e) => setPlan({ ...plan, interval: e.target.value })} /></div>
            <Button variant="secondary" loading={busy === "preview"} onClick={previewPlan}>
              {plan.items.length ? "Regenerate" : "Preview emails"}</Button>
          </div>

          {plan.items.length > 0 && (
            <div style={{ display: "grid", gap: 10, marginTop: 12, maxHeight: "44vh", overflow: "auto" }}>
              {plan.items.map((it, i) => (
                <div key={i} className="card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <b style={{ fontSize: 12.5 }}>Follow-up {i + 1}</b>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>sends</span>
                    <input type="number" min="0" max="60" value={it.days} style={{ width: 62, padding: "4px 6px" }}
                      onChange={(e) => { const items = [...plan.items]; items[i] = { ...it, days: Number(e.target.value) || 0 }; setPlan({ ...plan, items }); }} />
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>days after the previous email</span>
                  </div>
                  <textarea rows={5} value={it.body} style={{ width: "100%" }}
                    onChange={(e) => { const items = [...plan.items]; items[i] = { ...it, body: e.target.value }; setPlan({ ...plan, items }); }} />
                </div>
              ))}
            </div>
          )}

          <div className="actions" style={{ marginTop: 14 }}>
            <button className="btn ghost" onClick={() => setPlan(null)}>Cancel</button>
            {plan.items.length > 0 && <button className="btn ghost" disabled={busy === "saveplan"} onClick={() => savePlan(false)}>Save (don't send yet)</button>}
            <Button loading={busy === "saveplan"} disabled={!plan.items.length} onClick={() => savePlan(true)}>Save &amp; turn on</Button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// Persistent right-side lead context. Collapses to full-width focus mode.
function LeadContextPanel({ deal, conv, contact, setTab, onCollapse }) {
  const co = deal?.company;
  const Row = ({ k, v }) => (v ? (
    <div className="lcp-row"><span className="lcp-k">{k}</span><span className="lcp-v">{v}</span></div>
  ) : null);
  const related = [
    ["tasks", "Tasks"], ["files", "Files"], ["blueprint", "Blueprint"],
    ["agreement", "Agreement"], ["invoice", "Invoice"],
  ];
  return (
    <aside className="conv-context" aria-label="Lead context">
      <div className="lcp-head">
        <b>Lead context</b>
        <button className="iconbtn" aria-label="Collapse panel (focus mode)" title="Focus mode" onClick={onCollapse}><PanelRightClose size={16} /></button>
      </div>
      <div className="lcp-sec">
        <div className="lcp-title">Contact</div>
        <Row k="Name" v={contact?.name} />
        <Row k="Email" v={contact?.email} />
        <Row k="Role" v={contact?.title} />
        <Row k="Phone" v={contact?.phone} />
      </div>
      <div className="lcp-sec">
        <div className="lcp-title">Company</div>
        {co ? <Row k="Name" v={<Link to={`/companies/${co.id}`}>{co.name}</Link>} /> : <div className="lcp-empty">Not linked</div>}
        <Row k="Website" v={co?.website} />
        <Row k="Industry" v={co?.industry} />
      </div>
      <div className="lcp-sec">
        <div className="lcp-title">Deal</div>
        <Row k="Stage" v={deal?.stage?.name} />
        <Row k="Value" v={money(deal?.value)} />
        <Row k="Intent" v={deal?.lead_intent} />
        <Row k="Close date" v={deal?.close_date} />
      </div>
      <div className="lcp-sec">
        <div className="lcp-title">Activity</div>
        <Row k="Next follow-up" v={conv?.next_followup_at ? new Date(conv.next_followup_at).toLocaleDateString() : "None"} />
        <Row k="Autopilot" v={conv?.autopilot ? "Active" : "Off"} />
      </div>
      <div className="lcp-sec">
        <div className="lcp-title">Related items</div>
        <div className="lcp-related">
          {related.map(([key, label]) => (
            <button key={key} className="lcp-link" onClick={() => setTab(key)}>{label} →</button>
          ))}
        </div>
      </div>
    </aside>
  );
}
