// Deal Record (ROADMAP_V1 T14) — the deal is a real record with tabs. The
// Conversation tab is same-thread relationship management: an AI briefing on top,
// the email thread, and a composer that sends through the connected mailbox in the
// SAME thread. AI can draft the next reply; the human always approves.
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Send, Sparkles, RefreshCw, Mail, ExternalLink } from "lucide-react";
import { api, money, timeAgo } from "../api";
import {
  Avatar, Badge, Breadcrumbs, Button, ErrorBox, Spinner, StatusPill, Tabs, Timeline,
  useApi, useToast,
} from "../components";

const TABS = [
  { key: "conversation", label: "Conversation" },
  { key: "timeline", label: "Timeline" },
  { key: "blueprint", label: "Blueprint" },
  { key: "agreement", label: "Agreement" },
  { key: "invoice", label: "Invoice" },
];
const RISK_TONE = { low: "green", medium: "amber", high: "red", unknown: "gray" };
const INTENT_TONE = { high: "green", medium: "amber", low: "gray" };

export default function DealRecord() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: d, error, loading } = useApi(`/api/deals/${id}`);
  const [tab, setTab] = useState("conversation");

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
            {d.contact && <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{d.contact.name} · {d.contact.email}</span>}
          </p>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <Tabs value={tab} onChange={setTab} tabs={TABS} />
      </div>

      {tab === "conversation" && <ConversationTab dealId={id} contact={d.contact} />}
      {tab === "timeline" && (
        <div className="card" style={{ padding: 18 }}><Timeline items={d.timeline || []} /></div>
      )}
      {tab === "blueprint" && <DocTab title="Blueprints" empty="No blueprint yet." to="blueprints"
        endpoint="/api/documents" params={{ company_id: d.company?.id }} nav={nav} label={(x) => x.title || x.slug} />}
      {tab === "agreement" && <DocTab title="Agreements" empty="No agreement yet." to="agreements"
        endpoint="/api/agreements" params={{ deal_id: id }} nav={nav} label={(x) => `${x.number} · ${x.status}`} />}
      {tab === "invoice" && <DocTab title="Invoices" empty="No invoice yet." to="invoices"
        endpoint="/api/invoices" params={{ company_id: d.company?.id }} nav={nav} label={(x) => `${x.number} · ${x.currency} ${(x.total || 0).toLocaleString()}`} />}
    </div>
  );
}

function DocTab({ title, empty, endpoint, params, to, nav, label }) {
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

function ConversationTab({ dealId, contact }) {
  const toast = useToast();
  const { data, loading, error, reload } = useApi(`/api/deals/${dealId}/conversation`);
  const { data: brief, reload: reloadBrief } = useApi(`/api/deals/${dealId}/conversation/briefing`);
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
    try { await api(`/api/deals/${dealId}/conversation/send`, { method: "POST", body: { body: draft } }); setDraft(""); reload(); reloadBrief(); toast("Sent in the same thread"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {/* persistent AI briefing */}
      {brief && (
        <div className="card" style={{ padding: 16, background: "linear-gradient(180deg,#fbfbff,#fff)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <Sparkles size={15} style={{ color: "var(--accent,#635BFF)" }} />
            <b style={{ fontSize: 13 }}>Deal briefing</b>
            <span style={{ flex: 1 }} />
            <Button size="sm" variant="ghost" icon={RefreshCw} onClick={reloadBrief}>Refresh</Button>
          </div>
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap", fontSize: 13, marginBottom: 10 }}>
            <Brief k="Stage" v={brief.stage} />
            <Brief k="Last contact" v={brief.last_contact_days == null ? "—" : `${brief.last_contact_days}d ago`} />
            <Brief k="Intent"><Badge tone={INTENT_TONE[brief.intent] || "gray"}>{brief.intent}</Badge></Brief>
            <Brief k="Risk"><Badge tone={RISK_TONE[brief.risk] || "gray"}>{brief.risk}</Badge></Brief>
            <Brief k="Proposal viewed" v={brief.blueprint_viewed ? "Yes" : (brief.blueprint ? "No" : "—")} />
            <Brief k="Agreement" v={brief.agreement_status || "None"} />
            <Brief k="Invoice" v={brief.invoice_status || "None"} />
            {brief.ghost && <Brief k="Status"><Badge tone="red">Ghost</Badge></Brief>}
          </div>
          <div style={{ fontSize: 13, color: "var(--ink,#12131a)", marginBottom: 4 }}>
            <b>Recommendation:</b> {brief.recommendation}</div>
          <div style={{ fontSize: 13, color: "var(--muted)" }}><b>Suggested next action:</b> {brief.next_action}</div>
        </div>
      )}

      {!connected && (
        <div className="card" style={{ padding: 16, display: "flex", alignItems: "center", gap: 12, background: "#FFFAEB", borderColor: "#FEDF89" }}>
          <Mail size={18} style={{ color: "#B54708" }} />
          <div style={{ flex: 1, fontSize: 13, color: "#B54708" }}>
            Connect a mailbox to send from your own address, in the same thread.</div>
          <Link className="btn" to="/settings/email">Connect email</Link>
        </div>
      )}

      {/* the thread */}
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
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)}
            placeholder={connected ? "Reply in the same thread…" : "Connect a mailbox to send…"} />
          <div className="row">
            <Button icon={Send} loading={busy === "send"} disabled={!connected || !!busy} onClick={send}>Send in thread</Button>
            <Button variant="secondary" icon={Sparkles} loading={busy === "draft"} disabled={!!busy} onClick={aiDraft}>AI draft</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Brief({ k, v, children }) {
  return (
    <div><div style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted2)", fontWeight: 700 }}>{k}</div>
      <div style={{ marginTop: 2 }}>{children ?? v}</div></div>
  );
}
