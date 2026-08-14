import { confirmDialog } from "../components";
// Settings → Developers: API keys, request logs, webhook endpoints + deliveries,
// and the client-facing API documentation. Shared components only.
import { useMemo, useState } from "react";
import { Copy, ExternalLink, KeyRound, Plus, RefreshCw, RotateCw, Trash2, Webhook } from "lucide-react";
import { api, localDate, timeAgo } from "../api";
import { useAuth } from "../auth";
import {
  Badge, Button, ConfirmDialog, DataTable, ErrorBox, Modal, PageHeader, RowCard,
  StatusPill, Tabs, useApi, useToast,
} from "../components";

function SecretModal({ title, secret, note, onClose }) {
  const toast = useToast();
  return (
    <Modal title={title} onClose={onClose}>
      <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>{note} <b>It will not be shown again.</b></p>
      <div style={{ display: "flex", gap: 8 }}>
        <input readOnly value={secret} onFocus={(e) => e.target.select()}
          style={{ flex: 1, fontFamily: "monospace", fontSize: 12 }} />
        <Button variant="secondary" icon={Copy}
          onClick={() => { navigator.clipboard?.writeText(secret); toast("Copied"); }}>Copy</Button>
      </div>
      <div className="actions"><Button onClick={onClose}>I've stored it safely</Button></div>
    </Modal>
  );
}

