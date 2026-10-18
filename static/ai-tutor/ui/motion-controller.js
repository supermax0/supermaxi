/*
 * MotionController: the single place that sequences a step change.
 *
 *   transitionToStep(view): fade current content → swap content (measured) → make the
 *   target visible (smart scroll) → compute placement → morph spotlight + slide the SAME
 *   card + animate its height → fade the new content in.
 */
import { computePlacement, layoutMode, toRect } from "./positioner.js";

const CHROME_SELECTORS = [".cx-topbar", ".cx-mobile-nav"];
const CARD_POS_KEY = "finora.tutor.cardPos";
const SHEET_MAX_VH = 0.42;

export class MotionController {
  constructor({ overlay, spotlight, card, pointer, motion, win = window }) {
    this.overlay = overlay;
    this.spotlight = spotlight;
    this.card = card;
    this.pointer = pointer;
    this.motion = motion;
    this.win = win;
    this.doc = overlay.doc;
    this.side = null;
    this.target = null;
    this.spotlight.onMove = (rect) => this.follow(rect);
  }

  // ---- environment measurement --------------------------------------------

  viewport() {
    return { width: this.win.innerWidth, height: this.win.innerHeight };
  }

  /** Insets taken by fixed/sticky chrome (navbar, bottom bar) so targets never hide behind them. */
  safeInsets() {
    const vp = this.viewport();
    const insets = { top: 0, bottom: 0, left: 0, right: 0 };
    for (const selector of CHROME_SELECTORS) {
      const node = this.doc.querySelector(selector);
      if (!node) continue;
      const style = this.win.getComputedStyle(node);
      if (!["fixed", "sticky"].includes(style.position)) continue;
      const r = node.getBoundingClientRect();
      if (r.height === 0 || r.width === 0) continue;
      if (r.top <= 1 && r.bottom < vp.height / 2) insets.top = Math.max(insets.top, r.bottom);
      if (r.bottom >= vp.height - 1 && r.top > vp.height / 2) insets.bottom = Math.max(insets.bottom, vp.height - r.top);
    }
    return insets;
  }

  containerOf(target) {
    const modal = target.closest(".cx-modal, [role='dialog']:not([data-tutor-ui])");
    return modal && !modal.hidden ? modal.getBoundingClientRect() : null;
  }

  avoidRects(target) {
    const rects = [];
    const nodes = this.doc.querySelectorAll("[data-finora-field], [data-finora-action]");
    for (const node of nodes) {
      if (node === target || node.contains(target) || target.contains(node) || node.closest("[data-tutor-ui]")) continue;
      const r = node.getBoundingClientRect();
      if (r.width < 4 || r.height < 4 || r.right < 0 || r.left > this.win.innerWidth || r.bottom < 0 || r.top > this.win.innerHeight) continue;
      rects.push({ rect: toRect(r.left, r.top, r.width, r.height), weight: 0.7 });
      if (rects.length >= 40) break;
    }
    return rects;
  }

  // ---- smart scrolling -----------------------------------------------------

  needsScroll(target, safe) {
    const r = target.getBoundingClientRect();
    return r.top < safe.top + 12 || r.bottom > this.win.innerHeight - safe.bottom - 12;
  }

  async ensureVisible(target, safe) {
    if (!this.needsScroll(target, safe)) return false;
    target.scrollIntoView({ block: "center", inline: "nearest", behavior: this.motion.reduced ? "auto" : "smooth" });
    await this.untilStable(target);
    // Centering may still leave it under fixed chrome (or behind a bottom sheet): nudge the window.
    const r = target.getBoundingClientRect();
    const overTop = safe.top + 12 - r.top;
    const overBottom = r.bottom - (this.win.innerHeight - safe.bottom - 12);
    if (overTop > 0) this.win.scrollBy(0, -overTop);
    else if (overBottom > 0) this.win.scrollBy(0, overBottom);
    return true;
  }

