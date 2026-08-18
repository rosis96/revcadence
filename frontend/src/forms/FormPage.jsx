// The onboarding form — one page, reached two ways.
//
// The client meets it first through a link in an email, days before they have an
// account, and later from their own dashboard once they do. Those are two
// credentials, not two pages: the only thing that differs below is `transport`,
// which is four URLs. Everything after it — restore, autosave, validation,
// submit, the thank-you — is shared, because a forked "public version" is how
// the two drift until one of them quietly stops saving.
//
// It renders inside the client's own space rather than as a standalone
// microsite. This is often the first screen they ever see of it, and a detached
// branded form page would teach them the wrong thing about where their work
// lives. On the token route the surrounding shell is deliberately inert: it
// draws the space's name and nothing else, and fetches no documents, prospects
// or sequences — the one unauthenticated route in the product loads the invite
// and the form, full stop.
import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Send } from "lucide-react";
import { useParams } from "react-router-dom";
import { API_BASE, api, getToken } from "../api";
import { Button, SaveIndicator } from "../components";
import FormFields, { isAnswered } from "./FormFields";

const DETAIL_KEYS = {
  "invite.contact_name": "name", "invite.contact_email": "email",
  "invite.company_name": "company", "invite.website_url": "website",
};

// The only difference between the two ways in.
function transportFor(token) {
  if (token) {
    const base = `/api/public/forms/${token}`;
    return {
      standalone: true,
      load: () => api(base, { auth: false }),
      save: (body) => api(`${base}/save`, { method: "POST", body, auth: false }),
      submit: (body) => api(`${base}/submit`, { method: "POST", body, auth: false }),
      upload: (data) => fetch(`${API_BASE}${base}/upload`, { method: "POST", body: data }),
    };
  }
  const base = "/api/client-space/onboarding-form/fill";
  return {
    standalone: false,
    load: () => api(base),
    save: (body) => api(`${base}/save`, { method: "POST", body }),
    submit: (body) => api(`${base}/submit`, { method: "POST", body }),
    upload: (data) => fetch(`${API_BASE}${base}/upload`, {
      method: "POST", body: data, credentials: "include",
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    }),
  };
}

