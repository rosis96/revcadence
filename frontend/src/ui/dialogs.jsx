// In-app dialogs (confirm / prompt / alert) that replace the browser's native
// window.confirm/prompt/alert ("engine.revcadence.com says…") popups with our own
// modal styled inside the dashboard. Callable imperatively from anywhere:
//   if (!(await confirmDialog("Delete this?"))) return;
//   const name = await promptDialog("Save view as:");
//   await alertDialog("Something went wrong");
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { backdropMotion, currentOrigin, dialogMotion, isTopOverlay, trackPointerOrigin } from "./motion";

let _show = null;          // installed by <GlobalDialogs/>
const _queue = [];

function request(opts) {
  return new Promise((resolve) => {
    // Captured at request time: by the time this renders, focus has moved.
    const item = { ...opts, resolve, origin: currentOrigin() };
    if (_show) _show(item);
    else _queue.push(item);
  });
}

export function confirmDialog(message, opts = {}) {
  return request({
    kind: "confirm", message, title: opts.title || "Please confirm",
    confirmText: opts.confirmText || "Confirm", cancelText: opts.cancelText || "Cancel",
    danger: !!opts.danger,
  });
}
export function promptDialog(message, opts = {}) {
  return request({
    kind: "prompt", message, title: opts.title || "",
    placeholder: opts.placeholder || "", defaultValue: opts.defaultValue || "",
    confirmText: opts.confirmText || "OK", cancelText: opts.cancelText || "Cancel",
  });
}
export function alertDialog(message, opts = {}) {
  return request({ kind: "alert", message, title: opts.title || "Heads up", confirmText: "OK" });
}

export function GlobalDialogs() {
  const [item, setItem] = useState(null);
  const [val, setVal] = useState("");

  useEffect(() => {
    _show = (it) => setItem((cur) => { if (cur) { _queue.push(it); return cur; } setVal(it.defaultValue || ""); return it; });
    if (_queue.length && !item) { const q = _queue.shift(); setVal(q.defaultValue || ""); setItem(q); }
    const untrack = trackPointerOrigin();
    return () => { _show = null; untrack(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const finish = (result) => {
    item.resolve(result);
    const next = _queue.shift() || null;
    setVal(next?.defaultValue || "");
    setItem(next);
  };
  const onCancel = () => finish(item?.kind === "prompt" ? null : false);
  const onConfirm = () => finish(item?.kind === "prompt" ? val : (item?.kind === "alert" ? undefined : true));

  // Esc cancels — but only while this is the top layer. An imperative confirm is
  // usually opened FROM a dialog, and one keypress must not close both.
  const shell = useRef(null);
  useEffect(() => {
    if (!item) return;
    const h = (e) => { if (e.key === "Escape" && isTopOverlay(shell.current)) onCancel(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item]);

  // AnimatePresence lives outside the null check so the box can animate OUT —
  // returning null early would rip it from the tree with no exit.
  return (
    <AnimatePresence>
      {item && (
        <motion.div ref={shell} key="dlg" className="modal" {...backdropMotion}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
          <motion.div className="box" style={{ width: 460, maxWidth: "94vw" }}
            onMouseDown={(e) => e.stopPropagation()} {...dialogMotion(item.origin)}>
            {item.title && <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 700 }}>{item.title}</h3>}
            <div style={{ fontSize: 13.5, color: "var(--muted)", whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{item.message}</div>
            {item.kind === "prompt" && (
              <input autoFocus value={val} placeholder={item.placeholder}
                onChange={(e) => setVal(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") onConfirm(); if (e.key === "Escape") onCancel(); }}
                style={{ width: "100%", marginTop: 12 }} />
            )}
            <div className="actions" style={{ marginTop: 16, display: "flex", gap: 8, justifyContent: "flex-end" }}>
              {item.kind !== "alert" && (
                <button className="btn ghost" onClick={onCancel}>{item.cancelText}</button>
              )}
              <button className={`btn ${item.danger ? "danger" : ""}`} autoFocus={item.kind !== "prompt"} onClick={onConfirm}>
                {item.confirmText}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
