// Invoices (DESIGN_SYSTEM.md step 8): every invoice on the shared DataTable,
// plus a standalone "New invoice" form (client, amount, dates) so an invoice can
// be created without an executed agreement.
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Receipt, Trash2 } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Button, ConfirmDialog, DataTable, ErrorBox, Modal, PageHeader, StatusPill, useApi, useToast } from "../components";
import { Select } from "../components";

const TONE = { draft: "gray", issued: "blue", viewed: "amber", partially_paid: "amber", paid: "green", overdue: "red", void: "gray" };
const fmt = (cur, n) => `${cur || "USD"} ${(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;
const todayISO = () => new Date().toISOString().slice(0, 10);
const fmtDate = (iso) => { try { return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }); } catch { return iso; } };
const NEW = () => ({ billed: "", desc: "Outbound Lead Generation Service", qty: 1, price: "", currency: "USD", issue: todayISO(), terms: "30", customDays: 30 });

export default function Invoices() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const [confirmRows, setConfirmRows] = useState(null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(NEW());
  const [busy, setBusy] = useState(false);
  const { data, error, loading, reload } = useApi("/api/invoices", { workspace_id: wsParam });
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  const days = f.terms === "custom" ? Number(f.customDays) || 0 : Number(f.terms);
  const duePreview = (() => { const d = new Date((f.issue || todayISO()) + "T00:00:00"); d.setDate(d.getDate() + (isNaN(days) ? 0 : days)); return d.toISOString().slice(0, 10); })();
  const total = (Number(f.qty) || 0) * (parseFloat(f.price) || 0);

  const createInvoice = async () => {
    if (!wsParam) return toast("Select a workspace first.", "bad");
    if (!f.billed.trim()) return toast("Enter who the invoice is billed to.", "bad");
    if (!(parseFloat(f.price) > 0)) return toast("Enter an amount.", "bad");
    setBusy(true);
    try {
      const r = await api("/api/invoices", {
        method: "POST",
        body: {
          workspace_id: wsParam,
          line_items: [{ description: f.desc || "Service", quantity: Number(f.qty) || 1, rate: parseFloat(f.price) || 0 }],
          overrides: { bill_to_company: f.billed.trim(), currency: f.currency, issue_date: f.issue, terms_days: days },
        },
      });
      toast(`Created ${r.number}`);
      setOpen(false); setF(NEW());
      nav(`/invoices/${r.id}`);
    } catch (e) { toast(e.message, "bad"); }
    finally { setBusy(false); }
  };

  const deleteInvoices = async (rows) => {
    for (const r of rows) {
      try { await api(`/api/invoices/${r.id}`, { method: "DELETE" }); }
      catch (e) { toast(`${r.number}: ${e.message}`, "bad"); }
    }
    toast(`Deleted ${rows.length} invoice(s)`);
    reload();
  };

  const columns = useMemo(() => [
    { accessorKey: "number", header: "Invoice", size: 150,
      cell: ({ getValue }) => <span className="lead-nm">{getValue()}</span> },
    { accessorKey: "bill_to_company", header: "Billed to", size: 220,
      cell: ({ row }) => (
        <div><div className="lead-nm">{row.original.bill_to_company || "—"}</div>
          <div className="lead-sub">{row.original.bill_to_email || ""}</div></div>) },
    { accessorKey: "status", header: "Status", size: 140,
      cell: ({ getValue }) => <StatusPill tone={TONE[getValue()] || "gray"}>{String(getValue()).replaceAll("_", " ")}</StatusPill> },
    { accessorKey: "total", header: "Total", size: 130,
      cell: ({ row }) => fmt(row.original.currency, row.original.total) },
    { accessorKey: "balance_due", header: "Balance due", size: 130,
      cell: ({ row }) => fmt(row.original.currency, row.original.balance_due) },
    { accessorKey: "issue_date", header: "Issued", size: 110, cell: ({ getValue }) => getValue() || "—" },
    { accessorKey: "due_date", header: "Due", size: 110, cell: ({ getValue }) => getValue() || "—" },
  ], []);

  if (error) return <ErrorBox msg={error} retry={reload} />;

  const fld = { display: "flex", flexDirection: "column", gap: 5 };
  const inp = { padding: "9px 10px", border: "1px solid var(--line-2, #d5d9e2)", borderRadius: 8, font: "inherit", fontSize: 14, width: "100%" };
  const lab = { fontSize: 12.5, fontWeight: 700, color: "var(--muted, #697586)" };

  return (
    <>
      <PageHeader title="Invoices" desc="Billing across every client: status, totals and balances."
        actions={<Button icon={Plus} onClick={() => { setF(NEW()); setOpen(true); }}>New invoice</Button>} />
      <DataTable
        id="invoices" columns={columns} data={data || []} loading={loading}
        searchPlaceholder="Search invoices…" getRowId={(r) => String(r.id)}
        onRowClick={(r) => nav(`/invoices/${r.id}`)}
        bulkActions={[{ label: "Delete", icon: Trash2, onClick: (rows) => setConfirmRows(rows) }]}
        emptyIcon={Receipt} emptyTitle="No invoices yet"
        emptyHint="Click New invoice to create one."
      />

      {open && (
        <Modal title="New invoice" onClose={() => setOpen(false)}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 460, maxWidth: 520 }}>
            <div style={fld}>
              <label style={lab}>Billed to (client)</label>
              <input style={inp} value={f.billed} placeholder="Client or company name" onChange={(e) => set("billed", e.target.value)} />
            </div>
            <div style={fld}>
              <label style={lab}>Description</label>
              <input style={inp} value={f.desc} onChange={(e) => set("desc", e.target.value)} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr 1fr", gap: 12 }}>
              <div style={fld}><label style={lab}>Quantity</label>
                <input style={inp} type="number" min="1" value={f.qty} onChange={(e) => set("qty", e.target.value)} /></div>
              <div style={fld}><label style={lab}>Unit price</label>
                <input style={inp} type="number" min="0" step="0.01" placeholder="0.00" value={f.price} onChange={(e) => set("price", e.target.value)} /></div>
              <div style={fld}><label style={lab}>Currency</label>
                <Select style={{ width: "100%" }} value={f.currency} onChange={(e) => set("currency", e.target.value)}>
                  <option>USD</option><option>GBP</option><option>EUR</option>
                </Select></div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div style={fld}><label style={lab}>Issue date</label>
                <input style={inp} type="date" value={f.issue} onChange={(e) => set("issue", e.target.value)} /></div>
              <div style={fld}><label style={lab}>Terms</label>
                <Select style={{ width: "100%" }} value={f.terms} onChange={(e) => set("terms", e.target.value)}>
                  <option value="0">Due on receipt</option>
                  <option value="7">Net 7</option>
                  <option value="14">Net 14</option>
                  <option value="15">Net 15</option>
                  <option value="30">Net 30</option>
                  <option value="custom">Custom days</option>
                </Select></div>
            </div>
            {f.terms === "custom" && (
              <div style={fld}><label style={lab}>Days until due</label>
                <input style={{ ...inp, maxWidth: 140 }} type="number" min="0" value={f.customDays} onChange={(e) => set("customDays", e.target.value)} /></div>
            )}
            <div className="card" style={{ background: "var(--soft, #f6f7f9)", borderRadius: 8, padding: "12px 14px", fontSize: 13.5, color: "var(--ink-2, #3b4557)" }}>
              <b>{f.currency} {total.toLocaleString("en-US", { minimumFractionDigits: 2 })}</b> due by <b>{fmtDate(duePreview)}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
              <Button icon={Plus} disabled={busy} onClick={createInvoice}>{busy ? "Creating…" : "Create invoice"}</Button>
            </div>
          </div>
        </Modal>
      )}

      {confirmRows && (
        <ConfirmDialog title="Delete invoices"
          message={`Permanently delete ${confirmRows.length} invoice(s)? This can't be undone.`}
          confirmLabel="Delete" danger
          onConfirm={() => deleteInvoices(confirmRows)} onClose={() => setConfirmRows(null)} />
      )}
    </>
  );
}
