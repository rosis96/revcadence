// Reply Management → Setup: edits THE current workspace's reply space (which is
// auto-provisioned with the workspace — no "create" step). Full structured
// editor: connection + AI + client profile + response types + follow-ups + rules.
// This is the legacy reply-format editor, ported faithfully.
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Spinner } from "../components";

function Field({ label, children, hint }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 3 }}>{hint}</div>}
    </div>
  );
}

// The exact, copy-ready webhook URL to paste into Instantly/Bison. This is the
// single most-missed setup step: if the sending platform isn't POSTing here,
// no replies ever reach RevCadence (the queue stays empty).
function WebhookBox({ platform, name }) {
  const [copied, setCopied] = useState(false);
  const origin = typeof window !== "undefined" ? window.location.origin : "https://engine.revcadence.com";
  const path = platform === "bison"
    ? `/api/reply/webhooks/bison?reply_workspace=${encodeURIComponent(name || "")}`
    : `/api/reply/webhooks/instantly?workspace_name=${encodeURIComponent(name || "")}`;
  const url = origin + path;
  const copy = () => { navigator.clipboard?.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <div className="card" style={{ padding: 14, margin: "4px 0 14px", background: "var(--bg-soft, #f7f8fb)" }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
        Webhook URL — paste this into {platform === "bison" ? "Bison" : "Instantly"} so replies reach RevCadence
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input readOnly value={url} onFocus={(e) => e.target.select()}
               style={{ flex: 1, fontFamily: "monospace", fontSize: 12, padding: "7px 9px" }} />
        <button className="btn ghost sm" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
      </div>
      <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8, lineHeight: 1.55 }}>
        {platform === "instantly"
          ? <>In Instantly: <b>Settings → Integrations → Webhooks</b> (or the campaign's webhook), add this URL and trigger it
             on <b>Reply Received</b> / <b>Lead marked Interested</b>. The <code>workspace_name</code> must match the reply-space
             name above <b>exactly</b>. Instantly's own “AI Reply Agent” is separate — this is RevCadence's engine, so you don't
             need Instantly's paid AI agent.</>
          : <>In Bison: add this as the reply webhook. The <code>reply_workspace</code> must match the reply-space name above exactly.</>}
      </div>
    </div>
  );
}

// ----- structured response types (Type id / intent / examples / template / rules / auto_send)
function ResponseTypes({ items, onChange }) {
  const set = (i, k, v) => onChange(items.map((t, j) => (j === i ? { ...t, [k]: v } : t)));
  const add = () => onChange([...items, { id: "", intent: "", examples: [], template: "", rules: "", auto_send: false }]);
  const remove = (i) => onChange(items.filter((_, j) => j !== i));
  return (
    <>
      {items.map((t, i) => (
        <div className="card" style={{ padding: 16, marginBottom: 12 }} key={i}>
          <div style={{ display: "flex", gap: 12 }}>
            <Field label="Type (id)"><input value={t.id} onChange={(e) => set(i, "id", e.target.value)} placeholder="simple_positive" /></Field>
            <div className="field" style={{ minWidth: 200 }}>
              <label>Auto-send?</label>
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginTop: 4 }}>
                <input type="checkbox" checked={!!t.auto_send} onChange={(e) => set(i, "auto_send", e.target.checked)} />
                send automatically on a confident match
              </label>
            </div>
          </div>
          <Field label="When it applies (intent)"><input style={{ width: "100%" }} value={t.intent} onChange={(e) => set(i, "intent", e.target.value)} /></Field>
          <Field label="Example replies (comma separated)">
            <input style={{ width: "100%" }} value={(t.examples || []).join(", ")}
                   onChange={(e) => set(i, "examples", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))} /></Field>
          <Field label="Response template"><textarea rows={5} style={{ width: "100%" }} value={t.template} onChange={(e) => set(i, "template", e.target.value)} /></Field>
          <Field label="Rules / conditions (one per line)"><textarea rows={2} style={{ width: "100%" }} value={t.rules} onChange={(e) => set(i, "rules", e.target.value)} /></Field>
          <div style={{ textAlign: "right" }}><button className="btn danger sm" onClick={() => remove(i)}>Remove</button></div>
        </div>
      ))}
      <button className="btn ghost sm" onClick={add}>+ Add response type</button>
    </>
  );
}

