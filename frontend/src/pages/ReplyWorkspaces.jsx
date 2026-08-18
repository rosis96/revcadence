// Reply Management → Extra Channels: the full per-client config editor (platform,
// keys [write-only], Calendly, AI provider, client profile, reply format, rules).
//
// Mounted at two bases. The main reply space is edited under Setup; this screen
// exists for the second one — a client running Bison for cold and Instantly for
// follow-up. That is a statement about their own sending setup, so it is theirs
// to make, and the list is workspace-scoped on the server.
//
// The "Client workspace" picker is the one operator-only control: choosing which
// client a channel belongs to is a question that only exists when you have more
// than one, and answering it wrongly would put a channel in the wrong client.
import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { api } from "../api";
import { useAuth } from "../auth";
import { Area, Badge, Empty, ErrorBox, Modal, Spinner, useApi } from "../components";
import { alertDialog } from "../components";
import { Select } from "../components";

function Field({ label, children, half }) {
  return <div className="field" style={half ? { flex: 1 } : {}}><label>{label}</label>{children}</div>;
}

function WorkspaceModal({ existing, workspaces, defaultWorkspaceId, onClose, onDone }) {
  // The workspace on screen, not the org's first one: with a workspace selected
  // the picker used to open on somebody else, so a distracted Create filed the
  // channel under the wrong client.
  const blank = {
    workspace_id: Number(defaultWorkspaceId) || workspaces[0]?.id,
    name: "", platform: "bison", mode: "reply", active: true,
    base_url: "", reply_followup_campaign_id: "", website: "", sender_name: "",
    default_sender_email: "", calendly_scheduling_url: "", ai_provider: "openai", ai_fallback: true,
    reply_delay_seconds: 420, client_profile: {}, reply_format: {}, ai_rules: "",
  };
  const [f, setF] = useState(existing ? { ...existing } : blank);
  const [secrets, setSecrets] = useState({});   // only sent if typed
  const [profileStr, setProfileStr] = useState(JSON.stringify(existing?.client_profile || {}, null, 2));
  const [formatStr, setFormatStr] = useState(JSON.stringify(existing?.reply_format || {}, null, 2));
  const [err, setErr] = useState("");
  const set = (k, v) => setF({ ...f, [k]: v });

  const submit = async (e) => {
    e.preventDefault(); setErr("");
    let client_profile, reply_format;
    try { client_profile = JSON.parse(profileStr || "{}"); } catch { setErr("Client Profile JSON invalid"); return; }
    try { reply_format = JSON.parse(formatStr || "{}"); } catch { setErr("Reply Format JSON invalid"); return; }
    const body = { ...f, client_profile, reply_format, ...secrets };
    try {
      if (existing) await api(`/api/reply/workspaces/${existing.id}`, { method: "PUT", body });
      else await api("/api/reply/workspaces", { method: "POST", body });
      onDone();
    } catch (x) { setErr(x.message); }
  };
  const secretField = (key, label, isSet) => (
    <Field label={`${label}${isSet ? " (set — leave blank to keep)" : ""}`} half>
      <input type="password" placeholder={isSet ? "••••••••" : ""} onChange={(e) => setSecrets({ ...secrets, [key]: e.target.value })} />
    </Field>
  );
  return (
    <Modal title={existing ? `Edit ${existing.name}` : "New reply workspace"} onClose={onClose}>
      <form onSubmit={submit}>
        {err && <div className="error-box" style={{ marginBottom: 10 }}>{err}</div>}
        {!existing && workspaces.length > 1 && (
          <Field label="Client workspace">
            <Select value={f.workspace_id} onChange={(e) => set("workspace_id", Number(e.target.value))}>
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </Field>
        )}
        <Field label="Reply-workspace name (must match webhook ?workspace_name=)">
          <input value={f.name} onChange={(e) => set("name", e.target.value)} required /></Field>
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Platform" half>
            <Select value={f.platform} onChange={(e) => set("platform", e.target.value)}>
              <option value="bison">Bison</option><option value="instantly">Instantly</option>
            </Select></Field>
          <Field label="Mode" half>
            <Select value={f.mode} onChange={(e) => set("mode", e.target.value)}>
              <option value="reply">reply</option><option value="followup">followup</option>
            </Select></Field>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {secretField("api_key", "API key", existing?.api_key_set)}
          <Field label="Follow-up campaign ID" half>
            <input value={f.reply_followup_campaign_id} onChange={(e) => set("reply_followup_campaign_id", e.target.value)} /></Field>
        </div>
        {f.platform === "bison" && (
          <Field label="Base URL (Bison)"><input value={f.base_url} onChange={(e) => set("base_url", e.target.value)} placeholder="https://send.ascendly.one" /></Field>
        )}
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="Sender name" half><input value={f.sender_name} onChange={(e) => set("sender_name", e.target.value)} /></Field>
          <Field label="Website (signature)" half><input value={f.website} onChange={(e) => set("website", e.target.value)} /></Field>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          {secretField("calendly_token", "Calendly token", existing?.calendly_token_set)}
          <Field label="Calendly scheduling link" half><input value={f.calendly_scheduling_url} onChange={(e) => set("calendly_scheduling_url", e.target.value)} /></Field>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Field label="AI provider" half>
            <Select value={f.ai_provider} onChange={(e) => set("ai_provider", e.target.value)}>
              <option value="openai">OpenAI</option><option value="gemini">Gemini</option>
            </Select></Field>
          <Field label="Reply delay (seconds)" half>
            <input type="number" value={f.reply_delay_seconds} onChange={(e) => set("reply_delay_seconds", Number(e.target.value))} /></Field>
        </div>
        <label style={{ display: "flex", gap: 8, fontSize: 13, margin: "4px 0 10px" }}>
          <input type="checkbox" checked={f.ai_fallback} onChange={(e) => set("ai_fallback", e.target.checked)} />
          Auto-fallback to the other provider on failure</label>
        <Field label="Client Profile (JSON)"><Area size="md" style={{ fontFamily: "monospace", fontSize: 12 }} value={profileStr} onChange={(e) => setProfileStr(e.target.value)} /></Field>
        <Field label="Reply Format (JSON — response_types[] + followups)"><Area size="lg" style={{ fontFamily: "monospace", fontSize: 12 }} value={formatStr} onChange={(e) => setFormatStr(e.target.value)} /></Field>
        <Field label="AI Rules (one per line — injected into every prompt)"><Area size="md" value={f.ai_rules} onChange={(e) => set("ai_rules", e.target.value)} /></Field>
        <label style={{ display: "flex", gap: 8, fontSize: 13 }}>
          <input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> Active</label>
        <div className="actions"><button type="button" className="btn ghost" onClick={onClose}>Cancel</button><button className="btn">{existing ? "Save" : "Create"}</button></div>
      </form>
    </Modal>
  );
}

