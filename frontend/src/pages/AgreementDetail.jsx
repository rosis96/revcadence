// Agreement editor: structured sections, commercial fields, status/versions,
// send for signature, copy public link, download PDFs, internal countersign,
// and the audit timeline. Executed versions are locked (read-only).
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download, timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Modal, Spinner, useApi } from "../components";

const STATUS_TONE = {
  draft: "", ready: "blue", sent: "blue", viewed: "indigo",
  client_signed: "amber", countersigned: "amber", executed: "green",
  voided: "red", archived: "",
};

function publicUrl(kind, slug) {
  if (!slug) return "";
  const host = window.location.host;
  const bp = host.startsWith("engine.") ? host.replace(/^engine\./, `${kind}.`) : "";
  return bp ? `https://${bp}/${slug}` : `${window.location.origin}/${kind}/${slug}`;
}

export default function AgreementDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { me } = useAuth();
  const { data, error, loading, reload } = useApi(`/api/agreements/${id}`);
  const { data: timeline } = useApi(`/api/activities`, { limit: 50 });
  const [a, setA] = useState(null);
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState(false);
  const [counter, setCounter] = useState(false);
  const [cform, setCform] = useState({ name: me?.user?.name || "", title: "", email: me?.user?.email || "" });

  useEffect(() => { if (data) setA(data); }, [data]);
  if (loading || !a) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const editable = a.status === "draft" || a.status === "ready";
  const url = publicUrl("agreement", a.slug);
  const acts = (timeline || []).filter((t) => (t.data || {}).agreement_id === a.id);

  const save = async (patch) => {
    setBusy("save");
    try { setA(await api(`/api/agreements/${id}`, { method: "PUT", body: patch })); }
    catch (e) { alert(e.message); }
    setBusy("");
  };
  const act = async (path, body, key) => {
    setBusy(key);
    try { setA(await api(`/api/agreements/${id}/${path}`, { method: "POST", body: body || {} })); reload(); }
    catch (e) { alert(e.message); }
    setBusy("");
  };
  const setSection = (i, body) => {
    const secs = a.sections.map((s, j) => (j === i ? { ...s, body } : s));
    setA({ ...a, sections: secs });
  };
  const setFee = (k, v) => setA({ ...a, fields: { ...a.fields, fees: { ...(a.fields.fees || {}), [k]: v } } });
  const copy = () => { navigator.clipboard?.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  const makeInvoice = async () => {
    setBusy("inv");
    try { const inv = await api(`/api/agreements/${id}/invoice`, { method: "POST", body: {} }); nav(`/invoices/${inv.id}`); }
    catch (e) { alert(e.message); }
    setBusy("");
  };
  const doCountersign = async () => {
    setBusy("counter");
    try { setA(await api(`/api/agreements/${id}/countersign`, { method: "POST", body: cform })); setCounter(false); reload(); }
    catch (e) { alert(e.message); }
    setBusy("");
  };

  const fees = a.fields.fees || {};
  return (
    <div style={{ maxWidth: 1080 }}>
      <div className="toolbar">
        <input value={a.title} disabled={!editable}
               onChange={(e) => setA({ ...a, title: e.target.value })}
               onBlur={() => editable && save({ title: a.title })}
               style={{ fontSize: 16, fontWeight: 600, border: "none", background: "transparent", minWidth: 320 }} />
        <Badge>{a.number}</Badge>
        <Badge tone={STATUS_TONE[a.status] || ""}>{a.status}</Badge>
        <Badge>v{a.version}</Badge>
        {a.locked && <Badge tone="green">locked</Badge>}
        <div className="spacer" />
        {a.deal_id && <button className="btn ghost sm" onClick={() => nav(`/pipeline?open=${a.deal_id}`)}>Deal ↗</button>}
        {a.company_id && <button className="btn ghost sm" onClick={() => nav(`/companies/${a.company_id}`)}>Company ↗</button>}
      </div>

      {(a.missing_flags || []).length > 0 && editable && (
        <div className="card" style={{ padding: 12, marginBottom: 12, borderColor: "#f0b429", background: "#fffaf0" }}>
          <b style={{ fontSize: 13 }}>Missing before sending:</b>{" "}
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{a.missing_flags.join(", ")} — fill these in below.</span>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16, alignItems: "start" }}>
        <div>
          {/* commercial fields */}
          <div className="card" style={{ padding: 16, marginBottom: 14 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Commercial terms</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              <div className="field"><label>Effective date</label>
                <input type="date" disabled={!editable} value={a.fields.effective_date || ""}
                       onChange={(e) => setA({ ...a, fields: { ...a.fields, effective_date: e.target.value } })}
                       onBlur={() => editable && save({ fields: { effective_date: a.fields.effective_date } })} /></div>
              <div className="field"><label>Setup fee ({fees.currency || "USD"})</label>
                <input type="number" disabled={!editable} value={fees.setup ?? ""}
                       onChange={(e) => setFee("setup", e.target.value === "" ? null : Number(e.target.value))}
                       onBlur={() => editable && save({ fields: { fees } })} /></div>
              <div className="field"><label>Recurring / {fees.recurring_period || "month"}</label>
                <input type="number" disabled={!editable} value={fees.recurring ?? ""}
                       onChange={(e) => setFee("recurring", e.target.value === "" ? null : Number(e.target.value))}
                       onBlur={() => editable && save({ fields: { fees } })} /></div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="field"><label>Governing law</label>
                <input disabled={!editable} value={a.fields.governing_law || ""}
                       onChange={(e) => setA({ ...a, fields: { ...a.fields, governing_law: e.target.value } })}
                       onBlur={() => editable && save({ fields: { governing_law: a.fields.governing_law } })} /></div>
              <div className="field"><label>Performance / revenue-share</label>
                <input disabled={!editable} value={fees.performance || ""}
                       onChange={(e) => setFee("performance", e.target.value)}
                       onBlur={() => editable && save({ fields: { fees } })} /></div>
            </div>
            <p style={{ fontSize: 11.5, color: "var(--muted)", margin: "2px 0 0" }}>
              Pricing is never auto-generated — only what you enter here (or that came from the approved blueprint) appears in the contract and invoices.</p>
          </div>

          {/* sections */}
          {a.sections.map((s, i) => (
            <div className="card" key={s.key} style={{ padding: 14, marginBottom: 10 }}>
              <label style={{ fontSize: 12.5, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".03em", color: "var(--muted)" }}>{s.label}</label>
              <textarea rows={Math.min(10, Math.max(3, (s.body || "").split("\n").length + 1))}
                        disabled={!editable} style={{ width: "100%", marginTop: 6, fontSize: 13 }}
                        value={s.body} onChange={(e) => setSection(i, e.target.value)}
                        onBlur={() => editable && save({ sections: a.sections })} />
            </div>
          ))}
        </div>

        {/* right rail */}
        <div>
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Lifecycle</h3>
            {editable && (
              <button className="btn" style={{ width: "100%", marginBottom: 6 }} disabled={busy === "send"}
                      onClick={() => act("send", {}, "send")}>{busy === "send" ? "Sending…" : "Send for signature"}</button>
            )}
            {a.status === "client_signed" && me?.is_master && (
              <button className="btn" style={{ width: "100%", marginBottom: 6 }} onClick={() => setCounter(true)}>Countersign &amp; execute</button>
            )}
            {a.status === "client_signed" && !me?.is_master && (
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>Client signed — an owner/admin must countersign.</div>
            )}
            {a.status === "sent" || a.status === "viewed" ? (
              <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>Awaiting client signature.</div>
            ) : null}
            {a.status === "executed" && (
              <button className="btn" style={{ width: "100%", marginBottom: 6 }} disabled={busy === "inv"} onClick={makeInvoice}>
                {busy === "inv" ? "Creating…" : "Create invoice"}</button>
            )}
            {editable && (
              <button className="btn ghost sm" style={{ width: "100%", marginBottom: 6 }}
                      onClick={() => act("status", { status: "voided" }, "void")}>Void</button>
            )}
            {!editable && a.status !== "executed" && a.status !== "voided" && (
              <button className="btn ghost sm" style={{ width: "100%", marginBottom: 6 }} disabled={busy === "ver"}
                      onClick={() => api(`/api/agreements/${id}/version`, { method: "POST" }).then((nv) => nav(`/agreements/${nv.id}`))}>
                New version / amendment</button>
            )}
            {a.status === "executed" && (
              <button className="btn ghost sm" style={{ width: "100%" }} disabled={busy === "ver"}
                      onClick={() => api(`/api/agreements/${id}/version`, { method: "POST" }).then((nv) => nav(`/agreements/${nv.id}`))}>
                Amend (new version)</button>
            )}
          </div>

          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Public link</h3>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input readOnly value={url} onFocus={(e) => e.target.select()}
                     style={{ flex: 1, fontFamily: "monospace", fontSize: 11, padding: "6px 8px" }} />
              <button className="btn ghost sm" onClick={copy}>{copied ? "✓" : "Copy"}</button>
            </div>
            {(a.status !== "draft" && a.status !== "ready") && (
              <a href={url} target="_blank" rel="noreferrer" className="btn ghost sm" style={{ display: "inline-block", marginTop: 8 }}>Open public page →</a>
            )}
            <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>Views: {a.view_count}</div>
          </div>

          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Download PDF</h3>
            <button className="btn ghost sm" style={{ width: "100%", marginBottom: 6 }}
                    onClick={() => download(`/api/agreements/${id}/pdf?mode=draft`)}>Draft PDF</button>
            {a.client_signed_at && (
              <button className="btn ghost sm" style={{ width: "100%", marginBottom: 6 }}
                      onClick={() => download(`/api/agreements/${id}/pdf?mode=client_signed`)}>Client-signed PDF</button>
            )}
            {a.executed_at && (
              <button className="btn sm" style={{ width: "100%" }}
                      onClick={() => download(`/api/agreements/${id}/pdf?mode=executed`)}>Executed PDF</button>
            )}
          </div>

          {(a.client_signed_at || a.countersigned_at) && (
            <div className="card" style={{ padding: 14, marginBottom: 12 }}>
              <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Signatures</h3>
              <div style={{ fontSize: 12.5 }}>
                <div><b>{a.client_signer_name || "—"}</b> <span style={{ color: "var(--muted)" }}>(client)</span></div>
                <div style={{ color: "var(--muted)", fontSize: 11.5, marginBottom: 6 }}>{a.client_signed_at ? new Date(a.client_signed_at + "Z").toLocaleString() : "pending"}</div>
                <div><b>{a.counter_signer_name || "—"}</b> <span style={{ color: "var(--muted)" }}>(RevCadence)</span></div>
                <div style={{ color: "var(--muted)", fontSize: 11.5 }}>{a.countersigned_at ? new Date(a.countersigned_at + "Z").toLocaleString() : "pending"}</div>
                {a.checksum && <div style={{ fontSize: 10.5, color: "var(--muted)", marginTop: 6, wordBreak: "break-all" }}>checksum {a.checksum.slice(0, 24)}…</div>}
              </div>
            </div>
          )}

          <div className="card" style={{ padding: 14 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Audit history</h3>
            {acts.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>No events yet.</div>}
            {acts.map((t) => (
              <div key={t.id} style={{ fontSize: 12, padding: "5px 0", borderTop: "1px solid var(--line,#eee)" }}>
                {t.title}<div style={{ color: "var(--muted)", fontSize: 11 }}>{timeAgo(t.occurred_at)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {counter && (
        <Modal title="Countersign & execute" onClose={() => setCounter(false)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            The client has signed. Countersigning executes the agreement, locks the version, generates the executed PDF, and moves the deal to Closed Won.</p>
          <div className="field"><label>Your full name</label>
            <input value={cform.name} onChange={(e) => setCform({ ...cform, name: e.target.value })} autoFocus /></div>
          <div className="field"><label>Title</label>
            <input value={cform.title} onChange={(e) => setCform({ ...cform, title: e.target.value })} placeholder="Founder" /></div>
          <div className="actions">
            <button className="btn ghost" onClick={() => setCounter(false)}>Cancel</button>
            <button className="btn" disabled={busy === "counter" || !cform.name} onClick={doCountersign}>
              {busy === "counter" ? "Executing…" : "Countersign & execute"}</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