function KeysTab() {
  const { wsParam } = useAuth();
  const toast = useToast();
  const { data: meta } = useApi("/api/devapi/meta");
  const { data: keys, error, loading, reload } = useApi("/api/devapi/keys", { workspace_id: wsParam });
  const [modal, setModal] = useState(false);
  const [secret, setSecret] = useState(null);
  const [revoke, setRevoke] = useState(null);
  const [logsFor, setLogsFor] = useState(null);
  const [form, setForm] = useState({ name: "", scopes: [], expires_days: "" });

  const create = async () => {
    try {
      const r = await api("/api/devapi/keys", { method: "POST", body: {
        name: form.name, scopes: form.scopes.length ? form.scopes : undefined,
        expires_days: form.expires_days ? Number(form.expires_days) : null,
        workspace_id: wsParam ? Number(wsParam) : undefined } });
      setModal(false); setSecret({ title: "API key created", secret: r.key,
        note: "Copy this key now and store it in your client system." });
      setForm({ name: "", scopes: [], expires_days: "" });
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const rotate = async (k) => {
    try {
      const r = await api(`/api/devapi/keys/${k.id}/rotate`, { method: "POST" });
      setSecret({ title: "Key rotated", secret: r.key,
        note: "The old key is revoked. Update your client system with this replacement." });
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };

  const columns = useMemo(() => [
    { accessorKey: "name", header: "Name", size: 180,
      cell: ({ row }) => <div><div className="lead-nm">{row.original.name}</div>
        <div className="lead-sub" style={{ fontFamily: "monospace" }}>{row.original.prefix}…</div></div> },
    { id: "status", header: "Status", size: 110, accessorFn: (k) => (k.revoked_at ? "revoked" : "active"),
      cell: ({ row }) => row.original.revoked_at
        ? <StatusPill tone="red">revoked</StatusPill>
        : (row.original.expires_at && new Date(row.original.expires_at) < new Date())
          ? <StatusPill tone="amber">expired</StatusPill>
          : <StatusPill tone="green">active</StatusPill> },
    { id: "scopes", header: "Scopes", size: 220, enableSorting: false,
      cell: ({ row }) => <span style={{ fontSize: 11.5, color: "var(--muted)" }}>
        {(row.original.scopes || []).length} scope(s)</span> },
    { accessorKey: "last_used_at", header: "Last used", size: 130,
      cell: ({ getValue }) => (getValue() ? timeAgo(getValue()) : "never") },
    { accessorKey: "expires_at", header: "Expires", size: 120,
      cell: ({ getValue }) => (getValue() ? localDate(getValue()) : "never") },
    { id: "acts", header: "", size: 220, enableSorting: false,
      cell: ({ row }) => !row.original.revoked_at && (
        <span style={{ display: "inline-flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="ghost" onClick={() => setLogsFor(row.original)}>Logs</Button>
          <Button size="sm" variant="ghost" icon={RotateCw} onClick={() => rotate(row.original)}>Rotate</Button>
          <Button size="sm" variant="danger" onClick={() => setRevoke(row.original)}>Revoke</Button>
        </span>) },
  ], []);

  if (error) return <ErrorBox msg={error} retry={reload} />;
  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <Button icon={Plus} onClick={() => setModal(true)}>Create key</Button>
      </div>
      <DataTable id="api-keys" columns={columns} data={keys || []} loading={loading}
        searchPlaceholder="Search keys…" getRowId={(r) => String(r.id)}
        emptyIcon={KeyRound} emptyTitle="No API keys yet"
        emptyHint="Create a key to let a client system talk to the RevCadence API."
        emptyAction={<Button icon={Plus} onClick={() => setModal(true)}>Create key</Button>} />

      {modal && (
        <Modal title="Create API key" onClose={() => setModal(false)}>
          <div className="field"><label>Name</label>
            <input value={form.name} placeholder="e.g. HubSpot bridge, Zapier"
              onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></div>
          <div className="field"><label>Expires (days, empty = never)</label>
            <input type="number" value={form.expires_days}
              onChange={(e) => setForm({ ...form, expires_days: e.target.value })} /></div>
          <div className="field"><label>Scopes (none selected = all)</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4, fontSize: 12.5 }}>
              {(meta?.scopes || []).map((s) => (
                <label key={s} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={form.scopes.includes(s)}
                    onChange={() => setForm({ ...form, scopes: form.scopes.includes(s)
                      ? form.scopes.filter((x) => x !== s) : [...form.scopes, s] })} />
                  {s}
                </label>
              ))}
            </div></div>
          <div className="actions">
            <Button variant="ghost" onClick={() => setModal(false)}>Cancel</Button>
            <Button onClick={create}>Create key</Button>
          </div>
        </Modal>
      )}
      {secret && <SecretModal {...secret} onClose={() => setSecret(null)} />}
      {revoke && (
        <ConfirmDialog danger title={`Revoke "${revoke.name}"?`}
          message="Every system using this key loses access immediately."
          confirmLabel="Revoke"
          onConfirm={async () => { await api(`/api/devapi/keys/${revoke.id}/revoke`, { method: "POST" }); toast("Key revoked"); reload(); }}
          onClose={() => setRevoke(null)} />
      )}
      {logsFor && <RequestLogs k={logsFor} onClose={() => setLogsFor(null)} />}
    </>
  );
}

function RequestLogs({ k, onClose }) {
  const { data } = useApi(`/api/devapi/keys/${k.id}/requests`);
  return (
    <Modal title={`Requests · ${k.name}`} onClose={onClose}>
      {(data || []).length === 0 && <p style={{ color: "var(--muted)", fontSize: 13 }}>No requests yet.</p>}
      {(data || []).map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 10, fontSize: 12.5, padding: "6px 0",
          borderTop: "1px solid var(--border)", fontFamily: "monospace" }}>
          <b style={{ width: 52 }}>{r.method}</b>
          <span style={{ flex: 1 }}>{r.path}</span>
          <Badge tone={r.status < 400 ? "green" : "red"}>{r.status}</Badge>
          <span style={{ color: "var(--muted2)" }}>{r.latency_ms}ms · {timeAgo(r.at)}</span>
        </div>
      ))}
    </Modal>
  );
}

