import { useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, ConfirmDialog, ErrorBox, Modal, Spinner, useApi, useToast } from "../components";

function Field({ label, children }) { return <div className="field"><label>{label}</label>{children}</div>; }

function WorkspaceModal({ existing, onClose, onDone }) {
  const [name, setName] = useState(existing?.name || "");
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (existing) await api(`/api/admin/workspaces/${existing.id}`, { method: "PATCH", body: { name } });
      else await api("/api/admin/workspaces", { method: "POST", body: { name } });
      onDone();
    } catch (x) { setErr(x.message); }
  };
  return (
    <Modal title={existing ? "Rename workspace" : "New workspace"} onClose={onClose}>
      <form onSubmit={submit}>
        {err && <div className="error-box" style={{ marginBottom: 10 }}>{err}</div>}
        <Field label="Client / workspace name"><input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
        <div className="actions"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">{existing ? "Save" : "Create"}</button></div>
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

// In-page reset link: shown on screen in a selectable field with one-click copy.
// (Replaces the old blocking alert() that froze the page.)
function ResetLinkModal({ email, link, onClose }) {
  const toast = useToast();
  const inputRef = useRef(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      toast("Reset link copied");
    } catch {
      // Fallback for browsers that block the clipboard API.
      inputRef.current?.select();
      document.execCommand?.("copy");
      toast("Reset link selected — press ⌘/Ctrl+C");
    }
  };
  return (
    <Modal title="Password reset link" onClose={onClose}>
      <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 12px" }}>
        One-time link for <b>{email}</b>, valid for 1 hour. Copy it and send it to them.
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <input ref={inputRef} readOnly value={link} onFocus={(e) => e.target.select()}
          onClick={(e) => e.target.select()} style={{ flex: 1, fontFamily: "monospace", fontSize: 12.5 }} />
        <Button onClick={copy}>Copy</Button>
      </div>
      <div className="actions" style={{ marginTop: 16 }}>
        <button type="button" className="btn ghost" onClick={onClose}>Done</button>
      </div>
    </Modal>
  );
}

export default function Admin() {
  const { me } = useAuth();
  const toast = useToast();
  const [modal, setModal] = useState(null);     // {type, data?}
  const [confirm, setConfirm] = useState(null);  // {title, message, danger, onConfirm}
  const [resetLink, setResetLink] = useState(null); // {email, link}
  const ws = useApi("/api/admin/workspaces");
  const users = useApi("/api/admin/users");
  if (!me.is_master) return <ErrorBox msg="Master access required." />;
  if (ws.loading || users.loading) return <Spinner />;
  const err = ws.error || users.error;
  if (err) return <ErrorBox msg={err} retry={() => { ws.reload(); users.reload(); }} />;
  const wsName = (id) => ws.data.find((w) => w.id === id)?.name || `#${id}`;

  const doDeactivateUser = (u) => setConfirm({
    title: "Deactivate user",
    message: `${u.email} will no longer be able to sign in. You can re-issue access later with a reset link.`,
    confirmLabel: "Deactivate", danger: true,
    onConfirm: async () => {
      try { await api(`/api/admin/users/${u.id}/deactivate`, { method: "POST" }); toast("User deactivated"); users.reload(); }
      catch (e) { toast(e.message, "bad"); }
    },
  });

  const showResetLink = async (u) => {
    try {
      const r = await api(`/api/admin/users/${u.id}/reset-link`, { method: "POST" });
      setResetLink({ email: u.email, link: `${window.location.origin}/${r.reset_path}` });
    } catch (e) { toast(e.message, "bad"); }
  };

  const toggleActive = async (w) => {
    try { await api(`/api/admin/workspaces/${w.id}`, { method: "PATCH", body: { active: !w.active } });
      toast(w.active ? "Workspace deactivated" : "Workspace reactivated"); ws.reload(); }
    catch (e) { toast(e.message, "bad"); }
  };

  const doDeleteWorkspace = (w) => setConfirm({
    title: "Delete workspace",
    message: `Permanently delete “${w.name}”? This only works if the workspace has no contacts, deals, or leads. Populated workspaces should be deactivated instead.`,
    confirmLabel: "Delete", danger: true,
    onConfirm: async () => {
      try { await api(`/api/admin/workspaces/${w.id}`, { method: "DELETE" }); toast("Workspace deleted"); ws.reload(); users.reload(); }
      catch (e) { toast(e.message, "bad"); }
    },
  });

  return (
    <>
      <div className="section" style={{ marginTop: 0 }}>
        <div className="toolbar"><h2 style={{ margin: 0 }}>Workspaces ({ws.data.length})</h2><div className="spacer" />
          <button className="btn sm" onClick={() => setModal({ type: "ws" })}>+ Workspace</button></div>
        <table className="tbl">
          <thead><tr><th>Name</th><th>Slug</th><th>Active</th><th></th></tr></thead>
          <tbody>{ws.data.map((w) => (
            <tr key={w.id}>
              <td><b>{w.name}</b></td>
              <td style={{ color: "var(--muted)" }}>{w.slug}</td>
              <td>{w.active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}</td>
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                <button className="btn ghost sm" onClick={() => setModal({ type: "ws", data: w })} style={{ marginRight: 6 }}>Rename</button>
                <button className="btn ghost sm" onClick={() => toggleActive(w)} style={{ marginRight: 6 }}>{w.active ? "Deactivate" : "Reactivate"}</button>
                <button className="btn danger sm" onClick={() => doDeleteWorkspace(w)}>Delete</button>
              </td>
            </tr>))}
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
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                {u.active && <button className="btn ghost sm" onClick={() => showResetLink(u)} style={{ marginRight: 6 }}>Reset link</button>}
                {u.active ? <button className="btn danger sm" onClick={() => doDeactivateUser(u)}>Deactivate</button> : <Badge>deactivated</Badge>}
              </td>
            </tr>))}
          </tbody>
        </table>
      </div>

      {modal?.type === "ws" && <WorkspaceModal existing={modal.data} onClose={() => setModal(null)} onDone={() => { setModal(null); ws.reload(); }} />}
      {modal?.type === "user" && <UserModal workspaces={ws.data} onClose={() => setModal(null)} onDone={() => { setModal(null); users.reload(); }} />}
      {resetLink && <ResetLinkModal email={resetLink.email} link={resetLink.link} onClose={() => setResetLink(null)} />}
      {confirm && <ConfirmDialog title={confirm.title} message={confirm.message} confirmLabel={confirm.confirmLabel}
        danger={confirm.danger} onConfirm={confirm.onConfirm} onClose={() => setConfirm(null)} />}
    </>
  );
}
