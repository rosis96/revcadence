/* One question card. The card *is* the editor: there is no panel anywhere else
   holding the fields for it.

   Active, it shows the title field with its formatting strip, the type dropdown,
   the option editor, and the footer. Idle, it collapses to what the client will
   see — title, description, and a preview of the control — which is what makes a
   long form readable while you scroll it. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Copy, GripHorizontal, Image as ImageIcon, MoreVertical, Trash2 } from "lucide-react";
import { Select } from "../../components";
import { RichTitle } from "./RichTitle";
import { OptionsEditor, OptionsPreview } from "./OptionsEditor";
import { CardMenu, SectionMenu } from "./CardMenu";
import { CHOICE_TYPES, TYPES, defaultOptions } from "./registry";

const ANSWER_HINT = {
  short_text: "Short answer text", long_text: "Long answer text", number: "Number",
  date: "Date", email: "Email address", url: "Link", file_upload: "The client uploads a file",
};

/** What the client sees, for the types with no list to edit. */
function AnswerPreview({ type }) {
  if (type === "yes_no") return <OptionsPreview type="yes_no" choices={[]} />;
  if (type === "long_text") {
    return <div className="gf-answer-block"><span>{ANSWER_HINT.long_text}</span></div>;
  }
  return <div className="gf-answer-line"><span>{ANSWER_HINT[type] || "Answer"}</span></div>;
}

export function QuestionCard({
  item, active, onActivate, sections, mapTargets, prefillSources,
  focus, clearFocus, requestFocus, onPatch, onDuplicate, onRemove, onMoveToSection, onAddBelow,
  dragging, dropEdge, onDragStart, onDragOver, onDrop, onDragEnd,
}) {
  const question = item.data;
  const fields = useRef({});
  const menuRef = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [armed, setArmed] = useState(false);

  const isChoice = CHOICE_TYPES.has(question.type);
  const choices = question.options?.choices || [];
  const hasDescription = (question.help_text || "").length > 0;

  const setRef = (name, element) => {
    if (element) fields.current[name] = element;
    else delete fields.current[name];
  };

  /* One-shot focus requests from the hook — a card that was just created, an
     option row that was just inserted, the row above one that was deleted.

     The target often does not exist on the render the request arrives on: the
     patch that adds the row is applied a microtask later, so the row appears on
     the next commit. The request therefore survives a few renders (the deps below
     cover every field that can appear) instead of being dropped on first miss,
     which is what left focus behind in the ghost row. */
  const attempts = useRef(0);
  useEffect(() => {
    if (!focus || focus.kind !== "question" || focus.id !== item.id) { attempts.current = 0; return; }
    const element = fields.current[focus.field];
    if (element) {
      element.focus();
      if (focus.select) element.select?.();
      else {
        const end = element.value?.length ?? 0;
        element.setSelectionRange?.(end, end);
      }
      attempts.current = 0;
      clearFocus();
      return;
    }
    attempts.current += 1;
    if (attempts.current > 4) { attempts.current = 0; clearFocus(); }
  }, [focus, item.id, clearFocus, choices.length, hasDescription, question.type]);

  const typeOptions = useMemo(() => TYPES.map((type) => {
    const Icon = type.icon;
    return { value: type.value, group: type.group,
      label: <span className="gf-type-option"><Icon size={15} />{type.label}</span> };
  }), []);

  const focusField = (field) => requestFocus({ kind: "question", id: item.id, field });

  /* Enter commits and advances: into the options if there are any, otherwise on
     to a fresh question below this one. */
  const advance = () => {
    if (isChoice) { focusField("option:0"); return; }
    onAddBelow();
  };

  return (
    <article
      className={`gf-card ${active ? "active" : ""} ${dragging ? "dragging" : ""}`}
      draggable={armed}
      onMouseDown={() => !active && onActivate()}
      onFocusCapture={() => !active && onActivate()}
      onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; onDragStart(); }}
      onDragEnd={() => { setArmed(false); onDragEnd(); }}
      onDragOver={(event) => {
        event.preventDefault();
        const box = event.currentTarget.getBoundingClientRect();
        onDragOver(event.clientY < box.top + box.height / 2 ? "before" : "after");
      }}
      onDrop={(event) => { event.preventDefault(); onDrop(); }}
      /* A collapsed card has no focusable field of its own, so it takes focus
         itself — that is how Tab reaches the next question and opens it. */
      tabIndex={active ? -1 : 0}
      aria-current={active || undefined}
    >
      {dropEdge && <span className={`gf-drop gf-drop-${dropEdge}`} aria-hidden />}

      <button type="button" className="gf-grip" title="Drag to reorder" aria-label="Drag to reorder"
        onMouseDown={() => setArmed(true)} onMouseUp={() => setArmed(false)}>
        <GripHorizontal size={16} />
      </button>

      <div className="gf-card-top">
        <RichTitle
          className="gf-title"
          value={question.label || ""}
          placeholder="Question"
          ariaLabel="Question title"
          active={active}
          toolbar
          onEnter={advance}
          onChange={(value) => onPatch({ label: value })}
          setRef={(element) => setRef("title", element)}
        />
        {active && (
          <div className="gf-card-tools">
            <button type="button" className="gf-attach" disabled
              title="Image questions need a media block on the form schema — not available yet"
              aria-label="Attach image (unavailable)">
              <ImageIcon size={19} />
            </button>
            <Select className="gf-type" options={typeOptions} value={question.type}
              aria-label="Question type"
              onChange={(event) => onPatch({
                type: event.target.value,
                options: defaultOptions(event.target.value, question.options || {}),
              })} />
          </div>
        )}
      </div>

      {hasDescription && (
        <RichTitle
          className="gf-help"
          value={question.help_text || ""}
          placeholder="Description"
          ariaLabel="Question description"
          active={active}
          onEnter={advance}
          onChange={(value) => onPatch({ help_text: value })}
          setRef={(element) => setRef("help", element)}
        />
      )}

      <div className="gf-card-body">
        {isChoice && active && (
          <OptionsEditor type={question.type} choices={choices} setRef={setRef} focusField={focusField}
            onChange={(next) => onPatch({ options: { ...(question.options || {}), choices: next } })} />
        )}
        {isChoice && !active && <OptionsPreview type={question.type} choices={choices.length ? choices : [""]} />}
        {!isChoice && <AnswerPreview type={question.type} />}
      </div>

      {!active && (question.required || question.maps_to || question.prefill_source) && (
        <div className="gf-card-tags">
          {question.required && <span className="gf-tag req">Required</span>}
          {question.maps_to && <span className="gf-tag">Maps to {question.maps_to}</span>}
          {question.prefill_source && <span className="gf-tag">Pre-filled</span>}
        </div>
      )}

      {active && (
        <>
          <div className="gf-card-rule" />
          <footer className="gf-card-foot">
            <button type="button" className="gf-foot-btn" title="Duplicate" aria-label="Duplicate question"
              onClick={onDuplicate}><Copy size={18} /></button>
            <button type="button" className="gf-foot-btn" title="Delete" aria-label="Delete question"
              onClick={onRemove}><Trash2 size={18} /></button>
            <span className="gf-foot-rule" />
            <label className="gf-required">
              Required
              <span className={`gf-switch ${question.required ? "on" : ""}`}>
                <input type="checkbox" checked={!!question.required}
                  onChange={(event) => onPatch({ required: event.target.checked })} />
                <i />
              </span>
            </label>
            <button ref={menuRef} type="button" className="gf-foot-btn" title="More options"
              aria-label="More options" aria-haspopup="menu" aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}><MoreVertical size={18} /></button>
          </footer>
          <CardMenu open={menuOpen} onClose={() => setMenuOpen(false)} anchorRef={menuRef}
            question={question} sections={sections} mapTargets={mapTargets} prefillSources={prefillSources}
            onPatch={onPatch} onMoveToSection={onMoveToSection}
            onToggleDescription={() => {
              if (hasDescription) { onPatch({ help_text: "" }); return; }
              onPatch({ help_text: " " });
              requestFocus({ kind: "question", id: item.id, field: "help", select: true });
            }} />
        </>
      )}
    </article>
  );
}

