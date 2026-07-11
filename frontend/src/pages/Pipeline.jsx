import { useState } from "react";
import { api, money, timeAgo } from "../api";
import { useAuth } from "../auth";
import { Badge, Drawer, ErrorBox, Spinner, Timeline, useApi } from "../components";

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
  const { wsParam } = useAuth();
  const { data: board, error, loading, reload } = useApi("/api/deals/board", { workspace_id: wsParam });
  const [openDeal, setOpenDeal] = useState(null);
  const [dragOver, setDragOver] = useState(null);

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
    </>
  );
}
