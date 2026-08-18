// The canvas.
//
// tldraw does the drawing. That is a deliberate choice rather than a shortcut: a
// whiteboard is not a small problem — arrows that stay bound to the shapes they
// connect while you drag them, groups, frames, snapping, undo, text editing,
// export. Owning all of that would mean maintaining it forever, and the version
// we could maintain would be worse than the one we get for free.
//
// What we own is the part that is ours:
//
//   · persistence into the block, keeping the optimistic revision so two people
//     on one board cannot silently erase each other,
//   · images, which upload into the workspace's private store rather than being
//     inlined into the row as base64,
//   · note types — the tag that lets a card on the board graduate into the ICP
//     definition or the proof library. That lives in tldraw's `meta`, the field
//     it reserves for exactly this.
//
// We store tldraw's *document* snapshot, never its editor snapshot. Session
// state holds the camera and the selection, which belong to a person, not to the
// board: persisting them would mean one person scrolling moved everyone's view.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Sparkles } from "lucide-react";
import {
  ArrowShapeKindStyle, DefaultColorStyle, DefaultFillStyle, DefaultFontStyle,
  DefaultMainMenu, DefaultMainMenuContent, DefaultSizeStyle, Tldraw, TldrawUiMenuGroup,
  TldrawUiMenuItem, createShapeId, toRichText, useValue,
} from "tldraw";
import "tldraw/tldraw.css";
import { API_BASE, api, getToken } from "../api";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import { Button, useToast } from "../components";
import { docsBaseFrom } from "../clientspace/nav";

// A card's tag decides its colour, so the board is legible before anyone reads
// it: the shape of the thinking shows at a zoom where the words do not.
const NOTE_TYPES = [
  ["segment", "Segment", "blue"],
  ["trigger", "Trigger", "violet"],
  ["proof", "Proof", "green"],
  ["reject", "Reject", "red"],
  ["angle", "Angle", "orange"],
  ["question", "Question", "grey"],
];
const NOTE_COLOR = Object.fromEntries(NOTE_TYPES.map(([value, , color]) => [value, color]));
const NOTE_LABEL = Object.fromEntries(NOTE_TYPES.map(([value, label]) => [value, label]));
const PROMOTABLE = { segment: "segment", proof: "case study", reject: "exclusion" };

// Shapes a note type can be pinned to. A tag on an arrow or a scribble would
// mean nothing to the generator that reads the board later.
const TAGGABLE = new Set(["geo", "note", "text"]);

const emptyContent = () => ({ kind: "tldraw", snapshot: null });
const snapshotOf = (content) =>
  (content && content.kind === "tldraw" && content.snapshot) || null;

/** Legacy boards were `{shapes, connectors}` in a private format. Rather than
 *  teach the server two shapes forever, the first person to open an old board
 *  converts it through the editor itself — which is the only thing that can
 *  produce records the current tldraw schema actually accepts. */
function importLegacy(editor, content) {
  const shapes = Array.isArray(content?.shapes) ? content.shapes : [];
  if (!shapes.length) return false;
  const idFor = new Map();
  editor.createShapes(shapes.map((shape) => {
    const id = createShapeId();
    idFor.set(shape.id, id);
    const noteType = shape.note_type && NOTE_COLOR[shape.note_type] ? shape.note_type : null;
    return {
      id, type: "geo", x: Number(shape.x) || 0, y: Number(shape.y) || 0,
      meta: noteType ? { note_type: noteType } : {},
      props: {
        geo: shape.kind === "frame" ? "rectangle" : "rectangle",
        w: Math.max(96, Number(shape.w) || 240), h: Math.max(48, Number(shape.h) || 144),
        fill: "solid", color: noteType ? NOTE_COLOR[noteType] : "grey",
        dash: "solid", size: "s", font: "sans",
        richText: toRichText(String(shape.text || "")),
      },
    };
  }));
  const connectors = Array.isArray(content?.connectors) ? content.connectors : [];
  connectors.forEach((link) => {
    const from = idFor.get(link.from); const to = idFor.get(link.to);
    if (!from || !to) return;
    const a = editor.getShape(from); const b = editor.getShape(to);
    if (!a || !b) return;
    const arrow = createShapeId();
    editor.createShapes([{ id: arrow, type: "arrow", x: 0, y: 0,
      props: { color: "grey", size: "s", richText: toRichText(String(link.label || "")) } }]);
    editor.createBindings([
      { type: "arrow", fromId: arrow, toId: from, props: { terminal: "start", isPrecise: false, normalizedAnchor: { x: 0.5, y: 0.5 }, isExact: false } },
      { type: "arrow", fromId: arrow, toId: to, props: { terminal: "end", isPrecise: false, normalizedAnchor: { x: 0.5, y: 0.5 }, isExact: false } },
    ]);
  });
  return true;
}

