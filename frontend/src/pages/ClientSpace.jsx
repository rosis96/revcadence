/*
 * Client Space (Outbound) — a client-facing workspace that opens as a full-screen
 * takeover from inside the Outbound section. Additive only: this file is new and
 * nothing existing is modified except one nav entry and one route in App.jsx.
 *
 * It reuses the system design tokens (CSS custom properties from styles.css) and
 * shared components (Metric, Select, StatusBadge, btn classes), so it inherits the
 * app fonts (Inter / Montserrat) and light/dark theme automatically. Data here is
 * placeholder for the prototype; wiring to the real API is a follow-up.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Home, CalendarClock, Target, Mail, FileText, Rows3, Sparkles, ArrowLeft,
  Share2, Plus, ChevronDown,
} from "lucide-react";
import { Metric, StatusBadge, Select, notify } from "../components";

/* ---------- date engine ---------- */
const addDays = (iso, n) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return d; };
const addMonths = (iso, n) => { const d = new Date(iso + "T00:00:00"); d.setMonth(d.getMonth() + n); return d; };
const fmt = (d) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/* ---------- placeholder data ---------- */
const SEED_SEQUENCE = [
  { type: "email", subject: "Quick idea for {{company}}", body: "Hi {{first_name}},\n\nNoticed {{company}} is investing in {{signal}}. We help teams like yours turn that into qualified pipeline without adding headcount.\n\nWorth a short conversation this week?\n\nBest,\nRosis" },
  { type: "wait", days: 3 },
  { type: "email", subject: "Re: Quick idea for {{company}}", body: "Hi {{first_name}},\n\nA quick example of what this looks like in practice — happy to share a 90-second walkthrough of a recent campaign.\n\nOpen to it?\n\nRosis" },
  { type: "wait", days: 4 },
  { type: "email", subject: "Last note, {{first_name}}", body: "Hi {{first_name}},\n\nI'll leave this here for now. If reaching more of the right accounts is a priority this quarter, I'm around.\n\nRosis" },
];
const SEED_LEADS = [
  { name: "Marcus Lee", company: "Nebula Robotics", title: "VP Marketing", email: "marcus@nebula.io", date: "2026-08-26", status: "Booked", conv: [["us", "Personalized opener referencing their new brand hire."], ["them", "Interested — what does onboarding look like?"], ["us", "Shared an overview, proposed a call."]] },
  { name: "Dana Cruz", company: "Gomora Health", title: "Head of Growth", email: "dana@gomora.co", date: "2026-08-27", status: "Meeting completed", conv: [["us", "Opener tied to their Series B."], ["them", "Yes, let's talk. Booked a slot."], ["us", "Call done — sending proposal."]] },
  { name: "Priya N.", company: "Starlord Labs", title: "CMO", email: "priya@starlord.ai", date: "2026-08-28", status: "No-show", conv: [["us", "Reached out on the open-CMO-role signal."], ["them", "Booked a slot."], ["us", "No-show — following up to reschedule."]] },
  { name: "Tom Vega", company: "Groot Interactive", title: "Founder", email: "tom@groot.dev", date: "2026-08-29", status: "Booked", conv: [["us", "Opener referencing recent funding."], ["them", "Curious, sent times."]] },
];
const STATUS_TONE = { "Booked": "blue", "Meeting completed": "green", "No-show": "red", "Rescheduled": "amber", "Lost": "gray" };
const DOCS = [
  { icon: "📄", title: "Engagement Agreement", meta: "Signed · Aug 1, 2026", key: "agreement" },
  { icon: "🎯", title: "Positioning & ICP", meta: "Updated Aug 4, 2026", key: "positioning" },
  { icon: "🧭", title: "The Concept (how we work)", meta: "Updated Aug 2, 2026", key: "concept" },
  { icon: "📊", title: "Targets & List", meta: "Updated weekly", key: "targets" },
];

const NAV = [
  ["home", "Home", Home], ["planner", "Planner", CalendarClock], ["plan", "Plan & targets", Target],
  ["sequences", "Sequences", Mail], ["docs", "Docs", FileText], ["pipeline", "Pipeline", Rows3], ["report", "AI report", Sparkles],
];

