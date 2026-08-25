import { Area, alertDialog, confirmDialog, promptDialog } from "../components";
// Enrichment list (DESIGN_SYSTEM.md step 4). Apollo Find-People philosophy:
// sticky left filter rail with live full-list counts, instant server-side
// filtering, one shared DataTable (server pagination), quick profile Drawer.
// All engine behavior (jobs, runs, clears, select-all-in-view) is unchanged.
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useLocation, useParams } from "react-router-dom";
import {
  AlertTriangle, AtSign, CheckCircle2, Download, ExternalLink, Eye,
  FileSearch, Globe2, Image as ImageIcon, Play, Quote, ShieldCheck,
  Sparkles, Square, Target, Trash2, Upload, Users,
} from "lucide-react";
import { api, getToken } from "../api";
import { enrichBase } from "../clientspace/modules";
import {
  Badge, Breadcrumbs, Button, DataTable, Drawer, ErrorBox, FilterPanel,
  Modal, PageHeader, Spinner, useApi, useDebounced, useToast,
} from "../components";
import { Select } from "../components";

const VIEWS = [["all", "All"], ["processed", "Processed"], ["verified", "Verified"],
  ["enriched", "Enriched"], ["insufficient", "Insufficient research"],
  ["needs_review", "Needs review"], ["generation_failed", "Generation failed"],
  ["icp", "ICP"], ["nonicp", "Non-ICP"], ["no_website", "No website"],
  ["invalid", "Invalid"], ["unsafe", "Unsafe"], ["notrun", "Not run"],
  ["title_rejected", "Title-rejected"]];
// Mailbox provider (MX-based) — segment for provider-aware sending / deliverability.
const ESP_VIEWS = [["esp_microsoft", "Microsoft"], ["esp_google", "Google"],
  ["esp_other", "Other"], ["esp_unknown", "Unknown"]];
const espTone = (e) => ({ Microsoft: "blue", Google: "green", Other: "gray" }[e] || "gray");

const stTone = { done: "green", invalid: "red", unsafe: "red", skipped: "amber", error: "red",
  insufficient: "amber", needs_review: "amber", generation_failed: "red" };
const vTone = (v) => v === "ok" || v === "safe" || v === "valid" ? "green"
  : v === "role" || v === "catch_all" || v === "unknown" ? "amber"
  : v === "skipped" || !v ? "" : "red";
const adTone = (state) => ({ confirmed_advertiser: "green", probable_advertiser: "amber",
  no_evidence: "gray", not_assessed: "gray" }[state] || "gray");
