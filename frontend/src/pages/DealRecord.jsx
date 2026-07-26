// Deal Workspace — the center of RevCadence. A deal card opens this full page.
// Tabs: Overview (dashboard) · Conversation (same-thread) · Timeline · Blueprint ·
// Agreement · Invoice · Tasks · Files · Notes. Overview answers "what's happening
// with this deal right now?" without opening another tab.
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Send, Sparkles, RefreshCw, Mail, Plus, Check, Trash2, Download, FileText, FileSignature, Receipt } from "lucide-react";
import { api, download, money, timeAgo } from "../api";
import {
  Avatar, Badge, Breadcrumbs, Button, ErrorBox, Spinner, StatusPill, Tabs, Timeline,
  useApi, useToast,
} from "../components";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "conversation", label: "Conversation" },
  { key: "timeline", label: "Timeline" },
  { key: "blueprint", label: "Blueprint" },
  { key: "agreement", label: "Agreement" },
  { key: "invoice", label: "Invoice" },
  { key: "tasks", label: "Tasks" },
  { key: "files", label: "Files" },
  { key: "notes", label: "Notes" },
];
const HEALTH_TONE = { healthy: "green", cooling: "amber", ghosted: "red", unknown: "gray" };
const RISK_TONE = { low: "green", medium: "amber", high: "red", unknown: "gray" };
const INTENT_TONE = { high: "green", medium: "amber", low: "gray" };

export default function DealRecord() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: d, error, loading } = useApi(`/api/deals/${id}`);
  const [tab, setTab] = useState("overview");

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} />;
  if (!d) return <Spinner />;

  return (
    <div style={{ maxWidth: 1100 }}>
      <Breadcrumbs items={[{ label: "Pipeline", href: "/pipeline" }, { label: d.name || "Deal" }]} />
      <div className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ fontSize: 22, fontWeight: 650 }}>{d.name || "Untitled deal"}</h1>
          <p style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {d.stage && <StatusPill tone="blue">{d.stage.name}</StatusPill>}
            <span style={{ fontWeight: 700 }}>{money(d.value)}</span>
            {d.company && <Link to={`/companies/${d.company.id}`} style={{ fontSize: 12.5 }}>{d.company.name} →</Link>}
          </p>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}><Tabs value={tab} onChange={setTab} tabs={TABS} /></div>

      {tab === "overview" && <OverviewTab dealId={id} deal={d} nav={nav} setTab={setTab} />}
      {tab === "conversation" && <ConversationTab dealId={id} contact={d.contact} />}
      {tab === "timeline" && <div className="card" style={{ padding: 18 }}><Timeline items={d.timeline || []} /></div>}
      {tab === "blueprint" && <DocTab endpoint="/api/documents" params={{ company_id: d.company?.id }} to="blueprints"
        empty="No blueprint yet." nav={nav} label={(x) => x.title || x.slug} />}
      {tab === "agreement" && <DocTab endpoint="/api/agreements" params={{ deal_id: id }} to="agreements"
        empty="No agreement yet." nav={nav} label={(x) => `${x.number} · ${x.status}`} />}
      {tab === "invoice" && <DocTab endpoint="/api/invoices" params={{ company_id: d.company?.id }} to="invoices"
        empty="No invoice yet." nav={nav} label={(x) => `${x.number} · ${x.currency} ${(x.total || 0).toLocaleString()}`} />}
      {tab === "tasks" && <TasksTab dealId={id} />}
      {tab === "files" && <FilesTab deal={d} />}
      {tab === "notes" && <NotesTab dealId={id} />}
    </div>
  );
}

