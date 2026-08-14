// Blueprints list + "New from transcript": pick a company, paste the Fathom
// call transcript, and generate a personalized client blueprint.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Modal, Spinner, useApi } from "../components";
import { alertDialog } from "../components";
import { Select } from "../components";

const statusTone = { draft: "amber", published: "green", viewed: "green", executed: "green" };

export default function Blueprints() {
  const { wsParam, me } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/documents", { workspace_id: wsParam });
  const wsName = (id) => me.workspaces.find((w) => w.id === id)?.name || `#${id}`;

  const [modal, setModal] = useState("");   // "" | "transcript" | "upload"
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const { data: companies } = useApi(modal ? "/api/companies" : null, { workspace_id: wsParam });
  const [companyId, setCompanyId] = useState("");
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState(false);
  // upload flow
  const [upTitle, setUpTitle] = useState("");
  const [upHtml, setUpHtml] = useState("");
  const [upFileName, setUpFileName] = useState("");

  useEffect(() => { if (companies?.length && !companyId) setCompanyId(String(companies[0].id)); }, [companies]);

  const create = async () => {
    if (!wsId) { alertDialog("Pick a specific workspace first (top-left)."); return; }
    if (!companyId) { alertDialog("Pick a company."); return; }
    if (!transcript.trim()) { alertDialog("Paste the call transcript."); return; }
    setBusy(true);
    try {
      const doc = await api("/api/blueprints/from-transcript", { method: "POST",
        body: { workspace_id: Number(wsId), company_id: Number(companyId), transcript } });
      nav(`/blueprints/${doc.id}`);
    } catch (e) { alertDialog(e.message); }
    setBusy(false);
  };

  const onFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setUpFileName(f.name);
    const r = new FileReader();
    r.onload = () => {
      setUpHtml(String(r.result || ""));
      if (!upTitle) setUpTitle(f.name.replace(/\.(html?|htm)$/i, ""));
    };
    r.readAsText(f);
  };

  const upload = async () => {
    if (!wsId) { alertDialog("Pick a specific workspace first (top-left)."); return; }
    if (!upHtml.trim()) { alertDialog("Choose an HTML file or paste the markup."); return; }
    setBusy(true);
    try {
      const doc = await api("/api/blueprints/upload", { method: "POST",
        body: { workspace_id: Number(wsId), company_id: companyId ? Number(companyId) : null,
                title: upTitle || null, html: upHtml } });
      nav(`/blueprints/${doc.id}`);
    } catch (e) { alertDialog(e.message); }
    setBusy(false);
  };

  return (
    <>
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <h1 style={{ fontSize: 18 }}>Blueprints & Agreements</h1>
        <span style={{ color: "var(--muted)", fontSize: 12.5 }}>Deals in progress — proposals you're discussing</span>
        <div className="spacer" />
        <button className="btn ghost" onClick={() => setModal("upload")}>⬆ Upload blueprint (HTML)</button>
        <button className="btn" onClick={() => setModal("transcript")}>+ New blueprint (from transcript)</button>
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

      {modal === "transcript" && (
        <Modal title="New blueprint from a call transcript" onClose={() => setModal("")}>
          <div className="field"><label>Company</label>
            <Select value={companyId} onChange={(e) => setCompanyId(e.target.value)} style={{ width: "100%" }}>
              {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
            {(!companies || companies.length === 0) && (
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>No companies in this workspace yet — add one in CRM first.</div>
            )}
          </div>
          <div className="field"><label>Fathom transcript</label>
            <textarea rows={10} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                      value={transcript} onChange={(e) => setTranscript(e.target.value)}
                      placeholder="Paste the full call transcript or Fathom summary here…" /></div>
          <div className="actions">
            <button type="button" className="btn ghost" onClick={() => setModal("")}>Cancel</button>
            <button className="btn" disabled={busy} onClick={create}>{busy ? "Generating…" : "Generate blueprint"}</button>
          </div>
        </Modal>
      )}

      {modal === "upload" && (
        <Modal title="Upload a custom blueprint" onClose={() => setModal("")}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            Bring your own page — upload an HTML file (or paste the markup) you built outside the system.
            It gets its own slug and public link, and publishes exactly like a generated blueprint.</p>
          <div className="field"><label>Company (optional)</label>
            <Select value={companyId} onChange={(e) => setCompanyId(e.target.value)} style={{ width: "100%" }}>
              <option value="">— none —</option>
              {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </Select>
          </div>
          <div className="field"><label>Title</label>
            <input value={upTitle} onChange={(e) => setUpTitle(e.target.value)}
                   placeholder="e.g. Acme — Growth Blueprint" style={{ width: "100%" }} /></div>
          <div className="field"><label>HTML file</label>
            <input type="file" accept=".html,.htm,text/html" onChange={onFile} />
            {upFileName && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Loaded: {upFileName} ({upHtml.length.toLocaleString()} chars)</div>}
          </div>
          <div className="field"><label>…or paste HTML</label>
            <textarea rows={8} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                      value={upHtml} onChange={(e) => { setUpHtml(e.target.value); setUpFileName(""); }}
                      placeholder="<!doctype html> …" /></div>
          <div className="actions">
            <button type="button" className="btn ghost" onClick={() => setModal("")}>Cancel</button>
            <button className="btn" disabled={busy} onClick={upload}>{busy ? "Uploading…" : "Create blueprint"}</button>
          </div>
        </Modal>
      )}
    </>
  );
}
