/* Inline formatting for form copy.

   Google Forms puts a Bold / Italic / Underline / Link toolbar under the question
   title, so the builder needs one too. `form_questions.label` is a plain string
   and the client-facing page prints it as text, so rather than move HTML through
   the API — which would put a sanitising problem on the render the client sees —
   the toolbar writes markers into the string (**bold**, *italic*, __underline__,
   [label](url)) and <RichText> is the single place that turns them back into
   elements.

   The stored value stays a string, so everything downstream that reads a label
   (the version snapshot, the mapping audit, the response drawer) keeps working
   untouched, and a label that was never formatted is byte-identical to before. */
import { useMemo } from "react";

export const MARKS = { bold: "**", italic: "*", underline: "__" };

/* Ordered longest-first: *** has to be tried before **, which has to be tried
   before *, or the shorter rule eats the opening of the longer one. */
const RULES = [
  { re: /\[([^\]\n]+)\]\(([^)\s]+)\)/,
    wrap: (m, key, walk) => <a key={key} href={m[2]} target="_blank" rel="noreferrer">{walk(m[1])}</a> },
  { re: /\*\*\*([^\n]+?)\*\*\*/, wrap: (m, key, walk) => <strong key={key}><em>{walk(m[1])}</em></strong> },
  { re: /\*\*([^\n]+?)\*\*/, wrap: (m, key, walk) => <strong key={key}>{walk(m[1])}</strong> },
  { re: /__([^\n]+?)__/, wrap: (m, key, walk) => <u key={key}>{walk(m[1])}</u> },
  { re: /\*([^\n*]+?)\*/, wrap: (m, key, walk) => <em key={key}>{walk(m[1])}</em> },
];

function parse(text, depth = 0) {
  if (!text) return [];
  if (depth > 4) return [text];
  let best = null;
  for (const rule of RULES) {
    const match = rule.re.exec(text);
    if (match && (best === null || match.index < best.match.index)) best = { rule, match };
  }
  if (!best) return [text];
  const { rule, match } = best;
  const walk = (inner) => parse(inner, depth + 1);
  return [
    ...parse(text.slice(0, match.index), depth + 1),
    rule.wrap(match, `rt-${depth}-${match.index}`, walk),
    ...parse(text.slice(match.index + match[0].length), depth + 1),
  ];
}

/** Formatted read-only render of a stored label. */
export function RichText({ text, as: Tag = "span", className, fallback = "" }) {
  const value = String(text ?? "");
  const nodes = useMemo(() => parse(value), [value]);
  if (!value) return fallback ? <Tag className={className}>{fallback}</Tag> : null;
  return <Tag className={className}>{nodes}</Tag>;
}

/** Every marker removed, links reduced to their label. */
export function stripMarks(text) {
  return String(text ?? "")
    .replace(/\[([^\]\n]+)\]\([^)\s]*\)/g, "$1")
    .replace(/\*\*\*|\*\*|__|\*/g, "");
}

/* Each editing helper returns { value, start, end } so the caller can put the
   caret back where the writer expects it rather than at the end of the field. */

export function toggleMark(value, start, end, kind) {
  const text = String(value ?? "");
  const mark = MARKS[kind];
  const len = mark.length;

  // No selection: drop an empty pair and park the caret inside it, so whatever
  // gets typed next lands already formatted.
  if (start === end) {
    return { value: text.slice(0, start) + mark + mark + text.slice(start),
             start: start + len, end: start + len };
  }

  const inner = text.slice(start, end);
  // A single * sits inside every **, so italic must not read a bold marker as
  // its own and unwrap half of it.
  const boldNeighbour = kind === "italic"
    && (text.slice(start - 2, start) === "**" || text.slice(end, end + 2) === "**");

  if (!boldNeighbour && text.slice(start - len, start) === mark && text.slice(end, end + len) === mark) {
    return { value: text.slice(0, start - len) + inner + text.slice(end + len),
             start: start - len, end: end - len };
  }
  if (!boldNeighbour && inner.length > len * 2 && inner.startsWith(mark) && inner.endsWith(mark)) {
    const bare = inner.slice(len, -len);
    return { value: text.slice(0, start) + bare + text.slice(end), start, end: start + bare.length };
  }
  return { value: text.slice(0, start) + mark + inner + mark + text.slice(end),
           start: start + len, end: end + len };
}

export function insertLink(value, start, end, url) {
  const text = String(value ?? "");
  const label = text.slice(start, end) || url;
  const link = `[${label}](${url})`;
  return { value: text.slice(0, start) + link + text.slice(end),
           start: start + link.length, end: start + link.length };
}

/** Selection only, or the whole field when nothing is selected. */
export function clearFormatting(value, start, end) {
  const text = String(value ?? "");
  if (start === end) {
    const bare = stripMarks(text);
    return { value: bare, start: bare.length, end: bare.length };
  }
  /* The marks wrapping a selection sit just outside it — that is where toggling
     bold leaves the caret. Pull them in before stripping, or clearing a bold word
     reads as doing nothing at all. */
  let from = start;
  let to = end;
  while (from > 0 && "*_".includes(text[from - 1])) from -= 1;
  while (to < text.length && "*_".includes(text[to])) to += 1;
  const bare = stripMarks(text.slice(from, to));
  return { value: text.slice(0, from) + bare + text.slice(to), start: from, end: from + bare.length };
}