/** Images live in the workspace's private store, never inside the board row.
 *  Reading one needs our bearer token, which an `<img src>` will not send — so
 *  resolve fetches it and hands tldraw an object URL instead. */
function assetStore(blockId, toast) {
  const cache = new Map();
  return {
    async upload(_asset, file) {
      const data = new FormData();
      data.append("file", file);
      const response = await fetch(
        `${API_BASE}/api/workspace/blocks/${blockId}/whiteboard/images`,
        { method: "POST", body: data, credentials: "include",
          headers: { Authorization: `Bearer ${getToken()}` } });
      if (!response.ok) {
        let detail = "Could not add that image";
        try { detail = (await response.json()).detail || detail; } catch { /* empty */ }
        const message = typeof detail === "string" ? detail : JSON.stringify(detail);
        toast(message, "bad");
        throw new Error(message);
      }
      return { src: (await response.json()).src };
    },
    async resolve(asset) {
      const src = asset?.props?.src;
      if (!src) return null;
      if (cache.has(src)) return cache.get(src);
      const pending = fetch(`${API_BASE}${src}`, {
        credentials: "include", headers: { Authorization: `Bearer ${getToken()}` },
      }).then((response) => {
        if (!response.ok) throw new Error("Image unavailable");
        return response.blob();
      }).then((blob) => URL.createObjectURL(blob)).catch(() => null);
      cache.set(src, pending);
      return pending;
    },
  };
}

// Shapes worth growing a diagram out of. An arrow off an arrow, or off a pen
// scribble, is not a thought anyone is trying to have.
const CONNECTABLE = new Set(["geo", "note"]);
const DIRECTIONS = [
  ["up", 0, -1, "M8 3.5 L8 12.5 M4.5 7 L8 3.5 L11.5 7"],
  ["right", 1, 0, "M3.5 8 L12.5 8 M9 4.5 L12.5 8 L9 11.5"],
  ["down", 0, 1, "M8 3.5 L8 12.5 M4.5 9 L8 12.5 L11.5 9"],
  ["left", -1, 0, "M12.5 8 L3.5 8 M7 4.5 L3.5 8 L7 11.5"],
];
const CONNECT_GAP = 96;

/** Grow the diagram from the card itself.
 *
 *  A whiteboard is mostly one thought leading to another, and making that cost
 *  "pick the arrow tool, drag from an edge, pick the box tool, draw a box, type"
 *  is what stops people from mapping anything. One click here places the next
 *  card, binds an arrow to both, and drops the cursor in it ready to type — in
 *  whichever of the four directions the thought went.
 *
 *  The buttons live in screen space, not on the canvas, so they keep their size
 *  and hit area at any zoom rather than shrinking into nothing at 20%.
 */