export default function FormPage() {
  const { token } = useParams();
  const transport = useMemo(() => transportFor(token), [token]);
  const [schema, setSchema] = useState(null);
  const [spaceName, setSpaceName] = useState("");
  const [answers, setAnswers] = useState({});
  const [details, setDetails] = useState({});
  const [edited, setEdited] = useState(new Set());
  const [errors, setErrors] = useState({});
  const [loadState, setLoadState] = useState("loading");
  const [saveState, setSaveState] = useState("idle");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [uploading, setUploading] = useState(null);
  // Autosave fires on blur, after the field it is saving has already moved on.
  // Reading state through a ref means it saves what is on screen now rather than
  // whatever the closure captured when the handler was created.
  const latest = useRef({ answers: {}, details: {}, edited: new Set() });

  useEffect(() => {
    let cancelled = false;
    transport.load().then((result) => {
      if (cancelled) return;
      // What we already know is shown as the starting value, so nothing they
      // have already told us — or that we read off their site — comes back to
      // them as an empty box.
      const restored = { ...(result.answers || {}) };
      for (const question of result.form?.questions || []) {
        if (restored[question.id] === undefined && question.prefill_value !== undefined) {
          restored[question.id] = question.prefill_value;
        }
      }
      setSchema(result.form);
      setSpaceName(result.space_name || "");
      setAnswers(restored);
      setDetails(result.details || {});
      setEdited(new Set(result.edited_question_ids || []));
      setDone((result.status || "") === "submitted");
      setLoadState("ready");
    }).catch(() => { if (!cancelled) setLoadState("invalid"); });
    return () => { cancelled = true; };
  }, [transport]);
  useEffect(() => { latest.current = { answers, details, edited }; }, [answers, details, edited]);

  const bodyQuestions = useMemo(
    () => (schema?.questions || []).filter((question) => !question.contact_detail), [schema]);
  const answered = bodyQuestions
    .filter((question) => isAnswered(answers[question.id] ?? question.prefill_value)).length;

  const payload = () => ({
    answers: latest.current.answers, details: latest.current.details,
    edited_question_ids: [...latest.current.edited],
  });

  const save = async () => {
    if (!schema || done) return;
    setSaveState("saving");
    try {
      await transport.save(payload());
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 1800);
    } catch { setSaveState("error"); }
  };

  // `userEdited` is the difference between an answer they actually touched and
  // one they confirmed by clicking past it. An operator reading the response
  // needs to know which pre-filled answers were genuinely checked.
  const setAnswer = (questionId, value, userEdited = false) => {
    const nextAnswers = { ...latest.current.answers, [questionId]: value };
    const nextEdited = userEdited
      ? new Set([...latest.current.edited, questionId]) : latest.current.edited;
    latest.current = { ...latest.current, answers: nextAnswers, edited: nextEdited };
    setAnswers(nextAnswers);
    if (userEdited) setEdited(nextEdited);
    setErrors((current) => { const next = { ...current }; delete next[questionId]; return next; });
  };

  const updateDetails = (nextDetails) => {
    latest.current = { ...latest.current, details: nextDetails };
    setDetails(nextDetails);
  };

  const upload = async (question, file) => {
    setUploading(question.id);
    const data = new FormData();
    data.append("question_id", String(question.id));
    data.append("file", file);
    try {
      const response = await transport.upload(data);
      if (!response.ok) {
        let message = "Upload failed";
        try { message = (await response.json()).detail || message; } catch { /* empty */ }
        throw new Error(message);
      }
      setAnswer(question.id, await response.json(), true);
      setTimeout(save, 0);
    } catch (e) {
      setErrors((current) => ({ ...current, [question.id]: e.message }));
    }
    setUploading(null);
  };

  const submit = async () => {
    const missing = {};
    for (const question of schema.questions || []) {
      const detailKey = DETAIL_KEYS[question.prefill_source];
      const value = detailKey ? details[detailKey] : answers[question.id] ?? question.prefill_value;
      if (question.required && !isAnswered(value)) missing[question.id] = "This field is required.";
    }
    if (Object.keys(missing).length) {
      setErrors(missing);
      document.getElementById(`form-question-${Object.keys(missing)[0]}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setSubmitting(true); setErrors({});
    try {
      await transport.submit(payload());
      setDone(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) { setErrors({ form: e.message }); }
    setSubmitting(false);
  };

  const frame = (children) => <Shell standalone={transport.standalone} name={spaceName}>{children}</Shell>;

  if (loadState === "loading") {
    return frame(<div className="forms-public-loading"><div className="spinner" /></div>);
  }
  // One message for a token that never existed and one that has expired. Telling
  // them apart is exactly the signal that makes probing worthwhile.
  if (loadState === "invalid") {
    return frame(
      <main className="forms-public-card forms-neutral">
        <h1>This link is no longer valid</h1>
        <p>Please contact the person who sent it if you still need to complete the form.</p>
      </main>);
  }
  if (done) {
    return frame(
      <main className="forms-public-card forms-thanks">
        <span className="forms-thanks-icon"><CheckCircle2 size={26} /></span>
        <h1>Thank you</h1>
        <p>Your answers are in. We’ll build your launch from them and come back to you
          if anything needs clarifying — there is nothing else for you to do here.</p>
      </main>);
  }

  const percent = bodyQuestions.length
    ? Math.round(100 * answered / bodyQuestions.length) : 100;
  return frame(
    <main className="forms-public-card">
      <header className="forms-public-head">
        <h1>{schema.title}</h1>
        {schema.description && <p>{schema.description}</p>}
      </header>
      <div className="forms-progress-row">
        <span>{answered} of {bodyQuestions.length} answered</span>
        <SaveIndicator state={saveState} />
      </div>
      <div className="forms-progress"><i style={{ width: `${percent}%` }} /></div>
      {errors.form && <div className="error-box forms-submit-error">{errors.form}</div>}
      <FormFields schema={schema} answers={answers} setAnswer={setAnswer} details={details}
        setDetails={updateDetails} errors={errors} onBlur={save} onDetailsBlur={save}
        onUpload={uploading ? undefined : upload} />
      <div className="forms-public-submit">
        <Button icon={Send} loading={submitting} disabled={!!uploading} onClick={submit}>Submit</Button>
      </div>
      <p className="forms-public-foot">
        Your answers save as you go. You can close this page and pick up where you left off.
      </p>
    </main>);
}

// Inside the dashboard the shell is already there. On the token route there is
// no shell to be inside, so this draws the quietest possible stand-in: the name
// of their space and the page. It fetches nothing.
function Shell({ standalone, name, children }) {
  if (!standalone) return <div className="forms-fill-page">{children}</div>;
  return (
    <div className="forms-public-wrap">
      <div className="forms-fill-page">
        {name && <div className="forms-space-name">{name}</div>}
        {children}
      </div>
    </div>
  );
}
