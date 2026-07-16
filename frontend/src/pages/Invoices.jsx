// Invoices (DESIGN_SYSTEM.md step 8): every invoice on the shared DataTable.
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Receipt } from "lucide-react";
import { useAuth } from "../auth";
import { DataTable, ErrorBox, PageHeader, StatusPill, useApi } from "../components";

const TONE = { draft: "gray", issued: "blue", viewed: "amber", partially_paid: "amber", paid: "green", overdue: "red", void: "gray" };
const fmt = (cur, n) => `${cur || "USD"} ${(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}`;

export default function Invoices() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/invoices", { workspace_id: wsParam });

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
        emptyIcon={Receipt} emptyTitle="No invoices yet"
        emptyHint="Create one from an executed agreement."
      />
    </>
  );
}
