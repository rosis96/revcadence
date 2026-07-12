// Inbound (Visitors) — website-visitor capture ONLY. Its own section.
import { timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";

export default function InboundVisitors() {
  const { wsParam } = useAuth();
  const { data, error, loading, reload } = useApi("/api/inbound/visitors", { workspace_id: wsParam });
  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  return (
    <>
      <div className="card" style={{ padding: 14, marginBottom: 16 }}>
        <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
          Point your visitor-identification provider (RB2B or similar) at this webhook. Each visitor
          becomes a company + contact, is auto-enriched, and appears below — the enrich job runs
          immediately so you can act within minutes.</div>
        <code style={{ display: "block", marginTop: 8, fontSize: 12, background: "#f4f5f7", padding: "8px 10px", borderRadius: 6 }}>
          POST {window.location.origin}{data.webhook_hint}</code>
      </div>

      <div className="grid stats" style={{ marginBottom: 18 }}>
        <div className="card stat"><div className="label">Visitors captured</div><div className="value">{data.events.length}</div></div>
        <div className="card stat"><div className="label">Enriched</div><div className="value" style={{ color: "var(--accent)" }}>{data.contacts.filter((c) => c.enriched).length}</div></div>
      </div>

      {data.events.length === 0 ? (
        <Empty icon="◍" title="No visitors yet" hint="Once your provider posts to the webhook above, identified visitors show here." />
      ) : (
        <table className="tbl">
          <thead><tr><th>Visitor</th><th>Page</th><th>When</th></tr></thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={e.id}>
                <td><b>{e.title}</b>{e.company_id && <> · <a href={`#/companies/${e.company_id}`}>company</a></>}</td>
                <td style={{ color: "var(--muted)", fontSize: 12.5 }}>{e.page || "—"}</td>
                <td>{timeAgo(e.at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
