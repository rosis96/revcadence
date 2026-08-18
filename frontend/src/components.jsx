import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { X } from "lucide-react";
import { api, money } from "./api";
import { backdropMotion, currentOrigin, dialogMotion, drawerMotion, isTopOverlay } from "./ui/motion";

/* Phase 0 design system: all new primitives live in src/ui/ and are re-exported
   here so pages keep a single import path. */
export * from "./ui";
export { DataTable } from "./ui/DataTable";
export { CommandPalette } from "./ui/CommandPalette";

// Tiny data hook: loading / error / reload — used by every page.
export function useApi(path, params, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    if (!path) {
      setData(null); setError(""); setLoading(false);
      return;
    }
    setLoading(true); setError("");
    api(path, { params }).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, JSON.stringify(params), ...deps]);
  // Quiet refresh: fetch fresh data WITHOUT flipping the loading spinner, so
  // background polls and syncs update in place instead of blanking the view.
  const refresh = useCallback(() => {
    if (!path) return Promise.resolve();
    return api(path, { params }).then(setData).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, JSON.stringify(params), ...deps]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload, refresh };
}

export const Spinner = () => <div className="center"><div className="spinner" /></div>;
export const ErrorBox = ({ msg, retry }) => (
  <div className="error-box">
    {msg} {retry && <button className="btn ghost sm" style={{ marginLeft: 10 }} onClick={retry}>Retry</button>}
  </div>
);
export const Empty = ({ icon = "○", title, hint }) => (
  <div className="empty card"><div className="big">{icon}</div><b>{title}</b><div style={{ marginTop: 4 }}>{hint}</div></div>
);

export function Badge({ children, tone = "" }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

// Deal value with EST fallback: real value renders exact; a $0/blank deal shows the
// workspace ACV default framed as an estimate, so pipeline never reads as unconfigured.
export function MoneyEst({ value, acv = 0 }) {
  const n = Number(value) || 0;
  if (n > 0) return <span className="val-exact">{money(n)}</span>;
  if (acv > 0)
    return (
      <span className="val-estimated" title={`Estimated from default ACV (${money(acv)})`}>
        {money(acv)}<span className="est-tag">EST</span>
      </span>
    );
  return <span className="val-none">—</span>;
}

// Semantic status pill (reusable across Lists/Database/CRM). tone: green/blue/red/amber/gray/indigo
export function StatusBadge({ tone = "gray", children }) {
  return <span className={`pill-badge pb-${tone}`}><span className="bd" />{children}</span>;
}

// Compact metric card for page summaries.
export function Metric({ icon, label, value, sub }) {
  return (
    <div className="metric">
      <div className="m-top">{icon && <span className="m-ic">{icon}</span>}<span className="m-label">{label}</span></div>
      <div className="m-val">{value}</div>
      {sub && <div className="m-sub">{sub}</div>}
    </div>
  );
}

// Standard page header: page actions only. Page names and descriptions are
// intentionally omitted to keep the workspace chrome minimal.
export function PageHeader({ actions }) {
  if (!actions) return null;
  return <div className="page-head page-head-actions"><div className="acts">{actions}</div></div>;
}

// Skeleton table rows while loading.
export function SkeletonRows({ cols = 6, rows = 8 }) {
  return [...Array(rows)].map((_, r) => (
    <tr key={r}>
      {[...Array(cols)].map((_, c) => (
        <td key={c}><div className="sk" style={{ width: c === 0 ? "70%" : `${40 + ((r + c) % 4) * 12}%` }} /></td>
      ))}
    </tr>
  ));
}
export const fitTone = (fit) => ({ strong: "green", possible: "indigo", weak: "amber" }[fit] || "");
export const scoreTone = (s) => (s >= 60 ? "green" : s >= 35 ? "indigo" : s > 0 ? "amber" : "");

export function Drawer({ title, onClose, children, className = "" }) {
  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <>
      <motion.div className="drawer-bg" onClick={onClose} {...backdropMotion} />
      <motion.div className={`drawer ${className}`} {...drawerMotion}>
        <button className="close" onClick={onClose}>✕</button>
        <h2>{title}</h2>
        {children}
      </motion.div>
    </>
  );
}

// `originRef` makes the dialog grow out of the control that opened it instead of
// appearing from nowhere — the button stays the subject and the eye follows it to
// the centre. Omit it and the dialog simply scales up in place, so every existing
// call site keeps working unchanged.
// Exit animation needs an <AnimatePresence> around the call site; without one the
// enter still plays and unmount is immediate.
export function Modal({ title, onClose, originRef, closeButton = false, children }) {
  // Measured once, on open — that is exactly the position we want to fly from.
  // Falls back to the last pointer press so a dialog opened without a ref still
  // grows from where the user clicked rather than from nowhere.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const motionProps = useMemo(() => dialogMotion(originRef?.current || currentOrigin()), []);
  // A popup opened from inside the dialog (icon picker, Select menu) portals ABOVE
  // it, so a click meant to dismiss the popup would otherwise also close the dialog
  // underneath. One click closes the popup; the next closes the dialog.
  const backdropDown = (e) => {
    if (e.target !== e.currentTarget) return;
    if (document.querySelector(".inline-popup")) return;
    onClose();
  };
  // Esc closes. Owned here rather than at each call site so a modal that forgets
  // to wire it is not a modal you cannot dismiss from the keyboard — and gated
  // on being the top layer so one keypress never closes two.
  const shell = useRef(null);
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape" && isTopOverlay(shell.current)) onClose?.(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <motion.div ref={shell} className="modal" onMouseDown={backdropDown} {...backdropMotion}>
      <motion.div className="box" {...motionProps}>
        {closeButton && (
          <motion.button type="button" className="modal-x" aria-label="Close" onClick={onClose}
            whileHover={{ rotate: 180 }} transition={{ type: "spring", stiffness: 260, damping: 20 }}>
            <X size={18} strokeWidth={2} />
          </motion.button>
        )}
        {title && <h2>{title}</h2>}{children}
      </motion.div>
    </motion.div>
  );
}

function dayLabel(at) {
  if (!at) return "Earlier";
  const d = new Date(at + (at.endsWith("Z") ? "" : "Z"));
  const now = new Date();
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(d)) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: now.getFullYear() === d.getFullYear() ? undefined : "numeric" });
}

export function Timeline({ items }) {
  if (!items?.length) return <div className="empty" style={{ padding: 14 }}>No activity yet</div>;
  const groups = [];
  for (const a of items) {
    const label = dayLabel(a.at);
    let g = groups[groups.length - 1];
    if (!g || g.label !== label) { g = { label, rows: [] }; groups.push(g); }
    g.rows.push(a);
  }
  return (
    <div className="rc-tl-groups">
      {groups.map((g, gi) => (
        <div key={gi} className="rc-tl-group">
          <div className="rc-tl-daylabel">{g.label}</div>
          <ul className="timeline">
            {g.rows.map((a, i) => (
              <li key={a.id ?? i}>
                <div>{a.title || a.kind}</div>
                <div className="when">{a.kind}{a.at ? " · " + new Date(a.at + (a.at.endsWith("Z") ? "" : "Z")).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : ""}</div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
