// CRM → Clients: closed-won accounts (a Client Profile exists), on the shared DataTable.
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Briefcase } from "lucide-react";
import { useAuth } from "../auth";
import { Avatar, Badge, DataTable, ErrorBox, PageHeader, StatusPill, useApi } from "../components";

const ONB_TONE = { approved: "green", submitted: "blue", in_review: "amber", sent: "blue", not_started: "gray" };

export default function Clients() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/client-profiles", { workspace_id: wsParam });

  const columns = useMemo(() => [
    { accessorKey: "company_name", header: "Client", size: 220,
      cell: ({ getValue }) => (
        <div className="co"><Avatar name={getValue()} size={26} /><div className="lead-nm">{getValue()}</div></div>) },
    { accessorKey: "scope_type", header: "Scope", size: 110,
      cell: ({ getValue }) => <Badge>{getValue()}</Badge> },
    { id: "onboarding", header: "Onboarding", size: 210, accessorFn: (r) => r.onboarding_status,
      cell: ({ row }) => (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <StatusPill tone={ONB_TONE[row.original.onboarding_status] || "gray"}>
            {String(row.original.onboarding_status || "").replaceAll("_", " ")}
          </StatusPill>
          <span style={{ color: "var(--muted)", fontSize: 12 }}>{row.original.completeness}%</span>
          {row.original.review_flags > 0 && <Badge tone="amber">{row.original.review_flags} to review</Badge>}
        </span>) },
    { accessorKey: "start_date", header: "Start", size: 110, cell: ({ getValue }) => getValue() || "—" },
    { accessorKey: "pricing", header: "Pricing", size: 140, cell: ({ getValue }) => getValue() || "—" },
    { accessorKey: "payment_status", header: "Payment", size: 120, cell: ({ getValue }) => getValue() || "—" },
    { id: "docs", header: "Docs", size: 170, enableSorting: false,
      cell: ({ row }) => (
        <span style={{ fontSize: 12 }} onClick={(e) => e.stopPropagation()}>
          {row.original.blueprint_doc_id
            ? <a href={`#/blueprints/${row.original.blueprint_doc_id}`}>Blueprint</a>
            : <span style={{ color: "var(--muted)" }}>—</span>}
          {" · "}
          {row.original.agreement_doc_id ? "Agreement" : <span style={{ color: "var(--muted)" }}>no agreement</span>}
        </span>) },
  ], []);

  if (error) return <ErrorBox msg={error} retry={reload} />;

  return (
    <>
      <PageHeader title="Clients" desc="Closed-won accounts: delivery, onboarding and payment at a glance." />
      <DataTable
        id="clients" columns={columns} data={data || []} loading={loading}
        searchPlaceholder="Search clients…" getRowId={(r) => String(r.company_id)}
        onRowClick={(r) => nav(`/companies/${r.company_id}/profile`)}
        emptyIcon={Briefcase} emptyTitle="No clients yet"
        emptyHint="A client appears here when a deal moves to a Won stage (or you activate a company's profile)."
      />
    </>
  );
}