function QuickConnect({ editor, readOnly }) {
  const box = useValue("wb-connect", () => {
    if (readOnly || editor.getEditingShapeId()) return null;
    const selection = editor.getSelectedShapes();
    if (selection.length !== 1 || !CONNECTABLE.has(selection[0].type)) return null;
    const bounds = editor.getShapePageBounds(selection[0].id);
    if (!bounds) return null;
    const topLeft = editor.pageToViewport({ x: bounds.minX, y: bounds.minY });
    const bottomRight = editor.pageToViewport({ x: bounds.maxX, y: bounds.maxY });
    return { id: selection[0].id, left: topLeft.x, top: topLeft.y,
             right: bottomRight.x, bottom: bottomRight.y };
  }, [editor, readOnly]);
  if (!box) return null;

  const connect = (dx, dy) => {
    const source = editor.getShape(box.id);
    const bounds = editor.getShapePageBounds(box.id);
    if (!source || !bounds) return;

    const next = createShapeId();
    // The new card inherits how the old one looks, so a chain reads as one
    // diagram instead of a pile of defaults.
    const { richText, text, url, ...look } = source.props || {};
    editor.createShapes([{
      id: next, type: source.type,
      x: bounds.minX + dx * (bounds.width + CONNECT_GAP),
      y: bounds.minY + dy * (bounds.height + CONNECT_GAP),
      meta: source.meta?.note_type ? { note_type: source.meta.note_type } : {},
      props: { ...look, w: bounds.width, h: bounds.height },
    }]);

    const arrow = createShapeId();
    // `elbow` routes in right angles and re-picks which side of each card it
    // leaves and lands on as they move — drag a card from the left of another to
    // its right and the arrow swaps sides instead of cutting diagonally across
    // the board.
    editor.createShapes([{ id: arrow, type: "arrow",
      x: bounds.center.x, y: bounds.center.y,
      props: { kind: "elbow", color: source.props?.color || "grey",
               size: source.props?.size || "s" } }]);
    // Bound at both ends, so the arrow follows the cards when either is moved
    // rather than being a line that quietly stops pointing at anything.
    // `isPrecise: false` is what leaves tldraw free to choose the edge; pinning
    // it to an exact point is what would nail the arrow to one side forever.
    const anchor = { normalizedAnchor: { x: 0.5, y: 0.5 }, isExact: false, isPrecise: false };
    editor.createBindings([
      { type: "arrow", fromId: arrow, toId: box.id, props: { terminal: "start", ...anchor } },
      { type: "arrow", fromId: arrow, toId: next, props: { terminal: "end", ...anchor } },
    ]);
    // Deliberately not sent to the back: an arrow buried under the cards is one
    // you cannot click, and you need to be able to select an arrow on its own to
    // delete just the arrow.
    editor.select(next);
    editor.setEditingShape(next);
  };

  const spot = (dx, dy) => ({
    up: { left: (box.left + box.right) / 2, top: box.top - 22 },
    down: { left: (box.left + box.right) / 2, top: box.bottom + 22 },
    left: { left: box.left - 22, top: (box.top + box.bottom) / 2 },
    right: { left: box.right + 22, top: (box.top + box.bottom) / 2 },
  })[dx === 0 ? (dy < 0 ? "up" : "down") : (dx < 0 ? "left" : "right")];

  return (
    <>
      {DIRECTIONS.map(([name, dx, dy, path]) => {
        const at = spot(dx, dy);
        return (
          <button key={name} type="button" className="wb-connect" title={`Add a connected card ${name}`}
            style={{ left: at.left, top: at.top }}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={() => connect(dx, dy)}>
            <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
              <path d={path} fill="none" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        );
      })}
    </>
  );
}

/** The one piece of board UI that is ours: what a selected card *means*.
 *  Tagging recolours the card, and a tagged card can graduate into the client
 *  brain — which is the whole reason a strategy board lives in this product
 *  rather than in a drawing tool someone screenshots into it. */
function NotePanel({ editor, readOnly, onPromote, promoting }) {
  const selected = useValue("wb-selection", () => {
    const shapes = editor.getSelectedShapes();
    return shapes.length === 1 && TAGGABLE.has(shapes[0].type) ? shapes[0] : null;
  }, [editor]);
  if (!selected) return null;

  const noteType = selected.meta?.note_type || "";
  const promotion = selected.meta?.promotion || null;
  const tag = (value) => {
    editor.updateShapes([{ id: selected.id, type: selected.type,
      meta: { ...selected.meta, note_type: value } }]);
    // The colour is the tag made visible, so they are set together or the board
    // starts lying about what is on it.
    if (NOTE_COLOR[value] && "color" in (selected.props || {})) {
      editor.updateShapes([{ id: selected.id, type: selected.type,
        props: { color: NOTE_COLOR[value], ...(selected.type === "geo" ? { fill: "solid" } : {}) } }]);
    }
  };

  return (
    <div className="wb-note-panel">
      <span className="wb-note-panel-label">Mark this as</span>
      <div className="wb-note-chips">
        {NOTE_TYPES.map(([value, label]) => (
          <button key={value} type="button" disabled={readOnly}
            className={`wb-chip tone-${value}${noteType === value ? " on" : ""}`}
            onClick={() => tag(noteType === value ? "" : value)}>{label}</button>
        ))}
      </div>
      {PROMOTABLE[noteType] && (
        <button type="button" className="wb-promote-btn"
          disabled={readOnly || !!promotion || promoting}
          onClick={() => onPromote(selected)}>
          <Sparkles size={13} />
          {promotion ? `In the ${PROMOTABLE[noteType]} library` : `Add to ${PROMOTABLE[noteType]}`}
        </button>
      )}
    </div>
  );
}

