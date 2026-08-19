/*
 * Client Space (Outbound) — a client-facing workspace that opens as a full-screen
 * takeover from inside the Outbound section. Additive: this page is new; App.jsx
 * only gains a nav entry + route.
 *
 * Everything is editable and persists to localStorage so a client can actually use
 * it (add campaign angles, edit segments and docs like Notion, move planner dates).
 * Reuses the system design tokens + shared components so it inherits fonts + theme.
 * Data is local/placeholder pending API wiring.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Home, CalendarClock, Target, Mail, FileText, Rows3, Sparkles, ArrowLeft, ArrowRight,
  Share2, Plus, ChevronDown, MoreHorizontal, Copy, Trash2, Pencil, Bold, Heading2, List as ListIcon,
} from "lucide-react";
import { Metric, StatusBadge, Select, notify } from "../components";

/* ---------- persistence ---------- */
function useStored(key, initial) {
  const [v, setV] = useState(() => {
    try { const s = localStorage.getItem(key); return s ? JSON.parse(s) : initial; } catch { return initial; }
  });
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* storage disabled */ } }, [key, v]);
  return [v, setV];
}
const uid = () => Math.random().toString(36).slice(2, 9);

/* ---------- date helpers ---------- */
const addDays = (iso, n) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n); return d; };
const addMonths = (iso, n) => { const d = new Date(iso + "T00:00:00"); d.setMonth(d.getMonth() + n); return d; };
const fmt = (d) => (d instanceof Date ? d : new Date(d + "T00:00:00")).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

/* ---------- defaults ---------- */
const DEF_ANGLES = [
  { id: uid(), name: "Signal-led opener", steps: [
    { type: "email", subject: "Quick idea for {{company}}", body: "Hi {{first_name}},\n\nNoticed {{company}} is investing in {{signal}}. We help teams like yours turn that into qualified pipeline without adding headcount.\n\nWorth a short conversation this week?\n\nBest,\nRosis" },
    { type: "wait", days: 3 },
    { type: "email", subject: "Re: Quick idea for {{company}}", body: "Hi {{first_name}},\n\nA quick example of what this looks like in practice — happy to share a 90-second walkthrough of a recent campaign.\n\nOpen to it?\n\nRosis" },
    { type: "wait", days: 4 },
    { type: "email", subject: "Last note, {{first_name}}", body: "Hi {{first_name}},\n\nI'll leave this here for now. If reaching more of the right accounts is a priority this quarter, I'm around.\n\nRosis" },
  ] },
  { id: uid(), name: "Problem-first", steps: [
    { type: "email", subject: "The gap most {{title}}s miss", body: "Hi {{first_name}},\n\nMost teams at {{company}}'s stage lose good opportunities in follow-up, not in getting the first meeting. We fix that side.\n\nCurious if that resonates?\n\nRosis" },
    { type: "wait", days: 3 },
    { type: "email", subject: "Re: The gap", body: "Hi {{first_name}},\n\nSharing a short breakdown of how we close that gap for teams like yours.\n\nWorth 15 minutes?\n\nRosis" },
  ] },
];
const DEF_SEGMENTS = [
  { id: uid(), name: "Robotics & AI (primary)", icon: "🤖", html: "<h2>Robotics &amp; AI, mid-market</h2><p>Companies actively investing in brand and growth. Roughly $10M–$50M revenue, hiring for brand or marketing roles.</p><ul><li>Total addressable: ~2,840 accounts</li><li>Selected this phase: 180 hand-picked</li><li>Buyers: VP Marketing, Head of Growth, CMO, founder</li></ul><p>Edit this like a Notion page — headings, bullets, bold all work.</p>" },
  { id: uid(), name: "AI infrastructure (test)", icon: "🧪", html: "<h2>AI infrastructure</h2><p>A second angle to test in month 2. Well-funded accounts hiring demand-gen.</p>" },
];
const DEF_DOCS = [
  { id: uid(), icon: "📄", title: "Engagement Agreement", html: "<p>This documents the engagement between RevCadence and Future Works, kept here so everything lives in one place.</p><ul><li><b>Engagement:</b> Outbound growth pilot</li><li><b>Term:</b> 3 months, rolling</li><li><b>Investment:</b> $3,000 / month</li><li><b>Start date:</b> August 1, 2026</li></ul>" },
  { id: uid(), icon: "🎯", title: "Positioning & ICP", html: "<h2>Who we are reaching for you</h2><p>Mid-market robotics and AI companies showing signs of brand and growth investment.</p><ul><li>Actively hiring for brand, growth, or marketing roles</li><li>Recent funding or strong revenue signals</li><li>Decision-makers: VP Marketing, Head of Growth, CMO, founder</li></ul>" },
  { id: uid(), icon: "🧭", title: "The Concept (how we work)", html: "<h2>How the engine works</h2><ul><li><b>Infrastructure first.</b> Dedicated domains and inboxes, warmed ~3 weeks.</li><li><b>Personalized outreach,</b> human-reviewed.</li><li><b>Reply management</b> before booking.</li><li><b>Pipeline</b> with full context.</li></ul>" },
];
const DEF_PLANNER = (start) => [
  { id: uid(), date: start, title: "Infrastructure setup begins", desc: "Domains, inboxes, warm-up started", link: "plan" },
  { id: uid(), date: addDays(start, 7).toISOString().slice(0, 10), title: "ICP & list approved", desc: "Hand-picked target accounts confirmed with you", link: "plan" },
  { id: uid(), date: addDays(start, 14).toISOString().slice(0, 10), title: "Sequences drafted & approved", desc: "You review every email before it sends", link: "sequences" },
  { id: uid(), date: addDays(start, 21).toISOString().slice(0, 10), title: "Campaigns launch", desc: "Outreach goes live to the approved list", link: "sequences" },
  { id: uid(), date: addDays(start, 28).toISOString().slice(0, 10), title: "First replies & meetings", desc: "Qualified conversations start landing", link: "pipeline" },
  { id: uid(), date: "", title: "Pipeline management", desc: "Qualify, book, follow up, optimize", link: "pipeline" },
];
const DEF_LEADS = [
  { name: "Marcus Lee", company: "Nebula Robotics", title: "VP Marketing", email: "marcus@nebula.io", date: "2026-08-26", status: "Booked", conv: [["us", "Personalized opener referencing their new brand hire."], ["them", "Interested — what does onboarding look like?"], ["us", "Shared an overview, proposed a call."]] },
  { name: "Dana Cruz", company: "Gomora Health", title: "Head of Growth", email: "dana@gomora.co", date: "2026-08-27", status: "Meeting completed", conv: [["us", "Opener tied to their Series B."], ["them", "Yes, let's talk. Booked a slot."], ["us", "Call done — sending proposal."]] },
  { name: "Priya N.", company: "Starlord Labs", title: "CMO", email: "priya@starlord.ai", date: "2026-08-28", status: "No-show", conv: [["us", "Reached out on the open-CMO-role signal."], ["them", "Booked a slot."], ["us", "No-show — following up to reschedule."]] },
  { name: "Tom Vega", company: "Groot Interactive", title: "Founder", email: "tom@groot.dev", date: "2026-08-29", status: "Booked", conv: [["us", "Opener referencing recent funding."], ["them", "Curious, sent times."]] },
];
const STATUS_TONE = { "Booked": "blue", "Meeting completed": "green", "No-show": "red", "Rescheduled": "amber", "Lost": "gray" };
const VIEW_LABELS = { home: "Home", planner: "Planner", plan: "Plan & targets", sequences: "Sequences", docs: "Docs", pipeline: "Pipeline", report: "AI report" };
const NAV = [
  ["home", "Home", Home], ["planner", "Planner", CalendarClock], ["plan", "Plan & targets", Target],
  ["sequences", "Sequences", Mail], ["docs", "Docs", FileText], ["pipeline", "Pipeline", Rows3], ["report", "AI report", Sparkles],
];

