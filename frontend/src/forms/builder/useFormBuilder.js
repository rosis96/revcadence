/* The builder's whole state model.

   Three ideas carry it:

   1. `items` is the canvas — one flat, ordered list of section-header and question
      cards. It is derived from the server rows, never stored, so there is no
      second copy of the order to fall out of sync.

   2. A question's section is derived from where its card sits, exactly as it is
      in Google Forms: a section header owns every question card below it until
      the next header. `commitOrder` writes that back to `section_id`. This is the
      part that keeps the clone honest — FormFields renders unsectioned questions
      first and then each section in order, which is precisely the order `flatten`
      produces, so the canvas is what the client gets rather than a lookalike.

   3. Exactly one card is active at a time. `active` is the card; `focus` is a
      one-shot request for a field inside it, consumed by the card that owns it.
      Nothing else in the tree keeps edit state. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { confirmDialog, useToast } from "../../components";
import { defaultOptions } from "./registry";

export const keyOf = (item) => `${item.kind}:${item.id}`;
const sameCard = (a, b) => !!a && !!b && a.kind === b.kind && a.id === b.id;

/** Server rows → the canvas order. Mirrors FormFields' grouping exactly. */
function flatten(form) {
  if (!form) return [];
  const byPosition = (a, b) => (a.position || 0) - (b.position || 0) || a.id - b.id;
  const questions = [...(form.questions || [])].sort(byPosition);
  const sections = [...(form.sections || [])].sort(byPosition);
  const items = questions.filter((question) => !question.section_id)
    .map((question) => ({ kind: "question", id: question.id, data: question }));
  for (const section of sections) {
    items.push({ kind: "section", id: section.id, data: section });
    for (const question of questions.filter((q) => q.section_id === section.id)) {
      items.push({ kind: "question", id: question.id, data: question });
    }
  }
  return items;
}

/** Positions and section membership implied by a candidate canvas order. */
function deriveOrder(items) {
  let section = null;
  const questionIds = [];
  const sectionIds = [];
  const sectionOf = new Map();
  for (const item of items) {
    if (item.kind === "section") { section = item.id; sectionIds.push(item.id); continue; }
    questionIds.push(item.id);
    sectionOf.set(item.id, section);
  }
  return { questionIds, sectionIds, sectionOf };
}

/** The section a card dropped at `index` would belong to. */
function sectionAt(items, index) {
  for (let i = index - 1; i >= 0; i -= 1) if (items[i].kind === "section") return items[i].id;
  return null;
}

