/* The inline field every piece of editable copy on the canvas uses.

   It is a textarea rather than an input so a long question title wraps the way
   Google's does, and it grows to fit instead of scrolling. Enter is intercepted
   on single-line fields — it commits and advances, it does not insert a newline.

   While the field has focus and `toolbar` is set, the Bold / Italic / Underline /
   Link / Clear strip sits directly underneath it. Those buttons cancel their own
   mousedown so focus and the selection never leave the field; without that the
   toolbar would blur away the very selection it is about to format. */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Bold, Italic, Link, RemoveFormatting, Underline } from "lucide-react";
import { promptDialog } from "../../components";
import { RichText, clearFormatting, insertLink, toggleMark } from "../richtext";

const SHORTCUTS = { b: "bold", i: "italic", u: "underline" };

export function RichTitle({
  value = "",
  onChange,
  placeholder = "",
  className = "",
  active = false,
  toolbar = false,
  multiline = false,
  readWhenIdle = true,
  onEnter,
  onFocus,
  setRef,
  ariaLabel,
}) {
  const ref = useRef(null);
  const pendingSelection = useRef(null);
  const [focused, setFocused] = useState(false);

  const attach = (element) => { ref.current = element; setRef?.(element); };
  const editing = active || !readWhenIdle;

  /* Grow to fit. A field that scrolls hides the end of a long question title. */
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !editing) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [value, editing]);

  /* Put the caret back after a formatting edit rather than at the end. */
  useEffect(() => {
    if (!pendingSelection.current) return;
    const [start, end] = pendingSelection.current;
    pendingSelection.current = null;
    const element = ref.current;
    if (!element) return;
    element.focus();
    element.setSelectionRange(start, end);
  });

  const apply = (transform) => {
    const element = ref.current;
    if (!element) return;
    const next = transform(element.value, element.selectionStart ?? 0, element.selectionEnd ?? 0);
    pendingSelection.current = [next.start, next.end];
    onChange(next.value);
  };

  const addLink = async () => {
    const element = ref.current;
    if (!element) return;
    // Captured before the dialog opens — it takes focus, and with it the selection.
    const start = element.selectionStart ?? 0;
    const end = element.selectionEnd ?? 0;
    const url = await promptDialog("Where should this link point?",
      { title: "Add link", placeholder: "https://example.com", confirmText: "Add link" });
    if (!url?.trim()) return;
    const next = insertLink(value, start, end, url.trim());
    pendingSelection.current = [next.start, next.end];
    onChange(next.value);
  };

  const onKeyDown = (event) => {
    if ((event.metaKey || event.ctrlKey) && SHORTCUTS[event.key.toLowerCase()]) {
      event.preventDefault();
      apply((text, start, end) => toggleMark(text, start, end, SHORTCUTS[event.key.toLowerCase()]));
      return;
    }
    if (event.key === "Enter" && !multiline) {
      event.preventDefault();
      onEnter?.(event);
    }
  };

  if (!editing) {
    return (
      <div className={`gf-inline gf-inline-idle ${className}`}>
        {value
          ? <RichText text={value} />
          : <span className="gf-inline-placeholder">{placeholder}</span>}
      </div>
    );
  }

  return (
    <div className={`gf-inline gf-inline-live ${className}`}>
      <textarea
        ref={attach}
        rows={1}
        value={value}
        placeholder={placeholder}
        aria-label={ariaLabel || placeholder}
        spellCheck
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => { setFocused(true); onFocus?.(); }}
        onBlur={() => setFocused(false)}
      />
      {toolbar && focused && (
        <div className="gf-format" role="toolbar" aria-label="Text formatting">
          <FormatButton label="Bold" hint="Bold (Ctrl+B)" icon={Bold}
            onPress={() => apply((t, s, e) => toggleMark(t, s, e, "bold"))} />
          <FormatButton label="Italic" hint="Italic (Ctrl+I)" icon={Italic}
            onPress={() => apply((t, s, e) => toggleMark(t, s, e, "italic"))} />
          <FormatButton label="Underline" hint="Underline (Ctrl+U)" icon={Underline}
            onPress={() => apply((t, s, e) => toggleMark(t, s, e, "underline"))} />
          <FormatButton label="Link" hint="Add link" icon={Link} onPress={addLink} />
          <FormatButton label="Clear formatting" hint="Clear formatting" icon={RemoveFormatting}
            onPress={() => apply(clearFormatting)} />
        </div>
      )}
    </div>
  );
}

function FormatButton({ icon: Icon, label, hint, onPress }) {
  return (
    <button type="button" className="gf-format-btn" title={hint} aria-label={label}
      onMouseDown={(event) => event.preventDefault()} onClick={onPress}>
      <Icon size={15} />
    </button>
  );
}