/** Section header card — Google's "add section" block. */
export function SectionCard({
  item, index, total, active, onActivate, focus, clearFocus, onPatch, onDuplicate, onRemove,
  dragging, dropEdge, onDragStart, onDragOver, onDrop, onDragEnd,
}) {
  const section = item.data;
  const fields = useRef({});
  const menuRef = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [armed, setArmed] = useState(false);

  const setRef = (name, element) => {
    if (element) fields.current[name] = element;
    else delete fields.current[name];
  };

  useEffect(() => {
    if (!focus || focus.kind !== "section" || focus.id !== item.id) return;
    const element = fields.current[focus.field];
    if (element) {
      element.focus();
      if (focus.select) element.select?.();
    }
    clearFocus();
  }, [focus, item.id, clearFocus]);

  return (
    <article
      className={`gf-card gf-section ${active ? "active" : ""} ${dragging ? "dragging" : ""}`}
      draggable={armed}
      onMouseDown={() => !active && onActivate()}
      onFocusCapture={() => !active && onActivate()}
      onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; onDragStart(); }}
      onDragEnd={() => { setArmed(false); onDragEnd(); }}
      onDragOver={(event) => {
        event.preventDefault();
        const box = event.currentTarget.getBoundingClientRect();
        onDragOver(event.clientY < box.top + box.height / 2 ? "before" : "after");
      }}
      onDrop={(event) => { event.preventDefault(); onDrop(); }}
      tabIndex={active ? -1 : 0}
    >
      {dropEdge && <span className={`gf-drop gf-drop-${dropEdge}`} aria-hidden />}
      <button type="button" className="gf-grip" title="Drag to reorder" aria-label="Drag section to reorder"
        onMouseDown={() => setArmed(true)} onMouseUp={() => setArmed(false)}>
        <GripHorizontal size={16} />
      </button>

      <div className="gf-section-head">
        <span className="gf-section-count">Section {index} of {total}</span>
        {active && (
          <div className="gf-card-tools">
            <button type="button" className="gf-foot-btn" title="Duplicate section"
              aria-label="Duplicate section" onClick={onDuplicate}><Copy size={17} /></button>
            <button type="button" className="gf-foot-btn" title="Delete section"
              aria-label="Delete section" onClick={onRemove}><Trash2 size={17} /></button>
            <button ref={menuRef} type="button" className="gf-foot-btn" title="More options"
              aria-label="More section options" aria-haspopup="menu" aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}><MoreVertical size={17} /></button>
          </div>
        )}
      </div>

      <RichTitle className="gf-section-title" value={section.title || ""} placeholder="Untitled section"
        ariaLabel="Section title" active={active} toolbar
        onEnter={() => fields.current.description?.focus()}
        onChange={(value) => onPatch({ title: value })}
        setRef={(element) => setRef("title", element)} />
      <RichTitle className="gf-section-desc" value={section.description || ""} placeholder="Description (optional)"
        ariaLabel="Section description" active={active} multiline
        onChange={(value) => onPatch({ description: value })}
        setRef={(element) => setRef("description", element)} />

      <SectionMenu open={menuOpen} onClose={() => setMenuOpen(false)} anchorRef={menuRef}
        onDuplicate={onDuplicate} onDelete={onRemove} />
    </article>
  );
}
