// Invoice editor (DESIGN_SYSTEM.md step 8). Professional accounting UI:
// bill-to + line items on the left, totals/status/actions/timeline on the right.
// Auto-save while draft; issue → payment → paid lifecycle. Shared components only.
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Download, Link2, Mail, Plus, Send, X } from "lucide-react";
import { api, download, timeAgo } from "../api";
import {
  Badge, Breadcrumbs, Button, ErrorBox, Modal, RowCard, SaveIndicator, Spinner,
  StatusPill, StatusSteps, useApi, useAutoSave, useToast,
} from "../components";

const TONE = { draft: "gray", issued: "blue", viewed: "amber", partially_paid: "amber", paid: "green", overdue: "red", void: "gray" };
const LIFE = [
  { key: "draft", label: "Draft" }, { key: "issued", label: "Issued" },
  { key: "viewed", label: "Viewed" }, { key: "partially_paid", label: "Partially paid" },
  { key: "paid", label: "Paid" },
];
const stepKey = (s) => (s === "overdue" ? "issued" : s);

function publicUrl(slug) {
  if (!slug) return "";
  const host = window.location.host;
  const bp = host.startsWith("engine.") ? host.replace(/^engine\./, "invoice.") : "";
  return bp ? `https://${bp}/${slug}` : `${window.location.origin}/invoice/${slug}`;
}

