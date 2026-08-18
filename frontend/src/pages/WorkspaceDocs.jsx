// Shared Documents — the page tree and the document, side by side.
//
// One screen serves both routes: /workspace/docs (tree + empty state) and
// /workspace/docs/:pageId (tree + document). Nesting routes would remount the
// tree on every page change for no benefit.
//
// Autosave is per block, using the shared useAutoSave hook — each block is its
// own editable region backed by one Block row, so each owns its own debounce.
// The toolbar shows the aggregate state through the shared SaveIndicator.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  Check, ChevronRight, Clock, EyeOff, FileText, Folder, FolderOpen, FolderPlus,
  GripVertical, MessageSquare, Plus, Share2, Trash2,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import {
  Button, confirmDialog, Drawer, EmptyState, Modal, SaveIndicator, Select,
  Skeleton, StatusPill, useAutoSave, useToast, VersionList,
} from "../components";
import { BLOCK_MENU, BlockBody } from "../docs/blocks";
import IconPicker, { PageIcon } from "../docs/IconPicker";
import { docsBaseFrom } from "../clientspace/nav";

const SECTION_LABELS = {
  strategy: "Strategy", operations: "Operations", reference: "Reference", internal: "Internal",
};
const STATUS_TONE = { draft: "gray", in_review: "blue", changes_requested: "amber", approved: "green" };
const STATUS_LABEL = {
  draft: "Draft", in_review: "In review", changes_requested: "Changes requested", approved: "Approved",
};

const timeAgo = (iso) => {
  if (!iso) return "";
  const then = new Date(iso + (String(iso).endsWith("Z") ? "" : "Z"));
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return then.toLocaleDateString([], { month: "short", day: "numeric" });
};

// Fold a background refetch into what is already on screen. Two things are kept
// from the local copy rather than overwritten:
//
//  - a title mid-edit, because the input owns it until it blurs;
//  - every whiteboard block, because it runs its own revision protocol and its
//    own refresh, and handing it a fresh content object mid-stroke re-imports
//    the canvas under the pen.
const mergeDoc = (prev, next, keepTitle) => {
  const boards = new Map((prev.blocks || [])
    .filter((b) => b.type === "whiteboard").map((b) => [b.id, b]));
  return {
    ...next,
    page: keepTitle && prev.page
      ? { ...next.page, title: prev.page.title }
      : next.page,
    blocks: (next.blocks || []).map((b) => boards.get(b.id) || b),
  };
};

/* ---------------------------------------------------------------- page tree */
function TreeRow({ page, activeId, onOpen, depth = 0, expanded, onToggle, onAddPage, onDelete }) {
  const isFolder = page.kind === "folder";
  return (
    <div className={`doc-tree-row ${page.id === activeId ? "on" : ""} ${depth ? "nested" : ""}`}>
      <button className={`doc-tree-item ${isFolder ? "folder" : ""}`}
        onClick={() => (isFolder ? onToggle(page.id) : onOpen(page.id))}>
        {isFolder && (
          <ChevronRight size={12} className={`doc-tree-caret ${expanded ? "open" : ""}`} />
        )}
        <PageIcon name={page.icon} fallback={isFolder ? (expanded ? FolderOpen : Folder) : FileText} />
        <span className="doc-tree-title">{page.title || "Untitled"}</span>
        {page.visibility === "internal" && (
          <span className="doc-tree-internal" title="Internal — not visible to the client">
            <EyeOff size={12} />
          </span>
        )}
      </button>
      <span className="doc-row-acts">
        {/* Pages are created here and only here, so the affordance sits on the folder
            that will hold the page rather than on a global button. */}
        {isFolder && (
          <button className="doc-row-act" title={`New page in ${page.title || "this folder"}`}
            onClick={(e) => { e.stopPropagation(); onAddPage(page); }}>
            <Plus size={13} />
          </button>
        )}
        <button className="doc-row-act danger" title={isFolder ? "Delete folder" : "Delete page"}
          onClick={(e) => { e.stopPropagation(); onDelete(page); }}>
          <Trash2 size={12} />
        </button>
      </span>
    </div>
  );
}

