/* "Import questions" — Google pulls questions from another of your forms, and so
   does this. It needs no template system to do it: the forms already in the org
   are the library, which is the same reasoning behind Duplicate. */
import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { api } from "../../api";
import { Button, Modal, Select, Spinner, useApi } from "../../components";
import { typeLabel } from "./registry";
import { RichText } from "../richtext";

export function ImportQuestions({ formId, onClose, onImport, busy }) {
  const { data: forms, loading } = useApi("/api/forms");
  const [sourceId, setSourceId] = useState("");
  const [source, setSource] = useState(null);
  const [picked, setPicked] = useState([]);

  const candidates = (forms || []).filter((form) => String(form.id) !== String(formId));

  useEffect(() => {
    if (!sourceId) { setSource(null); setPicked([]); return; }
    let live = true;
    setSource(null);
    api(`/api/forms/${sourceId}`).then((data) => {
      if (!live) return;
      setSource(data);
      setPicked(data.questions.map((question) => question.id));
    }).catch(() => live && setSource({ questions: [] }));
    return () => { live = false; };
  }, [sourceId]);

  const toggle = (id) => setPicked((current) => current.includes(id)
    ? current.filter((value) => value !== id) : [...current, id]);

  const questions = [...(source?.questions || [])].sort((a, b) => a.position - b.position);
  const allPicked = questions.length > 0 && picked.length === questions.length;

  return (
    <Modal title="Import questions" onClose={onClose}>
      <p className="forms-modal-copy">
        Copies the questions into this form. The originals are untouched, and nothing
        stays linked afterwards.
      </p>
      <div className="field">
        <label>From form</label>
        {loading ? <Spinner /> : (
          <Select value={sourceId} onChange={(event) => setSourceId(event.target.value)}
            placeholder={candidates.length ? "Choose a form" : "No other forms yet"}>
            <option value="">Choose a form</option>
            {candidates.map((form) => (
              <option key={form.id} value={form.id}>{form.name} · {form.question_count || 0} questions</option>
            ))}
          </Select>
        )}
      </div>

      {sourceId && !source && <Spinner />}
      {source && (
        <div className="gf-import">
          <div className="gf-import-head">
            <span>{questions.length} question{questions.length === 1 ? "" : "s"}</span>
            <button type="button" onClick={() => setPicked(allPicked ? [] : questions.map((q) => q.id))}>
              {allPicked ? "Clear all" : "Select all"}
            </button>
          </div>
          <div className="gf-import-list">
            {questions.length === 0 && <p className="gf-import-empty">That form has no questions yet.</p>}
            {questions.map((question) => {
              const on = picked.includes(question.id);
              return (
                <label key={question.id} className={`gf-import-row ${on ? "on" : ""}`}>
                  <input type="checkbox" checked={on} onChange={() => toggle(question.id)} />
                  <span className="gf-import-box">{on && <Check size={12} />}</span>
                  <span className="gf-import-main">
                    <RichText text={question.label} fallback="Untitled question" />
                    <em>{typeLabel(question.type)}{question.required ? " · required" : ""}</em>
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      <div className="actions">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy === "import"} disabled={!picked.length}
          onClick={async () => { await onImport(Number(sourceId), picked); onClose(); }}>
          Import {picked.length || ""} question{picked.length === 1 ? "" : "s"}
        </Button>
      </div>
    </Modal>
  );
}