// ----- follow-up formats FUP1..6 (Label / max_words / intent / template)
function Followups({ items, onChange }) {
  const set = (i, k, v) => onChange(items.map((t, j) => (j === i ? { ...t, [k]: v } : t)));
  const add = () => onChange([...items, { label: `FUP ${items.length + 1}`, max_words: 100, intent: "", template: "" }]);
  const remove = (i) => onChange(items.filter((_, j) => j !== i));
  return (
    <>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 10 }}>
        In send order. The 1st becomes followup_1, the 2nd followup_2, and so on.</p>
      {items.map((t, i) => (
        <div className="card" style={{ padding: 16, marginBottom: 12 }} key={i}>
          <div style={{ display: "flex", gap: 12 }}>
            <Field label="Label"><input value={t.label} onChange={(e) => set(i, "label", e.target.value)} /></Field>
            <Field label="Max words"><input type="number" style={{ width: 100 }} value={t.max_words ?? ""} onChange={(e) => set(i, "max_words", Number(e.target.value) || null)} /></Field>
          </div>
          <Field label="Purpose (intent)"><input style={{ width: "100%" }} value={t.intent} onChange={(e) => set(i, "intent", e.target.value)} /></Field>
          <Field label="Template"><textarea rows={4} style={{ width: "100%" }} value={t.template} onChange={(e) => set(i, "template", e.target.value)} /></Field>
          <div style={{ textAlign: "right" }}><button className="btn danger sm" onClick={() => remove(i)}>Remove</button></div>
        </div>
      ))}
      <button className="btn ghost sm" onClick={add}>+ Add follow-up</button>
    </>
  );
}

