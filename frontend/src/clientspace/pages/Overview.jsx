// Client Space · Overview — the module's landing screen.
//
// One screen that answers "what is the state of this account": where the launch
// is, how many days to first send, what is blocked and on whose side, and what
// is waiting on us. Everything on it is read from the launch plan, so nothing
// here is a number somebody typed into a slide.
import { useLocation, useNavigate } from "react-router-dom";
import { Building2, Gem, Hourglass, ListChecks } from "lucide-react";
import { useAuth } from "../../auth";
import { localDate } from "../../api";
import {
  Button, EmptyState, ErrorBox, Row, RowCard, Skeleton, StatCard, StatusPill, useApi,
} from "../../components";
import { moduleBase, path } from "../nav";

const HEALTH = {
  on_track: ["green", "On track"],
  blocked: ["red", "Blocked"],
  at_risk: ["amber", "At risk"],
  live: ["blue", "Live"],
  not_started: ["gray", "Not started"],
};
const SIDE = { us: "our side", client: "the client's side", both: "both sides" };
const OWNER = { us: "us", client: "the client" };

// Each stop opens the space where that phase's work actually lives, rather than
// all seven pointing at the plan. A rail you can only look at is decoration.
const STAGE_HOME = {
  intake: "onboarding-form", brain: "docs", icp: "library",
  infrastructure: "plan", copy: "sequences", list_build: "boards", live: "plan",
};

const countdown = (days) => {
  if (days === null || days === undefined) return "—";
  if (days === 0) return "Today";
  return days > 0 ? `${days}` : `${Math.abs(days)} late`;
};
const launchDate = (iso) => (iso
  ? new Date(`${String(iso).slice(0, 10)}T00:00:00`)
      .toLocaleDateString(undefined, { month: "short", day: "numeric" })
  : "—");

// The strip that answers "are we going to make it" before anything else on the
// screen. Three figures and a verdict — nothing that needs interpreting.
function Hero({ data, asClient }) {
  const [tone, label] = HEALTH[data.health] || HEALTH.not_started;
  const risks = data.risks || 0;
  const waiting = asClient ? (data.counts?.theirs ?? 0) : (data.counts?.ours ?? 0);
  return (
    <div className="cs-hero">
      <div className="cs-hero-figs">
        <div>
          <b>{countdown(data.days_to_first_send)}</b>
          <span>days to first send</span>
        </div>
        <div>
          <b>{launchDate(data.first_send_at)}</b>
          <span>target launch date</span>
        </div>
        <div className={waiting > 0 ? "attn" : ""}>
          <b>{waiting}</b>
          <span>items waiting on {asClient ? "you" : "us"}</span>
        </div>
      </div>
      <div className="cs-hero-state">
        <StatusPill tone={tone}>
          {label}{risks ? ` — ${risks} risk${risks === 1 ? "" : "s"}` : ""}
        </StatusPill>
        {data.critical_note && <span>{data.critical_note}</span>}
      </div>
    </div>
  );
}

// The progress rail. A stepper, not a row of pills: the connector carries the
// meaning — everything left of the ring is finished, everything right of it has
// not started. The note under each stop is read from the tasks in that phase, so
// the rail cannot claim progress the plan denies.
function WhereWeAre({ stages, base, nav, canOpen }) {
  return (
    <div className="card cs-where">
      <header>
        <b>Where we are</b>
        {canOpen && (
          <button className="cs-where-link" onClick={() => nav(path(base, "plan"))}>
            Open full plan →
          </button>
        )}
      </header>
      <div className="cs-steps">
        {stages.map((s, i) => (
          <button key={s.key} className={`cs-step ${s.state}`} title={s.note || s.label}
            onClick={() => nav(path(base, STAGE_HOME[s.key] || "plan"))}>
            <span className="cs-step-rail">
              <i className={`cs-step-line ${i === 0 ? "hide" : ""} ${
                stages[i - 1]?.state === "done" ? "on" : ""}`} />
              <span className="cs-step-dot" />
              <i className={`cs-step-line ${i === stages.length - 1 ? "hide" : ""} ${
                s.state === "done" ? "on" : ""}`} />
            </span>
            <span className="cs-step-label">{s.label}</span>
            <em>{s.note || " "}</em>
          </button>
        ))}
      </div>
      <p className="cs-where-hint">
        Every stage is clickable — it opens the space where that information lives.
      </p>
    </div>
  );
}

