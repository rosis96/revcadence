// Enrichment list (DESIGN_SYSTEM.md step 4). Apollo Find-People philosophy:
// sticky left filter rail with live full-list counts, instant server-side
// filtering, one shared DataTable (server pagination), quick profile Drawer.
// All engine behavior (jobs, runs, clears, select-all-in-view) is unchanged.
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Download, Play, ShieldCheck, Square, Upload, Users } from "lucide-react";
import { api, getToken } from "../api";
import {
  Badge, Breadcrumbs, Button, DataTable, Drawer, ErrorBox, FilterPanel,
  PageHeader, Spinner, useApi, useDebounced, useToast,
} from "../components";

const VIEWS = [["all", "All"], ["processed", "Processed"], ["verified", "Verified"],
  ["enriched", "Enriched"], ["nonicp", "Non-ICP"], ["no_website", "No website"],
  ["invalid", "Invalid"], ["unsafe", "Unsafe"], ["notrun", "Not run"],
  ["title_rejected", "Title-rejected"]];
// Mailbox provider (MX-based) — segment for provider-aware sending / deliverability.
const ESP_VIEWS = [["esp_microsoft", "Microsoft"], ["esp_google", "Google"],
  ["esp_other", "Other"], ["esp_unknown", "Unknown"]];
const espTone = (e) => ({ Microsoft: "blue", Google: "green", Other: "gray" }[e] || "gray");

const stTone = { done: "green", invalid: "red", unsafe: "red", skipped: "amber", error: "red" };
const vTone = (v) => v === "ok" || v === "safe" || v === "valid" ? "green"
  : v === "role" || v === "catch_all" || v === "unknown" ? "amber"
  : v === "skipped" || !v ? "" : "red";

function parseCsv(text) {
  const rows = [];
  let cur = [""], inQ = false, row = cur;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQ) {
      if (ch === '"' && text[i + 1] === '"') { row[row.length - 1] += '"'; i++; }
      else if (ch === '"') inQ = false;
      else row[row.length - 1] += ch;
    } else if (ch === '"') inQ = true;
    else if (ch === ",") row.push("");
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [""]; rows.length && (cur = row);
    } else row[row.length - 1] += ch;
  }
  if (row.length > 1 || row[0] !== "") rows.push(row);
  const head = (rows.shift() || []).map((h) => h.trim().toLowerCase().replaceAll(" ", "_"));
  return rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

