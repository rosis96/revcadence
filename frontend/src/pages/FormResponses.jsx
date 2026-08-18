import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { api, localDate, localDateTime } from "../api";
import { Button, Drawer, Empty, ErrorBox, SkeletonRows, StatusPill, useApi, useToast } from "../components";
import { RichText } from "../forms/richtext";

const TONES = { sent: "blue", opened: "blue", partial: "amber", submitted: "green", expired: "red" };

export default function FormResponses() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data: form } = useApi(`/api/forms/${id}`);
  const { data, loading, error, reload } = useApi(`/api/forms/${id}/responses`);
  const [open, setOpen] = useState(null);

  return (
    <div className="forms-page">
      <div className="forms-responses-head"><Button variant="ghost" icon={ArrowLeft} onClick={() => nav(`/forms/${id}/edit`)}>Builder</Button>
        <div><span className="forms-kicker">Responses</span><h1>{form?.name || "Form responses"}</h1><p>Submission progress and mapped client-supplied answers.</p></div></div>
      {error && <ErrorBox msg={error} retry={reload} />}
      {loading ? <div className="surface"><table className="dt"><tbody><SkeletonRows cols={6} rows={6} /></tbody></table></div>
        : data?.length === 0 ? <Empty icon="◎" title="No invites yet" hint="Publish the form and send it to a client." />
        : <div className="surface forms-table-surface"><table className="dt">
          <thead><tr><th>Recipient</th><th>Status</th><th>Sent</th><th>Submitted</th><th>Completion</th><th>Version</th></tr></thead>
          <tbody>{(data || []).map((row) => (
            <tr key={row.invite_id} className={row.response_id ? "click" : ""} onClick={() => row.response_id && setOpen(row.response_id)}>
              <td><b>{row.recipient_name || row.recipient_email}</b>{row.recipient_name && <div className="forms-row-sub">{row.recipient_email}</div>}</td>
              <td><StatusPill tone={TONES[row.status] || "gray"}>{row.status}</StatusPill></td>
              <td>{localDate(row.sent_at)}</td><td>{row.submitted_at ? localDate(row.submitted_at) : "—"}</td>
              <td><div className="forms-completion"><span><i style={{ width: `${row.completion}%` }} /></span><b>{row.completion}%</b></div></td>
              <td>{row.response_version ? `Response ${row.response_version}` : "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>}
      <AnimatePresence>
      {open && <ResponseDrawer key="resp" id={open} onClose={() => setOpen(null)} toast={toast} />}
      </AnimatePresence>
    </div>
  );
}

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return value.name || JSON.stringify(value);
  return String(value);
}

function ResponseDrawer({ id, onClose, toast }) {
  const { data, loading, error, reload } = useApi(`/api/forms/responses/${id}`);
  const [busy, setBusy] = useState(false);
  const rerun = async () => {
    setBusy(true);
    try { const result = await api(`/api/forms/responses/${id}/apply-mappings`, { method: "POST" }); toast(`Mappings complete · ${result.applied} applied${result.skipped ? ` · ${result.skipped} skipped` : ""}`); reload(); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  return (
    <Drawer title={data ? (data.recipient_name || data.recipient_email) : "Response"} onClose={onClose} className="forms-response-drawer">
      {loading && <div className="forms-drawer-loading">Loading response…</div>}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && <>
        <div className="forms-response-meta"><StatusPill tone={TONES[data.status] || "gray"}>{data.status}</StatusPill><span>Form v{data.form_version}</span><span>Response {data.response_version}</span></div>
        {data.submitted_at && <p className="forms-response-date">Submitted {localDateTime(data.submitted_at)}</p>}
        <section className="forms-response-details"><h3>Contact details</h3>{Object.entries(data.contact_details || {}).map(([key, value]) => (
          <div key={key}><span>{key}</span><b>{value || "—"}</b></div>
        ))}</section>
        <div className="forms-answer-list">{data.answers.map((answer) => (
          <article key={answer.question_id} className="forms-answer">
            <div className="forms-answer-head"><RichText text={answer.label} /><div><em>client_supplied</em>
              {answer.engagement && <StatusPill tone={answer.engagement === "edited" ? "blue" : "gray"}>{answer.engagement}</StatusPill>}</div></div>
            <p>{displayValue(answer.value)}</p>{answer.maps_to && <small>Maps to {answer.maps_to}</small>}
          </article>
        ))}</div>
        <div className="forms-drawer-actions"><Button icon={RefreshCw} loading={busy} onClick={rerun}>Re-run mappings</Button></div>
      </>}
    </Drawer>
  );
}
