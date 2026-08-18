import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Archive, ArrowDown, ArrowUp, BadgeCheck, Check, ChevronRight, CircleAlert,
  ClipboardCopy, Eye, FileCheck2, FlaskConical, GripVertical, Library,
  Mail, Plus, Save, Send, Settings2, Sparkles, Trophy, X,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Area, Badge, Button, Drawer, EmptyState, ErrorBox, Input, PageHeader, SaveIndicator,
  Select, Spinner, StatusPill, useToast,
} from "../components";
import { moduleBase, path } from "../clientspace/nav";

// This screen is mounted under three bases (/sequences, /client-space/…, and the
// client's own /w/<slug>/…), so "go add proof" has to be resolved from the URL
// we are on. A hardcoded link here sent a client to another shell's Library.
const useLibraryLink = () => {
  const { me } = useAuth();
  const { pathname } = useLocation();
  return path(moduleBase(pathname, me?.role === "client"), "library");
};

const statusTone = { draft: "gray", in_review: "amber", changes_requested: "red", approved: "green" };
const prettyStatus = (value) => ({ in_review: "In review", changes_requested: "Changes requested" }[value] || value);
const purposeLabels = { opener: "Opener", bump: "Bump", new_angle: "New angle", breakup: "Breakup", follow_up: "Follow-up" };

function GeneratedCopy({ parts }) {
  return (
    <span className="seq-rendered-copy">
      {(parts || []).map((part, index) => part.kind === "literal"
        ? <span key={index}>{part.text}</span>
        : <mark key={index} className={`seq-generated ${part.missing ? "missing" : ""}`}
            title={`${part.token}${part.missing ? " is missing" : " is generated for this prospect"}`}>
            {part.text}
          </mark>)}
    </span>
  );
}

function Performance({ data }) {
  const p = data || {};
  return (
    <div className="seq-performance">
      <span><b>{p.sent || 0}</b><em>Sent</em></span>
      <span><b>{p.reply_rate || 0}%</b><em>Replies</em></span>
      <span><b>{p.positive_rate || 0}%</b><em>Positive</em></span>
      <span><b>{p.meetings || 0}</b><em>Meetings</em></span>
    </div>
  );
}

function QualityPanel({ quality }) {
  if (!quality?.checked_at && !quality?.stale) {
    return <div className="seq-quality neutral"><CircleAlert size={15} /> Run checks before enabling this variant.</div>;
  }
  if (quality.passed) {
    return <div className="seq-quality pass"><BadgeCheck size={15} /> Quality, banned phrase, placeholder, and evidence checks passed.</div>;
  }
  return (
    <div className="seq-quality fail">
      <div><CircleAlert size={15} /> {quality.stale ? "Copy changed. Run the checks again." : "This variant needs attention."}</div>
      {(quality.issues || []).map((issue, i) => (
        <div className="seq-quality-issue" key={`${issue.code}-${i}`}>
          {issue.message}
          {issue.link && <a href={`#${issue.link}`}>Add or fix it <ChevronRight size={12} /></a>}
        </div>
      ))}
    </div>
  );
}

function PreviewPane({ preview, loading, onClose }) {
  return (
    <aside className="seq-preview-pane">
      <div className="seq-preview-head">
        <div><b>Ten-prospect preview</b><span>{preview?.list?.name || "Current list"}</span></div>
        <Button variant="ghost" size="sm" icon={X} onClick={onClose}>Close</Button>
      </div>
      {loading && <Spinner />}
      {!loading && !preview?.prospects?.length && (
        <EmptyState icon={Eye} title="No prospects to preview"
          hint="Choose a list with imported prospects. RevCadence never fills this panel with sample people." />
      )}
      {(preview?.prospects || []).map((row, index) => (
        <article className="seq-preview-email" key={row.lead_id}>
          <header><span>{index + 1}</span><div><b>{row.prospect}</b><em>{row.company}</em></div></header>
          <div className="seq-preview-subject"><small>Subject</small><GeneratedCopy parts={row.subject_parts} /></div>
          <div className="seq-preview-body"><GeneratedCopy parts={row.body_parts} /></div>
          {!!row.missing?.length && <div className="seq-missing">Missing: {row.missing.join(", ")}</div>}
        </article>
      ))}
    </aside>
  );
}

