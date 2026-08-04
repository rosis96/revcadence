import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Download, History, ShieldCheck, UploadCloud } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Spinner } from "../components";
import { confirmDialog, alertDialog } from "../components";

const card = { padding: 18, marginBottom: 14 };

export default function TrainingBridge() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [bundle, setBundle] = useState(null);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState(null);
  const [revisions, setRevisions] = useState([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!wsId || !me.is_master) return;
    try {
      const [nextBundle, nextRevisions] = await Promise.all([
        api(`/api/enrich-lists/config/${wsId}/training/export`),
        api(`/api/enrich-lists/config/${wsId}/training/revisions`),
      ]);
      setBundle(nextBundle);
      setRevisions(nextRevisions);
    } catch (e) { setError(e.message); }
  }, [wsId, me.is_master]);

  useEffect(() => { refresh(); }, [refresh]);

  if (!me.is_master) return <ErrorBox msg="Workspace Training is restricted to owners and administrators." />;
  if (!wsId) return <ErrorBox msg="Choose one workspace before opening Workspace Training." />;
  if (error) return <ErrorBox msg={error} />;
  if (!bundle) return <Spinner />;

  const download = () => {
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(bundle.workspace?.name || "workspace").replace(/\s+/g, "-").toLowerCase()}-training.json`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
  };

  const previewPackage = async () => {
    setBusy(true); setMessage(""); setPreview(null);
    try {
      const parsed = JSON.parse(text);
      const result = await api(`/api/enrich-lists/config/${wsId}/training/preview`, {
        method: "POST", body: { package: parsed, note },
      });
      setPreview(result);
      setMessage(result.changes.length
        ? `Preview ready: ${result.changes.length} section${result.changes.length === 1 ? "" : "s"} will change.`
        : "This package already matches the workspace.");
    } catch (e) { setMessage(""); alertDialog(e.message); }
    setBusy(false);
  };

  const applyPackage = async () => {
    if (!preview?.changes?.length) return;
    if (!await confirmDialog(`Apply ${preview.changes.length} reviewed training change(s)? A rollback point will be saved first.`)) return;
    setBusy(true);
    try {
      await api(`/api/enrich-lists/config/${wsId}/training/apply`, {
        method: "POST",
        body: {
          package: preview.normalized_package,
          expected_revision: preview.current_revision,
          note: note || "Workspace Training import",
        },
      });
      setText(""); setPreview(null); setMessage("Training package applied. A rollback point was saved.");
      await refresh();
    } catch (e) { alertDialog(e.message); }
    setBusy(false);
  };

  const rollback = async (revision) => {
    if (!await confirmDialog(`Restore workspace training snapshot v${revision.version}? The current state will be saved first.`)) return;
    setBusy(true);
    try {
      await api(`/api/enrich-lists/config/${wsId}/training/rollback/${revision.id}`, { method: "POST" });
      setPreview(null); setMessage(`Restored training snapshot v${revision.version}.`);
      await refresh();
    } catch (e) { alertDialog(e.message); }
    setBusy(false);
  };

  const runEvaluation = async () => {
    const count = bundle.evaluation_cases?.filter((x) => x.active !== false).length || 0;
    if (!count) return;
    if (!await confirmDialog(`Run up to ${Math.min(count, 5)} golden case(s) through the live writer? This uses OpenAI tokens but does not modify leads or training.`)) return;
    setBusy(true); setEvaluation(null);
    try {
      const result = await api(`/api/enrich-lists/config/${wsId}/training/evaluate`, {
        method: "POST", body: { confirm_spend: true, case_names: [] },
      });
      setEvaluation(result);
      setMessage(`Evaluation finished: ${result.passed}/${result.cases} cases passed, average score ${result.average_score}.`);
    } catch (e) { alertDialog(e.message); }
    setBusy(false);
  };

  return (
    <div style={{ maxWidth: 1180, width: "100%", minWidth: 0 }}>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontSize: 24, marginBottom: 4 }}>Workspace Training</h1>
        <p style={{ color: "var(--muted)", margin: 0 }}>
          A controlled bridge for Codex and your team to train {bundle.workspace?.name}. Every import is
          previewed, versioned, audited, and reversible.
        </p>
      </div>

      {message && <div className="card" style={{ ...card, color: "#166534", borderColor: "#bbf7d0", background: "#f0fdf4" }}>
        <CheckCircle2 size={16} style={{ verticalAlign: "text-bottom", marginRight: 7 }} />{message}
      </div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(190px,1fr))", gap: 12, marginBottom: 14 }}>
        <div className="card" style={card}><div style={{ color: "var(--muted)", fontSize: 12 }}>Current revision</div>
          <b style={{ fontFamily: "monospace", fontSize: 13 }}>{bundle.revision?.slice(0, 12)}</b></div>
        <div className="card" style={card}><div style={{ color: "var(--muted)", fontSize: 12 }}>Writing standard</div>
          <b>{bundle.config?.reading_level || "b2 business"}</b></div>
        <div className="card" style={card}><div style={{ color: "var(--muted)", fontSize: 12 }}>Golden evaluation cases</div>
          <b>{bundle.evaluation_cases?.length || 0}</b></div>
        <div className="card" style={card}><div style={{ color: "var(--muted)", fontSize: 12 }}>Safety</div>
          <b style={{ color: "#166534" }}>No leads or credentials</b></div>
      </div>

      <div className="card" style={card}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <ShieldCheck size={21} color="#2563eb" />
          <div style={{ flex: "1 1 420px", minWidth: 0 }}><h2 style={{ fontSize: 15, margin: 0 }}>Export a safe training package</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
              Contains Brain, ICP, formats, rules, model controls, feedback examples, and golden cases only.
              It excludes leads, emails, mailbox data, and secrets.
            </p></div>
          <button className="btn" onClick={download}><Download size={15} /> Export JSON</button>
        </div>
      </div>

      <div className="card" style={card}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <CheckCircle2 size={21} color="#2563eb" />
          <div style={{ flex: "1 1 420px", minWidth: 0 }}><h2 style={{ fontSize: 15, margin: 0 }}>Run golden-case evaluation</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
              Tests up to five active cases with the live writer, then checks required terms and quality gates.
              This spends OpenAI tokens and never changes leads.
            </p></div>
          <button className="btn" disabled={busy || !(bundle.evaluation_cases?.length)}
            onClick={runEvaluation}>Run {Math.min(bundle.evaluation_cases?.length || 0, 5)} cases</button>
        </div>
        {evaluation && <div style={{ marginTop: 12 }}>
          {evaluation.results.map((result) => (
            <details key={result.id} style={{ borderTop: "1px solid #eef2f7", padding: "9px 0" }}>
              <summary style={{ cursor: "pointer", fontSize: 13 }}>
                <b>{result.name}</b> · {result.score}/100 ·
                <span style={{ color: result.passed ? "#166534" : "#b91c1c" }}>
                  {" "}{result.passed ? "passed" : "needs work"}
                </span>
              </summary>
              {result.writer_error && <p style={{ color: "#b91c1c", fontSize: 12 }}>{result.writer_error}</p>}
              {result.variables.map((variable) => (
                <div key={variable.variable} style={{ margin: "9px 0 0 18px", fontSize: 12.5 }}>
                  <b>{variable.variable.replaceAll("_", " ")}</b> · {variable.score}/100
                  {variable.missing_terms.length > 0 &&
                    <div style={{ color: "#b91c1c" }}>Missing: {variable.missing_terms.join(", ")}</div>}
                  {variable.quality_failure &&
                    <div style={{ color: "#b91c1c" }}>{variable.quality_failure}</div>}
                  <div><span style={{ color: "var(--muted)" }}>Actual:</span> {variable.actual || "withheld"}</div>
                  {variable.expected_example &&
                    <div><span style={{ color: "var(--muted)" }}>Approved example:</span> {variable.expected_example}</div>}
                </div>
              ))}
            </details>
          ))}
        </div>}
      </div>

      <div className="card" style={card}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
          <UploadCloud size={21} color="#2563eb" />
          <div><h2 style={{ fontSize: 15, margin: 0 }}>Preview and apply a training package</h2>
            <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "4px 0 0" }}>
              Paste a complete exported package or a partial package such as
              {" "}<code>{'{"config":{"rules":"..."}}'}</code>. Nothing changes until you approve the preview.
            </p></div>
        </div>
        <textarea rows={12} style={{ width: "100%", boxSizing: "border-box", fontFamily: "monospace", fontSize: 12 }}
          value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }}
          placeholder={JSON.stringify({
            schema: "revcadence.workspace-training",
            schema_version: 1,
            config: { reading_level: "b2 business", rules: "One global rule per line." },
            evaluation_cases: [{
              name: "Approved Unbox benchmark",
              company: "Unbox",
              website: "https://unboxpd.com/",
              facts: {},
              expected_outputs: {
                personalized_first_line: {
                  example: "Approved output…",
                  required_terms: ["Monstatek", "$2.8 million"],
                },
              },
              notes: "Use the evidence packet captured during research.",
              active: true,
            }],
          }, null, 2)} />
        <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "end", flexWrap: "wrap" }}>
          <div className="field" style={{ flex: "1 1 300px", minWidth: 0, margin: 0 }}><label>Change note</label>
            <input style={{ width: "100%" }} value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="What this training update improves" /></div>
          <button className="btn ghost" disabled={busy || !text.trim()} onClick={previewPackage}>
            {busy ? "Checking…" : "Preview changes"}</button>
          <button className="btn" disabled={busy || !preview?.changes?.length} onClick={applyPackage}>
            Apply reviewed package</button>
        </div>

        {preview && <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 7 }}>
            Current {preview.current_revision.slice(0, 10)} → proposed {preview.proposed_revision.slice(0, 10)}
          </div>
          {preview.changes.map((change) => (
            <div key={change.section} style={{ display: "grid",
              gridTemplateColumns: "minmax(130px,180px) minmax(0,1fr) 26px minmax(0,1fr)",
              gap: 8, padding: "8px 0", borderTop: "1px solid #eef2f7", fontSize: 12.5,
              overflowWrap: "anywhere" }}>
              <b>{change.section.replaceAll("_", " ")}</b>
              <span style={{ color: "var(--muted)" }}>{change.before || "empty"}</span>
              <span>→</span><span>{change.after || "empty"}</span>
            </div>
          ))}
        </div>}
      </div>

      <div className="card" style={card}>
        <div style={{ display: "flex", gap: 9, alignItems: "center", marginBottom: 10 }}>
          <History size={19} /><h2 style={{ fontSize: 15, margin: 0 }}>Rollback history</h2>
        </div>
        {revisions.length === 0
          ? <p style={{ color: "var(--muted)", fontSize: 12.5 }}>No training imports have been applied yet.</p>
          : revisions.map((revision) => (
            <div key={revision.id} style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
              padding: "9px 0", borderTop: "1px solid #eef2f7", fontSize: 12.5 }}>
              <b>v{revision.version}</b><span style={{ color: "var(--muted)" }}>{revision.action}</span>
              <span style={{ flex: 1 }}>{revision.note || "Training snapshot"}</span>
              <code>{revision.revision.slice(0, 10)}</code>
              <button className="btn ghost sm" disabled={busy} onClick={() => rollback(revision)}>Restore</button>
            </div>
          ))}
      </div>
    </div>
  );
}
