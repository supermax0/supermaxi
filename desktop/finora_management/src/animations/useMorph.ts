/**
 * Compositor-only window morph driven by the Web Animations API.
 *
 * Pattern: read the element's *current* (possibly mid-animation) transform and
 * opacity, cancel what is running, write the FINAL values to the inline style,
 * then animate from the current values to them. When an animation ends there
 * is nothing to hand over, so no stale frame can flash (Framer Motion's WAAPI
 * hand-off showed one); interruptions (rapid switching) continue smoothly
 * from wherever the element is.
 */
import { useLayoutEffect, useRef, type RefObject } from "react";
import { collapsedTransform, IDENTITY, type MorphContext } from "./transitions";

const EASE_OUT = "cubic-bezier(0.16, 1, 0.3, 1)";
const EASE_IN_OUT = "cubic-bezier(0.45, 0, 0.2, 1)";

export const MORPH_TIMING = {
  open: { transform: 460, opacity: 200 },
  close: { transform: 340, opacity: 220, opacityDelay: 120 },
  contentIn: { delay: 140, duration: 260 },
  contentOut: { duration: 120 },
} as const;

function supportsWaapi(element: HTMLElement): boolean {
  return typeof element.animate === "function";
}

function reducedMotion(preference: "system" | "reduced"): boolean {
  if (preference === "reduced") return true;
  return (
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

interface MorphOptions {
  shell: RefObject<HTMLElement>;
  content: RefObject<HTMLElement>;
  open: boolean;
  ctx: MorphContext;
  motion: "system" | "reduced";
  onClosed(): void;
}

export function useMorph({ shell, content, open, ctx, motion, onClosed }: MorphOptions): void {
  const running = useRef<Animation[]>([]);
  const closedCallback = useRef(onClosed);
  closedCallback.current = onClosed;
  const first = useRef(true);

  useLayoutEffect(() => {
    const shellEl = shell.current;
    const contentEl = content.current;
    if (!shellEl || !contentEl) return;

    // Mount frame: start exactly on the button, invisible.
    if (first.current) {
      first.current = false;
      shellEl.style.transform = collapsedTransform(ctx);
      shellEl.style.opacity = "0";
      contentEl.style.opacity = "0";
      contentEl.style.transform = "translateY(10px)";
      // Pre-mounted while closed (idle warm-up): nothing to animate.
      if (!open) return;
    }

    const from = {
      shellTransform: getComputedStyle(shellEl).transform,
      shellOpacity: getComputedStyle(shellEl).opacity,
      contentOpacity: getComputedStyle(contentEl).opacity,
      contentTransform: getComputedStyle(contentEl).transform,
    };
    for (const animation of running.current) animation.cancel();
    running.current = [];

    const to = {
      shellTransform: open ? IDENTITY : collapsedTransform(ctx),
      shellOpacity: open ? "1" : "0",
      contentOpacity: open ? "1" : "0",
      contentTransform: open ? "translateY(0px)" : "translateY(4px)",
    };
    shellEl.style.transform = to.shellTransform;
    shellEl.style.opacity = to.shellOpacity;
    contentEl.style.opacity = to.contentOpacity;
    contentEl.style.transform = to.contentTransform;

    if (!supportsWaapi(shellEl)) {
      if (!open) closedCallback.current();
      return;
    }

    const reduce = reducedMotion(motion);
    const timing = open ? MORPH_TIMING.open : MORPH_TIMING.close;
    const animations: Animation[] = [];
    if (!reduce) {
      animations.push(
        shellEl.animate([{ transform: from.shellTransform }, { transform: to.shellTransform }], {
          duration: timing.transform,
          easing: open ? EASE_OUT : EASE_IN_OUT,
        }),
      );
    }
    animations.push(
      shellEl.animate([{ opacity: from.shellOpacity }, { opacity: to.shellOpacity }], {
        duration: reduce ? 160 : timing.opacity,
        delay: open || reduce ? 0 : MORPH_TIMING.close.opacityDelay,
        easing: "linear",
        fill: "backwards",
      }),
      contentEl.animate(
        [
          { opacity: from.contentOpacity, transform: from.contentTransform },
          { opacity: to.contentOpacity, transform: to.contentTransform },
        ],
        open
          ? {
              duration: MORPH_TIMING.contentIn.duration,
              delay: reduce ? 0 : MORPH_TIMING.contentIn.delay,
              easing: EASE_OUT,
              fill: "backwards",
            }
          : { duration: MORPH_TIMING.contentOut.duration, easing: "ease-out" },
      ),
    );
    running.current = animations;

    Promise.all(animations.map((animation) => animation.finished))
      .then(() => {
        running.current = [];
        if (!open) closedCallback.current();
      })
      .catch((error: unknown) => {
        // Cancelled because the user switched again — the next run takes over.
        if (!isAbort(error)) console.error("[morph] animation failed", error);
      });
    // `ctx` reads live geometry when called; re-running on its identity is unnecessary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, motion]);
}
