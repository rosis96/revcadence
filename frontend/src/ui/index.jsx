/* RevCadence UI library (Phase 0 of DESIGN_SYSTEM.md).
   Every reusable primitive lives here; components.jsx re-exports this module.
   Names deliberately do NOT clash with legacy exports in components.jsx. */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, Inbox as InboxIcon, Search, X } from "lucide-react";
export { confirmDialog, promptDialog, alertDialog, GlobalDialogs } from "./dialogs";
export { Select } from "./Select";
export { InlinePopup } from "./InlinePopup";
import { Select } from "./Select";

/* ---------------------------------------------------------------- Button */
export function Button({ variant = "primary", size = "md", loading = false, icon: Icon, children, className = "", ...rest }) {
  return (
    <button className={`ui-btn ${variant} ${size} ${className}`} disabled={loading || rest.disabled} {...rest}>
      {loading ? <span className="ui-btn-spin" /> : Icon && <Icon size={size === "sm" ? 14 : 16} />}
      {children}
    </button>
  );
}
export function IconButton({ icon: Icon, label, size = 16, className = "", ...rest }) {
  return <button className={`iconbtn ${className}`} title={label} aria-label={label} {...rest}><Icon size={size} /></button>;
}

/* ---------------------------------------------------------------- Inputs */
export const TextInput = (props) => <input type="text" {...props} />;
export function SearchInput({ value, onChange, placeholder = "Search…", kbd, className = "", ...rest }) {
  return (
    <div className={`dt-search ${className}`}>
      <Search size={15} />
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} {...rest} />
      {kbd && <kbd className="si-kbd">{kbd}</kbd>}
    </div>
  );
}