function PageTree({ tree, activeId, onOpen, onAddPage, onNewFolder, onDelete, loading, newRef }) {
  const [open, setOpen] = useState({});
  const toggle = (id) => setOpen((o) => ({ ...o, [id]: !(o[id] ?? true) }));
  const isOpen = (id) => open[id] ?? true;          // folders start expanded

  // Group by section, then nest children under their folder. One pass over a
  // flat list beats asking the server for a recursive shape.
  //
  // A page whose folder is missing from this list hangs at the root of its
  // section instead of nesting. That is not a rare repair: the client's list is
  // the shared pages, and the usual way to share one is to share the page inside
  // a folder we keep internal. Nesting it under a parent that was filtered out
  // would drop it from the sidebar entirely — the client would read "No folders
  // yet" while we are looking at a full tree of the same workspace. The rule to
  // hold is simply that the sidebar shows every page the reader may open.
  const bySection = useMemo(() => {
    const all = tree?.pages || [];
    const visible = new Set(all.map((p) => p.id));
    const children = {};
    const out = {};
    all.forEach((p) => {
      if (p.parent_id && visible.has(p.parent_id)) (children[p.parent_id] ||= []).push(p);
      else (out[p.section] ||= []).push(p);
    });
    return { roots: out, children };
  }, [tree]);

  return (
    <aside className="doc-tree">
      <div className="doc-tree-head">
        <b>Documents</b>
        <button ref={newRef} className="doc-tree-new" onClick={onNewFolder} title="New folder">
          <FolderPlus size={15} />
        </button>
      </div>
      <div className="doc-tree-body">
        {loading && [...Array(5)].map((_, i) => (
          <div className="doc-tree-sk" key={i}><Skeleton w={`${60 + (i % 3) * 12}%`} /></div>
        ))}
        {!loading && !(tree?.pages || []).length && (
          <p className="doc-tree-empty">No folders yet. Create one to hold your pages.</p>
        )}
        {!loading && (tree?.sections || []).map((section) => {
          const roots = bySection.roots[section] || [];
          if (!roots.length) return null;
          return (
            <div className="doc-tree-group" key={section}>
              <div className="doc-tree-label">{SECTION_LABELS[section] || section}</div>
              {roots.map((p) => {
                const kids = bySection.children[p.id] || [];
                return (
                  <div key={p.id}>
                    <TreeRow page={p} activeId={activeId} onOpen={onOpen} onAddPage={onAddPage}
                      onDelete={onDelete} expanded={isOpen(p.id)} onToggle={toggle} />
                    <AnimatePresence initial={false}>
                      {p.kind === "folder" && isOpen(p.id) && kids.length > 0 && (
                        <motion.div key={p.id} className="doc-tree-kids"
                          initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
                          {kids.map((c) => (
                            <TreeRow key={c.id} page={c} activeId={activeId} onOpen={onOpen}
                              onAddPage={onAddPage} onDelete={onDelete} depth={1}
                              expanded={false} onToggle={toggle} />
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>
                    {p.kind === "folder" && isOpen(p.id) && !kids.length && (
                      <button className="doc-tree-empty-folder" onClick={() => onAddPage(p)}>
                        <Plus size={11} /> Add a page
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

/* ---------------------------------------------------------------- slash menu */
function SlashMenu({ onPick, onClose }) {
  const [q, setQ] = useState("");
  const ref = useRef(null);
  useEffect(() => { ref.current?.focus(); }, []);
  const items = BLOCK_MENU.filter((b) =>
    !q || b.label.toLowerCase().includes(q.toLowerCase()) || b.type.includes(q.toLowerCase()));
  return (
    <>
      <div className="doc-slash-bg" onClick={onClose} />
      {/* grows out of the + it was opened from, rather than appearing from nowhere */}
      <motion.div className="doc-slash"
        initial={{ opacity: 0, scale: 0.9, y: -6 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}>
        <input ref={ref} value={q} placeholder="Search blocks…" onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "Enter" && items[0]) onPick(items[0]);
          }} />
        <div className="doc-slash-list">
          {items.map((b) => (
            <button key={b.type} className="doc-slash-item" onClick={() => onPick(b)}>
              <span className="doc-slash-ic"><b.icon size={14} /></span>
              <span><b>{b.label}</b><em>{b.hint}</em></span>
            </button>
          ))}
          {!items.length && <div className="doc-slash-none">No block matches “{q}”.</div>}
        </div>
      </motion.div>
    </>
  );
}

/* ---------------------------------------------------------------- comments */
function CommentThread({ root, replies, me, onReply, onResolve, onDelete }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const send = () => { if (text.trim()) { onReply(root.id, text.trim()); setText(""); setOpen(false); } };
  const line = (c, isReply) => (
    <div className={`doc-cmt ${isReply ? "reply" : ""}`} key={c.id}>
      <div className="doc-cmt-head">
        <b>{c.author || "Someone"}</b>
        <span className={`doc-cmt-side ${c.author_user_id === me ? "mine" : ""}`}>
          {c.author_user_id === me ? "You" : ""}
        </span>
        <em>{timeAgo(c.created_at)}</em>
        {c.author_user_id === me && (
          <button className="doc-cmt-x" title="Delete" onClick={() => onDelete(c.id)}>
            <Trash2 size={12} />
          </button>
        )}
      </div>
      <div className="doc-cmt-body">{c.body}</div>
    </div>
  );
  return (
    <div className="doc-thread">
      {line(root, false)}
      {replies.map((r) => line(r, true))}
      <div className="doc-thread-acts">
        {open ? (
          <div className="doc-cmt-in">
            <input value={text} autoFocus placeholder="Reply…" onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") send(); if (e.key === "Escape") setOpen(false); }} />
            <Button size="sm" onClick={send} disabled={!text.trim()}>Reply</Button>
          </div>
        ) : (
          <>
            <button className="doc-link" onClick={() => setOpen(true)}>Reply</button>
            <button className="doc-link" onClick={() => onResolve(root.id)}>Resolve</button>
          </>
        )}
      </div>
    </div>
  );
}

function BlockComments({ blockId, comments, me, onAdd, onReply, onResolve, onDelete }) {
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const mine = comments.filter((c) => c.block_id === blockId);
  const roots = mine.filter((c) => !c.parent_id);
  const open = roots.filter((c) => !c.resolved_at);
  const resolved = roots.filter((c) => c.resolved_at);
  const repliesOf = (id) => mine.filter((c) => c.parent_id === id);
  const send = () => { if (text.trim()) { onAdd(blockId, text.trim()); setText(""); setAdding(false); } };

  if (!open.length && !resolved.length && !adding) {
    return (
      <button className="doc-cmt-open" onClick={() => setAdding(true)}>
        <MessageSquare size={12} /> Comment on this block…
      </button>
    );
  }
  return (
    <div className="doc-comments">
      {open.map((r) => (
        <CommentThread key={r.id} root={r} replies={repliesOf(r.id)} me={me}
          onReply={onReply} onResolve={onResolve} onDelete={onDelete} />
      ))}
      {resolved.length > 0 && (
        <>
          <button className="doc-resolved-toggle" onClick={() => setShowResolved((v) => !v)}>
            <ChevronRight size={12} className={showResolved ? "open" : ""} />
            {resolved.length} resolved
          </button>
          {showResolved && resolved.map((r) => (
            <CommentThread key={r.id} root={r} replies={repliesOf(r.id)} me={me}
              onReply={onReply} onResolve={onResolve} onDelete={onDelete} />
          ))}
        </>
      )}
      {adding ? (
        <div className="doc-cmt-in">
          <input value={text} autoFocus placeholder="Comment on this block…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(); if (e.key === "Escape") setAdding(false); }} />
          <Button size="sm" onClick={send} disabled={!text.trim()}>Comment</Button>
        </div>
      ) : (
        <button className="doc-cmt-open" onClick={() => setAdding(true)}>
          <MessageSquare size={12} /> Add a comment…
        </button>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- one block */
function BlockRow({ block, readOnly, onState, comments, me, commentActions,
                   onDelete, onInsertAfter, onDragStart, onDragOver, onDrop, dragging }) {
  const [content, setContent] = useState(block.content || {});
  const [menu, setMenu] = useState(false);
  const server = useRef(block.content || {});

  // Server-side changes — a restore, a reorder, or the other side's edit
  // arriving on the live poll — win when this row is idle, and only then.
  // `server.current` is the copy we last agreed with the server, so content
  // differing from it means there are keystrokes here that have not landed yet;
  // adopting the incoming copy would delete the sentence being typed. Ours
  // stands until the debounce fires. Last write wins, as the page system says.
  useEffect(() => {
    const incoming = JSON.stringify(block.content || {});
    const agreed = JSON.stringify(server.current);
    if (incoming === agreed) return;                   // nothing new from the server
    if (JSON.stringify(content) !== agreed) return;    // unsaved edits here — keep them
    server.current = block.content || {};
    setContent(block.content || {});
  }, [block.content, content]);

  const toast = useToast();
  const save = useCallback(async (next) => {
    try {
      await api(`/api/workspace/blocks/${block.id}`, { method: "PATCH", body: { content: next } });
      server.current = next;
    } catch (e) {
      setContent(server.current);          // optimistic update rolled back
      toast(e.message || "Could not save this block", "bad");
      throw e;                             // let the hook show "Save failed"
    }
  }, [block.id, toast]);

  const managed = block.type === "whiteboard";
  const [state] = useAutoSave(content, save, { delay: 800, enabled: !readOnly && !managed });
  useEffect(() => { onState(block.id, state); }, [state, block.id, onState]);

  return (
    <div className={`doc-block ${managed ? "whiteboard" : ""} ${dragging ? "dragging" : ""}`}
      onDragOver={onDragOver} onDrop={onDrop}>
      {!readOnly && (
        <div className="doc-handle">
          <button className="doc-handle-btn" title="Add a block below" onClick={() => setMenu(true)}>
            <Plus size={14} />
          </button>
          <button className="doc-handle-btn grip" title="Drag to reorder" draggable
            onDragStart={onDragStart}><GripVertical size={14} /></button>
          <button className="doc-handle-btn" title="Delete block" onClick={onDelete}>
            <Trash2 size={13} />
          </button>
        </div>
      )}
      <div className="doc-block-body">
        <BlockBody block={{ ...block, content }} onChange={setContent} readOnly={readOnly}
          onManagedState={(next) => onState(block.id, next)} />
        <BlockComments blockId={block.id} comments={comments} me={me} {...commentActions} />
      </div>
      {menu && <SlashMenu onClose={() => setMenu(false)}
        onPick={(b) => { setMenu(false); onInsertAfter(b); }} />}
    </div>
  );
}

/* ---------------------------------------------------------------- new page */
// One modal for both kinds. A folder chooses its section; a page inherits the
// section from the folder it was opened in, so it only chooses a starting point.
function NewPageModal({ kind, parent, templates, onClose, onCreate, originRef }) {
  const isFolder = kind === "folder";
  const [title, setTitle] = useState("");
  const [icon, setIcon] = useState(isFolder ? "Folder" : "");
  const [section, setSection] = useState("strategy");
  const [templateId, setTemplateId] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      await onCreate({
        kind, icon,
        section: isFolder ? section : parent.section,
        title: title.trim() || (isFolder ? "New folder" : "Untitled"),
        template_id: !isFolder && templateId ? Number(templateId) : null,
        parent_id: isFolder ? null : parent.id,
      });
    } finally { setBusy(false); }
  };
  return (
    <Modal title={isFolder ? "New folder" : `New page in ${parent?.title || "folder"}`}
      onClose={onClose} originRef={originRef}>
      <div className="doc-form">
        <label>{isFolder ? "Folder name" : "Title"}
          <div className="doc-title-row">
            <IconPicker value={icon} onChange={setIcon} fallback={isFolder ? Folder : FileText} />
            <input value={title} autoFocus placeholder={isFolder ? "New folder" : "Untitled"}
              onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} />
          </div>
        </label>
        {isFolder ? (
          <label>Section
            <Select value={section} onChange={(e) => setSection(e.target.value)}>
              {Object.entries(SECTION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </label>
        ) : (
          <label>Start from
            <Select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
              <option value="">Blank page</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.block_count} blocks)</option>
              ))}
            </Select>
          </label>
        )}
        <div className="doc-form-acts">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={go} loading={busy}>{isFolder ? "Create folder" : "Create page"}</Button>
        </div>
      </div>
    </Modal>
  );
}

function SaveTemplateDrawer({ page, blocks, onClose, onSave }) {
  const [name, setName] = useState(`${page.title || "Untitled"} template`);
  const [keep, setKeep] = useState([]);
  const [busy, setBusy] = useState(false);
  const textual = blocks.filter((b) => ["text", "list", "checklist", "heading", "table"].includes(b.type));
  const toggle = (id) => setKeep((k) => (k.includes(id) ? k.filter((x) => x !== id) : [...k, id]));
  const label = (b) =>
    b.content?.text || b.content?.html?.replace(/<[^>]*>/g, "").slice(0, 60)
    || (b.content?.items || []).map((i) => i.text ?? i).join(", ").slice(0, 60)
    || (b.content?.columns || []).join(" · ").slice(0, 60) || "(empty)";
  return (
    <Drawer title="Save as template" onClose={onClose}>
      <p className="doc-drawer-hint">
        Every block keeps its type and structure. Tick the ones whose text should carry
        over — everything else starts empty in the new page.
      </p>
      <label className="doc-tpl-name">Template name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="doc-tpl-list">
        {textual.map((b) => (
          <label className="doc-tpl-row" key={b.id}>
            <input type="checkbox" checked={keep.includes(b.id)} onChange={() => toggle(b.id)} />
            <span className="doc-tpl-type">{b.type}</span>
            <span className="doc-tpl-text">{label(b)}</span>
          </label>
        ))}
        {!textual.length && <p className="doc-drawer-hint">This page has no text to keep.</p>}
      </div>
      <div className="doc-form-acts">
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!name.trim()}
          onClick={async () => { setBusy(true); try { await onSave(name.trim(), keep); } finally { setBusy(false); } }}>
          Save template
        </Button>
      </div>
    </Drawer>
  );
}

/* ---------------------------------------------------------------- the screen */
export default function WorkspaceDocs() {
  const { pageId } = useParams();
  const nav = useNavigate();
  const loc = useLocation();
  const { me, wsParam, setWorkspaceId } = useAuth();
  const toast = useToast();
  const isClient = me?.role === "client";
  // This screen is mounted under three bases — Client Space, the client's own
  // shell, and CRM's long-standing /workspace/docs. Read it off the URL so an
  // in-page link never drops the reader into a different module's copy.
  const base = docsBaseFrom(loc.pathname, isClient);

  const [tree, setTree] = useState(null);
  const [treeLoading, setTreeLoading] = useState(true);
  const [doc, setDoc] = useState(null);
  const [docLoading, setDocLoading] = useState(false);
  const [comments, setComments] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [saveStates, setSaveStates] = useState({});
  // { kind: "folder" } or { kind: "page", parent, originRef } — a page is always
  // created from a specific folder's + button, which is also what it flies from.
  const [creating, setCreating] = useState(null);
  const newRef = useRef(null);
  const titleRef = useRef(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState([]);
  const [tplOpen, setTplOpen] = useState(false);
  const [drag, setDrag] = useState(null);

  // `quiet` marks a refetch nobody asked for: the live poll noticed the other
  // side changed something. It skips the skeleton and the error toast — a screen
  // that already has content must not flash back to placeholders, and a poll
  // that loses a race is not news the reader needs.
  const loadTree = useCallback(async (quiet = false) => {
    if (!quiet) setTreeLoading(true);
    try { setTree(await api("/api/workspace/pages/tree", { params: { workspace_id: wsParam } })); }
    catch (e) { if (!quiet) toast(e.message, "bad"); }
    finally { if (!quiet) setTreeLoading(false); }
  }, [wsParam, toast]);

  const loadDoc = useCallback(async (id, quiet = false) => {
    if (!id) { setDoc(null); return; }
    if (!quiet) setDocLoading(true);
    try {
      const [d, c] = await Promise.all([
        api(`/api/workspace/pages/${id}`),
        api("/api/workspace/comments", { params: { page_id: id } }),
      ]);
      const keepTitle = quiet && document.activeElement === titleRef.current;
      setDoc((prev) => (quiet && prev ? mergeDoc(prev, d, keepTitle) : d));
      setComments(c);
    } catch (e) {
      if (quiet) return;
      toast(e.message, "bad");
      setDoc(null);
    } finally { if (!quiet) setDocLoading(false); }
  }, [toast]);

  // Documents belong to one client. On "All workspaces" the tree would merge
  // every client's folders into one sidebar that is nobody's, and the server
  // refuses to create a page without being told which workspace it is for. Ask
  // which client, the way the Client Space overview already does.
  const needsWorkspace = !wsParam && (me?.workspaces?.length || 0) > 1;

  useEffect(() => { if (!needsWorkspace) loadTree(); }, [loadTree, needsWorkspace]);
  useEffect(() => { loadDoc(pageId); }, [pageId, loadDoc]);
  useEffect(() => {
    if (isClient) return;                       // clients cannot save templates
    api("/api/workspace/page-templates").then(setTemplates).catch(() => setTemplates([]));
  }, [isClient]);

  /* ------------------------------------------------------------------ live */
  // The operator and the client read the same documents from two addresses. Both
  // poll one cheap stamp, and whichever half of the screen moved is the half
  // that refetches. That is what makes a share, a rename or an edit on one side
  // appear on the other without anyone reloading.
  //
  // The stamps are opaque and compared for equality only — see /api/workspace/pulse.
  const seen = useRef({ tree: null, page: null });
  useEffect(() => { seen.current = { tree: null, page: null }; }, [wsParam, pageId]);
  useEffect(() => {
    if (needsWorkspace) return undefined;
    let stopped = false;
    const check = async () => {
      // A hidden tab is looking at nothing; it catches up on the wake below.
      if (stopped || document.hidden) return;
      let now;
      try {
        now = await api("/api/workspace/pulse",
          { params: { workspace_id: wsParam, page_id: pageId } });
      } catch { return; }                       // a blip on a poll is not news
      if (stopped) return;
      const last = seen.current;
      seen.current = now;
      // A null stamp is the first tick, which has nothing to compare against and
      // only records. Anything that changed between the initial load and that
      // tick is caught by the tick after it.
      if (last.tree !== null && now.tree !== last.tree) loadTree(true);
      if (last.page !== null && now.page !== last.page) {
        if (now.page === null) {
          // Archived, or put out of reach, from under us. Leaving a document on
          // screen that no longer exists for this reader would be the lie.
          setDoc(null);
          toast("This page is no longer available", "bad");
          nav(base);
        } else loadDoc(pageId, true);
      }
    };
    check();
    const timer = setInterval(check, 4000);
    // Returning to the tab is both when staleness shows most and when the poll
    // has been asleep longest, so it checks then rather than at the next tick.
    const wake = () => { if (!document.hidden) check(); };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("focus", wake);
    return () => {
      stopped = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("focus", wake);
    };
  }, [wsParam, pageId, needsWorkspace, loadTree, loadDoc, toast, nav, base]);

  const page = doc?.page;
  const blocks = doc?.blocks || [];
  const readOnly = false;                        // both sides edit; the server gates access
  const docState = Object.values(saveStates).includes("saving") ? "saving"
    : Object.values(saveStates).includes("error") ? "error"
    : Object.values(saveStates).includes("saved") ? "saved" : "idle";

  const onState = useCallback((id, state) => {
    setSaveStates((prev) => (prev[id] === state ? prev : { ...prev, [id]: state }));
  }, []);

  const createPage = async (body) => {
    try {
      const p = await api("/api/workspace/pages", {
        method: "POST", body: { ...body, workspace_id: wsParam ?? null },
      });
      setCreating(null);
      await loadTree();
      // A folder has nothing to open — stay where you are and let the tree show it.
      if (p.kind !== "folder") nav(`${base}/${p.id}`);
    } catch (e) { toast(e.message, "bad"); }
  };

  // Soft delete: the server archives rather than destroys, so blocks, comments and
  // versions survive. The dialog says what a folder takes with it, because the
  // count is the part someone would regret not knowing.
  const deletePage = async (p) => {
    const isFolder = p.kind === "folder";
    const kids = isFolder
      ? (tree?.pages || []).filter((x) => x.parent_id === p.id).length : 0;
    const message = isFolder
      ? (kids
        ? `“${p.title || "Untitled"}” holds ${kids} page${kids === 1 ? "" : "s"}. `
          + `Deleting the folder removes ${kids === 1 ? "it" : "them"} from the sidebar too.\n\n`
          + "Nothing is destroyed — pages, comments and version history are kept and can be restored."
        : `“${p.title || "Untitled"}” is empty.\n\nNothing is destroyed — it can be restored.`)
      : `“${p.title || "Untitled"}” will be removed from the sidebar.\n\n`
        + "Nothing is destroyed — its blocks, comments and version history are kept and can be restored.";
    if (!await confirmDialog(message, {
      title: isFolder ? "Delete this folder?" : "Delete this page?",
      confirmText: "Delete", danger: true,
    })) return;
    try {
      await api(`/api/workspace/pages/${p.id}/archive`, { method: "POST" });
      await loadTree();
      // Leaving the open page on screen after deleting it would be a lie.
      const removed = String(p.id) === String(pageId)
        || (isFolder && (tree?.pages || []).some(
          (x) => x.parent_id === p.id && String(x.id) === String(pageId)));
      if (removed) nav(base);
      toast(isFolder ? "Folder deleted" : "Page deleted", "ok");
    } catch (e) { toast(e.message, "bad"); }
  };

  const renameTitle = async (title) => {
    setDoc((d) => ({ ...d, page: { ...d.page, title } }));
    try {
      await api(`/api/workspace/pages/${page.id}`, { method: "PATCH", body: { title } });
      loadTree();
    } catch (e) { toast(e.message, "bad"); }
  };

  const insertBlock = async (spec, afterPosition) => {
    try {
      await api(`/api/workspace/pages/${page.id}/blocks`, {
        method: "POST", body: { type: spec.type, content: spec.blank, position: afterPosition + 1 },
      });
      loadDoc(page.id);
    } catch (e) { toast(e.message, "bad"); }
  };

  const deleteBlock = async (block) => {
    if (!await confirmDialog("Its comments stay on the page.",
      { title: "Delete this block?", confirmText: "Delete", danger: true })) return;
    const before = blocks;
    setDoc((d) => ({ ...d, blocks: d.blocks.filter((b) => b.id !== block.id) }));
    try { await api(`/api/workspace/blocks/${block.id}`, { method: "DELETE" }); }
    catch (e) { setDoc((d) => ({ ...d, blocks: before })); toast(e.message, "bad"); }
  };

  const dropOn = async (targetId) => {
    if (!drag || drag === targetId) return setDrag(null);
    const ids = blocks.map((b) => b.id);
    const from = ids.indexOf(drag);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return setDrag(null);
    const next = [...ids];
    next.splice(to, 0, next.splice(from, 1)[0]);
    const before = blocks;
    setDoc((d) => ({ ...d, blocks: next.map((id) => before.find((b) => b.id === id)) }));
    setDrag(null);
    try {
      await api(`/api/workspace/pages/${page.id}/blocks/reorder`, {
        method: "POST", body: { ordered_ids: next },
      });
    } catch (e) { setDoc((d) => ({ ...d, blocks: before })); toast(e.message, "bad"); }
  };

  const share = async () => {
    try {
      const p = await api(`/api/workspace/pages/${page.id}/share`, { method: "POST" });
      setDoc((d) => ({ ...d, page: { ...d.page, ...p } }));
      loadTree();
      toast("Shared with the client", "ok");
    } catch (e) { toast(e.message, "bad"); }
  };

  const openHistory = async () => {
    setHistoryOpen(true);
    try { setVersions(await api(`/api/workspace/pages/${page.id}/versions`)); }
    catch (e) { toast(e.message, "bad"); }
  };

  const saveVersion = async () => {
    try {
      await api(`/api/workspace/pages/${page.id}/versions`, { method: "POST", body: { note: "" } });
      setVersions(await api(`/api/workspace/pages/${page.id}/versions`));
      toast("Version saved", "ok");
    } catch (e) { toast(e.message, "bad"); }
  };

  const restore = async (v) => {
    if (!await confirmDialog("The current state is snapshotted first, so this is undoable.",
      { title: `Restore v${v.version}?`, confirmText: "Restore" })) return;
    try {
      await api(`/api/workspace/pages/${page.id}/restore/${v.id}`, { method: "POST" });
      setHistoryOpen(false);
      loadDoc(page.id);
      toast("Restored", "ok");
    } catch (e) { toast(e.message, "bad"); }
  };

  const commentActions = useMemo(() => ({
    onAdd: async (blockId, body) => {
      try {
        const c = await api("/api/workspace/comments", {
          method: "POST", body: { page_id: Number(pageId), block_id: blockId, body },
        });
        setComments((prev) => [...prev, c]);
      } catch (e) { toast(e.message, "bad"); }
    },
    onReply: async (parentId, body) => {
      const parent = comments.find((c) => c.id === parentId);
      try {
        const c = await api("/api/workspace/comments", {
          method: "POST",
          body: { page_id: Number(pageId), block_id: parent?.block_id ?? null, parent_id: parentId, body },
        });
        setComments((prev) => [...prev, c]);
      } catch (e) { toast(e.message, "bad"); }
    },
    onResolve: async (id) => {
      try {
        const c = await api(`/api/workspace/comments/${id}/resolve`, { method: "POST" });
        setComments((prev) => prev.map((x) => (x.id === id ? { ...x, ...c } : x)));
      } catch (e) { toast(e.message, "bad"); }
    },
    onDelete: async (id) => {
      try {
        await api(`/api/workspace/comments/${id}`, { method: "DELETE" });
        setComments((prev) => prev.filter((x) => x.id !== id && x.parent_id !== id));
      } catch (e) { toast(e.message, "bad"); }
    },
  }), [pageId, comments, toast]);

  const openCount = comments.filter((c) => !c.resolved_at && !c.parent_id).length;

  if (needsWorkspace) {
    return (
      <div className="doc-screen">
        <section className="doc-main">
          <EmptyState icon={FileText} title="Pick a client"
            hint="Documents belong to one client workspace — the same set that client reads at their own address. Choose whose documents to open."
            action={(
              <Select value="" onChange={(e) => setWorkspaceId(e.target.value)}>
                <option value="">Choose a workspace</option>
                {(me?.workspaces || []).map((w) => (
                  <option key={w.id} value={w.id}>{w.name}</option>
                ))}
              </Select>
            )} />
        </section>
      </div>
    );
  }

  return (
    <div className="doc-screen">
      <PageTree tree={tree} activeId={Number(pageId)} loading={treeLoading} newRef={newRef}
        onOpen={(id) => nav(`${base}/${id}`)}
        onAddPage={(parent) => setCreating({ kind: "page", parent })}
        onNewFolder={() => setCreating({ kind: "folder" })}
        onDelete={deletePage} />

      <section className="doc-main">
        {!pageId && !docLoading && (
          <EmptyState icon={FileText} title="No page open"
            hint="Pages live inside folders. Create a folder on the left, then add pages to it."
            action={<Button icon={FolderPlus} onClick={() => setCreating({ kind: "folder" })}>
              New folder</Button>} />
        )}

        {docLoading && (
          <div className="doc-body">
            <Skeleton w="45%" h={26} />
            <Skeleton w="100%" h={14} style={{ marginTop: 22 }} />
            <Skeleton w="88%" h={14} style={{ marginTop: 10 }} />
            <Skeleton w="93%" h={14} style={{ marginTop: 10 }} />
          </div>
        )}

        {page && !docLoading && (
          <>
            <div className="doc-toolbar">
              <StatusPill tone={STATUS_TONE[page.status] || "gray"}>
                {STATUS_LABEL[page.status] || page.status}
              </StatusPill>
              {page.visibility === "internal" && (
                <span className="doc-internal-tag"><EyeOff size={12} /> Internal</span>
              )}
              <span className="doc-meta">
                v{page.version_no || 0}
                {page.edited_by ? ` · edited by ${page.edited_by}` : ""}
                {page.updated_at ? ` ${timeAgo(page.updated_at)}` : ""}
              </span>
              <span className="doc-toolbar-sp" />
              <SaveIndicator state={docState} />
              <button className="doc-tool" onClick={openHistory}><Clock size={14} /> History</button>
              <button className="doc-tool" onClick={() => document
                .querySelector(".doc-cmt-open")?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                <MessageSquare size={14} /> {openCount}
              </button>
              {!isClient && (
                <button className="doc-tool" onClick={() => setTplOpen(true)}>Save as template</button>
              )}
              <span title={isClient ? "Only the RevCadence team can share a page" : ""}>
                <Button size="sm" icon={Share2} onClick={share}
                  disabled={isClient || page.visibility === "shared"}>
                  {page.visibility === "shared" ? "Shared" : "Share"}
                </Button>
              </span>
            </div>

            <div className={`doc-body ${blocks.some((block) => block.type === "whiteboard") ? "has-whiteboard" : ""}`}>
              <input ref={titleRef} className="doc-title" value={page.title || ""} placeholder="Untitled"
                onChange={(e) => setDoc((d) => ({ ...d, page: { ...d.page, title: e.target.value } }))}
                onBlur={(e) => renameTitle(e.target.value)} />

              {blocks.map((b) => (
                <BlockRow key={b.id} block={b} readOnly={readOnly} onState={onState}
                  comments={comments} me={me?.user?.id} commentActions={commentActions}
                  dragging={drag === b.id}
                  onDragStart={() => setDrag(b.id)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => dropOn(b.id)}
                  onDelete={() => deleteBlock(b)}
                  onInsertAfter={(spec) => insertBlock(spec, b.position)} />
              ))}

              <button className="doc-add-end" onClick={() => insertBlock(
                BLOCK_MENU[0], blocks.length ? blocks[blocks.length - 1].position : 0)}>
                <Plus size={14} /> Add a block
              </button>
            </div>
          </>
        )}
      </section>

      <AnimatePresence>
        {creating && (
          <NewPageModal key={creating.kind} kind={creating.kind} parent={creating.parent}
            templates={templates} originRef={newRef}
            onClose={() => setCreating(null)} onCreate={createPage} />
        )}
      </AnimatePresence>

      <AnimatePresence>
      {historyOpen && page && (
        <Drawer key="history" title="Version history" onClose={() => setHistoryOpen(false)}>
          <p className="doc-drawer-hint">
            Last write wins while you edit. A version is a point you can come back to.
          </p>
          <Button size="sm" icon={Check} onClick={saveVersion}>Save a version now</Button>
          <div style={{ marginTop: 16 }}>
            <VersionList versions={versions.map((v) => ({
              id: v.id, version: v.version, label: v.note || `Version ${v.version}`, at: v.at,
            }))} onRestore={(v) => restore(versions.find((x) => x.id === v.id))} />
          </div>
        </Drawer>
      )}
      </AnimatePresence>

      <AnimatePresence>
      <AnimatePresence>
      {tplOpen && page && (
        <SaveTemplateDrawer key="tpl" page={page} blocks={blocks} onClose={() => setTplOpen(false)}
          onSave={async (name, keep) => {
            try {
              await api("/api/workspace/page-templates", {
                method: "POST",
                body: { from_page_id: page.id, name, keep_text_block_ids: keep },
              });
              setTemplates(await api("/api/workspace/page-templates"));
              setTplOpen(false);
              toast("Template saved", "ok");
            } catch (e) { toast(e.message, "bad"); }
          }} />
      )}
      </AnimatePresence>
      </AnimatePresence>
    </div>
  );
}
