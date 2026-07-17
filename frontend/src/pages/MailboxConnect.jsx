// Settings → Email: connect ONE mailbox (v1: app password over SMTP+IMAP) so the
// Deal Conversation can send from your real address in the same thread. OAuth for
// Google/Microsoft is a later drop-in behind the same API.
import { useEffect, useState } from "react";
import { Mail, CheckCircle2, AlertCircle, Plug } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, PageHeader, Spinner, useApi, useToast } from "../components";

const PROVIDERS = [
  { key: "gmail", label: "Google Workspace / Gmail" },
  { key: "outlook", label: "Microsoft 365 / Outlook" },
  { key: "smtp", label: "Other (custom SMTP/IMAP)" },
];

const HELP = {
  gmail: "Gmail needs an App Password (Google Account → Security → 2-Step Verification → App passwords). Use that 16-character password below, not your normal login.",
  outlook: "Microsoft 365 needs SMTP AUTH enabled for the mailbox, and an app password if security defaults require it. Use the mailbox address and app password below.",
  smtp: "Enter your provider's SMTP and IMAP host/port, the login username, and an app password.",
};

export default function MailboxConnect() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);
  const toast = useToast();
  const { data: existing, loading, reload } = useApi("/api/mailbox", { workspace_id: wsParam });
  const [form, setForm] = useState({ provider: "gmail", email: "", app_password: "", from_name: "",
    username: "", smtp_host: "", smtp_port: "", imap_host: "", imap_port: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (existing) setForm((f) => ({ ...f, provider: existing.provider, email: existing.email, from_name: existing.from_name || "" })); }, [existing]);

  const connect = async () => {
    if (!wsId) { toast("Pick a workspace first (top bar)", "bad"); return; }
    if (!form.email || !form.app_password) { toast("Email and app password are required", "bad"); return; }
    setBusy(true);
    try {
      await api("/api/mailbox/connect", { method: "POST", body: {
        workspace_id: Number(wsId), provider: form.provider, email: form.email,
        app_password: form.app_password, from_name: form.from_name, username: form.username,
        smtp_host: form.smtp_host, smtp_port: form.smtp_port ? Number(form.smtp_port) : null,
        imap_host: form.imap_host, imap_port: form.imap_port ? Number(form.imap_port) : null } });
      toast("Mailbox connected"); setForm((f) => ({ ...f, app_password: "" })); reload();
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
    if (!existing || !confirm("Disconnect this mailbox?")) return;
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

      {existing && (
        <div className="card" style={{ padding: 16, marginBottom: 14, display: "flex", alignItems: "center", gap: 12 }}>
          {existing.status === "connected" ? <CheckCircle2 size={20} style={{ color: "var(--ok,#12b76a)" }} /> : <AlertCircle size={20} style={{ color: "var(--bad,#f04438)" }} />}
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>{existing.email}</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)" }}>{existing.provider} · <Badge tone={existing.status === "connected" ? "green" : "red"}>{existing.status}</Badge>{existing.last_error ? ` · ${existing.last_error}` : ""}</div>
          </div>
          <Button variant="secondary" onClick={test} disabled={busy}>Test</Button>
          <Button variant="danger" onClick={disconnect} disabled={busy}>Disconnect</Button>
        </div>
      )}

      <div className="card" style={{ padding: 18 }}>
        <h3 style={{ fontSize: 14, margin: "0 0 12px", display: "flex", alignItems: "center", gap: 8 }}><Mail size={16} /> {existing ? "Reconnect / update" : "Connect a mailbox"}</h3>
        <div className="field"><label>Provider</label>
          <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
            {PROVIDERS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select></div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", background: "var(--bg)", borderRadius: 8, padding: "10px 12px", margin: "0 0 12px" }}>{HELP[form.provider]}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {F("email", "Mailbox address", "you@company.com", "email")}
          {F("from_name", "From name", "Your Name")}
          {F("app_password", "App password", "16-character app password", "password")}
          {F("username", "Login username (optional)", "defaults to the address")}
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
          Your password is encrypted at rest and only used to send/receive on your behalf. Nothing is sent automatically — the AI drafts, you approve.</p>
      </div>
    </div>
  );
}
