// Launch Plan · List — the plan as a table you can filter, group and edit.
//
// The Blocks column is the reason this view earns its place: it is the only one
// that shows the dependency graph as text, so you can read "this is what stops
// if this slips" without interpreting a picture.
import { Fragment, useMemo, useRef, useState } from "react";
import { Check, Columns3, Flag } from "lucide-react";
import { InlinePopup, Select, StatusPill } from "../../components";
import { STATUS_TONE, shortDate } from "./shared";

const COLUMNS = [
  ["phase", "Phase"], ["owner", "Owner"], ["start", "Start"],
  ["due", "Due"], ["status", "Status"], ["blocks", "Blocks"],
];
const FILTERS = [
  ["all", "All"], ["waiting_client", "Waiting on client"],
  ["blocked", "Blocked"], ["this_week", "This week"], ["overdue", "Overdue"],
];

const matches = (t, filter, todayISO) => {
  if (filter === "all") return true;
  if (t.status === "done") return false;
  if (filter === "waiting_client") return t.owner === "client";
  if (filter === "blocked") return t.blocked;
  if (filter === "overdue") return t.overdue;
  if (filter === "this_week") {
    if (!t.due_at) return false;
    const due = new Date(`${t.due_at.slice(0, 10)}T00:00:00`);
    const now = new Date(`${todayISO}T00:00:00`);
    return due >= now && due - now <= 7 * 864e5;
  }
  return true;
};

export default function List({ plan, canEdit, onOpen, onPatch, todayISO }) {
  const [filter, setFilter] = useState("all");
  const [grouped, setGrouped] = useState(true);
  const [hidden, setHidden] = useState({});
  const [colsOpen, setColsOpen] = useState(false);
  const colsRef = useRef(null);
  const shows = (key) => !hidden[key];

  const rows = useMemo(
    () => (plan.tasks || []).filter((t) => matches(t, filter, todayISO)),
    [plan.tasks, filter, todayISO]);

  // "Nothing matches this filter" is wrong when there is nothing to filter — it
  // sends you looking for a chip to clear. An empty plan says so instead.
  const noTasks = !(plan.tasks || []).length;
  // The header renders one <th> per shown column, so the empty row has to span
  // the same count. It was hard-coded to 7 and drifted the moment a column was
  // hidden — which the empty state now makes visible, because it is the row.
  const span = 1 + COLUMNS.filter(([key]) => shows(key)).length;

  const groups = useMemo(() => {
    if (!grouped) return [[null, rows]];
    return (plan.phases || [])
      .map((p) => [p, rows.filter((t) => t.stage === p.key)])
      .filter(([, list]) => list.length);
  }, [grouped, rows, plan.phases]);

  const statusCell = (t) => {
    if (t.overdue) return <StatusPill tone="red">Overdue</StatusPill>;
    if (t.blocked && t.status !== "done") return <StatusPill tone="amber">Blocked</StatusPill>;
    return <StatusPill tone={STATUS_TONE[t.status] || "gray"}>{t.status_label}</StatusPill>;
  };

  return (
    <div className="card plan-list-card">
      <div className="plan-toolbar">
        <div className="plan-chips">
          {FILTERS.map(([key, label]) => {
            const n = plan.filters?.[key] ?? 0;
            if (key !== "all" && !n) return null;
            return (
              <button key={key} className={`plan-chip ${filter === key ? "on" : ""}`}
                onClick={() => setFilter(key)}>
                {label} <em>{n}</em>
              </button>
            );
          })}
        </div>
        <div className="plan-tools">
          <button className="plan-tool" onClick={() => setGrouped((v) => !v)}>
            Group: {grouped ? "Phase" : "None"}
          </button>
          <button ref={colsRef} className="plan-tool" onClick={() => setColsOpen((v) => !v)}>
            <Columns3 size={13} /> Columns
          </button>
          <InlinePopup open={colsOpen} onClose={() => setColsOpen(false)} anchorRef={colsRef}
            align="end" className="plan-cols-pop">
            {COLUMNS.map(([key, label]) => (
              <button key={key} onClick={() => setHidden((h) => ({ ...h, [key]: !h[key] }))}>
                <span className="pc-check">{shows(key) && <Check size={12} />}</span>{label}
              </button>
            ))}
          </InlinePopup>
        </div>
      </div>

      <div className="plan-table-wrap">
        <table className="tbl plan-table">
          <thead>
            <tr>
              <th>Task</th>
              {shows("phase") && <th>Phase</th>}
              {shows("owner") && <th>Owner</th>}
              {shows("start") && <th>Start</th>}
              {shows("due") && <th>Due</th>}
              {shows("status") && <th>Status</th>}
              {shows("blocks") && <th>Blocks</th>}
            </tr>
          </thead>
          <tbody>
            {groups.map(([phase, list]) => (
              // Keyed: a bare <> in a .map() is an unkeyed list item, and React
              // says so on every render.
              <Fragment key={phase?.key ?? "ungrouped"}>
                {phase && (
                  <tr className="plan-group-row">
                    <td colSpan={span}>{phase.index} · {phase.label}
                      <em>{phase.done}/{phase.total}</em></td>
                  </tr>
                )}
                {list.map((t) => (
                  <tr key={t.id} className={t.critical ? "plan-critical" : ""}
                    onClick={() => onOpen(t)}>
                    <td>
                      <span className="plan-task-name">
                        {t.is_milestone && <Flag size={12} />}
                        <b>{t.title}</b>
                      </span>
                    </td>
                    {shows("phase") && <td className="muted-cell">{t.phase_label}</td>}
                    {shows("owner") && <td>{t.owner_label}</td>}
                    {shows("start") && <td className="muted-cell">{shortDate(t.start_at)}</td>}
                    {shows("due") && <td className="muted-cell">{shortDate(t.due_at)}</td>}
                    {shows("status") && (
                      <td onClick={(e) => e.stopPropagation()}>
                        {canEdit ? (
                          <Select size="sm" value={t.status}
                            onChange={(e) => onPatch(t, { status: e.target.value })}>
                            {(plan.statuses || []).map((s) => (
                              <option key={s.key} value={s.key}>{s.label}</option>
                            ))}
                          </Select>
                        ) : statusCell(t)}
                      </td>
                    )}
                    {shows("blocks") && (
                      <td className="muted-cell">{(t.blocks || []).join(", ")}</td>
                    )}
                  </tr>
                ))}
              </Fragment>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={span} className="plan-none">
                  {noTasks ? "No tasks yet." : "Nothing matches this filter."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
