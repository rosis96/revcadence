// Client Space · Library.
//
// The client's raw materials: the facts the email writer is allowed to use.
// Three tabs, because the writer needs three different kinds of input —
// proof (case studies), targets (segments & TAM), and what we have learned
// (ICP tests).
//
// Why this is not a document. In a doc, a case study is a paragraph. Here it is
// a record with a source, a link and a usage count, which is why the cards can
// say "Used in 2 angles · 312 emails". A paragraph cannot carry provenance, and
// an angle cannot point at one and survive it being reworded.
//
// The source tag is the point of the screen. `client-supplied` is usable as
// background and refused as a named claim — enforced server-side in
// `sequences.py::_quality`, so the badge on the card and the rule in the writer
// are the same fact, not two things that can drift apart.
//
// The add tiles are deliberately three specific invitations rather than one
// "+ New". This is the one surface where the client gives us something, and
// "add a case study" gets answered where "create record" does not. Two of them
// (exclusions, objections) open the list they write into, so the records they
// create have a home without inventing two more tabs.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import {
  Ban, BadgeCheck, Building2, CheckCircle2, ExternalLink, FlaskConical, Inbox, Layers,
  MessageSquareWarning, Pencil, Plus, ShieldQuestion, Trash2, TrendingUp,
} from "lucide-react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import {
  Area, Button, Drawer, EmptyState, ErrorBox, Input, Modal, Select, Skeleton, StatusPill,
  confirmDialog, promptDialog, useToast,
} from "../../components";
import { useClientView } from "../../clientspace/frame";

const TABS = [
  ["case_studies", "Case studies", Layers],
  ["segments", "Segments & TAM", Building2],
  ["icp_tests", "ICP tests", FlaskConical],
];

const SOURCE_TONE = { verified: "green", client_supplied: "blue", operator: "gray" };
const VERDICT_TONE = { validated: "green", testing: "blue", killed: "gray" };
const SOURCE_OPTIONS = [
  ["operator", "Operator — we wrote it down"],
  ["verified", "Verified — there is a link to check"],
];

