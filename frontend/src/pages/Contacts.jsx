import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, Drawer, Empty, ErrorBox, Modal, Spinner, Timeline, scoreTone, useApi } from "../components";
import { StatusPill, STATUS_ORDER, BOOKED_PLUS } from "./Companies";

function NewContactModal({ onClose, onCreated, workspaceId }) {
  const { data: companies } = useApi("/api/companies", { workspace_id: workspaceId });
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", title: "", company_id: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    if (!workspaceId) { setError("Pick a specific workspace first (top-left)."); return; }
    setBusy(true); setError("");
    try {
      const r = await api("/api/contacts", { method: "POST",
        body: { workspace_id: Number(workspaceId), first_name: form.first_name, last_name: form.last_name,
                email: form.email, title: form.title,
                company_id: form.company_id ? Number(form.company_id) : null } });
      onCreated(r.id);
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  return (
    <Modal title="New contact" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="error-box" style={{ marginBottom: 10 }}>{error}</div>}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>First name</label>
            <input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} autoFocus /></div>
          <div className="field"><label>Last name</label>
            <input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div>
        </div>
        <div className="field"><label>Email</label>
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="name@company.com" /></div>
        <div className="field"><label>Title</label>
          <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Founder, Head of Growth…" /></div>
        <div className="field"><label>Company</label>
          <select value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })}>
            <option value="">— none —</option>
            {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 4 }}>
            New contacts have no deal yet — they appear under the “No deal” chip. Create a deal on Pipeline to book a meeting.</div>
        </div>
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create contact"}</button>
        </div>
      </form>
    </Modal>
  );
}

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
  const { wsParam, me } = useAuth();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(null);
  const [modal, setModal] = useState(false);
  const [filter, setFilter] = useState("__booked");   // default: meetings booked & beyond
  const { data, error, loading, reload } = useApi("/api/contacts", { workspace_id: wsParam, q });
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);

  const counts = {};
  (data || []).forEach((c) => { const k = c.status?.key || "none"; counts[k] = (counts[k] || 0) + 1; });
  const bookedCount = (data || []).filter((c) => BOOKED_PLUS.has(c.status?.key)).length;
  const chips = STATUS_ORDER.filter((k) => counts[k]);
  const colorFor = (k) => (data || []).find((c) => c.status?.key === k)?.status?.color || "#64748b";
  const labelFor = (k) => (data || []).find((c) => c.status?.key === k)?.status?.label || k;
  const shown = (data || []).filter((c) => {
    const k = c.status?.key || "none";
    if (filter === "__booked") return BOOKED_PLUS.has(k);
    if (filter === "") return true;
    return k === filter;
  });
  const Chip = ({ on, color, onClick, children }) => (
    <button onClick={onClick} style={{ cursor: "pointer", fontSize: 12, fontWeight: 600, padding: "4px 12px",
            borderRadius: 999, border: `1px solid ${color}55`, background: on ? color : color + "1f", color: on ? "#fff" : color }}>{children}</button>
  );

  return (
    <>
      <div className="toolbar">
        <input type="text" placeholder="Search contacts…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="spacer" />
        <button className="btn" onClick={() => setModal(true)}>+ New contact</button>
      </div>
      {data && data.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "4px 0 12px", alignItems: "center" }}>
          <Chip on={filter === "__booked"} color="#3b82f6" onClick={() => setFilter("__booked")}>Meetings · {bookedCount}</Chip>
          <Chip on={filter === ""} color="#111827" onClick={() => setFilter("")}>All · {data.length}</Chip>
          <span style={{ width: 1, height: 18, background: "var(--line,#e5e7eb)", margin: "0 2px" }} />
          {chips.map((k) => (
            <Chip key={k} on={filter === k} color={colorFor(k)} onClick={() => setFilter(filter === k ? "__booked" : k)}>
              {labelFor(k)} · {counts[k]}
            </Chip>
          ))}
        </div>
      )}
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} retry={reload} />}
      {data && data.length === 0 && <Empty icon="◔" title="No contacts" hint="Contacts arrive via import, enrichment, or the reply bridge." />}
      {data && data.length > 0 && (
        <table className="tbl">
          <thead><tr><th>Name</th><th>Status</th><th>Company</th><th>Title</th><th>Email</th><th>Source</th><th>Score</th></tr></thead>
          <tbody>
            {shown.map((c) => (
              <tr key={c.id} className="click" onClick={() => setOpen(c.id)}>
                <td><b>{c.name || "—"}</b></td>
                <td><StatusPill status={c.status} /></td>
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
      {modal && (
        <NewContactModal workspaceId={wsId} onClose={() => setModal(false)}
                         onCreated={() => { setModal(false); setFilter("none"); reload(); }} />
      )}
    </>
  );
}
