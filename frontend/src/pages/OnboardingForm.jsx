// Public client onboarding form (no login). Premium, sectioned, save-draft or
// submit. On submit the backend auto-wires the workspace.
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, Save, Send } from "lucide-react";
import { api } from "../api";

export default function OnboardingForm() {
  const { token } = useParams();
  const [schema, setSchema] = useState(null);
  const [vals, setVals] = useState({});
  const [wsName, setWsName] = useState("");
  const [status, setStatus] = useState("draft");
  const [secretSet, setSecretSet] = useState({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [flash, setFlash] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    api(`/api/onboarding/form/${token}`).then((r) => {
      setSchema(r.form); setVals(r.data || {}); setWsName(r.workspace_name);
      setStatus(r.status); setSecretSet(r.secret_set || {});
      if (r.status === "submitted") setDone(true);
    }).catch((e) => setError(e.message));
  }, [token]);

  const set = (k, v) => setVals((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setBusy("save"); setFlash("");
    try { await api(`/api/onboarding/form/${token}/save`, { method: "POST", body: { data: vals } }); setFlash("Draft saved — you can come back anytime."); }
    catch (e) { setError(e.message); }
    setBusy("");
  };
  const submit = async () => {
    setBusy("submit"); setError("");
    try { await api(`/api/onboarding/form/${token}/submit`, { method: "POST", body: { data: vals } }); setDone(true); }
    catch (e) { setError(e.message); }
    setBusy("");
  };

  if (error && !schema) return <div className="ob-wrap"><div className="ob-card"><div className="error-box">{error}</div></div></div>;
  if (!schema) return <div className="ob-wrap"><div className="center"><div className="spinner" /></div></div>;

  if (done) return (
    <div className="ob-wrap">
      <div className="ob-card ob-done">
        <div className="ei" style={{ margin: "0 auto 16px" }}><CheckCircle2 size={26} /></div>
        <h1>You're all set 🎉</h1>
        <p>Thanks{vals.contact_name ? `, ${vals.contact_name.split(" ")[0]}` : ""}. We've received everything for
          <b> {wsName}</b> and our team is setting up your revenue system. No further action needed — we'll be in touch.</p>
      </div>
    </div>
  );

  const field = (f) => {
    const v = vals[f.key] ?? (f.type === "toggle" ? f.default : "");
    if (f.type === "toggle") return (
      <label className="ob-toggle"><input type="checkbox" checked={!!v} onChange={(e) => set(f.key, e.target.checked)} /><span /> {f.label}</label>
    );
    return (
      <div className="ob-field" key={f.key}>
        <label>{f.label}{f.required && <em>*</em>}</label>
        {f.type === "textarea"
          ? <textarea rows={3} value={v} placeholder={f.placeholder || "Enter text"} onChange={(e) => set(f.key, e.target.value)} />
          : <input type={f.type === "password" ? "password" : f.type === "email" ? "email" : "text"}
              value={v} placeholder={f.secret && secretSet[f.key] ? "•••••••• (saved — leave blank to keep)" : (f.placeholder || "Enter text")}
              onChange={(e) => set(f.key, e.target.value)} />}
        {f.hint && <div className="ob-hint">{f.hint}</div>}
      </div>
    );
  };

  return (
    <div className="ob-wrap">
      <div className="ob-card">
        <div className="ob-head">
          <div className="ob-mark">R</div>
          <div>
            <div className="ob-kicker">RevCadence onboarding{wsName ? ` · ${wsName}` : ""}</div>
            <h1>Let's set up your revenue system</h1>
            <p>A few details so we can run outbound, replies, meetings, and proposals for you — you'll only fill this once.</p>
          </div>
        </div>

        {error && <div className="error-box" style={{ margin: "0 0 16px" }}>{error}</div>}
        {flash && <div className="ob-flash">{flash}</div>}

        {schema.map((sec) => (
          <div className="ob-section" key={sec.section}>
            <h2>{sec.section}</h2>
            <div className="ob-grid">
              {sec.fields.map((f) => f.type === "toggle"
                ? <div key={f.key} style={{ gridColumn: "1 / -1" }}>{field(f)}</div>
                : <div key={f.key} style={{ gridColumn: f.type === "textarea" ? "1 / -1" : "auto" }}>{field(f)}</div>)}
            </div>
          </div>
        ))}

        <div className="ob-actions">
          <button className="hbtn ghost" disabled={!!busy} onClick={save}><Save size={16} /> {busy === "save" ? "Saving…" : "Save draft"}</button>
          <button className="hbtn primary" disabled={!!busy} onClick={submit}><Send size={16} /> {busy === "submit" ? "Submitting…" : "Submit"}</button>
        </div>
        <div className="ob-foot">Your credentials are encrypted. Powered by RevCadence.</div>
      </div>
    </div>
  );
}
