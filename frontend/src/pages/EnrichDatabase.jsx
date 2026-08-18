// Outbound → Database: every lead across all lists in the workspace.
// Premium redesign (Linear/Attio/Clay). Frontend-only — all data, filtering,
// and pagination logic is preserved exactly.
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Database, Download, Upload, Search, Filter, ArrowUpDown, Columns3, Bookmark,
  Rows3, MoreHorizontal, CheckCircle2, ShieldCheck, Sparkles, Target,
} from "lucide-react";
import { useAuth } from "../auth";
import { enrichBase } from "../clientspace/modules";
import { ErrorBox, Metric, PageHeader, SkeletonRows, StatusBadge, useApi } from "../components";

// view key → [label, dot color]  (preserves existing filter keys)
const TABS = [
  ["all", "All", "#98A2B3"],
  ["enriched", "Enriched", "#2E90FA"],
  ["verified", "Verified", "#12B76A"],
  ["nonicp", "Non-ICP", "#F79009"],
  ["invalid", "Invalid", "#F04438"],
  ["unsafe", "Unsafe", "#F04438"],
  ["notrun", "Not run", "#98A2B3"],
];
const STATUS_TONE = { done: "green", enriched: "blue", verified: "green", invalid: "red",
  unsafe: "red", skipped: "amber", error: "red", "not run": "gray" };
const statusLabel = (s) => s || "not run";
const icpTone = (d) => (d === "ICP" ? "green" : d === "Non-ICP" ? "amber" : "indigo");
const initials = (s) => (s || "?").trim().slice(0, 2).toUpperCase();

