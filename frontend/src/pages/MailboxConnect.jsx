// Settings → Email: connect ONE mailbox. Two ways:
//  • Google Workspace (domain-wide delegation) — sends via the Gmail API over
//    HTTPS, so it works even where the host blocks SMTP/IMAP. No app password;
//    the Workspace admin authorizes our client_id once.
//  • App password over SMTP+IMAP (Gmail/Outlook/custom).
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Mail, CheckCircle2, AlertCircle, Plug, Sparkles, ArrowRight, Copy, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, ConfirmDialog, PageHeader, Spinner, useApi, useToast } from "../components";

const PROVIDERS = [
  { key: "google_workspace", label: "Google Workspace (recommended · no password)" },
  { key: "gmail", label: "Gmail (app password)" },
  { key: "outlook", label: "Microsoft 365 / Outlook (app password)" },
  { key: "smtp", label: "Other (custom SMTP/IMAP)" },
];

const HELP = {
  google_workspace: "Sends and reads over the Gmail API (works even when SMTP/IMAP are blocked). Your Workspace admin authorizes RevCadence once with the Client ID below — then just enter the mailbox address. No app password.",
  gmail: "Gmail needs an App Password (Google Account → Security → 2-Step Verification → App passwords). Use that 16-character password below, not your normal login.",
  outlook: "Microsoft 365 needs SMTP AUTH enabled for the mailbox, and an app password if security defaults require it. Use the mailbox address and app password below.",
  smtp: "Enter your provider's SMTP and IMAP host/port, the login username, and an app password.",
};

