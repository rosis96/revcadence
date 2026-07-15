// Blueprints list + "New from transcript": pick a company, paste the Fathom
// call transcript, and generate a personalized client blueprint.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Modal, Spinner, useApi } from "../components";

const statusTone = { draft: "amber", published: "green", viewed: "green", executed: "green" };

export default function Blueprints() {
  const { wsParam, me } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/documents", { workspace_id: wsParam });
  const wsName = (id) => me.workspaces.find((w) => w.id === id)?.name || `#${id}`;

  const [modal, setModal] = useState(false);
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const { data: companies } = useApi(modal ? "/api/companies" : null, { workspace_id: wsParam });
  const [companyId, setCompanyId] = useState("");
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (companies?.length && !companyId) setCompanyId(String(companies[0].id)); }, [companies]);

  const create = async () => {
    if (!wsId) { alert("Pick a specific workspace first (top-left)."); return; }
    if (!companyId) { alert("Pick a company."); return; }
    if (!transcript.trim()) { alert("Paste the call transcript."); return; }
    setBusy(true);
    try {
      const doc = await api("/api/blueprints/from-transcript", { method: "POST",
        body: { workspace_id: Number(wsId), company_id: Number(companyId), transcript } });
      nav(`/blueprints/${doc.id}`);
    } catch (e) { alert(e.message); }
    setBusy(false);
  };

  return (
    <>
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <h1 style={{ fontSize: 18 }}>Blueprints & Agreements</h1>
        <span style={{ color: "var(--muted)", fontSize: 12.5 }}>Deals in progress — proposals you're discussing</span>
        <div className="spacer" />
        <button className="btn" onClick={() => setModal(true)}>+ New blueprint (from transcript)</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && (
        <Empty icon="▤" title="No blueprints yet" hint="Click + New blueprint, pick a company, and paste a Fathom call transcript." />
      )}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Title</th><th>Workspace</th><th>Status</th><th>Slug</th><th>Views</th></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.id} className="click" onClick={() => nav(`/blueprints/${d.id}`)}>
                <td><b>{d.title || d.slug}</b></td>
                <td>{wsName(d.workspace_id)}</td>
                <td><Badge tone={statusTone[d.status] || ""}>{d.status}</Badge></td>
                <td style={{ color: "var(--muted)", fontFamily: "monospace", fontSize: 12 }}>{d.slug}</td>
                <td>{d.view_count || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {modal && (
        <Modal title="New blueprint from a call transcript" onClose={() => setModal(false)}>
          <div className="field"><label>Company</label>
            <select value={companyId} onChange={(e) => setCompanyId(e.target.value)} style={{ width: "100%" }}>
              {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            {(!companies || companies.length === 0) && (
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>No companies in this workspace yet — add one in CRM first.</div>
            )}
          </div>
          <div className="field"><label>Fathom transcript</label>
            <textarea rows={10} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                      value={transcript} onChange={(e) => setTranscript(e.target.value)}
                      placeholder="Paste the full call transcript or Fathom summary here…" /></div>
          <div className="actions">
            <button type="button" className="btn ghost" onClick={() => setModal(false)}>Cancel</button>
            <button className="btn" disabled={busy} onClick={create}>{busy ? "Generating…" : "Generate blueprint"}</button>
          </div>
        </Modal>
      )}
    </>
  );
}
