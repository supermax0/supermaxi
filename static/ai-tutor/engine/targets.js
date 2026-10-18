/* Target discovery: stable data-finora-* identifiers only, with layered recovery. */
import { selectorFor } from "./core.js";

export function isVisible(el, win = window) {
  if (!el || !el.isConnected) return false;
  if (el.closest("[hidden]")) return false;
  const style = win.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  // A closed off-canvas drawer is laid out but fully outside the viewport horizontally.
  return rect.right > 0 && rect.left < win.innerWidth;
}

export function resolve(ref, root = document) {
  const matches = root.querySelectorAll(selectorFor(ref));
  for (const el of matches) if (isVisible(el, root.defaultView || window)) return el;
  return null;
}

export function exists(ref, root = document) {
  return resolve(ref, root) !== null;
}

/** Wait until `ref` becomes visible; resolves null on timeout or abort. */
export function waitForTarget(ref, { timeoutMs = 3500, signal, root = document } = {}) {
  return new Promise((done) => {
    const found = resolve(ref, root);
    if (found) return done(found);
    let finished = false;
    const finish = (value) => {
      if (finished) return;
      finished = true;
      observer.disconnect();
      clearTimeout(timer);
      clearInterval(poll);
      signal?.removeEventListener("abort", onAbort);
      done(value);
    };
    const check = () => {
      const el = resolve(ref, root);
      if (el) finish(el);
    };
    const observer = new MutationObserver(check);
    observer.observe(root.documentElement, { childList: true, subtree: true, attributes: true });
    // Layout-only changes (drawer transitions) raise no mutation: check per frame briefly, then every 200 ms.
    let frames = 0;
    const win = root.defaultView || window;
    const frame = () => {
      if (finished) return;
      check();
      if (!finished && ++frames < 40) win.requestAnimationFrame(frame);
    };
    win.requestAnimationFrame(frame);
    const poll = setInterval(check, 200);
    const timer = setTimeout(() => finish(null), timeoutMs);
    const onAbort = () => finish(null);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Click a non-destructive "reveal" control (menu button / collapsed nav group). */
function revealOne(ref, root) {
  const el = root.querySelector(selectorFor(ref));
  if (!el) return false;
  if (ref.section) {
    if (!el.classList.contains("is-collapsed")) return false;
    const label = el.querySelector(".cx-sidebar__label");
    if (!label) return false;
    label.click();
    return true;
  }
  if (!isVisible(el, root.defaultView || window)) return false;
  el.click();
  return true;
}

/** Present in the DOM but not visible: hidden by a collapsed group or a closed drawer, not "still rendering". */
const inDomButHidden = (ref, root) => !resolve(ref, root) && root.querySelector(selectorFor(ref)) !== null;

const nextFrame = (win) => new Promise((done) => win.requestAnimationFrame(() => done()));

/** Run every known reveal control that is actually available now; true when one was used. */
function revealAll(reveal, root) {
  let used = false;
  for (const item of reveal) if (revealOne(item, root)) used = true;
  return used;
}

/**
 * Find a step target without a fixed wait. Order:
 *  1. immediate query
 *  2. known reveal strategy, at once, when the target is in the DOM but hidden (collapsed nav / closed drawer)
 *  3. next animation frame (layout settles after the reveal / a render)
 *  4. short observer wait (renders that really need time), re-trying reveals once the target shows up hidden
 *  5. final timeout recovery: one more reveal pass and a last wait
 */
export async function acquireTarget(ref, { reveal = [], signal, root = document } = {}) {
  const win = root.defaultView || window;
  let el = resolve(ref, root);
  if (el || signal?.aborted) return el;

  let revealed = false;
  if (reveal.length && inDomButHidden(ref, root)) {
    revealed = revealAll(reveal, root);
    if (revealed) {
      await nextFrame(win);
      el = resolve(ref, root) || (await waitForTarget(ref, { timeoutMs: 900, signal, root }));
      if (el || signal?.aborted) return el;
      revealAll(reveal, root); // the next collapsed layer (drawer opened, group still collapsed)
      el = await waitForTarget(ref, { timeoutMs: 900, signal, root });
      if (el || signal?.aborted) return el;
    }
  }
  await nextFrame(win);
  el = resolve(ref, root);
  if (el) return el;

  // Genuinely not rendered yet: observe, and reveal as soon as it appears hidden.
  const hiddenWatch = new MutationObserver(() => {
    if (!revealed && reveal.length && inDomButHidden(ref, root)) revealed = revealAll(reveal, root);
  });
  hiddenWatch.observe(root.documentElement, { childList: true, subtree: true });
  try {
    el = await waitForTarget(ref, { timeoutMs: 2500, signal, root });
  } finally {
    hiddenWatch.disconnect();
  }
  if (el || signal?.aborted) return el;
  for (const item of reveal) {
    if (revealOne(item, root)) {
      el = await waitForTarget(ref, { timeoutMs: 1500, signal, root });
      if (el) return el;
    }
  }
  return waitForTarget(ref, { timeoutMs: 1500, signal, root });
}

export function currentPage(root = document) {
  return root.querySelector("[data-finora-page]")?.getAttribute("data-finora-page") || null;
}
