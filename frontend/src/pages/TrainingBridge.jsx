// Workspace Training — the controlled bridge for importing a training package.
//
// Same layout primitives as the other four config screens (ui/form.jsx), so the
// Build nav reads as one set of pages rather than five. Everything here is
// previewed before it applies and versioned after, and the screen's job is to
// make that sequence obvious.
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Download, History, ShieldCheck, UploadCloud } from "lucide-react";
// CheckCircle2 marks a passing evaluation; UploadCloud heads the import section.
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Area, Button, confirmDialog, ErrorBox, FieldGrid, FormField as Field, Section,
  Spinner, StatCard, Text, useToast,
} from "../components";

const SAMPLE = JSON.stringify({
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
}, null, 2);

export default function TrainingBridge() {
  const { wsParam, me } = useAuth();
  const toast = useToast();
  const wsId = wsParam || (!me.is_master ? me.workspaces[0]?.id : null);
  const [bundle, setBundle] = useState(null);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState(null);
  const [revisions, setRevisions] = useState([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [evaluation, setEvaluation] = useState(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    if (!wsId) return;
    try {
      const [nextBundle, nextRevisions] = await Promise.all([
        api(`/api/enrich-lists/config/${wsId}/training/export`),
        api(`/api/enrich-lists/config/${wsId}/training/revisions`),
      ]);
      setBundle(nextBundle);
      setRevisions(nextRevisions);
    } catch (e) { setError(e.message); }
  }, [wsId]);

  useEffect(() => { refresh(); }, [refresh]);

  if (!wsId) return <ErrorBox msg="Choose one workspace before opening Workspace Training." />;
  if (error) return <ErrorBox msg={error} />;
  if (!bundle) return <Spinner />;

  const download = () => {
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(bundle.workspace?.name || "workspace").replace(/\s+/g, "-").toLowerCase()}-training.json`;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
    toast("Training package exported");
  };

  const previewPackage = async () => {
    setBusy(true); setPreview(null);
    try {
      const parsed = JSON.parse(text);
      const result = await api(`/api/enrich-lists/config/${wsId}/training/preview`, {
        method: "POST", body: { package: parsed, note },
      });
      setPreview(result);
      toast(result.changes.length
        ? `Preview ready: ${result.changes.length} section${result.changes.length === 1 ? "" : "s"} will change.`
        : "This package already matches the workspace.");
    } catch (e) { toast(e.message, "bad"); }
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
      setText(""); setPreview(null);
      toast("Training package applied — a rollback point was saved.");
      await refresh();
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };

  const rollback = async (revision) => {
    if (!await confirmDialog(`Restore workspace training snapshot v${revision.version}? The current state will be saved first.`)) return;
    setBusy(true);
    try {
      await api(`/api/enrich-lists/config/${wsId}/training/rollback/${revision.id}`, { method: "POST" });
      setPreview(null);
      toast(`Restored training snapshot v${revision.version}.`);
      await refresh();
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };

  const activeCases = bundle.evaluation_cases?.filter((x) => x.active !== false).length || 0;

  const runEvaluation = async () => {
    if (!activeCases) return;
    if (!await confirmDialog(`Run up to ${Math.min(activeCases, 5)} golden case(s) through the live writer? This uses OpenAI tokens but does not modify leads or training.`)) return;
    setBusy(true); setEvaluation(null);
    try {
      const result = await api(`/api/enrich-lists/config/${wsId}/training/evaluate`, {
        method: "POST", body: { confirm_spend: true, case_names: [] },
      });
      setEvaluation(result);
      toast(`Evaluation finished: ${result.passed}/${result.cases} cases passed, average score ${result.average_score}.`);
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };

  return (
    <div className="fpage">
      <Section first title="Workspace Training"
        hint={`A controlled bridge for Codex and your team to train ${bundle.workspace?.name || "this workspace"}. Every import is previewed, versioned, audited and reversible.`}>
        <div className="tb-stats">
          <StatCard label="Current revision" value={bundle.revision?.slice(0, 12) || "—"} />
          <StatCard label="Writing standard" value={bundle.config?.reading_level || "b2 business"} />
          <StatCard label="Golden evaluation cases" value={bundle.evaluation_cases?.length || 0} />
          <StatCard label="Safety" value="No leads or credentials" />
        </div>
      </Section>

      <Section title="Export a safe training package"
        hint="Contains Brain, ICP, formats, rules, model controls, feedback examples and golden cases only. It excludes leads, emails, mailbox data and secrets."
        actions={<Button icon={Download} onClick={download}>Export JSON</Button>}>
        <p className="fstatus"><ShieldCheck size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Safe to hand to anyone who needs to author training changes.</p>
      </Section>

      <Section title="Run golden-case evaluation"
        hint="Tests up to five active cases with the live writer, then checks required terms and quality gates. This spends OpenAI tokens and never changes leads."
        actions={<Button disabled={busy || !activeCases} onClick={runEvaluation}>
          Run {Math.min(activeCases, 5)} cases</Button>}>
        {!activeCases && <p className="fstatus">No active golden cases yet — add some in a training package below.</p>}
        {evaluation && (
          <div className="tb-eval">
            {evaluation.results.map((result) => (
              <details key={result.id}>
                <summary>
                  {result.passed && <CheckCircle2 size={13} style={{ verticalAlign: "-2px", marginRight: 5 }} />}
                  <b>{result.name}</b> · {result.score}/100 ·
                  <span className={result.passed ? "fstatus ok" : "fstatus bad"}>
                    {" "}{result.passed ? "passed" : "needs work"}
                  </span>
                </summary>
                {result.writer_error && <p className="fstatus bad">{result.writer_error}</p>}
                {result.variables.map((variable) => (
                  <div key={variable.variable} className="tb-var">
                    <b>{variable.variable.replaceAll("_", " ")}</b> · {variable.score}/100
                    {variable.missing_terms.length > 0 &&
                      <div className="fstatus bad">Missing: {variable.missing_terms.join(", ")}</div>}
                    {variable.quality_failure && <div className="fstatus bad">{variable.quality_failure}</div>}
                    <div><span className="fstatus">Actual:</span> {variable.actual || "withheld"}</div>
                    {variable.expected_example &&
                      <div><span className="fstatus">Approved example:</span> {variable.expected_example}</div>}
                  </div>
                ))}
              </details>
            ))}
          </div>
        )}
      </Section>

      <Section title={<><UploadCloud size={15} style={{ verticalAlign: "-2px", marginRight: 7 }} />Preview and apply a training package</>}
        hint={<>Paste a complete exported package or a partial one such as <code>{'{"config":{"rules":"..."}}'}</code>.
          Nothing changes until you approve the preview.</>}>
        <FieldGrid>
          <Field label="Training package JSON" wide>
            <Area size="lg" className="mono" value={text}
              onChange={(e) => { setText(e.target.value); setPreview(null); }}
              placeholder={SAMPLE} />
          </Field>
          <Field label="Change note" hint="Shown in the rollback history.">
            <Text value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="What this training update improves" />
          </Field>
        </FieldGrid>
        <div className="fnote-row">
          <Button variant="secondary" disabled={busy || !text.trim()} onClick={previewPackage}>
            {busy ? "Checking…" : "Preview changes"}</Button>
          <Button disabled={busy || !preview?.changes?.length} onClick={applyPackage}>
            Apply reviewed package</Button>
        </div>

        {preview && (
          <div className="tb-diff">
            <div className="fstatus">
              Current {preview.current_revision.slice(0, 10)} → proposed {preview.proposed_revision.slice(0, 10)}
            </div>
            {preview.changes.map((change) => (
              <div key={change.section} className="tb-diff-row">
                <b>{change.section.replaceAll("_", " ")}</b>
                <span className="fstatus">{change.before || "empty"}</span>
                <span>→</span>
                <span>{change.after || "empty"}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Rollback history"
        hint="Every apply saves the state it replaced, so any import can be undone.">
        {revisions.length === 0
          ? <p className="fstatus"><History size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
            No training imports have been applied yet.</p>
          : revisions.map((revision) => (
            <div key={revision.id} className="tb-rev">
              <b>v{revision.version}</b>
              <span className="fstatus">{revision.action}</span>
              <span className="tb-rev-note">{revision.note || "Training snapshot"}</span>
              <code>{revision.revision.slice(0, 10)}</code>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => rollback(revision)}>Restore</Button>
            </div>
          ))}
      </Section>

    </div>
  );
}