function TemplateStart({ context, onCreate, busy }) {
  const libraryLink = useLibraryLink();
  const [template, setTemplate] = useState(context?.templates?.[0]?.key || "system:founder-four");
  const [name, setName] = useState("Client outreach");
  const [angle, setAngle] = useState("Primary angle");
  const [hypothesis, setHypothesis] = useState("");
  const [proof, setProof] = useState(context?.proof?.[0]?.key || "");
  useEffect(() => {
    if (!proof && context?.proof?.[0]?.key) setProof(context.proof[0].key);
  }, [context, proof]);
  return (
    <div className="seq-start">
      <div className="seq-start-copy">
        <Badge>Angle → sequence → emails → variants</Badge>
        <h2>Start with a useful four-email shape</h2>
        <p>The waits and roles are ready. Tie the angle to real client proof, then write and check each enabled variant.</p>
      </div>
      <div className="seq-template-grid">
        {(context?.templates || []).map((item) => (
          <button key={item.key} className={`seq-template-card ${template === item.key ? "selected" : ""}`}
            onClick={() => setTemplate(item.key)}>
            <span className="seq-template-icon"><Mail size={18} /></span>
            <b>{item.name}</b><p>{item.description}</p>
            <span>{item.system ? "RevCadence template" : "Saved template"}</span>
          </button>
        ))}
      </div>
      <div className="card seq-start-fields">
        <label>Sequence name<Input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Angle name<Input value={angle} onChange={(e) => setAngle(e.target.value)} /></label>
        <label className="wide">Hypothesis<Input value={hypothesis} onChange={(e) => setHypothesis(e.target.value)}
          placeholder="Why this angle should earn a reply" /></label>
        <label className="wide">Proof from the client library
          <Select value={proof} onChange={(e) => setProof(e.target.value)} placeholder="Choose specific proof">
            {(context?.proof || []).map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </Select>
          {!context?.proof?.length && <span className="seq-field-note">No case study exists yet. <Link to={libraryLink}>Add proof in the client library.</Link></span>}
        </label>
        <div className="wide seq-start-action">
          <Button icon={Plus} loading={busy} disabled={!name.trim()}
            onClick={() => onCreate({ name, angle_name: angle, hypothesis, proof_key: proof, template_key: template })}>
            Create sequence
          </Button>
        </div>
      </div>
    </div>
  );
}

function VariantEditor({ variant, step, context, onReload, onLocalVariant, onPreview }) {
  const toast = useToast();
  const [draft, setDraft] = useState(variant);
  const [saving, setSaving] = useState("idle");
  const [checking, setChecking] = useState(false);
  const [formatOpen, setFormatOpen] = useState(null);
  const [formatDraft, setFormatDraft] = useState(null);
  const activeField = useRef("body");
  const first = useRef(true);
  useEffect(() => { setDraft(variant); first.current = true; }, [variant?.id]);
  useEffect(() => {
    if (!draft || first.current) { first.current = false; return undefined; }
    setSaving("saving");
    const timer = setTimeout(async () => {
      try {
        const updated = await api(`/api/sequences/variants/${draft.id}`, {
          method: "PATCH", body: { subject: draft.subject, body: draft.body, change_note: draft.change_note },
        });
        setDraft(updated); onLocalVariant(updated); setSaving("saved");
      } catch (e) { setSaving("error"); toast(e.message, "error"); }
    }, 800);
    return () => clearTimeout(timer);
  }, [draft?.subject, draft?.body, draft?.change_note]);

  const runQuality = async () => {
    setChecking(true);
    try {
      const quality = await api(`/api/sequences/variants/${draft.id}/quality`, { method: "POST" });
      const next = { ...draft, quality }; setDraft(next); onLocalVariant(next);
      toast(quality.passed ? "Variant passed every send check" : "The checks found copy to fix", quality.passed ? "ok" : "error");
    } catch (e) { toast(e.message, "error"); }
    finally { setChecking(false); }
  };
  const toggleEnabled = async () => {
    try {
      const updated = await api(`/api/sequences/variants/${draft.id}`, {
        method: "PATCH", body: { enabled: !draft.enabled },
      });
      setDraft(updated); onLocalVariant(updated);
      toast(updated.enabled ? `Variant ${updated.label} is in rotation` : `Variant ${updated.label} is out of rotation`);
    } catch (e) {
      const quality = e.detail?.quality;
      if (quality) { const next = { ...draft, quality }; setDraft(next); onLocalVariant(next); }
      toast(e.message, "error");
    }
  };
  const insertToken = (name) => {
    const key = activeField.current || "body";
    setDraft((old) => ({ ...old, [key]: `${old[key] || ""}{{${name}}}` }));
  };
  const openFormat = (fmt) => { setFormatOpen(fmt); setFormatDraft({ ...fmt }); };
  const saveFormat = async () => {
    try {
      await api(`/api/sequences/formats/${context.workspaceId}/${formatDraft.name}`, {
        method: "PATCH", body: { guidance: formatDraft.guidance, template: formatDraft.template },
      });
      toast("Shared format definition updated everywhere"); setFormatOpen(null); onReload();
    } catch (e) { toast(e.message, "error"); }
  };
  if (!draft) return null;
  return (
    <div className="seq-variant-editor">
      <div className="seq-editor-toolbar">
        <div>
          <Badge>Variant {draft.label}</Badge>
          {draft.promoted && <Badge tone="green"><Trophy size={12} /> Winner</Badge>}
          {draft.archived && <Badge>Archived</Badge>}
          {draft.enabled ? <StatusPill tone="green">Enabled</StatusPill> : <StatusPill tone="gray">Disabled</StatusPill>}
        </div>
        <div><SaveIndicator state={saving} /><Button size="sm" variant="ghost" icon={Eye} onClick={onPreview}>Preview</Button></div>
      </div>
      {draft.label !== "A" && (
        <label className="seq-field">What changed from the control?
          <Input value={draft.change_note || ""} readOnly={draft.archived} onFocus={() => { activeField.current = "change_note"; }}
            onChange={(e) => setDraft((old) => ({ ...old, change_note: e.target.value }))}
            placeholder="One line, for example: leads with proof instead of the observation" />
        </label>
      )}
      <label className="seq-field">Subject
        <Input value={draft.subject || ""} readOnly={draft.archived} onFocus={() => { activeField.current = "subject"; }}
          onChange={(e) => setDraft((old) => ({ ...old, subject: e.target.value }))} />
      </label>
      <label className="seq-field">Plain-text email
        <Area size="lg" value={draft.body || ""} readOnly={draft.archived} onFocus={() => { activeField.current = "body"; }}
          onChange={(e) => setDraft((old) => ({ ...old, body: e.target.value }))} />
      </label>
      {!draft.archived && <div className="seq-placeholder-box">
        <div><b>Generated formats</b><span>Shared definitions; click the gear to edit the one source.</span></div>
        <div className="seq-placeholder-list">
          {(context.formats || []).filter((f) => f.enabled).map((fmt) => (
            <span className="seq-placeholder" key={fmt.name}>
              <button onClick={() => insertToken(fmt.name)}>{`{{${fmt.name}}}`}</button>
              <button aria-label={`Edit ${fmt.label}`} title={`Edit ${fmt.label}`} onClick={() => openFormat(fmt)}><Settings2 size={12} /></button>
            </span>
          ))}
        </div>
        <div><b>Prospect fields</b></div>
        <div className="seq-placeholder-list core">
          {(context.core_placeholders || []).map((fmt) => (
            <button className="seq-placeholder core" key={fmt.name} onClick={() => insertToken(fmt.name)}>{`{{${fmt.name}}}`}</button>
          ))}
        </div>
      </div>}
      <QualityPanel quality={draft.quality} />
      {!draft.archived && <div className="seq-editor-actions">
        <Button variant="secondary" icon={FlaskConical} loading={checking} onClick={runQuality}>Run send checks</Button>
        <Button variant={draft.enabled ? "ghost" : "primary"} icon={draft.enabled ? X : Check} onClick={toggleEnabled}>
          {draft.enabled ? "Disable variant" : "Enable variant"}
        </Button>
        <span className="seq-action-spacer" />
        <Button variant="ghost" size="sm" icon={Trophy}
          onClick={async () => { await api(`/api/sequences/variants/${draft.id}/promote`, { method: "POST" }); onReload(); }}>
          Promote winner
        </Button>
        <Button variant="ghost" size="sm" icon={Archive}
          onClick={async () => { await api(`/api/sequences/variants/${draft.id}/archive`, { method: "POST" }); onReload(); }}>
          Archive
        </Button>
      </div>}
      <Performance data={draft.performance} />
      <AnimatePresence>
      {formatOpen && (
        <Drawer key="fmt" title={`Shared format · ${formatOpen.label}`} onClose={() => setFormatOpen(null)}>
          <div className="seq-format-drawer">
            <p>This definition belongs to the workspace enrichment configuration. Saving here updates the same source used by every sequence and prospect.</p>
            <label>Writing guidance<Area size="lg" value={formatDraft.guidance || ""}
              onChange={(e) => setFormatDraft((old) => ({ ...old, guidance: e.target.value }))} /></label>
            <label>Fixed template<Input value={formatDraft.template || ""}
              onChange={(e) => setFormatDraft((old) => ({ ...old, template: e.target.value }))} /></label>
            <div className="actions"><Button variant="ghost" onClick={() => setFormatOpen(null)}>Cancel</Button>
              <Button icon={Save} onClick={saveFormat}>Save shared definition</Button></div>
          </div>
        </Drawer>
      )}
      </AnimatePresence>
    </div>
  );
}

function SequenceEditor({ sequence, context, onReload, onSequenceChange }) {
  const toast = useToast();
  const libraryLink = useLibraryLink();
  const [selectedStep, setSelectedStep] = useState(sequence.steps?.[0]?.id);
  const [selectedVariant, setSelectedVariant] = useState(sequence.steps?.[0]?.variants?.[0]?.id);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [approvalNote, setApprovalNote] = useState("");
  const [addingVariant, setAddingVariant] = useState(false);
  const [newVariantNote, setNewVariantNote] = useState("");
  const [dragged, setDragged] = useState(null);
  const seqTimer = useRef(null);
  useEffect(() => {
    const exists = sequence.steps?.some((s) => s.id === selectedStep);
    const nextStep = exists ? sequence.steps.find((s) => s.id === selectedStep) : sequence.steps?.[0];
    if (nextStep?.id !== selectedStep) setSelectedStep(nextStep?.id);
    if (!nextStep?.variants?.some((v) => v.id === selectedVariant)) setSelectedVariant(nextStep?.variants?.[0]?.id);
  }, [sequence.id, sequence.steps]);
  const step = sequence.steps?.find((item) => item.id === selectedStep) || sequence.steps?.[0];
  const variant = step?.variants?.find((item) => item.id === selectedVariant) || step?.variants?.[0];

  const seqPatch = (fields) => {
    onSequenceChange({ ...sequence, ...fields,
      angle: { ...sequence.angle,
        ...(fields.angle_name !== undefined ? { name: fields.angle_name } : {}),
        ...(fields.hypothesis !== undefined ? { hypothesis: fields.hypothesis } : {}),
        ...(fields.proof_key !== undefined ? { proof_key: fields.proof_key } : {}) } });
    clearTimeout(seqTimer.current);
    seqTimer.current = setTimeout(async () => {
      try { const updated = await api(`/api/sequences/${sequence.id}`, { method: "PATCH", body: fields }); onSequenceChange(updated); }
      catch (e) { toast(e.message, "error"); }
    }, 800);
  };
  const mutate = async (path, body) => {
    try { await api(path, { method: "POST", body }); await onReload(); }
    catch (e) { toast(e.message, "error"); }
  };
  const previewVariant = async () => {
    if (!variant) return;
    setPreviewLoading(true); setPreview({ prospects: [] });
    try {
      const data = await api(`/api/sequences/${sequence.id}/preview`, {
        params: { list_id: sequence.current_list_id, variant_id: variant.id },
      });
      setPreview(data);
    } catch (e) { toast(e.message, "error"); setPreview(null); }
    finally { setPreviewLoading(false); }
  };
  const moveStep = async (fromId, toId) => {
    if (!fromId || fromId === toId) return;
    const ids = sequence.steps.map((s) => s.id);
    const from = ids.indexOf(fromId), to = ids.indexOf(toId);
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    await api(`/api/sequences/${sequence.id}/steps/reorder`, { method: "POST", body: { ordered_ids: ids } });
    setDragged(null); onReload();
  };
  const patchStep = async (fields) => {
    await api(`/api/sequences/steps/${step.id}`, { method: "PATCH", body: fields }); onReload();
  };
  const updateLocalVariant = (updated) => {
    onSequenceChange({ ...sequence, steps: sequence.steps.map((s) => s.id === step.id
      ? { ...s, variants: s.variants.map((v) => v.id === updated.id ? updated : v) } : s) });
  };
  const addVariant = async () => {
    if (!newVariantNote.trim()) return;
    try {
      const made = await api(`/api/sequences/steps/${step.id}/variants`, {
        method: "POST", body: { from_variant_id: variant?.id, change_note: newVariantNote.trim() },
      });
      setAddingVariant(false); setNewVariantNote(""); await onReload(); setSelectedVariant(made.id);
    } catch (e) { toast(e.message, "error"); }
  };
  const selectedProof = (context.proof || []).find((p) => p.key === sequence.angle.proof_key);
  return (
    <div className={`seq-workbench ${preview || previewLoading ? "with-preview" : ""}`}>
      <section className="seq-builder">
        <div className="seq-summary card">
          <div className="seq-title-row">
            <div className="seq-title-input">
              <Input value={sequence.name} onChange={(e) => seqPatch({ name: e.target.value })} aria-label="Sequence name" />
              <Input value={sequence.description || ""} onChange={(e) => seqPatch({ description: e.target.value })}
                placeholder="A short description for the client" aria-label="Sequence description" />
            </div>
            <StatusPill tone={statusTone[sequence.status]}>{prettyStatus(sequence.status)}</StatusPill>
          </div>
          <div className="seq-angle-grid">
            <label>Angle<Input value={sequence.angle.name} onChange={(e) => seqPatch({ angle_name: e.target.value })} /></label>
            <label>Why it should work<Input value={sequence.angle.hypothesis || ""}
              onChange={(e) => seqPatch({ hypothesis: e.target.value })} placeholder="The hypothesis behind the copy" /></label>
            <label>Proof
              <Select value={sequence.angle.proof_key || ""} onChange={(e) => seqPatch({ proof_key: e.target.value })}
                placeholder="Choose a case study">
                {(context.proof || []).map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.named_claim_allowed ? item.label : `${item.label} · ${item.source_label}`}
                  </option>
                ))}
              </Select>
              {!context.proof?.length && <span className="seq-field-note">Missing case study. <Link to={libraryLink}>Add proof here.</Link></span>}
              {/* Flagged at the moment somebody picks it, not at QC time. The
                  block itself is server-side (sequences.py::_quality) — this only
                  stops the refusal arriving as a surprise. */}
              {selectedProof && !selectedProof.named_claim_allowed && (
                <span className="seq-field-note warn">
                  {selectedProof.source_label} evidence: usable as background, and it cannot
                  name {selectedProof.client_name || "this client"} in the copy.{" "}
                  <Link to={libraryLink}>Verify it in the Library.</Link>
                </span>
              )}
            </label>
            <label>Preview list
              <Select value={sequence.current_list_id || ""}
                onChange={(e) => seqPatch({ current_list_id: Number(e.target.value) })} placeholder="Choose current list">
                {(context.lists || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </Select>
            </label>
          </div>
        </div>

        <div className="seq-flow">
          {(sequence.steps || []).map((item, index) => (
            <div key={item.id}>
              {index > 0 && <div className="seq-wait"><span />Wait <b>{item.wait_days}</b> days<span /></div>}
              <article className={`seq-step card ${item.id === step?.id ? "selected" : ""}`}
                draggable onDragStart={() => setDragged(item.id)} onDragOver={(e) => e.preventDefault()}
                onDrop={() => moveStep(dragged, item.id)} onClick={() => { setSelectedStep(item.id); setSelectedVariant(item.variants?.[0]?.id); }}>
                <div className="seq-step-grip"><GripVertical size={17} /></div>
                <div className="seq-step-index">{index + 1}</div>
                <div className="seq-step-copy"><b>{item.name}</b><span>{purposeLabels[item.purpose] || item.purpose}</span></div>
                <div className="seq-step-state"><span>{item.variants.filter((v) => v.enabled).length} in rotation</span>
                  <Badge>{item.variants.length} variant{item.variants.length === 1 ? "" : "s"}</Badge></div>
              </article>
            </div>
          ))}
          <Button variant="ghost" icon={Plus} onClick={() => mutate(`/api/sequences/${sequence.id}/steps`, {
            name: `Email ${(sequence.steps?.length || 0) + 1}`, purpose: "follow_up", wait_days: 3,
          })}>Add email</Button>
        </div>

        {step && (
          <section className="seq-step-editor card">
            <div className="seq-step-editor-head">
              <div className="seq-step-settings">
                <Input value={step.name} onChange={(e) => onSequenceChange({ ...sequence,
                  steps: sequence.steps.map((s) => s.id === step.id ? { ...s, name: e.target.value } : s) })}
                  onBlur={(e) => patchStep({ name: e.target.value })} />
                <Select value={step.purpose} onChange={(e) => patchStep({ purpose: e.target.value })}>
                  {Object.entries(purposeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </Select>
                {step.position > 0 && <label className="seq-days">Wait<Input type="number" min="0" max="365" value={step.wait_days}
                  onChange={(e) => patchStep({ wait_days: Number(e.target.value) })} />days</label>}
              </div>
              <Button variant="ghost" size="sm" icon={Archive}
                onClick={async () => { await api(`/api/sequences/steps/${step.id}`, { method: "DELETE" }); await onReload(); }}>Archive email</Button>
            </div>
            {addingVariant && (
              <div className="seq-add-variant">
                <div><b>How is the new variant different?</b><span>This note stays with its results.</span></div>
                <Input autoFocus value={newVariantNote} onChange={(e) => setNewVariantNote(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addVariant()}
                  placeholder="For example: leads with the case study" />
                <Button size="sm" variant="ghost" onClick={() => { setAddingVariant(false); setNewVariantNote(""); }}>Cancel</Button>
                <Button size="sm" icon={ClipboardCopy} disabled={!newVariantNote.trim()} onClick={addVariant}>Duplicate</Button>
              </div>
            )}
            <div className="seq-variant-layout">
              <VariantEditor variant={variant} step={step} context={{ ...context, workspaceId: sequence.workspace_id }}
                onReload={onReload} onLocalVariant={updateLocalVariant} onPreview={previewVariant} />
              <div className="sequence-variant-rail" aria-label="Variants">
                {step.variants.map((item) => (
                  <button key={item.id} className={`${item.id === variant?.id ? "on" : ""} ${item.enabled ? "enabled" : ""} ${item.archived ? "archived" : ""}`}
                    onClick={() => setSelectedVariant(item.id)}>
                    <b>{item.label}</b>{item.enabled && <span />}
                  </button>
                ))}
                {step.variants.length < 7 && <button className="add" title="Duplicate active variant"
                  onClick={() => setAddingVariant(true)}><Plus size={16} /></button>}
              </div>
            </div>
          </section>
        )}

        <section className="seq-approval card">
          <div><FileCheck2 size={20} /><div><b>Client approval</b><span>Approval pins an immutable copy of the full angle, email, wait, and variant tree.</span></div></div>
          {sequence.status === "approved" && <StatusPill tone="green">Approved · version {sequence.version}</StatusPill>}
          {context.can_request_approval && sequence.status !== "approved" && (
            <div className="seq-approval-action"><Input value={approvalNote} onChange={(e) => setApprovalNote(e.target.value)}
              placeholder="Optional note for the client" />
              <Button icon={Send} onClick={() => mutate(`/api/sequences/${sequence.id}/submit-approval`, { note: approvalNote })}>
                Send for approval
              </Button></div>
          )}
          {context.can_approve && sequence.status === "in_review" && (
            <div className="seq-approval-action"><Input value={approvalNote} onChange={(e) => setApprovalNote(e.target.value)}
              placeholder="Add a note, or explain requested changes" />
              <Button variant="ghost" onClick={() => mutate(`/api/sequences/${sequence.id}/request-changes`, { note: approvalNote })}>Request changes</Button>
              <Button icon={Check} onClick={() => mutate(`/api/sequences/${sequence.id}/approve`, { note: approvalNote })}>Approve all four emails</Button></div>
          )}
          {!!sequence.approvals?.length && <div className="seq-approval-history">
            {sequence.approvals.map((item) => <span key={item.id}><b>v{item.version}</b> {prettyStatus(item.status)} {item.note && `· ${item.note}`}</span>)}
          </div>}
        </section>
      </section>
      {(preview || previewLoading) && <PreviewPane preview={preview} loading={previewLoading} onClose={() => setPreview(null)} />}
    </div>
  );
}

export default function Sequences() {
  const { me, wsParam } = useAuth();
  const toast = useToast();
  const initialWorkspace = wsParam || me?.workspaces?.[0]?.id;
  const [workspaceId, setWorkspaceId] = useState(initialWorkspace);
  const [rows, setRows] = useState(null);
  const [context, setContext] = useState(null);
  const [selected, setSelected] = useState(null);
  const [sequence, setSequence] = useState(null);
  const [creating, setCreating] = useState(false);
  const [showStart, setShowStart] = useState(false);
  const [error, setError] = useState("");
  // Whether this workspace's data ever arrived. A failed FIRST load has to
  // resolve into something the screen can show: the toast is gone in seconds,
  // and without this the page waits on data that is never coming. A failed
  // RELOAD keeps the workbench instead — losing an open sequence over one bad
  // response would be worse than a stale view.
  const loaded = useRef(false);
  const load = async (keepId = selected) => {
    if (!workspaceId) return;
    setError("");
    try {
      const [list, ctx] = await Promise.all([
        api("/api/sequences", { params: { workspace_id: workspaceId } }),
        api("/api/sequences/context", { params: { workspace_id: workspaceId } }),
      ]);
      setRows(list); setContext(ctx);
      const id = keepId || list[0]?.id;
      setSelected(id || null);
      if (id) setSequence(await api(`/api/sequences/${id}`)); else setSequence(null);
      loaded.current = true;
    } catch (e) {
      toast(e.message, "error");
      if (!loaded.current) { setError(e.message); setRows([]); }
    }
  };
  useEffect(() => {
    loaded.current = false;
    setSelected(null); setRows(null); setContext(null); setError("");
    load(null);
  }, [workspaceId]);
  const select = async (id) => {
    setSelected(id); setSequence(null); setShowStart(false);
    try { setSequence(await api(`/api/sequences/${id}`)); }
    catch (e) { toast(e.message, "error"); setSelected(null); }
  };
  const create = async (data) => {
    setCreating(true);
    try {
      const made = await api("/api/sequences", { method: "POST", body: { ...data, workspace_id: workspaceId } });
      setSelected(made.id); setSequence(made); setShowStart(false); await load(made.id); toast("Four-email sequence created");
    } catch (e) { toast(e.message, "error"); }
    finally { setCreating(false); }
  };
  const workspaceOptions = me?.workspaces || [];
  const actions = (
    <>
      {me?.is_master && workspaceOptions.length > 1 && (
        <Select size="sm" value={workspaceId || ""} onChange={(e) => setWorkspaceId(Number(e.target.value))}>
          {workspaceOptions.map((ws) => <option key={ws.id} value={ws.id}>{ws.name}</option>)}
        </Select>
      )}
      {sequence && <Button variant="ghost" size="sm" icon={ClipboardCopy}
        onClick={async () => { const made = await api(`/api/sequences/${sequence.id}/duplicate`, { method: "POST" }); await load(made.id); }}>Duplicate</Button>}
      {sequence && context?.can_request_approval && <Button variant="ghost" size="sm" icon={Library}
        onClick={async () => { await api(`/api/sequences/${sequence.id}/save-as-template`, { method: "POST", body: {} }); toast("Sequence saved as a reusable template"); await load(sequence.id); }}>Save as template</Button>}
      <Button size="sm" icon={Plus} onClick={() => setShowStart(true)}>New sequence</Button>
    </>
  );
  if (!workspaceId) return <EmptyState icon={Mail} title="Choose a workspace" hint="Email sequences always belong to one client workspace." />;
  if (error) return <ErrorBox msg={`Email sequences could not be loaded: ${error}`} retry={() => load(null)} />;
  if (!rows || !context) return <Spinner />;
  return (
    <div className="sequences-page">
      <PageHeader actions={actions} />
      <div className="seq-page-title"><div><span className="seq-page-icon"><Mail size={20} /></span><div><h1>Email Sequences</h1>
        <p>Angles, waits, plain-text emails, and approved variants in one shared workspace.</p></div></div>
        {sequence && <span>Version {sequence.version}</span>}</div>
      <div className="seq-shell">
        <aside className="seq-list">
          <div className="seq-list-head"><b>Sequences</b><Badge>{rows.length}</Badge></div>
          {rows.map((row) => (
            <button key={row.id} className={selected === row.id && !showStart ? "on" : ""} onClick={() => select(row.id)}>
              <span className="seq-list-mark"><Mail size={15} /></span>
              <span><b>{row.name}</b><em>{row.angle.name}</em></span>
              <StatusPill tone={statusTone[row.status]}>{prettyStatus(row.status)}</StatusPill>
            </button>
          ))}
          {!rows.length && <div className="seq-list-empty">No sequences yet.</div>}
        </aside>
        <main className="seq-main">
          {(showStart || !rows.length) && <TemplateStart context={context} onCreate={create} busy={creating} />}
          {!showStart && selected && !sequence && <Spinner />}
          {!showStart && sequence && <SequenceEditor sequence={sequence} context={context}
            onSequenceChange={setSequence} onReload={() => load(sequence.id)} />}
        </main>
      </div>
    </div>
  );
}
