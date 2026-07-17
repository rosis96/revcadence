// CRM → Revenue Inbox. Email threads where your connected mailbox was a
// participant WITH a lead we already know, not yet tied to a deal. Attach each to
// the right deal with one click — it becomes that deal's Conversation.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Mail, Check, X, ArrowRight, RefreshCw } from "lucide-react";
import { api, timeAgo } from "../api";
import { useAuth } from "../auth";
import { Avatar, Badge, Button, Empty, ErrorBox, PageHeader, Spinner, useApi, useToast } from "../components";

export default function RevenueInbox() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const { data, loading, error, reload } = useApi("/api/revenue-inbox", { workspace_id: wsParam });
  const [busy, setBusy] = useState(0);
  const [pick, setPick] = useState({});   // itemId -> chosen deal_id

  const attach = async (item) => {
    const dealId = pick[item.id] || item.deals[0]?.id;
    if (!dealId) { toast("Pick a deal to attach to (or create one on the contact)", "bad"); return; }
    setBusy(item.id);
    try { const r = await api(`/api/revenue-inbox/${item.id}/attach`, { method: "POST", body: { deal_id: Number(dealId) } });
      toast("Attached to the deal conversation"); reload();
      nav(`/deals/${r.deal_id}`);
    } catch (e) { toast(e.message, "bad"); }
    setBusy(0);
  };
  const dismiss = async (item) => {
    setBusy(item.id);
    try { await api(`/api/revenue-inbox/${item.id}/dismiss`, { method: "POST" }); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(0);
  };

  return (
    <>
      <PageHeader title="Revenue Inbox"
        desc="Threads where your mailbox was CC'd (or on the thread) with a lead we already know. Attach each to its deal — the conversation continues in the same thread."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={reload}>Refresh</Button>} />

      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && (
        <Empty icon={<Mail size={26} />} title="Nothing waiting"
          hint="When your connected mailbox is on an email thread with a known contact, it shows up here to attach to a deal." />
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {(data || []).map((it) => (
          <div key={it.id} className="card" style={{ padding: 16 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
              <Avatar name={it.contact?.name || it.from_email} size={34} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <b style={{ fontSize: 14 }}>{it.subject || "(no subject)"}</b>
                  {it.contact && <Badge tone="green">known: {it.contact.name || it.contact.email}</Badge>}
                  {it.company && <Badge>{it.company.name}</Badge>}
                  <span style={{ color: "var(--muted)", fontSize: 12 }}>{timeAgo(it.created_at)}</span>
                </div>
                <div style={{ color: "var(--muted)", fontSize: 12.5, margin: "2px 0 6px" }}>
                  from {it.from_email} · {(it.participants || []).length} on thread</div>
                <div style={{ fontSize: 13, whiteSpace: "pre-wrap", color: "var(--ink,#12131a)" }}>{it.preview}</div>

                <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12, flexWrap: "wrap" }}>
                  {it.deals.length > 0 ? (
                    <>
                      <select value={pick[it.id] || it.deals[0].id} onChange={(e) => setPick({ ...pick, [it.id]: e.target.value })}
                        style={{ padding: "7px 10px", borderRadius: 8, fontSize: 13 }}>
                        {it.deals.map((dd) => <option key={dd.id} value={dd.id}>{dd.name || `Deal #${dd.id}`}</option>)}
                      </select>
                      <Button icon={ArrowRight} loading={busy === it.id} onClick={() => attach(it)}>Attach to deal</Button>
                    </>
                  ) : (
                    <>
                      <span style={{ fontSize: 12.5, color: "var(--muted)" }}>No deal for this contact yet —</span>
                      {it.contact && <Button variant="secondary" onClick={() => nav(`/companies/${it.company?.id || ""}`)}>Open contact/company</Button>}
                    </>
                  )}
                  <span style={{ flex: 1 }} />
                  <Button variant="ghost" icon={X} disabled={busy === it.id} onClick={() => dismiss(it)}>Dismiss</Button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
