// Client Space · Setup · Onboarding Form. Internal.
//
// Deliberately narrow: send the form to THIS client, and read what came back.
// Building forms is org-level work on an asset we own and lives under SYSTEM — a
// builder inside a client-scoped module would imply the form belongs to that
// client, which is how one client's questions end up in another's workspace.
//
// This screen is in the internal zone of Client Space, the same way a page in
// Docs can be internal. A client never sees it in their sidebar and the server
// refuses them the URL. Their side of this is the form itself, waiting on their
// dashboard as an open task.
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, ClipboardList, ExternalLink, Send } from "lucide-react";
import { api, localDate } from "../../api";
import { useAuth } from "../../auth";
import {
  Button, EmptyState, ErrorBox, Input, Row, RowCard, Select, Skeleton, StatusPill, useToast,
} from "../../components";

const TONE = { submitted: "green", partial: "blue", opened: "blue", sent: "amber", expired: "red" };

export default function OnboardingForm() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [formId, setFormId] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");

  const load = useCallback(() => {
    setError("");
    api("/api/client-space/onboarding-form", { params: { workspace_id: wsParam } })
      .then((d) => { setData(d); setFormId((prev) => prev || String(d.forms?.[0]?.id || "")); })
      .catch((e) => setError(e.message));
  }, [wsParam]);
  useEffect(() => { load(); }, [load]);

  const send = async () => {
    setSending(true);
    try {
      await api(`/api/forms/${formId}/invites`, {
        method: "POST", body: { workspace_id: Number(wsParam), email, name },
      });
      setEmail(""); setName("");
      toast("Onboarding form sent");
      load();
    } catch (e) { toast(e.message, "bad"); }
    finally { setSending(false); }
  };

  if (error) return <ErrorBox msg={error} retry={load} />;
  if (!data) return <div className="card" style={{ padding: 16 }}><Skeleton w="40%" /><Skeleton style={{ marginTop: 12 }} /></div>;
  if (!data.workspace) {
    return (
      <EmptyState icon={Building2} title="Choose a client"
        hint="An onboarding form is sent to one client. Pick a workspace in the switcher above." />
    );
  }

  const canSend = data.can_send;
  const invites = data.invites || [];
  const forms = data.forms || [];
  const sender = canSend && forms.length > 0 && (
    <div className="card cs-invite">
      <label>Form
        <Select value={formId} onChange={(e) => setFormId(e.target.value)}>
          {forms.map((f) => <option key={f.id} value={f.id}>{f.name} · {f.question_count} questions</option>)}
        </Select>
      </label>
      <label>Their email<Input type="email" value={email} placeholder="ops@acme.com"
        onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Their name<Input value={name} placeholder="Dana Ruiz" onChange={(e) => setName(e.target.value)} /></label>
      <Button icon={Send} loading={sending} disabled={!formId || !email.trim()} onClick={send}>
        {invites.length ? "Send again" : "Send form"}
      </Button>
    </div>
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Onboarding Form</h1>
          <p>Send this client their onboarding form and read what comes back.
            The client does not see this screen.</p>
        </div>
      </div>

      {sender}

      {invites.length === 0 ? (
        <EmptyState icon={ClipboardList} title="No onboarding form sent yet"
          hint={forms.length
            ? "Send this client the form above; their answers land on this screen as they submit."
            : "No published form exists yet. Build one under SYSTEM → Forms, publish it, then send it from here."}
          action={!forms.length
            ? <Button icon={ExternalLink} onClick={() => nav("/forms")}>Go to Forms</Button>
            : null} />
      ) : (
        <div className="cc-grid">
          <RowCard title="Sent" count={invites.length} className="span2" empty="Nothing sent yet.">
            {invites.map((i) => (
              <Row key={i.id} title={i.recipient_name || i.recipient_email}
                sub={`${i.form_name}${i.sent_at ? ` · sent ${localDate(i.sent_at)}` : ""}${
                  i.submitted_at ? ` · submitted ${localDate(i.submitted_at)}` : ""}`}
                right={<StatusPill tone={TONE[i.status] || "gray"}>{i.status}</StatusPill>}
                onClick={i.response_id ? () => nav(`/forms/${i.form_id}/responses`) : undefined} />
            ))}
          </RowCard>
        </div>
      )}
    </>
  );
}
