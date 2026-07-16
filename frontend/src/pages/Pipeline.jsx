import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Rows3 } from "lucide-react";
import { api, money, timeAgo } from "../api";
import { useAuth } from "../auth";
import {
  Badge, Button, DataTable, Drawer, ErrorBox, Modal, PageHeader, Spinner, Tabs,
  Timeline, useApi,
} from "../components";

function NewLeadModal({ onClose, onCreated, workspaceId, stages }) {
  const { data: companies } = useApi("/api/companies", { workspace_id: workspaceId });
  const { data: contacts } = useApi("/api/contacts", { workspace_id: workspaceId });
  const [coMode, setCoMode] = useState("existing");   // existing | new
  const [ctMode, setCtMode] = useState("new");         // new | existing
  const [form, setForm] = useState({
    company_id: "", company_name: "",
    contact_id: "", first_name: "", last_name: "", email: "", title: "",
    stage_id: "", deal_name: "", value: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (stages?.length && !form.stage_id) setForm((f) => ({ ...f, stage_id: String(stages[0].id) })); }, [stages]);
  const contactOpts = (contacts || []).filter((c) => coMode === "new" || !form.company_id || String(c.company_id) === String(form.company_id));

  const submit = async (e) => {
    e.preventDefault();
    if (!workspaceId) { setError("Pick a specific workspace first (top-left)."); return; }
    setBusy(true); setError("");
    try {
      const body = { workspace_id: Number(workspaceId),
        stage_id: form.stage_id ? Number(form.stage_id) : null,
        deal_name: form.deal_name, value: form.value ? Number(form.value) : 0 };
      if (coMode === "existing") body.company_id = form.company_id ? Number(form.company_id) : null;
      else body.company_name = form.company_name;
      if (ctMode === "existing") body.contact_id = form.contact_id ? Number(form.contact_id) : null;
      else Object.assign(body, { first_name: form.first_name, last_name: form.last_name, email: form.email, title: form.title });
      const r = await api("/api/leads", { method: "POST", body });
      onCreated(r.deal_id);
    } catch (err) { setError(err.message); }
    setBusy(false);
  };
  const Seg = ({ v, cur, set, children }) => (
    <button type="button" onClick={() => set(v)} className={`btn ${cur === v ? "" : "ghost"} sm`}>{children}</button>
  );
  return (
    <Modal title="New lead" onClose={onClose}>
      <form onSubmit={submit}>
        {error && <div className="error-box" style={{ marginBottom: 10 }}>{error}</div>}
        <p style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 0 }}>
          Adds the lead to Companies, Contacts and the Pipeline together — for website or referral leads that didn’t come through reply management.</p>

        <label style={{ fontSize: 12.5, fontWeight: 600 }}>Company</label>
        <div style={{ display: "flex", gap: 6, margin: "4px 0 6px" }}>
          <Seg v="existing" cur={coMode} set={setCoMode}>Existing</Seg>
          <Seg v="new" cur={coMode} set={setCoMode}>New</Seg>
        </div>
        {coMode === "existing" ? (
          <div className="field"><select value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value, contact_id: "" })}>
            <option value="">— none —</option>
            {(companies || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></div>
        ) : (
          <div className="field"><input value={form.company_name} placeholder="New company name"
                onChange={(e) => setForm({ ...form, company_name: e.target.value })} /></div>
        )}

        <label style={{ fontSize: 12.5, fontWeight: 600 }}>Contact</label>
        <div style={{ display: "flex", gap: 6, margin: "4px 0 6px" }}>
          <Seg v="new" cur={ctMode} set={setCtMode}>New</Seg>
          <Seg v="existing" cur={ctMode} set={setCtMode}>Existing</Seg>
        </div>
        {ctMode === "existing" ? (
          <div className="field"><select value={form.contact_id} onChange={(e) => setForm({ ...form, contact_id: e.target.value })}>
            <option value="">— none —</option>
            {contactOpts.map((c) => <option key={c.id} value={c.id}>{c.name || c.email}</option>)}
          </select></div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="field"><input value={form.first_name} placeholder="First name"
                    onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></div>
              <div className="field"><input value={form.last_name} placeholder="Last name"
                    onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div className="field"><input type="email" value={form.email} placeholder="Email"
                    onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
              <div className="field"><input value={form.title} placeholder="Title"
                    onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            </div>
          </>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
          <div className="field"><label>Stage</label>
            <select value={form.stage_id} onChange={(e) => setForm({ ...form, stage_id: e.target.value })}>
              {(stages || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select></div>
          <div className="field"><label>Deal name</label>
            <input value={form.deal_name} placeholder="optional" onChange={(e) => setForm({ ...form, deal_name: e.target.value })} /></div>
          <div className="field"><label>Value ($)</label>
            <input type="number" min="0" value={form.value} placeholder="0" onChange={(e) => setForm({ ...form, value: e.target.value })} /></div>
        </div>
        <div className="actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={busy}>{busy ? "Adding…" : "Add lead"}</button>
        </div>
      </form>
    </Modal>
  );
}

function DealDrawer({ dealId, onClose, onChanged }) {
  const nav = useNavigate();
  const { data: d, error, loading, reload } = useApi(`/api/deals/${dealId}`);
  const { data: ags } = useApi(`/api/agreements`, { deal_id: dealId });
  const [busy, setBusy] = useState(false);
  const move = async (stageId) => {
    setBusy(true);
    try { await api(`/api/deals/${dealId}/move`, { method: "POST", body: { stage_id: Number(stageId) } }); reload(); onChanged(); }
    catch (e) { alert(e.message); }
    setBusy(false);
  };
  const newAgreement = async () => {
    setBusy(true);
    try { const a = await api("/api/agreements/generate", { method: "POST", body: { deal_id: Number(dealId) } }); nav(`/agreements/${a.id}`); }
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
          <div style={{ display: "flex", alignItems: "center", margin: "10px 0 6px" }}>
            <h3 style={{ fontSize: 13, flex: 1, margin: 0 }}>Agreement</h3>
            <button className="btn ghost sm" disabled={busy} onClick={newAgreement}>+ New</button>
          </div>
          {(ags || []).length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>No agreement yet for this deal.</div>}
          {(ags || []).map((ag) => (
            <div key={ag.id} className="click" onClick={() => nav(`/agreements/${ag.id}`)}
                 style={{ display: "flex", gap: 8, alignItems: "center", padding: "6px 0", fontSize: 12.5 }}>
              <span>✍</span><span style={{ flex: 1 }}>{ag.number} · v{ag.version}</span>
              <Badge tone={ag.status === "executed" ? "green" : "blue"}>{ag.status}</Badge>
            </div>
          ))}
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
  const params = new URLSearchParams(window.location.hash.split("?")[1] || "");
  const [openDeal, setOpenDeal] = useState(params.get("open") ? Number(params.get("open")) : null);
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

  const [view, setView] = useState(localStorage.getItem("rc_pipeline_view") || "board");
  const changeView = (v) => { localStorage.setItem("rc_pipeline_view", v); setView(v); };
  const allDeals = useMemo(() => (board || []).flatMap((col) =>
    col.deals.map((d) => ({ ...d, stage_name: col.stage.name, stage_color: col.stage.color }))), [board]);
  const dealColumns = useMemo(() => [
    { id: "deal", header: "Deal", size: 240, accessorFn: (d) => d.name || d.company_name || "Untitled deal",
      cell: ({ row, getValue }) => (
        <div><div className="lead-nm">{getValue()}</div>
          <div className="lead-sub">{row.original.contact_name || ""}</div></div>) },
    { accessorKey: "company_name", header: "Company", size: 190, cell: ({ getValue }) => getValue() || "—" },
    { id: "stage", header: "Stage", size: 160, accessorFn: (d) => d.stage_name,
      cell: ({ row }) => (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600 }}>
          <span className="dot" style={{ background: row.original.stage_color }} />{row.original.stage_name}
        </span>) },
    { accessorKey: "value", header: "Value", size: 110, cell: ({ getValue }) => money(getValue()) },
    { accessorKey: "lead_intent", header: "Intent", size: 140,
      cell: ({ getValue }) => (getValue() ? <Badge tone="indigo">{getValue()}</Badge> : "—") },
    { accessorKey: "updated_at", header: "Updated", size: 110, cell: ({ getValue }) => timeAgo(getValue()) },
  ], []);

  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  return (
    <>
      <PageHeader title="Pipeline" desc="Every open deal, by stage. Drag cards on the board, or work the table."
        actions={
          <>
            {!wsId && <span style={{ fontSize: 12, color: "var(--muted)", alignSelf: "center" }}>Pick a workspace to add a lead</span>}
            <Button icon={Plus} disabled={!wsId} onClick={() => setModal(true)}>New lead</Button>
          </>
        } />
      <div style={{ marginBottom: 16 }}>
        <Tabs value={view} onChange={changeView} tabs={[
          { key: "board", label: "Board" },
          { key: "table", label: "Table", count: allDeals.length },
        ]} />
      </div>

      {view === "table" && (
        <DataTable
          id="deals" columns={dealColumns} data={allDeals}
          searchPlaceholder="Search deals…" getRowId={(r) => String(r.id)}
          onRowClick={(r) => setOpenDeal(r.id)}
          emptyIcon={Rows3} emptyTitle="No deals yet"
          emptyHint="Add a lead or promote one from reply management."
        />
      )}

      {view === "board" && (
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
      )}
      {openDeal && <DealDrawer dealId={openDeal} onClose={() => setOpenDeal(null)} onChanged={reload} />}
      {modal && (
        <NewLeadModal workspaceId={wsId} stages={stages} onClose={() => setModal(false)}
                      onCreated={(id) => { setModal(false); reload(); setOpenDeal(id); }} />
      )}
    </>
  );
}