/* ---------- tiny reusable UI ---------- */
function Menu({ items }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <span className="cw-menu" ref={ref}>
      <button className="cw-menubtn" onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}><MoreHorizontal size={16} /></button>
      {open && (
        <div className="cw-menupop" onClick={(e) => e.stopPropagation()}>
          {items.map((it, i) => (
            <button key={i} className={`cw-mi ${it.danger ? "danger" : ""}`} onClick={() => { setOpen(false); it.onClick(); }}>{it.icon}{it.label}</button>
          ))}
        </div>
      )}
    </span>
  );
}
/* Notion-lite rich editor: uncontrolled contentEditable + a small toolbar. Saves on blur. */
function RichDoc({ html, onChange, placeholder = "Write something…" }) {
  const ref = useRef(null);
  const cmd = (c, val) => { document.execCommand(c, false, val); ref.current?.focus(); onChange(ref.current.innerHTML); };
  return (
    <div className="cw-rich">
      <div className="cw-rtoolbar">
        <button title="Bold" onMouseDown={(e) => { e.preventDefault(); cmd("bold"); }}><Bold size={14} /></button>
        <button title="Heading" onMouseDown={(e) => { e.preventDefault(); cmd("formatBlock", "H2"); }}><Heading2 size={14} /></button>
        <button title="Text" onMouseDown={(e) => { e.preventDefault(); cmd("formatBlock", "P"); }}>¶</button>
        <button title="Bullet list" onMouseDown={(e) => { e.preventDefault(); cmd("insertUnorderedList"); }}><ListIcon size={14} /></button>
      </div>
      <div ref={ref} className="cw-rt" contentEditable suppressContentEditableWarning
        data-ph={placeholder} dangerouslySetInnerHTML={{ __html: html }}
        onBlur={(e) => onChange(e.currentTarget.innerHTML)} />
    </div>
  );
}
function InlineName({ value, onCommit, className = "" }) {
  const [v, setV] = useState(value);
  return (
    <input autoFocus className={`cw-inline ${className}`} value={v}
      onChange={(e) => setV(e.target.value)}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") { setV(value); e.currentTarget.blur(); } }}
      onBlur={() => onCommit(v.trim() || value)} onClick={(e) => e.stopPropagation()} />
  );
}

