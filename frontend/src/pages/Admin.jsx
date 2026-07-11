import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Modal, Spinner, useApi } from "../components";

const SOURCES = ["reply_manager", "enrichment", "client_portals"];

function Field({ label, children }) { return <div className="field"><label>{label}</label>{children}</div>; }

function WorkspaceModal({ onClose, onDone }) {
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try { await api("/api/admin/workspaces", { method: "POST", body: { name } }); onDone(); }
    catch (x) { setErr(x.message); }
  };
  return (
    <Modal title="New workspace" onClose={onClose}>
      <form onSubmit={submit}>
        {err && <div className="error-box" style={{ marginBottom: 10 }}>{err}</div>}
        <Field label="Client / workspace name"><input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
        <div className="actions"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">Create</button></div>
      </form>
    </Modal>
  );
}

function UserModal({ workspaces, onClose, onDone }) {
  const [f, setF] = useState({ email: "", name: "", password: "", role: "client", workspace_ids: [] });
  const [err, setErr] = useState("");
  const set = (k, v) => setF({ ...f, [k]: v });
  const submit = async (e) => {
    e.preventDefault();
    try { await api("/api/admin/users", { method: "POST", body: f }); onDone(); }
    catch (x) { setErr(x.message); }
  };
  const needsWs = f.role === "client" || f.role === "member";
  return (
    <Modal title="New user" onClose={onClose}>
      <form onSubmit={submit}>
        {err && <div className="error-box" style={{ marginBottom: 10 }}>{err}</div>}
        <Field label="Email"><input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} required autoFocus /></Field>
        <Field label="Name"><input value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Password"><input type="text" value={f.password} onChange={(e) => set("password", e.target.value)} required minLength={8} /></Field>
        <Field label="Role">
          <select value={f.role} onChange={(e) => set("role", e.target.value)}>
            <option value="client">client — locked to ONE workspace (for your clients)</option>
            <option value="member">member — selected workspaces</option>
            <option value="admin">admin — all workspaces</option>
            <option value="owner">owner — all workspaces + billing</option>
          </select>
        </Field>
        {needsWs && (
          <Field label={f.role === "client" ? "Workspace (exactly one)" : "Workspaces"}>
            <select multiple={f.role === "member"} size={Math.min(5, workspaces.length)}
                    value={f.role === "member" ? f.workspace_ids.map(String) : String(f.workspace_ids[0] ?? "")}
                    onChange={(e) => set("workspace_ids",
                      f.role === "member"
                        ? Array.from(e.target.selectedOptions).map((o) => Number(o.value))
                        : [Number(e.target.value)])}>
              {f.role === "client" && <option value="" disabled>choose…</option>}
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </Field>
        )}
        <div className="actions"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">Create user</button></div>
      </form>
    </Modal>
  );
}

