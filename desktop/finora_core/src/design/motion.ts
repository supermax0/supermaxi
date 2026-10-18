import type { Transition } from "framer-motion";

/** Centralized motion tokens (ms). Every animation in the app reads from here. */
export const duration = {
  fast: 120,
  normal: 220,
  slow: 550,
  orbMorph: 650,
} as const;

/** Premium ease-out: fast start, long soft landing. No overshoot. */
export const easeOutSoft = [0.22, 1, 0.36, 1] as const;
export const easeInOutSoft = [0.65, 0, 0.35, 1] as const;

const s = (ms: number) => ms / 1000;

export const transitions = {
  fast: { duration: s(duration.fast), ease: easeOutSoft },
  normal: { duration: s(duration.normal), ease: easeOutSoft },
  slow: { duration: s(duration.slow), ease: easeOutSoft },
  /** Shared-layout morph between the orb and the workspace surface. Critically damped spring, no bounce. */
  morph: { type: "spring", stiffness: 210, damping: 30, mass: 1, restDelta: 0.5 },
} satisfies Record<string, Transition>;

/** Used when reduced motion is requested: everything collapses to a short fade. */
export const reducedTransition: Transition = { duration: s(duration.fast), ease: "linear" };
