import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";

const statusTone = { draft: "amber", published: "green", executed: "green" };

export default function Blueprints() {
  const { wsParam, me } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/documents", { workspace_id: wsParam });
  const wsName = (id) => me.workspaces.find((w) => w.id === id)?.name || `#${id}`;
  return (
    <>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && (
        <Empty icon="▤" title="No blueprints yet" hint="Generate one from a company page or the Enrichment screen." />
      )}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Title</th><th>Kind</th><th>Workspace</th><th>Status</th><th>Views</th></tr></thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.id} className="click" onClick={() => nav(`/blueprints/${d.id}`)}>
                <td><b>{d.title || d.slug}</b></td>
                <td><Badge>{d.kind}</Badge></td>
                <td>{wsName(d.workspace_id)}</td>
                <td><Badge tone={statusTone[d.status] || ""}>{d.status}</Badge></td>
                <td>{d.view_count || 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