export default function ReplyWorkspaces() {
  const { me, wsParam } = useAuth();
  const { data, error, loading, reload } = useApi("/api/reply/workspaces", { workspace_id: wsParam });
  const [modal, setModal] = useState(null);
  const dup = async (id) => { try { await api(`/api/reply/workspaces/${id}/duplicate`, { method: "POST" }); reload(); } catch (e) { alertDialog(e.message); } };
  return (
    <>
      <div className="card" style={{ padding: 12, marginBottom: 14, fontSize: 12.5, color: "var(--muted)" }}>
        Every client workspace already has its main reply space (edit it under <b>Setup</b>).
        Add an <b>extra channel</b> here only when a client needs a second platform or a separate
        follow-up space (e.g. a Bison main + an Instantly channel).
      </div>
      <div className="toolbar"><div className="spacer" /><button className="btn" onClick={() => setModal({})}>+ Add extra channel</button></div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="⚑" title="No reply spaces here" hint="Pick a workspace top-left; its main reply space is under Setup." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Platform</th><th>Mode</th><th>Keys</th><th>Active</th><th></th></tr></thead>
          <tbody>
            {data.map((w) => (
              <tr key={w.id}>
                <td><b>{w.name}</b></td>
                <td><Badge>{w.platform}</Badge></td>
                <td>{w.mode}</td>
                <td style={{ fontSize: 12 }}>{w.api_key_set ? <Badge tone="green">api</Badge> : <Badge tone="red">no api</Badge>} {w.calendly_token_set && <Badge tone="green">calendly</Badge>}</td>
                <td>{w.active ? <Badge tone="green">active</Badge> : <Badge>off</Badge>}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn ghost sm" onClick={() => setModal(w)}>Edit</button>{" "}
                  <button className="btn ghost sm" onClick={() => dup(w.id)}>Duplicate</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <AnimatePresence>
      {modal && <WorkspaceModal key="ws" existing={modal.id ? modal : null} workspaces={me.workspaces}
        defaultWorkspaceId={wsParam} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
      </AnimatePresence>
    </>
  );
}