function HooksTab() {
  const { wsParam } = useAuth();
  const toast = useToast();
  const { data: meta } = useApi("/api/devapi/meta");
  const { data: hooks, error, loading, reload } = useApi("/api/devapi/webhooks", { workspace_id: wsParam });
  const [modal, setModal] = useState(false);
  const [secret, setSecret] = useState(null);
  const [openHook, setOpenHook] = useState(null);
  const [form, setForm] = useState({ url: "", events: [] });

  const create = async () => {
    try {
      const r = await api("/api/devapi/webhooks", { method: "POST", body: {
        url: form.url, events: form.events, workspace_id: wsParam ? Number(wsParam) : undefined } });
      setModal(false);
      setSecret({ title: "Webhook endpoint created", secret: r.secret,
        note: "Use this signing secret to verify X-RevCadence-Signature on every delivery." });
      setForm({ url: "", events: [] });
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };

  if (error) return <ErrorBox msg={error} retry={reload} />;
  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <Button icon={Plus} onClick={() => setModal(true)}>Add endpoint</Button>
      </div>
      {(hooks || []).length === 0 && !loading && (
        <RowCard title="Webhook endpoints" empty="No endpoints yet. Add one to receive signed events."><span /></RowCard>
      )}
      <div style={{ display: "grid", gap: 12 }}>
        {(hooks || []).map((h) => (
          <RowCard key={h.id} title={h.url}
            action={
              <span style={{ display: "inline-flex", gap: 6 }}>
                <StatusPill tone={h.active ? "green" : "gray"}>{h.active ? "active" : "off"}</StatusPill>
                <Button size="sm" variant="ghost" onClick={async () => {
                  await api(`/api/devapi/webhooks/${h.id}/test`, { method: "POST" }); toast("Test event queued");
                }}>Send test</Button>
                <Button size="sm" variant="ghost" onClick={() => setOpenHook(openHook === h.id ? null : h.id)}>
                  Deliveries</Button>
                <Button size="sm" variant="ghost" onClick={async () => {
                  await api(`/api/devapi/webhooks/${h.id}`, { method: "PUT", body: { active: !h.active } }); reload();
                }}>{h.active ? "Disable" : "Enable"}</Button>
                <Button size="sm" variant="danger" icon={Trash2} onClick={async () => {
                  if (!await confirmDialog("Delete this endpoint?")) return;
                  await api(`/api/devapi/webhooks/${h.id}`, { method: "DELETE" }); reload();
                }} />
              </span>
            }
            empty="">
            <div style={{ padding: "0 10px 8px", display: "flex", gap: 6, flexWrap: "wrap" }}>
              {(h.events || []).map((e) => <Badge key={e}>{e}</Badge>)}
              {h.failure_count > 0 && <Badge tone="red">{h.failure_count} recent failures</Badge>}
              {h.last_delivery_at && <span style={{ fontSize: 11.5, color: "var(--muted2)" }}>
                last delivery {timeAgo(h.last_delivery_at)}</span>}
            </div>
            {openHook === h.id && <Deliveries hookId={h.id} />}
          </RowCard>
        ))}
      </div>

      {modal && (
        <Modal title="Add webhook endpoint" onClose={() => setModal(false)}>
          <div className="field"><label>Endpoint URL</label>
            <input value={form.url} placeholder="https://your-system.com/webhooks/revcadence"
              onChange={(e) => setForm({ ...form, url: e.target.value })} autoFocus /></div>
          <div className="field"><label>Events</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 12.5 }}>
              {(meta?.events || []).map((e) => (
                <label key={e} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={form.events.includes(e)}
                    onChange={() => setForm({ ...form, events: form.events.includes(e)
                      ? form.events.filter((x) => x !== e) : [...form.events, e] })} />
                  {e}
                </label>
              ))}
            </div></div>
          <div className="actions">
            <Button variant="ghost" onClick={() => setModal(false)}>Cancel</Button>
            <Button onClick={create} disabled={!form.url || form.events.length === 0}>Create endpoint</Button>
          </div>
        </Modal>
      )}
      {secret && <SecretModal {...secret} onClose={() => setSecret(null)} />}
    </>
  );
}

function Deliveries({ hookId }) {
  const toast = useToast();
  const { data, reload } = useApi(`/api/devapi/webhooks/${hookId}/deliveries`);
  const TONE = { delivered: "green", pending: "blue", failed: "amber", dead: "red" };
  return (
    <div style={{ padding: "6px 10px 10px" }}>
      {(data || []).length === 0 && <div className="rc-empty">No deliveries yet.</div>}
      {(data || []).map((d) => (
        <div key={d.id} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12.5,
          padding: "6px 0", borderTop: "1px solid var(--border)" }}>
          <StatusPill tone={TONE[d.status] || "gray"}>{d.status}</StatusPill>
          <span style={{ fontFamily: "monospace", flex: 1 }}>{d.event_type}</span>
          <span style={{ color: "var(--muted2)" }}>attempt {d.attempts}{d.response_status ? ` · HTTP ${d.response_status}` : ""} · {timeAgo(d.created_at)}</span>
          {(d.status === "failed" || d.status === "dead") && (
            <Button size="sm" variant="ghost" icon={RefreshCw} onClick={async () => {
              await api(`/api/devapi/webhooks/deliveries/${d.id}/replay`, { method: "POST" });
              toast("Replay queued"); reload();
            }}>Replay</Button>
          )}
        </div>
      ))}
    </div>
  );
}

