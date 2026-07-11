import { useState } from "react";
import { useAuth } from "../auth";
import { Badge, Drawer, Empty, ErrorBox, Spinner, Timeline, scoreTone, useApi } from "../components";

function ContactDrawer({ id, onClose }) {
  const { data: c, loading, error } = useApi(`/api/contacts/${id}`);
  const { data: tl } = useApi(`/api/contacts/${id}/timeline`);
  return (
    <Drawer title={loading ? "Loading…" : c?.name || c?.email || "Contact"} onClose={onClose}>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} />}
      {c && (
        <>
          <div className="kv">
            <div className="k">Email</div><div>{c.email || "—"}</div>
            <div className="k">Title</div><div>{c.title || "—"}</div>
            <div className="k">Company</div><div>{c.company_id ? <a href={`#/companies/${c.company_id}`}>view company</a> : "—"}</div>
            <div className="k">Email status</div><div>{c.email_status ? <Badge>{c.email_status}</Badge> : "—"}</div>
            <div className="k">Revenue score</div>
            <div>{c.revenue_score != null ? <Badge tone={scoreTone(c.revenue_score)}>{c.revenue_score}</Badge> : <Badge>not scored</Badge>}</div>
          </div>
          <h3 style={{ fontSize: 13, margin: "14px 0 8px" }}>Timeline</h3>
          <Timeline items={tl || []} />
        </>
      )}
    </Drawer>
  );
}

export default function Contacts() {
  const { wsParam } = useAuth();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(null);
  const { data, error, loading, reload } = useApi("/api/contacts", { workspace_id: wsParam, q });
  return (
    <>
      <div className="toolbar">
        <input type="text" placeholder="Search contacts…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="◔" title="No contacts" hint="Contacts arrive via import, enrichment, or the reply bridge." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Company</th><th>Title</th><th>Email</th><th>Source</th><th>Score</th></tr></thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.id} className="click" onClick={() => setOpen(c.id)}>
                <td><b>{c.name || "—"}</b></td>
                <td>{c.company_name || "—"}</td>
                <td>{c.title || "—"}</td>
                <td style={{ color: "var(--muted)" }}>{c.email}</td>
                <td><Badge>{c.source || "—"}</Badge></td>
                <td>{c.revenue_score != null ? <Badge tone={scoreTone(c.revenue_score)}>{c.revenue_score}</Badge> : <Badge>—</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && <ContactDrawer id={open} onClose={() => setOpen(null)} />}
    </>
  );
}
