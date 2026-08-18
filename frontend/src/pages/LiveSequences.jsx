// Client Space → Email Sequences. READ-ONLY, and mirrored from the sending
// platform rather than from our own email_sequences tables.
//
// The reason is not caution, it is honesty: Instantly/Bison is what actually
// sends. A screen rendered from our tables is a claim about what a prospect will
// receive; this one is a report of it. If someone adds a step directly in the
// platform, this page shows it — which is exactly the case that makes rendering
// our own copy here indefensible.
//
// Nothing on this screen mutates. There is no editor to disable and no button
// that 403s: the client is a reader here, and "Request changes" (on the sequence
// approval flow) is their channel for anything else.
import { useEffect, useMemo, useState } from "react";
import {
  Clock, Inbox, Mail, MessageSquareReply, RefreshCw, ShieldCheck, Sparkles, Zap,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, EmptyState, ErrorBox, Spinner, StatusPill } from "../components";

const STATUS_TONE = { live: "green", paused: "amber", draft: "gray", completed: "gray" };
const STATUS_LABEL = { live: "Live", paused: "Paused", draft: "Draft", completed: "Finished" };

const TOKEN_RE = /(\{\{\s*[\w .-]+?\s*\}\})/g;

// Placeholders are the whole point of the page: they are what makes each send
// different, so they read as generated content rather than as literal braces.
function Copy({ text }) {
  const parts = useMemo(() => String(text || "").split(TOKEN_RE), [text]);
  return (
    <div className="seq-preview-body">
      {parts.map((part, i) => (TOKEN_RE.test(part) && part.startsWith("{{")
        ? <mark key={i} className="seq-generated" title="Written per prospect from real research">{part}</mark>
        : <span key={i}>{part}</span>))}
    </div>
  );
}

