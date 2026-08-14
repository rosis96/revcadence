// Inbound — website form-fills (high intent → deal + 10-min task) and identified
// visitors (a signal). Shows the client's own capture key + a paste-ready form.
import { useState } from "react";
import { timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Empty, ErrorBox, PageHeader, Spinner, useApi, useToast } from "../components";

export default function InboundVisitors() {
  const { wsParam } = useAuth();
  const toast = useToast();
  const [showSnippet, setShowSnippet] = useState(false);
  const { data, error, loading, reload } = useApi("/api/inbound/visitors", { workspace_id: wsParam });
  const cfg = useApi(wsParam ? `/api/inbound/config?workspace_id=${wsParam}` : null);

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const copy = (text, label) => {
    navigator.clipboard?.writeText(text).then(() => toast(`${label} copied`)).catch(() => {});
  };
  const forms = data.events.filter((e) => e.kind === "inbound_lead");
  const visits = data.events.filter((e) => e.kind === "visitor");

  return (
    <>
      <PageHeader title="Inbound" desc="Every website lead captured — form-fills become deals with a 10-minute follow-up." />

      {/* Capture setup */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        {!wsParam ? (
          <div style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Select a specific workspace (top-left) to get its inbound capture key.</div>
        ) : cfg.data ? (
          <>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Website form capture</div>
            <div style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 10 }}>
              Point your website form at this URL. Each submission creates a contact, a deal in the
              pipeline, and a <b>“respond within 10 minutes”</b> task — so inbound is never dropped.</div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <code style={{ flex: 1, minWidth: 280, fontSize: 12, background: "var(--card-2)", padding: "8px 10px",
                borderRadius: 6, overflowX: "auto", whiteSpace: "nowrap" }}>{cfg.data.form_url}</code>
              <button className="btn ghost sm" onClick={() => copy(cfg.data.form_url, "URL")}>Copy URL</button>
              <button className="btn ghost sm" onClick={() => setShowSnippet((v) => !v)}>
                {showSnippet ? "Hide" : "Show"} form snippet</button>
            </div>
            {showSnippet && (
              <div style={{ marginTop: 10 }}>
                <pre style={{ fontSize: 11.5, background: "#0f1b2a", color: "#d6e4f0", padding: 12,
                  borderRadius: 8, overflowX: "auto" }}>{cfg.data.form_snippet}</pre>
                <button className="btn ghost sm" onClick={() => copy(cfg.data.form_snippet, "Snippet")}>Copy snippet</button>
              </div>
            )}
          </>
        ) : <div style={{ fontSize: 12.5, color: "var(--muted)" }}>Loading capture key…</div>}
      </div>

      <div className="grid stats" style={{ marginBottom: 18 }}>
        <div className="card stat"><div className="label">Form leads</div><div className="value">{forms.length}</div></div>
        <div className="card stat"><div className="label">Identified visitors</div><div className="value">{visits.length}</div></div>
        <div className="card stat"><div className="label">Enriched</div><div className="value" style={{ color: "var(--accent)" }}>{data.contacts.filter((c) => c.enriched).length}</div></div>
      </div>

      {data.events.length === 0 ? (
        <Empty icon="◍" title="No inbound yet"
          hint="Add the form URL above to your website, or point a visitor-ID provider at /api/inbound/visitor." />
      ) : (
        <table className="tbl">
          <thead><tr><th>Lead</th><th>Type</th><th>Page / message</th><th>When</th></tr></thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={e.id}>
                <td>
                  <b>{e.title}</b>
                  {e.deal_id ? <> · <a href={`#/deals/${e.deal_id}`}>deal</a></>
                    : e.company_id ? <> · <a href={`#/companies/${e.company_id}`}>company</a></> : null}
                </td>
                <td><Badge tone={e.kind === "inbound_lead" ? "green" : "blue"}>
                  {e.kind === "inbound_lead" ? "Form lead" : "Visitor"}</Badge></td>
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
