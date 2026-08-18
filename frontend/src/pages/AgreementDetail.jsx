// Agreement editor (DESIGN_SYSTEM.md step 7). Split view: quiet section editor
// on the left, live document preview on the right, signing timeline, versions,
// countersign, PDFs. Executed versions stay locked. Shared components only.
import { useEffect, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useNavigate, useParams } from "react-router-dom";
import { Download, FileSignature, GitBranch, Link2, Receipt, Send } from "lucide-react";
import { api, download, timeAgo } from "../api";
import { useAppPath } from "../clientspace/appPath";
import { useAuth } from "../auth";
import {
  Area, Badge, Breadcrumbs, Button, ErrorBox, Modal, RowCard, SaveIndicator, Spinner,
  StatusPill, StatusSteps, VersionList, useApi, useAutoSave, useToast,
} from "../components";

const STATUS_TONE = {
  draft: "gray", ready: "blue", sent: "blue", viewed: "amber",
  client_signed: "amber", countersigned: "amber", executed: "green",
  voided: "red", archived: "gray",
};
const LIFE_STEPS = [
  { key: "draft", label: "Draft" }, { key: "sent", label: "Sent" },
  { key: "viewed", label: "Viewed by client" }, { key: "client_signed", label: "Client signed" },
  { key: "executed", label: "Executed" },
];
const stepKey = (s) => (s === "ready" ? "draft" : s === "countersigned" ? "client_signed" : s);

function publicUrl(slug) {
  if (!slug) return "";
  const host = window.location.host;
  const bp = host.startsWith("engine.") ? host.replace(/^engine\./, "agreement.") : "";
  return bp ? `https://${bp}/${slug}` : `${window.location.origin}/agreement/${slug}`;
}
const fmtMoney = (cur, n) => (n == null || n === "" ? null : `${cur || "USD"} ${Number(n).toLocaleString()}`);