function relTime(iso) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 60000);
  if (!Number.isFinite(mins)) return "never";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function StepCard({ step, senderName }) {
  const [active, setActive] = useState(0);
  const variants = step.variants || [];
  const shown = variants[active] || variants[0] || {};
  const live = variants.filter((v) => v.enabled);

  return (
    <Card className="live-seq-step">
      <header className="live-seq-step-head">
        <div>
          <span className="live-seq-step-badge">Step {step.position}</span>
          <b>{step.position === 1 ? "Opening email" : `Follow-up ${step.position - 1}`}</b>
          <span className="live-seq-step-meta">
            Day {step.day_offset}
            {variants.length > 1 && ` · ${plural(live.length, "variant")} running`}
          </span>
        </div>
        {variants.length > 1 && (
          <div className="live-seq-variant-tabs" role="tablist">
            {variants.map((v, i) => (
              <button key={v.label} type="button" role="tab" aria-selected={i === active}
                      className={`live-seq-variant-tab${i === active ? " on" : ""}`}
                      onClick={() => setActive(i)}>
                {v.label}
                <em>{v.enabled ? `${v.reply_rate}%` : "off"}</em>
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="live-seq-step-body">
        {shown.subject && (
          <div className="seq-preview-subject"><small>Subject</small><Copy text={shown.subject} /></div>
        )}
        <Copy text={shown.body || "This step has no body text on the platform."} />
        {senderName && <div className="live-seq-sign">Kind regards,<br />{senderName}</div>}
      </div>

      {(shown.sent > 0 || shown.replies > 0) && (
        <footer className="live-seq-step-foot">
          <span>{shown.sent.toLocaleString()} sent</span>
          <span>{shown.replies.toLocaleString()} replied</span>
          <span className="live-seq-rate">{shown.reply_rate}% reply rate</span>
        </footer>
      )}
    </Card>
  );
}

function ReplyPanel({ behavior }) {
  if (!behavior) return null;
  const delayMin = Math.round((behavior.reply_delay_seconds || 0) / 60);
  const types = behavior.response_types || [];
  const fups = behavior.followups || [];

  return (
    <div className="live-seq-side">
      <Card className="live-seq-panel">
        <h3><MessageSquareReply size={15} /> When someone replies</h3>
        <p className="live-seq-panel-hint">
          A reply stops the sequence. What happens next depends on what they said.
        </p>
        <div className="live-seq-kv">
          <span><Clock size={13} /> Reply delay</span>
          <b>{delayMin ? `${delayMin} min` : "immediate"}</b>
        </div>
        <div className="live-seq-kv">
          <span><ShieldCheck size={13} /> Sending</span>
          <b>{behavior.auto_send_enabled ? "Automatic on confident matches" : "Reviewed by a human first"}</b>
        </div>
        {types.length > 0 && (
          <ul className="live-seq-list">
            {types.map((t) => (
              <li key={t.id}>
                <b>{(t.id || "").replace(/_/g, " ") || "Reply type"}</b>
                {t.auto_send && <span className="live-seq-auto">auto</span>}
                {t.intent && <em>{t.intent}</em>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="live-seq-panel">
        <h3><Zap size={15} /> If they stay quiet</h3>
        <p className="live-seq-panel-hint">
          {fups.length
            ? `${plural(fups.length, "nudge")}, written fresh for each prospect — never the same twice.`
            : "No follow-up ladder is configured yet."}
        </p>
        {fups.length > 0 && (
          <ol className="live-seq-list numbered">
            {fups.map((f, i) => (
              <li key={i}>
                <b>{f.label}</b>
                {f.max_words ? <span className="live-seq-words">≤ {f.max_words} words</span> : null}
                {f.intent && <em>{f.intent}</em>}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

export default function LiveSequences() {
  const { wsParam, me } = useAuth();
  const workspaceId = wsParam || me?.workspaces?.[0]?.id;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(0);

  const load = () => {
    if (!workspaceId) return;
    api("/api/reply/live-sequence", { params: { workspace_id: workspaceId } })
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e.message));
  };
  useEffect(load, [workspaceId]);

  // Operators can force a pull; clients read whatever the hourly worker last
  // mirrored. Refresh spends a third-party rate limit, so it is not theirs.
  const refresh = async () => {
    setBusy(true);
    try {
      await api("/api/reply/live-sequence/refresh", { method: "POST", params: { workspace_id: workspaceId } });
      load();
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  if (error) return <ErrorBox msg={error} retry={load} />;
  if (!data) return <Spinner />;

  const campaigns = data.campaigns || [];
  const current = campaigns[selected] || campaigns[0];
  const isClient = me?.role === "client";

  return (
    <div className="live-seq">
      <div className="seq-page-title">
        <div>
          <span className="seq-page-icon"><Mail size={19} /></span>
          <div>
            <h1>Email Sequences</h1>
            <p>Exactly what is going out, read live from your sending platform.</p>
          </div>
        </div>
        <div className="live-seq-head-right">
          {current?.fetched_at && <span>Updated {relTime(current.fetched_at)}</span>}
          {!isClient && (
            <button type="button" className="btn ghost sm" disabled={busy} onClick={refresh}>
              <RefreshCw size={14} className={busy ? "spin" : ""} /> {busy ? "Refreshing…" : "Refresh"}
            </button>
          )}
        </div>
      </div>

      {!isClient && (data.needs_mapping || []).length > 0 && (
        <div className="live-seq-warn">
          Some fields could not be read from {data.platform || "the platform"}:{" "}
          <b>{data.needs_mapping.join(", ")}</b>. Correct <code>FIELDS</code> in{" "}
          <code>app/reply/campaigns.py</code> against a real payload.
        </div>
      )}

      {!data.configured || !campaigns.length ? (
        <EmptyState
          icon={Inbox}
          title={data.configured ? "Nothing mirrored yet" : "No sending platform connected"}
          hint={data.configured
            ? "Your sequences will appear here once the first campaign is pulled from the platform."
            : "Once your outreach account is connected, every live sequence shows up here automatically."} />
      ) : (
        <div className="seq-shell">
          <aside className="seq-list">
            <div className="seq-list-head"><b>SEQUENCES</b></div>
            {campaigns.map((c, i) => {
              const steps = (c.steps || []).length;
              const variants = (c.steps || []).reduce((n, s) => n + (s.variants || []).length, 0);
              const stats = c.stats || {};
              return (
                <button key={`${c.id}-${i}`} type="button" className={i === selected ? "on" : ""}
                        onClick={() => setSelected(i)}>
                  <span className="seq-list-mark">{String.fromCharCode(65 + i)}</span>
                  <span>
                    <b>{c.name}</b>
                    <em>
                      {plural(steps, "step")} · {plural(variants, "variant")}
                      {stats.sent ? ` · ${stats.sent.toLocaleString()} sent · ${stats.reply_rate}% reply` : ""}
                    </em>
                  </span>
                  <StatusPill tone={STATUS_TONE[c.status] || "gray"}>
                    {STATUS_LABEL[c.status] || c.status}
                  </StatusPill>
                </button>
              );
            })}
          </aside>

          <div className="seq-main">
            {current?.fetch_status === "error" && (
              <div className="live-seq-warn">
                This sequence could not be refreshed{current.fetch_error ? `: ${current.fetch_error}` : ""}.
                Showing the last successful read.
              </div>
            )}

            <div className="live-seq-note">
              <Sparkles size={15} />
              <span>
                <b>This is what will send.</b> Highlighted text is written per prospect from real
                research — never the same twice. This view is read-only; it mirrors your sending
                platform, so it always matches what lands in an inbox.
              </span>
            </div>

            <div className="live-seq-grid">
              <div className="live-seq-steps">
                {(current?.steps || []).map((step, i) => (
                  <div key={step.position}>
                    {i > 0 && (
                      <div className="seq-wait">
                        <span />Wait <b>{step.wait_days}</b> {step.wait_days === 1 ? "day" : "days"}<span />
                      </div>
                    )}
                    <StepCard step={step} senderName={data.behavior?.sender_name} />
                  </div>
                ))}
                {!(current?.steps || []).length && (
                  <EmptyState icon={Mail} title="No steps read yet"
                              hint="The platform returned this campaign without a sequence ladder." />
                )}
              </div>
              <ReplyPanel behavior={data.behavior} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
