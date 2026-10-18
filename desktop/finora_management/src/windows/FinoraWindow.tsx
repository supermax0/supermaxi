import { motion } from "framer-motion";
import { memo, useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { STAGE_INSET, STAGE_INSET_EXPANDED, type MorphContext } from "@/animations/transitions";
import { useMorph } from "@/animations/useMorph";
import { usePreferences } from "@/stores/preferences";
import { useWindowManager } from "@/stores/windowManager";
import { WindowHeader } from "./WindowHeader";
import { WINDOWS, type WindowId } from "./registry";

interface FinoraWindowProps {
  id: WindowId;
  open: boolean;
  stage: HTMLElement | null;
  children: ReactNode;
}

function currentInset(): number {
  return useWindowManager.getState().expanded ? STAGE_INSET_EXPANDED : STAGE_INSET;
}

/**
 * A floating application window. It stays mounted once opened, so switching
 * windows never re-creates tables or refetches: only the glass shell morphs
 * (button ⇄ window, compositor-only via useMorph) and the content fades.
 * A closed window is hidden with `visibility` after its close morph finishes,
 * so it costs nothing to paint.
 */
export const FinoraWindow = memo(function FinoraWindow({ id, open, stage, children }: FinoraWindowProps) {
  const expanded = useWindowManager((s) => s.expanded);
  const motionPreference = usePreferences((s) => s.motion);
  const definition = WINDOWS[id];
  const inset = expanded ? STAGE_INSET_EXPANDED : STAGE_INSET;
  const ctx = useMemo<MorphContext>(() => ({ id, stage, inset: currentInset }), [id, stage]);
  const shell = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [settledClosed, setSettledClosed] = useState(!open);
  const onClosed = useCallback(() => setSettledClosed(true), []);

  if (open && settledClosed) setSettledClosed(false);
  const hidden = !open && settledClosed;

  useMorph({ shell, content, open, ctx, motion: motionPreference, onClosed });

  return (
    <motion.section
      role="dialog"
      aria-label={definition.title}
      aria-hidden={!open}
      data-window={id}
      data-state={open ? "open" : hidden ? "closed" : "closing"}
      className="absolute"
      style={{
        zIndex: open ? 2 : 1,
        pointerEvents: open ? "auto" : "none",
        visibility: hidden ? "hidden" : "visible",
      }}
      initial={false}
      animate={{ top: inset, left: inset, right: inset, bottom: inset }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
    >
      <div
        ref={shell}
        aria-hidden
        className="glass glass-outline absolute inset-0 rounded-window"
        style={{ willChange: "transform, opacity", transformOrigin: "50% 50%" }}
      />
      <div ref={content} className="absolute inset-0 flex flex-col overflow-hidden rounded-window">
        <WindowHeader definition={definition} />
        <div className="min-h-0 flex-1 px-7 pb-6">{children}</div>
      </div>
    </motion.section>
  );
});
