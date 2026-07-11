import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

// Tiny data hook: loading / error / reload — used by every page.
export function useApi(path, params, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true); setError("");
    api(path, { params }).then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, JSON.stringify(params), ...deps]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, loading, reload };
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
export const fitTone = (fit) => ({ strong: "green", possible: "indigo", weak: "amber" }[fit] || "");
export const scoreTone = (s) => (s >= 60 ? "green" : s >= 35 ? "indigo" : s > 0 ? "amber" : "");

export function Drawer({ title, onClose, children }) {
  useEffect(() => {
    const h = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <div className="drawer">
        <button className="close" onClick={onClose}>✕</button>
        <h2>{title}</h2>
        {children}
      </div>
    </>
  );
}

export function Modal({ title, onClose, children }) {
  return (
    <div className="modal" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="box"><h2>{title}</h2>{children}</div>
    </div>
  );
}

export function Timeline({ items }) {
  if (!items?.length) return <div className="empty" style={{ padding: 14 }}>No activity yet</div>;
  return (
    <ul className="timeline">
      {items.map((a) => (
        <li key={a.id}>
          <div>{a.title || a.kind}</div>
          <div className="when">{a.kind} · {a.at ? new Date(a.at + "Z").toLocaleString() : ""}</div>
        </li>
      ))}
    </ul>
  );
}