export function useFormBuilder(id, { onDuplicated } = {}) {
  const toast = useToast();
  const [form, setForm] = useState(null);
  const [active, setActive] = useState(null);       // { kind: "form" | "question" | "section", id }
  const [focus, setFocus] = useState(null);         // { kind, id, field, select? } — one shot
  const [saveState, setSaveState] = useState("idle");
  const [busy, setBusy] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const timers = useRef({});
  const pending = useRef({});
  const warnedVersion = useRef(false);
  const statusRef = useRef("draft");

  const items = useMemo(() => flatten(form), [form]);
  statusRef.current = form?.status || "draft";

  /* Stable, so the effect that consumes a focus request in a card does not re-run
     on every render of the tree above it. */
  const clearFocus = useCallback(() => setFocus(null), []);

  /* ----------------------------------------------------------------- loading */
  const load = useCallback(async () => {
    try {
      const fresh = await api(`/api/forms/${id}`);
      setForm(fresh);
      setLoadError("");
    } catch (e) { setLoadError(e.message); }
    setLoading(false);
  }, [id]);

  useEffect(() => { setLoading(true); load(); }, [load]);
  useEffect(() => () => Object.values(timers.current).forEach(clearTimeout), []);

  /* Clicking the page background collapses the active card, the way it does in
     Google Forms. Portalled menus and dialogs are not "outside" — dismissing the
     card under an open menu would close the menu's own owner. */
  useEffect(() => {
    const onPointerDown = (event) => {
      if (event.target.closest?.(".gf-card, .gf-rail, .inline-popup, .modal, .Toastify")) return;
      setActive(null);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      if (document.querySelector(".inline-popup, .modal")) return;   // that layer owns Escape
      setActive(null);
      document.activeElement?.blur?.();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  /* ------------------------------------------------------------------ saving */
  const markSaved = () => {
    setSaveState("saved");
    setTimeout(() => setSaveState((state) => (state === "saved" ? "idle" : state)), 1800);
  };

  /* The first edit after publish opens a new draft version server-side, so the
     writer is told once per session rather than per keystroke. */
  const ensureVersionEdit = useCallback(async () => {
    if (statusRef.current !== "published" || warnedVersion.current) return true;
    const ok = await confirmDialog(
      "Editing this published form creates a new draft version. Existing invites keep the version they were sent.",
      { title: "Create a new version?", confirmText: "Edit new version" });
    if (ok) warnedVersion.current = true;
    return ok;
  }, []);

  /** Debounced PATCH. Fields typed into the same row coalesce into one request. */
  const queueSave = useCallback((key, path, body, apply) => {
    clearTimeout(timers.current[key]);
    pending.current[key] = { ...(pending.current[key] || {}), ...body };
    setSaveState("saving");
    timers.current[key] = setTimeout(async () => {
      const payload = pending.current[key] || {};
      delete pending.current[key];
      try {
        const saved = await api(path, { method: "PATCH", body: payload });
        apply?.(saved);
        if (statusRef.current === "published") await load();
        markSaved();
      } catch (e) { setSaveState("error"); toast(e.message, "bad"); }
    }, 700);
  }, [load, toast]);

  const updateForm = useCallback(async (patch) => {
    if (!(await ensureVersionEdit())) return;
    setForm((current) => current && { ...current, ...patch });
    /* The server rejects a blank name. Clearing the field to retype is normal, so
       the keystroke lands locally and only the save waits for a name. */
    const { name, ...rest } = patch;
    const body = name !== undefined && !name.trim() ? rest : patch;
    if (!Object.keys(body).length) return;
    queueSave("form", `/api/forms/${id}`, body,
      (saved) => setForm((current) => current && { ...current, ...saved }));
  }, [ensureVersionEdit, id, queueSave]);

  const updateQuestion = useCallback(async (questionId, patch) => {
    if (!(await ensureVersionEdit())) return;
    setForm((current) => current && { ...current,
      questions: current.questions.map((question) => question.id === questionId
        ? { ...question, ...patch,
            // Mirrors the server: giving a question a source makes it a confirm field.
            ...(patch.prefill_source && patch.display_mode === undefined ? { display_mode: "confirm" } : {}) }
        : question) });
    queueSave(`question-${questionId}`, `/api/forms/questions/${questionId}`, patch,
      (saved) => setForm((current) => current && { ...current,
        questions: current.questions.map((question) => question.id === saved.id ? saved : question) }));
  }, [ensureVersionEdit, queueSave]);

  const updateSection = useCallback(async (sectionId, patch) => {
    if (!(await ensureVersionEdit())) return;
    setForm((current) => current && { ...current,
      sections: current.sections.map((section) => section.id === sectionId
        ? { ...section, ...patch } : section) });
    queueSave(`section-${sectionId}`, `/api/forms/sections/${sectionId}`, patch);
  }, [ensureVersionEdit, queueSave]);

  /* -------------------------------------------------------------- reordering */
  /** Writes a candidate canvas order back as positions + derived section_id. */
  const commitOrder = useCallback(async (next) => {
    if (!(await ensureVersionEdit())) return;
    const { questionIds, sectionIds, sectionOf } = deriveOrder(next);
    const movedQuestions = next.filter((item) => item.kind === "question"
      && (item.data?.section_id ?? null) !== (sectionOf.get(item.id) ?? null));
    const movedSections = next.filter((item) => item.kind === "section"
      && (item.data?.position ?? 0) !== sectionIds.indexOf(item.id) + 1);

    setSaveState("saving");
    setForm((current) => current && { ...current,
      questions: current.questions.map((question) => sectionOf.has(question.id)
        ? { ...question, position: questionIds.indexOf(question.id) + 1,
            section_id: sectionOf.get(question.id) ?? null }
        : question),
      sections: current.sections.map((section) => sectionIds.includes(section.id)
        ? { ...section, position: sectionIds.indexOf(section.id) + 1 } : section) });

    try {
      if (questionIds.length) {
        await api(`/api/forms/${id}/questions/reorder`,
          { method: "POST", body: { ordered_ids: questionIds } });
      }
      /* Sequential on purpose. Every write calls _begin_edit server-side, and two
         of those racing on a published form would open two draft versions. */
      for (const item of movedQuestions) {
        await api(`/api/forms/questions/${item.id}`,
          { method: "PATCH", body: { section_id: sectionOf.get(item.id) ?? null } });
      }
      for (const item of movedSections) {
        await api(`/api/forms/sections/${item.id}`,
          { method: "PATCH", body: { position: sectionIds.indexOf(item.id) + 1 } });
      }
      if (statusRef.current === "published") await load();
      markSaved();
    } catch (e) { setSaveState("error"); toast(e.message, "bad"); load(); }
  }, [ensureVersionEdit, id, load, toast]);

  /** Where a new card goes: straight below the active one, like Google Forms. */
  const insertIndex = useCallback(() => {
    if (!active || active.kind === "form") return 0;
    const at = items.findIndex((item) => sameCard(item, active));
    if (at < 0) return items.length;
    // Adding below a section header means "first question in that section".
    return at + 1;
  }, [active, items]);

  /* ------------------------------------------------------------ adding cards */
  const addQuestion = useCallback(async (type = "short_text", at = null) => {
    if (!(await ensureVersionEdit())) return null;
    const list = items;
    const index = at ?? insertIndex();
    setBusy("add");
    try {
      const made = await api(`/api/forms/${id}/questions`, { method: "POST", body: {
        type, label: "Untitled question", section_id: sectionAt(list, index),
        position: (form?.questions?.length || 0) + 1, options: defaultOptions(type),
      } });
      setForm((current) => current && { ...current, questions: [...current.questions, made] });
      setActive({ kind: "question", id: made.id });
      setFocus({ kind: "question", id: made.id, field: "title", select: true });
      await commitOrder([...list.slice(0, index),
        { kind: "question", id: made.id, data: made }, ...list.slice(index)]);
      setBusy("");
      return made;
    } catch (e) { toast(e.message, "bad"); setBusy(""); return null; }
  }, [commitOrder, ensureVersionEdit, form, id, insertIndex, items, toast]);

  const addSection = useCallback(async ({ focusField = "title" } = {}) => {
    if (!(await ensureVersionEdit())) return null;
    const list = items;
    const index = insertIndex();
    setBusy("add");
    try {
      const made = await api(`/api/forms/${id}/sections`, { method: "POST", body: {
        title: "Untitled section", description: "",
        position: (form?.sections?.length || 0) + 1,
      } });
      setForm((current) => current && { ...current, sections: [...current.sections, made] });
      setActive({ kind: "section", id: made.id });
      setFocus({ kind: "section", id: made.id, field: focusField, select: focusField === "title" });
      await commitOrder([...list.slice(0, index),
        { kind: "section", id: made.id, data: made }, ...list.slice(index)]);
      setBusy("");
      return made;
    } catch (e) { toast(e.message, "bad"); setBusy(""); return null; }
  }, [commitOrder, ensureVersionEdit, form, id, insertIndex, items, toast]);

  const duplicateCard = useCallback(async (item) => {
    if (!(await ensureVersionEdit())) return;
    const list = items;
    const from = list.findIndex((entry) => keyOf(entry) === keyOf(item));
    if (from < 0) return;
    try {
      if (item.kind === "question") {
        const source = item.data;
        const made = await api(`/api/forms/${id}/questions`, { method: "POST", body: {
          type: source.type, label: source.label, help_text: source.help_text || "",
          required: !!source.required, options: source.options || {},
          maps_to: source.maps_to || null, prefill_source: source.prefill_source || null,
          display_mode: source.display_mode || "ask", section_id: source.section_id || null,
          position: (form?.questions?.length || 0) + 1,
        } });
        setForm((current) => current && { ...current, questions: [...current.questions, made] });
        setActive({ kind: "question", id: made.id });
        await commitOrder([...list.slice(0, from + 1),
          { kind: "question", id: made.id, data: made }, ...list.slice(from + 1)]);
        return;
      }
      // A section copy lands after the original's whole block, not inside it.
      let end = from + 1;
      while (end < list.length && list[end].kind === "question") end += 1;
      const made = await api(`/api/forms/${id}/sections`, { method: "POST", body: {
        title: item.data.title, description: item.data.description || "",
        position: (form?.sections?.length || 0) + 1,
      } });
      setForm((current) => current && { ...current, sections: [...current.sections, made] });
      setActive({ kind: "section", id: made.id });
      await commitOrder([...list.slice(0, end),
        { kind: "section", id: made.id, data: made }, ...list.slice(end)]);
    } catch (e) { toast(e.message, "bad"); }
  }, [commitOrder, ensureVersionEdit, form, id, items, toast]);

  const removeCard = useCallback(async (item) => {
    const question = item.kind === "question";
    const ok = await confirmDialog(question
      ? "Delete this question? Published versions already sent stay unchanged."
      : "Delete this section? Its questions move into the section above it.",
      { danger: true, confirmText: "Delete" });
    if (!ok || !(await ensureVersionEdit())) return;
    const next = items.filter((entry) => keyOf(entry) !== keyOf(item));
    try {
      await api(`/api/forms/${question ? "questions" : "sections"}/${item.id}`, { method: "DELETE" });
      setActive(null);
      setForm((current) => current && (question
        ? { ...current, questions: current.questions.filter((row) => row.id !== item.id) }
        : { ...current, sections: current.sections.filter((row) => row.id !== item.id) }));
      /* The server nulls a deleted section's questions. Re-committing the order
         re-derives them from the header above, so nothing jumps to the top. */
      await commitOrder(next);
    } catch (e) { toast(e.message, "bad"); load(); }
  }, [commitOrder, ensureVersionEdit, items, load, toast]);

  /* --------------------------------------------------------------- moving */
  const moveCard = useCallback((fromKey, toKey, edge) => {
    if (fromKey === toKey) return;
    const list = items;
    const from = list.findIndex((item) => keyOf(item) === fromKey);
    if (from < 0) return;
    /* A section travels with the questions under it — that block is what the
       writer sees as "the section". */
    let span = 1;
    if (list[from].kind === "section") {
      while (from + span < list.length && list[from + span].kind === "question") span += 1;
    }
    const chunk = list.slice(from, from + span);
    const rest = [...list.slice(0, from), ...list.slice(from + span)];
    let to = rest.findIndex((item) => keyOf(item) === toKey);
    if (to < 0) return;                       // dropped inside its own block
    if (edge === "after") to += 1;
    commitOrder([...rest.slice(0, to), ...chunk, ...rest.slice(to)]);
  }, [commitOrder, items]);

  /** The ⋮ menu's Section picker. Moves the card so position and section agree. */
  const moveToSection = useCallback((question, sectionId) => {
    const list = items;
    const from = list.findIndex((item) => item.kind === "question" && item.id === question.id);
    if (from < 0) return;
    const rest = [...list.slice(0, from), ...list.slice(from + 1)];
    let to;
    if (sectionId == null) {
      to = rest.findIndex((item) => item.kind === "section");
      if (to < 0) to = rest.length;
    } else {
      const head = rest.findIndex((item) => item.kind === "section" && item.id === sectionId);
      if (head < 0) return;
      to = head + 1;
      while (to < rest.length && rest[to].kind === "question") to += 1;
    }
    commitOrder([...rest.slice(0, to), list[from], ...rest.slice(to)]);
  }, [commitOrder, items]);

  /* Google's "import questions" pulls from another form; ours does the same, and
     needs no template system to do it. */
  const importQuestions = useCallback(async (sourceId, questionIds) => {
    if (!questionIds.length || !(await ensureVersionEdit())) return;
    setBusy("import");
    try {
      const source = await api(`/api/forms/${sourceId}`);
      const chosen = source.questions
        .filter((question) => questionIds.includes(question.id))
        .sort((a, b) => a.position - b.position);
      const tail = sectionAt(items, items.length);
      for (const question of chosen) {
        await api(`/api/forms/${id}/questions`, { method: "POST", body: {
          type: question.type, label: question.label, help_text: question.help_text || "",
          required: !!question.required, options: question.options || {},
          maps_to: question.maps_to || null, prefill_source: question.prefill_source || null,
          display_mode: question.display_mode || "ask", section_id: tail,
        } });
      }
      await load();
      toast(`Imported ${chosen.length} question${chosen.length === 1 ? "" : "s"}`);
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
  }, [ensureVersionEdit, id, items, load, toast]);

  /* ----------------------------------------------------------- form actions */
  const publish = useCallback(async () => {
    setBusy("publish");
    try {
      const saved = await api(`/api/forms/${id}/publish`, { method: "POST" });
      setForm((current) => current && { ...current, ...saved });
      warnedVersion.current = false;
      toast("Form published");
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
  }, [id, toast]);

  const duplicateForm = useCallback(async () => {
    setBusy("duplicate");
    try {
      const made = await api(`/api/forms/${id}/duplicate`, { method: "POST" });
      toast("Duplicated — editing the copy");
      onDuplicated?.(made);
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
  }, [id, onDuplicated, toast]);

  return {
    form, items, loading, loadError, reload: load,
    active, setActive, isActive: (item) => sameCard(active, item),
    focus, clearFocus, requestFocus: setFocus,
    saveState, busy,
    updateForm, updateQuestion, updateSection,
    addQuestion, addSection, duplicateCard, removeCard,
    moveCard, moveToSection, importQuestions,
    publish, duplicateForm,
  };
}