const num = (value) => (value === null || value === undefined ? "" : value.toLocaleString());
const count = (n, one, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;

function SourcePill({ record }) {
  return (
    <StatusPill tone={SOURCE_TONE[record.source] || "gray"}>{record.source_label}</StatusPill>
  );
}

// The meta line under a card title: the facts that place the record, then its
// provenance. Provenance sits last because it is the thing the eye should land
// on when scanning for what still needs doing.
function MetaLine({ parts, record }) {
  const shown = parts.filter(Boolean);
  return (
    <div className="lib-meta">
      {shown.map((part, i) => <span key={i}>{part}</span>)}
      <SourcePill record={record} />
      {record.source_url ? (
        <a href={record.source_url} target="_blank" rel="noreferrer" title={record.source_url}>
          <ExternalLink size={12} />
        </a>
      ) : null}
    </div>
  );
}

function CardActions({ onEdit, onVerify, onDelete, canEdit, canVerify, record }) {
  if (!canEdit) return null;
  return (
    <div className="lib-card-acts">
      {canVerify && !record.verified && (
        <button title="Verify — needs a link somebody can check" onClick={onVerify}>
          <BadgeCheck size={14} /> Verify
        </button>
      )}
      <button title="Edit" onClick={onEdit}><Pencil size={14} /></button>
      <button title="Remove" className="danger" onClick={onDelete}><Trash2 size={14} /></button>
    </div>
  );
}

function CaseStudyCard({ row, ...actions }) {
  const usage = row.usage || {};
  return (
    <article className="card lib-card">
      <h3>{row.title}</h3>
      <MetaLine parts={[row.segment, row.year]} record={row} />
      <p>{row.outcome}</p>
      {row.limitation ? <p className="lib-limit">{row.limitation}</p> : null}
      <footer>
        {usage.angles ? (
          <>
            <span className="lib-use" title={(usage.angle_names || []).join(", ")}>
              <span className="dot" />{count(usage.angles, "angle")}
            </span>
            {usage.emails ? <span className="lib-tag">{count(usage.emails, "email")}</span> : null}
          </>
        ) : (
          <span className="lib-tag">Not used in an angle yet</span>
        )}
        {!row.verified && (
          <span className="lib-use warn"><span className="dot" />Needs verification</span>
        )}
      </footer>
      <CardActions record={row} {...actions} />
    </article>
  );
}

function SegmentCard({ row, ...actions }) {
  return (
    <article className="card lib-card">
      <h3>{row.name}</h3>
      <MetaLine parts={[row.company_type, row.headcount && `${row.headcount} staff`,
        row.geography]} record={row} />
      <div className="lib-figures">
        <div>
          <b>{row.tam_estimate === null || row.tam_estimate === undefined
            ? "—" : num(row.tam_estimate)}</b>
          <span>exist</span>
        </div>
        <div>
          <b>{row.in_list === null || row.in_list === undefined ? "—" : num(row.in_list)}</b>
          <span>{row.in_list === null || row.in_list === undefined
            ? "not in a list yet" : "in the list"}</span>
        </div>
        {row.coverage !== null && row.coverage !== undefined && (
          <div><b>{row.coverage}%</b><span>covered</span></div>
        )}
      </div>
      {row.tam_note ? <p>{row.tam_note}</p> : null}
      {row.list_name ? (
        <footer><span className="lib-tag"><TrendingUp size={12} /> {row.list_name}</span></footer>
      ) : null}
      <CardActions record={row} {...actions} />
    </article>
  );
}

function IcpTestCard({ row, ...actions }) {
  return (
    <article className="card lib-card">
      <h3>{row.hypothesis}</h3>
      <div className="lib-meta">
        <StatusPill tone={VERDICT_TONE[row.verdict] || "gray"}>{row.verdict_label}</StatusPill>
        {row.segment_name ? <span>{row.segment_name}</span> : null}
        {row.sample_size ? <span>{count(row.sample_size, "prospect")}</span> : null}
      </div>
      <p>{row.result || "No result recorded yet."}</p>
      <CardActions record={row} {...actions} canVerify={false} />
    </article>
  );
}

// A tile is an invitation, and it earns the room by naming the thing being
// asked for. When it also owns a list, it shows the count — so the client can
// see they have already answered rather than being asked again.
function AddTile({ icon: Icon, label, hint, onClick, badge }) {
  return (
    <button className="card lib-add" onClick={onClick}>
      <span className="lib-add-label"><Icon size={15} /> {label}</span>
      {hint ? <span className="lib-add-hint">{hint}</span> : null}
      {badge ? <span className="lib-add-badge">{badge}</span> : null}
    </button>
  );
}

// ---------------------------------------------------------------- forms
function Field({ label, hint, children }) {
  return (
    <label className="lib-field">
      <span>{label}{hint ? <em>{hint}</em> : null}</span>
      {children}
    </label>
  );
}

function CaseStudyForm({ row, isClient, onSave, onClose }) {
  const [form, setForm] = useState(() => ({
    client_name: row?.client_name || "", engagement: row?.engagement || "",
    segment: row?.segment || "", year: row?.year || "", outcome: row?.outcome || "",
    source: row?.source === "verified" ? "verified" : "operator",
    source_url: row?.source_url || "", note: row?.note || "",
  }));
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const [saving, setSaving] = useState(false);
  const needsLink = !isClient && form.source === "verified" && !form.source_url.trim();
  const ready = form.client_name.trim() && form.outcome.trim() && !needsLink;
  const submit = async () => {
    setSaving(true);
    const ok = await onSave({
      ...form, year: form.year ? Number(form.year) : null,
      ...(row ? {} : { source: isClient ? undefined : form.source }),
    });
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <div className="lib-form">
      <Field label="Client" hint="the name we would put in an email">
        <Input value={form.client_name} onChange={set("client_name")} placeholder="Kaya" autoFocus />
      </Field>
      <Field label="Engagement"><Input value={form.engagement} onChange={set("engagement")}
        placeholder="full rebrand" /></Field>
      <Field label="Segment"><Input value={form.segment} onChange={set("segment")}
        placeholder="Consumer" /></Field>
      <Field label="Year"><Input value={form.year} onChange={set("year")} placeholder="2024"
        inputMode="numeric" /></Field>
      <Field label="Result" hint="with the numbers the copy may use">
        <Area size="md" value={form.outcome} onChange={set("outcome")}
          placeholder="3.1x inbound enquiries within 6 months of launch." />
      </Field>
      {isClient ? (
        <p className="lib-form-note">
          Anything you add is tagged <b>client-supplied</b>. We can use it as background
          straight away, and once we can point at something public we mark it verified —
          which is when an email is allowed to name you.
        </p>
      ) : (
        <>
          <Field label="Source">
            <Select value={form.source} onChange={set("source")}>
              {SOURCE_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </Select>
          </Field>
          <Field label="Link" hint="required to verify">
            <Input value={form.source_url} onChange={set("source_url")}
              placeholder="https://example.com/case-study" />
          </Field>
        </>
      )}
      <div className="lib-form-acts">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={saving} disabled={!ready} onClick={submit}>
          {row ? "Save changes" : "Add to Library"}
        </Button>
      </div>
    </div>
  );
}

function SegmentForm({ row, isClient, lists, onSave, onClose }) {
  const [form, setForm] = useState(() => ({
    name: row?.name || "", company_type: row?.company_type || "",
    headcount: row?.headcount || "", geography: row?.geography || "",
    tam_estimate: row?.tam_estimate ?? "", tam_note: row?.tam_note || "",
    enrich_list_id: row?.enrich_list_id ? String(row.enrich_list_id) : "",
    source: row?.source === "verified" ? "verified" : "operator", source_url: row?.source_url || "",
  }));
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    setSaving(true);
    const ok = await onSave({
      ...form,
      tam_estimate: form.tam_estimate === "" ? null : Number(form.tam_estimate),
      enrich_list_id: form.enrich_list_id ? Number(form.enrich_list_id) : null,
      ...(isClient ? { source: undefined } : {}),
    });
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <div className="lib-form">
      <Field label="Segment"><Input value={form.name} onChange={set("name")}
        placeholder="Founder-led agencies, 10-50 staff" autoFocus /></Field>
      <Field label="Type of company"><Input value={form.company_type} onChange={set("company_type")}
        placeholder="Independent creative agencies" /></Field>
      <Field label="Headcount"><Input value={form.headcount} onChange={set("headcount")}
        placeholder="10-50" /></Field>
      <Field label="Geography"><Input value={form.geography} onChange={set("geography")}
        placeholder="UK & Ireland" /></Field>
      <Field label="How many exist" hint="the sourced figure, not a guess">
        <Input value={form.tam_estimate} onChange={set("tam_estimate")} inputMode="numeric"
          placeholder="400" />
      </Field>
      <Field label="Prospect list" hint="the in-list count is read from it">
        <Select value={form.enrich_list_id} onChange={set("enrich_list_id")}>
          <option value="">Not in a list yet</option>
          {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </Select>
      </Field>
      <Field label="How the figure was arrived at">
        <Area size="sm" value={form.tam_note} onChange={set("tam_note")}
          placeholder="Companies House SIC 73110, filtered to 10-50 employees." />
      </Field>
      {!isClient && (
        <Field label="Source">
          <Select value={form.source} onChange={set("source")}>
            {SOURCE_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </Select>
        </Field>
      )}
      <div className="lib-form-acts">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={saving} disabled={!form.name.trim()} onClick={submit}>
          {row ? "Save changes" : "Add segment"}
        </Button>
      </div>
    </div>
  );
}

function IcpTestForm({ row, isClient, segments, onSave, onClose }) {
  const [form, setForm] = useState(() => ({
    hypothesis: row?.hypothesis || "", verdict: row?.verdict || "testing",
    result: row?.result || "", sample_size: row?.sample_size ?? "",
    segment_id: row?.segment_id ? String(row.segment_id) : "",
  }));
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const [saving, setSaving] = useState(false);
  const needsResult = form.verdict !== "testing" && !form.result.trim();
  const submit = async () => {
    setSaving(true);
    const ok = await onSave({
      ...form,
      sample_size: form.sample_size === "" ? null : Number(form.sample_size),
      segment_id: form.segment_id ? Number(form.segment_id) : null,
      ...(isClient ? { source: undefined } : {}),
    });
    setSaving(false);
    if (ok) onClose();
  };
  return (
    <div className="lib-form">
      <Field label="Hypothesis" hint="what you expected to be true">
        <Area size="sm" value={form.hypothesis} onChange={set("hypothesis")}
          placeholder="Operations leads reply more than founders at 50-200 staff." autoFocus />
      </Field>
      <Field label="Verdict">
        <Select value={form.verdict} onChange={set("verdict")}>
          <option value="testing">Testing — still open</option>
          <option value="validated">Validated</option>
          <option value="killed">Killed</option>
        </Select>
      </Field>
      <Field label="Prospects tested"><Input value={form.sample_size} onChange={set("sample_size")}
        inputMode="numeric" placeholder="120" /></Field>
      <Field label="Segment">
        <Select value={form.segment_id} onChange={set("segment_id")}>
          <option value="">Not tied to one segment</option>
          {segments.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
      </Field>
      <Field label="Result" hint={needsResult ? "required to decide a test" : "what happened"}>
        <Area size="md" value={form.result} onChange={set("result")}
          placeholder="4.1% reply rate against 1.2% for founders, across 120 prospects." />
      </Field>
      <div className="lib-form-acts">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={saving} disabled={!form.hypothesis.trim() || needsResult} onClick={submit}>
          {row ? "Save changes" : "Add test"}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- side lists
// Exclusions and objections are Library material too, but they are lists rather
// than cards — nobody reads a do-not-contact list, they check it. So they live
// behind the tile that writes to them instead of taking a tab.
function ListPanel({ kind, data, canEdit, onAdd, onRemove, onClose }) {
  const isExclusion = kind === "exclusion";
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const rows = isExclusion ? data.exclusions : data.objections;
  const add = async () => {
    setSaving(true);
    const ok = await onAdd(isExclusion
      ? { value, reason, kind: value.includes("@") ? "email" : "domain" }
      : { objection: value, response: reason });
    setSaving(false);
    if (ok) { setValue(""); setReason(""); }
  };
  return (
    <Drawer className="lib-panel"
      title={isExclusion ? "Accounts we should not contact" : "Objections you hear on calls"}
      onClose={onClose}>
      <p className="lib-panel-lead">
        {isExclusion
          ? "Existing customers, live deals, competitors, anyone off-limits. Applied before we research an account, so an excluded company costs nothing."
          : "What comes back on calls, and the answer that works. The writer reads these, so an objection you name here stops turning up in the copy unanswered."}
      </p>
      {canEdit && (
        <div className="lib-panel-add">
          <Input value={value} onChange={(e) => setValue(e.target.value)}
            placeholder={isExclusion ? "acme.com" : "We already have an SDR team."} />
          <Input value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={isExclusion ? "existing customer" : "the answer that lands"} />
          <Button loading={saving} disabled={!value.trim()} onClick={add} icon={Plus}>Add</Button>
        </div>
      )}
      {!rows.length ? (
        <EmptyState icon={isExclusion ? Ban : MessageSquareWarning}
          title={isExclusion ? "Nothing is excluded yet" : "No objections recorded yet"}
          hint={isExclusion
            ? "Every account here is skipped before research runs."
            : "Two or three real ones change the copy more than a rewrite does."} />
      ) : (
        <ul className="lib-panel-list">
          {rows.map((row, i) => (
            <li key={row.id || i}>
              <div>
                <b>{isExclusion ? (row.label || row.value) : row.objection}</b>
                <span>{isExclusion
                  ? [row.kind, row.reason].filter(Boolean).join(" · ")
                  : row.response || "No answer recorded."}</span>
              </div>
              <StatusPill tone={SOURCE_TONE[row.source] || "gray"}>{row.source_label}</StatusPill>
              {canEdit && isExclusion && (
                <button className="lib-panel-del" onClick={() => onRemove(row)} title="Remove">
                  <Trash2 size={14} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}

// ---------------------------------------------------------------- page
const ENDPOINT = { case_study: "case-studies", segment: "segments", icp_test: "icp-tests" };
const FORM_TITLE = {
  case_study: "case study", segment: "segment", icp_test: "ICP test",
};

export default function Library() {
  const { wsParam } = useAuth();
  const { previewing } = useClientView();
  const toast = useToast();
  const addRef = useRef(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("case_studies");
  const [editing, setEditing] = useState(null);   // {kind, row}
  const [panel, setPanel] = useState(null);       // "exclusion" | "objection"
  const [filing, setFiling] = useState(false);

  const load = useCallback(() => {
    setError("");
    api("/api/library", { params: { workspace_id: wsParam } })
      .then(setData).catch((e) => setError(e.message));
  }, [wsParam]);
  useEffect(() => { load(); }, [load]);

  const body = (extra) => ({ workspace_id: wsParam ? Number(wsParam) : null, ...extra });

  // Every write returns the whole page, so the screen never has to guess what
  // the server did with it — a usage count that moved comes back moved.
  const write = async (path, options, okMessage) => {
    try {
      const next = await api(path, options);
      setData(next);
      if (okMessage) toast(okMessage);
      return true;
    } catch (e) { toast(e.message, "bad"); return false; }
  };

  const save = (kind, row) => async (fields) => {
    // Only `undefined` is dropped — that is how a form says "the server decides
    // this one" (a client cannot set `source`). An empty string is a real edit:
    // it is how somebody clears a field they filled in by mistake.
    const clean = Object.fromEntries(
      Object.entries(fields).filter(([, value]) => value !== undefined));
    return row
      ? write(`/api/library/${ENDPOINT[kind]}/${row.id}`, { method: "PATCH", body: clean },
              "Saved.")
      : write(`/api/library/${ENDPOINT[kind]}`, { method: "POST", body: body(clean) },
              "Added to the Library.");
  };

  // Verification needs a link, and asking for it in the flow beats sending
  // somebody to the edit form to discover the requirement there.
  const verify = async (kind, row) => {
    const url = (row.source_url || await promptDialog(
      `Paste the page that backs up “${row.client_name || row.name}”.`,
      { title: "Verify this record", placeholder: "https://example.com/case-study",
        confirmText: "Verify" }) || "").trim();
    if (!url) return;
    await write(`/api/library/${ENDPOINT[kind]}/${row.id}/verify`,
                { method: "POST", body: { source_url: url } },
                "Verified. This can now be named in an email.");
  };

  const remove = async (kind, row) => {
    const name = row.client_name || row.name || row.hypothesis || row.value;
    if (!await confirmDialog(`Remove “${name}” from the Library?`, { danger: true })) return;
    await write(`/api/library/${ENDPOINT[kind]}/${row.id}`, { method: "DELETE" }, "Removed.");
  };

  const fileInbox = async () => {
    setFiling(true);
    const before = data.counts.unfiled;
    await write("/api/library/import-unfiled", { method: "POST", body: body() },
                `Filed ${count(before, "record")} from the client brain.`);
    setFiling(false);
  };

  const counts = data?.counts || {};
  const tabCount = { case_studies: counts.case_studies, segments: counts.segments,
                     icp_tests: counts.icp_tests };
  const canEdit = Boolean(data?.can_edit) && !previewing;
  const isClient = Boolean(data?.is_client) || previewing;
  const rows = useMemo(() => (data ? data[tab] || [] : []), [data, tab]);

  if (error) return <ErrorBox msg={error} retry={load} />;
  if (!data) {
    return (
      <div className="lib-grid">
        {[...Array(3)].map((_, i) => (
          <div className="card lib-card" key={i}>
            <Skeleton w="55%" h={16} />
            <Skeleton w="35%" style={{ marginTop: 12 }} />
            <Skeleton w="90%" style={{ marginTop: 14 }} />
          </div>
        ))}
      </div>
    );
  }
  if (!data.workspace) {
    return (
      <EmptyState icon={Building2} title="Choose a client"
        hint="A library belongs to one client. Pick a workspace in the switcher above." />
    );
  }

  const kindForTab = { case_studies: "case_study", segments: "segment", icp_tests: "icp_test" }[tab];
  const Card = { case_studies: CaseStudyCard, segments: SegmentCard, icp_tests: IcpTestCard }[tab];
  const emptyCopy = {
    case_studies: ["No proof in the Library yet",
      "Three case studies means thin, repetitive copy and a lot of prospects marked insufficient. Six means noticeably better emails. This is the highest-leverage thing to add."],
    segments: ["No segments defined yet",
      "A segment is a type of company, a size, a place, and how many of them exist. It is what the list is built from."],
    icp_tests: ["No tests recorded yet",
      "One hypothesis, what happened, and a verdict. Killed tests are kept, so next quarter does not retry them."],
  }[tab];

  return (
    <>
      <div className="plan-head">
        <div>
          <div className="plan-crumb">Client Space / Library</div>
          <h1>Library</h1>
          <p>Structured records, not free text. Everything here feeds the writer, which is why
            each item carries a source tag.</p>
        </div>
        {canEdit && (
          <div className="acts" ref={addRef}>
            <Button icon={Plus} onClick={() => setEditing({ kind: kindForTab })}>Add</Button>
          </div>
        )}
      </div>

      {/* Ours, not the client's: proof still sitting in the brain's JSON. It is
          shown as work to do rather than absorbed quietly, because filing it
          stamps provenance and moves the angles that point at it. */}
      {!isClient && counts.unfiled > 0 && (
        <div className="lib-inbox">
          <span className="icon"><Inbox size={16} /></span>
          <div>
            <b>{count(counts.unfiled, "piece")} of proof is still only in the client brain</b>
            <span>Filing it creates real records with a source and moves any angle pointing at
              them, so nothing is orphaned.</span>
          </div>
          {canEdit && <Button size="sm" loading={filing} onClick={fileInbox}>File it</Button>}
        </div>
      )}

      <div className="plan-tabs">
        {TABS.map(([key, label, Icon]) => (
          <button key={key} className={`plan-tab ${tab === key ? "on" : ""}`}
            onClick={() => setTab(key)}>
            <Icon size={14} /> {label}
            {tabCount[key] ? <span className="lib-tabcount">{tabCount[key]}</span> : null}
          </button>
        ))}
        <span className="plan-tabs-spacer" />
        {tab === "case_studies" && counts.case_studies > 0 && (
          <span className="lib-tabnote">
            {counts.verified_case_studies} of {counts.case_studies} verified
            {counts.needs_verification
              ? ` · ${counts.needs_verification} usable as background only`
              : " · all nameable in copy"}
          </span>
        )}
      </div>

      {!rows.length ? (
        <EmptyState icon={{ case_studies: Layers, segments: Building2, icp_tests: FlaskConical }[tab]}
          title={emptyCopy[0]} hint={emptyCopy[1]}
          action={canEdit
            ? <Button icon={Plus} onClick={() => setEditing({ kind: kindForTab })}>
                Add the first one
              </Button>
            : null} />
      ) : (
        <div className="lib-grid">
          {rows.map((row) => (
            <Card key={row.id} row={row} canEdit={canEdit}
              canVerify={Boolean(data.can_verify)}
              onEdit={() => setEditing({ kind: kindForTab, row })}
              onVerify={() => verify(kindForTab, row)}
              onDelete={() => remove(kindForTab, row)} />
          ))}
        </div>
      )}

      {/* The contribution surface. Present on every tab, because the answer to
          "what should I do here" does not change with which tab is open. */}
      {canEdit && (
        <div className="lib-grid lib-tiles">
          <AddTile icon={Layers} label="Add a case study"
            hint="Named client, result, and a link if it is public"
            onClick={() => setEditing({ kind: "case_study" })} />
          <AddTile icon={Ban} label="Add an account we should not contact"
            hint="Skipped before we research it, so it costs nothing"
            badge={counts.exclusions ? count(counts.exclusions, "account") : ""}
            onClick={() => setPanel("exclusion")} />
          <AddTile icon={MessageSquareWarning} label="Add an objection you hear on calls"
            hint="The writer reads these and answers them"
            badge={counts.objections ? count(counts.objections, "objection") : ""}
            onClick={() => setPanel("objection")} />
        </div>
      )}

      {isClient && counts.needs_verification > 0 && (
        <div className="cs-note">
          <ShieldQuestion size={15} />
          <span>
            {count(counts.needs_verification, "record")} you gave us
            {counts.needs_verification === 1 ? " is" : " are"} in use as background. We cannot
            name you or your clients in an email until there is something public to point at,
            so a link is the single most useful thing you can add.
          </span>
        </div>
      )}
      {isClient && counts.verified_case_studies > 0 && counts.needs_verification === 0 && (
        <div className="cs-note">
          <CheckCircle2 size={15} />
          <span>Every case study here is verified, so all of them can be named in copy.</span>
        </div>
      )}

      <AnimatePresence>
        {editing && (
          <Modal originRef={addRef} onClose={() => setEditing(null)}
            title={`${editing.row ? "Edit" : "Add a"} ${FORM_TITLE[editing.kind]}`}>
            {editing.kind === "case_study" && (
              <CaseStudyForm row={editing.row} isClient={isClient}
                onSave={save("case_study", editing.row)} onClose={() => setEditing(null)} />
            )}
            {editing.kind === "segment" && (
              <SegmentForm row={editing.row} isClient={isClient} lists={data.lists || []}
                onSave={save("segment", editing.row)} onClose={() => setEditing(null)} />
            )}
            {editing.kind === "icp_test" && (
              <IcpTestForm row={editing.row} isClient={isClient} segments={data.segments || []}
                onSave={save("icp_test", editing.row)} onClose={() => setEditing(null)} />
            )}
          </Modal>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {panel && (
          <ListPanel kind={panel} data={data} canEdit={canEdit} onClose={() => setPanel(null)}
            onAdd={(fields) => write(
              panel === "exclusion" ? "/api/library/exclusions" : "/api/library/objections",
              { method: "POST", body: body(fields) },
              panel === "exclusion" ? "Excluded. It will be skipped before research."
                                    : "Added. The writer reads this now.")}
            onRemove={(row) => write(`/api/library/exclusions/${row.id}`, { method: "DELETE" },
                                     "Removed from the exclusion list.")} />
        )}
      </AnimatePresence>
    </>
  );
}
