// Client Space · Boards & Tables.
//
// Three fixed, live projections over records the engine already owns. There is
// no view builder, column chooser, saved-view system or manual record creation
// here: clients come to inspect outcomes, not configure a database product.
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  Building2, CalendarCheck2, Download, Handshake, SearchX, ShieldCheck, Users,
} from "lucide-react";
import { api, money, timeAgo } from "../../api";
import { useAuth } from "../../auth";
import {
  Button, EmptyState, ErrorBox, SearchInput, SkeletonRows, StatusBadge, useToast,
} from "../../components";

const DATASETS = {
  prospects: {
    label: "Prospects", icon: Users,
    description: "The outreach list, from verification through first contact.",
    search: "Search companies, people, or email…",
    chips: [
      ["verified", "Verified", (row) => row.verified],
      ["researched", "Researched", (row) => row.researched],
      ["contacted", "Contacted", (row) => row.contacted],
    ],
  },
  meetings: {
    label: "Meetings", icon: CalendarCheck2,
    description: "Booked meetings and their outcomes. Quality stays one click away.",
    search: "Search meetings, companies, or people…",
    chips: [
      ["qualified", "Qualified", (row) => row.quality === "qualified"],
      ["no_show", "No show", (row) => row.quality === "no_show"],
      ["no_update", "No update", (row) => row.quality === "no_update"],
    ],
  },
  deals: {
    label: "Deals", icon: Handshake,
    description: "Every opportunity, stage, and value in the pipeline.",
    search: "Search deals, companies, or stages…",
    chips: [
      ["open", "Open", (row) => row.stage_state === "open"],
      ["won", "Won", (row) => row.stage_state === "won"],
      ["lost", "Lost", (row) => row.stage_state === "lost"],
    ],
  },
};

const QUALITY = {
  qualified: { label: "Qualified", tone: "green" },
  no_show: { label: "No show", tone: "gray" },
  no_update: { label: "No update", tone: "amber" },
};