export default function InvoiceDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data, error, loading, reload } = useApi(`/api/invoices/${id}`);
  const { data: timeline } = useApi(`/api/activities`, { limit: 50 });
  const [inv, setInv] = useState(null);
  const [busy, setBusy] = useState("");
  const [payOpen, setPayOpen] = useState(false);
  const [pay, setPay] = useState("");

  useEffect(() => { if (data) setInv(data); }, [data]);

  const editable = inv?.status === "draft";
  const [saveState] = useAutoSave(
    inv && editable ? {
      number: inv.number,
      bill_to_company: inv.bill_to_company, bill_to_name: inv.bill_to_name, bill_to_email: inv.bill_to_email,
      currency: inv.currency, issue_date: inv.issue_date, due_date: inv.due_date,
      line_items: inv.line_items, tax_rate: inv.tax_rate, discount_amount: inv.discount_amount,
      payment_instructions: inv.payment_instructions, notes: inv.notes,
    } : null,
    async (v) => { if (v) setInv(await api(`/api/invoices/${id}`, { method: "PUT", body: v })); },
    { enabled: !!editable },
  );

  if (loading || !inv) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const url = publicUrl(inv.slug);
  const items = inv.line_items || [];
  const cur = inv.currency;
  const fmt = (n) => `${cur} ${(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const acts = (timeline || []).filter((t) => (t.data || {}).invoice_id === inv.id);

  const doAction = async (path, body, key, ok) => {
    setBusy(key);
    try { setInv(await api(`/api/invoices/${id}/${path}`, { method: "POST", body: body || {} })); reload(); ok && toast(ok); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  // Keep raw values while typing (so a field can be briefly empty); an empty
  // quantity bills as 1 and an empty rate as 0 for the amount math.
  const setItem = (i, k, v) =>
    setInv({ ...inv, line_items: items.map((li, j) => (j === i ? { ...li, [k]: v } : li)) });
  const num = (v, d) => (v === "" || v == null || isNaN(Number(v)) ? d : Number(v));
  const lineAmt = (li) => num(li.quantity, 1) * num(li.rate, 0);
  const emailInvoice = () => {
    const subject = encodeURIComponent(`Invoice ${inv.number}${inv.bill_to_company ? ` — ${inv.bill_to_company}` : ""}`);
    const body = encodeURIComponent(`Hi ${inv.bill_to_name || ""},\n\nPlease find invoice ${inv.number} here:\n${url}\n\nTotal: ${fmt(inv.total)}${inv.due_date ? `\nDue: ${inv.due_date}` : ""}\n\nThank you!`);
    window.location.href = `mailto:${inv.bill_to_email || ""}?subject=${subject}&body=${body}`;
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "Invoices", href: "/invoices" }, { label: inv.number }]} />
      <div className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ fontSize: 22, fontWeight: 650, display: "flex", alignItems: "center", gap: 10 }}>
            Invoice
            {editable
              ? <input value={inv.number || ""} onChange={(e) => setInv({ ...inv, number: e.target.value })}
                  aria-label="Invoice number"
                  style={{ fontSize: 20, fontWeight: 650, border: "1px solid var(--line-2, #d5d9e2)", borderRadius: 8, padding: "3px 10px", width: 190 }} />
              : <span>{inv.number}</span>}
          </h1>
          <p style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <StatusPill tone={TONE[inv.status] || "gray"}>{inv.status.replaceAll("_", " ")}</StatusPill>
            {inv.agreement_id && <a href={`#/agreements/${inv.agreement_id}`} style={{ fontSize: 12.5 }}>Agreement →</a>}
            {inv.company_id && <a href={`#/companies/${inv.company_id}`} style={{ fontSize: 12.5 }}>Company →</a>}
            <SaveIndicator state={editable ? saveState : "idle"} />
          </p>
        </div>
        <div className="acts">
          {editable && <Button icon={Send} loading={busy === "issue"} onClick={() => doAction("issue", {}, "issue", "Invoice issued")}>Issue invoice</Button>}
          {inv.status !== "draft" && inv.status !== "void" && inv.status !== "paid" &&
            <Button onClick={() => { setPay(String(inv.balance_due)); setPayOpen(true); }}>Record payment</Button>}
          <Button variant="secondary" icon={Mail} disabled={inv.status === "draft"} onClick={emailInvoice}>Email</Button>
          <Button variant="secondary" icon={Download} onClick={() => download(`/api/invoices/${id}/pdf`)}>PDF</Button>
          {inv.status !== "draft" &&
            <Button variant="secondary" icon={Link2} onClick={() => { navigator.clipboard?.writeText(url); toast("Public link copied"); }}>Share</Button>}
          {inv.status !== "void" && inv.status !== "paid" &&
            <Button variant="danger" icon={X} loading={busy === "void"} onClick={() => doAction("void", {}, "void", "Invoice voided")}>Void</Button>}
        </div>
      </div>

      <div className="doc-split">
        <div style={{ display: "grid", gap: 12 }}>
          <div className="card" style={{ padding: 22 }}>
            <h3 style={{ fontSize: 12.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", margin: "0 0 14px" }}>Bill to</h3>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div className="field"><label>Company</label>
                <input disabled={!editable} value={inv.bill_to_company || ""} placeholder="Client or company" onChange={(e) => setInv({ ...inv, bill_to_company: e.target.value })} /></div>
              <div className="field"><label>Name (optional)</label>
                <input disabled={!editable} value={inv.bill_to_name || ""} onChange={(e) => setInv({ ...inv, bill_to_name: e.target.value })} /></div>
              <div className="field"><label>Email</label>
                <input disabled={!editable} value={inv.bill_to_email || ""} onChange={(e) => setInv({ ...inv, bill_to_email: e.target.value })} /></div>
              <div className="field"><label>Currency</label>
                <select disabled={!editable} value={inv.currency || "USD"} onChange={(e) => setInv({ ...inv, currency: e.target.value })}>
                  <option>USD</option><option>GBP</option><option>EUR</option></select></div>
              <div className="field"><label>Issue date</label>
                <input type="date" disabled={!editable} value={inv.issue_date || ""} onChange={(e) => setInv({ ...inv, issue_date: e.target.value })} /></div>
              <div className="field"><label>Due date</label>
                <input type="date" disabled={!editable} value={inv.due_date || ""} onChange={(e) => setInv({ ...inv, due_date: e.target.value })} /></div>
            </div>
          </div>

          <div className="card" style={{ padding: 22 }}>
            <h3 style={{ fontSize: 12.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--muted)", margin: "0 0 14px" }}>Line items</h3>
            <table className="dt" style={{ tableLayout: "fixed", width: "100%" }}>
              <thead><tr>
                <th>Description</th>
                <th style={{ width: 92, textAlign: "center" }}>Qty</th>
                <th style={{ width: 130, textAlign: "right" }}>Unit price</th>
                <th style={{ width: 140, textAlign: "right" }}>Amount</th>
                <th style={{ width: 38 }} />
              </tr></thead>
              <tbody>
                {items.map((li, i) => (
                  <tr key={i}>
                    <td><input disabled={!editable} value={li.description || ""} style={{ width: "100%" }} placeholder="Service or product"
                      onChange={(e) => setItem(i, "description", e.target.value)} /></td>
                    <td><input type="number" min="0" step="1" disabled={!editable} value={li.quantity ?? 1}
                      style={{ width: "100%", textAlign: "center" }}
                      onChange={(e) => setItem(i, "quantity", e.target.value)}
                      onBlur={(e) => { if (e.target.value === "") setItem(i, "quantity", 1); }} /></td>
                    <td><input type="number" min="0" step="0.01" disabled={!editable} value={li.rate ?? 0}
                      style={{ width: "100%", textAlign: "right" }}
                      onChange={(e) => setItem(i, "rate", e.target.value)} /></td>
                    <td style={{ textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{fmt(lineAmt(li))}</td>
                    <td style={{ textAlign: "center" }}>{editable && <Button size="sm" variant="ghost" icon={X} onClick={() =>
                      setInv({ ...inv, line_items: items.filter((_, j) => j !== i) })} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {editable && <Button size="sm" variant="secondary" icon={Plus} style={{ marginTop: 12 }}
              onClick={() => setInv({ ...inv, line_items: [...items, { description: "", quantity: 1, rate: 0 }] })}>Add line</Button>}
          </div>

          <div className="card" style={{ padding: 22 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              <div className="field"><label>Tax rate (%)</label>
                <input type="number" disabled={!editable} value={inv.tax_rate ?? 0} onChange={(e) => setInv({ ...inv, tax_rate: Number(e.target.value) })} /></div>
              <div className="field"><label>Discount ({cur})</label>
                <input type="number" disabled={!editable} value={inv.discount_amount ?? 0} onChange={(e) => setInv({ ...inv, discount_amount: Number(e.target.value) })} /></div>
            </div>
            <div className="field"><label>Payment instructions</label>
              <textarea rows={2} disabled={!editable} value={inv.payment_instructions || ""} onChange={(e) => setInv({ ...inv, payment_instructions: e.target.value })} /></div>
            <div className="field" style={{ marginBottom: 0 }}><label>Notes</label>
              <textarea rows={2} disabled={!editable} value={inv.notes || ""} onChange={(e) => setInv({ ...inv, notes: e.target.value })} /></div>
          </div>
        </div>

        <div className="doc-side">
          <div className="doc-preview">
            <div className="dp-head"><span>Totals</span><Badge>{cur}</Badge></div>
            <div className="doc-paper" style={{ maxHeight: "none", padding: "18px 22px" }}>
              <table><tbody>
                <tr><td>Subtotal</td><td>{fmt(inv.subtotal)}</td></tr>
                {inv.discount_amount ? <tr><td>Discount</td><td>-{fmt(inv.discount_amount)}</td></tr> : null}
                {inv.tax_amount ? <tr><td>Tax</td><td>{fmt(inv.tax_amount)}</td></tr> : null}
                <tr><td style={{ fontWeight: 700, fontSize: 15 }}>Total</td><td style={{ fontWeight: 700, fontSize: 15 }}>{fmt(inv.total)}</td></tr>
                {inv.amount_paid ? <tr><td>Paid</td><td>{fmt(inv.amount_paid)}</td></tr> : null}
                <tr><td style={{ color: "var(--muted)" }}>Balance due</td><td style={{ color: "var(--muted)" }}>{fmt(inv.balance_due)}</td></tr>
              </tbody></table>
            </div>
          </div>

          <RowCard title="Payment status" empty="">
            <div style={{ padding: "4px 10px 8px" }}>
              {inv.status === "void"
                ? <StatusPill tone="gray">void</StatusPill>
                : <StatusSteps steps={LIFE.map((s) => ({
                    ...s,
                    sub: s.key === "issued" && inv.status === "overdue" ? "overdue" : undefined,
                  }))} current={stepKey(inv.status)} />}
              {inv.status !== "draft" && <div style={{ fontSize: 11.5, color: "var(--muted2)" }}>Views: {inv.view_count || 0}</div>}
            </div>
          </RowCard>

          <RowCard title="Timeline" empty="No events yet.">
            {acts.map((t) => (
              <div key={t.id} style={{ fontSize: 12, padding: "5px 10px", borderTop: "1px solid #F2F3F5" }}>
                {t.title}<div style={{ color: "var(--muted2)", fontSize: 11 }}>{timeAgo(t.occurred_at)}</div>
              </div>
            ))}
          </RowCard>
        </div>
      </div>

      {payOpen && (
        <Modal title="Record payment" onClose={() => setPayOpen(false)}>
          <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
            Enter the total amount received so far ({cur}). This updates the status — no payment processor is connected.</p>
          <div className="field"><label>Amount paid ({cur})</label>
            <input type="number" value={pay} onChange={(e) => setPay(e.target.value)} autoFocus /></div>
          <div className="actions">
            <Button variant="ghost" onClick={() => setPayOpen(false)}>Cancel</Button>
            <Button onClick={() => { doAction("payment", { amount_paid: Number(pay) }, "pay", "Payment recorded"); setPayOpen(false); }}>Save</Button>
          </div>
        </Modal>
      )}
    </>
  );
}
