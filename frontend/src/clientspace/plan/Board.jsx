// Launch Plan · Board — the plan by what state each task is in.
//
// Lanes are `status`, the same column the List's dropdown writes, so dragging a
// card here and changing the dropdown there are the same edit. There is no
// "Blocked" lane on purpose: blocked is derived from the dependency graph, so a
// lane for it would be one nothing could be dragged into and nothing could
// legitimately leave. A blocked card sits in the lane for the work it is waiting
// to do, and says so on its face.
import { useState } from "react";
import { Flag, Plus } from "lucide-react";
import { lateLabel, taskTone } from "./shared";

export default function Board({ plan, canEdit, onOpen, onPatch, onAdd }) {
  const [dragging, setDragging] = useState(null);
  const [over, setOver] = useState(null);

  const drop = (lane) => {
    setOver(null);
    const task = dragging;
    setDragging(null);
    if (task && task.status !== lane) onPatch(task, { status: lane });
  };

  return (
    <div className="plan-board">
      {(plan.lanes || []).map((lane) => {
        const cards = (plan.tasks || []).filter((t) => t.status === lane.key);
        return (
          <section key={lane.key}
            className={`plan-lane ${over === lane.key ? "over" : ""}`}
            onDragOver={(e) => { if (canEdit) { e.preventDefault(); setOver(lane.key); } }}
            onDragLeave={() => setOver((v) => (v === lane.key ? null : v))}
            onDrop={() => drop(lane.key)}>
            <header className="plan-lane-head">
              <b>{lane.label}</b><span>{lane.count}</span>
            </header>
            <div className="plan-lane-body">
              {cards.map((t) => (
                <article key={t.id} className={`plan-card tone-${taskTone(t)} ${t.blocked ? "blocked" : ""}`}
                  draggable={canEdit}
                  onDragStart={() => setDragging(t)}
                  onDragEnd={() => { setDragging(null); setOver(null); }}
                  onClick={() => onOpen(t)}>
                  <span className="pc-title">
                    {t.is_milestone && <Flag size={12} />}
                    {t.title}
                  </span>
                  <span className="pc-meta">
                    {t.phase_short} · {t.owner_label}
                    {lateLabel(t) ? ` · ${lateLabel(t)}` : ""}
                  </span>
                  {t.blocked && t.blocked_by?.length > 0 && (
                    <span className="pc-blocked">waiting on {t.blocked_by[0].title}</span>
                  )}
                </article>
              ))}
              {/* Lanes come from the status vocabulary, not from the tasks, so
                  an empty plan still draws all five and every one of them is
                  still a drop target. The placeholder says which it is: a
                  dashed target while something is in the air, a quiet label
                  when nothing is. */}
              {!cards.length && (
                <div className={`plan-lane-empty ${dragging ? "target" : ""}`}>
                  {dragging ? "Drop here" : "Nothing here"}
                </div>
              )}
              {canEdit && (
                <button className="plan-lane-add" onClick={() => onAdd(lane.key)}>
                  <Plus size={13} /> Add task
                </button>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
