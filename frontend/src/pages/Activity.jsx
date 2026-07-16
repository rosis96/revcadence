// CRM → Activity: the workspace-wide timeline on the shared DataTable.
import { useMemo, useState } from "react";
import { Activity as ActivityIcon, RefreshCw } from "lucide-react";
import { timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Button, DataTable, ErrorBox, PageHeader, useApi } from "../components";

const KINDS = ["", "email_in", "email_out", "reply_drafted", "stage_change", "enriched", "deal_created", "doc_created", "import"];

export default function ActivityPage() {
  const { wsParam } = useAuth();
  const [kind, setKind] = useState("");
  const { data, error, loading, reload } = useApi("/api/activities", { workspace_id: wsParam, kind, limit: 200 });

  const columns = useMemo(() => [
    { accessorKey: "title", header: "Event", size: 420,
      cell: ({ row }) => (
        <div>
          <div className="lead-nm">{row.original.title || "—"}</div>
          {row.original.body && <div className="lead-sub">{row.original.body.slice(0, 140)}</div>}
          {row.original.company_id && (
            <a href={`#/companies/${row.original.company_id}`} style={{ fontSize: 12 }}
               onClick={(e) => e.stopPropagation()}>company →</a>
          )}
        </div>) },
    { accessorKey: "kind", header: "Type", size: 150,
      cell: ({ getValue }) => <Badge>{getValue()}</Badge> },
    { accessorKey: "at", header: "When", size: 120, cell: ({ getValue }) => timeAgo(getValue()) },
  ], []);

  if (error) return <ErrorBox msg={error} retry={reload} />;

  return (
    <>
      <PageHeader title="Activity" desc="Everything that happened, across every section of the workspace."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={reload}>Refresh</Button>} />
      <DataTable
        id="activity" columns={columns} data={data || []} loading={loading}
        searchPlaceholder="Search events…" getRowId={(r) => String(r.id)}
        tools={
          <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ height: 40 }}>
            {KINDS.map((k) => <option key={k} value={k}>{k || "All activity types"}</option>)}
          </select>
        }
        emptyIcon={ActivityIcon} emptyTitle="No activity"
        emptyHint="Events across the workspace appear here."
      />
    </>
  );
}