function AliasModal({ workspaces, existing, onClose, onDone }) {
  const [f, setF] = useState(existing || { workspace_id: workspaces[0]?.id, source_system: "reply_manager", external_name: "" });
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (existing) await api(`/api/admin/aliases/${existing.id}`, { method: "PATCH",
        body: { workspace_id: Number(f.workspace_id), external_name: f.external_name } });
      else await api("/api/admin/aliases", { method: "POST",
        body: { ...f, workspace_id: Number(f.workspace_id) } });
      onDone();
    } catch (x) { setErr(x.message); }
  };
  return (
    <Modal title={existing ? "Edit alias" : "New alias"} onClose={onClose}>
      <form onSubmit={submit}>
        {err && <div className="error-box" style={{ marginBottom: 10 }}>{err}</div>}
        <Field label="Canonical workspace">
          <select value={f.workspace_id} onChange={(e) => setF({ ...f, workspace_id: e.target.value })}>
            {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </Field>
        <Field label="Source system">
          <select value={f.source_system} disabled={!!existing} onChange={(e) => setF({ ...f, source_system: e.target.value })}>
            {SOURCES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Exact legacy name"><input value={f.external_name} onChange={(e) => setF({ ...f, external_name: e.target.value })} required /></Field>
        <div className="actions"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">{existing ? "Save" : "Create"}</button></div>
      </form>
    </Modal>
  );
}

export default function Admin() {
  const { me } = useAuth();
  const [modal, setModal] = useState(null); // {type, data?}
  const ws = useApi("/api/admin/workspaces");
  const users = useApi("/api/admin/users");
  const aliases = useApi("/api/admin/aliases");
  if (!me.is_master) return <ErrorBox msg="Master access required." />;
  if (ws.loading || users.loading || aliases.loading) return <Spinner />;
  const err = ws.error || users.error || aliases.error;
  if (err) return <ErrorBox msg={err} retry={() => { ws.reload(); users.reload(); aliases.reload(); }} />;
  const wsName = (id) => ws.data.find((w) => w.id === id)?.name || `#${id}`;

  const deactivate = async (id) => {
    if (!confirm("Deactivate this user? They will no longer be able to sign in.")) return;
    try { await api(`/api/admin/users/${id}/deactivate`, { method: "POST" }); users.reload(); }
    catch (e) { alert(e.message); }
  };
  const deleteAlias = async (id) => {
    if (!confirm("Delete this alias?")) return;
    try { await api(`/api/admin/aliases/${id}`, { method: "DELETE" }); aliases.reload(); }
    catch (e) { alert(e.message); }
  };

  return (
    <>
      <div className="section" style={{ marginTop: 0 }}>
        <div className="toolbar"><h2 style={{ margin: 0 }}>Workspaces ({ws.data.length})</h2><div className="spacer" />
          <button className="btn sm" onClick={() => setModal({ type: "ws" })}>+ Workspace</button></div>
        <table className="tbl">
          <thead><tr><th>Name</th><th>Slug</th><th>Active</th></tr></thead>
          <tbody>{ws.data.map((w) => (
            <tr key={w.id}><td><b>{w.name}</b></td><td style={{ color: "var(--muted)" }}>{w.slug}</td>
              <td>{w.active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}</td></tr>))}
          </tbody>
        </table>
      </div>

      <div className="section">
        <div className="toolbar"><h2 style={{ margin: 0 }}>Users ({users.data.length})</h2><div className="spacer" />
          <button className="btn sm" onClick={() => setModal({ type: "user" })}>+ User</button></div>
        <table className="tbl">
          <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Workspaces</th><th></th></tr></thead>
          <tbody>{users.data.map((u) => (
            <tr key={u.id}>
              <td><b>{u.email}</b></td><td>{u.name || "—"}</td>
              <td><Badge tone={["owner", "admin"].includes(u.role) ? "indigo" : u.role === "client" ? "amber" : ""}>{u.role}</Badge></td>
              <td style={{ fontSize: 12.5 }}>{["owner", "admin"].includes(u.role) ? "all" : (u.workspace_ids || []).map(wsName).join(", ") || "—"}</td>
              <td style={{ textAlign: "right" }}>
                {u.active ? <button className="btn danger sm" onClick={() => deactivate(u.id)}>Deactivate</button> : <Badge>deactivated</Badge>}
              </td>
            </tr>))}
          </tbody>
        </table>
      </div>

      <div className="section">
        <div className="toolbar"><h2 style={{ margin: 0 }}>Workspace aliases ({aliases.data.length})</h2><div className="spacer" />
          <button className="btn sm" onClick={() => setModal({ type: "alias" })}>+ Alias</button></div>
        <table className="tbl">
          <thead><tr><th>Legacy name</th><th>Source</th><th>→ Workspace</th><th></th></tr></thead>
          <tbody>
            {aliases.data.length === 0 && <tr><td colSpan={4} className="empty">No aliases — used to map legacy system names during imports.</td></tr>}
            {aliases.data.map((a) => (
              <tr key={a.id}>
                <td style={{ fontFamily: "monospace", fontSize: 12.5 }}>{a.external_name}</td>
                <td><Badge>{a.source_system}</Badge></td>
                <td>{wsName(a.workspace_id)}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn ghost sm" onClick={() => setModal({ type: "alias", data: a })}>Edit</button>{" "}
                  <button className="btn danger sm" onClick={() => deleteAlias(a.id)}>Delete</button>
                </td>
              </tr>))}
          </tbody>
        </table>
      </div>

      {modal?.type === "ws" && <WorkspaceModal onClose={() => setModal(null)} onDone={() => { setModal(null); ws.reload(); }} />}
      {modal?.type === "user" && <UserModal workspaces={ws.data} onClose={() => setModal(null)} onDone={() => { setModal(null); users.reload(); }} />}
      {modal?.type === "alias" && <AliasModal workspaces={ws.data} existing={modal.data} onClose={() => setModal(null)} onDone={() => { setModal(null); aliases.reload(); }} />}
    </>
  );
}
