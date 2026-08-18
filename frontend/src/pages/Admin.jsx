import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { ArrowRight, Check, MoreVertical, Pencil, Plus, Power, RotateCcw, Send, Trash2 } from "lucide-react";
import { SiMinutemailer } from "react-icons/si";
import { api, localDate, timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, ConfirmDialog, ErrorBox, FolderMark, InlinePopup, Modal, PasswordInput, Spinner, useApi, useToast } from "../components";
import { Select } from "../components";

// Long enough for any real client name, short enough that the admin table and
// the workspace switcher stay readable — both truncate, and a name that is only
// ever seen truncated is not a name. Kept quiet until it bites: a field that
// opens by announcing its own limit is a field explaining our storage.
const NAME_MAX = 40;

function Field({ label, hint, children }) {
  return (
    <div className="field">
      <label>{label}{hint && <span className="fhint">{hint}</span>}</label>
      {children}
    </div>
  );
}

// What a workspace holds, in words — "12 companies · 340 contacts". Used
// wherever the operator is about to lose it, so the sentence that warns them
// says the actual size of the thing rather than "all its data".
function holds(w) {
  const c = w?.counts || {};
  const parts = [[c.companies, "companies", "company"], [c.contacts, "contacts", "contact"],
    [c.deals, "deals", "deal"]]
    .filter(([n]) => n > 0)
    .map(([n, many, one]) => `${n} ${n === 1 ? one : many}`);
  return parts.join(" · ");
}

