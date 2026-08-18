// Launch Plan · Timeline — the Gantt.
//
// Drawn with absolutely-positioned bars over a day grid rather than an SVG or a
// charting library: every bar has to be a real focusable control (click to open,
// drag to reschedule), and the rows have to reuse the same sticky-label pattern
// the rest of the app's tables use. A library would give us pixels we then have
// to fight to make interactive.
//
// The left column is `position: sticky` so task names stay readable while the
// dates scroll — a Gantt where you lose track of which row you are on is a
// picture, not a tool.
import { useMemo, useRef, useState } from "react";
import { Flag } from "lucide-react";
import { LEGEND, dayKey, shortDate, taskTone, todayKey } from "./shared";

const DAY_W = 48;          // px per day column
const LABEL_W = 260;

export default function Timeline({ plan, canEdit, onOpen, onReschedule, onSchedule, showBaseline }) {
  const days = plan.range?.days || [];
  const index = useMemo(() => Object.fromEntries(days.map((d, i) => [d, i])), [days]);
  const [drag, setDrag] = useState(null);      // {id, dx} while a bar is moving
  const trackRef = useRef(null);

  const at = (iso) => index[dayKey(iso)] ?? null;
  const width = LABEL_W + days.length * DAY_W;
  const today = index[todayKey()];

  // Drag moves the whole bar: start and due shift together, so a slipped task
  // keeps its duration instead of silently growing.
  const startDrag = (e, task) => {
    if (!canEdit || !task.start_at) return;
    e.preventDefault();
    const originX = e.clientX;
    const move = (ev) => setDrag({ id: task.id, dx: Math.round((ev.clientX - originX) / DAY_W) });
    const up = (ev) => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      const shift = Math.round((ev.clientX - originX) / DAY_W);
      setDrag(null);
      if (shift !== 0) onReschedule(task, shift);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const rows = [];
  (plan.phases || []).forEach((phase) => {
    const tasks = (plan.tasks || []).filter((t) => t.stage === phase.key);
    if (!tasks.length) return;
    rows.push({ kind: "phase", phase });
    tasks.forEach((task) => rows.push({ kind: "task", task }));
  });

  return (
    <div className="card gantt-card">
      {/* A task with no dates has nowhere to sit on a time axis. Say that, and
          offer the fix — a blank grid with task names beside it reads as a
          broken screen rather than as unscheduled work. */}
      {plan.undated > 0 && (
        <div className="gantt-undated">
          <span>
            <b>{plan.undated} of {plan.tasks.length} tasks have no dates yet.</b>{" "}
            They cannot be placed on a timeline until they do.
          </span>
          {canEdit && (
            <button className="gantt-undated-btn" onClick={onSchedule}>
              Schedule from kickoff
            </button>
          )}
        </div>
      )}
      <div className="gantt-legend">
        <div className="gl-keys">
          {LEGEND.map(([tone, label]) => (
            <span key={tone} className="gl-key"><i className={`gl-dot tone-${tone}`} />{label}</span>
          ))}
          <span className="gl-key"><i className="gl-diamond" />Milestone</span>
        </div>
        <span className="gl-range">
          {days.length ? `${shortDate(days[0])} – ${shortDate(days[days.length - 1])}` : ""}
        </span>
      </div>

      <div className="gantt-scroll" ref={trackRef}>
        <div className="gantt-inner" style={{ width }}>
          <div className="gantt-row gantt-head">
            <div className="gantt-label" style={{ width: LABEL_W }}>Phase / Task</div>
            <div className="gantt-track" style={{ width: days.length * DAY_W }}>
              {days.map((d) => (
                <div key={d} className="gantt-day" style={{ width: DAY_W }}>{shortDate(d)}</div>
              ))}
              {today != null && (
                <span className="gantt-today" style={{ left: today * DAY_W + DAY_W / 2 }} />
              )}
            </div>
          </div>

          {/* An empty plan still gets a grid. `range` is always a real window —
              the server falls back to three weeks from today when no task has a
              date (app/client_space/plan.py) — so the axis, the day columns and
              the today marker are all true before the first task exists. Four
              blank rows, because one strip of dates under a header reads as a
              chart that failed to load rather than as a calendar waiting for
              work. */}
          {!rows.length && [0, 1, 2, 3].map((i) => (
            <div className="gantt-row gantt-empty" key={`e-${i}`}>
              <div className="gantt-label" style={{ width: LABEL_W }}>
                {i === 0 && <span className="gantt-empty-note">No tasks yet</span>}
              </div>
              <div className="gantt-track" style={{ width: days.length * DAY_W }}>
                {days.map((d) => <div key={d} className="gantt-day" style={{ width: DAY_W }} />)}
                {today != null && (
                  <span className="gantt-today" style={{ left: today * DAY_W + DAY_W / 2 }} />
                )}
              </div>
            </div>
          ))}

          {rows.map((row) => {
            if (row.kind === "phase") {
              return (
                <div className="gantt-row gantt-phase" key={`p-${row.phase.key}`}>
                  <div className="gantt-label" style={{ width: LABEL_W }}>
                    <b>{row.phase.index} · {row.phase.label}</b>
                  </div>
                  <div className="gantt-track" style={{ width: days.length * DAY_W }}>
                    {days.map((d) => <div key={d} className="gantt-day" style={{ width: DAY_W }} />)}
                  </div>
                </div>
              );
            }
            const t = row.task;
            const from = at(t.start_at);
            const to = at(t.due_at) ?? from;
            const shift = drag?.id === t.id ? drag.dx : 0;
            const tone = taskTone(t);
            return (
              <div className="gantt-row" key={t.id}>
                <div className="gantt-label" style={{ width: LABEL_W }} title={t.title}>
                  {t.is_milestone && <Flag size={12} className="gantt-ms-ic" />}
                  <span className="gantt-name">{t.title}</span>
                  {t.overdue && <em className="gantt-late">overdue</em>}
                </div>
                <div className="gantt-track" style={{ width: days.length * DAY_W }}>
                  {days.map((d) => <div key={d} className="gantt-day" style={{ width: DAY_W }} />)}
                  {today != null && (
                    <span className="gantt-today" style={{ left: today * DAY_W + DAY_W / 2 }} />
                  )}

                  {showBaseline && t.baseline_start_at && (
                    <span className="gantt-baseline" style={{
                      left: (at(t.baseline_start_at) ?? 0) * DAY_W + 3,
                      width: Math.max(DAY_W - 6,
                        ((at(t.baseline_due_at) ?? at(t.baseline_start_at)) -
                          (at(t.baseline_start_at) ?? 0) + 1) * DAY_W - 6),
                    }} />
                  )}

                  {from != null && (t.is_milestone ? (
                    <button className={`gantt-milestone ${drag?.id === t.id ? "dragging" : ""}`}
                      style={{ left: (from + shift) * DAY_W + DAY_W / 2 }}
                      onMouseDown={(e) => startDrag(e, t)} onClick={() => onOpen(t)}
                      title={`${t.title} · ${shortDate(t.start_at)}`}>
                      <span className="gm-diamond" />
                      <span className="gm-text">{t.title}</span>
                    </button>
                  ) : (
                    <button className={`gantt-bar tone-${tone} ${drag?.id === t.id ? "dragging" : ""}`}
                      style={{
                        left: (from + shift) * DAY_W + 3,
                        width: Math.max(DAY_W - 6, (to - from + 1) * DAY_W - 6),
                      }}
                      onMouseDown={(e) => startDrag(e, t)} onClick={() => onOpen(t)}
                      title={`${t.title} · ${t.owner_label} · ${shortDate(t.start_at)}–${shortDate(t.due_at)}`}>
                      {t.status === "done" && <span className="gb-tick">✓</span>}
                      <span className="gb-text">{t.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
