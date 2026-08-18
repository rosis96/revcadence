// CRM → Revenue Inbox. Email threads where your connected mailbox was a
// participant WITH a lead we already know, not yet tied to a deal. Attach each to
// the right deal with one click — it becomes that deal's Conversation.
import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Mail, X, ArrowRight, RefreshCw, Download, Inbox as InboxIcon, ChevronDown } from "lucide-react";
import { api, emailText, localDateTime, splitQuoted, timeAgo } from "../api";
import { useAuth } from "../auth";
import { useAppPath } from "../clientspace/appPath";
import { Avatar, Badge, Button, Empty, ErrorBox, Modal, PageHeader, Spinner, useApi, useToast } from "../components";
import { Select } from "../components";

function ThreadMsg({ mm, name, last }) {
  const [open, setOpen] = useState(false);
  const { main, quoted } = splitQuoted(emailText(mm.text));
  return (
    <div style={{ padding: "10px 0", borderBottom: last ? "none" : "1px solid var(--border)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--muted)", marginBottom: 3 }}>
        <b style={{ color: mm.direction === "out" ? "var(--primary)" : "var(--text)" }}>
          {mm.direction === "out" ? "You" : (name || mm.from_email || "Them")}</b>
        <span>{localDateTime(mm.at)}</span>
      </div>
      <div style={{ fontSize: 13, whiteSpace: "pre-wrap", color: "var(--text)" }}>{main}</div>
      {quoted && (
        <div style={{ marginTop: 5 }}>
          <button className="quote-toggle" onClick={() => setOpen(!open)}>{open ? "Hide quoted text" : "•••  Show quoted text"}</button>
          {open && <div className="quoted-block">{quoted}</div>}
        </div>
      )}
    </div>
  );
}