function DocsTab() {
  const base = `${window.location.origin}/api/v1`;
  const Code = ({ children }) => (
    <pre style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 10,
      padding: 14, fontSize: 12, overflowX: "auto", fontFamily: "monospace" }}>{children}</pre>
  );
  return (
    <div style={{ maxWidth: 780, display: "grid", gap: 18 }}>
      <RowCard title="Interactive reference" empty=""
        action={<a href={`${base}/docs`} target="_blank" rel="noreferrer">Open API docs <ExternalLink size={12} /></a>}>
        <p style={{ fontSize: 13, color: "var(--muted)", padding: "0 10px 8px" }}>
          The full, always-current reference lives at <code>{base}/docs</code>. The OpenAPI spec
          (external endpoints only) is downloadable at <code>{base}/openapi.json</code>.
        </p>
      </RowCard>
      <RowCard title="Authentication" empty="">
        <div style={{ padding: "0 10px 8px" }}>
          <p style={{ fontSize: 13, color: "var(--muted)" }}>Create an API key above, then send it as a Bearer token. All data is scoped to your workspace.</p>
          <Code>{`curl ${base}/companies \\\n  -H "Authorization: Bearer rck_..."`}</Code>
        </div>
      </RowCard>
      <RowCard title="Pagination, filtering, idempotency" empty="">
        <div style={{ padding: "0 10px 8px" }}>
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Lists accept <code>page</code>, <code>page_size</code> (max 100), <code>sort=field:asc|desc</code>,{" "}
            <code>updated_since</code> (ISO 8601) and <code>external_id</code>. Writes accept an{" "}
            <code>Idempotency-Key</code> header — retrying with the same key never creates duplicates.
            Rate limit: 120 requests/minute per key (HTTP 429 + Retry-After when exceeded).
          </p>
          <Code>{`curl -X POST ${base}/contacts \\\n  -H "Authorization: Bearer rck_..." \\\n  -H "Idempotency-Key: 3f2c-…" \\\n  -H "Content-Type: application/json" \\\n  -d '{"email":"jane@acme.com","first_name":"Jane","external_id":"hs_9912","external_source":"hubspot"}'`}</Code>
        </div>
      </RowCard>
      <RowCard title="Verifying webhook signatures" empty="">
        <div style={{ padding: "0 10px 8px" }}>
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Every delivery includes <code>X-RevCadence-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code>.
            Recompute HMAC-SHA256 over <code>{"{t}.{raw_body}"}</code> with your endpoint's signing secret
            and compare with constant-time equality. Reject if <code>t</code> is older than 5 minutes.
          </p>
          <Code>{`import hmac, hashlib\n\ndef verify(secret, header, raw_body):\n    parts = dict(p.split("=", 1) for p in header.split(","))\n    expected = hmac.new(secret.encode(),\n        f"{parts['t']}.".encode() + raw_body,\n        hashlib.sha256).hexdigest()\n    return hmac.compare_digest(expected, parts["v1"])`}</Code>
        </div>
      </RowCard>
      <RowCard title="Errors" empty="">
        <div style={{ padding: "0 10px 8px" }}>
          <Code>{`{"error": {"code": "duplicate_external_id", "message": "…"}}\n\n401 missing/invalid/revoked/expired key\n403 missing scope\n404 not found (workspace-scoped)\n409 duplicate (external_id / email)\n422 validation\n429 rate limited (Retry-After header)`}</Code>
        </div>
      </RowCard>
    </div>
  );
}

export default function Developers() {
  const [tab, setTab] = useState("keys");
  return (
    <>
      <PageHeader title="Developers"
        desc="API keys, webhooks and documentation for connecting your existing systems to RevCadence." />
      <div style={{ marginBottom: 16 }}>
        <Tabs value={tab} onChange={setTab} tabs={[
          { key: "keys", label: "API keys" },
          { key: "hooks", label: "Webhooks" },
          { key: "docs", label: "API documentation" },
        ]} />
      </div>
      {tab === "keys" && <KeysTab />}
      {tab === "hooks" && <HooksTab />}
      {tab === "docs" && <DocsTab />}
    </>
  );
}
