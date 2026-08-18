/* The form builder.

   A single centred column of cards, the way Google Forms edits a form: the header
   card, then one card per question, and the card you are working in is the editor
   for that question. Nothing lives in a side panel — the split-panel model this
   replaced kept the structure and the fields in two places, which meant reading
   both to understand one question.

   Two invariants hold the whole screen together:

   · The canvas order is the published order. A question's section comes from the
     header above it, and useFormBuilder writes that back, so what an operator
     arranges here is exactly what FormFields renders for the client.

   · One card is active. It owns the type dropdown, the option editor, the footer,
     the ⋮ menu, and the floating add rail. Everything else is collapsed to a
     preview of the control the client will see. */
import { useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronRight, CopyPlus, Eye, FileText, Mail, Send } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, ErrorBox, Input, Modal, SaveIndicator, Select, Spinner,
  useToast } from "../components";
import { AddRail } from "../forms/builder/AddRail";
import { ImportQuestions } from "../forms/builder/ImportQuestions";
import { QuestionCard, SectionCard } from "../forms/builder/QuestionCard";
import { RichTitle } from "../forms/builder/RichTitle";
import { keyOf, useFormBuilder } from "../forms/builder/useFormBuilder";

export default function FormBuilder() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { me } = useAuth();
  const builder = useFormBuilder(id, { onDuplicated: (made) => nav(`/forms/${made.id}/edit`) });
  const { form, items, active, setActive, focus, clearFocus, requestFocus } = builder;

  /* The drag lives in a ref as well as in state: state is what draws the drop
     line, but the drop handler must not depend on a re-render having landed
     between dragstart and drop. */
  const [drag, setDrag] = useState(null);          // { key, overKey, edge }
  const dragRef = useRef(null);
  const [importOpen, setImportOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState({ email: "", name: "", workspace_id: "" });
  const [inviting, setInviting] = useState(false);

  if (builder.loadError) return <ErrorBox msg={builder.loadError} retry={builder.reload} />;
  if (builder.loading || !form) return <Spinner />;

  const headerActive = active?.kind === "form";
  /* With nothing selected the rail sits beside the header card, which is also
     where a new question would be inserted — the button and its effect agree. */
  const railKey = active && active.kind !== "form" ? `${active.kind}:${active.id}` : "form";
  const sectionNumbers = new Map();
  items.filter((item) => item.kind === "section")
    .forEach((item, index) => sectionNumbers.set(item.id, index + 1));

  const endDrag = () => { dragRef.current = null; setDrag(null); };
  const dragProps = (item) => {
    const key = keyOf(item);
    return {
      dragging: drag?.key === key,
      dropEdge: drag && drag.key !== key && drag.overKey === key ? drag.edge : null,
      onDragStart: () => { dragRef.current = { key, overKey: null, edge: null }; setDrag(dragRef.current); },
      onDragOver: (edge) => {
        const current = dragRef.current;
        if (!current || (current.overKey === key && current.edge === edge)) return;
        dragRef.current = { ...current, overKey: key, edge };
        setDrag(dragRef.current);
      },
      onDrop: () => {
        const current = dragRef.current;
        if (current && current.key !== key) builder.moveCard(current.key, key, current.edge || "after");
        endDrag();
      },
      onDragEnd: endDrag,
    };
  };

  const rail = (
    <AddRail
      disabled={builder.busy === "add"}
      onAddQuestion={() => builder.addQuestion("short_text")}
      onImport={() => setImportOpen(true)}
      onAddTitleBlock={() => builder.addSection({ focusField: "title" })}
      onAddSection={() => builder.addSection()}
    />
  );

  const sendInvite = async () => {
    setInviting(true);
    try {
      await api(`/api/forms/${id}/invites`, { method: "POST", body: {
        workspace_id: Number(invite.workspace_id), email: invite.email, name: invite.name,
      } });
      toast("Invite queued for sending");
      setInviteOpen(false);
      setInvite({ email: "", name: "", workspace_id: "" });
    } catch (e) { toast(e.message, "bad"); }
    setInviting(false);
  };

  return (
    <div className="forms-builder-shell">
      <header className="forms-builder-top">
        <div className="forms-builder-title">
          <button className="forms-back" onClick={() => nav("/forms")}>Forms</button>
          <ChevronRight size={14} />
          <Input value={form.name} aria-label="Form name"
            onChange={(event) => builder.updateForm({ name: event.target.value })} />
        </div>
        <div className="forms-builder-actions">
          <SaveIndicator state={builder.saveState} />
          <Badge tone={form.status === "published" ? "green" : "amber"}>{form.status} · v{form.version}</Badge>
          <Button variant="ghost" icon={CopyPlus} loading={builder.busy === "duplicate"}
            onClick={builder.duplicateForm}>Duplicate</Button>
          <Button variant="secondary" icon={Eye} onClick={() => nav(`/forms/${id}/preview`)}>Preview</Button>
          <Button variant="secondary" icon={FileText} onClick={() => nav(`/forms/${id}/responses`)}>Responses</Button>
          {form.status === "published"
            ? <Button icon={Mail} onClick={() => setInviteOpen(true)}>Send</Button>
            : <Button icon={Send} loading={builder.busy === "publish"} onClick={builder.publish}>Publish</Button>}
        </div>
      </header>

      <div className="gf-canvas">
        <div className="gf-stack">
          <div className="gf-slot">
            <FormHeaderCard form={form} active={headerActive}
              onActivate={() => setActive({ kind: "form", id: 0 })}
              onPatch={builder.updateForm} />
            {railKey === "form" && rail}
          </div>

          {items.map((item) => {
            const key = keyOf(item);
            const isActive = builder.isActive(item);
            const shared = {
              item, active: isActive, focus, clearFocus, requestFocus,
              onActivate: () => setActive({ kind: item.kind, id: item.id }),
              onDuplicate: () => builder.duplicateCard(item),
              onRemove: () => builder.removeCard(item),
              ...dragProps(item),
            };
            return (
              <div key={key} className="gf-slot">
                {item.kind === "question" ? (
                  <QuestionCard {...shared}
                    sections={form.sections} mapTargets={form.map_targets} prefillSources={form.prefill_sources}
                    onPatch={(patch) => builder.updateQuestion(item.id, patch)}
                    onMoveToSection={(sectionId) => builder.moveToSection(item.data, sectionId)}
                    onAddBelow={() => builder.addQuestion(item.data.type)} />
                ) : (
                  <SectionCard {...shared}
                    index={sectionNumbers.get(item.id)} total={sectionNumbers.size}
                    onPatch={(patch) => builder.updateSection(item.id, patch)} />
                )}
                {railKey === key && rail}
              </div>
            );
          })}

          {items.length === 0 && (
            <button type="button" className="gf-empty" onClick={() => builder.addQuestion("short_text")}>
              Add your first question
            </button>
          )}
        </div>
      </div>

      <AnimatePresence>
        {importOpen && (
          <ImportQuestions key="import" formId={id} busy={builder.busy}
            onClose={() => setImportOpen(false)} onImport={builder.importQuestions} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {inviteOpen && (
          <Modal key="invite" title="Send form" onClose={() => setInviteOpen(false)}>
            <p className="forms-modal-copy">
              The client receives a short plain-text email with a private link that expires in 30 days.
            </p>
            {/* The form belongs to the org, so the client is chosen here — at send time. */}
            <div className="field"><label>Client workspace</label>
              <Select value={invite.workspace_id}
                onChange={(event) => setInvite({ ...invite, workspace_id: event.target.value })}>
                <option value="">Choose a client</option>
                {(me.workspaces || []).map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
                ))}
              </Select></div>
            <div className="field"><label>Name</label>
              <Input value={invite.name} placeholder="Client name"
                onChange={(event) => setInvite({ ...invite, name: event.target.value })} /></div>
            <div className="field"><label>Email</label>
              <Input type="email" value={invite.email} placeholder="client@company.com"
                onChange={(event) => setInvite({ ...invite, email: event.target.value })} /></div>
            <div className="actions">
              <Button variant="ghost" onClick={() => setInviteOpen(false)}>Cancel</Button>
              <Button icon={Mail} loading={inviting} disabled={!invite.email || !invite.workspace_id}
                onClick={sendInvite}>Queue invite</Button>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

/* The form's own card. Its title and description carry no formatting toolbar: the
   name reaches invite subject lines and the forms list as a plain string, and
   markers would surface there as literal asterisks. Question and section copy is
   only ever rendered through FormFields, which does render them. */
function FormHeaderCard({ form, active, onActivate, onPatch }) {
  return (
    <article className={`gf-card gf-header ${active ? "active" : ""}`}
      onMouseDown={() => !active && onActivate()}
      onFocusCapture={() => !active && onActivate()}>
      <span className="gf-header-band" aria-hidden />
      <RichTitle className="gf-form-title" value={form.name || ""} placeholder="Untitled form"
        ariaLabel="Form title" active={active} readWhenIdle={false}
        onChange={(value) => onPatch({ name: value })} />
      <RichTitle className="gf-form-desc" value={form.description || ""} placeholder="Form description"
        ariaLabel="Form description" active={active} readWhenIdle={false} multiline
        onChange={(value) => onPatch({ description: value })} />
    </article>
  );
}
