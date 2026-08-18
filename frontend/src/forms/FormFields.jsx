import { useState } from "react";
import { Check, Edit3, FileUp } from "lucide-react";
import { Area, Input, Select } from "../components";
import { RichText } from "./richtext";

const CONTACT_SOURCES = new Set([
  "invite.contact_name", "invite.contact_email", "invite.company_name", "invite.website_url",
]);

export const isAnswered = (value) => value !== undefined && value !== null && value !== ""
  && (!Array.isArray(value) || value.length > 0);

function choicesOf(question) {
  return (question.options?.choices || []).map((choice) => typeof choice === "object"
    ? { value: choice.value, label: choice.label || choice.value }
    : { value: choice, label: choice });
}

function QuestionField({ question, value, onChange, onBlur, onUpload, disabled, error }) {
  const choices = choicesOf(question);
  const set = (next) => onChange(question.id, next, true);
  const common = {
    id: `form-question-${question.id}`,
    disabled,
    "aria-invalid": !!error,
    onBlur: () => onBlur?.(question.id),
  };

  if (question.display_mode === "readonly") {
    const shown = Array.isArray(value) ? value.join(", ") : String(value ?? "—");
    return <div className="forms-readonly" id={common.id}>{shown}</div>;
  }
  if (question.type === "long_text") {
    return <Area {...common} size="md" value={value ?? ""} onChange={(e) => set(e.target.value)} />;
  }
  if (question.type === "single_choice" || question.type === "yes_no") {
    const opts = question.type === "yes_no"
      ? [{ value: true, label: "Yes" }, { value: false, label: "No" }]
      : choices;
    return (
      <div className="forms-choice-list" id={common.id} onBlur={common.onBlur}>
        {opts.map((option) => (
          <label key={String(option.value)} className="forms-choice">
            <input type="radio" name={`q-${question.id}`} disabled={disabled}
              checked={value === option.value} onChange={() => set(option.value)} />
            <span className="forms-choice-control" />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    );
  }
  if (question.type === "multi_choice") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <div className="forms-choice-list" id={common.id} onBlur={common.onBlur}>
        {choices.map((option) => {
          const checked = selected.includes(option.value);
          return (
            <label key={String(option.value)} className="forms-choice">
              <input type="checkbox" disabled={disabled} checked={checked}
                onChange={() => set(checked ? selected.filter((item) => item !== option.value) : [...selected, option.value])} />
              <span className="forms-choice-control square">{checked && <Check size={12} />}</span>
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
    );
  }
  if (question.type === "dropdown") {
    return (
      <Select {...common} value={value ?? ""} onChange={(e) => set(e.target.value)}>
        <option value="">Choose an option</option>
        {choices.map((option) => <option key={String(option.value)} value={option.value}>{option.label}</option>)}
      </Select>
    );
  }
  if (question.type === "file_upload") {
    return (
      <div className="forms-upload" id={common.id}>
        {value?.name && <div className="forms-uploaded"><Check size={15} /> {value.name}</div>}
        <label className={`ui-btn secondary md ${disabled ? "disabled" : ""}`}>
          <FileUp size={16} /> {value?.name ? "Replace file" : "Choose file"}
          <input type="file" hidden disabled={disabled} accept=".pdf,.doc,.docx,.png,.jpg"
            onChange={(event) => event.target.files?.[0] && onUpload?.(question, event.target.files[0])} />
        </label>
        <span className="forms-upload-hint">PDF, DOC, DOCX, PNG or JPG · 10MB max</span>
      </div>
    );
  }
  const inputType = {
    number: "number", date: "date", email: "email", url: "url",
  }[question.type] || "text";
  return <Input {...common} type={inputType} value={value ?? ""}
    min={question.options?.min} max={question.options?.max}
    onChange={(e) => set(inputType === "number" ? e.target.value : e.target.value)} />;
}

function DetailsBlock({ details, onChange, disabled = false, onBlur }) {
  const [editing, setEditing] = useState(false);
  const fields = [
    ["name", "Name"], ["email", "Email"], ["company", "Company"], ["website", "Website"],
  ];
  return (
    <section className="forms-details">
      <div className="forms-details-head">
        <div><span className="forms-kicker">Your details</span><p>Here’s what we already have on file.</p></div>
        {!disabled && <button type="button" className="forms-edit-details" onClick={() => setEditing((value) => !value)}>
          <Edit3 size={13} /> {editing ? "Done" : "Not right?"}
        </button>}
      </div>
      <div className="forms-details-grid">
        {fields.map(([key, label]) => (
          <div key={key} className="forms-detail">
            <span>{label}</span>
            {editing && !disabled
              ? <Input type={key === "email" ? "email" : key === "website" ? "url" : "text"}
                  value={details?.[key] || ""} onChange={(e) => onChange({ ...details, [key]: e.target.value })}
                  onBlur={onBlur} />
              : <b>{details?.[key] || "—"}</b>}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function FormFields({ schema, answers, setAnswer, details, setDetails,
  errors = {}, onBlur, onDetailsBlur, onUpload, disabled = false }) {
  const sections = [...(schema?.sections || [])].sort((a, b) => a.position - b.position);
  const bodyQuestions = [...(schema?.questions || [])]
    .filter((question) => !question.contact_detail && !CONTACT_SOURCES.has(question.prefill_source))
    .sort((a, b) => a.position - b.position);
  const unsectioned = bodyQuestions.filter((question) => !question.section_id);
  const groups = [
    ...(unsectioned.length ? [{ id: "unsectioned", title: "", description: "", questions: unsectioned }] : []),
    ...sections.map((section) => ({ ...section,
      questions: bodyQuestions.filter((question) => question.section_id === section.id) })),
  ].filter((group) => group.questions.length || group.title);

  return (
    <>
      <DetailsBlock details={details} onChange={setDetails} disabled={disabled} onBlur={onDetailsBlur} />
      <div className="forms-public-body">
        {groups.map((group) => (
          <section key={group.id} className="forms-public-section">
            {/* Section and question copy can carry inline formatting from the
                builder's toolbar; RichText is what turns those markers back into
                elements instead of showing them as asterisks. */}
            {group.title && <div className="forms-section-heading"><RichText as="h2" text={group.title} />
              {group.description && <RichText as="p" text={group.description} />}</div>}
            {group.questions.map((question) => {
              const value = answers?.[question.id] ?? question.prefill_value ?? "";
              const confirm = question.prefill_source && question.display_mode === "confirm";
              return (
                <div key={question.id} className={`forms-public-question ${errors[question.id] ? "has-error" : ""}`}>
                  {confirm && <div className="forms-confirm-note">We read your site — please confirm or edit</div>}
                  <label htmlFor={`form-question-${question.id}`}>
                    <RichText text={question.label} />{question.required && <em>Required</em>}
                  </label>
                  {question.help_text?.trim() && <RichText as="p" className="forms-help" text={question.help_text} />}
                  <QuestionField question={question} value={value} onChange={setAnswer}
                    onBlur={onBlur} onUpload={onUpload} disabled={disabled} error={errors[question.id]} />
                  {errors[question.id] && <div className="forms-field-error">{errors[question.id]}</div>}
                </div>
              );
            })}
          </section>
        ))}
      </div>
    </>
  );
}