export default function EnrichDatabase() {
  // Mounted at two bases — `/enrichment` for us, `/w/<slug>/enrichment` for the
  // client — so links resolve from the URL this screen was opened at.
  const base = enrichBase(useLocation().pathname);
  const { wsParam, me } = useAuth();
  const nav = useNavigate();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [view, setView] = useState("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState({});
  const { data, error, loading, reload } = useApi(wsId ? `/api/enrich-lists/database/${wsId}` : null,
    { view, q, page });

  if (!wsId) {
    return (
      <>
        <PageHeader title="Database" desc="Manage, enrich, verify, and qualify every lead across your workspaces." />
        <ErrorBox msg="Pick a specific workspace (top-left) to see its lead database." />
      </>
    );
  }

  const chips = data?.chips || {};
  const pages = data ? Math.max(1, Math.ceil(data.total_in_view / 50)) : 1;
  const leads = data?.leads || [];
  const selIds = Object.keys(sel).filter((k) => sel[k]);
  const allChecked = leads.length > 0 && selIds.length === leads.length;

  const actions = (
    <>
      <button className="hbtn ghost" title="Export the current view (per-list export lives on each List)" disabled>
        <Download size={16} /> Export
      </button>
      <button className="hbtn primary" onClick={() => nav(base)} title="Create a list and import a CSV">
        <Upload size={16} /> Import leads
      </button>
    </>
  );

  return (
    <>
      <PageHeader title="Database"
        desc="Manage, enrich, verify, and qualify every lead across your workspaces."
        actions={actions} />

      {/* summary metrics */}
      <div className="metrics">
        <Metric icon={<Database size={17} />} label="Total leads" value={(chips.all ?? 0).toLocaleString()} />
        <Metric icon={<Sparkles size={17} />} label="Enriched" value={(chips.enriched ?? 0).toLocaleString()}
          sub={chips.all ? `${Math.round(((chips.enriched || 0) / chips.all) * 100)}% of database` : ""} />
        <Metric icon={<ShieldCheck size={17} />} label="Verified" value={(chips.verified ?? 0).toLocaleString()} />
        <Metric icon={<Target size={17} />} label="ICP matches"
          value={((chips.all ?? 0) - (chips.nonicp ?? 0) - (chips.notrun ?? 0)).toLocaleString()}
          sub={chips.nonicp ? `${(chips.nonicp).toLocaleString()} non-ICP` : ""} />
      </div>

      <div className="surface">
        {/* status tabs */}
        <div className="dt-tabs">
          {TABS.map(([v, label, dot]) => (
            <button key={v} className={`dt-tab ${view === v ? "on" : ""}`}
              onClick={() => { setView(v); setPage(1); setSel({}); }}>
              <span className="tdot" style={{ background: dot }} />{label}
              <span className="cnt">{(chips[v] ?? 0).toLocaleString()}</span>
            </button>
          ))}
        </div>

        {/* toolbar */}
        <div className="dt-toolbar">
          <div className="dt-search">
            <Search size={16} />
            <input type="text" placeholder="Search leads, companies, domains…"
              value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <div style={{ flex: 1 }} />
          <button className="dt-tool" disabled title="Advanced filters (coming soon)"><Filter size={15} /> Filters</button>
          <button className="dt-tool" disabled title="Sort (coming soon)"><ArrowUpDown size={15} /> Sort</button>
          <button className="dt-tool" disabled title="Choose columns (coming soon)"><Columns3 size={15} /> Columns</button>
          <button className="dt-tool" disabled title="Saved views (coming soon)"><Bookmark size={15} /> Saved view</button>
          <button className="dt-tool" disabled title="Row density (coming soon)"><Rows3 size={15} /> Density</button>
        </div>

        {/* bulk bar */}
        {selIds.length > 0 && (
          <div className="bulkbar">
            <b>{selIds.length} selected</b>
            <span style={{ color: "var(--muted)" }}>Bulk actions are available per-list on the Lists screen.</span>
            <div style={{ flex: 1 }} />
            <button className="dt-tool" onClick={() => setSel({})}>Clear</button>
          </div>
        )}

        {/* table / states */}
        {error ? (
          <div style={{ padding: 20 }}><ErrorBox msg={error} retry={reload} /></div>
        ) : (
          <>
            <div className="dt-scroll">
              <table className="dt">
                <thead>
                  <tr>
                    <th className="checkbox-cell">
                      <input type="checkbox" checked={allChecked}
                        onChange={(e) => setSel(e.target.checked ? Object.fromEntries(leads.map((l) => [l.id, true])) : {})} />
                    </th>
                    <th>Lead</th><th>Company</th><th>List</th><th>ESP</th>
                    <th>ICP fit</th><th>Industry</th><th>Status</th><th style={{ width: 44 }} />
                  </tr>
                </thead>
                <tbody>
                  {loading && <SkeletonRows cols={9} rows={9} />}
                  {!loading && leads.map((l) => (
                    <tr key={l.id} className={sel[l.id] ? "sel" : ""}>
                      <td className="checkbox-cell">
                        <input type="checkbox" checked={!!sel[l.id]}
                          onChange={(e) => setSel({ ...sel, [l.id]: e.target.checked })} />
                      </td>
                      <td>
                        <div className="lead-nm">{l.name || l.email || "—"}</div>
                        {l.name && l.email && <div className="lead-sub">{l.email}</div>}
                      </td>
                      <td>
                        {l.company ? (
                          <div className="co"><span className="co-av">{initials(l.company)}</span>
                            <span className="trunc">{l.company}</span></div>
                        ) : <span style={{ color: "var(--muted2)" }}>—</span>}
                      </td>
                      <td style={{ color: "var(--muted)", fontSize: 12.5 }}><span className="trunc">{l.list_name || "—"}</span></td>
                      <td>{l.esp ? <StatusBadge tone="gray">{l.esp}</StatusBadge> : <span style={{ color: "var(--muted2)" }}>—</span>}</td>
                      <td>{l.icp_decision ? <StatusBadge tone={icpTone(l.icp_decision)}>{l.icp_decision}</StatusBadge> : <span style={{ color: "var(--muted2)" }}>—</span>}</td>
                      <td style={{ fontSize: 12.5 }}><span className="trunc">{l.industry || "—"}</span></td>
                      <td><StatusBadge tone={STATUS_TONE[statusLabel(l.status)] || "gray"}>{statusLabel(l.status)}</StatusBadge></td>
                      <td><button className="rowact" title="More" disabled><MoreHorizontal size={16} /></button></td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {!loading && leads.length === 0 && (
                <div className="emptystate">
                  <div className="ei"><Database size={22} /></div>
                  <h3>{view === "all" ? "Your lead database is empty" : "Nothing in this view"}</h3>
                  <p>{view === "all"
                    ? "Import a lead list to begin enriching, verifying, and qualifying prospects."
                    : "No leads match this filter yet. Run enrichment or switch views."}</p>
                  <div className="ea">
                    <button className="hbtn primary" onClick={() => nav(base)}><Upload size={16} /> Import leads</button>
                    <button className="hbtn ghost" onClick={() => setView("all")}>View all leads</button>
                  </div>
                </div>
              )}
            </div>

            {/* pagination footer */}
            <div className="pager">
              <div>{selIds.length} {selIds.length === 1 ? "lead" : "leads"} selected</div>
              <div className="pr">
                <span>{data ? `${data.total_in_view.toLocaleString()} leads · page ${page} of ${pages}` : ""}</span>
                <button className="pgbtn" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
                <button className="pgbtn" disabled={page >= pages} onClick={() => setPage(page + 1)}>›</button>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
