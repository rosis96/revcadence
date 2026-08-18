// Shared motion for anything that opens over the page: dialogs, confirms, drawers.
//
// One definition so the surfaces cannot drift apart — a confirm that snaps open
// while a dialog eases in reads as two different products. No React, no imports:
// dialogs.jsx and index.jsx both consume this, so it must not import either.

export const EASE = [0.22, 1, 0.36, 1];

/** Offset from the viewport centre to `from`, which may be an element, a
 *  {x, y} point, or nothing. Used so a dialog appears to grow out of whatever
 *  opened it rather than materialising in the middle. */
export function originOffset(from) {
  if (!from) return { x: 0, y: 0 };
  let point = from;
  if (typeof Element !== "undefined" && from instanceof Element) {
    const r = from.getBoundingClientRect();
    point = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }
  if (typeof point?.x !== "number" || typeof point?.y !== "number") return { x: 0, y: 0 };
  return {
    x: Math.round(point.x - window.innerWidth / 2),
    y: Math.round(point.y - window.innerHeight / 2),
  };
}

/** Motion props for a centred dialog box flying from `from`. */
export function dialogMotion(from) {
  const o = originOffset(from);
  return {
    initial: { opacity: 0, scale: 0.45, x: o.x, y: o.y },
    animate: { opacity: 1, scale: 1, x: 0, y: 0 },
    exit: { opacity: 0, scale: 0.6, x: o.x, y: o.y },
    transition: { duration: 0.32, ease: EASE },
  };
}

/** Motion props for the dimmed backdrop behind a dialog. */
export const backdropMotion = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0 },
  transition: { duration: 0.18, ease: "easeOut" },
};

/** Motion props for a right-hand drawer. */
export const drawerMotion = {
  initial: { x: "100%" },
  animate: { x: 0 },
  exit: { x: "100%" },
  transition: { duration: 0.28, ease: EASE },
};

/** True when `el` is the last overlay in the document — i.e. the one on top.
 *
 *  Dialogs stack: a confirm can open over a dialog. Both listen for Escape, and
 *  without this both would close, so one keypress would dismiss a decision the
 *  user has not made yet. Escape closes the top layer and nothing else.
 *
 *  An anchored popup (a Select menu, an icon picker) portals ABOVE everything,
 *  so while one is open no overlay is on top and Escape belongs to the popup. */
export function isTopOverlay(el) {
  if (typeof document === "undefined" || !el) return false;
  if (document.querySelector(".inline-popup")) return false;
  const overlays = document.querySelectorAll(".modal");
  return overlays.length === 0 || overlays[overlays.length - 1] === el;
}

// Where the last pointer press landed. An imperative confirm/prompt has no ref to
// the control that opened it, so we remember the press instead — that is the point
// the user's eye is already on. Falls back to the focused element for keyboard use.
let lastPress = null;

export function trackPointerOrigin() {
  if (typeof document === "undefined") return () => {};
  const onDown = (e) => {
    if (typeof e.clientX !== "number" || (e.clientX === 0 && e.clientY === 0)) return;
    lastPress = { x: e.clientX, y: e.clientY, at: Date.now() };
  };
  document.addEventListener("mousedown", onDown, true);
  return () => document.removeEventListener("mousedown", onDown, true);
}

/** Best guess at what opened an imperative dialog: a recent click, else the
 *  focused control (keyboard), else the centre. */
export function currentOrigin() {
  if (lastPress && Date.now() - lastPress.at < 800) return { x: lastPress.x, y: lastPress.y };
  const el = typeof document !== "undefined" ? document.activeElement : null;
  if (el && el !== document.body && typeof el.getBoundingClientRect === "function") return el;
  return null;
}