const text = (value) => String(value ?? "").toLowerCase();
const domain = (value) => String(value || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
const href = (value) => value && (/^https?:\/\//i.test(value) ? value : `https://${value}`);
const when = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(date);
};
const cell = (value) => value || <span className="bt-empty">—</span>;

function QualitySelect({ row, disabled, saving, onSave }) {
  return (
    <label className={`bt-quality q-${row.quality} ${saving ? "saving" : ""}`}>
      <span className="bt-quality-dot" />
      <select aria-label={`Quality for ${row.company}`} value={row.quality}
        disabled={disabled || saving} onChange={(event) => onSave(row.id, { quality: event.target.value })}>
        {Object.entries(QUALITY).map(([key, item]) => (
          <option key={key} value={key}>{item.label}</option>
        ))}
      </select>
    </label>
  );
}

function RemarksInput({ row, disabled, saving, onSave }) {
  const [value, setValue] = useState(row.remarks || "");
  useEffect(() => setValue(row.remarks || ""), [row.remarks]);
  const commit = () => value.trim() !== (row.remarks || "").trim()
    && onSave(row.id, { remarks: value });
  return (
    <input className="bt-remarks" aria-label={`Remarks for ${row.company}`}
      value={value} disabled={disabled || saving} placeholder={disabled ? "—" : "Add a remark…"}
      onChange={(event) => setValue(event.target.value)} onBlur={commit}
      onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
  );
}

function ProspectRows({ rows }) {
  return rows.map((row) => (
    <tr key={row.id}>
      <td><b className="bt-company">{cell(row.company)}</b></td>
      <td>{row.website ? <a className="bt-link" href={href(row.website)} target="_blank" rel="noreferrer">{domain(row.website)}</a> : cell()}</td>
      <td><span>{cell(row.contact)}</span>{row.title && <em className="bt-sub">{row.title}</em>}</td>
      <td>{row.email ? <a className="bt-link" href={`mailto:${row.email}`}>{row.email}</a> : cell()}</td>
      <td><StatusBadge tone={row.verified ? "green" : "gray"}>{row.verified ? "Verified" : "Pending"}</StatusBadge></td>
      <td><StatusBadge tone={row.researched ? "blue" : "gray"}>{row.researched ? "Ready" : "Pending"}</StatusBadge></td>
      <td><StatusBadge tone={row.contacted ? "indigo" : "gray"}>{row.contacted ? "Contacted" : "Not contacted"}</StatusBadge></td>
    </tr>
  ));
}

function MeetingRows({ rows, canEdit, savingId, onSave }) {
  return rows.map((row) => (
    <tr key={row.id}>
      <td><b className="bt-company">{cell(row.company)}</b></td>
      <td>{row.website ? <a className="bt-link" href={href(row.website)} target="_blank" rel="noreferrer">{domain(row.website)}</a> : cell()}</td>
      <td>{cell(row.contact)}</td>
      <td>{row.email ? <a className="bt-link" href={`mailto:${row.email}`}>{row.email}</a> : cell()}</td>
      <td className="bt-date">{when(row.meeting_at)}</td>
      <td><QualitySelect row={row} disabled={!canEdit} saving={savingId === row.id} onSave={onSave} /></td>
      <td><span className={`bt-source ${row.source === "verified" ? "verified" : ""}`}>
        {row.source === "verified" && <ShieldCheck size={12} />}{row.source}
      </span></td>
      <td><RemarksInput row={row} disabled={!canEdit} saving={savingId === row.id} onSave={onSave} /></td>
    </tr>
  ));
}

function DealRows({ rows }) {
  return rows.map((row) => (
    <tr key={row.id}>
      <td><b className="bt-company">{cell(row.name)}</b></td>
      <td>{cell(row.company)}</td>
      <td><span>{cell(row.contact)}</span>{row.email && <em className="bt-sub">{row.email}</em>}</td>
      <td><span className="bt-stage"><i style={{ background: row.stage_color }} />{row.stage}</span></td>
      <td className="bt-value">{money(row.value)}</td>
      <td>{cell(row.next_step)}</td>
      <td className="bt-date">{row.updated_at ? timeAgo(row.updated_at) : "—"}</td>
    </tr>
  ));
}

const HEADERS = {
  prospects: ["Company", "Website", "Contact", "Email", "Verification", "Research", "Outreach"],
  meetings: ["Company", "Website", "Contact", "Email", "Meeting", "Quality", "Source", "Remarks"],
  deals: ["Deal", "Company", "Contact", "Stage", "Value", "Next step", "Updated"],
};

const exportRows = {
  prospects: (row) => [row.company, row.website, row.contact, row.email, row.verified ? "Verified" : "Pending",
    row.researched ? "Ready" : "Pending", row.contacted ? "Contacted" : "Not contacted"],
  meetings: (row) => [row.company, row.website, row.contact, row.email, row.meeting_at,
    QUALITY[row.quality]?.label || "No update", row.source, row.remarks],
  deals: (row) => [row.name, row.company, row.contact, row.stage, row.value, row.next_step, row.updated_at],
};

const csvCell = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;

export default function Boards() {
  const { dataset: routeDataset } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const { wsParam } = useAuth();
  const dataset = DATASETS[routeDataset] ? routeDataset : "meetings";
  const config = DATASETS[dataset];
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [savingId, setSavingId] = useState(null);

  const load = () => {
    setError("");
    api("/api/client-space/boards", { params: { workspace_id: wsParam } })
      .then(setData).catch((err) => setError(err.message));
  };
  useEffect(load, [wsParam]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setFilter(""); setQuery(""); }, [dataset]);

  const rows = data?.[dataset] || [];
  const chips = config.chips.map(([key, label, test]) => ({
    key, label, test, count: rows.filter(test).length,
  }));
  const filtered = useMemo(() => {
    const chip = chips.find((item) => item.key === filter);
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => (!chip || chip.test(row)) && (!needle || [
      row.company, row.name, row.website, row.contact, row.email, row.stage,
      row.next_step, row.remarks,
    ].some((value) => text(value).includes(needle))));
  }, [rows, filter, query]); // eslint-disable-line react-hooks/exhaustive-deps

  const boardsRoot = location.pathname.slice(0, location.pathname.indexOf("/boards") + 7);
  const changeDataset = (key) => navigate(key === "meetings" ? boardsRoot : `${boardsRoot}/${key}`);

  const saveMeeting = async (id, patch) => {
    const previous = data.meetings.find((row) => row.id === id);
    setSavingId(id);
    setData((current) => ({ ...current, meetings: current.meetings.map((row) => (
      row.id === id ? { ...row, ...patch, remarks: patch.remarks?.trim() ?? row.remarks } : row
    )) }));
    try {
      const saved = await api(`/api/client-space/boards/meetings/${id}`, { method: "PATCH", body: patch });
      setData((current) => ({ ...current, meetings: current.meetings.map((row) => (
        row.id === id ? { ...row, ...saved } : row
      )) }));
    } catch (err) {
      setData((current) => ({ ...current, meetings: current.meetings.map((row) => (
        row.id === id ? previous : row
      )) }));
      toast(err.message, "bad");
    } finally { setSavingId(null); }
  };

  const download = () => {
    const csv = [HEADERS[dataset], ...filtered.map(exportRows[dataset])]
      .map((row) => row.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `${dataset}.csv`; anchor.click(); URL.revokeObjectURL(url);
  };

  if (error) return <ErrorBox msg={error} retry={load} />;
  if (data && !data.workspace) {
    return <EmptyState icon={Building2} title="Choose a client"
      hint="Prospects, meetings, and deals belong to one client. Pick a workspace above." />;
  }

  return (
    <div className="bt-page">
      <header className="bt-head">
        <div className="bt-crumb">Workspace / Boards &amp; Tables / {config.label}</div>
        <h1>{config.label}</h1>
        <p>{config.description}</p>
      </header>

      <div className="bt-datasets" role="tablist" aria-label="Boards and tables">
        {Object.entries(DATASETS).map(([key, item]) => {
          const Icon = item.icon;
          return (
            <button key={key} role="tab" aria-selected={dataset === key}
              className={dataset === key ? "on" : ""} onClick={() => changeDataset(key)}>
              <Icon size={15} />{item.label}<span>{data?.[key]?.length ?? "—"}</span>
            </button>
          );
        })}
      </div>

      <section className="surface bt-surface">
        <div className="bt-toolbar">
          <SearchInput value={query} onChange={setQuery} placeholder={config.search} />
          <div className="bt-chips" aria-label={`${config.label} filters`}>
            {chips.map((chip) => (
              <button key={chip.key} className={filter === chip.key ? `on ${chip.key}` : chip.key}
                aria-pressed={filter === chip.key}
                onClick={() => setFilter((current) => current === chip.key ? "" : chip.key)}>
                {chip.label} <span>{chip.count}</span>
              </button>
            ))}
          </div>
          <Button variant="secondary" icon={Download} onClick={download} disabled={!filtered.length}>Export</Button>
        </div>

        <div className="bt-table-wrap">
          <table className={`bt-table bt-${dataset}`} aria-label={`${config.label} table`}>
            <thead><tr>{HEADERS[dataset].map((header) => <th key={header}>{header}</th>)}</tr></thead>
            <tbody>
              {!data ? <SkeletonRows cols={HEADERS[dataset].length} rows={8} /> : !filtered.length ? (
                <tr><td colSpan={HEADERS[dataset].length}>
                  <EmptyState icon={SearchX} title={rows.length ? "No matching records" : `No ${dataset} yet`}
                    hint={rows.length ? "Clear the search or select the active filter again." :
                      dataset === "meetings" ? "Meetings appear here automatically when they are booked."
                        : `Live ${dataset} will appear here automatically.`} />
                </td></tr>
              ) : dataset === "prospects" ? <ProspectRows rows={filtered} />
                : dataset === "meetings" ? <MeetingRows rows={filtered} canEdit={data.can_update_meetings}
                  savingId={savingId} onSave={saveMeeting} />
                  : <DealRows rows={filtered} />}
            </tbody>
          </table>
        </div>
        <footer className="bt-footer">
          <span>{filtered.length.toLocaleString()} {filtered.length === 1 ? "record" : "records"}</span>
          <span>Live system data</span>
        </footer>
      </section>
    </div>
  );
}
