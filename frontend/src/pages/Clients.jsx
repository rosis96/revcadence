// CRM → Clients: closed-won / active clients (a profile exists). Delivery-focused
// summary — scope, onboarding %, start date, pricing, payment status — click into
// the full Client Profile.
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, Spinner, useApi } from "../components";

const onbTone = { approved: "green", submitted: "blue", in_review: "amber", sent: "indigo", not_started: "" };

export default function Clients() {
  const { wsParam } = useAuth();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi("/api/client-profiles", { workspace_id: wsParam });

  return (
    <>
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <h1 style={{ fontSize: 18 }}>Clients</h1>
        <span style={{ color: "var(--muted)", fontSize: 12.5 }}>Closed-won accounts — delivery, onboarding & payment</span>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && (
        <Empty icon="◎" title="No clients yet" hint="A client appears here when a deal moves to a Won stage (or you Activate a company's profile)." />
      )}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr>
            <th>Client</th><th>Scope</th><th>Onboarding</th><th>Start</th><th>Pricing</th><th>Payment</th><th>Docs</th>
          </tr></thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.company_id} className="click" onClick={() => nav(`/companies/${c.company_id}/profile`)}>
                <td><b>{c.company_name}</b></td>
                <td><Badge>{c.scope_type}</Badge></td>
                <td>
                  <Badge tone={onbTone[c.onboarding_status] || ""}>{c.onboarding_status}</Badge>
                  <span style={{ color: "var(--muted)", fontSize: 12, marginLeft: 6 }}>{c.completeness}%</span>
                  {c.review_flags > 0 && <Badge tone="amber" >{c.review_flags} to review</Badge>}
                </td>
                <td style={{ color: "var(--muted)", fontSize: 12.5 }}>{c.start_date || "—"}</td>
                <td style={{ fontSize: 12.5 }}>{c.pricing || "—"}</td>
                <td style={{ fontSize: 12.5 }}>{c.payment_status || "—"}</td>
                <td style={{ fontSize: 12 }} onClick={(e) => e.stopPropagation()}>
                  {c.blueprint_doc_id
                    ? <a className="link" onClick={() => nav(`/blueprints/${c.blueprint_doc_id}`)}>Blueprint</a>
                    : <span style={{ color: "var(--muted)" }}>—</span>}
                  {" · "}
                  {c.agreement_doc_id ? "Agreement" : <span style={{ color: "var(--muted)" }}>no agreement</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
