/* Select — the one dropdown for the whole dashboard.

   Replaces every native select element. The popup is a themed, rounded panel rendered
   in a portal (native option lists can't be styled, and an in-flow menu would be
   clipped by .surface / .dt-scroll / .modal .box, which all hide overflow).

   Drop-in with the native element on purpose: same `value` / `onChange` contract,
   same <option> children. onChange receives { target: { value, selectedOptions } }
   so existing handlers (Number(e.target.value), Array.from(e.target.selectedOptions))
   keep working untouched.

   Values are stringified exactly like the native element does, so `value={25}` still
   matches <option value={25}>. */
import { Children, Fragment, isValidElement, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { InlinePopup } from "./InlinePopup";

const MENU_MAX = 320;   /* tallest the panel gets before it scrolls */
const MENU_MIN = 176;   /* narrowest, so a tiny trigger still gets a readable menu */
const SEARCH_AT = 10;   /* auto-show the filter box from this many options up */

function nodeText(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement(node)) return nodeText(node.props.children);
  return "";
}

/* <option>/<optgroup> children → a flat option list. Mirrors native coercion:
   an option with no `value` uses its text, and every value becomes a string. */
function collectOptions(children, out = [], group = null) {
  Children.forEach(children, (child) => {
    if (child == null || typeof child === "boolean") return;
    if (Array.isArray(child)) return void collectOptions(child, out, group);
    if (!isValidElement(child)) return;
    if (child.type === Fragment) return void collectOptions(child.props.children, out, group);
    if (child.type === "optgroup") return void collectOptions(child.props.children, out, child.props.label ?? null);
    if (child.type !== "option") return;
    const text = nodeText(child.props.children);
    out.push({
      value: String(child.props.value ?? text),
      text,
      node: child.props.children,
      disabled: !!child.props.disabled,
      group,
    });
  });
  return out;
}

/* `options` prop shorthand: ["a", "b"] or [{ value, label }] */
const normalizeOptions = (options) =>
  (options || []).map((o) =>
    typeof o === "object" && o !== null
      ? { value: String(o.value ?? o.label ?? ""), text: nodeText(o.label ?? o.value), node: o.label ?? String(o.value ?? ""), disabled: !!o.disabled, group: o.group ?? null }
      : { value: String(o), text: String(o), node: String(o), disabled: false, group: null });

