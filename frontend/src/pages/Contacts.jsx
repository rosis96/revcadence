// CRM → Contacts. Shared DataTable + global shell (DESIGN_SYSTEM.md step 3).
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Contact as ContactIcon, Plus } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Avatar, Badge, Button, DataTable, Drawer, ErrorBox, Modal, PageHeader, Spinner,
  Timeline, scoreTone, useApi,
} from "../components";
import { PipelinePill, StatusChips, filterByStatus } from "./Companies";

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
            New contacts have no deal yet. Create a deal on Pipeline to book a meeting.</div>
        </div>
        <div className="actions">
          <Button variant="ghost" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={busy}>Create contact</Button>
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
  const nav = useNavigate();
  const [open, setOpen] = useState(null);
  const [modal, setModal] = useState(false);
  const [filter, setFilter] = useState("__booked");
  const { data, error, loading, reload } = useApi("/api/contacts", { workspace_id: wsParam });
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);

  const shown = useMemo(() => filterByStatus(data, filter), [data, filter]);

  const columns = useMemo(() => {
    // Enterprise feel: drop any column that's empty for EVERY visible row, so the
    // table never reads as a wall of dashes. Name + Status always show.
    const has = (key) => shown.some((r) => r[key] != null && r[key] !== "");
    const cols = [
      { accessorKey: "name", header: "Name", size: 230,
        cell: ({ row }) => (
          <div className="co"><Avatar name={row.original.name || row.original.email} size={26} />
            <div><div className="lead-nm">{row.original.name || "—"}</div>
              <div className="lead-sub">{row.original.email}</div></div>
          </div>) },
      { id: "status", header: "Status", size: 160, accessorFn: (r) => r.status?.label || "",
        cell: ({ row }) => <PipelinePill status={row.original.status} /> },
    ];
    if (has("company_name"))
      cols.push({ accessorKey: "company_name", header: "Company", size: 190, cell: ({ getValue }) => getValue() || "—" });
    if (has("title"))
      cols.push({ accessorKey: "title", header: "Title", size: 190, cell: ({ getValue }) => getValue() || "—" });
    if (has("source"))
      cols.push({ accessorKey: "source", header: "Source", size: 130, cell: ({ getValue }) => <Badge>{getValue() || "—"}</Badge> });
    if (has("revenue_score"))
      cols.push({ accessorKey: "revenue_score", header: "Score", size: 90,
        cell: ({ getValue }) => (getValue() != null
          ? <Badge tone={scoreTone(getValue())}>{getValue()}</Badge> : <Badge>—</Badge>) });
    return cols;
  }, [shown]);

  if (error) return <ErrorBox msg={error} retry={reload} />;

  return (
    <>
      <PageHeader title="Contacts" desc="Every person, connected to their company, deals and timeline."
        actions={<Button icon={Plus} onClick={() => setModal(true)}>New contact</Button>} />
      <StatusChips data={data} filter={filter} setFilter={setFilter} />
      <DataTable
        id="contacts" columns={columns} data={shown} loading={loading}
        searchPlaceholder="Search contacts…" getRowId={(r) => String(r.id)}
        onRowClick={(r) => nav(`/contacts/${r.id}`)}
        emptyIcon={ContactIcon} emptyTitle="No contacts"
        emptyHint="Contacts arrive via import, enrichment, or the reply bridge."
      />
      {open && <ContactDrawer id={open} onClose={() => setOpen(null)} />}
      {modal && (
        <NewContactModal workspaceId={wsId} onClose={() => setModal(false)}
          onCreated={() => { setModal(false); setFilter("none"); reload(); }} />
      )}
    </>
  );
}
