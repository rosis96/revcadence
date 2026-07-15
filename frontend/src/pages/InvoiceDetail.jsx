// Invoice editor/view: bill-to, line items, totals, notes/instructions, issue,
// record payment status, void, copy public link, download PDF.
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, download } from "../api";
import { Badge, ErrorBox, Modal, Spinner, useApi } from "../components";

const TONE = { draft: "", issued: "blue", viewed: "indigo", partially_paid: "amber", paid: "green", overdue: "red", void: "" };

function publicUrl(slug) {
  if (!slug) return "";
  const host = window.location.host;
  const bp = host.startsWith("engine.") ? host.replace(/^engine\./, "invoice.") : "";
  return bp ? `https://${bp}/${slug}` : `${window.location.origin}/invoice/${slug}`;
}

export default function InvoiceDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi(`/api/invoices/${id}`);
  const [inv, setInv] = useState(null);
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState(false);
  const [payOpen, setPayOpen] = useState(false);
  const [pay, setPay] = useState("");

  useEffect(() => { if (data) setInv(data); }, [data]);
  if (loading || !inv) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const editable = inv.status === "draft";
  const url = publicUrl(inv.slug);
  const items = inv.line_items || [];

  const save = async (patch) => {
    setBusy("save");
    try { setInv(await api(`/api/invoices/${id}`, { method: "PUT", body: patch })); }
    catch (e) { alert(e.message); }
    setBusy("");
  };
  const setItem = (i, k, v) => {
    const next = items.map((li, j) => (j === i ? { ...li, [k]: k === "description" ? v : Number(v) } : li));
    setInv({ ...inv, line_items: next });
  };
  const addItem = () => setInv({ ...inv, line_items: [...items, { description: "", quantity: 1, rate: 0 }] });
  const rmItem = (i) => { const next = items.filter((_, j) => j !== i); setInv({ ...inv, line_items: next }); save({ line_items: next }); };
  const copy = () => { navigator.clipboard?.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  const doAction = async (path, body, key) => {
    setBusy(key);
    try { setInv(await api(`/api/invoices/${id}/${path}`, { method: "POST", body: body || {} })); reload(); }
    catch (e) { alert(e.message); }
    setBusy("");
  };

  const cur = inv.currency;
  const fmt = (n) => `${cur} ${(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div style={{ maxWidth: 960 }}>
      <div className="toolbar">
        <h1 style={{ fontSize: 18 }}>Invoice {inv.number}</h1>
        <Badge tone={TONE[inv.status] || ""}>{inv.status}</Badge>
        <div className="spacer" />
        {inv.agreement_id && <button className="btn ghost sm" onClick={() => nav(`/agreements/${inv.agreement_id}`)}>Agreement ↗</button>}
        {inv.company_id && <button className="btn ghost sm" onClick={() => nav(`/companies/${inv.company_id}`)}>Company ↗</button>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 16, alignItems: "start" }}>
        <div>
          <div className="card" style={{ padding: 16, marginBottom: 14 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Bill to</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="field"><label>Company</label>
                <input disabled={!editable} value={inv.bill_to_company || ""} onChange={(e) => setInv({ ...inv, bill_to_company: e.target.value })} onBlur={() => editable && save({ bill_to_company: inv.bill_to_company })} /></div>
              <div className="field"><label>Name</label>
                <input disabled={!editable} value={inv.bill_to_name || ""} onChange={(e) => setInv({ ...inv, bill_to_name: e.target.value })} onBlur={() => editable && save({ bill_to_name: inv.bill_to_name })} /></div>
              <div className="field"><label>Email</label>
                <input disabled={!editable} value={inv.bill_to_email || ""} onChange={(e) => setInv({ ...inv, bill_to_email: e.target.value })} onBlur={() => editable && save({ bill_to_email: inv.bill_to_email })} /></div>
              <div className="field"><label>Currency</label>
                <input disabled={!editable} value={inv.currency} onChange={(e) => setInv({ ...inv, currency: e.target.value })} onBlur={() => editable && save({ currency: inv.currency })} /></div>
              <div className="field"><label>Issue date</label>
                <input type="date" disabled={!editable} value={inv.issue_date || ""} onChange={(e) => setInv({ ...inv, issue_date: e.target.value })} onBlur={() => editable && save({ issue_date: inv.issue_date })} /></div>
              <div className="field"><label>Due date</label>
                <input type="date" disabled={!editable} value={inv.due_date || ""} onChange={(e) => setInv({ ...inv, due_date: e.target.value })} onBlur={() => editable && save({ due_date: inv.due_date })} /></div>
            </div>
          </div>

          <div className="card" style={{ padding: 16, marginBottom: 14 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Line items</h3>
            <table className="tbl">
              <thead><tr><th>Description</th><th style={{ width: 70 }}>Qty</th><th style={{ width: 110 }}>Rate</th><th style={{ width: 110, textAlign: "right" }}>Amount</th><th></th></tr></thead>
              <tbody>
                {items.map((li, i) => (
                  <tr key={i}>
                    <td><input disabled={!editable} value={li.description || ""} style={{ width: "100%" }}
                               onChange={(e) => setItem(i, "description", e.target.value)} onBlur={() => editable && save({ line_items: items })} /></td>
                    <td><input type="number" disabled={!editable} value={li.quantity ?? 1} style={{ width: "100%" }}
                               onChange={(e) => setItem(i, "quantity", e.target.value)} onBlur={() => editable && save({ line_items: items })} /></td>
                    <td><input type="number" disabled={!editable} value={li.rate ?? 0} style={{ width: "100%" }}
                               onChange={(e) => setItem(i, "rate", e.target.value)} onBlur={() => editable && save({ line_items: items })} /></td>
                    <td style={{ textAlign: "right", fontWeight: 600 }}>{fmt((li.quantity || 0) * (li.rate || 0))}</td>
                    <td>{editable && <button className="btn ghost sm" onClick={() => rmItem(i)}>✕</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {editable && <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={addItem}>+ Add line</button>}
          </div>

          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="field"><label>Tax rate (%)</label>
                <input type="number" disabled={!editable} value={inv.tax_rate ?? 0} onChange={(e) => setInv({ ...inv, tax_rate: Number(e.target.value) })} onBlur={() => editable && save({ tax_rate: inv.tax_rate })} /></div>
              <div className="field"><label>Discount ({cur})</label>
                <input type="number" disabled={!editable} value={inv.discount_amount ?? 0} onChange={(e) => setInv({ ...inv, discount_amount: Number(e.target.value) })} onBlur={() => editable && save({ discount_amount: inv.discount_amount })} /></div>
            </div>
            <div className="field"><label>Payment instructions</label>
              <textarea rows={2} disabled={!editable} value={inv.payment_instructions || ""} onChange={(e) => setInv({ ...inv, payment_instructions: e.target.value })} onBlur={() => editable && save({ payment_instructions: inv.payment_instructions })} /></div>
            <div className="field"><label>Notes</label>
              <textarea rows={2} disabled={!editable} value={inv.notes || ""} onChange={(e) => setInv({ ...inv, notes: e.target.value })} onBlur={() => editable && save({ notes: inv.notes })} /></div>
          </div>
        </div>

        <div>
          <div className="card" style={{ padding: 16, marginBottom: 12 }}>
            <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0" }}><span>Subtotal</span><span>{fmt(inv.subtotal)}</span></div>
            {inv.discount_amount ? <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0" }}><span>Discount</span><span>-{fmt(inv.discount_amount)}</span></div> : null}
            {inv.tax_amount ? <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0" }}><span>Tax</span><span>{fmt(inv.tax_amount)}</span></div> : null}
            <div className="row" style={{ display: "flex", justifyContent: "space-between", fontWeight: 800, fontSize: 16, borderTop: "2px solid var(--ink,#111)", marginTop: 6, paddingTop: 8 }}><span>Total</span><span>{fmt(inv.total)}</span></div>
            {inv.amount_paid ? <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0" }}><span>Paid</span><span>{fmt(inv.amount_paid)}</span></div> : null}
            <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0", color: "var(--muted)" }}><span>Balance due</span><span>{fmt(inv.balance_due)}</span></div>
          </div>

          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            {editable && <button className="btn" style={{ width: "100%", marginBottom: 6 }} disabled={busy === "issue"} onClick={() => doAction("issue", {}, "issue")}>{busy === "issue" ? "Issuing…" : "Issue invoice"}</button>}
            {inv.status !== "draft" && inv.status !== "void" && inv.status !== "paid" && (
              <button className="btn" style={{ width: "100%", marginBottom: 6 }} onClick={() => { setPay(String(inv.balance_due)); setPayOpen(true); }}>Record payment</button>
            )}
            <button className="btn ghost sm" style={{ width: "100%", marginBottom: 6 }} onClick={() => download(`/api/invoices/${id}/pdf`)}>Download PDF</button>
            {inv.status !== "void" && inv.status !== "paid" && <button className="btn ghost sm" style={{ width: "100%" }} onClick={() => doAction("void", {}, "void")}>Void</button>}
          </div>

          {inv.status !== "draft" && (
            <div className="card" style={{ padding: 14 }}>
              <h3 style={{ fontSize: 13, margin: "0 0 8px" }}>Public link</h3>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input readOnly value={url} onFocus={(e) => e.target.select()} style={{ flex: 1, fontFamily: "monospace", fontSize: 11, padding: "6px 8px" }} />
                <button className="btn ghost sm" onClick={copy}>{copied ? "✓" : "Copy"}</button>
              </div>
              <a href={url} target="_blank" rel="noreferrer" className="btn ghost sm" style={{ display: "inline-block", marginTop: 8 }}>Open →</a>
              <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>Views: {inv.view_count}</div>
            </div>
          )}
        </div>
      </div>

      {payOpen && (
        <Modal title="Record payment" onClose={() => setPayOpen(false)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>Enter the total amount received so far ({cur}). This updates the status — no payment processor is connected.</p>
          <div className="field"><label>Amount paid ({cur})</label>
            <input type="number" value={pay} onChange={(e) => setPay(e.target.value)} autoFocus /></div>
          <div className="actions">
            <button className="btn ghost" onClick={() => setPayOpen(false)}>Cancel</button>
            <button className="btn" onClick={() => { doAction("payment", { amount_paid: Number(pay) }, "pay"); setPayOpen(false); }}>Save</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