export default function Overview() {
  const { me, wsParam } = useAuth();
  const nav = useNavigate();
  const isClient = me?.role === "client";
  const base = moduleBase(useLocation().pathname, isClient);
  const { data, error, loading, reload } = useApi("/api/client-space/overview", { workspace_id: wsParam });

  if (error) return <ErrorBox msg={error} retry={reload} />;
  if (loading || !data) {
    return (
      <div className="metrics">
        {[...Array(4)].map((_, i) => (
          <div className="metric" key={i}><Skeleton w="50%" /><Skeleton w="70%" h={26} style={{ marginTop: 10 }} /></div>
        ))}
      </div>
    );
  }

  // Masters can sit on "All workspaces". Client Space is per-client by
  // definition, so say so rather than averaging seven launches into one number.
  if (!data.workspace) {
    return (
      <EmptyState icon={Building2} title="Choose a client"
        hint="Client Space shows one client at a time. Pick a workspace in the switcher above to see their launch." />
    );
  }

  const [tone, label] = HEALTH[data.health] || HEALTH.not_started;
  const c = data.counts || {};

  if (data.health === "not_started") {
    return (
      <>
        <div className="page-head">
          <div>
            <h1>{data.workspace.name}</h1>
            <p>Where this launch is, what is blocked, and what is waiting on us.</p>
          </div>
        </div>
        <EmptyState icon={Gem} title="This launch hasn't started"
          hint="The launch plan holds every task between today and the first send, and everything on this screen is read from it."
          action={data.can_edit
            ? <Button icon={Hourglass} onClick={() => nav(path(base, "plan"))}>Start the launch plan</Button>
            : null} />
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{data.workspace.name}</h1>
          <p>
            {data.stage_label ? `${data.stage_label} · ` : ""}
            <StatusPill tone={tone}>{label}</StatusPill>
            {data.blocked_side ? ` on ${SIDE[data.blocked_side]}` : ""}
          </p>
        </div>
        <div className="acts">
          <Button variant="ghost" icon={ListChecks} onClick={() => nav(path(base, "plan"))}>Open launch plan</Button>
        </div>
      </div>

      <Hero data={data} asClient={isClient} />

      <WhereWeAre stages={data.stages || []} base={base} nav={nav} canOpen={!isClient} />

      <div className="cc-grid">
        <RowCard title="Blocked" count={(data.blocked || []).length} className="span2"
          viewAll={path(base, "plan")}
          empty="Nothing is blocked. Blocked tasks appear here with the side that has to move.">
          {(data.blocked || []).map((t) => (
            <Row key={t.id} title={t.title}
              sub={`${t.stage_label} · waiting on ${OWNER[t.owner]}${t.blocked_note ? ` — ${t.blocked_note}` : ""}`}
              right={<StatusPill tone={t.owner === "client" ? "amber" : "red"}>{OWNER[t.owner]}</StatusPill>}
              onClick={() => nav(path(base, "plan"))} />
          ))}
        </RowCard>

        <RowCard title="Waiting on us" count={c.ours ?? 0} viewAll={path(base, "plan")}
          empty="Nothing sits with us right now.">
          {(data.waiting_on_us || []).map((t) => (
            <Row key={t.id} title={t.title} sub={t.stage_label}
              right={t.due_at ? localDate(t.due_at) : ""} onClick={() => nav(path(base, "plan"))} />
          ))}
        </RowCard>

        <RowCard title="Waiting on the client" count={c.theirs ?? 0} viewAll={path(base, "plan")}
          empty="Nothing sits with the client right now.">
          {(data.waiting_on_client || []).map((t) => (
            <Row key={t.id} title={t.title} sub={t.stage_label}
              right={t.due_at ? localDate(t.due_at) : ""} onClick={() => nav(path(base, "plan"))} />
          ))}
        </RowCard>

        <RowCard title="Shared with the client" className="span2"
          empty="Nothing has been shared yet.">
          <Row title="Docs" sub="pages the client can read" right={data.shared?.docs ?? 0}
            onClick={() => nav(path(base, "docs"))} />
          <Row title="Whiteboards" sub="canvases we map together" right={data.shared?.whiteboards ?? 0}
            onClick={() => nav(path(base, "whiteboards"))} />
          <Row title="Email sequences" sub="going out under their name" right={data.shared?.sequences ?? 0}
            onClick={() => nav(path(base, "sequences"))} />
          <Row title="Boards & tables" sub="saved views of their data" right={data.shared?.tables ?? 0}
            onClick={() => nav(path(base, "boards"))} />
        </RowCard>

        {/* Two audiences, two destinations. For us this is the internal Setup
            screen — who was invited and what came back. For the client it is
            the form itself, sitting here as an open task: the emailed link is
            buried in their inbox by the time they have an account, so this is
            how they get back to a half-finished form. */}
        {isClient ? (
          data.onboarding?.status && data.onboarding.status !== "not_sent" && (
            <RowCard title="Your onboarding form"
              empty="Nothing to fill in right now.">
              <Row title={data.onboarding.status === "submitted"
                ? "Onboarding form — all done" : "Finish your onboarding form"}
                sub={data.onboarding.status === "submitted"
                  ? `submitted ${localDate(data.onboarding.submitted_at)}`
                  : "picks up wherever you left off"}
                right={<StatusPill tone={data.onboarding.status === "submitted" ? "green" : "amber"}>
                  {data.onboarding.status === "submitted" ? "done" : "to do"}
                </StatusPill>}
                onClick={() => nav(path(base, "form"))} />
            </RowCard>
          )
        ) : (
          <RowCard title="Onboarding" viewAll={path(base, "onboarding-form")}
            empty="No onboarding form sent yet.">
            {data.onboarding?.status !== "not_sent" && (
              <Row title={data.onboarding.recipient || "Onboarding form"}
                sub={data.onboarding.submitted_at ? `submitted ${localDate(data.onboarding.submitted_at)}` : "sent, not submitted"}
                right={<StatusPill tone={data.onboarding.status === "submitted" ? "green" : "amber"}>
                  {data.onboarding.status}
                </StatusPill>}
                onClick={() => nav(path(base, "onboarding-form"))} />
            )}
          </RowCard>
        )}
      </div>
    </>
  );
}
