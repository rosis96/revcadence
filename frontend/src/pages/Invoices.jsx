// Invoices (DESIGN_SYSTEM.md step 8): every invoice on the shared DataTable.
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Receipt, Trash2 } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ConfirmDialog, DataTable, ErrorBox, PageHeader, StatusPill, useApi, useToast } from "../components";

const TONE = { draft: "gray", issued: "blue", viewed: "amber", partially_paid: "amber", paid: "green", overdue: "red", void: "gray" };
const fmt = (cur, n) => `${cur || "USD"} ${(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

export default function Invoices() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const [confirmRows, setConfirmRows] = useState(null);
  const { data, error, loading, reload } = useApi("/api/invoices", { workspace_id: wsParam });

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

  return (
    <>
      <PageHeader title="Invoices" desc="Billing across every client: status, totals and balances." />
      <DataTable
        id="invoices" columns={columns} data={data || []} loading={loading}
        searchPlaceholder="Search invoices…" getRowId={(r) => String(r.id)}
        onRowClick={(r) => nav(`/invoices/${r.id}`)}
        bulkActions={[{ label: "Delete", icon: Trash2, onClick: (rows) => setConfirmRows(rows) }]}
        emptyIcon={Receipt} emptyTitle="No invoices yet"
        emptyHint="Create one from an executed agreement."
      />
      {confirmRows && (
        <ConfirmDialog title="Delete invoices"
          message={`Permanently delete ${confirmRows.length} invoice(s)? This can't be undone.`}
          confirmLabel="Delete" danger
          onConfirm={() => deleteInvoices(confirmRows)} onClose={() => setConfirmRows(null)} />
      )}
    </>
  );
}
