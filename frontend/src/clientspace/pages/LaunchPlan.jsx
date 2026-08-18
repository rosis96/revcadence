// Client Space · Launch Plan — every task between today and the first send.
//
// Three views over one payload. The server derives blocked-ness, slippage and
// the critical path once (app/client_space/plan.py) and all three render it, so
// a status changed on the Board is already correct on the Timeline and in the
// Overview's stage rail — there is no second copy of the rules to disagree.
//
// The view choice persists per workspace: an operator who lives in the Timeline
// should not land on the List every morning.
import { useCallback, useEffect, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  Building2, Check, Download, GitBranch, Hourglass, LayoutGrid, List as ListIcon,
  Plus, Settings2, Trash2,
} from "lucide-react";
import { API_BASE, api, getToken } from "../../api";
import { useAuth } from "../../auth";
import {
  Area, Button, confirmDialog, EmptyState, ErrorBox, Input, Modal, Select, Skeleton,
  StatusPill, useToast,
} from "../../components";
import { useClientView } from "../frame";
import Timeline from "../plan/Timeline";
import PlanList from "../plan/List";
import Board from "../plan/Board";
import { STATUS_TONE, todayKey } from "../plan/shared";

// Board first, and the default. A plan is built and worked here — the Timeline
// answers "will we make the date", which is a question you only have once there
// is something to schedule.
const VIEWS = [["board", "Board", LayoutGrid], ["list", "List", ListIcon],
  ["timeline", "Timeline", GitBranch]];
