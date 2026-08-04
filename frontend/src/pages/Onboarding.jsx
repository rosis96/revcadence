import { alertDialog } from "../components";
// CRM → Onboarding: create a client's onboarding link, track status/progress,
// review what they submitted + the auto-generated checklist.
import { useState } from "react";
import { Copy, Link2, Plus } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Modal, PageHeader, Spinner, StatusBadge, useApi } from "../components";

function DetailModal({ id, onClose }) {
  const { data: o, loading, error } = useApi(`/api/onboarding/${id}`);
  if (loading) return <Modal title="Loading…" onClose={onClose}><Spinner /></Modal>;
  if (error) return <Modal title="Error" onClose={onClose}><ErrorBox msg={error} /></Modal>;
  return (
    <Modal title={`Onboarding ${o.status === "submitted" ? "· submitted" : "· draft"}`} onClose={onClose}>
      <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Checklist</h3>
      {o.checklist.map((c) => (
        <div key={c.key} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5, padding: "4px 0" }}>
          <span style={{ color: c.done ? "var(--ok)" : "var(--muted2)" }}>{c.done ? "●" : "○"}</span>{c.label}
        </div>
      ))}
      <h3 style={{ fontSize: 13, margin: "14px 0 6px" }}>Submitted details</h3>
      {Object.keys(o.data || {}).filter((k) => !k.startsWith("_")).length === 0
        ? <div className="empty" style={{ padding: 12 }}>Nothing submitted yet</div>
        : <div className="kv" style={{ margin: 0 }}>
            {Object.entries(o.data).filter(([k]) => !k.startsWith("_")).map(([k, v]) => (
              <><div className="k" key={k + "k"}>{k}</div><div key={k + "v"}>{String(v)}</div></>
            ))}
          </div>}
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 10 }}>
        Secret fields (mailbox app password, Calendly token) are stored encrypted and not shown.
      </div>
    </Modal>
  );
}

export default function Onboarding() {
  const { wsParam, me } = useAuth();
  const { data, error, loading, reload } = useApi("/api/onboarding", { workspace_id: wsParam });
  const [creating, setCreating] = useState(false);
  const [ws, setWs] = useState(wsParam || me.workspaces[0]?.id || "");
  const [newLink, setNewLink] = useState("");
  const [open, setOpen] = useState(null);
  const [copied, setCopied] = useState("");

  if (!me.is_master) return <ErrorBox msg="Master access required." />;

  const create = async () => {
    try {
      const r = await api("/api/onboarding", { method: "POST", body: { workspace_id: Number(ws) } });
      setNewLink(r.link); reload();
    } catch (e) { alertDialog(e.message); }
  };
  const copy = (link, id) => { navigator.clipboard.writeText(link); setCopied(id); setTimeout(() => setCopied(""), 1500); };
  const linkFor = (t) => `${window.location.origin}/#/onboard/${t}`;

  return (
    <>
      <PageHeader title="Client Onboarding"
        desc="Send a client one link. They fill it once; the system wires up their profile, mailbox, and preferences automatically."
        actions={<button className="hbtn primary" onClick={() => { setCreating(true); setNewLink(""); }}><Plus size={16} /> New onboarding link</button>} />

      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="◎" title="No onboardings yet" hint="Create a link and send it to a new client." />}
      {data && data.length > 0 && (
        <div className="surface">
          <table className="dt">
            <thead><tr><th>Client</th><th>Status</th><th>Progress</th><th>Link</th><th /></tr></thead>
            <tbody>
              {data.map((o) => (
                <tr key={o.id} className="click" onClick={() => setOpen(o.id)} style={{ cursor: "pointer" }}>
                  <td><b>{o.workspace_name}</b></td>
                  <td>{o.status === "submitted" ? <StatusBadge tone="green">submitted</StatusBadge> : <StatusBadge tone="amber">draft</StatusBadge>}</td>
                  <td>{o.progress}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button className="dt-tool" onClick={() => copy(linkFor(o.token), o.id)}>
                      <Copy size={14} /> {copied === o.id ? "Copied!" : "Copy link"}
                    </button>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <a href={linkFor(o.token)} target="_blank" rel="noreferrer" className="rowact" title="Open form"><Link2 size={16} /></a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && (
        <Modal title="New onboarding link" onClose={() => setCreating(false)}>
          {!newLink ? (
            <>
              <div className="field"><label>Client workspace</label>
                <select value={ws} onChange={(e) => setWs(e.target.value)}>
                  {me.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select></div>
              <div className="actions">
                <button className="btn ghost" onClick={() => setCreating(false)}>Cancel</button>
                <button className="btn" onClick={create}>Create link</button>
              </div>
            </>
          ) : (
            <>
              <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 8 }}>Send this link to your client:</p>
              <div style={{ display: "flex", gap: 8 }}>
                <input readOnly value={newLink} style={{ flex: 1 }} />
                <button className="btn" onClick={() => copy(newLink, "new")}>{copied === "new" ? "Copied!" : "Copy"}</button>
              </div>
              <div className="actions"><button className="btn" onClick={() => setCreating(false)}>Done</button></div>
            </>
          )}
        </Modal>
      )}
      {open && <DetailModal id={open} onClose={() => setOpen(null)} />}
    </>
  );
}