  /** Resolve once the target stopped moving (scroll finished); bounded so it can never hang. */
  untilStable(target, maxFrames = 90) {
    return new Promise((resolve) => {
      let last = null;
      let still = 0;
      let frames = 0;
      const tick = () => {
        const r = target.getBoundingClientRect();
        const key = `${Math.round(r.top)}:${Math.round(r.left)}`;
        still = key === last ? still + 1 : 0;
        last = key;
        frames += 1;
        if (still >= 4 || frames >= maxFrames) resolve();
        else requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  // ---- placement -----------------------------------------------------------

  computeFor(target, safe) {
    const cardSize = this.card.size();
    return computePlacement({
      target: toRect(...Object.values(this.rectOf(target))),
      card: cardSize,
      viewport: this.viewport(),
      safe,
      avoid: this.avoidRects(target),
      container: this.containerOf(target),
      stickySide: this.side,
    });
  }

  rectOf(target) {
    const r = target.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }

  dockPosition() {
    const { width, height } = this.card.size();
    const vp = this.viewport();
    return { x: vp.width > 640 ? 24 : 12, y: Math.max(16, vp.height - height - 96), width, height };
  }

  applyPlacement(placement, { animateMove }) {
    const isSheet = placement.mode === "sheet";
    this.card.setSheet(isSheet);
    this.card.el.dataset.tutorSide = placement.side;
    this.card.el.dataset.tutorEdge = isSheet ? placement.edge || "bottom" : "";
    this.side = isSheet ? null : placement.side;
    this.pointer.show(isSheet ? null : placement.connector);
    if (isSheet) return Promise.resolve();
    return this.card.moveTo(placement.x, placement.y, { animateMove });
  }

  /** The spotlight reports target movement (scroll/resize/layout): keep the card attached. */
  follow(rect) {
    if (!this.target || !this.card.visible || this.card.el.classList.contains("is-transitioning") || this.card.el.classList.contains("is-min")) return;
    const safe = this.safeInsets();
    const placement = this.computeFor(this.target, safe);
    if (placement.mode === "sheet" || this.card.sheet) {
      const edgeChanged = placement.mode === "sheet" && (placement.edge || "bottom") !== (this.card.el.dataset.tutorEdge || "bottom");
      if ((placement.mode === "sheet") !== this.card.sheet || edgeChanged) this.applyPlacement(placement, { animateMove: false });
      return;
    }
    const sameSide = placement.side === this.side;
    this.applyPlacement(placement, { animateMove: !sameSide });
    void rect;
  }

  // ---- the transition ------------------------------------------------------

  async transitionToStep(view, isCurrent) {
    const first = !this.card.visible;
    const heightBefore = first ? 0 : this.card.el.offsetHeight;
    if (!first) await this.card.fadeOutContent();
    if (!isCurrent()) return;

    this.card.renderStep(view);
    if (!first) this.card.inner.style.opacity = "0";
    else this.card.el.classList.add("is-transitioning");
    this.card.el.hidden = false;
    this.card.el.style.visibility = first ? "hidden" : "";

    const target = view.target;
    this.target = target;
    const vp = this.viewport();
    const phone = layoutMode(vp) === "phone";
    let safe = this.safeInsets();
    if (phone) safe = { ...safe, bottom: Math.max(safe.bottom, Math.round(Math.min(this.card.size().height, vp.height * SHEET_MAX_VH)) + 12) };

    if (target) {
      const scrolled = await this.ensureVisible(target, safe);
      if (!isCurrent()) return;
      void scrolled;
    }

    const heightAfter = this.card.el.offsetHeight;
    let placement;
    if (target) placement = this.computeFor(target, safe);
    else placement = { mode: phone ? "sheet" : "floating", side: "dock", connector: null, ...this.dockPosition() };

    const focus = target
      ? this.spotlight.focus(target, { mode: view.mode, morph: !first })
      : this.spotlight.fadeOut();
    const move = this.applyPlacement(placement, { animateMove: !first });
    this.card.el.style.visibility = "";

    if (first) {
      await focus;
      if (!isCurrent()) return;
      await this.card.intro();
      this.card.inner.style.opacity = "";
      this.card.el.classList.remove("is-transitioning");
    } else {
      const heights = this.card.animateHeight(heightBefore, heightAfter);
      const reveal = new Promise((resolve) => setTimeout(resolve, this.motion.ms("move") * 0.45))
        .then(() => this.card.fadeInContent());
      await Promise.all([focus, move, heights, reveal]);
      this.card.el.classList.remove("is-transitioning"); // only once EVERY animation has finished
    }
    this.rememberPosition();
  }

  rememberPosition() {
    if (!this.card.pos) return;
    try {
      this.win.sessionStorage.setItem(CARD_POS_KEY, JSON.stringify({ ...this.card.pos, t: Date.now() }));
    } catch (error) {
      console.warn("[tutor] could not remember card position", error);
    }
  }

  readRememberedPosition() {
    try {
      const stored = JSON.parse(this.win.sessionStorage.getItem(CARD_POS_KEY) || "null");
      if (stored && Date.now() - stored.t < 8000 && Number.isFinite(stored.x) && Number.isFinite(stored.y)) return stored;
    } catch (error) {
      console.warn("[tutor] ignoring unreadable card position", error);
    }
    return null;
  }

  clearRememberedPosition() {
    try {
      this.win.sessionStorage.removeItem(CARD_POS_KEY);
    } catch (error) {
      console.warn("[tutor] could not clear card position", error);
    }
  }
}
