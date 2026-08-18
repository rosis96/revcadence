// Focused block types. Whiteboard is a document-native thinking surface, not a
// separate app, so it is dispatched beside text and tables here.
//
// Only `text` runs a ProseMirror instance (TipTap), because only `text` is
// genuinely rich. A checklist or a table inside ProseMirror would be a worse
// editor than a purpose-built one, and every block is its own Block row anyway,
// so there is nothing to gain from one big document instance.
//
// `live` and `view` render labelled placeholder cards. They are NOT stubbed out
// of the union — the binding columns exist and the resolver is a later step.
import { useEffect, useRef } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import {
  AlertCircle, Check, Info, LayoutGrid, Link2, Minus, Paperclip, Table2, TriangleAlert, Zap,
} from "lucide-react";
import WhiteboardBlock from "./WhiteboardBlock";
import { Area } from "../components";

export const BLOCK_TYPES = [
  "heading", "text", "list", "checklist", "callout",
  "table", "file", "divider", "embed", "live", "view", "whiteboard",
];

// Slash-menu catalogue: label, icon, and the content a fresh block starts with.
export const BLOCK_MENU = [
  { type: "text", label: "Text", hint: "Plain paragraph", icon: Info, blank: { html: "" } },
  { type: "heading", label: "Heading", hint: "Section title", icon: Info, blank: { level: 2, text: "" } },
  { type: "list", label: "Bulleted list", hint: "Simple list", icon: Info, blank: { ordered: false, items: [""] } },
  { type: "checklist", label: "Checklist", hint: "Tickable items", icon: Check, blank: { items: [{ text: "", done: false }] } },
  { type: "callout", label: "Callout", hint: "Highlight a note", icon: Info, blank: { tone: "info", text: "" } },
  { type: "table", label: "Table", hint: "Rows and columns", icon: Table2, blank: { columns: ["Column", "Column"], rows: [["", ""]] } },
  { type: "file", label: "File", hint: "Attach a document", icon: Paperclip, blank: { upload_id: "", name: "", size: 0 } },
  { type: "divider", label: "Divider", hint: "Section break", icon: Minus, blank: {} },
  { type: "embed", label: "Embed", hint: "External link", icon: Link2, blank: { url: "", provider: "" } },
  { type: "live", label: "Live value", hint: "Pulls from the brain", icon: Zap, blank: { display: "" } },
  { type: "view", label: "Saved view", hint: "Embed a table or board", icon: Table2, blank: { view_id: null } },
  // `snapshot: null` is an untouched board: tldraw builds its own first document,
  // and inventing one here would pin a schema version that goes stale.
  { type: "whiteboard", label: "Whiteboard", hint: "Map segments, triggers, and proof", icon: LayoutGrid,
    blank: { kind: "tldraw", snapshot: null } },
];

const CALLOUT_TONES = [
  { key: "info", label: "Info", icon: Info },
  { key: "warn", label: "Warning", icon: TriangleAlert },
  { key: "bad", label: "Problem", icon: AlertCircle },
];

const fileSize = (bytes) => {
  const n = Number(bytes) || 0;
  if (!n) return "";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
};

/* ---------------------------------------------------------------- text (TipTap) */
function TextBlock({ content, onChange, readOnly }) {
  const editor = useEditor({
    editable: !readOnly,
    extensions: [
      StarterKit.configure({ heading: false, codeBlock: false, horizontalRule: false }),
      Placeholder.configure({ placeholder: "Write something, or press / for blocks…" }),
    ],
    content: content?.html || "",
    onUpdate: ({ editor: ed }) => onChange({ html: ed.getHTML() }),
  }, [readOnly]);

  // Only push external content in when this editor is not the source of it —
  // otherwise every autosave round-trip would reset the caret to the start.
  const lastPushed = useRef(content?.html || "");
  useEffect(() => {
    const incoming = content?.html || "";
    if (!editor || incoming === lastPushed.current) return;
    if (incoming !== editor.getHTML()) editor.commands.setContent(incoming, false);
    lastPushed.current = incoming;
  }, [content?.html, editor]);

  return <EditorContent className="db-text" editor={editor} />;
}