const VIEW_KEY = "rc_plan_view";
const dateValue = (iso) => (iso ? String(iso).slice(0, 10) : "");
const shiftDate = (iso, days) => {
  if (!iso) return null;
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

/* ------------------------------------------------------- task editor */
function TaskEditor({ task, plan, canEdit, onClose, onSave, onDelete }) {
  const [f, setF] = useState({
    title: task.title, detail: task.detail || "", stage: task.stage, owner: task.owner,
    status: task.status, start_at: dateValue(task.start_at), due_at: dateValue(task.due_at),
    is_milestone: task.is_milestone, blocked_note: task.blocked_note || "",
    depends_on: task.depends_on || [],
  });
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const others = (plan.tasks || []).filter((t) => t.id !== task.id);
  return (
    <Modal title={task.draft ? "New task" : canEdit ? "Edit task" : task.title} onClose={onClose}>
      <div className="plan-edit">
        <label className="wide">Task<Input value={f.title} disabled={!canEdit} autoFocus
          placeholder="Sending domains bought and records set"
          onChange={(e) => set("title", e.target.value)} /></label>
        <label className="wide">Detail<Area size="md" value={f.detail} disabled={!canEdit}
          onChange={(e) => set("detail", e.target.value)} /></label>
        <label>Phase
          <Select value={f.stage} disabled={!canEdit} onChange={(e) => set("stage", e.target.value)}>
            {(plan.phase_options || []).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </Select>
        </label>
        <label>Owner
          <Select value={f.owner} disabled={!canEdit} onChange={(e) => set("owner", e.target.value)}>
            {(plan.owners || []).map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
          </Select>
        </label>
        <label>Status
          <Select value={f.status} disabled={!canEdit} onChange={(e) => set("status", e.target.value)}>
            {(plan.statuses || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </Select>
        </label>
        <label>Start<Input type="date" value={f.start_at} disabled={!canEdit}
          onChange={(e) => set("start_at", e.target.value)} /></label>
        <label>Due<Input type="date" value={f.due_at} disabled={!canEdit}
          onChange={(e) => set("due_at", e.target.value)} /></label>
        <label className="chk">
          <input type="checkbox" checked={!!f.is_milestone} disabled={!canEdit}
            onChange={(e) => set("is_milestone", e.target.checked)} />
          <span>Milestone — a moment, not a span</span>
        </label>
        <label className="wide">Waits for
          <select multiple size={4} value={f.depends_on.map(String)} disabled={!canEdit}
            onChange={(e) => set("depends_on",
              Array.from(e.target.selectedOptions).map((o) => Number(o.value)))}>
            {others.map((t) => <option key={t.id} value={t.id}>{t.phase_short} · {t.title}</option>)}
          </select>
        </label>
        <label className="wide">Blocked because<Input value={f.blocked_note} disabled={!canEdit}
          placeholder="Their legal team is reviewing it"
          onChange={(e) => set("blocked_note", e.target.value)} /></label>
        {task.blocked_by?.length > 0 && (
          <div className="plan-edit-note wide">
            Waiting on {task.blocked_by.map((b) => b.title).join(", ")}.
          </div>
        )}
        {task.critical && (
          <div className="plan-edit-note wide critical">
            On the critical path — moving this moves the launch date.
          </div>
        )}
      </div>
      <div className="actions">
        {canEdit && !task.draft && (
          <Button variant="ghost" icon={Trash2} onClick={() => onDelete(task)}>Delete</Button>
        )}
        <span style={{ flex: 1 }} />
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        {canEdit && (
          <Button icon={Check} disabled={!f.title.trim()} onClick={() => onSave(task, f)}>
            {task.draft ? "Add task" : "Save"}
          </Button>
        )}
      </div>
    </Modal>
  );
}

// The dates the plan is measured against. There is no template to set them any
// more, so the plan has to be able to state them itself — without a first-send
// date "6 days to first send" has nothing to count towards.
function PlanSettings({ launch, plan, onClose, onSave }) {
  const [f, setF] = useState({
    name: launch?.name || "Outbound Launch Plan",
    stage: launch?.stage || "intake",
    kickoff_at: dateValue(launch?.kickoff_at),
    first_send_at: dateValue(launch?.first_send_at),
    prospect_target: launch?.prospect_target || 0,
  });
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  return (
    <Modal title="Plan settings" onClose={onClose}>
      <div className="plan-edit">
        <label className="wide">Plan name<Input value={f.name}
          onChange={(e) => set("name", e.target.value)} /></label>
        <label>Current phase
          <Select value={f.stage} onChange={(e) => set("stage", e.target.value)}>
            {(plan.phase_options || []).map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </Select>
        </label>
        <label>Prospect target<Input type="number" min={0} value={f.prospect_target}
          onChange={(e) => set("prospect_target", Number(e.target.value))} /></label>
        <label>Kick-off<Input type="date" value={f.kickoff_at}
          onChange={(e) => set("kickoff_at", e.target.value)} /></label>
        <label>Target first send<Input type="date" value={f.first_send_at}
          onChange={(e) => set("first_send_at", e.target.value)} /></label>
      </div>
      <div className="actions">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button icon={Check} onClick={() => onSave(f)}>Save</Button>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------- screen */
export default function LaunchPlan() {
  const { wsParam } = useAuth();
  const { previewing } = useClientView();
  const toast = useToast();
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState(() => localStorage.getItem(VIEW_KEY) || "board");
  const [editing, setEditing] = useState(null);
  const [baseline, setBaseline] = useState(false);
  const [settings, setSettings] = useState(false);

  const load = useCallback(() => {
    setError("");
    api("/api/client-space/plan", { params: { workspace_id: wsParam } })
      .then(setPlan).catch((e) => setError(e.message));
  }, [wsParam]);
  useEffect(() => { load(); }, [load]);

  const pickView = (key) => { localStorage.setItem(VIEW_KEY, key); setView(key); };
  const ws = () => (wsParam ? Number(wsParam) : null);

  // Every mutation returns the whole recomputed plan, so the critical path and
  // blocked-ness are never stale by one interaction.
  // Returns whether it worked, so a caller can keep a form open on failure
  // instead of closing it and throwing the user's typing away.
  const run = async (fn, ok) => {
    setBusy(true);
    try { setPlan(await fn()); if (ok) toast(ok); return true; }
    catch (e) { toast(e.message, "bad"); return false; }
    finally { setBusy(false); }
  };

  const patch = (task, body) =>
    run(() => api(`/api/client-space/plan/tasks/${task.id}`, { method: "PATCH", body }));

  const save = async (task, f) => {
    const body = { ...f, start_at: f.start_at || "", due_at: f.due_at || "" };
    const ok = task.draft
      ? await run(() => api("/api/client-space/plan/tasks", {
        method: "POST", body: { workspace_id: ws(), ...body },
      }), "Task added")
      : await run(() => api(`/api/client-space/plan/tasks/${task.id}`, { method: "PATCH", body }), "Task saved");
    if (ok) setEditing(null);
  };

  const remove = async (task) => {
    if (!(await confirmDialog(`Delete "${task.title}"?`, { danger: true, confirmText: "Delete" }))) return;
    setEditing(null);
    run(() => api(`/api/client-space/plan/tasks/${task.id}`, { method: "DELETE" }), "Task deleted");
  };

  const reschedule = (task, shift) => patch(task, {
    start_at: shiftDate(task.start_at, shift) || "",
    due_at: shiftDate(task.due_at, shift) || "",
  });

  // Opening the editor writes NOTHING. A placeholder row called "New task" that
  // somebody abandons is worse than no row: it shows up on the board, in the
  // counts, and in the client's view of their own plan. The task exists when it
  // is saved, and not before.
  const openNew = (stage, status) => setEditing({
    draft: true, title: "", detail: "", owner: "us",
    stage: stage || plan?.launch?.stage || "intake", status: status || "backlog",
    start_at: null, due_at: null, is_milestone: false, depends_on: [], blocked_note: "",
  });

  const exportCsv = async () => {
    // Authed download: the CSV endpoint needs the bearer token, so it cannot be
    // a plain link.
    const url = new URL(`${API_BASE}/api/client-space/plan/export`, window.location.origin);
    if (wsParam) url.searchParams.set("workspace_id", wsParam);
    try {
      const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "launch-plan.csv";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    } catch (e) { toast(e.message, "bad"); }
  };

  if (error) return <ErrorBox msg={error} retry={load} />;
  if (!plan) {
    return <div className="card" style={{ padding: 16 }}><Skeleton w="40%" />
      <Skeleton style={{ marginTop: 12 }} /></div>;
  }
  if (!plan.workspace) {
    return <EmptyState icon={Building2} title="Choose a client"
      hint="A launch plan belongs to one client. Pick a workspace in the switcher above." />;
  }

  const canEdit = plan.can_edit && !previewing;
  const tasks = plan.tasks || [];
  const empty = !tasks.length;

  // ONE return, not two.
  //
  // The empty state used to return early — above the <TaskEditor/> at the
  // bottom of this component. "Add the first task" set `editing` and nothing
  // rendered it, because the only thing that renders it was in the branch this
  // never reached. A plan with no tasks is the exact moment you need that
  // editor most, so the editor now lives outside the branch entirely.
  //
  // And ONE layout, not two. An empty plan no longer replaces the page with a
  // message: the switcher and the chosen view always render, and each view
  // draws its own emptiness inside its own chrome — column headers over an
  // empty table, five lanes you can still drop into, an axis with no bars. So
  // the switcher works before the first task exists, and the view you were on
  // is the view you are on once you add it. There is no branch to fall out of,
  // which is what used to reset the choice.
  return (
    <>
      <div className="plan-head">
        <div>
          <div className="plan-crumb">Client Space / Launch Plan</div>
          <h1>{plan.launch?.name || "Outbound Launch Plan"}</h1>
          {plan.launch?.subtitle && <p>{plan.launch.subtitle}</p>}
        </div>
        <div className="acts">
          {canEdit && (
            <Button variant="ghost" size="sm" icon={Settings2}
              onClick={() => setSettings(true)}>Settings</Button>
          )}
          {/* Baseline and Export read the tasks. With none they are a snapshot
              of nothing and a CSV of headers, so they wait for the first task —
              and the header's Task button stands down while the empty-state
              prompt below carries the call to action, so there is one primary
              "add a task", not two of them a centimetre apart. */}
          {!empty && (
            <>
              <Button variant={baseline ? "primary" : "ghost"} size="sm"
                onClick={() => (plan.launch?.baseline_at
                  ? setBaseline((v) => !v)
                  : run(() => api("/api/client-space/plan/baseline",
                    { method: "POST", body: { workspace_id: ws() } }), "Baseline captured"))}>
                {plan.launch?.baseline_at ? "Baseline vs actual" : "Set baseline"}
              </Button>
              <Button variant="ghost" size="sm" icon={Download} onClick={exportCsv}>Export</Button>
              {canEdit && <Button size="sm" icon={Plus} onClick={() => openNew()}>Task</Button>}
            </>
          )}
        </div>
      </div>

      <div className="plan-tabs">
        {VIEWS.map(([key, label, Ic]) => (
          <button key={key} className={`plan-tab ${view === key ? "on" : ""}`}
            onClick={() => pickView(key)}>
            <Ic size={14} />{label}
          </button>
        ))}
        <span className="plan-tabs-spacer" />
        <span className="plan-summary">
          {/* "0/0 done" is not a fact worth a pill. Days-to-first-send is one
              even with no tasks — it is the date the plan is measured against. */}
          {!empty && (
            <StatusPill tone={plan.filters?.blocked ? "red" : "green"}>
              {plan.counts?.done}/{plan.counts?.total} done
            </StatusPill>
          )}
          {plan.launch?.days_to_first_send != null && (
            <em>{plan.launch.days_to_first_send >= 0
              ? `${plan.launch.days_to_first_send} days to first send`
              : `first send was ${Math.abs(plan.launch.days_to_first_send)} days ago`}</em>
          )}
        </span>
      </div>

      {/* The old full-page empty state, demoted to a strip. Same sentence — it
          is the one that says what a launch plan is actually for — but it now
          sits above a working view instead of standing in for one, and it is
          rendered once here rather than three times inside the views, because
          the answer to "how do I start" does not change with the view. */}
      {empty && (
        <div className="plan-empty-note">
          <Hourglass size={15} />
          <span>
            <b>No launch plan yet.</b> Add the work between today and this client&apos;s
            first send. Give each task an owner and a phase; link what waits on what,
            and the critical path draws itself.
          </span>
          {canEdit && <Button size="sm" icon={Plus} onClick={() => openNew()}>Add task</Button>}
        </div>
      )}

      {view === "timeline" && (
        <Timeline plan={plan} canEdit={canEdit} onOpen={setEditing}
          onReschedule={reschedule} showBaseline={baseline}
          onSchedule={() => run(() => api("/api/client-space/plan/schedule",
            { method: "POST", body: { workspace_id: ws() } }), "Plan scheduled")} />
      )}
      {view === "list" && (
        <PlanList plan={plan} canEdit={canEdit} onOpen={setEditing}
          onPatch={patch} todayISO={todayKey()} />
      )}
      {view === "board" && (
        <Board plan={plan} canEdit={canEdit} onOpen={setEditing} onPatch={patch}
          onAdd={(lane) => openNew(null, lane)} />
      )}

      <AnimatePresence>
        {settings && (
          <PlanSettings key="settings" launch={plan.launch} plan={plan} onClose={() => setSettings(false)}
            onSave={(f) => { setSettings(false);
              run(() => api("/api/client-space/plan", { method: "PUT", body: { workspace_id: ws(), ...f } }),
                "Plan updated"); }} />
        )}
        {editing && (
          <TaskEditor key="task" task={(editing.id && plan.tasks.find((t) => t.id === editing.id)) || editing}
            plan={plan} canEdit={canEdit} onClose={() => setEditing(null)} onSave={save} onDelete={remove} />
        )}
      </AnimatePresence>
    </>
  );
}
