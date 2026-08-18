import { alertDialog, confirmDialog } from "../components";
// Outbound → Lists: named lead lists per workspace (the old dashboard's Lists).
import { useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { enrichBase } from "../clientspace/modules";
import { Empty, ErrorBox, Modal, Spinner, useApi } from "../components";

// Reuse the CSV machinery from the companies-enrichment page.
export function parseCsv(text) {
  const rows = [];
  let cur = [""], inQ = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"' && text[i + 1] === '"') { cur[cur.length - 1] += '"'; i++; }
      else if (ch === '"') inQ = false;
      else cur[cur.length - 1] += ch;
    } else if (ch === '"') inQ = true;
    else if (ch === ",") cur.push("");
    else if (ch === "\n" || ch === "\r") {
      if (cur.length > 1 || cur[0] !== "") rows.push(cur);
      cur = [""];
      if (ch === "\r" && text[i + 1] === "\n") i++;
    } else cur[cur.length - 1] += ch;
  }
  if (cur.length > 1 || cur[0] !== "") rows.push(cur);
  return rows;
}
const HEADER_MAP = {
  first_name: ["first_name", "firstname", "first name", "first"],
  last_name: ["last_name", "lastname", "last name", "last"],
  email: ["email", "email address", "e-mail"],
  title: ["title", "job title", "position", "role"],
  company: ["company", "company_name", "company name", "organization"],
  website: ["website", "company website", "domain", "url", "company_website"],
};
export function mapRows(csvRows) {
  const headers = csvRows[0].map((h) => (h || "").trim());
  const lower = headers.map((h) => h.toLowerCase());
  const idx = {};
  for (const [f, names] of Object.entries(HEADER_MAP)) {
    const i = lower.findIndex((h) => names.includes(h));
    if (i >= 0) idx[f] = i;
  }
  return csvRows.slice(1).map((r) => {
    const row = {};
    // preserve EVERY uploaded column under its original header (in order)
    headers.forEach((h, i) => { if (h) row[h] = (r[i] || "").trim(); });
    // plus the normalized standard fields the backend uses to fill model columns
    for (const [f, i] of Object.entries(idx)) row[f] = (r[i] || "").trim();
    return row;
  });
}

export default function EnrichLists() {
  const { wsParam, me } = useAuth();
  const nav = useNavigate();
  // Mounted at two bases — `/enrichment` for us, `/w/<slug>/enrichment` for the
  // client — so a row click resolves from the URL this screen was opened at.
  const base = enrichBase(useLocation().pathname);
  const { data, error, loading, reload } = useApi("/api/enrich-lists", { workspace_id: wsParam });
  const [modal, setModal] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const pendingFile = useRef(null);

  const createList = async (e) => {
    e.preventDefault();
    const targetWs = wsParam || (me.is_master ? null : me.workspaces[0]?.id);
    if (!targetWs) { alertDialog("Pick a specific workspace first (top-left)."); return; }
    setBusy(true);
    try {
      const r = await api("/api/enrich-lists", { method: "POST",
        body: { workspace_id: Number(targetWs), name } });
      if (pendingFile.current) {
        const rows = mapRows(parseCsv(await pendingFile.current.text()));
        const chunks = [];
        for (let i = 0; i < rows.length; i += 2000) chunks.push(rows.slice(i, i + 2000));
        for (const chunk of chunks) {
          await api(`/api/enrich-lists/${r.id}/import`, { method: "POST", body: { rows: chunk } });
        }
      }
      setModal(false); setName(""); pendingFile.current = null;
      nav(`${base}/lists/${r.id}`);
    } catch (err) { alertDialog(err.message); }
    setBusy(false);
  };

  const remove = async (id) => {
    if (!await confirmDialog("Delete this list and all its leads?")) return;
    try { await api(`/api/enrich-lists/${id}`, { method: "DELETE" }); reload(); }
    catch (e) { alertDialog(e.message); }
  };

  return (
    <>
      <div className="toolbar">
        <div className="spacer" />
        <button className="btn" onClick={() => setModal(true)}>+ New list (import CSV)</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && (
        <Empty icon="▦" title="No lists yet" hint="Import a CSV of leads (name, email, title, company, website) to start the Verify → Enrich pipeline." />
      )}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>List</th><th>Leads</th><th>Created</th><th></th></tr></thead>
          <tbody>
            {data.map((l) => (
              <tr key={l.id} className="click" onClick={() => nav(`${base}/lists/${l.id}`)}>
                <td><b>{l.name}</b></td>
                <td>{l.leads.toLocaleString()}</td>
                <td style={{ color: "var(--muted)" }}>{new Date(l.created_at + "Z").toLocaleDateString()}</td>
                <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                  <button className="btn danger sm" onClick={() => remove(l.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <AnimatePresence>
      {modal && (
        <Modal key="newlist" title="New list" onClose={() => setModal(false)}>
          <form onSubmit={createList}>
            <div className="field"><label>List name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></div>
            <div className="field"><label>CSV file (optional — headers: first_name, last_name, email, title, company, website)</label>
              <input type="file" accept=".csv,text/csv" ref={fileRef}
                     onChange={(e) => { pendingFile.current = e.target.files[0] || null; }} /></div>
            <div className="actions">
              <button type="button" className="btn ghost" onClick={() => setModal(false)}>Cancel</button>
              <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create list"}</button>
            </div>
          </form>
        </Modal>
      )}
      </AnimatePresence>
    </>
  );
}