/* ================= MAIN ================= */
export default function ClientSpace() {
  const nav = useNavigate();
  const [view, setView] = useState("home");
  const [startDate, setStartDate] = useStored("rc_cs_fw_start", "2026-08-01");
  const [stats, setStats] = useStored("rc_cs_fw_stats", { reached: 3600, replied: 25 });
  const [config, setConfig] = useStored("rc_cs_fw_config", { tam: 2840, listSize: 180, segment: "Robotics & AI, mid-market" });
  const [angles, setAngles] = useStored("rc_cs_fw_angles", DEF_ANGLES);
  const [segments, setSegments] = useStored("rc_cs_fw_segments", DEF_SEGMENTS);
  const [planner, setPlanner] = useStored("rc_cs_fw_planner", DEF_PLANNER("2026-08-01"));
  const [docs, setDocs] = useStored("rc_cs_fw_docs", DEF_DOCS);
  const [leads, setLeads] = useStored("rc_cs_fw_leads", DEF_LEADS);
  const [report, setReport] = useState("");
  const [share, setShare] = useState(false);

  const invoice = addMonths(startDate, 1);
  const setLeadStatus = (i, v) => setLeads((ls) => ls.map((l, k) => (k === i ? { ...l, status: v } : l)));

  const genReport = () => {
    setReport("Generating…");
    setTimeout(() => {
      const done = leads.filter((l) => l.status === "Meeting completed").length;
      const ns = leads.filter((l) => l.status === "No-show").length;
      setReport(
`Future Works — Outbound performance (as of ${fmt(new Date())})

Activity
• Emails reached: ${stats.reached.toLocaleString()}
• Replied: ${stats.replied}
• Meetings booked: ${leads.length}   Completed: ${done}   No-shows: ${ns}

Targeting
• Segment: ${config.segment}
• Total addressable: ${config.tam.toLocaleString()}   Selected: ${config.listSize}

What is working
• Signal-led openers (funding, brand hires) drive the strongest replies.
• Personalized first lines outperform generic intros.

Next
• Continue the primary segment; test the second angle.
• Next invoice: ${fmt(invoice)}.

Draft generated from campaign data. Review before sending.`);
    }, 650);
  };

  return (
    <div className="cw-root">
      <style>{CW_CSS}</style>
      <div className="cw-top">
        <button className="btn ghost sm" onClick={() => nav("/enrichment")}><ArrowLeft size={15} /> Back to Outbound</button>
        <div className="cw-ws"><span className="cw-avatar">FW</span> Future Works <span className="cw-dim">/ Client Space</span></div>
        <span className="cw-badge">Client view</span>
        <div className="cw-search">Search this workspace…</div>
        <button className="btn sm" onClick={() => setShare(true)}><Share2 size={14} /> Share</button>
      </div>

      <div className="cw-body">
        <div className="cw-rail">
          {NAV.map(([id, label, Icon]) => (
            <button key={id} className={`cw-ir ${view === id ? "on" : ""}`} title={label} onClick={() => setView(id)}><Icon size={18} /></button>
          ))}
        </div>

        <div className="cw-side">
          <div className="cw-sidehead"><span className="cw-avatar sm">FW</span> Future Works</div>
          {NAV.map(([id, label, Icon]) => (
            <button key={id} className={`cw-nav ${view === id ? "on" : ""}`} onClick={() => setView(id)}>
              <Icon size={16} /> {label}{id === "pipeline" && <span className="cw-ct">{leads.length}</span>}
            </button>
          ))}
          <div className="cw-sec">Shared with me</div>
          {docs.map((d) => (
            <button key={d.id} className="cw-doc" onClick={() => setView("docs")}><span>{d.icon}</span> {d.title}</button>
          ))}
        </div>

        <div className="cw-main">
          <div className="cw-title">{VIEW_LABELS[view]}</div>
          {view === "home" && <HomeView stats={stats} leads={leads} startDate={startDate} setStartDate={setStartDate} invoice={invoice} />}
          {view === "planner" && <PlannerView config={config} setConfig={setConfig} stats={stats} setStats={setStats} planner={planner} setPlanner={setPlanner} go={setView} />}
          {view === "plan" && <PlanView segments={segments} setSegments={setSegments} />}
          {view === "sequences" && <SeqView angles={angles} setAngles={setAngles} />}
          {view === "docs" && <DocsView docs={docs} setDocs={setDocs} />}
          {view === "pipeline" && <PipeView leads={leads} setStatus={setLeadStatus} />}
          {view === "report" && <ReportView report={report} onGen={genReport} onPush={(w) => notify(w === "slack" ? "Report posted to #future-works" : "Report emailed to the client", "ok")} />}
        </div>
      </div>

      {share && <ShareModal onClose={() => setShare(false)} />}
    </div>
  );
}