/* ---------------------------------------------------------------- heading */
function HeadingBlock({ content, onChange, readOnly }) {
  const level = content?.level || 2;
  return (
    <div className="db-heading">
      {!readOnly && (
        <div className="db-h-levels">
          {[1, 2, 3].map((l) => (
            <button key={l} type="button" className={`db-h-lvl ${l === level ? "on" : ""}`}
              onClick={() => onChange({ ...content, level: l })} title={`Heading ${l}`}>H{l}</button>
          ))}
        </div>
      )}
      <input className={`db-h-input h${level}`} value={content?.text || ""} readOnly={readOnly}
        placeholder="Heading" onChange={(e) => onChange({ ...content, text: e.target.value })} />
    </div>
  );
}

/* ---------------------------------------------------------------- list */
function ListBlock({ content, onChange, readOnly }) {
  const items = content?.items?.length ? content.items : [""];
  const ordered = !!content?.ordered;
  const set = (i, v) => onChange({ ...content, items: items.map((it, n) => (n === i ? v : it)) });
  const add = (i) => onChange({ ...content, items: [...items.slice(0, i + 1), "", ...items.slice(i + 1)] });
  const remove = (i) => onChange({ ...content, items: items.length > 1 ? items.filter((_, n) => n !== i) : [""] });
  return (
    <div className="db-list">
      {!readOnly && (
        <div className="db-h-levels">
          <button type="button" className={`db-h-lvl ${ordered ? "" : "on"}`}
            onClick={() => onChange({ ...content, ordered: false })}>Bulleted</button>
          <button type="button" className={`db-h-lvl ${ordered ? "on" : ""}`}
            onClick={() => onChange({ ...content, ordered: true })}>Numbered</button>
        </div>
      )}
      {items.map((it, i) => (
        <div className="db-li" key={i}>
          <span className="db-li-mark">{ordered ? `${i + 1}.` : "•"}</span>
          <input value={it} readOnly={readOnly} placeholder="List item"
            onChange={(e) => set(i, e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); add(i); }
              if (e.key === "Backspace" && !it && items.length > 1) { e.preventDefault(); remove(i); }
            }} />
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- checklist */
function ChecklistBlock({ content, onChange, readOnly }) {
  const items = content?.items?.length ? content.items : [{ text: "", done: false }];
  const set = (i, patch) =>
    onChange({ ...content, items: items.map((it, n) => (n === i ? { ...it, ...patch } : it)) });
  const add = (i) => onChange({
    ...content,
    items: [...items.slice(0, i + 1), { text: "", done: false }, ...items.slice(i + 1)],
  });
  return (
    <div className="db-list">
      {items.map((it, i) => (
        <div className="db-li check" key={i}>
          <button type="button" className={`db-check ${it.done ? "on" : ""}`} disabled={readOnly}
            aria-label={it.done ? "Mark not done" : "Mark done"}
            onClick={() => set(i, { done: !it.done })}>{it.done && <Check size={11} />}</button>
          <input className={it.done ? "done" : ""} value={it.text || ""} readOnly={readOnly}
            placeholder="To do" onChange={(e) => set(i, { text: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(i); } }} />
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- callout */
function CalloutBlock({ content, onChange, readOnly }) {
  const tone = content?.tone || "info";
  const Icon = (CALLOUT_TONES.find((t) => t.key === tone) || CALLOUT_TONES[0]).icon;
  return (
    <div className={`db-callout tone-${tone}`}>
      <span className="db-callout-ic"><Icon size={15} /></span>
      <Area className="db-callout-text" value={content?.text || ""} readOnly={readOnly}
        size="sm" placeholder="Something worth calling out"
        onChange={(e) => onChange({ ...content, text: e.target.value })} />
      {!readOnly && (
        <div className="db-h-levels">
          {CALLOUT_TONES.map((t) => (
            <button key={t.key} type="button" className={`db-h-lvl ${t.key === tone ? "on" : ""}`}
              onClick={() => onChange({ ...content, tone: t.key })}>{t.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- table */
function TableBlock({ content, onChange, readOnly }) {
  const columns = content?.columns?.length ? content.columns : ["Column"];
  const rows = content?.rows?.length ? content.rows : [columns.map(() => "")];
  const setCol = (c, v) => onChange({ ...content, columns: columns.map((x, i) => (i === c ? v : x)), rows });
  const setCell = (r, c, v) => onChange({
    ...content, columns,
    rows: rows.map((row, i) => (i === r ? row.map((x, j) => (j === c ? v : x)) : row)),
  });
  const addRow = () => onChange({ ...content, columns, rows: [...rows, columns.map(() => "")] });
  const addCol = () => onChange({
    ...content, columns: [...columns, "Column"], rows: rows.map((row) => [...row, ""]),
  });
  return (
    <div className="db-table-wrap">
      <table className="db-table">
        <thead>
          <tr>{columns.map((c, i) => (
            <th key={i}><input value={c} readOnly={readOnly} placeholder="Column"
              onChange={(e) => setCol(i, e.target.value)} /></th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>{columns.map((_, c) => (
              <td key={c}><input value={row[c] ?? ""} readOnly={readOnly}
                onChange={(e) => setCell(r, c, e.target.value)} /></td>
            ))}</tr>
          ))}
        </tbody>
      </table>
      {!readOnly && (
        <div className="db-h-levels">
          <button type="button" className="db-h-lvl" onClick={addRow}>+ Row</button>
          <button type="button" className="db-h-lvl" onClick={addCol}>+ Column</button>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- file */
// Metadata only: there is no upload endpoint yet, so nothing here can mint an
// upload_id. The block records what the file is; attaching bytes comes later.
function FileBlock({ content, onChange, readOnly }) {
  return (
    <div className="db-file">
      <span className="db-file-ic"><Paperclip size={15} /></span>
      <input className="db-file-name" value={content?.name || ""} readOnly={readOnly}
        placeholder="File name" onChange={(e) => onChange({ ...content, name: e.target.value })} />
      {content?.size ? <span className="db-file-size">{fileSize(content.size)}</span> : null}
    </div>
  );
}

/* ---------------------------------------------------------------- embed */
function EmbedBlock({ content, onChange, readOnly }) {
  const url = content?.url || "";
  return (
    <div className="db-embed">
      <span className="db-file-ic"><Link2 size={15} /></span>
      <input className="db-file-name" value={url} readOnly={readOnly} placeholder="https://…"
        onChange={(e) => {
          const next = e.target.value;
          let provider = "";
          try { provider = next ? new URL(next).hostname.replace(/^www\./, "") : ""; } catch { provider = ""; }
          onChange({ ...content, url: next, provider });
        }} />
      {content?.provider && <span className="db-file-size">{content.provider}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- placeholders */
// Deliberately visible and labelled rather than silently blank: an operator
// should be able to tell the difference between "not wired yet" and "broken".
function PlaceholderBlock({ icon: Icon, kind, title, hint }) {
  return (
    <div className="db-placeholder">
      <span className="db-ph-ic"><Icon size={15} /></span>
      <span className="db-ph-body">
        <b>{title}</b>
        <em>{hint}</em>
      </span>
      <span className="db-ph-tag">{kind}</span>
    </div>
  );
}

/* ---------------------------------------------------------------- dispatch */
export function BlockBody({ block, onChange, readOnly = false, onManagedState }) {
  const props = { content: block.content || {}, onChange, readOnly };
  switch (block.type) {
    case "text": return <TextBlock {...props} />;
    case "heading": return <HeadingBlock {...props} />;
    case "list": return <ListBlock {...props} />;
    case "checklist": return <ChecklistBlock {...props} />;
    case "callout": return <CalloutBlock {...props} />;
    case "table": return <TableBlock {...props} />;
    case "file": return <FileBlock {...props} />;
    case "embed": return <EmbedBlock {...props} />;
    case "divider": return <hr className="db-divider" />;
    case "live":
      return <PlaceholderBlock icon={Zap} kind="Live" title={block.content?.display || "Live value"}
        hint={block.field_path ? `Bound to ${block.entity_type} · ${block.field_path}` : "Not bound yet"} />;
    case "view":
      return <PlaceholderBlock icon={Table2} kind="View" title="Saved view"
        hint={block.content?.view_id ? `View #${block.content.view_id}` : "No view selected yet"} />;
    case "whiteboard":
      return <WhiteboardBlock block={block} readOnly={readOnly} onState={onManagedState} />;
    default:
      return <PlaceholderBlock icon={AlertCircle} kind="Unknown" title={block.type}
        hint="This block type is not recognised" />;
  }
}