export function Select({
  value,
  onChange,
  children,
  options,
  placeholder = "Select…",
  disabled = false,
  multiple = false,
  searchable,
  caret,                   /* swap the trigger glyph; a custom one does not flip on open */
  size = "md",
  tone = "field",          /* "dark"/"ghost" → trigger sits on the shell (sidebar / top bar) */
  align = "start",
  className = "",
  style,
  name,
  id,
  title,
  "aria-label": ariaLabel,
}) {
  const Caret = caret || ChevronDown;
  const opts = useMemo(
    () => (options ? normalizeOptions(options) : collectOptions(children)),
    [options, children],
  );

  const selected = useMemo(() => {
    if (multiple) return new Set((Array.isArray(value) ? value : value == null ? [] : [value]).map(String));
    return new Set(value == null ? [] : [String(value)]);
  }, [value, multiple]);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);

  const wrapRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const searchRef = useRef(null);
  const typeahead = useRef({ buf: "", at: 0 });
  const listId = useId();

  const useSearch = searchable ?? opts.length >= SEARCH_AT;
  const visible = useMemo(() => {
    if (!useSearch || !query.trim()) return opts;
    const q = query.trim().toLowerCase();
    return opts.filter((o) => o.text.toLowerCase().includes(q));
  }, [opts, query, useSearch]);

  const chosen = opts.filter((o) => selected.has(o.value));
  const label = multiple
    ? (chosen.length === 0 ? placeholder : chosen.length === 1 ? chosen[0].node : `${chosen.length} selected`)
    : (chosen[0]?.node ?? placeholder);
  const isPlaceholder = chosen.length === 0;

  /* ------------------------------------------------------------ open / close */
  const openMenu = useCallback(() => {
    if (disabled) return;
    setQuery("");
    const first = opts.findIndex((o) => selected.has(o.value) && !o.disabled);
    setActive(first >= 0 ? first : opts.findIndex((o) => !o.disabled));
    setOpen(true);
  }, [disabled, opts, selected]);

  const closeMenu = useCallback((refocus = true) => {
    setOpen(false);
    if (refocus) triggerRef.current?.focus();
  }, []);

  /* focus into the panel so arrow keys land there, not on the page behind it */
  useEffect(() => {
    if (!open) return;
    (useSearch ? searchRef.current : menuRef.current)?.focus({ preventScroll: true });
  }, [open, useSearch]);

  useEffect(() => {
    if (!open || active < 0) return;
    menuRef.current?.querySelector('[data-active="1"]')?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  /* ------------------------------------------------------------ selection */
  const emit = useCallback(
    (values) => {
      onChange?.({
        target: {
          value: multiple ? (values[values.length - 1] ?? "") : (values[0] ?? ""),
          selectedOptions: values.map((v) => ({ value: v })),
          name,
        },
      });
    },
    [onChange, multiple, name],
  );

  const pick = useCallback(
    (opt) => {
      if (opt.disabled) return;
      if (multiple) {
        const next = selected.has(opt.value)
          ? [...selected].filter((v) => v !== opt.value)
          : [...selected, opt.value];
        emit(next);          /* stay open: multi-select is a batch action */
      } else {
        emit([opt.value]);
        closeMenu();
      }
    },
    [multiple, selected, emit, closeMenu],
  );

  /* ------------------------------------------------------------ keyboard */
  const step = (dir) => {
    if (!visible.length) return;
    const cur = visible.findIndex((o) => o === opts[active]);
    let i = cur;
    for (let n = 0; n < visible.length; n++) {
      i = (i + dir + visible.length) % visible.length;
      if (!visible[i].disabled) break;
    }
    setActive(opts.indexOf(visible[i]));
  };

  const onTriggerKey = (e) => {
    if (disabled) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openMenu();
    }
  };

  const onMenuKey = (e) => {
    switch (e.key) {
      case "Escape":       e.preventDefault(); closeMenu(); break;
      case "Tab":          closeMenu(false); break;
      case "ArrowDown":    e.preventDefault(); step(1); break;
      case "ArrowUp":      e.preventDefault(); step(-1); break;
      case "Home":         e.preventDefault(); setActive(opts.indexOf(visible.find((o) => !o.disabled))); break;
      case "End":          e.preventDefault(); setActive(opts.indexOf([...visible].reverse().find((o) => !o.disabled))); break;
      case "Enter":
      case " ":
        if (e.key === " " && useSearch) return;   /* space belongs to the filter box */
        e.preventDefault();
        if (opts[active]) pick(opts[active]);
        break;
      default:
        if (useSearch || e.key.length !== 1 || e.metaKey || e.ctrlKey || e.altKey) return;
        {
          const now = Date.now();
          const ta = typeahead.current;
          ta.buf = now - ta.at > 800 ? e.key : ta.buf + e.key;
          ta.at = now;
          const hit = opts.find((o) => !o.disabled && o.text.toLowerCase().startsWith(ta.buf.toLowerCase()));
          if (hit) setActive(opts.indexOf(hit));
        }
    }
  };

  /* ------------------------------------------------------------ render */
  const menu = (
    <InlinePopup
      open={open}
      onClose={() => closeMenu(false)}
      anchorRef={triggerRef}
      anchorSelector="[data-sel-anchor]"
      contentRef={menuRef}
      id={listId}
      className="sel-menu"
      role="listbox"
      tabIndex={-1}
      aria-multiselectable={multiple || undefined}
      align={align}
      side="auto"
      minWidth={MENU_MIN}
      maxHeight={MENU_MAX}
      onKeyDown={onMenuKey}
    >
      {useSearch && (
        <div className="sel-search">
          <Search size={13} />
          <input
            ref={searchRef}
            value={query}
            placeholder="Filter…"
            onChange={(e) => {
              setQuery(e.target.value);
              const next = e.target.value.trim().toLowerCase();
              const hit = opts.find((o) => !o.disabled && o.text.toLowerCase().includes(next));
              setActive(hit ? opts.indexOf(hit) : -1);
            }}
          />
        </div>
      )}
      <div className="sel-list">
        {visible.length === 0 && <div className="sel-none">No matches</div>}
        {visible.map((o, i) => {
          const on = selected.has(o.value);
          const showGroup = o.group && o.group !== visible[i - 1]?.group;
          return (
            <Fragment key={`${o.group ?? ""}:${o.value}:${i}`}>
              {showGroup && <div className="sel-group">{o.group}</div>}
              <div
                role="option"
                aria-selected={on}
                aria-disabled={o.disabled || undefined}
                data-active={opts[active] === o ? "1" : undefined}
                className={`sel-opt${on ? " on" : ""}${o.disabled ? " off" : ""}`}
                onMouseEnter={() => !o.disabled && setActive(opts.indexOf(o))}
                onMouseDown={(e) => e.preventDefault()}   /* keep focus in the panel */
                onClick={() => pick(o)}
              >
                <span className="sel-opt-t">{o.node}</span>
                {on && <Check size={14} className="sel-tick" />}
              </div>
            </Fragment>
          );
        })}
      </div>
    </InlinePopup>
  );

  return (
    <div ref={wrapRef} className={`sel sel-${size} sel-${tone}${open ? " open" : ""}${disabled ? " disabled" : ""} ${className}`} style={style}>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        title={title}
        aria-label={ariaLabel}
        className="sel-trigger"
        disabled={disabled}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => (open ? closeMenu() : openMenu())}
        onKeyDown={onTriggerKey}
      >
        <span className={`sel-value${isPlaceholder ? " ph" : ""}`}>{label}</span>
        <Caret size={size === "sm" ? 13 : 15} className={`sel-caret${caret ? "" : " spin"}`} />
      </button>
      {name && <input type="hidden" name={name} value={multiple ? [...selected].join(",") : ([...selected][0] ?? "")} />}
      {menu}
    </div>
  );
}
