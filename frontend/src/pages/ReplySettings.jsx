// Reply Management → Reply Settings: OpenAI/Gemini keys + models, human-review
// webhook, Bison base URL, reply delay, trigger tags. Secrets are write-only.
//
// One screen, two scopes, decided by the server (see routers/reply.py). A master
// on "All workspaces" edits the org-wide defaults, exactly as this screen always
// did. Anyone scoped to a workspace — a client always is — edits that client's
// own reply space instead, because every value here is a single value and an
// org-wide one edited by one client would land on all of them.
//
// The screen does not decide which it is. It renders `scope` from the response,
// which is what keeps the header honest about what a Save is about to change.
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Spinner } from "../components";
import { alertDialog } from "../components";

function Field({ label, children, hint }) {
  return <div className="field"><label>{label}</label>{children}{hint && <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 3 }}>{hint}</div>}</div>;
}

export default function ReplySettings() {
  const { wsParam } = useAuth();
  const [s, setS] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setS(null); setError("");
    api("/api/reply/settings", { params: { workspace_id: wsParam } })
      .then(setS).catch((e) => setError(e.message));
  }, [wsParam]);
  if (error) return <ErrorBox msg={error} />;
  if (!s) return <Spinner />;
  const set = (k, v) => setS({ ...s, [k]: v });
  const scoped = s.scope === "workspace";
  // Saved, but nothing reads them yet. Saying so is cheaper than a support call
  // asking why the trigger tag did not do anything.
  const inert = new Set(s.inert || []);
  const inertNote = (key) => (inert.has(key) ? "saved, not yet acted on" : "");

  const save = async () => {
    setBusy(true); setSaved(false);
    try {
      await api("/api/reply/settings", { method: "PUT", params: { workspace_id: wsParam }, body: {
        openai_api_key: s.openai_api_key || "", gemini_api_key: s.gemini_api_key || "",
        openai_model: s.openai_model, gemini_model: s.gemini_model,
        review_webhook_url: s.review_webhook_url, default_bison_base_url: s.default_bison_base_url,
        reply_delay_seconds: s.reply_delay_seconds, reply_trigger_tag: s.reply_trigger_tag,
        followup_trigger_tag: s.followup_trigger_tag,
      } });
      setSaved(true); setTimeout(() => setSaved(false), 2500);
    } catch (e) { alertDialog(e.message); }
    setBusy(false);
  };

  const secret = (key, label, isSet) => (
    <Field label={`${label}${isSet ? " · set" : ""}`} hint={isSet ? "leave blank to keep the current value" : ""}>
      <input type="password" placeholder={isSet ? "••••••••" : "sk-…"} onChange={(e) => set(key, e.target.value)} /></Field>
  );

  return (
    <div style={{ maxWidth: 1100 }}>
      <div className="toolbar">
        <h1 style={{ fontSize: 18 }}>
          Reply Settings{scoped && s.scope_label ? ` — ${s.scope_label}` : ""}
        </h1><div className="spacer" />
        {saved && <span style={{ color: "var(--ok)", fontSize: 13 }}>Saved ✓</span>}
        <button className="btn" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save settings"}</button>
      </div>

      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ fontSize: 14, marginBottom: 4 }}>
          AI models{scoped ? "" : " (global defaults)"}</h2>
        <p style={{ color: "var(--muted)", fontSize: 12.5, marginBottom: 12 }}>
          {scoped
            ? <>These apply to this workspace only. Leave a field blank to inherit the platform default.</>
            : <>Each reply space picks its provider; these keys/models are used unless a space sets its own.</>}</p>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          {secret("openai_api_key", "OpenAI API key", s.openai_api_key_set)}
          {secret("gemini_api_key", "Gemini API key", s.gemini_api_key_set)}
          <Field label="OpenAI model"><input value={s.openai_model} onChange={(e) => set("openai_model", e.target.value)} placeholder="gpt-4.1" /></Field>
          <Field label="Gemini model"><input value={s.gemini_model} onChange={(e) => set("gemini_model", e.target.value)} placeholder="gemini-2.5-pro" /></Field>
        </div>
      </div>

      <div className="card" style={{ padding: 18, marginTop: 14 }}>
        <h2 style={{ fontSize: 14, marginBottom: 12 }}>Routing & timing</h2>
        <Field label="Human-review webhook URL" hint={inertNote("review_webhook_url") || "posted when a reply needs a human (e.g. Make.com)"}><input style={{ width: "100%" }} value={s.review_webhook_url} onChange={(e) => set("review_webhook_url", e.target.value)} /></Field>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field label={scoped ? "Bison base URL" : "Default Bison base URL"}><input value={s.default_bison_base_url} onChange={(e) => set("default_bison_base_url", e.target.value)} /></Field>
          <Field label="Reply delay (seconds)"><input type="number" value={s.reply_delay_seconds} onChange={(e) => set("reply_delay_seconds", e.target.value)} placeholder="420" /></Field>
          <Field label="Reply trigger tag (Bison)" hint={inertNote("reply_trigger_tag")}><input value={s.reply_trigger_tag} onChange={(e) => set("reply_trigger_tag", e.target.value)} placeholder="Interested" /></Field>
          <Field label="Follow-up trigger tag (Bison)" hint={inertNote("followup_trigger_tag")}><input value={s.followup_trigger_tag} onChange={(e) => set("followup_trigger_tag", e.target.value)} placeholder="Begin follow-up" /></Field>
        </div>
      </div>
      <div className="toolbar" style={{ marginTop: 16 }}><div className="spacer" /><button className="btn" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save settings"}</button></div>
    </div>
  );
}
