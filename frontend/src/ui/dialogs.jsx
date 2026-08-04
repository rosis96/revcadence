// In-app dialogs (confirm / prompt / alert) that replace the browser's native
// window.confirm/prompt/alert ("engine.revcadence.com says…") popups with our own
// modal styled inside the dashboard. Callable imperatively from anywhere:
//   if (!(await confirmDialog("Delete this?"))) return;
//   const name = await promptDialog("Save view as:");
//   await alertDialog("Something went wrong");
import { useEffect, useState } from "react";

let _show = null;          // installed by <GlobalDialogs/>
const _queue = [];

function request(opts) {
  return new Promise((resolve) => {
    const item = { ...opts, resolve };
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
    return () => { _show = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!item) return null;
  const finish = (result) => {
    item.resolve(result);
    const next = _queue.shift() || null;
    setVal(next?.defaultValue || "");
    setItem(next);
  };
  const onCancel = () => finish(item.kind === "prompt" ? null : false);
  const onConfirm = () => finish(item.kind === "prompt" ? val : (item.kind === "alert" ? undefined : true));

  return (
    <div className="modal" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="box" style={{ width: 460, maxWidth: "94vw" }} onMouseDown={(e) => e.stopPropagation()}>
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
      </div>
    </div>
  );
}
