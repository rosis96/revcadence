/* The card's ⋮ menu.

   Google's overflow menu holds per-question extras, so ours is where the four
   settings with no Google equivalent live — Section, Maps to, Pre-fill from,
   Display as — alongside the one item Google does have, Description.

   It navigates in place rather than opening nested popups. Seventeen mapping
   targets do not fit a flyout, and a second portalled menu inside this one would
   dismiss its own parent on click. A back arrow and one list at a time is what
   native menus do, and it reads better at that length. */
import { useEffect, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { InlinePopup } from "../../components";
import { DISPLAY_MODES, MAP_LABELS, PREFILL_LABELS } from "./registry";
import { RichText } from "../richtext";

export function CardMenu({
  open, onClose, anchorRef, question, sections, mapTargets, prefillSources,
  onPatch, onMoveToSection, onToggleDescription,
}) {
  const [view, setView] = useState("root");
  /* InlinePopup treats anything outside its anchor and its contentRef as a click
     away. Without the ref, drilling into a submenu dismisses the menu doing the
     drilling. */
  const panelRef = useRef(null);
  useEffect(() => { if (open) setView("root"); }, [open]);

  const section = sections.find((row) => row.id === question.section_id);
  const hasDescription = (question.help_text || "").length > 0;

  // Picking a value is the end of the errand, so the menu closes behind it.
  const choose = (patch) => { onPatch(patch); onClose(); };

  const VIEWS = {
    section: {
      title: "Section",
      options: [{ value: "", label: "No section" },
        ...sections.map((row) => ({ value: String(row.id), label: row.title || "Untitled section" }))],
      current: question.section_id ? String(question.section_id) : "",
      pick: (value) => { onMoveToSection(value ? Number(value) : null); onClose(); },
      note: "Moving a question changes where its card sits on the canvas.",
    },
    maps_to: {
      title: "Maps to",
      options: [{ value: "", label: "Answer only" },
        ...mapTargets.map((target) => ({ value: target, label: MAP_LABELS[target] || target }))],
      current: question.maps_to || "",
      pick: (value) => choose({ maps_to: value || null }),
      note: "Mapped answers merge into the workspace and keep client-supplied provenance.",
    },
    prefill: {
      title: "Pre-fill from",
      options: [{ value: "", label: "No pre-fill" },
        ...prefillSources.map((source) => ({ value: source, label: PREFILL_LABELS[source] || source }))],
      current: question.prefill_source || "",
      pick: (value) => choose({ prefill_source: value || null }),
      note: "A pre-filled question is shown as a confirm field unless you change how it displays.",
    },
    display: {
      title: "Display as",
      options: DISPLAY_MODES,
      current: question.display_mode || "ask",
      pick: (value) => choose({ display_mode: value }),
    },
  };

  const panel = VIEWS[view];

  return (
    <InlinePopup open={open} onClose={onClose} anchorRef={anchorRef} contentRef={panelRef}
      align="end" side="auto" maxHeight={380} minWidth={264} className="gf-menu" role="menu">
      {panel ? (
        <>
          <button type="button" className="gf-menu-back" onClick={() => setView("root")}>
            <ChevronLeft size={15} /> {panel.title}
          </button>
          <div className="gf-menu-list">
            {panel.options.map((option) => (
              <button key={option.value} type="button" role="menuitemradio"
                aria-checked={panel.current === option.value}
                className={panel.current === option.value ? "on" : ""}
                onClick={() => panel.pick(option.value)}>
                <span className="gf-menu-tick">{panel.current === option.value && <Check size={14} />}</span>
                {option.label}
              </button>
            ))}
          </div>
          {panel.note && <p className="gf-menu-note">{panel.note}</p>}
        </>
      ) : (
        <div className="gf-menu-list">
          <button type="button" role="menuitemcheckbox" aria-checked={hasDescription}
            onClick={() => { onToggleDescription(); onClose(); }}>
            <span className="gf-menu-tick">{hasDescription && <Check size={14} />}</span>
            Description
          </button>
          <div className="gf-menu-sep" />
          <MenuRow label="Section" value={section ? <RichText text={section.title} /> : "No section"}
            onClick={() => setView("section")} />
          <MenuRow label="Maps to" value={question.maps_to ? (MAP_LABELS[question.maps_to] || question.maps_to) : "Answer only"}
            onClick={() => setView("maps_to")} />
          <MenuRow label="Pre-fill from" value={question.prefill_source ? (PREFILL_LABELS[question.prefill_source] || question.prefill_source) : "No pre-fill"}
            onClick={() => setView("prefill")} />
          <MenuRow label="Display as" value={DISPLAY_MODES.find((mode) => mode.value === (question.display_mode || "ask"))?.label}
            onClick={() => setView("display")} />
        </div>
      )}
    </InlinePopup>
  );
}

function MenuRow({ label, value, onClick }) {
  return (
    <button type="button" role="menuitem" className="gf-menu-row" onClick={onClick}>
      <span className="gf-menu-row-label">{label}</span>
      <span className="gf-menu-row-value">{value}</span>
      <ChevronRight size={14} />
    </button>
  );
}

/** A section header card's smaller menu. */
export function SectionMenu({ open, onClose, anchorRef, onDuplicate, onDelete }) {
  const panelRef = useRef(null);
  return (
    <InlinePopup open={open} onClose={onClose} anchorRef={anchorRef} contentRef={panelRef}
      align="end" side="auto" minWidth={200} className="gf-menu" role="menu">
      <div className="gf-menu-list">
        <button type="button" role="menuitem" onClick={() => { onDuplicate(); onClose(); }}>
          <span className="gf-menu-tick" />Duplicate section
        </button>
        <button type="button" role="menuitem" className="danger" onClick={() => { onDelete(); onClose(); }}>
          <span className="gf-menu-tick" />Delete section
        </button>
      </div>
    </InlinePopup>
  );
}
