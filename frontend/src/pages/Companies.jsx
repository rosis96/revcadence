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

export default function Companies() {
  const { wsParam, me } = useAuth();
  const [q, setQ] = useState("");
  const [modal, setModal] = useState(false);
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/companies", { workspace_id: wsParam, q });
  return (
    <>
      <div className="toolbar">
        <input type="text" placeholder="Search companies…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="spacer" />
        <button className="btn" onClick={() => setModal(true)}>+ New company</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="◫" title="No companies" hint="Create one or import via enrichment." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Domain</th><th>Industry</th><th>ICP fit</th></tr></thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.id} className="click" onClick={() => nav(`/companies/${c.id}`)}>
                <td><b>{c.name}</b></td>
                <td style={{ color: "var(--muted)" }}>{c.domain || "—"}</td>
                <td>{c.industry || "—"}</td>
                <td>{c.icp_fit ? <Badge tone={fitTone(c.icp_fit)}>{c.icp_fit}</Badge> : <Badge>not enriched</Badge>}</td>
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