// ---------------------------------------------------------------- Overview
function OverviewTab({ dealId, deal, nav, setTab }) {
  const { data: b, loading } = useApi(`/api/deals/${dealId}/conversation/briefing`);
  if (loading || !b) return <Spinner />;
  const recent = (deal.timeline || []).slice(0, 6);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.4fr .9fr", gap: 14, alignItems: "start" }}>
      <div style={{ display: "grid", gap: 14 }}>
        {/* AI briefing */}
        <div className="card" style={{ padding: 18, background: "linear-gradient(180deg,#f6f5ff,#fff)", borderColor: "#e3e1ff" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <Sparkles size={16} style={{ color: "var(--accent,#635BFF)" }} />
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
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
  const { data: invs } = useApi("/api/invoices", { company_id: deal.company?.id });
  const { data: bps } = useApi("/api/documents", { company_id: deal.company?.id });
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
function ConversationTab({ dealId, contact }) {
  const toast = useToast();
  const { data, loading, error, reload } = useApi(`/api/deals/${dealId}/conversation`);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState("");
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
    try { await api(`/api/deals/${dealId}/conversation/send`, { method: "POST", body: { body: draft } }); setDraft(""); reload(); toast("Sent in the same thread"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const conv = data?.conversation || {};
  const toggleAutopilot = async () => {
    setBusy("auto");
    try {
      await api(`/api/deals/${dealId}/conversation/autopilot`, { method: "POST", body: { enabled: !conv.autopilot } });
      reload();
      toast(conv.autopilot ? "Autopilot off" : "Autopilot on — AI follows up until they reply");
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  return (
    <div style={{ display: "grid", gap: 14 }}>
      {!connected && (
        <div className="card" style={{ padding: 16, display: "flex", alignItems: "center", gap: 12, background: "#FFFAEB", borderColor: "#FEDF89" }}>
          <Mail size={18} style={{ color: "#B54708" }} />
          <div style={{ flex: 1, fontSize: 13, color: "#B54708" }}>Connect a mailbox to send from your own address, in the same thread.</div>
          <Link className="btn" to="/settings/email">Connect email</Link>
        </div>
      )}
      {connected && (
        <div className="card" style={{ padding: 14, display: "flex", alignItems: "center", gap: 12,
          justifyContent: "space-between", background: conv.autopilot ? "#f0f7ff" : "transparent",
          borderColor: conv.autopilot ? "#bfdcf6" : undefined }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Sparkles size={18} style={{ color: conv.autopilot ? "#1f8fe6" : "var(--muted)" }} />
            <div style={{ fontSize: 13 }}>
              <div style={{ fontWeight: 600 }}>Follow-up autopilot {conv.autopilot ? "· ON" : "· off"}</div>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>
                {conv.autopilot
                  ? `AI sends the next follow-up ${conv.next_followup_at ? "on " + new Date(conv.next_followup_at).toLocaleDateString() : "when due"} · ${conv.followups_sent}/${conv.max_followups} sent · stops the moment they reply`
                  : `Send AI follow-ups automatically every ${conv.followup_interval_days} days until they reply (max ${conv.max_followups}). Grounded in this thread + the client brain.`}
              </div>
            </div>
          </div>
          <Button size="sm" variant={conv.autopilot ? "secondary" : undefined} loading={busy === "auto"}
            disabled={!!busy} onClick={toggleAutopilot}>{conv.autopilot ? "Turn off" : "Turn on"}</Button>
        </div>
      )}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="ib-msgs" style={{ maxHeight: "48vh" }}>
          {msgs.length === 0 && <div className="rc-empty" style={{ padding: 24 }}>No messages yet. Start the conversation below — it stays in one email thread until the deal is won or lost.</div>}
          {msgs.map((m) => (
            <div key={m.id} className={`msg ${m.direction === "in" ? "in" : "out"}`}>
              <div className="who">{m.direction === "in" ? (contact?.name || "Prospect") : "You"}{m.ai_generated ? " · AI" : ""}{m.status === "cancelled" ? " · cancelled" : ""}</div>
              <div style={{ whiteSpace: "pre-wrap" }}>{m.body_text}</div>
              <div style={{ fontSize: 10.5, color: "var(--muted2)", marginTop: 4 }}>{timeAgo(m.sent_at || m.created_at)}</div>
            </div>
          ))}
        </div>
        <div className="ib-compose">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={connected ? "Reply in the same thread…" : "Connect a mailbox to send…"} />
          <div className="row">
            <Button icon={Send} loading={busy === "send"} disabled={!connected || !!busy} onClick={send}>Send in thread</Button>
            <Button variant="secondary" icon={Sparkles} loading={busy === "draft"} disabled={!!busy} onClick={aiDraft}>AI draft</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
