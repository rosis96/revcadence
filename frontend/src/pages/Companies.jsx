import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Modal, Spinner, fitTone, useApi } from "../components";

export function NewCompanyModal({ onClose, onCreated, workspaceId, workspaces }) {
  const [form, setForm] = useState({ name: "", website: "", workspace_id: workspaceId || (workspaces[0]?.id ?? "") });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const r = await api("/api/companies", { method: "POST", body: { ...form, workspace_id: Number(form.workspace_id) } });
      onCreated(r.id);
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  return (
    <Modal title="New company" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="error-box" style={{ marginBottom: 10 }}>{error}</div>}
        {!workspaceId && (
          <div className="field"><label>Workspace</label>
            <select value={form.workspace_id} onChange={(e) => setForm({ ...form, workspace_id: e.target.value })}>
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}
        <div className="field"><label>Name</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus /></div>
        <div className="field"><label>Website</label>
          <input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} placeholder="acme.com" /></div>
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create"}</button>
        </div>
      </form>
    </Modal>
  );
}

// pipeline-status chip order (matches stage progression)
export const STATUS_ORDER = ["interested", "meeting_booked", "meeting_completed", "no_show",
                             "follow_up", "won", "client", "none"];
// The Companies/Contacts lists are for real conversations — a meeting was booked
// or beyond. Interested + no-deal are hidden by default (reachable via their chip).
export const BOOKED_PLUS = new Set(["meeting_booked", "meeting_completed", "no_show", "follow_up", "won", "client"]);

export function StatusPill({ status }) {
  if (!status) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600,
                   padding: "2px 10px", borderRadius: 999, color: status.color,
                   background: status.color + "1f", border: `1px solid ${status.color}44` }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: status.color }} />{status.label}
    </span>
  );
}

export default function Companies() {
  const { wsParam, me } = useAuth();
  const [q, setQ] = useState("");
  const [modal, setModal] = useState(false);
  const [filter, setFilter] = useState("__booked");   // default: meetings booked & beyond
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/companies", { workspace_id: wsParam, q });

  const del = async (e, c) => {
    e.stopPropagation();
    if (!confirm(`Delete "${c.name}" and all its contacts, deals, documents & profile? This can't be undone.`)) return;
    try { await api(`/api/companies/${c.id}`, { method: "DELETE" }); reload(); }
    catch (err) { alert(err.message); }
  };

  const counts = {};
  (data || []).forEach((c) => { const k = c.status?.key || "none"; counts[k] = (counts[k] || 0) + 1; });
  const bookedCount = (data || []).filter((c) => BOOKED_PLUS.has(c.status?.key)).length;
  const chips = STATUS_ORDER.filter((k) => counts[k]);
  const colorFor = (k) => (data || []).find((c) => c.status?.key === k)?.status?.color || "#64748b";
  const labelFor = (k) => (data || []).find((c) => c.status?.key === k)?.status?.label || k;
  const shown = (data || []).filter((c) => {
    const k = c.status?.key || "none";
    if (filter === "__booked") return BOOKED_PLUS.has(k);
    if (filter === "") return true;
    return k === filter;
  });

  const Chip = ({ on, color, onClick, children }) => (
    <button onClick={onClick}
            style={{ cursor: "pointer", fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 999,
                     border: `1px solid ${color}55`, background: on ? color : color + "1f", color: on ? "#fff" : color }}>
      {children}
    </button>
  );

  return (
    <>
      <div className="toolbar">
        <input type="text" placeholder="Search companies…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="spacer" />
        <button className="btn" onClick={() => setModal(true)}>+ New company</button>
      </div>

      {data && data.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "4px 0 12px", alignItems: "center" }}>
          <Chip on={filter === "__booked"} color="#3b82f6" onClick={() => setFilter("__booked")}>Meetings · {bookedCount}</Chip>
          <Chip on={filter === ""} color="#111827" onClick={() => setFilter("")}>All · {data.length}</Chip>
          <span style={{ width: 1, height: 18, background: "var(--line,#e5e7eb)", margin: "0 2px" }} />
          {chips.map((k) => (
            <Chip key={k} on={filter === k} color={colorFor(k)} onClick={() => setFilter(filter === k ? "__booked" : k)}>
              {labelFor(k)} · {counts[k]}
            </Chip>
          ))}
        </div>
      )}

      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="◫" title="No companies" hint="Create one or import via enrichment." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Status</th><th>Domain</th><th>Industry</th><th>ICP fit</th><th></th></tr></thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id} className="click" onClick={() => nav(`/companies/${c.id}`)}>
                <td><b>{c.name}</b></td>
                <td><StatusPill status={c.status} /></td>
                <td style={{ color: "var(--muted)" }}>{c.domain || "—"}</td>
                <td>{c.industry || "—"}</td>
                <td>{c.icp_fit ? <Badge tone={fitTone(c.icp_fit)}>{c.icp_fit}</Badge> : <Badge>not enriched</Badge>}</td>
                <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                  <button className="btn danger sm" onClick={(e) => del(e, c)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {modal && (
        <NewCompanyModal workspaceId={wsParam} workspaces={me.workspaces} onClose={() => setModal(false)}
                         onCreated={(id) => { setModal(false); nav(`/companies/${id}`); }} />
      )}
    </>
  );
}