const adChip = (ads) => {
  if (!ads || !ads.state) return "Not assessed";
  if (ads.state === "not_assessed") return "Not assessed";
  if (ads.state === "no_evidence") return "No ad evidence";
  const label = ads.state === "confirmed_advertiser" ? "Running ads" : "Likely running ads";
  return ads.confidence ? `${label} · ${ads.confidence}%` : label;
};
const pretty = (s = "") => String(s).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
const hostOf = (url = "") => {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
};

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
  const [espSel, setEspSel] = useState([]);   // multi-select provider facet
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
  const [showAllEvidence, setShowAllEvidence] = useState(false);
  const [outputs, setOutputs] = useState(null);
  const [dedupeOpen, setDedupeOpen] = useState(false);
  const [dedupeLists, setDedupeLists] = useState([]);
  const [dedupeOther, setDedupeOther] = useState("");
  const [dedupeTarget, setDedupeTarget] = useState("this");
  const [dedupePreview, setDedupePreview] = useState(null);
  const [dedupeBusy, setDedupeBusy] = useState(false);
  const [icpOpen, setIcpOpen] = useState(false);
  const [icpInfo, setIcpInfo] = useState(null);   // {icp_definition, workspace_icp, uses_list_icp}
  const [icpText, setIcpText] = useState("");
  const [icpBusy, setIcpBusy] = useState(false);
  const espParam = espSel.join(",");
  // The Lists crumb has to point at the base this screen was opened at, or a
  // client clicking it lands on the operator path and gets bounced home.
  const base = enrichBase(useLocation().pathname);
  const { data, error, loading, reload, refresh } = useApi(`/api/enrich-lists/${id}/leads`,
    { view, page, q, page_size: 50, esp: espParam });
  const { data: reoon } = useApi(data
    ? `/api/enrich-lists/reoon/balance?workspace_id=${data.list.workspace_id}` : null);
  const cfg = useApi(data ? `/api/enrich-lists/config/${data.list.workspace_id}` : null);

  useEffect(() => { setPage(1); }, [q, view, espParam]);

  // Reconnect to a run already in progress — on load AND on a light poll while
  // no job is tracked, so a run started elsewhere (another tab, or still going
  // after a reload) always surfaces the live bar + Stop button.
  useEffect(() => {
    if (!data || job) return;
    let alive = true;
    const check = () => api(`/api/enrich-lists/${id}/active-job`)
      .then((r) => { if (alive && r.job_id) setJob(r.job_id); }).catch(() => {});
    check();
    const t = setInterval(check, 5000);
    return () => { alive = false; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.list?.id, job]);

  // live job progress poll — refresh the rows/counts in place (quiet, no spinner)
  // each tick so you SEE enrichment happening, then a final reload when it finishes.
  useEffect(() => {
    if (!job) return;
    const t = setInterval(async () => {
      try {
        const s = await api(`/api/jobs/${job}/status`);
        setJobStatus(s);
        if (["done", "failed", "cancelled"].includes(s.status)) { clearInterval(t); setJob(null); reload(); }
        else refresh();   // live: update the table + counts while the job runs, no loading flash
      } catch { clearInterval(t); setJob(null); }
    }, 2500);
    return () => clearInterval(t);
  }, [job, reload, refresh]);

  const selectedCount = allInView ? (data?.total_in_view || 0) : selIds.length;

  const openIcp = async () => {
    setIcpOpen(true);
    setIcpInfo(null);
    try {
      const r = await api(`/api/enrich-lists/${id}/icp`);
      setIcpInfo(r);
      setIcpText(r.icp_definition || "");
    } catch { setIcpInfo({ icp_definition: "", workspace_icp: "", uses_list_icp: false }); }
  };
  const saveIcp = async () => {
    setIcpBusy(true);
    try {
      await api(`/api/enrich-lists/${id}/icp`, { method: "PUT", body: { icp_definition: icpText } });
      toast(icpText.trim()
        ? "Saved. This list now filters by its own ICP. Re-run or clear results to re-apply to existing leads."
        : "Cleared. This list falls back to the workspace ICP.");
      setIcpOpen(false);
    } catch (e) { toast(e.message, "bad"); }
    finally { setIcpBusy(false); }
  };

  const run = async (steps, opts = {}) => {
    const explicit = allInView || selIds.length > 0;
    const body = { steps, limit: explicit ? 0 : Number(limit) || 0,
                   workers: Math.max(1, Math.min(Number(workers) || 1, 25)) };
    if (outputs) body.enrichments = outputs;
    // ESP is independent of run status, so an unfiltered "Check ESP" runs the
    // whole list (fullView), not just the not-run leads.
    if (allInView || selIds.length === 0) {
      body.view = view === "all" ? (opts.fullView ? "all" : "notrun") : view;
      if (espSel.length) body.esp = espSel;   // respect the provider facet
    } else body.lead_ids = selIds;
    const n = selectedCount || (opts.fullView ? data.chips.all : data.total_in_view);
    const label = { esp: "ESP check", verify: "Verify", icp: "ICP filter", pipeline: "Verify → Enrich" }[steps] || steps;
    if (n > 50 && !await confirmDialog(`Run ${label} on ${n.toLocaleString()} leads${body.limit ? ` (capped at ${body.limit})` : ""}?`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/run`, { method: "POST", body });
      setJob(r.job_id); setSelIds([]); setAllInView(false);
    } catch (e) { toast(e.message, "bad"); }
  };
  const stop = async () => {
    try {
      // Cancel EVERY active job for this list, not just the tracked one, so a
      // second/duplicate run can't keep enriching in the background after Stop.
      const r = await api(`/api/enrich-lists/${id}/stop`, { method: "POST" });
      setJob(null); setJobStatus(null);
      toast(r.cancelled ? `Stopped. In-flight leads will finish.` : "Nothing running.");
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const diagnoseDns = async () => {
    try {
      const [r, le] = await Promise.all([
        api(`/api/enrich-lists/diag/dns`),
        api(`/api/enrich-lists/${id}/diag-esp`),
      ]);
      const working = Object.entries(r.probe?.tiers || {}).filter(([, v]) => v.ok).map(([k]) => k);
      const sample = (le.samples || []).map((s) => `  ${s.email} → ${s.esp_live} (stored: ${s.esp_stored || "—"})`).join("\n");
      // eslint-disable-next-line no-alert
      alertDialog(
        `DNS working: ${r.dns_working}   ·   ESP for gmail.com: ${r.probe?.result?.esp}\n` +
        `Working tiers: ${working.length ? working.join(", ") : "NONE"}\n\n` +
        `THIS LIST (${le.list}):\n` +
        `  leads: ${le.total}   ·   in standard email field: ${le.email_in_standard_field}\n` +
        `  recoverable emails (sample): ${le.sample_recoverable}\n  ${le.note}\n\n` +
        `Sample leads (live lookup → stored):\n${sample || "  (none)"}`,
      );
    } catch (e) { toast(e.message, "bad"); }
  };
  const findCompetitors = async () => {
    const body = allInView || selIds.length === 0 ? { view } : { lead_ids: selIds };
    try {
      const r = await api(`/api/enrich-lists/${id}/find-competitors`, { method: "POST", body });
      setJob(r.job_id); setSelIds([]); setAllInView(false);
    } catch (e) { toast(e.message, "bad"); }
  };
  const splitByIndustry = async () => {
    if (!await confirmDialog("Create '<List> — <Industry>' lists and move classified leads into them?")) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/split-by-industry`, { method: "POST" });
      toast(`Moved ${r.moved} leads into ${r.lists_created.length} industry lists.`);
      reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const [grammarVar, setGrammarVar] = useState("");   // "" = all variables
  const fixGrammar = async () => {
    const scope = allInView || selIds.length === 0 ? { view, esp: espSel } : { lead_ids: selIds };
    const n = selIds.length || data?.total_in_view || 0;
    const varLabel = grammarVar ? `the "${grammarVar}" variable` : "all variables";
    if (!await confirmDialog(`Fix grammar & punctuation on ${varLabel} for ${n.toLocaleString()} lead(s)? Company/product names, numbers and meaning are preserved.`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/fix-grammar`, { method: "POST", body: { ...scope, variable: grammarVar || null } });
      setJob(r.job_id); setSelIds([]); setAllInView(false); toast("Fixing grammar…");
    } catch (e) { toast(e.message, "bad"); }
  };
  const espQs = espParam ? `&esp=${encodeURIComponent(espParam)}` : "";
  const clearAction = async (what) => {
    const label = what === "clear-results" ? "Clear enrichment results" : "Clear verification";
    const filterNote = (view !== "all" || espSel.length)
      ? `the CURRENT FILTER only — view "${view}"${espSel.length ? `, ESP: ${espSel.join("/")}` : ""}`
      : "the WHOLE list";
    if (!await confirmDialog(`${label} for ${(data?.total_in_view ?? 0).toLocaleString()} lead(s) — ${filterNote}.\n\nTo affect every lead, clear all filters first (View = All, no ESP).\n\nContinue?`)) return;
    try { await api(`/api/enrich-lists/${id}/${what}?view=${view}${espQs}`, { method: "POST" }); reload(); }
    catch (e) { toast(e.message, "bad"); }
  };
  const deleteSelected = async (rows) => {
    const body = allInView || (!rows?.length && selIds.length === 0) ? { view, esp: espSel }
      : { lead_ids: rows?.length ? rows.map((r) => r.id) : selIds };
    const n = body.lead_ids?.length || selectedCount || data.chips[view] || 0;
    const scopeNote = body.lead_ids ? ""
      : `\n\nThis deletes EVERY lead in the current view (${pretty(view)}${espSel.length ? " + ESP filter" : ""}), across all pages.`;
    if (!await confirmDialog(`Delete ${n.toLocaleString()} lead(s)? This cannot be undone.${scopeNote}`)) return;
    try {
      const r = await api(`/api/enrich-lists/${id}/delete-leads`, { method: "POST", body });
      toast(`Deleted ${r.deleted} lead(s).`); setSelIds([]); setAllInView(false); reload();
    } catch (e) { toast(e.message, "bad"); }
  };
  const openDedupe = async () => {
    setDedupePreview(null); setDedupeOther(""); setDedupeTarget("this");
    try {
      const ls = await api(`/api/enrich-lists?workspace_id=${data.list.workspace_id}`);
      setDedupeLists((ls || []).filter((l) => l.id !== data.list.id));
      setDedupeOpen(true);
    } catch (e) { toast(e.message, "bad"); }
  };
  const dedupeCall = async (dry) =>
    api(`/api/enrich-lists/${id}/dedupe`, { method: "POST",
      body: { other_list_id: Number(dedupeOther), target: dedupeTarget, dry_run: dry } });
  const previewDedupe = async () => {
    if (!dedupeOther) return;
    setDedupeBusy(true);
    try { setDedupePreview(await dedupeCall(true)); }
    catch (e) { toast(e.message, "bad"); } finally { setDedupeBusy(false); }
  };
  const runDedupe = async () => {
    if (!dedupePreview?.matches) return;
    if (!await confirmDialog(`Delete ${dedupePreview.matches.toLocaleString()} duplicate lead(s) from "${dedupePreview.target_list}"? This cannot be undone.`)) return;
    setDedupeBusy(true);
    try {
      const r = await dedupeCall(false);
      toast(`Deleted ${r.deleted.toLocaleString()} duplicate(s) from ${r.target_list}.`);
      setDedupeOpen(false); reload();
    } catch (e) { toast(e.message, "bad"); } finally { setDedupeBusy(false); }
  };
  const exportCsv = async () => {
    const res = await fetch(`/api/enrich-lists/${id}/export?view=${view}${espQs}`,
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

  const trainWithOutput = async (name, text) => {
    const wsId = data?.list?.workspace_id;
    if (!wsId || !String(text || "").trim()) return;
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/formats/${encodeURIComponent(name)}/feedback`,
        { method: "POST", body: { text, verdict: "approved", reason: "" } });
      toast(`Saved as a ${pretty(name)} training example (${r.count} approved)`);
    } catch (e) { toast(e.message, "bad"); }
  };

  const rejectOutput = async (name, text) => {
    const wsId = data?.list?.workspace_id;
    if (!wsId || !String(text || "").trim()) return;
    const reason = await promptDialog(
      "Why should the writer avoid this output? Be specific, for example: “too corporate”, “ignored the number”, or “sentence is too complex”.",
    );
    if (reason == null) return;
    if (reason.trim().length < 3) { toast("Add a brief reason so the writer knows what to avoid.", "bad"); return; }
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/formats/${encodeURIComponent(name)}/feedback`,
        { method: "POST", body: { text, verdict: "rejected", reason: reason.trim() } });
      toast(`Saved as an anti-example (${r.count} rejected examples)`);
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

  const filterGroups = [
    { key: "view", label: "View",
      options: VIEWS.map(([v, label]) => ({ value: v, label, count: data.chips[v] ?? 0 })) },
    { key: "esp", label: "Provider (ESP)",
      // option value is the provider LABEL (backend facet); count from the chip key
      options: ESP_VIEWS.map(([chip, label]) => ({ value: label, label, count: data.chips[chip] ?? 0 })) },
    ...(cfg.data?.formats?.length ? [{
      key: "outputs", label: "Output variables",
      options: cfg.data.formats.map((f) => ({ value: f.name, label: f.label })),
    }] : []),
  ];
  // View is single-select (one funnel status); ESP is MULTI-select (combine
  // providers, e.g. Google + Other) and ANDs with the view on the server.
  const filterValues = { view: [view], esp: espSel, outputs: outputs || [] };
  const onFilter = (key, vals) => {
    if (key === "view") {
      const next = vals.filter((v) => v !== view)[0] || "all";   // single-select behavior
      setView(next); setSelIds([]); setAllInView(false);
    } else if (key === "esp") {
      setEspSel(vals); setSelIds([]); setAllInView(false);       // multi-select
    } else if (key === "outputs") setOutputs(vals.length ? vals : null);
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "Lists", href: base }, { label: data.list.name }]} />
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
            <Button variant="secondary" icon={Target} onClick={openIcp}>ICP filter</Button>
            <Button variant="secondary" icon={AtSign} disabled={!!job} onClick={() => run("esp", { fullView: true })}>Check ESP</Button>
            <Button variant="secondary" icon={ShieldCheck} disabled={!!job} onClick={() => run("verify")}>Verify</Button>
            <Button variant="secondary" icon={Target} disabled={!!job} onClick={() => run("icp")}>ICP filter only</Button>
            <Button icon={Play} disabled={!!job} onClick={() => run("pipeline")}>Verify → Enrich</Button>
            {job && <Button variant="danger" icon={Square} onClick={stop}>Stop</Button>}
          </>
        } />

      {reoon?.demo && (
        <div className="card" style={{
          background: "var(--bad-soft)", border: "1px solid var(--bad-border)", color: "var(--bad-text)",
          padding: "12px 16px", marginBottom: 12, fontSize: 13, display: "flex",
          alignItems: "center", gap: 10,
        }}>
          <span style={{ fontSize: 16 }}>⚠️</span>
          <span><b>No Reoon API key — emails are NOT being verified.</b> Every lead will stop as
            “unsafe” until you add a key (they’re never falsely marked safe). Add it in{" "}
            <b>Client Profile → Reoon email verification key</b>.</span>
        </div>
      )}

      {job && jobStatus && (
        <div className="card jobbar">
          <div className="spinner" style={{ width: 16, height: 16 }} />
          {jobStatus.status === "pending" ? (
            <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
              Queued, waiting for a free worker{jobStatus.progress_note ? ` · ${jobStatus.progress_note}` : "…"}
            </span>
          ) : (
            <>
              <div className="progressbar" style={{ width: 220 }}><div style={{ width: `${jobStatus.progress || 0}%` }} /></div>
              <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{jobStatus.progress || 0}% · {jobStatus.progress_note}</span>
            </>
          )}
        </div>
      )}

      <div className="rail-layout">
        <FilterPanel groups={filterGroups} values={filterValues} onChange={onFilter}
          onClear={() => { setView("all"); setEspSel([]); setOutputs(null); }} />

        <div className="rail-main">
          {(selectedCount > 0 || data.total_in_view > 0) && (
            <div className="chips" style={{ marginBottom: 10, alignItems: "center" }}>
              {selectedCount > 0 && <Badge tone="indigo">{selectedCount.toLocaleString()} selected</Badge>}
              {!allInView && data.total_in_view > 0 && (
                <Button size="sm" variant="ghost" onClick={() => setAllInView(true)}>
                  Select all {data.total_in_view.toLocaleString()} in view</Button>
              )}
              {allInView && <Button size="sm" variant="ghost" onClick={() => setAllInView(false)}>Clear selection</Button>}
              {selectedCount > 0 && (
                <Button size="sm" variant="danger" icon={Trash2} disabled={!!job}
                  onClick={() => deleteSelected()}>
                  Delete {selectedCount.toLocaleString()}</Button>
              )}
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
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <button className="dt-tool" disabled={!!job} onClick={fixGrammar}>Fix grammar</button>
                  <Select size="sm" value={grammarVar} onChange={(e) => setGrammarVar(e.target.value)} title="Which variable to fix (default: all)"
                    style={{ maxWidth: 150 }}>
                    <option value="">all variables</option>
                    {(cfg.data?.formats || []).map((f) => <option key={f.name} value={f.name}>{f.label || f.name}</option>)}
                  </Select>
                </span>
                <button className="dt-tool" onClick={openDedupe}>Dedupe</button>
                <button className="dt-tool" onClick={() => clearAction("clear-results")}>Clear results</button>
                <button className="dt-tool" onClick={() => clearAction("clear-verification")}>Clear verification</button>
                <button className="dt-tool" onClick={diagnoseDns}>Diagnose DNS</button>
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

      <AnimatePresence>
      {openLead && (
        <Drawer key="lead" title={openLead.name || openLead.email} className="research-drawer"
          onClose={() => { setOpenLead(null); setShowAllEvidence(false); }}>
          <div className="rd-hero">
            <div>
              <div className="rd-company">
                {openLead.company || "Unknown company"}
                {openLead.website && (
                  <a href={openLead.website.startsWith("http") ? openLead.website : `https://${openLead.website}`}
                    target="_blank" rel="noreferrer" title="Open company website"><ExternalLink size={14} /></a>)}
              </div>
              <div className="rd-contact">{openLead.title || "No title"} · {openLead.email}</div>
            </div>
            <Badge tone={stTone[openLead.status] || ""}>{pretty(openLead.status || "not run")}</Badge>
          </div>

          <div className="rd-verification">
            <span><ShieldCheck size={14} /> Deliverability</span>
            <Badge tone={vTone(openLead.free_status)}>{openLead.free_status || "not checked"}</Badge>
            <Badge tone={vTone(openLead.email_status)}>{openLead.email_status || "not checked"}</Badge>
            {openLead.esp && <Badge tone={espTone(openLead.esp)}>{openLead.esp}</Badge>}
          </div>

          {(openLead.research_error || openLead.generation_error ||
            ["insufficient", "needs_review", "generation_failed"].includes(openLead.status)) && (
            <div className={`rd-alert ${openLead.status === "generation_failed" ? "bad" : ""}`}>
              <AlertTriangle size={17} />
              <div>
                <b>{openLead.research_error ? "Research failed safely"
                  : openLead.generation_error ? "Generation failed safely"
                  : openLead.status === "needs_review" ? "Human review required"
                  : "Not enough verified evidence"}</b>
                <p>{openLead.research_error || openLead.generation_error ||
                  (openLead.status === "needs_review"
                    ? "One or more variables failed grounding checks and were quarantined instead of shipping."
                    : (openLead.research?.reason
                      || "Fewer than three source-backed signals were found. No generic copy was generated."))}</p>
              </div>
            </div>)}

          <section className="rd-section">
            <div className="rd-section-head"><div><span>Research confidence</span><h3>Evidence at a glance</h3></div>
              {openLead.status === "done" && <span className="rd-verified"><CheckCircle2 size={14} /> Quality passed</span>}
            </div>
            <div className="rd-stats">
              <div><FileSearch size={16} /><b>{(openLead.evidence || []).length}</b><span>Verified facts</span></div>
              <div><Globe2 size={16} /><b>{openLead.research?.pages_crawled || 0}</b><span>Pages read</span></div>
              <div><Eye size={16} /><b>{openLead.research?.rendered_pages || 0}</b><span>JS rendered</span></div>
              <div><ImageIcon size={16} /><b>{openLead.research?.visual_evidence || 0}</b><span>Visual facts</span></div>
            </div>
          </section>

          <section className="rd-section">
            <div className="rd-section-head">
              <div><span>Qualification</span><h3>ICP assessment</h3></div>
              {openLead.icp_decision && <Badge tone={openLead.icp_decision === "ICP" ? "green"
                : openLead.icp_decision === "Non-ICP" ? "red" : "amber"}>
                {openLead.icp_decision}{openLead.icp_score != null ? ` · ${openLead.icp_score}` : ""}</Badge>}
            </div>
            <p className="rd-reason">{openLead.icp_reason || "No assessment yet."}</p>
          </section>

          {/* Paid-advertising evidence. Read off the same crawl — no extra cost.
              It answers "do they buy traffic", never "how much do they spend":
              a website does not state a media budget, so the verify links hand
              the operator straight to the ad libraries to settle the volume. */}
          <section className="rd-section">
            <div className="rd-section-head">
              <div><span>Paid media</span><h3>Ad activity</h3></div>
              <Badge tone={adTone(openLead.ads?.state)}>{adChip(openLead.ads)}</Badge>
            </div>
            <p className="rd-reason">{openLead.ads?.summary || "Not assessed."}</p>
            {(openLead.ads?.platforms || []).length > 0 && (
              <div className="rd-chips">
                {openLead.ads.platforms.map((p) => <Badge key={p} tone="indigo">{p}</Badge>)}
              </div>)}
            {(openLead.ads?.evidence || []).length > 0 && (
              <ul className="rd-adevidence">
                {openLead.ads.evidence.map((e, i) => <li key={`${e}-${i}`}>{e}</li>)}
              </ul>)}
            {(openLead.ads?.scale_indicators || []).length > 0 && (
              <ul className="rd-adevidence rd-adscale">
                {openLead.ads.scale_indicators.map((e, i) => <li key={`${e}-${i}`}>{e}</li>)}
              </ul>)}
            {(openLead.ads?.verify || []).length > 0 && (
              <div className="rd-adverify">
                <span>Confirm volume by hand</span>
                {openLead.ads.verify.map((v) => (
                  <a key={v.platform} href={v.url} target="_blank" rel="noreferrer noopener" title={v.what}>
                    {v.platform} <ExternalLink size={12} />
                  </a>))}
              </div>)}
            <p className="rd-adnote">
              Site evidence proves whether they buy traffic, not how much they spend —
              no page states a media budget. Use the links above for volume.
            </p>
          </section>

          <section className="rd-section">
            <div className="rd-section-head"><div><span>Source-backed research</span><h3>Evidence ledger</h3></div>
              <Badge tone="indigo">{(openLead.evidence || []).length} facts</Badge>
            </div>
            {(openLead.evidence || []).length === 0
              ? <div className="rd-empty"><FileSearch size={20} />No validated evidence yet</div>
              : <div className="rd-evidence-list">
                {(showAllEvidence ? openLead.evidence : openLead.evidence.slice(0, 8)).map((ev, i) => (
                  <article className="rd-evidence" key={ev.id || `${ev.claim}-${i}`}>
                    <div className="rd-evidence-top">
                      <span className="rd-type">{pretty(ev.type)}</span>
                      <span className="rd-source-kind">{ev.source_kind === "image"
                        ? <><ImageIcon size={12} /> Visual</> : <><Globe2 size={12} /> Web</>}</span>
                    </div>
                    <b>{ev.claim}</b>
                    {ev.supporting_quote && <blockquote><Quote size={13} />{ev.supporting_quote}</blockquote>}
                    {ev.source_url && <a href={ev.source_url} target="_blank" rel="noreferrer">
                      {hostOf(ev.source_url)} <ExternalLink size={12} /></a>}
                  </article>))}
                {openLead.evidence.length > 8 && (
                  <button className="btn ghost sm" style={{ alignSelf: "flex-start" }}
                    onClick={() => setShowAllEvidence((v) => !v)}>
                    {showAllEvidence ? "Show less" : `Show all ${openLead.evidence.length} facts`}</button>)}
              </div>}
          </section>

          <section className="rd-section">
            <div className="rd-section-head"><div><span>Ready for outreach</span><h3>Generated variables</h3></div>
              {openLead.generation?.model
                ? <Badge tone="indigo">{openLead.generation.model} · {openLead.generation.candidates_considered || 0} candidates · {openLead.generation.calls || 1} call{openLead.generation.calls === 1 ? "" : "s"}</Badge>
                : <Sparkles size={17} className="rd-spark" />}</div>
            {Object.keys(openLead.vars || {}).length === 0
              ? <div className="rd-empty"><Sparkles size={20} />No approved copy yet</div>
              : <div className="rd-output-list">
                {Object.entries(openLead.vars).map(([k, v]) => {
                  const assignment = openLead.assignments?.[k] || {};
                  const failure = openLead.quality_failures?.[k];
                  return (
                    <article key={k} className={`rd-output ${failure ? "failed" : ""}`}>
                      <div className="rd-output-head"><b>{pretty(k)}</b>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          {!failure && v && <button className="btn ghost sm" onClick={() => trainWithOutput(k, v)}
                            title="Save this approved output as a style/structure example for future leads">
                            Train with this
                          </button>}
                          {!failure && v && <button className="btn ghost sm" onClick={() => rejectOutput(k, v)}
                            title="Save this as an anti-example and explain what the writer should avoid">
                            Needs work
                          </button>}
                          {failure ? <Badge tone="red">Held</Badge> : <Badge tone="green">Grounded</Badge>}
                        </div></div>
                      <p>{String(v) || "This variable was withheld because it did not pass quality review."}</p>
                      {failure && <div className="rd-failure"><AlertTriangle size={13} />{failure}</div>}
                      {assignment.evidence && (
                        <div className="rd-used">
                          <span>Evidence used</span><b>{assignment.evidence}</b>
                          {assignment.source_url && <a href={assignment.source_url} target="_blank" rel="noreferrer">
                            View source <ExternalLink size={11} /></a>}
                        </div>)}
                    </article>);
                })}
              </div>}
          </section>

          {openLead.research && (
            <details className="rd-diagnostics">
              <summary>Technical research diagnostics</summary>
              <div className="kv">
                {[["HTTP status", openLead.research.http_status],
                  ["Final URL", openLead.research.final_url],
                  ["Fetch strategy", openLead.research.fallback_method],
                  ["Internal links", openLead.research.internal_links_found],
                  ["Sitemap URLs", openLead.research.sitemap_urls],
                  ["Pages crawled", openLead.research.pages_crawled],
                  ["Pages failed", openLead.research.pages_failed],
                  ["Rendered pages", openLead.research.rendered_pages],
                  ["Images discovered", openLead.research.images_discovered],
                  ["Vision candidates", openLead.research.vision_candidates],
                  ["Research text length", openLead.research.signals_text_len],
                  ["Signals collected", openLead.research.signals_collected],
                  ["Evidence validated", openLead.research.evidence_validated],
                  ["Evidence (strict / corroborated)",
                    (openLead.research.evidence_strict != null || openLead.research.evidence_corroborated != null)
                      ? `${openLead.research.evidence_strict || 0} / ${openLead.research.evidence_corroborated || 0}` : null],
                  ["Facts found", Object.entries(openLead.research.facts_by_type || {})
                    .map(([k, v]) => `${pretty(k)} ${v}`).join(" · ")],
                  ["Writer model", openLead.generation?.model],
                  ["Writer calls", openLead.generation?.calls],
                  ["Candidates considered", openLead.generation?.candidates_considered],
                  ["Writer prompt chars", openLead.generation?.prompt_chars],
                  ["Page types", Object.entries(openLead.research.page_types || {})
                    .map(([k, v]) => `${pretty(k)} ${v}`).join(" · ")],
                  ["Signal types", (openLead.research.signal_types || []).map(pretty).join(", ")]]
                  .filter(([, v]) => v !== undefined && v !== null && v !== "")
                  .map(([k, v]) => (
                    <div key={k} style={{ display: "contents" }}>
                      <div className="k">{k}</div><div>{String(v) || "—"}</div>
                    </div>))}
              </div>
            </details>)}

          {Object.keys(openLead.imported || {}).length > 0 && (
            <details className="rd-diagnostics">
              <summary>Original uploaded data</summary>
              <div className="kv" style={{ margin: 0 }}>
                {Object.entries(openLead.imported).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <div className="k">{k}</div><div>{String(v) || "—"}</div>
                  </div>
                ))}
              </div>
            </details>
          )}
        </Drawer>
      )}
      </AnimatePresence>

      <AnimatePresence>
      {icpOpen && (
        <Modal key="icp" title="ICP filter for this list" onClose={() => setIcpOpen(false)}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 520, maxWidth: 620 }}>
            <div style={{ fontSize: 13, color: "var(--muted)" }}>
              This ICP applies only to <b>{data.list.name}</b>, so each list can target a different
              segment. Leave it blank to fall back to the workspace ICP. Describe <b>who the companies
              are</b> (the kind of business you want), not who they serve.
            </div>
            <Area size="lg"
              value={icpText}
              onChange={(e) => setIcpText(e.target.value)}
              placeholder={"e.g. B2B SaaS and digital agencies, 10-200 employees, selling paid services to other businesses. Plain prose or ICP JSON both work."}
              style={{ width: "100%", fontSize: 13, lineHeight: 1.5, fontFamily: "inherit", padding: 10 }}
            />
            <div className="card" style={{ padding: "10px 12px", background: "var(--ok-soft)", border: "1px solid var(--ok-border)", fontSize: 12.5, color: "var(--ok-text)" }}>
              Always on for every list: non-profits, charities, churches, and donation
              organizations are kept as Non-ICP automatically (based on who they are, not who they serve).
            </div>
            {icpInfo && !((icpInfo.icp_definition || "").trim()) && (icpInfo.workspace_icp || "").trim() && (
              <details style={{ fontSize: 12.5 }}>
                <summary style={{ cursor: "pointer", color: "var(--muted)" }}>Workspace ICP (used when this is blank)</summary>
                <div style={{ whiteSpace: "pre-wrap", marginTop: 6, padding: 10, background: "var(--card-2)", borderRadius: 6 }}>
                  {icpInfo.workspace_icp}
                </div>
              </details>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", alignItems: "center" }}>
              {icpText.trim() && (
                <Button variant="secondary" disabled={icpBusy} onClick={() => setIcpText("")}>Clear</Button>
              )}
              <Button icon={Target} disabled={icpBusy || !icpInfo} onClick={saveIcp}>
                {icpBusy ? "Saving…" : "Save ICP for this list"}</Button>
            </div>
          </div>
        </Modal>
      )}
      </AnimatePresence>

      <AnimatePresence>
      {dedupeOpen && (
        <Modal key="dedupe" title="Remove duplicates by email" onClose={() => setDedupeOpen(false)}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 440 }}>
            <label style={{ fontSize: 13 }}>
              Compare against list
              <Select value={dedupeOther} style={{ width: "100%", marginTop: 4 }}
                onChange={(e) => { setDedupeOther(e.target.value); setDedupePreview(null); }}>
                <option value="">Select a list…</option>
                {dedupeLists.map((l) => (
                  <option key={l.id} value={l.id}>{l.name} ({(l.leads || 0).toLocaleString()} leads)</option>
                ))}
              </Select>
            </label>
            <div style={{ fontSize: 13 }}>
              <div style={{ marginBottom: 6, color: "var(--muted)" }}>When an email appears in both lists, delete it from:</div>
              <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input type="radio" checked={dedupeTarget === "this"}
                  onChange={() => { setDedupeTarget("this"); setDedupePreview(null); }} />
                <span><b>This list</b> ({data.list.name}) — keep the other as the reference</span>
              </label>
              <label style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 5 }}>
                <input type="radio" checked={dedupeTarget === "other"}
                  onChange={() => { setDedupeTarget("other"); setDedupePreview(null); }} />
                <span>The other list</span>
              </label>
            </div>
            {dedupePreview && (
              <div className="card" style={{ padding: 12, background: "var(--card-2)", fontSize: 13 }}>
                <b>{dedupePreview.matches.toLocaleString()}</b> duplicate{dedupePreview.matches === 1 ? "" : "s"} found —
                would be deleted from <b>{dedupePreview.target_list}</b> (of {dedupePreview.target_total.toLocaleString()} leads).
                {dedupePreview.matches === 0 && " Nothing to remove."}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <Button variant="secondary" disabled={!dedupeOther || dedupeBusy} onClick={previewDedupe}>Preview</Button>
              <Button variant="danger" disabled={!dedupePreview?.matches || dedupeBusy} onClick={runDedupe}>
                Delete duplicates</Button>
            </div>
          </div>
        </Modal>
      )}
      </AnimatePresence>
    </>
  );
}