export default function AgreementDetail() {
  const appTo = useAppPath();
  const { id } = useParams();
  const nav = useNavigate();
  const { me } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useApi(`/api/agreements/${id}`);
  const { data: versions } = useApi(`/api/agreements/${id}/versions`);
  const { data: timeline } = useApi(`/api/activities`, { limit: 50 });
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState("");
  const [counter, setCounter] = useState(false);
  const [cform, setCform] = useState({ name: me?.user?.name || "", title: "", email: me?.user?.email || "" });

  useEffect(() => { if (data) setA(data); }, [data]);

  const editable = a && (a.status === "draft" || a.status === "ready");

  // Notion-style auto-save while editable
  const [saveState] = useAutoSave(
    a && editable ? { title: a.title, sections: a.sections, fields: a.fields } : null,
    async (v) => { if (v) setA(await api(`/api/agreements/${id}`, { method: "PUT", body: v })); },
    { enabled: !!editable },
  );

  if (loading || !a) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const url = publicUrl(a.slug);
  const acts = (timeline || []).filter((t) => (t.data || {}).agreement_id === a.id);
  const fees = a.fields.fees || {};

  const act = async (path, body, key, ok) => {
    setBusy(key);
    try { setA(await api(`/api/agreements/${id}/${path}`, { method: "POST", body: body || {} })); reload(); ok && toast(ok); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const setSection = (i, body) => setA({ ...a, sections: a.sections.map((s, j) => (j === i ? { ...s, body } : s)) });
  const setField = (k, v) => setA({ ...a, fields: { ...a.fields, [k]: v } });
  const setFee = (k, v) => setA({ ...a, fields: { ...a.fields, fees: { ...fees, [k]: v } } });
  const newVersion = () => api(`/api/agreements/${id}/version`, { method: "POST" }).then((nv) => nav(appTo(`/agreements/${nv.id}`)));

  return (
    <>
      <Breadcrumbs items={[{ label: "Blueprints & Agreements", href: appTo("/blueprints") }, { label: a.number || "Agreement" }]} />
      <div className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <input className="doc-title" value={a.title} disabled={!editable} placeholder="Agreement title"
            onChange={(e) => setA({ ...a, title: e.target.value })} />
          <p style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <Badge>{a.number}</Badge>
            <StatusPill tone={STATUS_TONE[a.status] || "gray"}>{a.status.replaceAll("_", " ")}</StatusPill>
            <Badge>v{a.version}</Badge>
            {a.locked && <Badge tone="green">locked</Badge>}
            <SaveIndicator state={editable ? saveState : "idle"} />
          </p>
        </div>
        <div className="acts">
          {editable && <Button icon={Send} loading={busy === "send"} onClick={() => act("send", {}, "send", "Sent for signature")}>Send for signature</Button>}
          {a.status === "client_signed" && me?.is_master &&
            <Button icon={FileSignature} onClick={() => setCounter(true)}>Countersign & execute</Button>}
          {a.status === "executed" &&
            <Button icon={Receipt} loading={busy === "inv"} onClick={async () => {
              setBusy("inv");
              try { const inv = await api(`/api/agreements/${id}/invoice`, { method: "POST", body: {} }); nav(appTo(`/invoices/${inv.id}`)); }
              catch (e) { toast(e.message, "bad"); }
              setBusy("");
            }}>Create invoice</Button>}
          <Button variant="secondary" icon={Link2} onClick={() => { navigator.clipboard?.writeText(url); toast("Public link copied"); }}>Share</Button>
          <Button variant="secondary" icon={Download} onClick={() => download(`/api/agreements/${id}/pdf?mode=${a.executed_at ? "executed" : a.client_signed_at ? "client_signed" : "draft"}`)}>PDF</Button>
          {!editable && a.status !== "voided" &&
            <Button variant="secondary" icon={GitBranch} onClick={newVersion}>New version</Button>}
        </div>
      </div>

      {(a.missing_flags || []).length > 0 && editable && (
        <div className="error-box" style={{ marginBottom: 14, background: "var(--warn-soft)", borderColor: "var(--warn-border)", color: "var(--warn-text)" }}>
          Missing before sending: {a.missing_flags.join(", ")}.
        </div>
      )}

      <div className="doc-split">
        {/* left: the editor */}
        <div style={{ display: "grid", gap: 12 }}>
          <div className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Commercial terms</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              <div className="field"><label>Effective date</label>
                <input type="date" disabled={!editable} value={a.fields.effective_date || ""}
                  onChange={(e) => setField("effective_date", e.target.value)} /></div>
              <div className="field"><label>Setup fee ({fees.currency || "USD"})</label>
                <input type="number" disabled={!editable} value={fees.setup ?? ""}
                  onChange={(e) => setFee("setup", e.target.value === "" ? null : Number(e.target.value))} /></div>
              <div className="field"><label>Recurring / {fees.recurring_period || "month"}</label>
                <input type="number" disabled={!editable} value={fees.recurring ?? ""}
                  onChange={(e) => setFee("recurring", e.target.value === "" ? null : Number(e.target.value))} /></div>
              <div className="field"><label>Governing law</label>
                <input disabled={!editable} value={a.fields.governing_law || ""}
                  onChange={(e) => setField("governing_law", e.target.value)} /></div>
              <div className="field" style={{ gridColumn: "span 2" }}><label>Performance / revenue-share</label>
                <input disabled={!editable} value={fees.performance || ""}
                  onChange={(e) => setFee("performance", e.target.value)} /></div>
            </div>
            <p style={{ fontSize: 11.5, color: "var(--muted2)", margin: "2px 0 0" }}>
              Pricing is never auto-generated. Only what you enter here appears in the contract and invoices.</p>
          </div>

          <div className="card doc-editor" style={{ padding: 8 }}>
            {a.sections.map((s, i) => (
              <div className="doc-sec" key={s.key}>
                <label>{s.label}</label>
                <Area size="lg" disabled={!editable} value={s.body} onChange={(e) => setSection(i, e.target.value)} />
              </div>
            ))}
          </div>
        </div>

        {/* right: live preview + lifecycle */}
        <div className="doc-side">
          <div className="doc-preview">
            <div className="dp-head"><span>Live preview</span><span>{a.number}</span></div>
            <div className="doc-paper">
              <h1>{a.title || "Agreement"}</h1>
              <div className="dp-sub">{a.number} · v{a.version} · {a.fields.effective_date || "effective date TBD"}</div>
              {(fmtMoney(fees.currency, fees.setup) || fmtMoney(fees.currency, fees.recurring) || fees.performance) && (
                <table><tbody>
                  {fmtMoney(fees.currency, fees.setup) && <tr><td>Setup fee</td><td>{fmtMoney(fees.currency, fees.setup)}</td></tr>}
                  {fmtMoney(fees.currency, fees.recurring) && <tr><td>Recurring ({fees.recurring_period || "month"})</td><td>{fmtMoney(fees.currency, fees.recurring)}</td></tr>}
                  {fees.performance && <tr><td>Performance</td><td>{fees.performance}</td></tr>}
                </tbody></table>
              )}
              {a.sections.filter((s) => (s.body || "").trim()).map((s) => (
                <div key={s.key}><h2>{s.label}</h2><p>{s.body}</p></div>
              ))}
            </div>
          </div>

          <RowCard title="Signing timeline" empty="">
            <div style={{ padding: "4px 10px 8px" }}>
              {a.status === "voided"
                ? <StatusPill tone="red">voided</StatusPill>
                : <StatusSteps steps={LIFE_STEPS.map((s) => ({
                    ...s,
                    sub: s.key === "client_signed" && a.client_signed_at
                      ? `${a.client_signer_name || "client"} · ${timeAgo(a.client_signed_at)}`
                      : s.key === "executed" && a.executed_at
                        ? `${a.counter_signer_name || "RevCadence"} · ${timeAgo(a.executed_at)}` : undefined,
                  }))} current={stepKey(a.status)} />}
              {a.checksum && <div style={{ fontSize: 10.5, color: "var(--muted2)", wordBreak: "break-all" }}>checksum {a.checksum.slice(0, 24)}…</div>}
            </div>
          </RowCard>

          <RowCard title="Versions" empty="No versions yet.">
            <div style={{ padding: "0 10px 8px" }}>
              <VersionList versions={(versions || []).map((v) => ({
                label: `v${v.version} · ${v.status.replaceAll("_", " ")}`, at: v.updated_at || v.created_at,
                current: v.id === a.id, id: v.id,
              }))} onOpen={(v) => nav(appTo(`/agreements/${v.id}`))} currentLabel="open" />
            </div>
          </RowCard>

          <RowCard title="Audit history" empty="No events yet.">
            {acts.map((t) => (
              <div key={t.id} style={{ fontSize: 12, padding: "5px 10px", borderTop: "1px solid var(--border)" }}>
                {t.title}<div style={{ color: "var(--muted2)", fontSize: 11 }}>{timeAgo(t.occurred_at)}</div>
              </div>
            ))}
          </RowCard>
        </div>
      </div>

      <AnimatePresence>
      {counter && (
        <Modal key="counter" title="Countersign & execute" onClose={() => setCounter(false)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            The client has signed. Countersigning executes the agreement, locks the version,
            generates the executed PDF, and moves the deal to Closed Won.</p>
          <div className="field"><label>Your full name</label>
            <input value={cform.name} onChange={(e) => setCform({ ...cform, name: e.target.value })} autoFocus /></div>
          <div className="field"><label>Title</label>
            <input value={cform.title} onChange={(e) => setCform({ ...cform, title: e.target.value })} placeholder="Founder" /></div>
          <div className="actions">
            <Button variant="ghost" onClick={() => setCounter(false)}>Cancel</Button>
            <Button loading={busy === "counter"} disabled={!cform.name}
              onClick={() => { act("countersign", cform, "counter", "Agreement executed"); setCounter(false); }}>
              Countersign & execute</Button>
          </div>
        </Modal>
      )}
      </AnimatePresence>
    </>
  );
}
