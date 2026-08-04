import { confirmDialog } from "../components";
// Settings → Integrations → CRM: connect an external CRM, configure sync
// direction / entities / mappings / conflict policy, test, run, and monitor.
// The Generic webhook/API provider is production-ready; native adapters are
// listed but clearly marked until their real integrations ship.
import { useState } from "react";
import { Cable, Play, Plug, RefreshCw, Trash2 } from "lucide-react";
import { api, timeAgo } from "../api";
import { useAuth } from "../auth";
import {
  Badge, Button, ErrorBox, Modal, PageHeader, RowCard, StatusPill, useApi, useToast,
} from "../components";

const PROVIDER_LABEL = {
  generic: "Generic webhook / API", hubspot: "HubSpot", salesforce: "Salesforce",
  gohighlevel: "GoHighLevel", pipedrive: "Pipedrive", zoho: "Zoho",
};
const POLICY_LABEL = {
  revcadence_wins: "RevCadence wins", external_wins: "External CRM wins",
  newest_wins: "Newest update wins", flag_review: "Flag for review",
};
const ENTITIES = ["companies", "contacts", "deals"];

function ConnForm({ meta, initial, onSaved, onClose }) {
  const { wsParam } = useAuth();
  const toast = useToast();
  const [f, setF] = useState(initial || {
    provider: "generic", name: "", direction: "outbound", conflict_policy: "newest_wins",
    entities: [...ENTITIES], config: { url: "", secret: "" },
    field_mappings: {}, stage_mappings: {},
  });
  const [maps, setMaps] = useState(JSON.stringify(initial?.field_mappings || {}, null, 2));
  const [stages, setStages] = useState(JSON.stringify(initial?.stage_mappings || {}, null, 2));
  const nativeReady = (meta?.native_ready || []).includes(f.provider);

  const save = async () => {
    let field_mappings, stage_mappings;
    try { field_mappings = JSON.parse(maps || "{}"); stage_mappings = JSON.parse(stages || "{}"); }
    catch { toast("Mappings must be valid JSON", "bad"); return; }
    try {
      const body = { ...f, field_mappings, stage_mappings,
        workspace_id: wsParam ? Number(wsParam) : undefined };
      const r = initial?.id
        ? await api(`/api/devapi/sync/connections/${initial.id}`, { method: "PUT", body })
        : await api("/api/devapi/sync/connections", { method: "POST", body });
      onSaved(r);
    } catch (e) { toast(e.message, "bad"); }
  };

  return (
    <Modal title={initial ? "Edit connection" : "Connect a CRM"} onClose={onClose}>
      <div className="field"><label>Provider</label>
        <select value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })}>
          {(meta?.providers || []).map((p) => (
            <option key={p} value={p}>{PROVIDER_LABEL[p] || p}{(meta?.native_ready || []).includes(p) ? "" : " (coming soon)"}</option>
          ))}
        </select>
        {!nativeReady && (
          <div style={{ fontSize: 12, color: "#B54708", marginTop: 4 }}>
            The native {PROVIDER_LABEL[f.provider]} adapter isn't live yet. Use the Generic
            webhook/API provider today — it works with Zapier, Make, n8n, or any middleware.
          </div>
        )}
      </div>
      <div className="field"><label>Name</label>
        <input value={f.name} placeholder="e.g. HubSpot via Make.com"
          onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
      {f.provider === "generic" && (
        <>
          <div className="field"><label>Endpoint URL (receives signed upserts)</label>
            <input value={f.config.url} placeholder="https://hook.make.com/…"
              onChange={(e) => setF({ ...f, config: { ...f.config, url: e.target.value } })} /></div>
          <div className="field"><label>Shared secret (signs every request)</label>
            <input value={f.config.secret} placeholder="any long random string"
              onChange={(e) => setF({ ...f, config: { ...f.config, secret: e.target.value } })} /></div>
        </>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <div className="field"><label>Sync direction</label>
          <select value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}>
            <option value="outbound">RevCadence → CRM</option>
            <option value="inbound">CRM → RevCadence (native adapters only)</option>
            <option value="two_way">Two-way (native adapters only)</option>
          </select></div>
        <div className="field"><label>Conflict policy</label>
          <select value={f.conflict_policy} onChange={(e) => setF({ ...f, conflict_policy: e.target.value })}>
            {(meta?.conflict_policies || []).map((p) => <option key={p} value={p}>{POLICY_LABEL[p] || p}</option>)}
          </select></div>
      </div>
      <div className="field"><label>Entities to sync</label>
        <div style={{ display: "flex", gap: 14, fontSize: 13 }}>
          {ENTITIES.map((e) => (
            <label key={e} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={f.entities.includes(e)}
                onChange={() => setF({ ...f, entities: f.entities.includes(e)
                  ? f.entities.filter((x) => x !== e) : [...f.entities, e] })} />
              {e}
            </label>
          ))}
        </div></div>
      <div className="field"><label>Field mappings (JSON: {"{entity: {local: external}}"})</label>
        <textarea rows={3} value={maps} onChange={(e) => setMaps(e.target.value)}
          style={{ fontFamily: "monospace", fontSize: 11.5 }} /></div>
      <div className="field"><label>Stage mappings (JSON: {"{local stage: external stage}"})</label>
        <textarea rows={3} value={stages} onChange={(e) => setStages(e.target.value)}
          style={{ fontFamily: "monospace", fontSize: 11.5 }} /></div>
      <div className="actions">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={save}>{initial ? "Save" : "Connect"}</Button>
      </div>
    </Modal>
  );
}

