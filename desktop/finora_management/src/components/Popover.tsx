import { AnimatePresence, motion } from "framer-motion";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/utils/cn";

interface PopoverProps {
  open: boolean;
  onClose(): void;
  /** The trigger; clicks on it are not treated as "outside". */
  anchor: RefObject<HTMLElement>;
  label: string;
  /** RTL alignment against the anchor: start = right edges, end = left edges, stretch = anchor width. */
  align?: "start" | "end" | "stretch";
  /** Fixed panel width in px (ignored for `stretch`). */
  width?: number;
  className?: string;
  children: ReactNode;
}

interface Placement {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
  width?: number;
  maxHeight: number;
  above: boolean;
}

const GAP = 8;
const MARGIN = 12;

/**
 * Floating glass panel anchored to a trigger. Rendered in a portal with fixed
 * positioning so scroll/overflow containers (window bodies, sheet footers)
 * never clip it; flips above the trigger when there is more room there.
 * Closes on outside click and Escape.
 */
export function Popover({
  open,
  onClose,
  anchor,
  label,
  align = "start",
  width,
  className,
  children,
}: PopoverProps) {
  const panel = useRef<HTMLDivElement>(null);
  const [placement, setPlacement] = useState<Placement | null>(null);

  const place = useCallback(() => {
    const trigger = anchor.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const viewportW = window.innerWidth;
    const viewportH = window.innerHeight;
    const panelH = panel.current?.scrollHeight ?? 0;
    const below = viewportH - rect.bottom - GAP - MARGIN;
    const aboveSpace = rect.top - GAP - MARGIN;
    const above = panelH > below && aboveSpace > below;
    const next: Placement = { maxHeight: Math.max(120, above ? aboveSpace : below), above };
    if (above) next.bottom = viewportH - rect.top + GAP;
    else next.top = rect.bottom + GAP;
    if (align === "stretch") {
      next.left = rect.left;
      next.width = rect.width;
    } else {
      const w = width ?? panel.current?.offsetWidth ?? 0;
      if (align === "start") {
        next.right = Math.max(MARGIN, Math.min(viewportW - rect.right, viewportW - w - MARGIN));
      } else {
        next.left = Math.max(MARGIN, Math.min(rect.left, viewportW - w - MARGIN));
      }
      if (width !== undefined) next.width = Math.min(width, viewportW - MARGIN * 2);
    }
    setPlacement((prev) =>
      prev &&
      prev.top === next.top &&
      prev.bottom === next.bottom &&
      prev.left === next.left &&
      prev.right === next.right &&
      prev.width === next.width &&
      prev.maxHeight === next.maxHeight
        ? prev
        : next,
    );
  }, [anchor, align, width]);

  useLayoutEffect(() => {
    if (!open) {
      setPlacement(null);
      return;
    }
    place();
    // results arriving / filtering change the height: re-place (and maybe flip)
    const node = panel.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => place());
    observer.observe(node);
    return () => observer.disconnect();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, onClose, anchor, place]);

  const above = placement?.above ?? false;
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          ref={panel}
          role="dialog"
          aria-label={label}
          data-popover
          dir="rtl"
          className={cn("glass-solid no-drag fixed z-[95] overflow-y-auto rounded-panel p-2", className)}
          style={{
            top: placement?.top,
            bottom: placement?.bottom,
            left: placement?.left,
            right: placement?.right,
            width: placement?.width ?? width,
            maxHeight: placement?.maxHeight,
            visibility: placement ? "visible" : "hidden",
          }}
          initial={{ opacity: 0, y: above ? 6 : -6, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: above ? 4 : -4, scale: 0.98, transition: { duration: 0.12 } }}
          transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
