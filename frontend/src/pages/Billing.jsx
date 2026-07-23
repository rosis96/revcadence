// Billing (master only) — track each client's subscription and see MRR.
// Manual today (edit plan/price/status); Stripe-ready underneath.
import { useState } from "react";
import { api, money } from "../api";
import { Badge, ErrorBox, Modal, PageHeader, Spinner, StatCard, useApi, useToast } from "../components";

const STATUSES = ["none", "trialing", "active", "past_due", "canceled"];
const TONE = { active: "green", trialing: "blue", past_due: "red", canceled: "gray", none: "gray" };
const dateOnly = (iso) => (iso ? iso.slice(0, 10) : "");

function EditModal({ row, onClose, onSaved }) {
  const toast = useToast();
  const [f, setF] = useState({
    plan_name: row.plan_name || "Pilot", price_monthly: row.price_monthly || 0,
    status: row.status || "none", current_period_end: dateOnly(row.current_period_end),
    notes: row.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api(`/api/billing/subscriptions/${row.workspace_id}`, { method: "PUT", body: f });
      toast("Saved"); onSaved(); onClose();
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  return (
    <Modal title={`Subscription — ${row.workspace_name}`} onClose={onClose}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 380 }}>
        <label style={{ fontSize: 13 }}>Plan
          <input style={{ width: "100%", marginTop: 4 }} value={f.plan_name} onChange={(e) => set("plan_name", e.target.value)} /></label>
        <div style={{ display: "flex", gap: 12 }}>
          <label style={{ fontSize: 13, flex: 1 }}>Price / month ($)
            <input type="number" min="0" style={{ width: "100%", marginTop: 4 }} value={f.price_monthly}
              onChange={(e) => set("price_monthly", Number(e.target.value) || 0)} /></label>
          <label style={{ fontSize: 13, flex: 1 }}>Status
            <select style={{ width: "100%", marginTop: 4 }} value={f.status} onChange={(e) => set("status", e.target.value)}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
        </div>
        <label style={{ fontSize: 13 }}>Renews / lapses on
          <input type="date" style={{ width: "100%", marginTop: 4 }} value={f.current_period_end}
            onChange={(e) => set("current_period_end", e.target.value)} /></label>
        <label style={{ fontSize: 13 }}>Notes
          <textarea rows={2} style={{ width: "100%", marginTop: 4 }} value={f.notes} onChange={(e) => set("notes", e.target.value)} /></label>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy} onClick={save}>Save</button>
        </div>
      </div>
    </Modal>
  );
}

export default function Billing() {
  const { data, error, loading, reload } = useApi("/api/billing/summary");
  const [edit, setEdit] = useState(null);
  if (error) return <ErrorBox msg={error} retry={reload} />;
  if (loading || !data) return <Spinner />;

  return (
    <>
      <PageHeader title="Billing" desc="Client subscriptions and recurring revenue." />
      <div className="metrics" style={{ marginBottom: 18 }}>
        <StatCard label="MRR" value={money(data.mrr)} sub={`${data.active + data.trialing + data.past_due} paying`} />
        <StatCard label="Active" value={data.active} sub={`${data.trialing} trialing`} />
        <StatCard label="Past due" value={data.past_due} sub="need attention" />
        <StatCard label="Not set up" value={data.unset} sub="no plan yet" />
      </div>

      <table className="tbl">
        <thead><tr><th>Client</th><th>Plan</th><th>Price/mo</th><th>Status</th><th>Renews</th><th></th></tr></thead>
        <tbody>
          {data.clients.map((r) => (
            <tr key={r.workspace_id}>
              <td><b>{r.workspace_name}</b></td>
              <td>{r.plan_name || "—"}</td>
              <td>{r.price_monthly ? money(r.price_monthly) : "—"}</td>
              <td>
                <Badge tone={TONE[r.status] || "gray"}>{r.status}</Badge>
                {r.overdue && <Badge tone="red" style={{ marginLeft: 6 }}>overdue</Badge>}
              </td>
              <td style={{ fontSize: 12.5, color: "var(--muted)" }}>{dateOnly(r.current_period_end) || "—"}</td>
              <td><button className="btn ghost sm" onClick={() => setEdit(r)}>Edit</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      {edit && <EditModal row={edit} onClose={() => setEdit(null)} onSaved={reload} />}
    </>
  );
}
