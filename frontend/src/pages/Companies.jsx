// CRM → Companies. Shared DataTable + global shell (DESIGN_SYSTEM.md step 3).
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Avatar, Badge, Button, ConfirmDialog, DataTable, ErrorBox, Modal, PageHeader, fitTone, useApi, useToast,
} from "../components";

export function NewCompanyModal({ onClose, onCreated, workspaceId, workspaces }) {
  const [form, setForm] = useState({ name: "", website: "", workspace_id: workspaceId || (workspaces[0]?.id ?? "") });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const r = await api("/api/companies", { method: "POST", body: { ...form, workspace_id: Number(form.workspace_id) } });
      onCreated(r.id);
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  return (
    <Modal title="New company" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="error-box" style={{ marginBottom: 10 }}>{error}</div>}
        {!workspaceId && (
          <div className="field"><label>Workspace</label>
            <select value={form.workspace_id} onChange={(e) => setForm({ ...form, workspace_id: e.target.value })}>
              {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </div>
        )}
        <div className="field"><label>Name</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus /></div>
        <div className="field"><label>Website</label>
          <input value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} placeholder="acme.com" /></div>
        <div className="actions">
          <Button variant="ghost" type="button" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={busy}>Create</Button>
        </div>
      </form>
    </Modal>
  );
}

// pipeline-status chip order (matches stage progression)
export const STATUS_ORDER = ["interested", "meeting_booked", "meeting_completed", "no_show",
                             "follow_up", "won", "client", "none"];
// Companies/Contacts default to real conversations: meeting booked & beyond.
export const BOOKED_PLUS = new Set(["meeting_booked", "meeting_completed", "no_show", "follow_up", "won", "client"]);

// Dynamic-color pipeline pill (color comes from the stage record, so it can't
// be a fixed StatusPill tone).
export function PipelinePill({ status }) {
  if (!status) return null;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600,
                   padding: "2px 10px", borderRadius: 999, color: status.color,
                   background: status.color + "1f", border: `1px solid ${status.color}44` }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", background: status.color }} />{status.label}
    </span>
  );
}
export const StatusPill = PipelinePill; // legacy import name (Contacts, CompanyDetail)

export function StatusChips({ data, filter, setFilter }) {
  const counts = {};
  (data || []).forEach((c) => { const k = c.status?.key || "none"; counts[k] = (counts[k] || 0) + 1; });
  const booked = (data || []).filter((c) => BOOKED_PLUS.has(c.status?.key)).length;
  const chips = STATUS_ORDER.filter((k) => counts[k]);
  const colorFor = (k) => (data || []).find((c) => c.status?.key === k)?.status?.color || "#64748b";
  const labelFor = (k) => (data || []).find((c) => c.status?.key === k)?.status?.label || k;
  if (!data?.length) return null;
  const Chip = ({ on, color, onClick, children }) => (
    <button onClick={onClick}
      style={{ cursor: "pointer", fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 999,
               border: `1px solid ${color}55`, background: on ? color : color + "1f", color: on ? "#fff" : color }}>
      {children}
    </button>
  );
  return (
    <div className="chips" style={{ marginBottom: 14 }}>
      <Chip on={filter === "__booked"} color="#3b82f6" onClick={() => setFilter("__booked")}>Meetings · {booked}</Chip>
      <Chip on={filter === ""} color="#111827" onClick={() => setFilter("")}>All · {data.length}</Chip>
      {chips.map((k) => (
        <Chip key={k} on={filter === k} color={colorFor(k)} onClick={() => setFilter(filter === k ? "__booked" : k)}>
          {labelFor(k)} · {counts[k]}
        </Chip>
      ))}
    </div>
  );
}

export const filterByStatus = (data, filter) => (data || []).filter((c) => {
  const k = c.status?.key || "none";
  if (filter === "__booked") return BOOKED_PLUS.has(k);
  if (filter === "") return true;
  return k === filter;
});

export default function Companies() {
  const { wsParam, me } = useAuth();
  const [modal, setModal] = useState(false);
  const [filter, setFilter] = useState("__booked");
  const [confirmRows, setConfirmRows] = useState(null);
  const nav = useNavigate();
  const toast = useToast();
  const { data, error, loading, reload } = useApi("/api/companies", { workspace_id: wsParam });

  const shown = useMemo(() => filterByStatus(data, filter), [data, filter]);

  const columns = useMemo(() => [
    { accessorKey: "name", header: "Company", size: 260,
      cell: ({ row }) => (
        <div className="co"><Avatar name={row.original.name} size={26} />
          <div><div className="lead-nm">{row.original.name}</div>
            <div className="lead-sub">{row.original.domain || row.original.website || ""}</div></div>
        </div>) },
    { id: "status", header: "Status", size: 160, accessorFn: (r) => r.status?.label || "",
      cell: ({ row }) => <PipelinePill status={row.original.status} /> },
    { accessorKey: "industry", header: "Industry", size: 180, cell: ({ getValue }) => getValue() || "—" },
    { accessorKey: "location", header: "Location", size: 160, cell: ({ getValue }) => getValue() || "—" },
    { accessorKey: "icp_fit", header: "ICP fit", size: 120,
      cell: ({ getValue }) => (getValue()
        ? <Badge tone={fitTone(getValue())}>{getValue()}</Badge> : <Badge>not enriched</Badge>) },
  ], []);

  const bulkDelete = async (rows) => {
    for (const c of rows) {
      try { await api(`/api/companies/${c.id}`, { method: "DELETE" }); }
      catch (err) { toast(`${c.name}: ${err.message}`, "bad"); }
    }
    toast(`Deleted ${rows.length} company(ies)`);
    reload();
  };

  if (error) return <ErrorBox msg={error} retry={reload} />;

  return (
    <>
      <PageHeader title="Companies" desc="Every account, with its live pipeline status."
        actions={<Button icon={Plus} onClick={() => setModal(true)}>New company</Button>} />
      <StatusChips data={data} filter={filter} setFilter={setFilter} />
      <DataTable
        id="companies" columns={columns} data={shown} loading={loading}
        searchPlaceholder="Search companies…" getRowId={(r) => String(r.id)}
        onRowClick={(r) => nav(`/companies/${r.id}`)}
        bulkActions={[{ label: "Delete", icon: Trash2, onClick: (rows) => setConfirmRows(rows) }]}
        emptyIcon={Building2} emptyTitle="No companies"
        emptyHint="Create one or import via enrichment."
        emptyAction={<Button icon={Plus} onClick={() => setModal(true)}>New company</Button>}
      />
      {modal && (
        <NewCompanyModal workspaceId={wsParam} workspaces={me.workspaces} onClose={() => setModal(false)}
          onCreated={(id) => { setModal(false); nav(`/companies/${id}`); }} />
      )}
      {confirmRows && (
        <ConfirmDialog title="Delete companies"
          message={`Delete ${confirmRows.length} company(ies) with all their contacts, deals, documents and profiles? This can't be undone.`}
          confirmLabel="Delete" danger
          onConfirm={() => bulkDelete(confirmRows)} onClose={() => setConfirmRows(null)} />
      )}
    </>
  );
}
