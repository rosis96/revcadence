// Vocabulary shared by the three launch-plan views.
//
// Timeline, List and Board are three arrangements of one dataset, so the words
// and colours have to come from one place — a task the board calls "Waiting on
// client" in amber must not be blue and called something else on the Gantt.

// Bar and pill colour by who has to move. Done wins over owner (a finished
// client task is green, not amber) and critical wins over both, because "this
// moves the launch date" outranks "this is yours".
export const OWNER_TONE = { us: "us", client: "client", system: "system", both: "both" };

export const STATUS_TONE = {
  backlog: "gray", waiting_client: "amber", in_progress: "blue",
  review: "indigo", done: "green",
};

export const LEGEND = [
  ["done", "Done"],
  ["us", "RevCadence"],
  ["client", "Client action"],
  ["system", "Automated / system"],
  ["critical", "Critical path"],
];

// One class for a bar or card, resolved in the order that matters.
export const taskTone = (t) =>
  (t.status === "done" ? "done" : t.critical ? "critical" : OWNER_TONE[t.owner] || "us");

export const dayKey = (iso) => (iso ? String(iso).slice(0, 10) : "");

export const shortDate = (iso) => {
  if (!iso) return "";
  const d = new Date(`${dayKey(iso)}T00:00:00`);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

// "overdue 2d" reads as a fact; "overdue" alone reads as an opinion.
export const lateLabel = (t) =>
  (t.overdue ? `overdue ${t.overdue_days}d` : t.due_at ? `due ${shortDate(t.due_at)}` : "");

export const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
