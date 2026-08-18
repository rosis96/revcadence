/* The option list inside a choice question's card.

   Each row is the control glyph the client will actually see plus an inline
   field. Below the last row sits a ghost row: typing in it promotes it to a real
   option and carries the keystroke and the caret across, so a list gets built
   without ever reaching for a button. */
import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { CHOICE_TYPES } from "./registry";

const labelOf = (choice) => (choice && typeof choice === "object" ? choice.label ?? choice.value ?? "" : choice ?? "");

function Glyph({ type, index, muted = false }) {
  if (type === "dropdown") return <span className={`gf-glyph gf-glyph-n ${muted ? "muted" : ""}`}>{index + 1}.</span>;
  return <span className={`gf-glyph ${type === "multi_choice" ? "square" : "round"} ${muted ? "muted" : ""}`} />;
}

/** Read-only rows, for a card that is not being edited. */
export function OptionsPreview({ type, choices }) {
  const rows = type === "yes_no" ? ["Yes", "No"] : choices;
  return (
    <div className="gf-options">
      {rows.map((choice, index) => (
        <div key={index} className="gf-option gf-option-idle">
          <Glyph type={type === "yes_no" ? "single_choice" : type} index={index} />
          <span className="gf-option-text">{labelOf(choice) || `Option ${index + 1}`}</span>
        </div>
      ))}
    </div>
  );
}

export function OptionsEditor({ type, choices, onChange, setRef, focusField }) {
  const values = choices.map(labelOf);
  /* The row the ghost promotes into does not exist until the next render, so focus
     is still in the ghost for one beat. Without this latch the next keystroke
     promotes again and a five-letter word becomes five options. */
  const promoting = useRef(false);
  useEffect(() => { promoting.current = false; }, [values.length]);

  if (!CHOICE_TYPES.has(type)) return null;
  const hasOther = values.some((value) => value.trim().toLowerCase() === "other");

  const write = (next) => onChange(next);
  const setAt = (index, value) => write(values.map((current, i) => (i === index ? value : current)));

  const insertAfter = (index) => {
    write([...values.slice(0, index + 1), "", ...values.slice(index + 1)]);
    focusField(`option:${index + 1}`);
  };

  const removeAt = (index) => {
    if (values.length <= 1) return;                 // a choice question keeps one row
    write(values.filter((_, i) => i !== index));
    focusField(`option:${Math.max(0, index - 1)}`);
  };

  const onRowKeyDown = (event, index) => {
    if (event.key === "Enter") {
      event.preventDefault();
      // Enter on a row that has nothing in it would only make another empty row.
      if (values[index].trim()) insertAfter(index);
      return;
    }
    if (event.key === "Backspace" && values[index] === "") {
      event.preventDefault();
      removeAt(index);
    }
  };

  /* The ghost row never holds text of its own: the first keystroke becomes a real
     option and focus follows it there. */
  const promote = (value) => {
    if (!value || promoting.current) return;
    promoting.current = true;
    write([...values, value]);
    focusField(`option:${values.length}`);
  };

  return (
    <div className="gf-options">
      {values.map((value, index) => (
        <div key={index} className="gf-option">
          <Glyph type={type} index={index} />
          <input
            ref={(element) => setRef(`option:${index}`, element)}
            className="gf-option-input"
            value={value}
            placeholder={`Option ${index + 1}`}
            aria-label={`Option ${index + 1}`}
            onChange={(event) => setAt(index, event.target.value)}
            onKeyDown={(event) => onRowKeyDown(event, index)}
          />
          <button type="button" className="gf-option-remove" title="Remove option"
            aria-label={`Remove option ${index + 1}`}
            disabled={values.length <= 1} onClick={() => removeAt(index)}>
            <X size={15} />
          </button>
        </div>
      ))}

      <div className="gf-option gf-option-ghost">
        <Glyph type={type} index={values.length} muted />
        <input
          ref={(element) => setRef("ghost", element)}
          className="gf-option-input"
          value=""
          placeholder="Add option"
          aria-label="Add option"
          onChange={(event) => promote(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") event.preventDefault(); }}
        />
        {!hasOther && (
          <span className="gf-option-other">
            or <button type="button" onClick={() => promote("Other")}>add &quot;Other&quot;</button>
          </span>
        )}
      </div>
    </div>
  );
}
