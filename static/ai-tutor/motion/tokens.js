/* Central motion tokens. No component may hard-code a duration or easing. */

export const tutorMotion = Object.freeze({
  fast: 160,
  normal: 260,
  move: 480,
  slow: 650,
  intro: 320,
  exit: 180,
  contentOut: 120,
  contentIn: 200,
  heightChange: 260,
  sheet: 360,
  shake: 220,
  success: 700,
  rippleDuration: 900,
  rippleEvery: 2200,
  pulse: 1800,
  reducedFade: 120,
  easeOut: "cubic-bezier(0.22, 1, 0.36, 1)",
  easeOutArray: Object.freeze([0.22, 1, 0.36, 1]),
  spring: Object.freeze({ stiffness: 360, damping: 30, mass: 0.8 }),
});

export function prefersReducedMotion(win = window) {
  return !!win.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Resolve a token for the current user preference. With reduced motion every
 * movement collapses to 0 and fades shrink to a short cross-fade.
 */
export function motionFor(win = window) {
  const reduced = prefersReducedMotion(win);
  const movement = new Set(["move", "slow", "heightChange", "sheet", "shake", "intro", "exit"]);
  return {
    reduced,
    ease: tutorMotion.easeOut,
    ms(name) {
      if (!(name in tutorMotion) || typeof tutorMotion[name] !== "number") throw new RangeError(`unknown motion token: ${name}`);
      if (!reduced) return tutorMotion[name];
      return movement.has(name) ? 0 : Math.min(tutorMotion[name], tutorMotion.reducedFade);
    },
  };
}

/** Run a Web Animation and resolve when finished; resolves immediately when `duration` is 0. */
export function animate(el, keyframes, duration, easing = tutorMotion.easeOut, options = {}) {
  if (!duration || typeof el.animate !== "function") return Promise.resolve();
  const animation = el.animate(keyframes, { duration, easing, fill: "none", ...options });
  return animation.finished.catch(() => undefined);
}