export default function RevenueInbox() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const appTo = useAppPath();
  const { data, loading, error, reload } = useApi("/api/revenue-inbox", { workspace_id: wsParam });
  const [busy, setBusy] = useState(0);
  const [pick, setPick] = useState({});   // itemId -> chosen deal_id
  const [expanded, setExpanded] = useState({});   // itemId -> thread open
  const [syncing, setSyncing] = useState(false);
  const [browse, setBrowse] = useState(null);   // { items, workspace_id } when the import modal is open
  const [browseLoading, setBrowseLoading] = useState(false);
  const [sel, setSel] = useState({});           // rfc_message_id -> thread object
  const [labels, setLabels] = useState([]);
  const [filterLabel, setFilterLabel] = useState("");
  const [filterQ, setFilterQ] = useState("");

  const syncNow = async () => {
    if (!wsParam) { toast("Pick a specific workspace first (top bar)", "bad"); return; }
    setSyncing(true);
    try { const r = await api("/api/mailbox/sync", { method: "POST", params: { workspace_id: wsParam } });
      toast(`Synced — ${r.matched || 0} matched, ${r.candidates || 0} surfaced`); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setSyncing(false);
  };
  const fetchThreads = async (label = filterLabel, q = filterQ) => {
    setBrowseLoading(true);
    try { const r = await api("/api/mailbox/threads", { params: { workspace_id: wsParam, days: 90, limit: 100, label, q } });
      setBrowse(r); }
    catch (e) { toast(e.message, "bad"); }
    setBrowseLoading(false);
  };
  const openBrowse = async () => {
    setSel({}); setFilterLabel(""); setFilterQ("");
    setBrowse({ items: [], mailbox: "" });    // open the modal immediately
    fetchThreads("", "");
    try {
      const r = await api("/api/mailbox/labels", { params: { workspace_id: wsParam } });
      setLabels(r.labels || []);
      if ((!r.labels || !r.labels.length) && r.error) toast(`Labels unavailable: ${r.error}`, "bad");
    } catch (e) { toast(`Labels: ${e.message}`, "bad"); }
  };
  const doImport = async (items) => {
    if (!items.length) { toast("Nothing to import", "bad"); return; }
    const wid = browse?.workspace_id || wsParam;
    if (!wid) { toast("No workspace/mailbox found", "bad"); return; }
    try { const r = await api("/api/mailbox/threads/import", { method: "POST", body: { workspace_id: Number(wid), items } });
      toast(`Imported ${r.imported} conversation(s)`); setBrowse(null); reload(); }
    catch (e) { toast(e.message, "bad"); }
  };
  const importSelected = () => doImport(Object.values(sel));
  const importAll = () => doImport((browse?.items || []).filter((t) => !t.already));

  const attach = async (item) => {
    const dealId = pick[item.id] || item.deals[0]?.id;
    if (!dealId) { toast("Pick a deal to attach to (or create one on the contact)", "bad"); return; }
    setBusy(item.id);
    try { const r = await api(`/api/revenue-inbox/${item.id}/attach`, { method: "POST", body: { deal_id: Number(dealId) } });
      toast("Attached to the deal conversation"); reload();
      nav(appTo(`/deals/${r.deal_id}`));
    } catch (e) { toast(e.message, "bad"); }
    setBusy(0);
  };
  const createDeal = async (item) => {
    setBusy(item.id);
    try { const r = await api(`/api/revenue-inbox/${item.id}/create-deal`, { method: "POST" });
      toast("Deal created — follow up in the thread"); nav(appTo(`/deals/${r.deal_id}`)); }
    catch (e) { toast(e.message, "bad"); }
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
        actions={<>
          <Button variant="secondary" icon={Download} loading={browseLoading} onClick={openBrowse}>Import from mailbox</Button>
          <Button variant="secondary" icon={RefreshCw} loading={syncing} onClick={syncNow}>Sync now</Button>
          <Button variant="ghost" onClick={reload}>Refresh</Button>
        </>} />

      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && (
        <Empty icon={<Mail size={26} />} title="Nothing waiting"
          hint="When your connected mailbox is on an email thread with a known contact, it shows up here to attach to a deal." />
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {(data || []).map((it) => {
          const open = !!expanded[it.id];
          const msgs = it.messages || [];
          const count = msgs.length;
          return (
          <div key={it.id} className="card" style={{ padding: 0, overflow: "hidden" }}>
            {/* header — click to expand the thread, Gmail-style */}
            <div onClick={() => setExpanded((e) => ({ ...e, [it.id]: !e[it.id] }))}
              style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: 16, cursor: "pointer" }}>
              <Avatar name={it.contact?.name || it.from_email} size={34} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <b style={{ fontSize: 14 }}>{it.subject || "(no subject)"}</b>
                  {count > 1 && <Badge>{count} messages</Badge>}
                  {it.contact && <Badge tone="green">{it.contact.name || it.contact.email}</Badge>}
                  {it.attached_deal && <Badge tone="blue">attached</Badge>}
                  <span style={{ color: "var(--muted)", fontSize: 12, marginLeft: "auto" }}>{timeAgo(it.created_at)}</span>
                </div>
                <div style={{ color: "var(--muted)", fontSize: 12.5, margin: "2px 0 6px" }}>
                  with {it.contact?.email || it.from_email} · {(it.participants || []).length} on thread</div>
                {!open && <div style={{ fontSize: 13, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{emailText(it.preview)}</div>}
              </div>
              <ChevronDown size={16} style={{ color: "var(--muted)", flexShrink: 0, marginTop: 4, transform: open ? "" : "rotate(-90deg)", transition: "transform .15s" }} />
            </div>

            {/* expanded thread: every message, oldest first */}
            {open && (
              <div style={{ borderTop: "1px solid var(--border)", background: "var(--bg)", padding: "6px 16px 14px" }}>
                {(count ? msgs : [{ direction: "in", from_email: it.from_email, text: it.preview }]).map((mm, i) => (
                  <ThreadMsg key={i} mm={mm} name={it.contact?.name} last={i >= count - 1} />
                ))}
              </div>
            )}

            {/* actions */}
            <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 16px", borderTop: "1px solid var(--border,#e6e9ef)", flexWrap: "wrap" }}>
              {it.attached_deal ? (
                <Button icon={ArrowRight} onClick={() => nav(appTo(`/deals/${it.attached_deal.id}`))}>Open deal · {it.attached_deal.name}</Button>
              ) : it.deals.length > 0 ? (
                <>
                  <Select size="sm" value={pick[it.id] || it.deals[0].id} onChange={(e) => setPick({ ...pick, [it.id]: e.target.value })}>
                    {it.deals.map((dd) => <option key={dd.id} value={dd.id}>{dd.name || `Deal #${dd.id}`}</option>)}
                  </Select>
                  <Button icon={ArrowRight} loading={busy === it.id} onClick={() => attach(it)}>Attach to deal</Button>
                </>
              ) : (
                <>
                  <span style={{ fontSize: 12.5, color: "var(--muted)" }}>No deal yet —</span>
                  <Button icon={ArrowRight} loading={busy === it.id} onClick={() => createDeal(it)}>Create deal &amp; follow up</Button>
                </>
              )}
              <span style={{ flex: 1 }} />
              <Button variant="ghost" icon={X} disabled={busy === it.id} onClick={() => dismiss(it)}>Dismiss</Button>
            </div>
          </div>
          );
        })}
      </div>

      <AnimatePresence>
      {browse && (
        <Modal key="browse" title="Import from mailbox" onClose={() => setBrowse(null)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            Conversations in <b>{browse.mailbox || "your mailbox"}</b>. Filter by a Gmail label or search, then import.
            Threads with a known lead are tagged — those are your pipeline contacts.</p>
          <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
            <Select size="sm" value={filterLabel} onChange={(e) => { setFilterLabel(e.target.value); fetchThreads(e.target.value, filterQ); }}
              style={{ minWidth: 150 }}>
              <option value="">All mail (last 90 days)</option>
              {labels.map((l) => <option key={l.id} value={l.name}>{l.name}</option>)}
            </Select>
            <input value={filterQ} onChange={(e) => setFilterQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchThreads(filterLabel, filterQ)}
              placeholder="Search sender, subject, text… (Enter)"
              style={{ flex: 1, minWidth: 180, padding: "8px 10px", borderRadius: 8, fontSize: 13 }} />
            <Button variant="secondary" loading={browseLoading} onClick={() => fetchThreads(filterLabel, filterQ)}>Search</Button>
          </div>
          {browseLoading && <div className="center" style={{ minHeight: 80 }}><div className="spinner" /></div>}
          {!browseLoading && (!browse.items || browse.items.length === 0) && (
            <div className="empty" style={{ padding: 20 }}>No conversations found for this filter.</div>
          )}
          <div style={{ display: "grid", gap: 6, maxHeight: "52vh", overflow: "auto" }}>
            {(browse.items || []).map((t) => {
              const k = t.thread_id || t.rfc_message_id || t.subject + t.counterpart;
              const on = !!sel[k];
              return (
                <label key={k}
                  style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 12px", borderRadius: 10,
                    border: `1px solid ${on ? "var(--primary,#2563eb)" : "var(--border,#e2e4e9)"}`,
                    background: on ? "var(--primary-soft,#eff6ff)" : "var(--card)", cursor: t.already ? "default" : "pointer",
                    opacity: t.already ? 0.6 : 1 }}>
                  <input type="checkbox" checked={on} disabled={t.already}
                    onChange={(e) => setSel((s) => { const n = { ...s }; if (e.target.checked) n[k] = t; else delete n[k]; return n; })}
                    style={{ marginTop: 3 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <b style={{ fontSize: 13 }}>{t.subject || "(no subject)"}</b>
                      {t.known && <Badge tone="green">known lead: {t.contact?.name || t.contact?.email}</Badge>}
                      {t.already && <Badge>already imported</Badge>}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--muted)", margin: "1px 0 3px" }}>with {t.counterpart}</div>
                    <div style={{ fontSize: 12.5, color: "var(--ink-2,#3b4557)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{emailText(t.preview)}</div>
                  </div>
                </label>
              );
            })}
          </div>
          <div className="actions" style={{ marginTop: 14 }}>
            <button className="btn ghost" onClick={() => setBrowse(null)}>Cancel</button>
            {(browse.items || []).some((t) => !t.already) && (
              <Button variant="secondary" onClick={importAll}>Import all shown</Button>
            )}
            <Button icon={InboxIcon} onClick={importSelected}>Import selected ({Object.keys(sel).length})</Button>
          </div>
        </Modal>
      )}
      </AnimatePresence>
    </>
  );
}