export default function MailboxConnect() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);
  const toast = useToast();
  const nav = useNavigate();
  const { data: existing, loading, reload } = useApi("/api/mailbox", { workspace_id: wsParam });
  const { data: gw } = useApi("/api/mailbox/google-workspace");
  const [form, setForm] = useState({ provider: "google_workspace", email: "", app_password: "", from_name: "",
    username: "", smtp_host: "", smtp_port: "", imap_host: "", imap_port: "" });
  const [fu, setFu] = useState(null);
  const [confirmDisc, setConfirmDisc] = useState(false);
  const isGW = form.provider === "google_workspace";

  useEffect(() => {
    if (existing) setFu({ default_autopilot: !!existing.default_autopilot,
      default_interval_days: existing.default_interval_days || 4,
      default_max_followups: existing.default_max_followups || 4 });
  }, [existing?.id, existing?.default_autopilot]);
  const saveFu = async () => {
    try {
      await api("/api/mailbox/followup-defaults", { method: "PUT", body: { workspace_id: wsId, ...fu } });
      toast("Follow-up defaults saved"); reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);

  useEffect(() => { if (existing) setForm((f) => ({ ...f, provider: existing.provider, email: existing.email, from_name: existing.from_name || "" })); }, [existing]);

  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast("Copied"); } catch { toast("Copy failed", "bad"); }
  };

  const connect = async () => {
    if (!wsId) { toast("Pick a workspace first (top bar)", "bad"); return; }
    if (!form.email) { toast("Mailbox address is required", "bad"); return; }
    if (!isGW && !form.app_password) { toast("App password is required", "bad"); return; }
    setBusy(true);
    try {
      const r = await api("/api/mailbox/connect", { method: "POST", body: {
        workspace_id: Number(wsId), provider: form.provider, email: form.email,
        app_password: form.app_password, from_name: form.from_name, username: form.username,
        smtp_host: form.smtp_host, smtp_port: form.smtp_port ? Number(form.smtp_port) : null,
        imap_host: form.imap_host, imap_port: form.imap_port ? Number(form.imap_port) : null } });
      toast("Mailbox connected — importing your recent conversations…");
      setForm((f) => ({ ...f, app_password: "" })); reload();
      if (r.backfill_job_id) setImporting(true);
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const test = async () => {
    setBusy(true);
    try { const r = await api("/api/mailbox/test", { method: "POST", params: { workspace_id: wsId } }); toast(r.status === "connected" ? "Connection OK" : `Error: ${r.last_error}`, r.status === "connected" ? "ok" : "bad"); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const disconnect = async () => {
    setBusy(true);
    try { await api(`/api/mailbox/${existing.id}`, { method: "DELETE" }); toast("Disconnected"); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };

  const F = (k, label, ph, type = "text") => (
    <div className="field"><label>{label}</label>
      <input type={type} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} placeholder={ph} /></div>
  );

  return (
    <div style={{ maxWidth: 640 }}>
      <PageHeader title="Email" desc="Connect one mailbox. RevCadence sends from your real address and keeps every reply in the same thread on the Deal." />
      {loading && <Spinner />}

      {importing && (
        <div className="card" style={{ padding: 16, marginBottom: 14, display: "flex", alignItems: "center", gap: 12,
             background: "linear-gradient(180deg,#f6f5ff,#fff)", borderColor: "#d6d3ff" }}>
          <Sparkles size={20} style={{ color: "var(--accent,#635BFF)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>Importing your last 60 days of conversations…</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
              We're matching them to your contacts and deals. Known threads appear in the Revenue Inbox in a minute or two.</div>
          </div>
          <Button icon={ArrowRight} onClick={() => nav("/revenue-inbox")}>Open Revenue Inbox</Button>
        </div>
      )}

      {existing && (
        <div className="card" style={{ padding: 16, marginBottom: 14, display: "flex", alignItems: "center", gap: 12 }}>
          {existing.status === "connected" ? <CheckCircle2 size={20} style={{ color: "var(--ok,#12b76a)" }} /> : <AlertCircle size={20} style={{ color: "var(--bad,#f04438)" }} />}
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>{existing.email}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{existing.provider} · <Badge tone={existing.status === "connected" ? "green" : "red"}>{existing.status}</Badge>{existing.last_error ? ` · ${existing.last_error}` : ""}</div>
          </div>
          <Button variant="secondary" onClick={test} disabled={busy}>Test</Button>
          <Button variant="danger" onClick={() => setConfirmDisc(true)} disabled={busy}>Disconnect</Button>
        </div>
      )}

      {existing?.status === "connected" && fu && (
        <div className="card" style={{ padding: 16, marginBottom: 14 }}>
          <h3 style={{ fontSize: 14, margin: "0 0 6px", display: "flex", alignItems: "center", gap: 8 }}>
            <Sparkles size={16} /> Follow-up autopilot defaults</h3>
          <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 12px" }}>
            New deals in this workspace inherit these. When on, the AI follows up in the same email
            thread automatically — stopping the moment the prospect replies. (Existing deals keep their own setting.)</p>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginBottom: 10 }}>
            <input type="checkbox" checked={fu.default_autopilot}
              onChange={(e) => setFu({ ...fu, default_autopilot: e.target.checked })} />
            Turn on autopilot for new deals by default
          </label>
          <div style={{ display: "flex", gap: 14, alignItems: "flex-end" }}>
            <label style={{ fontSize: 12.5 }}>Days between follow-ups
              <input type="number" min="1" max="60" value={fu.default_interval_days} style={{ width: 90, display: "block", marginTop: 4 }}
                onChange={(e) => setFu({ ...fu, default_interval_days: Number(e.target.value) || 4 })} /></label>
            <label style={{ fontSize: 12.5 }}>Max follow-ups
              <input type="number" min="0" max="12" value={fu.default_max_followups} style={{ width: 90, display: "block", marginTop: 4 }}
                onChange={(e) => setFu({ ...fu, default_max_followups: Number(e.target.value) || 0 })} /></label>
            <Button variant="secondary" onClick={saveFu}>Save defaults</Button>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 18 }}>
        <h3 style={{ fontSize: 14, margin: "0 0 12px", display: "flex", alignItems: "center", gap: 8 }}><Mail size={16} /> {existing ? "Reconnect / update" : "Connect a mailbox"}</h3>
        <div className="field"><label>Provider</label>
          <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
            {PROVIDERS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select></div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", background: "var(--bg)", borderRadius: 8, padding: "10px 12px", margin: "0 0 12px" }}>{HELP[form.provider]}</div>

        {isGW && (
          <div className="card" style={{ padding: 14, marginBottom: 12, background: "#fbfbfe" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
              <ShieldCheck size={16} style={{ color: "var(--accent,#635BFF)" }} /> One-time admin authorization
            </div>
            {gw && !gw.enabled && (
              <div className="error-box" style={{ fontSize: 12.5, marginBottom: 10 }}>
                Google Workspace isn't configured on the server yet. Set <code>GOOGLE_WORKSPACE_SA_JSON</code> on the backend, then reload.
              </div>
            )}
            <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--ink-2,#3b4557)", lineHeight: 1.7 }}>
              <li>Open <a href={gw?.admin_url || "https://admin.google.com/ac/owl/domainwidedelegation"} target="_blank" rel="noreferrer">Google Admin → Domain-wide delegation</a> and click <b>Add new</b>.</li>
              <li>Client ID:&nbsp;
                <code style={{ fontSize: 12 }}>{gw?.client_id || "—"}</code>
                {gw?.client_id && <button className="btn ghost sm" style={{ marginLeft: 6 }} onClick={() => copy(gw.client_id)}><Copy size={12} /> Copy</button>}
              </li>
              <li>OAuth scopes (paste comma-separated):<br />
                <code style={{ fontSize: 11.5 }}>{(gw?.scopes || []).join(", ")}</code>
                {gw?.scopes?.length > 0 && <button className="btn ghost sm" style={{ marginLeft: 6 }} onClick={() => copy(gw.scopes.join(","))}><Copy size={12} /> Copy</button>}
              </li>
              <li>Click <b>Authorize</b>, then enter the mailbox address below and Connect.</li>
            </ol>
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {F("email", "Mailbox address", "you@company.com", "email")}
          {F("from_name", "From name", "Your Name")}
          {!isGW && F("app_password", "App password", "16-character app password", "password")}
          {!isGW && F("username", "Login username (optional)", "defaults to the address")}
        </div>
        {form.provider === "smtp" && (
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 10 }}>
            {F("smtp_host", "SMTP host", "smtp.example.com")}
            {F("smtp_port", "SMTP port", "587")}
            {F("imap_host", "IMAP host", "imap.example.com")}
            {F("imap_port", "IMAP port", "993")}
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          <Button icon={Plug} loading={busy} onClick={connect}>{existing ? "Reconnect" : "Connect mailbox"}</Button>
        </div>
        <p style={{ fontSize: 11.5, color: "var(--muted2)", marginTop: 10 }}>
          {isGW
            ? "Access is granted by your Workspace admin and used only to send/receive on your behalf. Nothing is sent automatically — the AI drafts, you approve."
            : "Your password is encrypted at rest and only used to send/receive on your behalf. Nothing is sent automatically — the AI drafts, you approve."}</p>
      </div>

      {confirmDisc && (
        <ConfirmDialog title="Disconnect mailbox"
          message={`Disconnect ${existing?.email}? You can reconnect it anytime.`}
          confirmLabel="Disconnect" danger
          onConfirm={disconnect} onClose={() => setConfirmDisc(false)} />
      )}
    </div>
  );
}
