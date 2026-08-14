import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";

const zoomOf = () => parseFloat(getComputedStyle(document.body).zoom) || 1;

// Shared anchored popup shell for menus, selectors, and small contextual panels.
// It deliberately owns only portal positioning, dismissal, and motion; each caller
// supplies its own trigger and content.
export function InlinePopup({
  open,
  onClose,
  anchorRef,
  anchorSelector,
  children,
  className = "",
  align = "start",
  side = "bottom",
  offset = 6,
  minWidth,
  maxHeight,
  contentRef,
  style,
  role = "dialog",
  ...rest
}) {
  const [position, setPosition] = useState(null);

  const place = useCallback(() => {
    const anchor = anchorSelector
      ? anchorRef.current?.closest(anchorSelector) ?? anchorRef.current
      : anchorRef.current;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    const zoom = zoomOf();
    const gap = offset * zoom;
    const edge = 8 * zoom;
    const openUpward = side === "top" || (side === "auto" && rect.bottom + 240 * zoom > window.innerHeight && rect.top > window.innerHeight - rect.bottom);
    const available = (openUpward ? rect.top - edge : window.innerHeight - rect.bottom - edge) - gap;
    setPosition({
      ...(align === "end"
        ? { right: Math.max(edge, window.innerWidth - rect.right) / zoom }
        : { left: Math.max(edge, Math.min(rect.left, window.innerWidth - edge)) / zoom }),
      ...(minWidth ? { width: Math.max(rect.width, minWidth * zoom) / zoom } : {}),
      ...(maxHeight ? { maxHeight: Math.max(120 * zoom, Math.min(maxHeight * zoom, available)) / zoom } : {}),
      ...(openUpward ? { bottom: (window.innerHeight - rect.top + gap) / zoom } : { top: (rect.bottom + gap) / zoom }),
    });
  }, [align, anchorRef, anchorSelector, maxHeight, minWidth, offset, side]);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const dismiss = (event) => {
      if (anchorRef.current?.contains(event.target) || contentRef?.current?.contains(event.target)) return;
      onClose?.();
    };
    const onKeyDown = (event) => event.key === "Escape" && onClose?.();
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, anchorRef, contentRef, onClose]);

  return createPortal(
    <AnimatePresence>
      {open && position && (
        <motion.div
          ref={contentRef}
          className={`inline-popup ${className}`}
          role={role}
          style={{ position: "fixed", ...position, ...style }}
          initial={{ opacity: 0, scale: 0.98, y: side === "top" ? 4 : -4 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.98, y: side === "top" ? 4 : -4 }}
          transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
          {...rest}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