// Creating a client workspace and handing it to a person are two decisions, and
// this modal only makes the first one. Creating is done the moment the workspace
// exists; the invite is sent later, deliberately, from the workspace row — where
// the screen names the workspace and the address, so nobody mails a login to the
// wrong client because two rows looked alike.
//
// Beside the create form sits a second screen that only appears when it has
// something to say: this client's workspace is already in the archive. Creating a
// second, empty one beside it is almost never what was meant, so the duplicate is
// checked BEFORE anything is written and the answer offered is their own
// history back.
function WorkspaceModal({ existing, onClose, onCreated, onDone, onRestored, askConfirm }) {
  const toast = useToast();
  const [name, setName] = useState(existing?.name || "");
  const [conflicts, setConflicts] = useState(null);   // archived workspaces holding this name/email
  const [email, setEmail] = useState("");             // checked for duplicates, then remembered
  const [emailTaken, setEmailTaken] = useState("");   // live workspace already using it
  const [busy, setBusy] = useState(false);

  // The write itself. `replaceIds` is non-empty only after the operator has
  // been shown exactly what it destroys and said yes — the server purges those
  // archived workspaces and creates this one in a single transaction.
  const build = async (replaceIds = []) => {
    setBusy(true);
    try {
      const made = await api("/api/admin/workspaces", {
        method: "POST",
        body: { name: name.trim(), client_email: email.trim(), replace_ids: replaceIds },
      });
      setConflicts(null);
      // The switcher at the top of every screen reads the session, not this
      // list — so the new workspace has to be published to BOTH before it can
      // be selected. onCreated does that, and selects it.
      onCreated(made);
      // Done. The invite is a separate decision made from the workspace row, so
      // nothing is pushed at whoever just wanted a workspace.
      onClose();
    } catch (x) {
      // The check above is a courtesy; this is the guard. Either way the answer
      // belongs next to the input that has to change.
      if (x.detail?.code === "email_in_use") setEmailTaken(x.detail.message);
      else toast(x.message, "bad");
    }
    finally { setBusy(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (existing) {
      setBusy(true);
      try {
        await api(`/api/admin/workspaces/${existing.id}`, { method: "PATCH", body: { name } });
        toast("Workspace renamed");
        onDone();
      } catch (x) { toast(x.message, "bad"); setBusy(false); }
      return;
    }
    setBusy(true);
    setEmailTaken("");
    let hits = [];
    try {
      const check = await api("/api/admin/workspaces/check-conflicts", {
        method: "POST", body: { name: name.trim(), email: email.trim() },
      });
      hits = check.conflicts || [];
      // A live workspace already using this address is a refusal, not a choice:
      // it belongs on the field the operator has to change, not behind a screen
      // whose only honest button would be "go back".
      if (check.email_in_use) { setEmailTaken("Email already in use"); setBusy(false); return; }
    } catch { /* An ENHANCEMENT, not a gate. If the check is unavailable the
                 create still happens, and the server still refuses both a
                 duplicate address and a name an archived workspace holds. */ }
    if (hits.length) { setConflicts(hits); setBusy(false); return; }
    await build();
  };

  const restore = async (w) => {
    setBusy(true);
    try {
      const back = await api(`/api/admin/workspaces/${w.id}/restore`, { method: "POST" });
      toast(`“${back.name}” restored`);
      onRestored(back);
    } catch (x) { toast(x.message, "bad"); setBusy(false); }
  };

  // "Create new" means the archived one is not coming back. That is the only
  // irreversible thing in this flow, so it is the only thing that asks twice.
  const createNew = () => {
    const many = conflicts.length > 1;
    const held = conflicts.map(holds).filter(Boolean).join(", ");
    askConfirm({
      title: many ? "Delete the archived workspaces?" : "Delete the archived workspace?",
      message: `${conflicts.map((c) => `“${c.name}”`).join(", ")} will be permanently deleted`
        + (held ? `, along with everything ${many ? "they hold" : "it holds"} — ${held}` : "")
        + ". This cannot be undone.",
      confirmLabel: many ? "Delete them and create new" : "Delete it and create new",
      danger: true,
      onConfirm: () => build(conflicts.map((c) => c.id)),
    });
  };

  if (conflicts) {
    const matched = new Set(conflicts.flatMap((c) => c.matched));
    const what = matched.has("name") && matched.has("email") ? "name and email address"
      : matched.has("name") ? "name" : "email address";
    return (
      <Modal title="Workspace already exists" onClose={onClose} closeButton>
        <p className="modal-lede">
          A workspace with this {what} already exists. You might want to restore it instead.
        </p>
        <div className="del-block">
          <div className="del-block-h">In the archive</div>
          {conflicts.map((c) => (
            <div key={c.id} className="del-user">
              <span className="du-main">
                <b>{c.name}</b>
                <em>
                  {c.client?.email ? `${c.client.email} · ` : ""}
                  {holds(c) || "empty"}
                  {c.archived_at ? ` · deleted ${localDate(c.archived_at)}` : ""}
                </em>
              </span>
              <Button size="sm" variant="secondary" icon={RotateCcw} disabled={busy}
                onClick={() => restore(c)}>Restore</Button>
            </div>
          ))}
        </div>
        <div className="actions">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <span style={{ flex: 1 }} />
          <Button variant="danger" icon={ArrowRight} loading={busy} onClick={createNew}>Create new</Button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={existing ? "Rename workspace" : "Create New Workspace"} onClose={onClose} closeButton>
      <form onSubmit={submit}>
        <Field label="Workspace name">
          <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus
            maxLength={NAME_MAX} placeholder="Client / workspace name" />
          {name.length >= NAME_MAX && (
            <p className="field-cap">That is as long as a workspace name can be.</p>
          )}
        </Field>
        {!existing && (
          <Field label="Client email (optional)">
            <input type="email" value={email} placeholder="ops@acme.com"
              aria-invalid={emailTaken ? "true" : undefined}
              onChange={(e) => { setEmail(e.target.value); setEmailTaken(""); }} />
            {emailTaken && (
              <p className="field-cap text-[color:var(--bad-text)]">{emailTaken}</p>
            )}
          </Field>
        )}
        <div className="actions">
          <Button type="submit" loading={busy} disabled={!!emailTaken}
            icon={existing ? Check : <FolderMark className="sm gold" />}>
            {existing ? "Save" : busy ? "Creating…" : "Create"}</Button>
        </div>
      </form>
    </Modal>
  );
}

// Invite (or re-invite) from a workspace row, for clients added after creation.
//
// The temporary password is NOT shown, mentioned, or returned here. It goes to
// the client's inbox and nowhere else; this screen's whole job is to say the
// message went.
//
// It has a second screen for one specific dead end. An address can be held by a
// client login belonging to a DELETED workspace — invisible in every list, so
// "that email already belongs to another account" points at nothing the operator
// can find. When the server says that is what happened it names the workspaces,
// and this shows them with the same two ways out the create screen offers: bring
// it back, or destroy it and free the address.
function InviteModal({ workspace, onClose, onInvited, onRestored, askConfirm }) {
  const toast = useToast();
  const isReinvite = Boolean(workspace.client);
  // The address is almost never new information by this point: either a client
  // account already holds it, or it was typed when the workspace was created.
  // Asking for it again is asking the operator to remember what we recorded.
  const [email, setEmail] = useState(
    workspace.client?.email || workspace.pending_client_email || "");
  const [contact, setContact] = useState(workspace.client?.name || "");
  const [conflicts, setConflicts] = useState(null);   // archived workspaces holding this address
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    try {
      onInvited(await api(`/api/admin/workspaces/${workspace.id}/invite-client`, {
        method: "POST", body: { email, name: contact },
      }));
    } catch (x) {
      setBusy(false);
      if (x.detail?.code === "address_in_archive") setConflicts(x.detail);
      else toast(x.message, "bad");
    }
  };
  const submit = (e) => { e.preventDefault(); send(); };

  const restore = async (w) => {
    setBusy(true);
    try {
      await api(`/api/admin/workspaces/${w.id}/restore`, { method: "POST" });
      toast(`“${w.name}” restored`);
      onRestored(w);
    } catch (x) { toast(x.message, "bad"); setBusy(false); }
  };

  // Destroying the archived workspace is what frees the address, so the invite
  // the operator already asked for is sent the moment it is gone — and if a
  // second archived workspace also holds the address the server says so again,
  // and this screen comes straight back with whatever is left.
  const purge = (w) => askConfirm({
    title: `Permanently delete ${w.name}?`,
    message: (holds(w) ? `Everything it holds — ${holds(w)} — is destroyed` : "It is destroyed for good")
      + `, and its client logins are erased — which is what frees ${email} for `
      + `“${workspace.name}”. This cannot be undone.`,
    confirmLabel: "Delete it and send the invite", danger: true,
    onConfirm: async () => {
      setBusy(true);
      try {
        await api(`/api/admin/workspaces/${w.id}/purge`, { method: "POST" });
        toast(`“${w.name}” deleted permanently`);
        setConflicts(null);
        await send();
      } catch (x) { toast(x.message, "bad"); setBusy(false); }
    },
  });

  if (conflicts) {
    return (
      <Modal title="That address is already in use" onClose={onClose} closeButton>
        <p className="modal-lede">
          {conflicts.message} Restore it to keep using <b>{email}</b> there, or delete it
          permanently to free the address for <b>{workspace.name}</b>.
        </p>
        <div className="del-block">
          <div className="del-block-h">In the archive</div>
          {conflicts.workspaces.map((c) => (
            <div key={c.id} className="del-user">
              <span className="du-main">
                <b>{c.name}</b>
                <em>
                  {(c.client_emails || []).join(", ") || "no client login"}
                  {` · ${holds(c) || "empty"}`}
                  {c.archived_at ? ` · deleted ${localDate(c.archived_at)}` : ""}
                </em>
              </span>
              <Button size="sm" variant="secondary" icon={RotateCcw} disabled={busy}
                onClick={() => restore(c)}>Restore</Button>
              <Button size="sm" variant="danger" icon={Trash2} disabled={busy}
                onClick={() => purge(c)}>Delete permanently</Button>
            </div>
          ))}
        </div>
        <div className="actions">
          <Button variant="ghost" onClick={() => setConflicts(null)}>Use another address</Button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={`${isReinvite ? "Resend invite to" : "Invite a client to"} ${workspace.name}`} onClose={onClose} closeButton>
      <form onSubmit={submit}>
        <Field label="Client Name"><input value={contact} placeholder="Dana Ruiz" autoFocus
          onChange={(e) => setContact(e.target.value)} /></Field>
        <Field label="Client email"><input type="email" value={email} placeholder="ops@acme.com"
          onChange={(e) => setEmail(e.target.value)} required
          onFocus={(e) => e.target.select()} /></Field>
        <div className="actions">
          <Button type="submit" loading={busy} disabled={!email.trim()} className="group"
            icon={<SiMinutemailer aria-hidden="true"
              className="size-4 shrink-0 transition-transform duration-200 ease-out group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:rotate-6 group-focus-visible:-translate-y-0.5 group-focus-visible:translate-x-0.5 group-focus-visible:rotate-6 motion-reduce:transform-none" />}>
            {busy ? (isReinvite ? "Resending…" : "Sending…") : (isReinvite ? "Resend invite" : "Send invite")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// Deleting asks for the workspace's name and the operator's password. Both are
// re-checked server-side — a UI-only check is a courtesy to the person
// clicking, not a control.
function DeleteWorkspaceModal({ workspace, onClose, onDeleted }) {
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState({ name: "", password: "", form: "" });

  const remove = async (e) => {
    e.preventDefault();
    if (typed.trim() !== workspace.name.trim()) {
      setErrors({ name: `Type “${workspace.name}” exactly to confirm deletion.`, password: "", form: "" });
      return;
    }
    if (!password) {
      setErrors({ name: "", password: "Enter your password to confirm deletion.", form: "" });
      return;
    }
    setErrors({ name: "", password: "", form: "" });
    setBusy(true);
    try {
      await api(`/api/admin/workspaces/${workspace.id}/archive`, {
        method: "POST", body: { confirm_name: typed.trim(), password },
      });
      setPassword("");
      toast(`“${workspace.name}” deleted`);
      onDeleted();
    } catch (x) {
      const message = x.message || "Unable to delete this workspace. Please try again.";
      setErrors(x.status === 422
        ? { name: message, password: "", form: "" }
        : x.status === 403
          ? { name: "", password: message, form: "" }
          : { name: "", password: "", form: message });
      setBusy(false);
      if (x.status === 403) setPassword("");
    }
  };

  return (
    <Modal title={`Delete ${workspace.name}`} onClose={onClose} closeButton>
      <form onSubmit={remove}>
        <Field label={<>Type <b>{workspace.name}</b> to confirm</>}>
          <input value={typed} autoFocus autoComplete="off" spellCheck={false}
            placeholder={workspace.name}
            onChange={(e) => { setTyped(e.target.value); setErrors((current) => ({ ...current, name: "", form: "" })); }} />
          {errors.name && <p role="alert" className="mt-1.5 text-xs font-medium text-[color:var(--bad-text)]">{errors.name}</p>}
        </Field>
        <Field label="Your password">
          <PasswordInput value={password} autoComplete="current-password"
            placeholder="••••••••"
            onChange={(e) => { setPassword(e.target.value); setErrors((current) => ({ ...current, password: "", form: "" })); }} />
          {errors.password && <p role="alert" className="mt-1.5 text-xs font-medium text-[color:var(--bad-text)]">{errors.password}</p>}
        </Field>
        {errors.form && <p role="alert" className="text-xs font-medium text-[color:var(--bad-text)]">{errors.form}</p>}
        <div className="actions">
          <Button type="submit" variant="danger" icon={Trash2} loading={busy}>
            Delete workspace
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function UserModal({ workspaces, onClose, onDone }) {
  const toast = useToast();
  const [f, setF] = useState({ email: "", name: "", password: "", role: "client",
    workspace_ids: [], must_change_password: true });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF({ ...f, [k]: v });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { await api("/api/admin/users", { method: "POST", body: f }); toast("User created"); onDone(); }
    catch (x) { toast(x.message, "bad"); setBusy(false); }
  };
  const needsWs = f.role === "client" || f.role === "member";
  return (
    <Modal title="New user" onClose={onClose} closeButton>
      <form onSubmit={submit}>
        <Field label="Email"><input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} required autoFocus /></Field>
        <Field label="Name"><input value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Password"><input type="text" value={f.password} onChange={(e) => set("password", e.target.value)} required minLength={8} /></Field>
        <label className="chk-row">
          <input type="checkbox" checked={f.must_change_password}
            onChange={(e) => set("must_change_password", e.target.checked)} />
          <span>Treat this as temporary — they must choose their own password on first sign-in</span>
        </label>
        <Field label="Role">
          <Select value={f.role} onChange={(e) => set("role", e.target.value)}>
            <option value="client">client — locked to ONE workspace (for your clients)</option>
            <option value="member">member — selected workspaces</option>
            <option value="admin">admin — all workspaces</option>
            <option value="owner">owner — all workspaces + billing</option>
          </Select>
        </Field>
        {needsWs && (
          <Field label={f.role === "client" ? "Workspace (exactly one)" : "Workspaces"}>
            <Select multiple={f.role === "member"} placeholder="choose…"
                    value={f.role === "member" ? f.workspace_ids.map(String) : String(f.workspace_ids[0] ?? "")}
                    onChange={(e) => set("workspace_ids",
                      f.role === "member"
                        ? Array.from(e.target.selectedOptions).map((o) => Number(o.value))
                        : [Number(e.target.value)])}>
              {f.role === "client" && <option value="" disabled>choose…</option>}
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
        )}
        <div className="actions"><Button type="submit" loading={busy}>Create user</Button></div>
      </form>
    </Modal>
  );
}

// In-page reset link: shown on screen in a selectable field with one-click copy.
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
    <Modal title="Password reset link" onClose={onClose} closeButton>
      <p style={{ fontSize: 13, color: "var(--muted)", margin: "0 0 12px" }}>
        One-time link for <b>{email}</b>, valid for 1 hour. Copy it and send it to them.
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <input ref={inputRef} readOnly value={link} onFocus={(e) => e.target.select()}
          onClick={(e) => e.target.select()} style={{ flex: 1, fontFamily: "monospace", fontSize: 12.5 }} />
        <Button onClick={copy}>Copy</Button>
      </div>
      <div className="actions" style={{ marginTop: 16 }}>
        <Button variant="ghost" onClick={onClose}>Done</Button>
      </div>
    </Modal>
  );
}

// The row's ⋮ menu. It owns its own anchor and open state so the table body
// stays a plain map, and every handler stops propagation — the row underneath is
// a link to the client profile, and picking "Delete" from a menu must not also
// navigate there.
function RowMenu({ workspace, onInvite, onRename, onToggleActive, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const pick = (fn) => (e) => { e.stopPropagation(); setOpen(false); fn(workspace); };
  return (
    <>
      <button ref={ref} className="iconbtn kebab" aria-label={`Actions for ${workspace.name}`}
        aria-haspopup="menu" aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}>
        <MoreVertical size={16} />
      </button>
      <InlinePopup open={open} onClose={() => setOpen(false)} anchorRef={ref} align="end"
        className="row-menu" role="menu">
        <button role="menuitem" onClick={pick(onInvite)}><Send size={14} /> {workspace.client ? "Resend invite" : "Invite client"}</button>
        <button role="menuitem" onClick={pick(onRename)}><Pencil size={14} /> Rename</button>
        <button role="menuitem" onClick={pick(onToggleActive)}>
          <Power size={14} /> {workspace.active ? "Deactivate" : "Activate"}
        </button>
        <div className="row-menu-sep" />
        <button role="menuitem" className="danger" onClick={pick(onDelete)}>
          <Trash2 size={14} /> Delete
        </button>
      </InlinePopup>
    </>
  );
}

export default function Admin() {
  const { me, reloadMe, setWorkspaceId } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const [modal, setModal] = useState(null);     // {type, data?}
  const [confirm, setConfirm] = useState(null);  // {title, message, danger, onConfirm}
  const [resetLink, setResetLink] = useState(null); // {email, link}
  const ws = useApi("/api/admin/workspaces");
  // The archive is its own call rather than a flag this screen filters on: it
  // is a different thing on the page — a bin you restore from, not a table you
  // work in — and keeping it separate means the main table can never
  // accidentally show a workspace that is supposed to be gone.
  const archive = useApi("/api/admin/workspaces", { archived: 1 });
  const users = useApi("/api/admin/users");
  if (!me.is_master) return <ErrorBox msg="Master access required." />;
  if (ws.loading || users.loading || archive.loading) return <Spinner />;
  const err = ws.error || users.error || archive.error;
  if (err) return <ErrorBox msg={err} retry={() => { ws.reload(); users.reload(); archive.reload(); }} />;
  const wsName = (id) => ws.data.find((w) => w.id === id)?.name || `#${id}`;

  // Quiet refreshes on purpose. reload() flips `loading`, which returns a
  // <Spinner/> from this component and rips any open modal out of the tree
  // mid-exit-animation. refresh() updates the data in place.
  const refreshAll = () => { ws.refresh(); users.refresh(); archive.refresh(); };

  // Every workspace action changes what the session may reach, so the switcher
  // at the top of the app is re-read alongside the tables.
  const afterWorkspaceChange = () => { refreshAll(); reloadMe(); };

  const doDeactivateUser = (u, after) => setConfirm({
    title: "Deactivate user",
    message: `${u.email} will no longer be able to sign in. You can re-issue access later with a reset link.`,
    confirmLabel: "Deactivate", danger: true,
    onConfirm: async () => {
      try {
        await api(`/api/admin/users/${u.id}/deactivate`, { method: "POST" });
        toast("User deactivated");
        refreshAll();
        after?.();
      } catch (e) { toast(e.message, "bad"); }
    },
  });

  const showResetLink = async (u) => {
    try {
      const r = await api(`/api/admin/users/${u.id}/reset-link`, { method: "POST" });
      setResetLink({ email: u.email, link: `${window.location.origin}/${r.reset_path}` });
    } catch (e) { toast(e.message, "bad"); }
  };

  const setWorkspaceActive = async (w, active) => {
    try {
      await api(`/api/admin/workspaces/${w.id}`, { method: "PATCH", body: { active } });
      toast(active ? "Workspace activated" : "Workspace deactivated");
      ws.refresh();
      reloadMe();
    } catch (e) { toast(e.message, "bad"); }
  };

  const toggleActive = (w) => {
    if (!w.active) return setWorkspaceActive(w, true);
    setConfirm({
      title: `Deactivate ${w.name}?`,
      message: `“${w.name}” will be unavailable to its users until you reactivate it. Its data will remain intact.`,
      confirmLabel: "Deactivate",
      danger: true,
      closeButton: true,
      onConfirm: () => setWorkspaceActive(w, false),
    });
  };

  const doRestore = async (w) => {
    try {
      await api(`/api/admin/workspaces/${w.id}/restore`, { method: "POST" });
      toast(`“${w.name}” restored`);
      afterWorkspaceChange();
    } catch (e) { toast(e.message, "bad"); }
  };

  const doPurge = (w) => setConfirm({
    title: `Permanently delete ${w.name}?`,
    message: (holds(w) ? `Everything it holds — ${holds(w)} — is destroyed` : "It is destroyed for good")
      + (w.client ? `, and ${w.client.email} loses their login` : "")
      + ". This cannot be undone.",
    confirmLabel: "Delete permanently", danger: true,
    onConfirm: async () => {
      try {
        await api(`/api/admin/workspaces/${w.id}/purge`, { method: "POST" });
        toast(`“${w.name}” deleted permanently`);
        afterWorkspaceChange();
      } catch (e) { toast(e.message, "bad"); }
    },
  });

  // A workspace row is a way into that client's configuration — the same screen
  // the Build nav calls "Client Profile". Opening it selects the workspace
  // first, because every screen behind that switcher is per-workspace.
  const openProfile = (w) => {
    setWorkspaceId(String(w.id));
    nav("/enrichment/profile");
  };

  const rowCounts = (w) => {
    const c = w.counts || {};
    return { text: `${c.companies ?? 0} · ${c.contacts ?? 0} · ${c.deals ?? 0}`,
      title: `${c.companies ?? 0} companies · ${c.contacts ?? 0} contacts · ${c.deals ?? 0} deals` };
  };

  return (
    <>
      <div className="section" style={{ marginTop: 0 }}>
        <div className="toolbar"><h2 style={{ margin: 0 }}>Workspaces ({ws.data.length})</h2><div className="spacer" />
          <Button size="sm" icon={Plus} onClick={() => setModal({ type: "ws" })}>Workspace</Button></div>
        <div className="tbl-scroll">
          <table className="tbl tbl-ws">
            <thead><tr>
              <th>Workspace</th>
              <th>Status</th>
              <th>Client</th>
              <th className="num col-md">Members</th>
              <th className="num" title="companies · contacts · deals">Records</th>
              <th className="col-lg">Created</th>
              <th className="col-md">Last activity</th>
              <th aria-label="Actions" />
            </tr></thead>
            <tbody>{ws.data.map((w) => {
              const counts = rowCounts(w);
              return (
                <tr key={w.id} className="click" tabIndex={0}
                  onClick={() => openProfile(w)}
                  onKeyDown={(e) => { if (e.key === "Enter") openProfile(w); }}>
                  <td>
                    <div className="trunc" title={w.name}><b>{w.name}</b></div>
                    <div className="trunc sub" title={w.slug}>{w.slug}</div>
                  </td>
                  <td>{w.active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}</td>
                  <td>
                    {w.client ? (
                      <>
                        <div className="trunc" title={w.client.name || w.client.email}>
                          {w.client.name || w.client.email}
                          {!w.client.active && <span className="sub"> · deactivated</span>}
                        </div>
                        {w.client.name && <div className="trunc sub" title={w.client.email}>{w.client.email}</div>}
                      </>
                    ) : <span className="sub">not invited</span>}
                  </td>
                  <td className="num col-md">{w.members ?? 0}</td>
                  <td className="num" title={counts.title}>{counts.text}</td>
                  <td className="col-lg sub" title={w.created_at ? localDate(w.created_at) : ""}>
                    {w.created_at ? localDate(w.created_at) : "—"}
                  </td>
                  <td className="col-md sub">{w.last_activity_at ? timeAgo(w.last_activity_at) : "—"}</td>
                  <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                    <RowMenu workspace={w}
                      onInvite={(x) => setModal({ type: "invite", data: x })}
                      onRename={(x) => setModal({ type: "ws", data: x })}
                      onToggleActive={toggleActive}
                      onDelete={(x) => setModal({ type: "delete", data: x })} />
                  </td>
                </tr>);
            })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section">
        <div className="toolbar"><h2 style={{ margin: 0 }}>Users ({users.data.length})</h2><div className="spacer" />
          <Button size="sm" icon={Plus} onClick={() => setModal({ type: "user" })}>User</Button></div>
        <div className="tbl-scroll">
          <table className="tbl">
            <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Workspaces</th><th /></tr></thead>
            <tbody>{users.data.map((u) => (
              <tr key={u.id}>
                <td><b>{u.email}</b></td><td>{u.name || "—"}</td>
                <td><Badge tone={["owner", "admin"].includes(u.role) ? "indigo" : u.role === "client" ? "amber" : ""}>{u.role}</Badge></td>
                <td style={{ fontSize: 12.5 }}>{["owner", "admin"].includes(u.role) ? "all" : (u.workspace_ids || []).map(wsName).join(", ") || "—"}</td>
                <td className="row-actions">
                  {u.active && <Button size="sm" variant="ghost" onClick={() => showResetLink(u)}>Reset link</Button>}
                  {u.active ? <Button size="sm" variant="danger" onClick={() => doDeactivateUser(u)}>Deactivate</Button> : <Badge>deactivated</Badge>}
                </td>
              </tr>))}
            </tbody>
          </table>
        </div>
      </div>

      {/* The archive only exists on the page when it has something in it. An
          empty bin is a row of chrome explaining a thing that has not
          happened. */}
      {archive.data.length > 0 && (
        <div className="section">
          <div className="toolbar">
            <h2 className="arch-h folder-host"><FolderMark /> Archive ({archive.data.length})</h2>
          </div>
          <div className="tbl-scroll">
            <table className="tbl">
              <thead><tr>
                <th>Workspace</th>
                <th>Client</th>
                <th className="num" title="companies · contacts · deals">Records</th>
                <th className="col-md">Deleted</th>
                <th aria-label="Actions" />
              </tr></thead>
              <tbody>{archive.data.map((w) => {
                const counts = rowCounts(w);
                return (
                  <tr key={w.id}>
                    <td>
                      <div className="trunc" title={w.name}><b>{w.name}</b></div>
                      <div className="trunc sub" title={w.slug}>{w.slug}</div>
                    </td>
                    <td>
                      {w.client ? (
                        <div className="trunc" title={w.client.email}>{w.client.email}</div>
                      ) : <span className="sub">not invited</span>}
                    </td>
                    <td className="num" title={counts.title}>{counts.text}</td>
                    <td className="col-md sub" title={w.archived_at ? localDate(w.archived_at) : ""}>
                      {w.archived_at ? timeAgo(w.archived_at) : "—"}
                    </td>
                    <td className="row-actions">
                      <Button size="sm" variant="secondary" icon={RotateCcw}
                        onClick={() => doRestore(w)}>Restore</Button>
                      <Button size="sm" variant="danger" icon={Trash2}
                        onClick={() => doPurge(w)}>Delete permanently</Button>
                    </td>
                  </tr>);
              })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* AnimatePresence stays mounted; the conditional lives INSIDE it, so a
          modal closed by Esc, the cross, or an outside click animates out
          instead of vanishing. */}
      <AnimatePresence>
        {modal?.type === "ws" && (
          <WorkspaceModal key="ws" existing={modal.data} onClose={() => setModal(null)}
            onCreated={(made) => {
              toast(`“${made.name}” created`);
              refreshAll();
              // The top switcher is fed by the session, so it has to be
              // re-read — without this the workspace only appears after a
              // reload. Selecting it makes the new workspace the active one.
              reloadMe();
              setWorkspaceId(String(made.id));
            }}
            onRestored={(back) => {
              setModal(null);
              afterWorkspaceChange();
              setWorkspaceId(String(back.id));
            }}
            askConfirm={setConfirm}
            onDone={() => { setModal(null); refreshAll(); }} />
        )}
        {modal?.type === "invite" && (
          <InviteModal key="invite" workspace={modal.data} onClose={() => setModal(null)}
            askConfirm={setConfirm}
            onRestored={(w) => {
              setModal(null);
              afterWorkspaceChange();
              setWorkspaceId(String(w.id));
            }}
            onInvited={(r) => {
              setModal(null); refreshAll();
              if (r.emailed) toast(`Invite sent to ${r.email}`);
              else toast(`Account ready, but the email didn’t send: ${r.delivery}`, "bad");
            }} />
        )}
        {modal?.type === "delete" && (
          <DeleteWorkspaceModal key="delete" workspace={modal.data}
            onClose={() => setModal(null)}
            onDeleted={() => { setModal(null); afterWorkspaceChange(); }} />
        )}
        {modal?.type === "user" && (
          <UserModal key="user" workspaces={ws.data} onClose={() => setModal(null)}
            onDone={() => { setModal(null); users.refresh(); }} />
        )}
        {resetLink && (
          <ResetLinkModal key="reset" email={resetLink.email} link={resetLink.link}
            onClose={() => setResetLink(null)} />
        )}
        {confirm && (
          <ConfirmDialog key="confirm" title={confirm.title} message={confirm.message}
            confirmLabel={confirm.confirmLabel} danger={confirm.danger} closeButton={confirm.closeButton}
            onConfirm={confirm.onConfirm} onClose={() => setConfirm(null)} />
        )}
      </AnimatePresence>
    </>
  );
}