export default function ClientSpace() {
  const nav = useNavigate();
  const [view, setView] = useState("home");
  const [startDate, setStartDate] = useState("2026-08-01");
  const [sequence, setSequence] = useState(SEED_SEQUENCE);
  const [active, setActive] = useState(0);
  const [preview, setPreview] = useState(false);
  const [leads, setLeads] = useState(SEED_LEADS);
  const [docOpen, setDocOpen] = useState(0);
  const [openRow, setOpenRow] = useState(-1);
  const [report, setReport] = useState("");
  const [share, setShare] = useState(false);

  const ms = useMemo(() => ({
    infra: new Date(startDate + "T00:00:00"),
    launch: addDays(startDate, 21),
    results: addDays(startDate, 28),
    invoice: addMonths(startDate, 1),
  }), [startDate]);

  const setStatus = (i, v) => setLeads((ls) => ls.map((l, k) => k === i ? { ...l, status: v } : l));
  const saveSeq = (subject, body) => { setSequence((s) => s.map((st, i) => i === active ? { ...st, subject, body } : st)); notify("Sequence saved", "ok"); };
  const genReport = () => {
    setReport("Generating…");
    setTimeout(() => {
      const done = leads.filter((l) => l.status === "Meeting completed").length;
      const ns = leads.filter((l) => l.status === "No-show").length;
      setReport(
`Future Works — Outbound performance (as of ${fmt(new Date())})

Targeting
• Segment: Robotics & AI, mid-market
• Total addressable market: 2,840 accounts
• Hand-picked this phase: 180 accounts

Activity
• Campaigns launched: ${fmt(ms.launch)}
• Meetings booked: ${leads.length}   Completed: ${done}   No-shows: ${ns}

What is working
• Signal-led openers (funding, brand hires) drive the strongest replies.
• Personalized first lines outperform generic intros.

Next
• Continue the robotics segment; add an angle for AI-infrastructure accounts.
• Next invoice: ${fmt(ms.invoice)}.

Draft generated from live campaign data. Review before sending.`);
    }, 650);
  };

  return (
    <div className="cw-root">
      <style>{CW_CSS}</style>

      {/* top bar */}
      <div className="cw-top">
        <button className="btn ghost sm" onClick={() => nav("/enrichment")}><ArrowLeft size={15} /> Back to Outbound</button>
        <div className="cw-ws"><span className="cw-avatar">FW</span> Future Works <span className="cw-dim">/ Client Space</span></div>
        <span className="cw-badge">Client view</span>
        <div className="cw-search">Search this workspace…</div>
        <button className="btn sm" onClick={() => setShare(true)}><Share2 size={14} /> Share</button>
      </div>

      <div className="cw-body">
        {/* icon rail */}
        <div className="cw-rail">
          {NAV.map(([id, label, Icon]) => (
            <button key={id} className={`cw-ir ${view === id ? "on" : ""}`} title={label} onClick={() => setView(id)}><Icon size={18} /></button>
          ))}
        </div>

        {/* sidebar */}
        <div className="cw-side">
          <div className="cw-sidehead"><span className="cw-avatar sm">FW</span> Future Works</div>
          {NAV.map(([id, label, Icon]) => (
            <button key={id} className={`cw-nav ${view === id ? "on" : ""}`} onClick={() => setView(id)}>
              <Icon size={16} /> {label}
              {id === "pipeline" && <span className="cw-ct">{leads.length}</span>}
            </button>
          ))}
          <div className="cw-sec">Shared with me</div>
          {DOCS.map((d, i) => (
            <button key={d.key} className="cw-doc" onClick={() => { setDocOpen(i); setView("docs"); }}><span>{d.icon}</span> {d.title}</button>
          ))}
        </div>

        {/* main */}
        <div className="cw-main">
          <div className="cw-title">{NAV.find(([id]) => id === view)[1]}</div>

          {view === "home" && <HomeView ms={ms} startDate={startDate} setStartDate={setStartDate} leads={leads} />}
          {view === "planner" && <PlannerView ms={ms} startDate={startDate} />}
          {view === "plan" && <PlanView />}
          {view === "sequences" && <SeqView sequence={sequence} active={active} setActive={setActive} preview={preview} setPreview={setPreview} onSave={saveSeq} onAdd={() => { setSequence((s) => [...s, { type: "wait", days: 3 }, { type: "email", subject: "New follow-up", body: "Hi {{first_name}},\n\n" }]); }} />}
          {view === "docs" && <DocsView docOpen={docOpen} setDocOpen={setDocOpen} />}
          {view === "pipeline" && <PipeView leads={leads} setStatus={setStatus} openRow={openRow} setOpenRow={setOpenRow} />}
          {view === "report" && <ReportView report={report} onGen={genReport} onPush={(w) => notify(w === "slack" ? "Report posted to #future-works" : "Report emailed to the client", "ok")} />}
        </div>
      </div>

      {share && (
        <div className="cw-ov" onMouseDown={(e) => e.target === e.currentTarget && setShare(false)}>
          <div className="cw-modal">
            <div className="cw-mh">Share with Future Works</div>
            <div className="cw-mb">
              <p className="cw-dim2">Choose exactly what the client can see. For clients, expose only the Client Space.</p>
              <ShareRow label="Client Space" sub="Home, Planner, Plan, Sequences, Docs, Pipeline, AI report" on locked={false} />
              <ShareRow label="Outbound (internal)" sub="Lists, campaigns, raw data" locked />
              <ShareRow label="CRM (internal)" sub="Full contact database" locked />
              <ShareRow label="Reply / Inbox (internal)" sub="Live mailboxes" locked />
            </div>
            <div className="cw-mf">
              <button className="btn ghost" onClick={() => setShare(false)}>Cancel</button>
              <button className="btn" onClick={() => { setShare(false); notify("Invite sent · client sees only the Client Space", "ok"); }}>Send invite</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- views ---------- */
function HomeView({ ms, startDate, setStartDate, leads }) {
  const now = new Date();
  const steps = [
    { k: "Step 1", t: "Cold email infrastructure", d: "Domains, inboxes, warm-up", date: ms.infra, next: ms.launch },
    { k: "Step 2", t: "Launch outreach", d: "Campaigns go live", date: ms.launch, next: ms.results },
    { k: "Step 3", t: "First results", d: "Replies and meetings begin", date: ms.results, next: ms.invoice },
    { k: "Step 4", t: "Manage pipeline", d: "Qualify, book, follow up", date: ms.results, next: addDays(startDate, 999) },
  ];
  return (
    <>
      <div className="metrics cw-g4">
        <Metric icon={<Target size={14} />} label="TAM" value="2,840" sub="reachable accounts" />
        <Metric icon={<Rows3 size={14} />} label="List this phase" value="180" sub="hand-picked accounts" />
        <Metric icon={<CalendarClock size={14} />} label="Meetings booked" value={String(leads.length)} sub="this pilot" />
        <Metric icon={<FileText size={14} />} label="Next invoice" value={fmt(ms.invoice)} sub="$3,000 · monthly" />
      </div>

      <div className="cw-sech">Roadmap to results</div>
      <div className="card">
        <div className="cw-daterow">
          <b>Pilot start date</b>
          <input type="date" className="cw-date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <span className="cw-dim2">Everything recalculates: launch is start + 21 days, first results a week later, next invoice one month on.</span>
        </div>
        <div className="cw-road">
          {steps.map((s, i) => {
            const done = now >= s.next;
            const nowStep = !done && now >= s.date;
            const tone = done ? "green" : nowStep ? "blue" : "gray";
            const txt = done ? "Done" : nowStep ? "In progress" : "Upcoming";
            return (
              <div key={i} className="cw-rstep">
                <div className={`cw-bar ${done ? "done" : nowStep ? "now" : ""}`} />
                <div className="cw-rk">{s.k}</div>
                <div className="cw-rt">{s.t}</div>
                <div className="cw-rd">{s.d}<br />{fmt(s.date)}</div>
                <div style={{ marginTop: 8 }}><StatusBadge tone={tone}>{txt}</StatusBadge></div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="cw-sech">What this means for you</div>
      <div className="card cw-prose">
        We set up dedicated cold-email infrastructure first so your domain stays safe. Around <b>{fmt(ms.launch)}</b> campaigns launch. You should start seeing replies and meetings roughly a week later, around <b>{fmt(ms.results)}</b>. From there it is about managing the pipeline of the right conversations. A realistic timeline, not an overnight switch.
      </div>
    </>
  );
}

function PlannerView({ ms, startDate }) {
  const now = new Date();
  const rows = [
    { when: fmt(ms.infra), what: "Infrastructure setup begins", desc: "Domains, inboxes, warm-up started", date: ms.infra },
    { when: fmt(addDays(startDate, 7)), what: "ICP & list approved", desc: "Hand-picked target accounts confirmed with you", date: addDays(startDate, 7) },
    { when: fmt(addDays(startDate, 14)), what: "Sequences drafted & approved", desc: "You review every email before it sends", date: addDays(startDate, 14) },
    { when: fmt(ms.launch), what: "Campaigns launch", desc: "Outreach goes live to the approved list", date: ms.launch },
    { when: fmt(ms.results), what: "First replies & meetings", desc: "Qualified conversations start landing", date: ms.results },
    { when: "Ongoing", what: "Pipeline management", desc: "Qualify, book, follow up, optimize", date: addDays(startDate, 60) },
  ];
  return (
    <div className="cw-tline">
      {rows.map((r, i) => (
        <div key={i} className={`cw-tl ${now >= r.date ? "done" : ""}`}>
          <div className="cw-tw">{r.when}</div>
          <div className="cw-twh">{r.what}</div>
          <div className="cw-td">{r.desc}</div>
        </div>
      ))}
    </div>
  );
}

function PlanView() {
  return (
    <>
      <div className="metrics cw-g3">
        <Metric icon={<Target size={14} />} label="Total addressable" value="2,840" sub="accounts matching your ICP" />
        <Metric icon={<Rows3 size={14} />} label="Selected this phase" value="180" sub="hand-picked, approved by you" />
        <Metric label="Segment" value="Robotics & AI" sub="mid-market, actively hiring" />
      </div>
      <div className="cw-sech">The 3-month plan</div>
      <div className="cw-g3" style={{ display: "grid", gap: 16 }}>
        <div className="card"><b>Month 1</b><p className="cw-p">Infrastructure, list, and messaging. Launch to the first approved segment. Learn what lands.</p></div>
        <div className="card"><b>Month 2</b><p className="cw-p">Double down on the segments and angles that respond. Add a second angle if warranted.</p></div>
        <div className="card"><b>Month 3</b><p className="cw-p">Steady pipeline of qualified conversations. Review and decide whether to widen.</p></div>
      </div>
      <div className="cw-sech">How outreach is performed</div>
      <div className="card cw-prose">
        Every account is researched and verified before contact. Emails are personalized to a real signal (funding, hiring, a launch). The first email stays lightweight for deliverability; later steps can carry a visual. Replies are handled by a human, qualified, and only booked when the fit is real. You approve the list and the messaging before anything sends.
      </div>
    </>
  );
}

function SeqView({ sequence, active, setActive, preview, setPreview, onSave, onAdd }) {
  const st = sequence[active];
  const [subject, setSubject] = useState(st?.subject || "");
  const [body, setBody] = useState(st?.body || "");
  // keep local editor in sync when switching steps
  useEffect(() => { setSubject(sequence[active]?.subject || ""); setBody(sequence[active]?.body || ""); }, [active, sequence]);
  const fill = (s) => (s || "").replace(/{{first_name}}/g, "Marcus").replace(/{{company}}/g, "Nebula Robotics").replace(/{{signal}}/g, "a new brand hire").replace(/{{title}}/g, "VP Marketing");
  let emailNo = 0;
  return (
    <div className="cw-seq">
      <div className="cw-seqrail">
        {sequence.map((s, i) => {
          if (s.type === "wait") return <div key={i} className="cw-wait"><ChevronDown size={13} /> wait {s.days} day{s.days > 1 ? "s" : ""}</div>;
          emailNo++;
          return (
            <button key={i} className={`cw-step ${i === active ? "on" : ""}`} onClick={() => { setActive(i); setPreview(false); }}>
              <div className="cw-stepn">Email {emailNo}</div>
              <div className="cw-steps">{s.subject || "(no subject)"}</div>
              <div className="cw-stepm">{(s.body || "").split("\n")[0]}</div>
            </button>
          );
        })}
        <button className="btn ghost sm" style={{ width: "100%", marginTop: 6 }} onClick={onAdd}><Plus size={14} /> Add step</button>
      </div>
      <div className="cw-seqedit">
        {st?.type !== "email" ? <div className="cw-dim2">Select an email step.</div> : preview ? (
          <>
            <div className="cw-editbar"><b>Preview</b><button className="btn ghost sm" onClick={() => setPreview(false)}>← Edit</button></div>
            <div className="cw-preview">
              <div className="cw-ph"><b>Subject:</b> {fill(subject)}</div>
              <div className="cw-pb">{fill(body)}</div>
            </div>
            <p className="cw-dim2" style={{ marginTop: 12 }}>Preview uses sample values so the client sees exactly what a prospect receives.</p>
          </>
        ) : (
          <>
            <div className="cw-editbar">
              <b>Edit email</b>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn ghost sm" onClick={() => setPreview(true)}>Preview</button>
                <button className="btn sm" onClick={() => onSave(subject, body)}>Save</button>
              </div>
            </div>
            <div className="cw-vars">
              {["{{first_name}}", "{{company}}", "{{signal}}", "{{title}}"].map((v) => (
                <button key={v} className="cw-var" onClick={() => setBody((b) => b + v)}>{v}</button>
              ))}
            </div>
            <label className="cw-flabel">Subject</label>
            <input className="cw-input" value={subject} onChange={(e) => setSubject(e.target.value)} />
            <label className="cw-flabel" style={{ marginTop: 12 }}>Body</label>
            <textarea className="cw-input cw-area" value={body} onChange={(e) => setBody(e.target.value)} />
          </>
        )}
      </div>
    </div>
  );
}

const DOC_BODY = {
  agreement: (
    <>
      <p className="cw-p">This documents the engagement between RevCadence and Future Works, kept here so everything lives in one place.</p>
      <div className="cw-kv">
        <div><span className="k">Engagement</span><span className="v">Outbound growth pilot</span></div>
        <div><span className="k">Term</span><span className="v">3 months, rolling</span></div>
        <div><span className="k">Investment</span><span className="v">$3,000 / month</span></div>
        <div><span className="k">Start date</span><span className="v">August 1, 2026</span></div>
      </div>
      <div className="cw-callout">The signed PDF is attached in the Docs sidebar. This page is the plain-language summary.</div>
    </>
  ),
  positioning: (
    <>
      <h2 className="cw-h2">Who we are reaching for you</h2>
      <p className="cw-p">Mid-market robotics and AI companies showing signs of brand and growth investment.</p>
      <ul className="cw-ul"><li>Actively hiring for brand, growth, or marketing roles</li><li>Recent funding or strong revenue signals</li><li>Decision-makers: VP Marketing, Head of Growth, CMO, founder</li></ul>
      <h2 className="cw-h2">The message</h2>
      <p className="cw-p">We lead with a real, specific reason to talk, tied to a signal. No free-audit bait. The work and the relevance do the selling.</p>
    </>
  ),
  concept: (
    <>
      <h2 className="cw-h2">How the engine works</h2>
      <ul className="cw-ul"><li><b>Infrastructure first.</b> Dedicated domains and inboxes, warmed for ~3 weeks, so your main domain is never at risk.</li><li><b>Personalized outreach.</b> Every email is researched and human-reviewed.</li><li><b>Reply management.</b> A person handles replies and qualifies before booking.</li><li><b>Pipeline.</b> Booked meetings, statuses, and full context in one table.</li></ul>
      <div className="cw-callout">You always approve the list and the messaging before anything sends.</div>
    </>
  ),
  targets: (
    <>
      <h2 className="cw-h2">Targets & list</h2>
      <div className="cw-kv">
        <div><span className="k">Total addressable (TAM)</span><span className="v">2,840 accounts</span></div>
        <div><span className="k">Selected this phase</span><span className="v">180 hand-picked</span></div>
        <div><span className="k">Segment</span><span className="v">Robotics & AI, mid-market</span></div>
        <div><span className="k">Meetings booked</span><span className="v">4 so far</span></div>
      </div>
      <p className="cw-p">The full list is reviewed with you before launch and updated as we learn what responds.</p>
    </>
  ),
};
function DocsView({ docOpen, setDocOpen }) {
  const d = DOCS[docOpen];
  return (
    <>
      <div className="cw-doctabs">
        {DOCS.map((doc, i) => (
          <button key={doc.key} className={`btn ${i === docOpen ? "" : "ghost"} sm`} onClick={() => setDocOpen(i)}>{doc.icon} {doc.title}</button>
        ))}
      </div>
      <div className="cw-doc">
        <div className="cw-dicon">{d.icon}</div>
        <h1 className="cw-h1">{d.title}</h1>
        <div className="cw-dmeta">{d.meta}</div>
        {DOC_BODY[d.key]}
      </div>
    </>
  );
}

function PipeView({ leads, setStatus, openRow, setOpenRow }) {
  return (
    <>
      <p className="cw-dim2" style={{ margin: "0 0 14px" }}>Only booked meetings appear here. Change a status with the dropdown, like a sheet. Click a row for full lead info and the conversation.</p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table className="cw-tbl">
          <thead><tr><th>Lead</th><th>Email</th><th>Meeting date</th><th>Status</th><th>Update</th></tr></thead>
          <tbody>
            {leads.map((l, i) => (
              <FragmentRow key={i} l={l} i={i} open={openRow === i} onToggle={() => setOpenRow(openRow === i ? -1 : i)} setStatus={setStatus} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
function FragmentRow({ l, i, open, onToggle, setStatus }) {
  return (
    <>
      <tr className="cw-lead" onClick={onToggle}>
        <td><div className="cw-lb">{l.name}</div><div className="cw-ls">{l.title} · {l.company}</div></td>
        <td>{l.email}</td>
        <td>{fmt(new Date(l.date + "T00:00:00"))}</td>
        <td><StatusBadge tone={STATUS_TONE[l.status] || "gray"}>{l.status}</StatusBadge></td>
        <td onClick={(e) => e.stopPropagation()} style={{ maxWidth: 190 }}>
          <Select value={l.status} onChange={(e) => setStatus(i, e.target.value)}>
            <option>Booked</option><option>Meeting completed</option><option>No-show</option><option>Rescheduled</option><option>Lost</option>
          </Select>
        </td>
      </tr>
      {open && (
        <tr className="cw-conv"><td colSpan={5}>
          <div className="cw-convgrid">
            <div>
              <div className="cw-convh">Lead info</div>
              <div className="cw-kv">
                <div><span className="k">Name</span><span className="v">{l.name}</span></div>
                <div><span className="k">Title</span><span className="v">{l.title}</span></div>
                <div><span className="k">Company</span><span className="v">{l.company}</span></div>
                <div><span className="k">Email</span><span className="v">{l.email}</span></div>
                <div><span className="k">Meeting</span><span className="v">{fmt(new Date(l.date + "T00:00:00"))}</span></div>
              </div>
            </div>
            <div>
              <div className="cw-convh">Conversation</div>
              {l.conv.map((c, k) => (
                <div key={k} className={`cw-bubble ${c[0] === "them" ? "them" : ""}`}>
                  <div className="cw-who">{c[0] === "them" ? l.name : "RevCadence"}</div>{c[1]}
                </div>
              ))}
            </div>
          </div>
        </td></tr>
      )}
    </>
  );
}

function ReportView({ report, onGen, onPush }) {
  return (
    <>
      <p className="cw-dim2" style={{ margin: "0 0 14px" }}>Generate a plain-language performance report from what we have done, then push it to Slack and email.</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <button className="btn" onClick={onGen}><Sparkles size={14} /> Generate report</button>
        <button className="btn ghost" onClick={() => onPush("slack")}>Send to Slack</button>
        <button className="btn ghost" onClick={() => onPush("email")}>Send via email</button>
      </div>
      <div className="cw-report">{report || "Click Generate report to draft this month's summary from the campaign data."}</div>
    </>
  );
}

function ShareRow({ label, sub, on = false, locked }) {
  const [v, setV] = useState(on);
  return (
    <div className="cw-shrow">
      <div style={{ flex: 1 }}><b>{label}</b><div className="cw-dim2">{sub}</div></div>
      <button className={`cw-sw ${v ? "on" : ""} ${locked ? "lock" : ""}`} onClick={() => !locked && setV(!v)}><i /></button>
    </div>
  );
}

/* ---------- scoped styles: all reference the system tokens, so fonts + light/dark come for free ---------- */
const CW_CSS = `
.cw-root{position:fixed;inset:0;z-index:50;background:var(--bg);color:var(--text);display:flex;flex-direction:column;font-family:inherit}
.cw-top{height:52px;flex:none;display:flex;align-items:center;gap:12px;padding:0 14px;background:var(--sidebar-bg);border-bottom:1px solid var(--border)}
.cw-ws{display:flex;align-items:center;gap:8px;font-weight:700}
.cw-dim{color:var(--muted);font-weight:500}
.cw-avatar{width:22px;height:22px;border-radius:6px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700}
.cw-avatar.sm{width:20px;height:20px;font-size:10px}
.cw-badge{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);background:var(--accent-soft);padding:4px 9px;border-radius:6px}
.cw-search{flex:1;max-width:400px;margin:0 auto;background:var(--topbar-control);border:1px solid var(--border);border-radius:8px;padding:7px 12px;color:var(--muted);font-size:12.5px}
.cw-body{flex:1;display:flex;min-height:0}
.cw-rail{width:54px;flex:none;background:var(--sidebar-elevated);border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:center;padding:10px 0;gap:4px}
.cw-ir{width:36px;height:36px;border-radius:9px;border:0;background:transparent;color:var(--sidebar-text);display:flex;align-items:center;justify-content:center;cursor:pointer}
.cw-ir:hover{background:var(--sidebar-hover);color:var(--sidebar-text-active)}
.cw-ir.on{background:var(--accent);color:#fff}
.cw-side{width:236px;flex:none;background:var(--sidebar-bg);border-right:1px solid var(--border);overflow:auto;padding:12px 10px}
.cw-sidehead{display:flex;align-items:center;gap:8px;font-weight:700;font-size:14px;padding:4px 8px 12px}
.cw-nav{display:flex;align-items:center;gap:10px;width:100%;text-align:left;border:0;background:transparent;padding:8px 10px;border-radius:8px;color:var(--sidebar-text);font-weight:600;font-size:13.5px;cursor:pointer}
.cw-nav:hover{background:var(--sidebar-hover);color:var(--sidebar-text-active)}
.cw-nav.on{background:var(--sidebar-active);color:var(--sidebar-text-active)}
.cw-ct{margin-left:auto;font-size:11px;color:var(--muted);font-weight:700}
.cw-sec{font-size:10.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:16px 10px 6px}
.cw-doc{display:flex;align-items:center;gap:9px;width:100%;text-align:left;border:0;background:transparent;padding:7px 10px;border-radius:8px;color:var(--sidebar-text);font-size:13px;cursor:pointer}
.cw-doc:hover{background:var(--sidebar-hover);color:var(--sidebar-text-active)}
.cw-main{flex:1;overflow:auto;padding:22px 30px 60px;min-width:0}
.cw-title{font-size:22px;font-weight:800;letter-spacing:-.02em;margin-bottom:18px}
.cw-sech{font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:26px 0 12px}
.cw-g4{grid-template-columns:repeat(4,1fr)} .cw-g3{grid-template-columns:repeat(3,1fr)}
.cw-prose{line-height:1.7;color:var(--text)}
.cw-p{color:var(--muted);line-height:1.65;margin:8px 0}
.cw-daterow{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.cw-date{border:1px solid var(--border-strong);border-radius:8px;padding:7px 10px;font-family:inherit;background:var(--card);color:var(--text)}
.cw-dim2{color:var(--muted);font-size:12.5px}
.cw-road{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.cw-bar{height:6px;border-radius:6px;background:var(--progress-track)}
.cw-bar.done{background:var(--ok)} .cw-bar.now{background:var(--accent)}
.cw-rk{font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-top:10px}
.cw-rt{font-weight:700;margin-top:3px} .cw-rd{color:var(--muted);font-size:12.5px;margin-top:2px}
.cw-tline{border-left:2px solid var(--border);margin-left:8px}
.cw-tl{position:relative;padding:0 0 20px 24px}
.cw-tl::before{content:"";position:absolute;left:-7px;top:2px;width:12px;height:12px;border-radius:50%;background:var(--card);border:2px solid var(--border-strong)}
.cw-tl.done::before{background:var(--ok);border-color:var(--ok)}
.cw-tw{font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.cw-twh{font-weight:700;margin-top:2px} .cw-td{color:var(--muted);font-size:12.5px;margin-top:2px}
.cw-seq{display:grid;grid-template-columns:230px 1fr;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;min-height:440px}
.cw-seqrail{background:var(--sidebar-elevated);border-right:1px solid var(--border);padding:14px}
.cw-step{display:block;width:100%;text-align:left;background:var(--card);border:1px solid var(--border);border-radius:9px;padding:10px 12px;margin-bottom:8px;cursor:pointer}
.cw-step.on{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft)}
.cw-stepn{font-size:11px;font-weight:800;color:var(--accent);text-transform:uppercase;letter-spacing:.04em}
.cw-steps{font-weight:700;margin-top:2px;font-size:13px}
.cw-stepm{color:var(--muted);font-size:11.5px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cw-wait{text-align:center;color:var(--muted);font-size:11.5px;font-weight:700;margin:0 0 8px;display:flex;align-items:center;justify-content:center;gap:4px}
.cw-seqedit{padding:18px 20px}
.cw-editbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;font-size:15px}
.cw-vars{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.cw-var{font-size:11px;font-weight:700;background:var(--accent-soft);color:var(--accent);border:1px solid var(--accent-border);border-radius:6px;padding:3px 8px;cursor:pointer}
.cw-flabel{display:block;font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:5px}
.cw-input{width:100%;border:1px solid var(--border-strong);border-radius:8px;padding:9px 11px;font-family:inherit;font-size:13px;color:var(--text);background:var(--card)}
.cw-area{min-height:190px;resize:vertical;line-height:1.5}
.cw-preview{border:1px solid var(--border);border-radius:10px;overflow:hidden}
.cw-ph{background:var(--sidebar-elevated);border-bottom:1px solid var(--border);padding:10px 14px;font-size:12.5px}
.cw-pb{padding:16px 18px;font-size:13.5px;line-height:1.6;white-space:pre-wrap}
.cw-doctabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.cw-doc-wrap{}
.cw-dicon{font-size:38px} .cw-h1{font-size:28px;font-weight:800;letter-spacing:-.02em;margin:8px 0 4px}
.cw-dmeta{color:var(--muted);font-size:12px;margin-bottom:20px} .cw-h2{font-size:18px;margin:22px 0 8px}
.cw-ul{margin:8px 0;padding-left:4px;list-style:none} .cw-ul li{position:relative;padding:4px 0 4px 22px;color:var(--muted);line-height:1.6}
.cw-ul li::before{content:"";position:absolute;left:6px;top:12px;width:5px;height:5px;border-radius:50%;background:var(--muted)}
.cw-callout{background:var(--accent-soft);border:1px solid var(--accent-border);border-radius:10px;padding:12px 14px;color:var(--text);margin:14px 0}
.cw-kv{border:1px solid var(--border);border-radius:10px;overflow:hidden;margin:12px 0}
.cw-kv>div{display:grid;grid-template-columns:190px 1fr;font-size:13px}.cw-kv>div+div{border-top:1px solid var(--border)}
.cw-kv .k{background:var(--sidebar-elevated);padding:9px 12px;font-weight:700;color:var(--text)}.cw-kv .v{padding:9px 12px;color:var(--muted)}
.cw-tbl{width:100%;border-collapse:collapse}
.cw-tbl th{text-align:left;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:800;padding:11px 14px;background:var(--sidebar-elevated);border-bottom:1px solid var(--border)}
.cw-tbl td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:13px;vertical-align:middle}
.cw-lead:hover{background:var(--hover-soft);cursor:pointer}
.cw-lb{font-weight:700}.cw-ls{color:var(--muted);font-size:12px}
.cw-conv td{background:var(--sidebar-elevated);border-top:1px dashed var(--border-strong)}
.cw-convgrid{display:grid;grid-template-columns:1fr 1.4fr;gap:20px;padding:6px 4px}
.cw-convh{font-weight:800;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.cw-bubble{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:8px;font-size:12.5px;max-width:78%}
.cw-bubble.them{margin-left:auto;background:var(--accent-soft);border-color:var(--accent-border)}
.cw-who{font-size:10.5px;font-weight:800;color:var(--muted);margin-bottom:3px;text-transform:uppercase;letter-spacing:.04em}
.cw-report{white-space:pre-wrap;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;font-size:13.5px;line-height:1.65;color:var(--muted);min-height:120px}
.cw-ov{position:fixed;inset:0;background:var(--overlay);display:flex;align-items:center;justify-content:center;z-index:60}
.cw-modal{background:var(--card);border-radius:14px;width:460px;max-width:92vw;overflow:hidden;border:1px solid var(--border)}
.cw-mh{padding:18px 20px;border-bottom:1px solid var(--border);font-weight:800;font-size:16px}
.cw-mb{padding:18px 20px}.cw-mf{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:8px}
.cw-shrow{display:flex;align-items:center;gap:11px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;margin-bottom:8px}
.cw-sw{width:38px;height:22px;border-radius:999px;background:var(--border-strong);position:relative;flex:none;cursor:pointer;border:0}
.cw-sw.on{background:var(--accent)} .cw-sw i{position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.15s}
.cw-sw.on i{left:18px} .cw-sw.lock{opacity:.5;cursor:not-allowed}
`;