export default function WhiteboardBlock({ block, readOnly = false, onState, fill = false }) {
  const toast = useToast();
  const nav = useNavigate();
  const { pathname } = useLocation();
  const { me } = useAuth();
  const { isDark } = useTheme();
  const [editor, setEditor] = useState(null);
  const [saveState, setSaveState] = useState("idle");
  const [conflict, setConflict] = useState(null);
  const [busy, setBusy] = useState("");
  const [drift, setDrift] = useState(null);

  const revisionRef = useRef(block.revision || 1);
  const savedRef = useRef(JSON.stringify(snapshotOf(block.content)));
  const saving = useRef(null);
  const timer = useRef(null);
  const conflicted = useRef(false);
  const hostRef = useRef(null);

  useEffect(() => { onState?.(saveState); }, [saveState, onState]);
  useEffect(() => { conflicted.current = !!conflict; }, [conflict]);

  const assets = useMemo(() => assetStore(block.id, toast), [block.id, toast]);

  const write = useCallback(async (snapshot, { force = false, baseRevision } = {}) => {
    const body = { content: { kind: "tldraw", snapshot },
      base_revision: baseRevision ?? revisionRef.current, force };
    const request = api(`/api/workspace/blocks/${block.id}`, { method: "PATCH", body });
    saving.current = request;
    try {
      const saved = await request;
      revisionRef.current = saved.revision;
      savedRef.current = JSON.stringify(snapshotOf(saved.content));
      setConflict(null);
      setSaveState("saved");
      window.setTimeout(() => setSaveState((s) => s === "saved" ? "idle" : s), 1600);
      return saved;
    } catch (error) {
      if (error.status === 409 && error.detail?.current) {
        setConflict({ current: error.detail.current, local: snapshot });
      } else {
        toast(error.message || "Could not save the board", "bad");
      }
      setSaveState("error");
      throw error;
    } finally {
      if (saving.current === request) saving.current = null;
    }
  }, [block.id, toast]);

  const persist = useCallback(async (instance) => {
    if (readOnly || conflicted.current) return;
    if (saving.current) { try { await saving.current; } catch { return; } }
    const snapshot = instance.store.getStoreSnapshot();
    const encoded = JSON.stringify(snapshot);
    if (encoded === savedRef.current) { setSaveState("idle"); return; }
    await write(snapshot).catch(() => {});
  }, [readOnly, write]);

  const onMount = useCallback((instance) => {
    setEditor(instance);
    // A handle on the live editor. Not dev-gated on purpose: pointer-offset and
    // selection faults show up in the built app as often as in dev, and reading
    // what the editor thinks its bounds are beats inferring it from symptoms.
    window.__wbEditor = instance;
    instance.updateInstanceState({ isGridMode: true, isReadonly: readOnly });

    const snapshot = snapshotOf(block.content);
    if (snapshot) {
      try { instance.store.loadStoreSnapshot(snapshot); }
      catch { toast("This board was saved by a newer version and could not be opened", "bad"); }
    } else if (importLegacy(instance, block.content)) {
      // Converted in the client, so save it back in the new shape immediately —
      // otherwise the next reader converts it again from the same old row.
      instance.zoomToFit();
      window.setTimeout(() => persist(instance), 0);
    }

    // New shapes come out solid and readable rather than transparent outlines,
    // and arrows drawn by hand elbow around the board like the generated ones do.
    instance.setStyleForNextShapes(DefaultFillStyle, "solid");
    instance.setStyleForNextShapes(DefaultColorStyle, "blue");
    instance.setStyleForNextShapes(DefaultFontStyle, "sans");
    instance.setStyleForNextShapes(DefaultSizeStyle, "s");
    instance.setStyleForNextShapes(ArrowShapeKindStyle, "elbow");
    if (instance.getCurrentPageShapeIds().size) instance.zoomToFit();

    if (readOnly) return;
    // `document` scope only: session records are camera and selection, and
    // saving on those would write a row every time somebody scrolled.
    instance.store.listen(() => {
      if (conflicted.current) return;
      setSaveState("saving");
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => persist(instance), 700);
    }, { source: "user", scope: "document" });
  }, [block.content, persist, readOnly, toast]);

  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => { editor?.setColorMode?.(isDark ? "dark" : "light"); }, [editor, isDark]);

  // Keep tldraw's idea of where it is on screen honest.
  //
  // Every pointer position is computed against a cached measurement of the
  // canvas container. The board mounts inside a container that is still being
  // laid out — it gets pinned to the viewport and offset by the shell's rail a
  // moment later — so tldraw's first measurement is of a box that has since
  // moved, and from then on every click lands off by that shift.
  //
  // A ResizeObserver alone is not enough: it fires on size changes, and a
  // container that *moves* without resizing leaves the stale rect in place. So
  // re-measure once after layout settles, and again on anything that can shift
  // the container underneath it.
  //
  // Note what this does *not* fix, because it was mistaken for it for a long
  // time: a stale rect offsets every click by the same amount everywhere. An
  // offset that grows as you move away from the top-left corner is a scale
  // fault, not a position one, and no amount of re-measuring will touch it —
  // see the `zoom` reset on .wb-canvas-host in styles.css. The audit below is
  // what tells the two apart.
  useEffect(() => {
    const host = hostRef.current;
    if (!editor || !host) return undefined;
    // Pass the container explicitly. `updateViewportScreenBounds` takes the
    // element (or a Box) to measure — called with nothing it throws on the
    // missing argument, which is a re-measure that silently never happens.
    const remeasure = () => editor.updateViewportScreenBounds(editor.getContainer());
    const frame = window.requestAnimationFrame(remeasure);
    const observer = new ResizeObserver(remeasure);
    observer.observe(host);
    window.addEventListener("resize", remeasure);
    window.addEventListener("scroll", remeasure, true);   // capture: any ancestor scrolling
    // The one that cannot be out of date: measure on the way *into* a click, in
    // the capture phase, before tldraw reads the position. Observers and frame
    // callbacks only fire on events someone thought to listen for; this fires on
    // the event that actually needs the answer, and costs one rect per press.
    // There is deliberately no pointermove equivalent: it forced a synchronous
    // layout every frame of every drag — the whole cost of drawing a stroke —
    // to defend against a container that moves *between* a press and the move
    // before it, which this listener already covers.
    host.addEventListener("pointerdown", remeasure, true);

    // If the measurement and reality ever disagree, say so on screen instead of
    // leaving it to be found as "clicks land in the wrong place". Two faults are
    // possible and they are not the same bug, so they are reported apart:
    //
    //   offset — the cached rect moved out from under tldraw. Constant error.
    //   scale  — a CSS zoom/scale sits between the canvas's local pixels and the
    //            viewport's, which tldraw has no term for. Error grows with
    //            distance from the corner, and is zero at the corner, which is
    //            exactly why it reads as "fine here, wrong over there".
    const audit = window.setInterval(() => {
      const container = editor.getContainer();
      const rect = container?.getBoundingClientRect();
      const known = editor.getViewportScreenBounds();
      if (!rect || !known) return;
      const dx = Math.round(rect.left - known.x);
      const dy = Math.round(rect.top - known.y);
      // `currentCSSZoom` is the effective zoom of every ancestor multiplied out,
      // which is the exact quantity that has to be 1 here. Where it is missing,
      // the same number falls out of the measured box over the laid-out one.
      const scale = container.currentCSSZoom
        ?? (container.offsetWidth ? rect.width / container.offsetWidth : 1);
      if (Math.abs(scale - 1) > 0.005) setDrift({ kind: "scale", scale });
      else if (Math.abs(dx) > 1 || Math.abs(dy) > 1) setDrift({ kind: "offset", dx, dy });
      else setDrift(null);
    }, 1000);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      window.clearInterval(audit);
      window.removeEventListener("resize", remeasure);
      window.removeEventListener("scroll", remeasure, true);
      host.removeEventListener("pointerdown", remeasure, true);
    };
  }, [editor]);

  const promote = async (shape) => {
    if (!editor) return;
    setBusy("promote");
    try {
      await persist(editor);
      const result = await api(`/api/workspace/blocks/${block.id}/whiteboard/promote`, {
        method: "POST", body: { shape_id: shape.id, base_revision: revisionRef.current },
      });
      revisionRef.current = result.block.revision;
      savedRef.current = JSON.stringify(snapshotOf(result.block.content));
      editor.updateShapes([{ id: shape.id, type: shape.type,
        meta: { ...shape.meta, promotion: result.promotion } }]);
      toast(`Added to the ${PROMOTABLE[shape.meta?.note_type]} library`, "ok");
    } catch (error) {
      if (error.status === 409 && error.detail?.current) {
        setConflict({ current: error.detail.current, local: null });
      } else toast(error.message, "bad");
    }
    setBusy("");
  };

  const generatePage = async () => {
    if (!editor) return;
    setBusy("generate");
    try {
      await persist(editor);
      const page = await api(`/api/workspace/blocks/${block.id}/whiteboard/generate-page`, {
        method: "POST", body: {},
      });
      toast("Editable page generated from the board", "ok");
      nav(`${docsBaseFrom(pathname, me?.role === "client")}/${page.id}`);
    } catch (error) { toast(error.message, "bad"); }
    setBusy("");
  };

  // tldraw remounts its editor if `components` changes identity, so the callback
  // is reached through a ref rather than closed over.
  const generateRef = useRef(generatePage);
  generateRef.current = generatePage;
  const components = useMemo(() => ({
    MainMenu: () => (
      <DefaultMainMenu>
        <TldrawUiMenuGroup id="revcadence">
          <TldrawUiMenuItem id="wb-generate-page" label="Generate page from board"
            icon="external-link" readonlyOk={false}
            onSelect={() => generateRef.current()} />
        </TldrawUiMenuGroup>
        <DefaultMainMenuContent />
      </DefaultMainMenu>
    ),
  }), []);

  const takeTheirs = () => {
    const snapshot = snapshotOf(conflict.current.content);
    revisionRef.current = conflict.current.revision;
    savedRef.current = JSON.stringify(snapshot);
    setConflict(null);
    if (snapshot && editor) { try { editor.store.loadStoreSnapshot(snapshot); } catch { /* empty */ } }
    setSaveState("idle");
  };
  const keepMine = () => {
    const mine = conflict.local || editor?.store.getStoreSnapshot();
    setConflict(null);
    write(mine, { force: true, baseRevision: conflict.current.revision }).catch(() => {});
  };

  return (
    <div className={`wb-root${fill ? " fill" : ""}`}>
      {/* Nothing sits above the canvas. A board is a place to think, and a strip
          of product chrome across the top of it is the thing most in the way of
          that — so the one action that used to live there moved into tldraw's own
          menu, and the save state only appears when there is something wrong. */}
      <div className="wb-canvas-host" ref={hostRef}>
        {/* Unlicensed tldraw renders its own watermark over the canvas. On a
            client-facing screen that is a product decision, not a detail, so the
            key is config: set VITE_TLDRAW_LICENSE_KEY and it goes away. */}
        <Tldraw onMount={onMount} assets={assets} components={components}
          inferDarkMode={false}
          licenseKey={import.meta.env.VITE_TLDRAW_LICENSE_KEY || undefined}
          options={{ maxPages: 1 }} />
        {editor && <QuickConnect editor={editor} readOnly={readOnly} />}
        {editor && (
          <NotePanel editor={editor} readOnly={readOnly} onPromote={promote}
            promoting={busy === "promote"} />
        )}

        {conflict && (
          <div className="wb-alert conflict">
            <span><b>Someone else saved this board.</b> Your changes are still here and have
              not overwritten theirs.</span>
            <Button size="sm" variant="ghost" onClick={takeTheirs}>Load theirs</Button>
            <Button size="sm" variant="secondary" onClick={keepMine}>Keep mine</Button>
          </div>
        )}
        {!conflict && saveState === "error" && (
          <div className="wb-alert bad"><span>Your last change did not save.</span></div>
        )}
        {drift && (
          <div className="wb-alert bad">
            {drift.kind === "scale" ? (
              <span>The canvas is being scaled by {drift.scale.toFixed(2)}× by something above
                it, so clicks land further off the further they are from the top-left corner.
                A CSS <code>zoom</code> or <code>transform</code> has been added over the board —
                that is the bug, not the pointer code.</span>
            ) : (
              <span>Pointer alignment is off by {drift.dx}&thinsp;×&thinsp;{drift.dy}px — clicks will
                land in the wrong place. Reload; if it persists this is a layout bug worth reporting.</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