export default function CrmSync() {
  const { wsParam } = useAuth();
  const toast = useToast();
  const { data: meta } = useApi("/api/devapi/meta");
  const { data: conns, error, loading, reload } = useApi("/api/devapi/sync/connections", { workspace_id: wsParam });
  const [modal, setModal] = useState(null);   // null | "new" | connection object
  const [mapsFor, setMapsFor] = useState(null);

  const act = async (path, ok) => {
    try { const r = await api(path, { method: "POST" }); toast(r.error ? r.error : ok, r.error ? "bad" : "ok"); reload(); }
    catch (e) { toast(e.message, "bad"); }
  };

  if (error) return <ErrorBox msg={error} retry={reload} />;

  return (
    <>
      <PageHeader title="CRM integrations"
        desc="RevCadence works alongside your existing CRM. Connect it here — nothing gets replaced."
        actions={<Button icon={Plug} onClick={() => setModal("new")}>Connect a CRM</Button>} />

      {!loading && (conns || []).length === 0 && (
        <RowCard title="No CRM connected" empty="">
          <p style={{ fontSize: 13, color: "var(--muted)", padding: "0 10px 8px" }}>
            Connect the Generic webhook/API provider to push companies, contacts and deals into
            any system (directly or via Zapier / Make / n8n). Native HubSpot, Salesforce,
            GoHighLevel, Pipedrive and Zoho adapters plug into the same connection later.
          </p>
        </RowCard>
      )}

      <div style={{ display: "grid", gap: 12 }}>
        {(conns || []).map((c) => (
          <RowCard key={c.id}
            title={`${PROVIDER_LABEL[c.provider] || c.provider} · ${c.name}`}
            action={
              <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                {!c.native_ready && <Badge tone="amber">adapter coming soon</Badge>}
                <StatusPill tone={c.active ? "green" : "gray"}>{c.active ? "active" : "off"}</StatusPill>
                <Button size="sm" variant="ghost" icon={Cable}
                  onClick={() => act(`/api/devapi/sync/connections/${c.id}/test`, "Connection OK")}>Test</Button>
                <Button size="sm" variant="ghost" icon={Play}
                  onClick={() => act(`/api/devapi/sync/connections/${c.id}/run`, "Sync queued")}>Sync now</Button>
                {c.failed_records > 0 && (
                  <Button size="sm" variant="ghost" icon={RefreshCw}
                    onClick={() => act(`/api/devapi/sync/connections/${c.id}/retry-failed`, "Retry queued")}>
                    Retry failed</Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setModal(c)}>Configure</Button>
                <Button size="sm" variant="danger" icon={Trash2} onClick={async () => {
                  if (!await confirmDialog("Disconnect this CRM? Mappings are kept.")) return;
                  await api(`/api/devapi/sync/connections/${c.id}`, { method: "DELETE" }); reload();
                }} />
              </span>
            } empty="">
            <div style={{ padding: "0 10px 8px", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", fontSize: 12.5 }}>
              <Badge>{c.direction === "outbound" ? "RevCadence → CRM" : c.direction === "inbound" ? "CRM → RevCadence" : "Two-way"}</Badge>
              <Badge>{POLICY_LABEL[c.conflict_policy]}</Badge>
              {(c.entities || []).map((e) => <Badge key={e} tone="indigo">{e}</Badge>)}
              <span style={{ color: "var(--muted2)" }}>
                {c.mapped_records} mapped{c.failed_records ? ` · ${c.failed_records} failed` : ""}
                {c.last_sync_at ? ` · last sync ${timeAgo(c.last_sync_at)}` : " · never synced"}
              </span>
              {c.last_error && <Badge tone="red">{c.last_error}</Badge>}
              <Button size="sm" variant="ghost" onClick={() => setMapsFor(mapsFor === c.id ? null : c.id)}>
                {mapsFor === c.id ? "Hide records" : "Synced records"}</Button>
            </div>
            {mapsFor === c.id && <Mappings connId={c.id} />}
          </RowCard>
        ))}
      </div>

      {modal && (
        <ConnForm meta={meta} initial={modal === "new" ? null : modal}
          onSaved={() => { setModal(null); reload(); toast("Connection saved"); }}
          onClose={() => setModal(null)} />
      )}
    </>
  );
}

function Mappings({ connId }) {
  const { data } = useApi(`/api/devapi/sync/connections/${connId}/mappings`);
  const TONE = { synced: "green", pending: "blue", failed: "red", conflict: "amber" };
  return (
    <div style={{ padding: "0 10px 10px" }}>
      {(data || []).length === 0 && <div className="rc-empty">Nothing synced yet.</div>}
      {(data || []).map((m) => (
        <div key={m.id} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12.5,
          padding: "5px 0", borderTop: "1px solid #F2F3F5" }}>
          <Badge>{m.type}</Badge>
          <span style={{ fontFamily: "monospace" }}>#{m.local_id} → {m.external_id || "—"}</span>
          <StatusPill tone={TONE[m.status] || "gray"}>{m.status}</StatusPill>
          <span style={{ flex: 1, color: "var(--bad)", fontSize: 11.5, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.error}</span>
          <span style={{ color: "var(--muted2)" }}>{m.last_synced_at ? timeAgo(m.last_synced_at) : ""}</span>
        </div>
      ))}
    </div>
  );
}