/* ---------- HOME (progress-first) ---------- */
function HomeView({ stats, leads, startDate, setStartDate, invoice }) {
  const now = new Date();
  const steps = [
    { k: "Step 1", t: "Cold email infrastructure", d: "Domains, inboxes, warm-up", date: new Date(startDate + "T00:00:00"), next: addDays(startDate, 21) },
    { k: "Step 2", t: "Launch outreach", d: "Campaigns go live", date: addDays(startDate, 21), next: addDays(startDate, 28) },
    { k: "Step 3", t: "First results", d: "Replies and meetings begin", date: addDays(startDate, 28), next: addMonths(startDate, 1) },
    { k: "Step 4", t: "Manage pipeline", d: "Qualify, book, follow up", date: addDays(startDate, 28), next: addDays(startDate, 999) },
  ];
  const done = leads.filter((l) => l.status === "Meeting completed").length;
  return (
    <>
      <div className="metrics cw-g4">
        <Metric icon={<Mail size={14} />} label="Reached" value={stats.reached.toLocaleString()} sub="emails delivered" />
        <Metric icon={<ArrowRight size={14} />} label="Replied" value={String(stats.replied)} sub={`${((stats.replied / Math.max(stats.reached, 1)) * 100).toFixed(2)}% reply rate`} />
        <Metric icon={<CalendarClock size={14} />} label="Meetings booked" value={String(leads.length)} sub={`${done} completed`} />
        <Metric icon={<FileText size={14} />} label="Next invoice" value={fmt(invoice)} sub="$3,000 · monthly" />
      </div>
      <div className="cw-sech">Roadmap to results</div>
      <div className="card">
        <div className="cw-daterow">
          <b>Pilot start date</b>
          <input type="date" className="cw-date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <span className="cw-dim2">Launch is start + 21 days, first results a week later, next invoice one month on. Detailed targets and dates live in the Planner.</span>
        </div>
        <div className="cw-road">
          {steps.map((s, i) => {
            const isDone = now >= s.next; const isNow = !isDone && now >= s.date;
            const tone = isDone ? "green" : isNow ? "blue" : "gray";
            return (
              <div key={i} className="cw-rstep">
                <div className={`cw-bar ${isDone ? "done" : isNow ? "now" : ""}`} />
                <div className="cw-rk">{s.k}</div><div className="cw-rt">{s.t}</div>
                <div className="cw-rd">{s.d}<br />{fmt(s.date)}</div>
                <div style={{ marginTop: 8 }}><StatusBadge tone={tone}>{isDone ? "Done" : isNow ? "In progress" : "Upcoming"}</StatusBadge></div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

/* ---------- PLANNER (editable config + interactive stages) ---------- */
function PlannerView({ config, setConfig, stats, setStats, planner, setPlanner, go }) {
  const now = new Date();
  const patchStage = (id, patch) => setPlanner((p) => p.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  const del = (id) => setPlanner((p) => p.filter((s) => s.id !== id));
  const add = () => setPlanner((p) => [...p, { id: uid(), date: "", title: "New stage", desc: "", link: "home" }]);
  const numField = (label, key, store, set) => (
    <label className="cw-cfg"><span>{label}</span>
      <input className="cw-input" value={store[key]} onChange={(e) => set({ ...store, [key]: e.target.value.replace(/[^0-9]/g, "") === "" && typeof store[key] === "number" ? 0 : (typeof store[key] === "number" ? Number(e.target.value.replace(/[^0-9]/g, "")) : e.target.value) })} />
    </label>
  );
  return (
    <>
      <div className="cw-sech">Campaign setup <span className="cw-dim2" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>· the numbers behind the plan (editable)</span></div>
      <div className="card cw-cfggrid">
        {numField("Total addressable (TAM)", "tam", config, setConfig)}
        {numField("Selected this phase", "listSize", config, setConfig)}
        <label className="cw-cfg"><span>Segment</span><input className="cw-input" value={config.segment} onChange={(e) => setConfig({ ...config, segment: e.target.value })} /></label>
        {numField("Emails reached", "reached", stats, setStats)}
        {numField("Replied", "replied", stats, setStats)}
      </div>

      <div className="cw-sech">Timeline <span className="cw-dim2" style={{ textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>· pick dates, edit, and jump to each stage</span></div>
      <div className="cw-plan">
        {planner.map((s) => {
          const active = s.date && now >= new Date(s.date + "T00:00:00");
          return (
            <div key={s.id} className={`cw-planrow ${active ? "done" : ""}`}>
              <span className="cw-pdot" />
              <input type="date" className="cw-input cw-pdate" value={s.date} onChange={(e) => patchStage(s.id, { date: e.target.value })} />
              <div className="cw-pmid">
                <input className="cw-inline cw-ptitle" value={s.title} onChange={(e) => patchStage(s.id, { title: e.target.value })} />
                <input className="cw-inline cw-pdesc" value={s.desc} placeholder="Add a note…" onChange={(e) => patchStage(s.id, { desc: e.target.value })} />
              </div>
              <div className="cw-pact">
                <Select value={s.link} onChange={(e) => patchStage(s.id, { link: e.target.value })}>
                  {NAV.map(([id, label]) => <option key={id} value={id}>Go to {label}</option>)}
                </Select>
                <button className="btn ghost sm" onClick={() => go(s.link)}>Open <ArrowRight size={13} /></button>
                <button className="cw-menubtn" title="Delete" onClick={() => del(s.id)}><Trash2 size={15} /></button>
              </div>
            </div>
          );
        })}
        <button className="btn ghost sm" style={{ marginTop: 8 }} onClick={add}><Plus size={14} /> Add stage</button>
      </div>
    </>
  );
}

/* ---------- PLAN & TARGETS (Notion-editable segment folders) ---------- */
function PlanView({ segments, setSegments }) {
  const [openId, setOpenId] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const patch = (id, p) => setSegments((s) => s.map((x) => (x.id === id ? { ...x, ...p } : x)));
  const seg = segments.find((s) => s.id === openId);
  if (seg) {
    return (
      <>
        <button className="btn ghost sm" onClick={() => setOpenId(null)} style={{ marginBottom: 14 }}><ArrowLeft size={14} /> All segments</button>
        <div className="cw-docwrap">
          <div className="cw-dtitlerow">
            <span className="cw-dicon">{seg.icon}</span>
            <input className="cw-inline cw-h1in" value={seg.name} onChange={(e) => patch(seg.id, { name: e.target.value })} />
          </div>
          <RichDoc html={seg.html} onChange={(html) => patch(seg.id, { html })} placeholder="Write the segment strategy — positioning, list, angles…" />
        </div>
      </>
    );
  }
  return (
    <>
      <p className="cw-dim2" style={{ margin: "0 0 16px" }}>Segments are folders you can shape per market. Open one to edit it like a Notion page. Not rigid — add, rename, duplicate, delete.</p>
      <div className="cw-cards">
        {segments.map((s) => (
          <div key={s.id} className="cw-cardx" onClick={() => setOpenId(s.id)}>
            <div className="cw-cardtop"><span className="cw-cardicon">{s.icon}</span>
              <Menu items={[
                { icon: <Pencil size={14} />, label: "Rename", onClick: () => setRenaming(s.id) },
                { icon: <Copy size={14} />, label: "Duplicate", onClick: () => setSegments((a) => [...a, { ...s, id: uid(), name: s.name + " copy" }]) },
                { icon: <Trash2 size={14} />, label: "Delete", danger: true, onClick: () => setSegments((a) => a.filter((x) => x.id !== s.id)) },
              ]} />
            </div>
            {renaming === s.id
              ? <InlineName value={s.name} onCommit={(v) => { patch(s.id, { name: v }); setRenaming(null); }} className="cw-cardname" />
              : <div className="cw-cardname">{s.name}</div>}
            <div className="cw-carddim" dangerouslySetInnerHTML={{ __html: (s.html || "").replace(/<[^>]+>/g, " ").slice(0, 90) + "…" }} />
          </div>
        ))}
        <button className="cw-cardnew" onClick={() => { const id = uid(); setSegments((a) => [...a, { id, name: "New segment", icon: "📁", html: "<p></p>" }]); setOpenId(id); }}><Plus size={16} /> New segment</button>
      </div>
    </>
  );
}

/* ---------- SEQUENCES (multi-angle) ---------- */
function SeqView({ angles, setAngles }) {
  const [openId, setOpenId] = useState(null);
  const [renaming, setRenaming] = useState(null);
  const angle = angles.find((a) => a.id === openId);
  if (angle) return <SeqEditor angle={angle} onBack={() => setOpenId(null)} onChange={(steps) => setAngles((as) => as.map((a) => (a.id === angle.id ? { ...a, steps } : a)))} />;
  const emailCount = (a) => a.steps.filter((s) => s.type === "email").length;
  return (
    <>
      <p className="cw-dim2" style={{ margin: "0 0 16px" }}>There is never just one angle. Each campaign angle is its own sequence. Open one to edit its emails; add, rename, duplicate, or delete angles.</p>
      <div className="cw-cards">
        {angles.map((a) => (
          <div key={a.id} className="cw-cardx" onClick={() => setOpenId(a.id)}>
            <div className="cw-cardtop"><span className="cw-cardicon"><Mail size={16} /></span>
              <Menu items={[
                { icon: <Pencil size={14} />, label: "Rename", onClick: () => setRenaming(a.id) },
                { icon: <Copy size={14} />, label: "Duplicate", onClick: () => setAngles((x) => [...x, { ...a, id: uid(), name: a.name + " copy", steps: a.steps.map((s) => ({ ...s })) }]) },
                { icon: <Trash2 size={14} />, label: "Delete", danger: true, onClick: () => setAngles((x) => x.filter((y) => y.id !== a.id)) },
              ]} />
            </div>
            {renaming === a.id
              ? <InlineName value={a.name} onCommit={(v) => { setAngles((x) => x.map((y) => (y.id === a.id ? { ...y, name: v } : y))); setRenaming(null); }} className="cw-cardname" />
              : <div className="cw-cardname">{a.name}</div>}
            <div className="cw-carddim">{emailCount(a)} email{emailCount(a) > 1 ? "s" : ""} · {a.steps[0]?.subject || "no subject"}</div>
          </div>
        ))}
        <button className="cw-cardnew" onClick={() => { const id = uid(); setAngles((x) => [...x, { id, name: "New angle", steps: [{ type: "email", subject: "New subject", body: "Hi {{first_name}},\n\n" }] }]); setOpenId(id); }}><Plus size={16} /> New angle</button>
      </div>
    </>
  );
}
function SeqEditor({ angle, onBack, onChange }) {
  const [active, setActive] = useState(angle.steps.findIndex((s) => s.type === "email"));
  const [preview, setPreview] = useState(false);
  const st = angle.steps[active];
  const [subject, setSubject] = useState(st?.subject || "");
  const [body, setBody] = useState(st?.body || "");
  useEffect(() => { setSubject(angle.steps[active]?.subject || ""); setBody(angle.steps[active]?.body || ""); setPreview(false); }, [active, angle.id]);
  const fill = (s) => (s || "").replace(/{{first_name}}/g, "Marcus").replace(/{{company}}/g, "Nebula Robotics").replace(/{{signal}}/g, "a new brand hire").replace(/{{title}}/g, "VP Marketing");
  const save = () => { onChange(angle.steps.map((s, i) => (i === active ? { ...s, subject, body } : s))); notify("Sequence saved", "ok"); };
  const addStep = () => onChange([...angle.steps, { type: "wait", days: 3 }, { type: "email", subject: "New follow-up", body: "Hi {{first_name}},\n\n" }]);
  let emailNo = 0;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <button className="btn ghost sm" onClick={onBack}><ArrowLeft size={14} /> All angles</button>
        <b style={{ fontSize: 15 }}>{angle.name}</b>
      </div>
      <div className="cw-seq">
        <div className="cw-seqrail">
          {angle.steps.map((s, i) => {
            if (s.type === "wait") return <div key={i} className="cw-wait"><ChevronDown size={13} /> wait {s.days} day{s.days > 1 ? "s" : ""}</div>;
            emailNo++;
            return (
              <button key={i} className={`cw-step ${i === active ? "on" : ""}`} onClick={() => setActive(i)}>
                <div className="cw-stepn">Email {emailNo}</div>
                <div className="cw-steps">{s.subject || "(no subject)"}</div>
                <div className="cw-stepm">{(s.body || "").split("\n")[0]}</div>
              </button>
            );
          })}
          <button className="btn ghost sm" style={{ width: "100%", marginTop: 6 }} onClick={addStep}><Plus size={14} /> Add step</button>
        </div>
        <div className="cw-seqedit">
          {st?.type !== "email" ? <div className="cw-dim2">Select an email step.</div> : preview ? (
            <>
              <div className="cw-editbar"><b>Preview</b><button className="btn ghost sm" onClick={() => setPreview(false)}>← Edit</button></div>
              <div className="cw-preview"><div className="cw-ph"><b>Subject:</b> {fill(subject)}</div><div className="cw-pb">{fill(body)}</div></div>
            </>
          ) : (
            <>
              <div className="cw-editbar"><b>Edit email</b>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn ghost sm" onClick={() => setPreview(true)}>Preview</button>
                  <button className="btn sm" onClick={save}>Save</button>
                </div>
              </div>
              <div className="cw-vars">{["{{first_name}}", "{{company}}", "{{signal}}", "{{title}}"].map((v) => <button key={v} className="cw-var" onClick={() => setBody((b) => b + v)}>{v}</button>)}</div>
              <label className="cw-flabel">Subject</label>
              <input className="cw-input" value={subject} onChange={(e) => setSubject(e.target.value)} />
              <label className="cw-flabel" style={{ marginTop: 12 }}>Body</label>
              <textarea className="cw-input cw-area" value={body} onChange={(e) => setBody(e.target.value)} />
            </>
          )}
        </div>
      </div>
    </>
  );
}

/* ---------- DOCS (editable) ---------- */
function DocsView({ docs, setDocs }) {
  const [open, setOpen] = useState(0);
  const [renaming, setRenaming] = useState(false);
  const d = docs[open] || docs[0];
  const patch = (p) => setDocs((ds) => ds.map((x, i) => (i === open ? { ...x, ...p } : x)));
  return (
    <>
      <div className="cw-doctabs">
        {docs.map((doc, i) => <button key={doc.id} className={`btn ${i === open ? "" : "ghost"} sm`} onClick={() => { setOpen(i); setRenaming(false); }}>{doc.icon} {doc.title}</button>)}
        <button className="btn ghost sm" onClick={() => { setDocs((ds) => [...ds, { id: uid(), icon: "📝", title: "New doc", html: "<p></p>" }]); setOpen(docs.length); }}><Plus size={14} /> New doc</button>
      </div>
      {d && (
        <div className="cw-docwrap">
          <div className="cw-dtitlerow">
            <span className="cw-dicon">{d.icon}</span>
            {renaming ? <InlineName value={d.title} onCommit={(v) => { patch({ title: v }); setRenaming(false); }} className="cw-h1in" />
              : <h1 className="cw-h1" onClick={() => setRenaming(true)} title="Click to rename">{d.title}</h1>}
            <Menu items={[
              { icon: <Pencil size={14} />, label: "Rename", onClick: () => setRenaming(true) },
              { icon: <Copy size={14} />, label: "Duplicate", onClick: () => setDocs((ds) => [...ds, { ...d, id: uid(), title: d.title + " copy" }]) },
              { icon: <Trash2 size={14} />, label: "Delete", danger: true, onClick: () => { setDocs((ds) => ds.filter((_, i) => i !== open)); setOpen(0); } },
            ]} />
          </div>
          <RichDoc html={d.html} onChange={(html) => patch({ html })} placeholder="Start writing — headings, bullets, bold…" />
        </div>
      )}
    </>
  );
}

/* ---------- PIPELINE ---------- */
function PipeView({ leads, setStatus }) {
  const [openRow, setOpenRow] = useState(-1);
  return (
    <>
      <p className="cw-dim2" style={{ margin: "0 0 14px" }}>Only booked meetings appear here. Change status with the dropdown, like a sheet. Click a row for full lead info and the conversation.</p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <table className="cw-tbl">
          <thead><tr><th>Lead</th><th>Email</th><th>Meeting date</th><th>Status</th><th>Update</th></tr></thead>
          <tbody>
            {leads.map((l, i) => (
              <PipeRow key={i} l={l} i={i} open={openRow === i} onToggle={() => setOpenRow(openRow === i ? -1 : i)} setStatus={setStatus} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
function PipeRow({ l, i, open, onToggle, setStatus }) {
  return (
    <>
      <tr className="cw-lead" onClick={onToggle}>
        <td><div className="cw-lb">{l.name}</div><div className="cw-ls">{l.title} · {l.company}</div></td>
        <td>{l.email}</td><td>{fmt(l.date)}</td>
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
            <div><div className="cw-convh">Lead info</div>
              <div className="cw-kv">
                <div><span className="k">Name</span><span className="v">{l.name}</span></div>
                <div><span className="k">Title</span><span className="v">{l.title}</span></div>
                <div><span className="k">Company</span><span className="v">{l.company}</span></div>
                <div><span className="k">Email</span><span className="v">{l.email}</span></div>
                <div><span className="k">Meeting</span><span className="v">{fmt(l.date)}</span></div>
              </div>
            </div>
            <div><div className="cw-convh">Conversation</div>
              {l.conv.map((c, k) => <div key={k} className={`cw-bubble ${c[0] === "them" ? "them" : ""}`}><div className="cw-who">{c[0] === "them" ? l.name : "RevCadence"}</div>{c[1]}</div>)}
            </div>
          </div>
        </td></tr>
      )}
    </>
  );
}

/* ---------- AI REPORT ---------- */
function ReportView({ report, onGen, onPush }) {
  return (
    <>
      <p className="cw-dim2" style={{ margin: "0 0 14px" }}>Generate a plain-language performance report from the campaign data, then push it to Slack and email.</p>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <button className="btn" onClick={onGen}><Sparkles size={14} /> Generate report</button>
        <button className="btn ghost" onClick={() => onPush("slack")}>Send to Slack</button>
        <button className="btn ghost" onClick={() => onPush("email")}>Send via email</button>
      </div>
      <div className="cw-report">{report || "Click Generate report to draft this month's summary from the campaign data."}</div>
    </>
  );
}

/* ---------- SHARE ---------- */
function ShareModal({ onClose }) {
  const rows = [
    ["Client Space", "Home, Planner, Plan, Sequences, Docs, Pipeline, AI report", true, false],
    ["Outbound (internal)", "Lists, campaigns, raw data", false, true],
    ["CRM (internal)", "Full contact database", false, true],
    ["Reply / Inbox (internal)", "Live mailboxes", false, true],
  ];
  return (
    <div className="cw-ov" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cw-modal">
        <div className="cw-mh">Share with Future Works</div>
        <div className="cw-mb">
          <p className="cw-dim2">Choose exactly what the client can see. For clients, expose only the Client Space.</p>
          {rows.map(([label, sub, on, locked]) => <ShareRow key={label} label={label} sub={sub} on={on} locked={locked} />)}
        </div>
        <div className="cw-mf"><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn" onClick={() => { onClose(); notify("Invite sent · client sees only the Client Space", "ok"); }}>Send invite</button></div>
      </div>
    </div>
  );
}
function ShareRow({ label, sub, on, locked }) {
  const [v, setV] = useState(on);
  return (
    <div className="cw-shrow">
      <div style={{ flex: 1 }}><b>{label}</b><div className="cw-dim2">{sub}</div></div>
      <button className={`cw-sw ${v ? "on" : ""} ${locked ? "lock" : ""}`} onClick={() => !locked && setV(!v)}><i /></button>
    </div>
  );
}

/* ---------- scoped styles (reference system tokens) ---------- */
const CW_CSS = `
.cw-root{position:fixed;inset:0;z-index:50;background:var(--bg);color:var(--text);display:flex;flex-direction:column;font-family:inherit}
.cw-top{height:52px;flex:none;display:flex;align-items:center;gap:12px;padding:0 14px;background:var(--sidebar-bg);border-bottom:1px solid var(--border)}
.cw-ws{display:flex;align-items:center;gap:8px;font-weight:700}.cw-dim{color:var(--muted);font-weight:500}
.cw-avatar{width:22px;height:22px;border-radius:6px;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700}
.cw-avatar.sm{width:20px;height:20px;font-size:10px}
.cw-badge{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--accent);background:var(--accent-soft);padding:4px 9px;border-radius:6px}
.cw-search{flex:1;max-width:400px;margin:0 auto;background:var(--topbar-control);border:1px solid var(--border);border-radius:8px;padding:7px 12px;color:var(--muted);font-size:12.5px}
.cw-body{flex:1;display:flex;min-height:0}
.cw-rail{width:54px;flex:none;background:var(--sidebar-elevated);border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:center;padding:10px 0;gap:4px}
.cw-ir{width:36px;height:36px;border-radius:9px;border:0;background:transparent;color:var(--sidebar-text);display:flex;align-items:center;justify-content:center;cursor:pointer}
.cw-ir:hover{background:var(--sidebar-hover);color:var(--sidebar-text-active)}.cw-ir.on{background:var(--accent);color:#fff}
.cw-side{width:236px;flex:none;background:var(--sidebar-bg);border-right:1px solid var(--border);overflow:auto;padding:12px 10px}
.cw-sidehead{display:flex;align-items:center;gap:8px;font-weight:700;font-size:14px;padding:4px 8px 12px}
.cw-nav{display:flex;align-items:center;gap:10px;width:100%;text-align:left;border:0;background:transparent;padding:8px 10px;border-radius:8px;color:var(--sidebar-text);font-weight:600;font-size:13.5px;cursor:pointer}
.cw-nav:hover{background:var(--sidebar-hover);color:var(--sidebar-text-active)}.cw-nav.on{background:var(--sidebar-active);color:var(--sidebar-text-active)}
.cw-ct{margin-left:auto;font-size:11px;color:var(--muted);font-weight:700}
.cw-sec{font-size:10.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:16px 10px 6px}
.cw-doc{display:flex;align-items:center;gap:9px;width:100%;text-align:left;border:0;background:transparent;padding:7px 10px;border-radius:8px;color:var(--sidebar-text);font-size:13px;cursor:pointer}
.cw-doc:hover{background:var(--sidebar-hover);color:var(--sidebar-text-active)}
.cw-main{flex:1;overflow:auto;padding:22px 30px 60px;min-width:0}
.cw-title{font-size:22px;font-weight:800;letter-spacing:-.02em;margin-bottom:18px}
.cw-sech{font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:26px 0 12px}
.cw-g4{grid-template-columns:repeat(4,1fr)}
.cw-p{color:var(--muted);line-height:1.65;margin:8px 0}
.cw-daterow{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.cw-date{border:1px solid var(--border-strong);border-radius:8px;padding:7px 10px;font-family:inherit;background:var(--card);color:var(--text)}
.cw-dim2{color:var(--muted);font-size:12.5px}
.cw-road{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.cw-bar{height:6px;border-radius:6px;background:var(--progress-track)}.cw-bar.done{background:var(--ok)}.cw-bar.now{background:var(--accent)}
.cw-rk{font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-top:10px}
.cw-rt{font-weight:700;margin-top:3px}.cw-rd{color:var(--muted);font-size:12.5px;margin-top:2px}
.cw-cfggrid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.cw-cfg{display:flex;flex-direction:column;gap:5px}.cw-cfg>span{font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.cw-plan{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:14px}
.cw-planrow{display:flex;align-items:center;gap:12px;padding:10px 6px;border-bottom:1px solid var(--border)}
.cw-planrow:last-of-type{border-bottom:0}
.cw-pdot{width:11px;height:11px;border-radius:50%;background:var(--card);border:2px solid var(--border-strong);flex:none}
.cw-planrow.done .cw-pdot{background:var(--ok);border-color:var(--ok)}
.cw-pdate{width:150px;flex:none}
.cw-pmid{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.cw-ptitle{font-weight:700;font-size:14px}.cw-pdesc{font-size:12.5px;color:var(--muted)}
.cw-pact{display:flex;align-items:center;gap:8px;flex:none}
.cw-inline{border:1px solid transparent;border-radius:7px;padding:5px 7px;font-family:inherit;font-size:13px;color:var(--text);background:transparent;width:100%}
.cw-inline:hover{border-color:var(--border)}.cw-inline:focus{border-color:var(--accent);outline:none;background:var(--card)}
.cw-input{width:100%;border:1px solid var(--border-strong);border-radius:8px;padding:9px 11px;font-family:inherit;font-size:13px;color:var(--text);background:var(--card)}
.cw-area{min-height:190px;resize:vertical;line-height:1.5}
.cw-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.cw-cardx{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px;cursor:pointer;min-height:120px;display:flex;flex-direction:column}
.cw-cardx:hover{border-color:var(--accent-border);box-shadow:0 4px 14px rgba(15,17,32,.06)}
.cw-cardtop{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.cw-cardicon{width:30px;height:30px;border-radius:8px;background:var(--accent-soft);color:var(--accent);display:flex;align-items:center;justify-content:center;font-size:16px}
.cw-cardname{font-weight:700;font-size:14.5px}.cw-carddim{color:var(--muted);font-size:12.5px;margin-top:4px;line-height:1.5;overflow:hidden}
.cw-cardnew{background:transparent;border:1.5px dashed var(--border-strong);border-radius:var(--radius);color:var(--muted);font-weight:700;font-size:13.5px;display:flex;align-items:center;justify-content:center;gap:7px;cursor:pointer;min-height:120px}
.cw-cardnew:hover{border-color:var(--accent);color:var(--accent)}
.cw-menu{position:relative;display:inline-flex}
.cw-menubtn{width:28px;height:28px;border-radius:7px;border:0;background:transparent;color:var(--muted);display:flex;align-items:center;justify-content:center;cursor:pointer}
.cw-menubtn:hover{background:var(--hover-soft);color:var(--text)}
.cw-menupop{position:absolute;right:0;top:32px;background:var(--popup-bg);border:1px solid var(--popup-border);border-radius:10px;box-shadow:0 8px 30px rgba(15,17,32,.14);padding:5px;z-index:20;min-width:170px}
.cw-mi{display:flex;align-items:center;gap:9px;width:100%;text-align:left;border:0;background:transparent;padding:8px 10px;border-radius:7px;font-size:13px;color:var(--text);cursor:pointer;font-family:inherit}
.cw-mi:hover{background:var(--hover-soft)}.cw-mi.danger{color:var(--bad)}
.cw-docwrap{max-width:760px}
.cw-dtitlerow{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.cw-dicon{font-size:30px}.cw-h1{font-size:26px;font-weight:800;letter-spacing:-.02em;cursor:text}
.cw-h1in{font-size:24px;font-weight:800;flex:1}
.cw-rich{border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;background:var(--card)}
.cw-rtoolbar{display:flex;gap:2px;padding:7px 8px;border-bottom:1px solid var(--border);background:var(--sidebar-elevated)}
.cw-rtoolbar button{width:30px;height:28px;border:0;background:transparent;border-radius:6px;color:var(--muted);cursor:pointer;display:flex;align-items:center;justify-content:center;font-weight:700}
.cw-rtoolbar button:hover{background:var(--hover-soft);color:var(--text)}
.cw-rt{padding:16px 18px;min-height:260px;font-size:14px;line-height:1.7;color:var(--text);outline:none}
.cw-rt:empty:before{content:attr(data-ph);color:var(--muted)}
.cw-rt h2{font-size:18px;margin:16px 0 6px}.cw-rt p{margin:8px 0;color:var(--text)}.cw-rt ul{margin:8px 0;padding-left:22px}.cw-rt li{margin:3px 0}
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
.cw-preview{border:1px solid var(--border);border-radius:10px;overflow:hidden}
.cw-ph{background:var(--sidebar-elevated);border-bottom:1px solid var(--border);padding:10px 14px;font-size:12.5px}
.cw-pb{padding:16px 18px;font-size:13.5px;line-height:1.6;white-space:pre-wrap}
.cw-doctabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.cw-kv{border:1px solid var(--border);border-radius:10px;overflow:hidden;margin:12px 0}
.cw-kv>div{display:grid;grid-template-columns:150px 1fr;font-size:13px}.cw-kv>div+div{border-top:1px solid var(--border)}
.cw-kv .k{background:var(--sidebar-elevated);padding:9px 12px;font-weight:700;color:var(--text)}.cw-kv .v{padding:9px 12px;color:var(--muted)}
.cw-tbl{width:100%;border-collapse:collapse}
.cw-tbl th{text-align:left;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:800;padding:11px 14px;background:var(--sidebar-elevated);border-bottom:1px solid var(--border)}
.cw-tbl td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:13px;vertical-align:middle}
.cw-lead:hover{background:var(--hover-soft);cursor:pointer}.cw-lb{font-weight:700}.cw-ls{color:var(--muted);font-size:12px}
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
.cw-sw.on{background:var(--accent)}.cw-sw i{position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.15s}
.cw-sw.on i{left:18px}.cw-sw.lock{opacity:.5;cursor:not-allowed}
@media (max-width:900px){.cw-g4,.cw-road,.cw-cfggrid{grid-template-columns:1fr 1fr}.cw-seq{grid-template-columns:1fr}}
`;
