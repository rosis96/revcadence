// Settings → Email: connect ONE mailbox, Instantly-style. Three providers:
//  • Google Workspace  → Gmail API over HTTPS (domain-wide delegation, no password)
//  • Microsoft 365      → Graph API over HTTPS (app-only + admin consent, no password)
//  • Any Provider       → app password over SMTP/IMAP
// The HTTPS paths work even where the host blocks SMTP/IMAP (Railway).
import { useEffect, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Mail, CheckCircle2, AlertCircle, Plug, Sparkles, ArrowRight, Copy, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { useAppPath } from "../clientspace/appPath";
import { useAuth } from "../auth";
import { Badge, Button, ConfirmDialog, PageHeader, Spinner, useApi, useToast } from "../components";

// The three picker cards. `flow` drives which guided body shows.
const CARDS = [
  { key: "google_workspace", name: "Google", sub: "Gmail / Workspace", badge: "G", color: "#ea4335", flow: "google" },
  { key: "microsoft_graph", name: "Microsoft", sub: "Office 365 / Outlook", badge: "M", color: "#0078d4", flow: "microsoft" },
  { key: "smtp", name: "Any Provider", sub: "IMAP / SMTP", badge: "@", color: "var(--muted2)", flow: "smtp" },
];

export default function MailboxConnect() {
  const appTo = useAppPath();
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);
  const toast = useToast();
  const nav = useNavigate();
  const { data: existing, loading, reload } = useApi("/api/mailbox", { workspace_id: wsParam });
  const { data: gw } = useApi("/api/mailbox/google-workspace");
  const { data: ms } = useApi("/api/mailbox/microsoft");
  const { data: goauth } = useApi("/api/oauth/google/config");
  const [form, setForm] = useState({ provider: "google_workspace", email: "", app_password: "", from_name: "",
    username: "", smtp_host: "", smtp_port: "", imap_host: "", imap_port: "" });
  const [fu, setFu] = useState(null);
  const [confirmDisc, setConfirmDisc] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);

  const card = CARDS.find((c) => c.key === form.provider) || CARDS[0];
  const isAPI = form.provider === "google_workspace" || form.provider === "microsoft_graph";

  useEffect(() => {
    if (existing) setFu({ default_autopilot: !!existing.default_autopilot,
      default_interval_days: existing.default_interval_days || 4,
      default_max_followups: existing.default_max_followups || 4 });
  }, [existing?.id, existing?.default_autopilot]);
  useEffect(() => { if (existing) setForm((f) => ({ ...f, provider: existing.provider, email: existing.email, from_name: existing.from_name || "" })); }, [existing]);

  // Handle the return from the Google sign-in redirect.
  useEffect(() => {
    const q = new URLSearchParams(window.location.hash.split("?")[1] || "");
    if (q.get("connected")) { toast("Mailbox connected via Google — importing recent conversations…"); setImporting(true); reload(); }
    else if (q.get("oauth") === "error") { toast("Google sign-in didn't complete. Make sure your admin authorized RevCadence, then try again.", "bad"); }
    if (q.get("connected") || q.get("oauth")) window.history.replaceState(null, "", window.location.hash.split("?")[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signInGoogle = async () => {
    if (!wsId) { toast("Pick a workspace first (top bar)", "bad"); return; }
    try { const r = await api("/api/oauth/google/start", { params: { workspace_id: wsId } }); window.location.href = r.url; }
    catch (e) { toast(e.message, "bad"); }
  };

  const saveFu = async () => {
    try { await api("/api/mailbox/followup-defaults", { method: "PUT", body: { workspace_id: wsId, ...fu } }); toast("Follow-up defaults saved"); reload(); }
    catch (e) { toast(e.message, "bad"); }
  };
  const copy = async (t) => { try { await navigator.clipboard.writeText(t); toast("Copied"); } catch { toast("Copy failed", "bad"); } };

  const connect = async () => {
    if (!wsId) { toast("Pick a workspace first (top bar)", "bad"); return; }
    if (!form.email) { toast("Mailbox address is required", "bad"); return; }
    if (!isAPI && !form.app_password) { toast("App password is required", "bad"); return; }
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

  // A reusable guided-authorization block for the two HTTPS providers.
  const AuthSteps = ({ info, title, adminLabel, notConfiguredEnv, scopesLabel }) => (
    <div className="card" style={{ padding: 14, marginBottom: 12, background: "var(--card-2)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
        <ShieldCheck size={16} style={{ color: "var(--accent,#635BFF)" }} /> {title}
      </div>
      <span className="pill green" style={{ marginBottom: 10 }}><span className="dot" /> You only need to do this once per domain</span>
      {info && !info.enabled && (
        <div className="error-box" style={{ fontSize: 12.5, margin: "8px 0" }}>
          Not configured on the server yet. Set <code>{notConfiguredEnv}</code> on the backend, then reload.
        </div>
      )}
      <ol style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 12.5, color: "var(--ink-2,#3b4557)", lineHeight: 1.7 }}>
        <li>Open <a href={info?.admin_url || "#"} target="_blank" rel="noreferrer">{adminLabel}</a>.</li>
        <li>Client ID:&nbsp;<code style={{ fontSize: 12 }}>{info?.client_id || "—"}</code>
          {info?.client_id && <button className="btn ghost sm" style={{ marginLeft: 6 }} onClick={() => copy(info.client_id)}><Copy size={12} /> Copy</button>}</li>
        <li>{scopesLabel}:<br /><code style={{ fontSize: 11.5 }}>{(info?.scopes || []).join(", ")}</code>
          {info?.scopes?.length > 0 && <button className="btn ghost sm" style={{ marginLeft: 6 }} onClick={() => copy((info.scopes || []).join(","))}><Copy size={12} /> Copy</button>}</li>
        <li>Approve, then enter the mailbox address below and Connect.</li>
      </ol>
    </div>
  );

  return (
    <div style={{ maxWidth: 660 }}>
      <PageHeader title="Email" desc="Connect one mailbox. RevCadence sends from your real address and keeps every reply in the same thread on the Deal." />
      {loading && <Spinner />}

      {importing && (
        <div className="card" style={{ padding: 16, marginBottom: 14, display: "flex", alignItems: "center", gap: 12, background: "linear-gradient(180deg, var(--primary-soft), var(--card) 65%)", borderColor: "var(--accent-border)" }}>
          <Sparkles size={20} style={{ color: "var(--accent,#635BFF)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>Importing your last 60 days of conversations…</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)" }}>We're matching them to your contacts and deals. Known threads appear in the Revenue Inbox in a minute or two.</div>
          </div>
          <Button icon={ArrowRight} onClick={() => nav(appTo("/revenue-inbox"))}>Open Revenue Inbox</Button>
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
          <h3 style={{ fontSize: 14, margin: "0 0 6px", display: "flex", alignItems: "center", gap: 8 }}><Sparkles size={16} /> Follow-up autopilot defaults</h3>
          <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "0 0 12px" }}>New deals in this workspace inherit these. When on, the AI follows up in the same email thread automatically — stopping the moment the prospect replies.</p>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginBottom: 10 }}>
            <input type="checkbox" checked={fu.default_autopilot} onChange={(e) => setFu({ ...fu, default_autopilot: e.target.checked })} />
            Turn on autopilot for new deals by default
          </label>
          <div style={{ display: "flex", gap: 14, alignItems: "flex-end" }}>
            <label style={{ fontSize: 12.5 }}>Days between follow-ups
              <input type="number" min="1" max="60" value={fu.default_interval_days} style={{ width: 90, display: "block", marginTop: 4 }} onChange={(e) => setFu({ ...fu, default_interval_days: Number(e.target.value) || 4 })} /></label>
            <label style={{ fontSize: 12.5 }}>Max follow-ups
              <input type="number" min="0" max="12" value={fu.default_max_followups} style={{ width: 90, display: "block", marginTop: 4 }} onChange={(e) => setFu({ ...fu, default_max_followups: Number(e.target.value) || 0 })} /></label>
            <Button variant="secondary" onClick={saveFu}>Save defaults</Button>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 18 }}>
        <h3 style={{ fontSize: 14, margin: "0 0 12px", display: "flex", alignItems: "center", gap: 8 }}><Mail size={16} /> {existing ? "Reconnect / update" : "Connect existing accounts"}</h3>

        {/* Provider picker (Instantly-style cards) */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 14 }}>
          {CARDS.map((c) => {
            const on = form.provider === c.key;
            return (
              <button key={c.key} onClick={() => setForm((f) => ({ ...f, provider: c.key }))}
                style={{ textAlign: "left", cursor: "pointer", padding: "12px 14px", borderRadius: 12,
                  border: `1px solid ${on ? "var(--primary,#2563eb)" : "var(--border,#e2e4e9)"}`,
                  background: on ? "var(--primary-soft,#eff6ff)" : "var(--card)",
                  display: "flex", alignItems: "center", gap: 10, transition: "border-color .15s, background .15s" }}>
                <span style={{ width: 30, height: 30, borderRadius: 8, background: c.color, color: "var(--card)", fontWeight: 800,
                  display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{c.badge}</span>
                <span><span style={{ display: "block", fontWeight: 650, fontSize: 13.5 }}>{c.name}</span>
                  <span style={{ display: "block", fontSize: 11.5, color: "var(--muted)" }}>{c.sub}</span></span>
              </button>
            );
          })}
        </div>

        {card.flow === "google" && (
          <>
            <AuthSteps info={gw} title="Authorize RevCadence in Google Admin"
              adminLabel="Google Admin → Security → Domain-wide delegation → Add new"
              notConfiguredEnv="GOOGLE_WORKSPACE_SA_JSON" scopesLabel="OAuth scopes (paste comma-separated)" />
            {goauth?.enabled && (
              <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "0 0 6px" }}>
                <button onClick={signInGoogle}
                  style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: "pointer",
                    padding: "10px 16px", borderRadius: 10, border: "1px solid var(--border-strong,#cdd0d8)",
                    background: "var(--card)", fontWeight: 600, fontSize: 14 }}>
                  <span style={{ width: 20, height: 20, borderRadius: 4, background: "var(--card)",
                    border: "1px solid var(--border)", color: "#ea4335", fontWeight: 800,
                    display: "inline-flex", alignItems: "center", justifyContent: "center" }}>G</span>
                  Sign in with Google
                </button>
                <span style={{ fontSize: 12, color: "var(--muted)" }}>One click — pick your account, no typing.</span>
              </div>
            )}
          </>
        )}
        {card.flow === "microsoft" && (
          <AuthSteps info={ms} title="Grant admin consent in Microsoft 365"
            adminLabel="Microsoft admin consent (opens Microsoft login)"
            notConfiguredEnv="MS_GRAPH_CLIENT_ID / MS_GRAPH_CLIENT_SECRET" scopesLabel="Application permissions to approve" />
        )}
        {card.flow === "smtp" && (
          <div style={{ fontSize: 12.5, color: "var(--muted)", background: "var(--bg)", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
            Enter your provider's SMTP/IMAP host + port, the login username, and an app password. (Note: hosts that block outbound SMTP can't use this path — prefer Google or Microsoft above.)
          </div>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {F("email", "Mailbox address", "you@company.com", "email")}
          {F("from_name", "From name", "Your Name")}
          {!isAPI && F("app_password", "App password", "16-character app password", "password")}
          {!isAPI && F("username", "Login username (optional)", "defaults to the address")}
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
          {isAPI ? "Access is granted by your admin and used only to send/receive on your behalf. Nothing is sent automatically — the AI drafts, you approve."
                 : "Your password is encrypted at rest and only used to send/receive on your behalf. Nothing is sent automatically — the AI drafts, you approve."}</p>
      </div>

      <AnimatePresence>
      {confirmDisc && (
        <ConfirmDialog key="disc" title="Disconnect mailbox" message={`Disconnect ${existing?.email}? You can reconnect it anytime.`}
          confirmLabel="Disconnect" danger onConfirm={disconnect} onClose={() => setConfirmDisc(false)} />
      )}
      </AnimatePresence>
    </div>
  );
}