export default function ReplySetup() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [w, setW] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [secrets, setSecrets] = useState({});
  const [pasteJson, setPasteJson] = useState("");
  const [calResult, setCalResult] = useState(null);

  useEffect(() => {
    setW(null); setError("");
    if (!wsId || !me.is_master) return;
    api(`/api/reply/workspaces/for/${wsId}`).then(setW).catch((e) => setError(e.message));
  }, [wsId]);

  if (!me.is_master) return <ErrorBox msg="Master access required." />;
  if (!wsId) return <ErrorBox msg="Pick a specific workspace (top-left) — reply setup is per client workspace." />;
  if (error) return <ErrorBox msg={error} />;
  if (!w) return <Spinner />;

  const set = (k, v) => setW({ ...w, [k]: v });
  const checkCalendly = async () => {
    setCalResult(null);
    try { setCalResult(await api(`/api/reply/workspaces/${w.id}/calendly-probe`)); }
    catch (e) { setCalResult({ ok: false, error: e.message }); }
  };
  const rf = w.reply_format || { response_types: [], followups: [] };
  const setRf = (patch) => set("reply_format", { ...rf, ...patch });

  // REPLACE the sections with the pasted JSON (asks first — this overwrites).
  const fillFromJson = () => {
    try {
      const p = JSON.parse(pasteJson);
      if (!confirm("Replace the current response types and follow-ups with the pasted JSON? "
                   + "Use 'Add to existing' instead if you want to keep what's here.")) return;
      setRf({ response_types: p.response_types || rf.response_types || [], followups: p.followups || rf.followups || [] });
      setPasteJson("");
    } catch (e) { alert("Invalid JSON: " + e.message); }
  };

  // ADD the pasted intents without deleting anything: merge response types by
  // id (an incoming id updates the matching one, new ids are appended); append
  // any follow-ups. Existing data is preserved.
  const addFromJson = () => {
    try {
      const p = JSON.parse(pasteJson);
      const existing = rf.response_types || [];
      const incoming = Array.isArray(p.response_types) ? p.response_types : [];
      const merged = [...existing];
      for (const t of incoming) {
        const i = t && t.id ? merged.findIndex((e) => e.id === t.id) : -1;
        if (i >= 0) merged[i] = { ...merged[i], ...t };
        else merged.push(t);
      }
      const fups = Array.isArray(p.followups) ? [...(rf.followups || []), ...p.followups] : (rf.followups || []);
      setRf({ response_types: merged, followups: fups });
      setPasteJson("");
      alert(`Added. Response types now: ${merged.length}. Review, then Save all.`);
    } catch (e) { alert("Invalid JSON: " + e.message); }
  };

  // Back up the full reply config (no secrets) so nothing is ever lost.
  const downloadJson = () => {
    const data = {
      name: w.name, platform: w.platform, mode: w.mode, website: w.website,
      sender_name: w.sender_name, reply_delay_seconds: w.reply_delay_seconds,
      ai_provider: w.ai_provider, ai_rules: w.ai_rules || "",
      client_profile: w.client_profile || {},
      reply_format: { response_types: rf.response_types || [], followups: rf.followups || [] },
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(w.name || "reply-space").replace(/[^a-z0-9]+/gi, "_")}-reply-config.json`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
  };

  const save = async () => {
    setBusy(true); setSaved(false);
    try {
      await api(`/api/reply/workspaces/${w.id}`, { method: "PUT", body: {
        workspace_id: w.workspace_id, name: w.name, platform: w.platform, mode: w.mode,
        active: w.active, base_url: w.base_url, reply_followup_campaign_id: w.reply_followup_campaign_id,
        website: w.website, sender_name: w.sender_name, default_sender_email: w.default_sender_email,
        calendly_scheduling_url: w.calendly_scheduling_url, ai_provider: w.ai_provider,
        ai_fallback: w.ai_fallback, client_profile: w.client_profile, reply_format: w.reply_format,
        ai_rules: w.ai_rules, reply_delay_seconds: w.reply_delay_seconds, ...secrets,
      } });
      setSaved(true); setSecrets({}); setTimeout(() => setSaved(false), 2500);
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  const secretField = (key, label, isSet) => (
    <Field label={`${label}${isSet ? " · set" : ""}`} hint={isSet ? "leave blank to keep the current value" : ""}>
      <input type="password" placeholder={isSet ? "••••••••" : ""} onChange={(e) => setSecrets({ ...secrets, [key]: e.target.value })} />
    </Field>
  );

  return (
    <div>
      <div className="toolbar">
        <h1 style={{ fontSize: 18 }}>Reply Setup — {me.workspaces.find((x) => x.id === Number(wsId))?.name}</h1>
        {w.active ? <Badge tone="green">active</Badge> : <Badge tone="amber">inactive</Badge>}
        <div className="spacer" />
        {saved && <span style={{ color: "var(--ok)", fontSize: 13 }}>Saved ✓</span>}
        <button className="btn" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save all"}</button>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1.4fr 1fr", alignItems: "start" }}>
      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ fontSize: 14, marginBottom: 12 }}>Connection</h2>
        <Field label="Reply-space name (must match webhook ?workspace_name= / ?reply_workspace=)">
          <input style={{ width: "100%" }} value={w.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <WebhookBox platform={w.platform} name={w.name} />

        <div style={{ display: "flex", gap: 12 }}>
          <Field label="Platform"><select value={w.platform} onChange={(e) => set("platform", e.target.value)}><option value="bison">Bison</option><option value="instantly">Instantly</option></select></Field>
          <Field label="Mode"><select value={w.mode} onChange={(e) => set("mode", e.target.value)}><option value="reply">reply</option><option value="followup">followup</option></select></Field>
          <Field label="Reply delay (seconds)"><input type="number" style={{ width: 110 }} value={w.reply_delay_seconds} onChange={(e) => set("reply_delay_seconds", Number(e.target.value))} /></Field>
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          {secretField("api_key", "API key", w.api_key_set)}
          <Field label="Follow-up campaign ID"><input value={w.reply_followup_campaign_id} onChange={(e) => set("reply_followup_campaign_id", e.target.value)} /></Field>
        </div>
        {w.platform === "bison" && <Field label="Base URL (Bison)"><input style={{ width: "100%" }} value={w.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="https://send.ascendly.one" /></Field>}
        <div style={{ display: "flex", gap: 12 }}>
          <Field label="Sender name"><input value={w.sender_name} onChange={(e) => set("sender_name", e.target.value)} /></Field>
          <Field label="Website (signature)"><input value={w.website} onChange={(e) => set("website", e.target.value)} /></Field>
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          {secretField("calendly_token", "Calendly token", w.calendly_token_set)}
          <Field label="Calendly scheduling link"><input value={w.calendly_scheduling_url} onChange={(e) => set("calendly_scheduling_url", e.target.value)} /></Field>
        </div>
        <button type="button" className="btn ghost sm" onClick={checkCalendly}>
          Check Calendly availability →</button>
        {calResult && (
          <div className={calResult.ok ? "card" : "error-box"}
               style={{ marginTop: 8, padding: 10, fontSize: 12.5, ...(calResult.ok ? {} : {}) }}>
            {calResult.ok ? (
              <>Event type <b>{calResult.event_type_slug}</b> · sample times:{" "}
                {calResult.sample_slots.length ? calResult.sample_slots.join(" · ") : "none in the next week"}
                <div style={{ color: "var(--muted)", marginTop: 4 }}>{calResult.note}</div></>
            ) : calResult.error}
          </div>
        )}
        <label style={{ display: "flex", gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={w.active} onChange={(e) => set("active", e.target.checked)} /> Active (receives webhooks)</label>
      </div>

      <div>
      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ fontSize: 14, marginBottom: 8 }}>AI model</h2>
        <div style={{ display: "flex", gap: 12 }}>
          <Field label="Provider"><select value={w.ai_provider} onChange={(e) => set("ai_provider", e.target.value)}><option value="openai">OpenAI</option><option value="gemini">Gemini</option></select></Field>
        </div>
        <label style={{ display: "flex", gap: 8, fontSize: 13 }}><input type="checkbox" checked={w.ai_fallback} onChange={(e) => set("ai_fallback", e.target.checked)} /> Auto-fallback to the other provider on failure</label>
      </div>

      <div className="card" style={{ padding: 18, marginTop: 14 }}>
        <h2 style={{ fontSize: 14, marginBottom: 8 }}>Client profile (JSON)</h2>
        <textarea rows={8} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                  value={JSON.stringify(w.client_profile || {}, null, 2)}
                  onChange={(e) => { try { set("client_profile", JSON.parse(e.target.value || "{}")); } catch { /* keep typing */ } }} />
      </div>
      </div>
      </div>

      <div className="section">
        <div className="toolbar">
          <h2 style={{ margin: 0 }}>Response types</h2>
          <div className="spacer" />
          <button className="btn ghost sm" onClick={downloadJson}>⭳ Download JSON (backup)</button>
        </div>
        <div className="card" style={{ padding: 12, marginBottom: 12 }}>
          <label style={{ fontSize: 12.5, fontWeight: 600 }}>Paste Reply Format JSON</label>
          <p style={{ fontSize: 12, color: "var(--muted)", margin: "3px 0 4px" }}>
            <b>Add to existing</b> merges the pasted intents in (by id) and keeps everything you already have —
            use this to add new intent spaces. <b>Replace</b> overwrites the sections (asks first). Download a
            backup above before big changes.</p>
          <textarea rows={3} style={{ width: "100%", fontFamily: "monospace", fontSize: 12, marginTop: 4 }} value={pasteJson} onChange={(e) => setPasteJson(e.target.value)} placeholder='{"response_types":[{"id":"positive_simple","intent":"…","examples":["…"],"auto_send":true,"template":"…"}],"followups":[]}' />
          <div className="toolbar" style={{ marginTop: 6 }}>
            <button className="btn sm" onClick={addFromJson}>+ Add to existing</button>
            <button className="btn ghost sm" onClick={fillFromJson}>Replace sections</button>
          </div>
        </div>
        <ResponseTypes items={rf.response_types || []} onChange={(v) => setRf({ response_types: v })} />
      </div>

      <div className="section">
        <h2>Follow-up formats (FUP1–FUP6)</h2>
        <Followups items={rf.followups || []} onChange={(v) => setRf({ followups: v })} />
      </div>

      <div className="section">
        <h2>Reply Rules</h2>
        <p style={{ color: "var(--muted)", fontSize: 13, margin: "0 0 10px", lineHeight: 1.5 }}>
          Plain-English rules, one per line. Every line is a <b>mandatory override</b> obeyed on every reply
          and follow-up — just like the enrichment Rules. Use it to fix recurring mistakes without touching
          anything else. Examples: "Avoid em dashes — use commas or periods.", "Never propose meetings on
          Mondays.", "Keep replies under 90 words.", "Do not mention pricing in email; steer to a call.",
          "No emojis."
        </p>
        <textarea rows={8} style={{ width: "100%" }} value={w.ai_rules}
                  onChange={(e) => set("ai_rules", e.target.value)}
                  placeholder={"Avoid em dashes — use commas or periods.\nKeep replies short and specific.\nNever propose meetings on Mondays.\nDo not mention pricing in email; steer to a call."} />
      </div>

      <div className="toolbar" style={{ marginTop: 16 }}>
        <div className="spacer" />
        <button className="btn" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save all"}</button>
      </div>
    </div>
  );
}