/* ---------------------------------------------------------------- Tabs (underline, URL-syncable via value/onChange) */
export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="ui-tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={value === t.key}
          className={`ui-tab ${value === t.key ? "on" : ""}`} onClick={() => onChange(t.key)}>
          {t.label}{t.count != null && <span className="cnt">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- StatusPill / Avatar / Card / StatCard */
export function StatusPill({ tone = "gray", children }) {
  return <span className={`pill-badge pb-${tone}`}><span className="bd" />{children}</span>;
}
export function Avatar({ name = "?", size = 28 }) {
  const ini = String(name).split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase();
  return <span className="ui-avatar" style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}>{ini}</span>;
}
export function Card({ className = "", children, ...rest }) {
  return <div className={`card ui-card ${className}`} {...rest}>{children}</div>;
}
export function StatCard({ label, value, delta, sub }) {
  const up = typeof delta === "number" && delta >= 0;
  return (
    <div className="metric">
      <div className="m-top"><span className="m-label">{label}</span></div>
      <div className="m-val">{value}
        {delta != null && <span className={`m-delta ${up ? "up" : "down"}`}>{up ? "↑" : "↓"} {Math.abs(delta)}%</span>}
      </div>
      {sub && <div className="m-sub">{sub}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- Tooltip (pure CSS) */
export function Tooltip({ tip, children }) {
  return <span className="ui-tip" data-tip={tip}>{children}</span>;
}

/* ---------------------------------------------------------------- EmptyState / Skeleton / Pagination */
export function EmptyState({ icon: Icon = InboxIcon, title, hint, action }) {
  return (
    <div className="emptystate">
      <div className="ei"><Icon size={22} /></div>
      <h3>{title}</h3>
      {hint && <p>{hint}</p>}
      {action && <div className="ea">{action}</div>}
    </div>
  );
}
export function Skeleton({ w = "100%", h = 12, style }) {
  return <div className="sk" style={{ width: w, height: h, ...style }} />;
}
export function Pager({ page, pages, total, pageSize, onPage, onPageSize, sizes = [25, 50, 100] }) {
  return (
    <div className="pager">
      <span>{total != null ? `${total.toLocaleString()} rows` : ""}</span>
      <div className="pr">
        {onPageSize && (
          <Select size="sm" value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
            {sizes.map((s) => <option key={s} value={s}>{s} / page</option>)}
          </Select>
        )}
        <span>Page {page} of {Math.max(pages, 1)}</span>
        <button className="pgbtn" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={15} /></button>
        <button className="pgbtn" disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight size={15} /></button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- FilterPanel (left rail) */
export function FilterPanel({ groups, values, onChange, onClear }) {
  const [open, setOpen] = useState(() => Object.fromEntries(groups.map((g) => [g.key, true])));
  const active = Object.values(values || {}).reduce((n, v) => n + (Array.isArray(v) ? v.length : v ? 1 : 0), 0);
  return (
    <aside className="fp">
      <div className="fp-head">
        <b>Filters</b>
        {active > 0 && <button className="fp-clear" onClick={onClear}>Clear all ({active})</button>}
      </div>
      {groups.map((g) => {
        const sel = values?.[g.key] || [];
        return (
          <div key={g.key} className="fp-group">
            <button className="fp-gh" onClick={() => setOpen((o) => ({ ...o, [g.key]: !o[g.key] }))}>
              <span>{g.label}{sel.length > 0 && <em className="fp-n">{sel.length}</em>}</span>
              <ChevronDown size={14} style={{ transform: open[g.key] ? "" : "rotate(-90deg)", transition: "transform .15s" }} />
            </button>
            {open[g.key] && (
              <div className="fp-opts">
                {g.options.map((o) => {
                  const on = sel.includes(o.value);
                  return (
                    <label key={o.value} className={`fp-opt ${on ? "on" : ""}`}>
                      <input type="checkbox" checked={on}
                        onChange={() => onChange(g.key, on ? sel.filter((v) => v !== o.value) : [...sel, o.value])} />
                      <span className="fp-box">{on && <Check size={11} />}</span>
                      <span className="fp-lbl">{o.label}</span>
                      {o.count != null && <span className="fp-cnt">{o.count}</span>}
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </aside>
  );
}

/* ---------------------------------------------------------------- ConfirmDialog */
export function ConfirmDialog({ title, message, confirmLabel = "Confirm", danger = false, onConfirm, onClose }) {
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="box" style={{ width: 420 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
          {danger && <span className="cd-warn"><AlertTriangle size={18} /></span>}
          <div>
            <h2 style={{ marginBottom: 6 }}>{title}</h2>
            <p style={{ color: "var(--muted)", fontSize: 13.5 }}>{message}</p>
          </div>
        </div>
        <div className="actions">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</Button>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Toast */
const ToastCtx = createContext(null);
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((msg, tone = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <span className="tdot" />{t.msg}
            <button onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}><X size={13} /></button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export function useToast() {
  return useContext(ToastCtx) || (() => {});
}

/* ---------------------------------------------------------------- Breadcrumbs / ActivityFeed */
export function Breadcrumbs({ items }) {
  return (
    <nav className="bcrumb">
      {items.map((it, i) => (
        <span key={i}>
          {it.href ? <a href={`#${it.href}`}>{it.label}</a> : <b>{it.label}</b>}
          {i < items.length - 1 && <span className="sep">/</span>}
        </span>
      ))}
    </nav>
  );
}
export function ActivityFeed({ items, empty = "No activity yet" }) {
  if (!items?.length) return <div className="empty" style={{ padding: 14 }}>{empty}</div>;
  return (
    <div className="afeed">
      {items.map((a, i) => (
        <div key={a.id || i} className="af-row">
          <Avatar name={a.actor || a.kind || "•"} size={26} />
          <div className="af-body">
            <div className="af-title">{a.title || a.kind}</div>
            <div className="af-when">{a.subtitle ? `${a.subtitle} · ` : ""}{a.at ? new Date(a.at + (a.at.endsWith("Z") ? "" : "Z")).toLocaleString() : ""}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- RowCard + Row (dashboard/list sections) */
export function RowCard({ title, count, viewAll, action, empty, children, className = "" }) {
  const kids = Array.isArray(children) ? children.flat().filter(Boolean) : children ? [children] : [];
  const isEmpty = kids.length === 0 || (kids.length === 1 && Array.isArray(kids[0]) && kids[0].length === 0);
  return (
    <div className={`card rowcard ${className}`}>
      <div className="rc-head">
        <b>{title}{count != null && <span className="rc-count">{count}</span>}</b>
        {action || (viewAll && <a href={`#${viewAll}`}>View all →</a>)}
      </div>
      <div className="rc-body">
        {isEmpty && empty ? <div className="rc-empty">{empty}</div> : children}
      </div>
    </div>
  );
}
export function Row({ icon: Icon, avatar, title, sub, right, onClick }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag className={`rc-row ${onClick ? "click" : ""}`} onClick={onClick}>
      {avatar ? <Avatar name={avatar} size={28} /> : Icon && <span className="rc-ic"><Icon size={15} /></span>}
      <span className="rc-main">
        <span className="rc-title">{title}</span>
        {sub && <span className="rc-sub">{sub}</span>}
      </span>
      {right && <span className="rc-right">{right}</span>}
    </Tag>
  );
}

/* ---------------------------------------------------------------- document-editor primitives (Blueprint / Agreement / Invoice) */
export function SaveIndicator({ state }) {
  if (state === "saving") return <span className="save-ind saving"><span className="ui-btn-spin dark" /> Saving…</span>;
  if (state === "saved") return <span className="save-ind saved"><Check size={13} /> Saved</span>;
  if (state === "error") return <span className="save-ind error">Save failed</span>;
  return null;
}

/* Debounced auto-save: call setValue on edits; saveFn(value) runs `delay` ms after
   the last edit. Returns [state, flush]. */
export function useAutoSave(value, saveFn, { delay = 1200, enabled = true } = {}) {
  const [state, setState] = useState("idle");
  const first = useRef(true);
  const latest = useRef(value);
  latest.current = value;
  useEffect(() => {
    if (!enabled) return;
    if (first.current) { first.current = false; return; }
    setState("saving");
    const t = setTimeout(async () => {
      try { await saveFn(latest.current); setState("saved"); setTimeout(() => setState("idle"), 2500); }
      catch { setState("error"); }
    }, delay);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeof value === "string" ? value : JSON.stringify(value), enabled]);
  const flush = async () => {
    if (!enabled) return;
    setState("saving");
    try { await saveFn(latest.current); setState("saved"); setTimeout(() => setState("idle"), 2500); }
    catch { setState("error"); }
  };
  return [state, flush];
}

export function VersionList({ versions, onRestore, onOpen, currentLabel }) {
  if (!versions?.length) return <div className="rc-empty">No versions yet.</div>;
  return (
    <div className="vlist">
      {versions.map((v, i) => (
        <div key={v.id ?? i} className="vrow">
          <span className="vdot" />
          <span className="vmain">
            <b>{v.label || `Version ${v.version ?? versions.length - i}`}</b>
            <em>{v.at ? new Date(v.at + (String(v.at).endsWith("Z") ? "" : "Z")).toLocaleString() : v.status || ""}</em>
          </span>
          {v.current
            ? <span className="pill-badge pb-blue"><span className="bd" />{currentLabel || "current"}</span>
            : onOpen ? <Button size="sm" variant="ghost" onClick={() => onOpen(v)}>Open</Button>
            : onRestore ? <Button size="sm" variant="ghost" onClick={() => onRestore(v, i)}>Restore</Button> : null}
        </div>
      ))}
    </div>
  );
}

export function CommentsPanel({ comments, onAdd, me = "You" }) {
  const [text, setText] = useState("");
  const submit = () => { if (text.trim()) { onAdd(text.trim()); setText(""); } };
  return (
    <div className="cmts">
      {(comments || []).length === 0 && <div className="rc-empty">No comments yet.</div>}
      {(comments || []).map((c, i) => (
        <div key={c.id ?? i} className="cmt">
          <Avatar name={c.author || me} size={24} />
          <div className="cmt-b">
            <div className="cmt-h"><b>{c.author || me}</b>
              <em>{c.at ? new Date(String(c.at) + (String(c.at).endsWith("Z") ? "" : "Z")).toLocaleString() : ""}</em></div>
            <div className="cmt-t">{c.text}</div>
          </div>
        </div>
      ))}
      <div className="cmt-in">
        <input value={text} placeholder="Add a comment…" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()} />
        <Button size="sm" onClick={submit} disabled={!text.trim()}>Post</Button>
      </div>
    </div>
  );
}

/* Vertical progress of a document lifecycle (draft → sent → signed → executed …). */
export function StatusSteps({ steps, current }) {
  const idx = steps.findIndex((s) => s.key === current);
  return (
    <div className="ssteps">
      {steps.map((s, i) => (
        <div key={s.key} className={`sstep ${i < idx ? "done" : ""} ${i === idx ? "now" : ""}`}>
          <span className="ss-rail"><span className="ss-dot">{i < idx ? <Check size={10} /> : null}</span>
            {i < steps.length - 1 && <span className="ss-line" />}</span>
          <span className="ss-body"><b>{s.label}</b>{s.sub && <em>{s.sub}</em>}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- JourneyTimeline (the Revenue Timeline) */
const JT_ICONS = {}; // filled lazily below to avoid a big import block here
export function JourneyTimeline({ events, milestones, revenue }) {
  const reachedKeys = new Set((milestones || []).filter((m) => m.reached_at).map((m) => m.key));
  const MILESTONE_LABEL = {
    lead: "Lead", outreach: "Outreach", reply_positive: "Positive reply", meeting: "Meeting",
    blueprint: "Blueprint", agreement: "Agreement", signature: "Signed", invoice: "Invoice",
    revenue: "Revenue", live: "Live",
  };
  return (
    <div className="jt">
      <div className="jt-miles">
        {(milestones || []).map((m) => (
          <span key={m.key} className={`jt-mile ${m.reached_at ? "on" : ""}`}
            title={m.reached_at ? new Date(m.reached_at + "Z").toLocaleString() : "not reached yet"}>
            {MILESTONE_LABEL[m.key] || m.key}
          </span>
        ))}
        {revenue > 0 && <span className="jt-rev">${Math.round(revenue).toLocaleString()} collected</span>}
      </div>
      <div className="jt-rail">
        {(events || []).length === 0 && <div className="rc-empty">The journey starts with the first touch.</div>}
        {(events || []).map((e, i) => (
          <div key={i} className={`jt-ev jt-${e.kind}`}>
            <span className="jt-dot" />
            <span className="jt-body">
              <span className="jt-title">
                {e.href ? <a href={`#${e.href}`}>{e.title}</a> : e.title}
                {e.detail && <em> · {e.detail}</em>}
              </span>
              <span className="jt-when">{new Date(e.at + (String(e.at).endsWith("Z") ? "" : "Z")).toLocaleString()}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- misc */
export const Kbd = ({ children }) => <kbd className="ui-kbd">{children}</kbd>;
export function useDebounced(value, ms = 150) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}
export function useClickOutside(ref, onOut) {
  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) onOut(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, onOut]);
}