export default function EnrichListDetail() {
  const { id } = useParams();
  const toast = useToast();
  const fileRef = useRef(null);
  const [view, setView] = useState("all");
  const [page, setPage] = useState(1);
  const [qRaw, setQRaw] = useState("");
  const q = useDebounced(qRaw, 250);
  const [allInView, setAllInView] = useState(false);
  const [selIds, setSelIds] = useState([]);
  const [limit, setLimit] = useState(10);
  const [workers, setWorkers] = useState(10);
  const [job, setJob] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [openLead, setOpenLead] = useState(null);
  const [outputs, setOutputs] = useState(null);
  const { data, error, loading, reload } = useApi(`/api/enrich-lists/${id}/leads`,
    { view, page, q, page_size: 50 });
  const { data: reoon } = useApi("/api/enrich-lists/reoon/balance");
  const cfg = useApi(data ? `/api/enrich-lists/config/${data.list.workspace_id}` : null);

  useEffect(() => { setPage(1); }, [q, view]);

  // reconnect to a run already in progress
  useEffect(() => {
    if (!data || job) return;
    api(`/api/enrich-lists/${id}/active-job`).then((r) => { if (r.job_id) setJob(r.job_id); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.list?.id]);

  // live job progress poll
  useEffect(() => {
    if (!job) return;
    const t = setInterval(async () => {
      try {
        const s = await api(`/api/jobs/${job}/status`);
        setJobStatus(s);
        if (["done", "failed", "cancelled"].includes(s.status)) { clearInterval(t); setJob(null); reload(); }
      } catch { clearInterval(t); setJob(null); }
    }, 2500);
    return () => clearInterval(t);
  }, [job, reload]);

  const selectedCount = allInView ? (data?.total_in_view || 0) : selIds.length;

  const run = async (steps) => {
    const explicit = allInView || selIds.length > 0;
    const body = { steps, limit: explicit ? 0 : Number(limit) || 0,
                   workers: Math.max(1, Math.min(Number(workers) || 1, 25)) };
    if (outputs) body.enrichments = outputs;
    if (allInView || selIds.length === 0) body.view = view === "all" ? "notrun" : view;
    else body.lead_ids = selIds;
    const n = selectedCount || data.chips.notrun;
    if (n > 50 && !confirm(`Run ${steps} on ${n.toLocaleString()} leads${body.limit ? ` (capped at ${body.limit})` : ""}?`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/run`, { method: "POST", body });
      setJob(r.job_id); setSelIds([]); setAllInView(false);
    } catch (e) { toast(e.message, "bad"); }
  };
  const stop = async () => { if (job) { try { await api(`/api/jobs/${job}/cancel`, { method: "POST" }); } catch (e) { toast(e.message, "bad"); } } };
  const findCompetitors = async () => {
    const body = allInView || selIds.length === 0 ? { view } : { lead_ids: selIds };
    try {
      const r = await api(`/api/enrich-lists/${id}/find-competitors`, { method: "POST", body });
      setJob(r.job_id); setSelIds([]); setAllInView(false);
    } catch (e) { toast(e.message, "bad"); }
  };
  const splitByIndustry = async () => {
    if (!confirm("Create '<List> — <Industry>' lists and move classified leads into them?")) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/split-by-industry`, { method: "POST" });
      toast(`Moved ${r.moved} leads into ${r.lists_created.length} industry lists.`);
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const clearAction = async (what) => {
    if (!confirm(`${what === "clear-results" ? "Clear enrichment results" : "Clear verification"} for view "${view}"?`)) return;
    try { await api(`/api/enrich-lists/${id}/${what}?view=${view}`, { method: "POST" }); reload(); }
    catch (e) { toast(e.message, "bad"); }
  };
  const deleteSelected = async (rows) => {
    const body = allInView || (!rows?.length && selIds.length === 0) ? { view }
      : { lead_ids: rows?.length ? rows.map((r) => r.id) : selIds };
    const n = body.lead_ids?.length || selectedCount || data.chips[view] || 0;
    if (!confirm(`Delete ${n.toLocaleString()} lead(s)? This cannot be undone.`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/delete-leads`, { method: "POST", body });
      toast(`Deleted ${r.deleted} lead(s).`); setSelIds([]); setAllInView(false); reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const exportCsv = async () => {
    const res = await fetch(`/api/enrich-lists/${id}/export?view=${view}`,
      { headers: { Authorization: `Bearer ${getToken()}` } });
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `${data.list.name}-${view}.csv`; a.click();
    URL.revokeObjectURL(a.href);
  };
  const importCsv = async (file) => {
    if (!file) return;
    try {
      const rows = parseCsv(await file.text());
      if (!rows.length) { toast("No rows found in that CSV.", "bad"); return; }
      for (let i = 0; i < rows.length; i += 2000)
        await api(`/api/enrich-lists/${id}/import`, { method: "POST", body: { rows: rows.slice(i, i + 2000) } });
      toast(`Imported ${rows.length.toLocaleString()} leads`);
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };

  const columns = useMemo(() => [
    { accessorKey: "name", header: "Lead", size: 230,
      cell: ({ row }) => (
        <div><div className="lead-nm">{row.original.name || row.original.email}</div>
          <div className="lead-sub">{row.original.company}{row.original.title ? ` · ${row.original.title}` : ""}</div></div>) },
    { accessorKey: "free_status", header: "System check", size: 120,
      cell: ({ getValue }) => <Badge tone={vTone(getValue())}>{getValue() || "—"}</Badge> },
    { accessorKey: "email_status", header: "Reoon", size: 110,
      cell: ({ getValue }) => <Badge tone={vTone(getValue())}>{getValue() || "—"}</Badge> },
    { accessorKey: "esp", header: "ESP", size: 110,
      cell: ({ getValue }) => (getValue()
        ? <Badge tone={espTone(getValue())}>{getValue()}</Badge> : "—") },
    { accessorKey: "title_status", header: "Title gate", size: 100,
      cell: ({ getValue }) => (getValue()
        ? <Badge tone={getValue() === "pass" ? "green" : "red"}>{getValue()}</Badge> : "—") },
    { id: "icp", header: "ICP", size: 110, accessorFn: (l) => l.icp_decision || "",
      cell: ({ row }) => (row.original.icp_decision
        ? <Badge tone={row.original.icp_decision === "ICP" ? "green" : row.original.icp_decision === "Non-ICP" ? "red" : "amber"}>
            {row.original.icp_decision}{row.original.icp_score != null ? ` ${row.original.icp_score}` : ""}</Badge> : "—") },
    { accessorKey: "industry", header: "Industry", size: 150, cell: ({ getValue }) => getValue() || "—" },
    { id: "competitors", header: "Competitors", size: 170, enableSorting: false,
      cell: ({ row }) => ((row.original.competitors || []).length === 0 ? "—"
        : row.original.competitors.map((c, i) => <span key={i} title={c.why} style={{ display: "block", fontSize: 12 }}>{c.name}</span>)) },
    { accessorKey: "status", header: "Status", size: 100,
      cell: ({ getValue }) => <Badge tone={stTone[getValue()] || ""}>{getValue() || "not run"}</Badge> },
  ], []);

  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const espActive = ESP_VIEWS.some(([v]) => v === view);
  const filterGroups = [
    { key: "view", label: "View",
      options: VIEWS.map(([v, label]) => ({ value: v, label, count: data.chips[v] ?? 0 })) },
    { key: "esp", label: "Provider (ESP)",
      options: ESP_VIEWS.map(([v, label]) => ({ value: v, label, count: data.chips[v] ?? 0 })) },
    ...(cfg.data?.formats?.length ? [{
      key: "outputs", label: "Output variables",
      options: cfg.data.formats.map((f) => ({ value: f.name, label: f.label })),
    }] : []),
  ];
  // View and ESP both drive the single `view` param (server-side filter) — so
  // selecting a provider deselects the View chip and vice-versa (single-select).
  const filterValues = { view: espActive ? [] : [view], esp: espActive ? [view] : [], outputs: outputs || [] };
  const onFilter = (key, vals) => {
    if (key === "view" || key === "esp") {
      const cur = key === "esp" ? (espActive ? view : "") : (espActive ? "" : view);
      const next = vals.filter((v) => v !== cur)[0] || "all";   // single-select behavior
      setView(next); setSelIds([]); setAllInView(false);
    } else if (key === "outputs") setOutputs(vals.length ? vals : null);
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "Lists", href: "/enrichment" }, { label: data.list.name }]} />
      <PageHeader title={data.list.name}
        desc={`${data.chips.all.toLocaleString()} leads · Reoon ${reoon?.demo ? "demo" : (reoon?.credits != null ? `${reoon.credits.toLocaleString()} credits` : "connected")}`}
        actions={
          <>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--muted)" }}>
              Workers <input type="number" min="1" max="25" value={workers} onChange={(e) => setWorkers(e.target.value)} style={{ width: 58 }} />
            </span>
            {selectedCount > 0 ? (
              <span style={{ alignSelf: "center", fontSize: 12.5, color: "var(--muted)" }}>
                Runs all <b>{selectedCount.toLocaleString()}</b> selected</span>
            ) : (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--muted)" }}>
                Test first <input type="number" min="0" value={limit} onChange={(e) => setLimit(e.target.value)} style={{ width: 64 }} />
              </span>
            )}
            <Button variant="secondary" icon={ShieldCheck} disabled={!!job} onClick={() => run("verify")}>Verify</Button>
            <Button icon={Play} disabled={!!job} onClick={() => run("pipeline")}>Verify → Enrich</Button>
            {job && <Button variant="danger" icon={Square} onClick={stop}>Stop</Button>}
          </>
        } />

      {job && jobStatus && (
        <div className="card jobbar">
          <div className="spinner" style={{ width: 16, height: 16 }} />
          <div className="progressbar" style={{ width: 220 }}><div style={{ width: `${jobStatus.progress || 0}%` }} /></div>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{jobStatus.progress || 0}% · {jobStatus.progress_note}</span>
        </div>
      )}

      <div className="rail-layout">
        <FilterPanel groups={filterGroups} values={filterValues} onChange={onFilter}
          onClear={() => { setView("all"); setOutputs(null); }} />

        <div className="rail-main">
          {(selectedCount > 0 || (data.total_in_view > data.leads.length)) && (
            <div className="chips" style={{ marginBottom: 10 }}>
              {selectedCount > 0 && <Badge tone="indigo">{selectedCount.toLocaleString()} selected</Badge>}
              {!allInView && data.total_in_view > data.leads.length && (
                <Button size="sm" variant="ghost" onClick={() => setAllInView(true)}>
                  Select all {data.total_in_view.toLocaleString()} in view</Button>
              )}
              {allInView && <Button size="sm" variant="ghost" onClick={() => setAllInView(false)}>Clear selection</Button>}
            </div>
          )}
          <DataTable
            id="enrich-leads" columns={columns} data={data.leads} loading={loading && !data.leads?.length}
            searchable={false} getRowId={(r) => String(r.id)}
            leftTools={
              <div className="dt-search">
                <input type="text" style={{ paddingLeft: 12 }} placeholder="Search name, email, company…"
                  value={qRaw} onChange={(e) => setQRaw(e.target.value)} />
              </div>
            }
            tools={
              <>
                <input ref={fileRef} type="file" accept=".csv" style={{ display: "none" }}
                  onChange={(e) => { importCsv(e.target.files[0]); e.target.value = ""; }} />
                <button className="dt-tool" onClick={() => fileRef.current?.click()}><Upload size={15} /> Import</button>
                <button className="dt-tool" onClick={exportCsv}><Download size={15} /> Export view</button>
                <button className="dt-tool" disabled={!!job} onClick={findCompetitors}>Find competitors</button>
                <button className="dt-tool" disabled={!!job} onClick={splitByIndustry}>Split by industry</button>
                <button className="dt-tool" onClick={() => clearAction("clear-results")}>Clear results</button>
                <button className="dt-tool" onClick={() => clearAction("clear-verification")}>Clear verification</button>
              </>
            }
            onRowClick={(r) => setOpenLead(r)}
            bulkActions={[{ label: "Delete", onClick: (rows) => deleteSelected(rows) }]}
            manual={{ page, pages: Math.max(1, Math.ceil(data.total_in_view / data.page_size)),
                      total: data.total_in_view, onPage: setPage }}
            emptyIcon={Users} emptyTitle="Nothing in this view"
            emptyHint="Change the view on the left, or import leads."
          />
        </div>
      </div>

      {openLead && (
        <Drawer title={openLead.name || openLead.email} onClose={() => setOpenLead(null)}>
          <div className="kv">
            <div className="k">Email</div><div>{openLead.email}</div>
            <div className="k">Company</div>
            <div>{openLead.company} {openLead.website && <a href={openLead.website.startsWith("http") ? openLead.website : `https://${openLead.website}`} target="_blank" rel="noreferrer">↗</a>}</div>
            <div className="k">Verification</div>
            <div><Badge tone={vTone(openLead.free_status)}>{openLead.free_status || "—"}</Badge>{" "}
              <Badge tone={vTone(openLead.email_status)}>{openLead.email_status || "—"}</Badge></div>
            <div className="k">ICP reason</div><div>{openLead.icp_reason || "—"}</div>
          </div>
          <h3 style={{ fontSize: 13, margin: "10px 0 8px" }}>Enrichment variables</h3>
          {Object.keys(openLead.vars || {}).length === 0
            ? <div className="empty" style={{ padding: 12 }}>Not enriched yet</div>
            : Object.entries(openLead.vars).map(([k, v]) => (
              <div key={k} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: "var(--muted)" }}>{k}</div>
                <div style={{ fontSize: 13.5 }}>{String(v)}</div>
              </div>))}
          {Object.keys(openLead.imported || {}).length > 0 && (
            <>
              <h3 style={{ fontSize: 13, margin: "16px 0 8px" }}>Uploaded columns</h3>
              <div className="kv" style={{ margin: 0 }}>
                {Object.entries(openLead.imported).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <div className="k">{k}</div><div>{String(v) || "—"}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Drawer>
      )}
    </>
  );
}
