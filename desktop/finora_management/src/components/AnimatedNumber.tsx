import { useEffect, useRef, useState } from "react";
import { usePreferences } from "@/stores/preferences";
import { formatNumber } from "@/utils/format";

const DURATION_MS = 320;

function reducedMotion(preference: "system" | "reduced"): boolean {
  if (preference === "reduced") return true;
  return (
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** Counts smoothly from the previous value to the new one (ease-out), e.g. the POS total. */
export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const motion = usePreferences((s) => s.motion);
  const [shown, setShown] = useState(value);
  const shownRef = useRef(value);

  useEffect(() => {
    const from = shownRef.current;
    if (from === value || reducedMotion(motion) || typeof requestAnimationFrame !== "function") {
      shownRef.current = value;
      setShown(value);
      return;
    }
    const started = performance.now();
    let frame = 0;
    const tick = () => {
      const t = Math.min(1, Math.max(0, (performance.now() - started) / DURATION_MS));
      const eased = 1 - (1 - t) ** 3;
      const next = Math.round(from + (value - from) * eased);
      shownRef.current = next;
      setShown(next);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, motion]);

  return <span className={className}>{formatNumber(shown)}</span>;
}
