/* One table for the question types, so the type dropdown, the card body, and the
   defaults a new question is created with can never disagree.

   `value` is the wire value in app/models/forms.py QUESTION_TYPES — do not rename
   these. `label` is Google's name for the same control where one exists (short
   answer, paragraph, multiple choice, checkboxes, dropdown); the rest are ours
   and keep our names. */
import { AlignLeft, Calendar, CheckSquare, ChevronDownCircle, CircleDot, Hash,
  Link2, Mail, Minus, ToggleLeft, Upload } from "lucide-react";

export const TYPES = [
  { value: "short_text", label: "Short answer", group: "Text", icon: Minus },
  { value: "long_text", label: "Paragraph", group: "Text", icon: AlignLeft },
  { value: "single_choice", label: "Multiple choice", group: "Choice", icon: CircleDot },
  { value: "multi_choice", label: "Checkboxes", group: "Choice", icon: CheckSquare },
  { value: "dropdown", label: "Dropdown", group: "Choice", icon: ChevronDownCircle },
  { value: "yes_no", label: "Yes / no", group: "Choice", icon: ToggleLeft },
  { value: "number", label: "Number", group: "Structured", icon: Hash },
  { value: "date", label: "Date", group: "Structured", icon: Calendar },
  { value: "email", label: "Email", group: "Structured", icon: Mail },
  { value: "url", label: "URL", group: "Structured", icon: Link2 },
  { value: "file_upload", label: "File upload", group: "Structured", icon: Upload },
];

export const TYPE_BY_VALUE = Object.fromEntries(TYPES.map((type) => [type.value, type]));
export const typeLabel = (value) => TYPE_BY_VALUE[value]?.label || value;

/** Types whose options the writer edits as a list of choices. */
export const CHOICE_TYPES = new Set(["single_choice", "multi_choice", "dropdown"]);
/** Types that render a control but have nothing to configure in the card body. */
export const FIXED_CHOICE_TYPES = new Set(["yes_no"]);

export function defaultOptions(type, previous = {}) {
  if (CHOICE_TYPES.has(type)) {
    const choices = previous.choices?.length ? previous.choices : ["Option 1"];
    return { ...previous, choices };
  }
  if (type === "file_upload") {
    return { ...previous, accepted_file_types: previous.accepted_file_types
      || ["pdf", "doc", "docx", "png", "jpg"] };
  }
  const { choices, ...rest } = previous;   // eslint-disable-line no-unused-vars
  return rest;
}

/* Our four extra per-question settings. Google has no equivalent, so they live
   in the card's ⋮ menu — see CardMenu. */
export const MAP_LABELS = {
  "workspace.name": "Workspace · name", "client.website_url": "Client · website URL",
  "client.contact_name": "Client · contact name", "client.contact_email": "Client · contact email",
  "client.role": "Client · role", "client.timezone": "Client · timezone",
  "brain.offers": "Brain · offers", "brain.positioning": "Brain · positioning",
  "icp.titles": "ICP · titles", "icp.geo": "ICP · geography",
  "icp.company_size": "ICP · company size", "icp.reject_signals": "ICP · reject signals",
  "library.do_not_contact": "Library · do not contact", "library.case_study": "Library · case study",
  "approval.copy_approver": "Approval · copy approver", "infra.booking_link": "Infrastructure · booking link",
  "infra.has_domains": "Infrastructure · has domains",
};

export const PREFILL_LABELS = {
  "invite.contact_name": "Contact name", "invite.contact_email": "Contact email",
  "invite.company_name": "Company name", "invite.website_url": "Website URL",
  "crawl.positioning": "Crawled positioning", "crawl.offers": "Crawled offers",
  "crawl.case_studies": "Crawled case studies",
};

export const DISPLAY_MODES = [
  { value: "ask", label: "Ask · blank field" },
  { value: "confirm", label: "Confirm · pre-filled and editable" },
  { value: "readonly", label: "Readonly · context only" },
];
