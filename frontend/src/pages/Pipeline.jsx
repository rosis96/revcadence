import { useEffect, useMemo, useState } from "react";
import { api, money, timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Drawer, ErrorBox, Modal, Spinner, Timeline, useApi } from "../components";

function NewDealModal({ onClose, onCreated, workspaceId, stages }) {
  const { data: companies } = useApi("/api/companies", { workspace_id: workspaceId });
  const { data: contacts } = useApi("/api/contacts", { workspace_id: workspaceId });
  const [form, setForm] = useState({ name: "", company_id: "", contact_id: "", stage_id: "", value: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (stages?.length && !form.stage_id) setForm((f) => ({ ...f, stage_id: String(stages[0].id) })); }, [stages]);
  // contacts filtered to the chosen company (if any)
  const contactOpts = (contacts || []).filter((c) => !form.company_id || String(c.company_id) === String(form.company_id));

  const submit = async (e) => {
    e.preventDefault();
    if (!workspaceId) { setError("Pick a specific workspace first (top-left)."); return; }
    setBusy(true); setError("");
    try {
      const r = await api("/api/deals", { method: "POST",
        body: { workspace_id: Number(workspaceId), name: form.name,
                company_id: form.company_id ? Number(form.company_id) : null,
                contact_id: form.contact_id ? Number(form.contact_id) : null,
                stage_id: form.stage_id ? Number(form.stage_id) : null,
                value: form.value ? Number(form.value) : 0 } });
      onCreated(r.id);
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  return (
    <Modal title="New deal" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="error-box" style={{ marginBottom: 10 }}>{error}</div>}
        <div className="field"><label>Deal name</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                 placeholder="e.g. Acme — managed revenue engine" autoFocus /></div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>Company</label>
            <select value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value, contact_id: "" })}>
              <option value="">— none —</option>
              {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select></div>
          <div className="field"><label>Contact</label>
            <select value={form.contact_id} onChange={(e) => setForm({ ...form, contact_id: e.target.value })}>
              <option value="">— none —</option>
              {contactOpts.map((c) => <option key={c.id} value={c.id}>{c.name || c.email}</option>)}
            </select></div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div className="field"><label>Stage</label>
            <select value={form.stage_id} onChange={(e) => setForm({ ...form, stage_id: e.target.value })}>
              {(stages || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></div>
          <div className="field"><label>Value ($)</label>
            <input type="number" min="0" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} placeholder="0" /></div>
        </div>
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create deal"}</button>
        </div>
      </form>
    </Modal>
  );
}

function DealDrawer({ dealId, onClose, onChanged }) {
  const { data: d, error, loading, reload } = useApi(`/api/deals/${dealId}`);
  const [busy, setBusy] = useState(false);
  const move = async (stageId) => {
    setBusy(true);
    try { await api(`/api/deals/${dealId}/move`, { method: "POST", body: { stage_id: Number(stageId) } }); reload(); onChanged(); }
    catch (e) { alert(e.message); }
    setBusy(false);
  };
  return (
    <Drawer title={loading ? "Loading…" : d?.name || "Deal"} onClose={onClose}>
      {loading && <Spinner />}
      {error && <ErrorBox msg={error} />}
      {d && (
        <>
          <div className="kv">
            <div className="k">Value</div><div><b>{money(d.value)}</b></div>
            <div className="k">Stage</div>
            <div>
              <select disabled={busy} value={d.stage?.id || ""} onChange={(e) => move(e.target.value)}>
                {d.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div className="k">Company</div><div>{d.company ? <a href={`#/companies/${d.company.id}`}>{d.company.name}</a> : "—"}</div>
            <div className="k">Contact</div><div>{d.contact ? `${d.contact.name} · ${d.contact.email}` : "—"}</div>
            <div className="k">Lead intent</div><div>{d.lead_intent ? <Badge tone="indigo">{d.lead_intent}</Badge> : "—"}</div>
            <div className="k">Status</div><div>{d.status_label || "—"}</div>
            <div className="k">Next step</div><div>{d.next_step || "—"}</div>
            <div className="k">Close date</div><div>{d.close_date || "—"}</div>
          </div>
          {d.description && <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 14 }}>{d.description}</p>}
          <h3 style={{ fontSize: 13, margin: "14px 0 8px" }}>Timeline</h3>
          <Timeline items={d.timeline} />
        </>
      )}
    </Drawer>
  );
}

export default function Pipeline() {
  const { wsParam, me } = useAuth();
  const { data: board, error, loading, reload } = useApi("/api/deals/board", { workspace_id: wsParam });
  const [openDeal, setOpenDeal] = useState(null);
  const [dragOver, setDragOver] = useState(null);
  const [modal, setModal] = useState(false);
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);
  const stages = useMemo(() => (board || []).map((col) => col.stage), [board]);

  const onDrop = async (e, stage) => {
    setDragOver(null);
    const dealId = e.dataTransfer.getData("dealId");
    if (!dealId) return;
    try { await api(`/api/deals/${dealId}/move`, { method: "POST", body: { stage_id: stage.id } }); reload(); }
    catch (err) { alert(err.message); }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  return (
    <>
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <h1 style={{ fontSize: 18 }}>Pipeline</h1>
        <div className="spacer" />
        {!wsId && <span style={{ fontSize: 12, color: "var(--muted)", marginRight: 8 }}>Pick a workspace to add a deal</span>}
        <button className="btn" disabled={!wsId} onClick={() => setModal(true)}>+ New deal</button>
      </div>
      <div className="board">
        {board.map((col) => (
          <div key={col.stage.name} className={`col ${dragOver === col.stage.name ? "dragover" : ""}`}
               onDragOver={(e) => { e.preventDefault(); setDragOver(col.stage.name); }}
               onDragLeave={() => setDragOver(null)}
               onDrop={(e) => onDrop(e, col.stage)}>
            <h3>
              <span><span className="dot" style={{ background: col.stage.color, marginRight: 6 }} />{col.stage.name}</span>
              <span className="tot">{col.count} · {money(col.total_value)}</span>
            </h3>
            {col.deals.map((d) => (
              <div key={d.id} className="dealcard" draggable
                   onDragStart={(e) => e.dataTransfer.setData("dealId", String(d.id))}
                   onClick={() => setOpenDeal(d.id)}>
                <div className="nm">{d.name || d.company_name || "Untitled deal"}</div>
                <div className="co">{d.company_name}{d.contact_name ? ` · ${d.contact_name}` : ""}</div>
                <div className="row">
                  <span className="val">{money(d.value)}</span>
                  {d.lead_intent && <Badge tone="indigo">{d.lead_intent}</Badge>}
                </div>
                <div className="co" style={{ marginTop: 4 }}>{timeAgo(d.updated_at)}</div>
              </div>
            ))}
            {col.deals.length === 0 && <div className="empty" style={{ padding: "18px 8px", fontSize: 12.5 }}>Drop deals here</div>}
          </div>
        ))}
      </div>
      {openDeal && <DealDrawer dealId={openDeal} onClose={() => setOpenDeal(null)} onChanged={reload} />}
      {modal && (
        <NewDealModal workspaceId={wsId} stages={stages} onClose={() => setModal(false)}
                      onCreated={(id) => { setModal(false); reload(); setOpenDeal(id); }} />
      )}
    </>
  );
}
