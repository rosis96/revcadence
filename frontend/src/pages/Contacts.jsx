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

function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function downloadCsv(rows) {
  const head = ["first_name", "last_name", "email", "company", "title", "intent", "status", "source"];
  const lines = [head.join(",")].concat(rows.map((c) => {
    const [fn, ...rest] = (c.name || "").split(" ");
    return [c.first_name || fn || "", c.last_name || rest.join(" ") || "", c.email || "",
            c.company_name || "", c.title || "", c.intent || "", c.status?.label || "", c.source || ""]
      .map(csvCell).join(",");
  }));
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `contacts-export-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
}

export default function Contacts() {
  const { wsParam } = useAuth();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(null);
  const [sel, setSel] = useState({});
  const [intent, setIntent] = useState("");
  const { data, error, loading, reload } = useApi("/api/contacts", { workspace_id: wsParam, q });

  const intents = [...new Set((data || []).map((c) => c.intent).filter(Boolean))].sort();
  const shown = (data || []).filter((c) => !intent || c.intent === intent);
  const selIds = Object.keys(sel).filter((k) => sel[k]);
  const allShownSelected = shown.length > 0 && shown.every((c) => sel[c.id]);
  const toggleAll = () => {
    const next = { ...sel };
    if (allShownSelected) shown.forEach((c) => delete next[c.id]);
    else shown.forEach((c) => { next[c.id] = true; });
    setSel(next);
  };
  const exportSel = () => {
    const rows = (data || []).filter((c) => sel[c.id]);
    if (!rows.length) { alert("Select some contacts first (or use Select all)."); return; }
    downloadCsv(rows);
  };

  return (
    <>
      <div className="toolbar">
        <input type="text" placeholder="Search contacts…" value={q} onChange={(e) => setQ(e.target.value)} />
        {intents.length > 0 && (
          <select value={intent} onChange={(e) => setIntent(e.target.value)} style={{ maxWidth: 220 }}>
            <option value="">All intents</option>
            {intents.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        )}
        <div className="spacer" />
        <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{selIds.length} selected</span>
        <button className="btn" disabled={!selIds.length} onClick={exportSel}>⭳ Export selected (CSV)</button>
      </div>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="◔" title="No contacts" hint="Contacts arrive via import, enrichment, or the reply bridge." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr>
            <th style={{ width: 30 }}><input type="checkbox" checked={allShownSelected} onChange={toggleAll} /></th>
            <th>Name</th><th>Company</th><th>Intent</th><th>Email</th><th>Source</th><th>Score</th>
          </tr></thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id} className="click" onClick={() => setOpen(c.id)}>
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={!!sel[c.id]} onChange={(e) => setSel({ ...sel, [c.id]: e.target.checked })} /></td>
                <td><b>{c.name || "—"}</b></td>
                <td>{c.company_name || "—"}</td>
                <td>{c.intent ? <Badge tone="indigo">{c.intent}</Badge> : "—"}</td>
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
