/*
 * Presenter port used by TutorEngine (unchanged contract + a few additive methods).
 *
 *   setHandler(fn)                 fn(actionId): 'next' | 'back' | 'goto' | 'cancel' | 'end' | recovery ids
 *   present(view)                  view = {tutorialTitle, stepNumber, totalSteps, message, chip, mode, kind,
 *                                  target: Element|null, nextVisible, nextEnabled, nextLabel, canBack, review, hint}
 *   update({nextEnabled?, notice?})
 *   showNavigating(text)           compact "opening page…" state that survives a page change
 *   showRecovery({message, actions, kind})
 *   showResult({kind, title, message, suggestion?, actions?})
 *   flashSuccess(text) -> Promise  short confirmation for important operations
 *   shake(text)                    gentle "wrong control" feedback
 *   confirm(text, opts) -> Promise<boolean>   in-card confirmation
 *   hide() / destroy() / resumeFromNavigation()
 *
 * `createPresenter({parts})` composes the replaceable parts (overlay, spotlight, pointer, card,
 * motion controller) so any of them can be swapped without touching the engine.
 */
import { motionFor } from "../motion/tokens.js";
import { MotionController } from "./motion-controller.js";
import { TutorCard } from "./card.js";
import { TutorOverlay, TutorPointer, TutorSpotlight } from "./overlay.js";

export class TutorPresenter {
  constructor({ overlay, spotlight, pointer, card, controller, motion, win }) {
    this.overlay = overlay;
    this.spotlight = spotlight;
    this.pointer = pointer;
    this.card = card;
    this.controller = controller;
    this.motion = motion;
    this.win = win;
    this.baseHandler = () => undefined;
    this.handlerStack = [];
    this.view = null;
    this.token = 0;
    this.minimized = false;
    this.paused = false;
    this.asking = false;
    this.card.onAction = (action) => this.onCardAction(action);
    this.keydown = (event) => this.onKeydown(event);
    win.document.addEventListener("keydown", this.keydown, true);
    this.resize = () => this.view && this.card.visible && this.controller.follow(null);
    win.addEventListener("resize", this.resize);
  }

  setHandler(fn) {
    this.baseHandler = fn;
  }

  /** Temporarily route card actions elsewhere (e.g. Show Me). Returns the function that restores them. */
  pushHandler(fn) {
    this.handlerStack.push(fn);
    return () => {
      const at = this.handlerStack.indexOf(fn);
      if (at >= 0) this.handlerStack.splice(at, 1);
    };
  }

  handler(action) {
    const top = this.handlerStack[this.handlerStack.length - 1];
    return (top || this.baseHandler)(action);
  }

  current() {
    const token = ++this.token;
    return () => token === this.token;
  }

  onCardAction(action) {
    switch (action) {
      case "minimize": return this.setMinimized(true);
      case "expand": return this.setMinimized(false);
      case "pause": return this.setPaused(true);
      case "resume": return this.setPaused(false);
      default: return this.handler(action);
    }
  }

  onKeydown(event) {
    if (event.key !== "Escape" || !this.card.visible || this.paused) return;
    event.preventDefault();
    event.stopPropagation();
    if (this.asking) this.card.answer(false);
    else this.handler("cancel");
  }

  // ---- steps ---------------------------------------------------------------

  async present(view) {
    this.view = { ...view };
    this.minimized = false;
    if (this.paused) await this.setPaused(false, { rerender: false });
    await this.controller.transitionToStep(this.view, this.current());
  }

  update(patch) {
    if (this.view) Object.assign(this.view, patch);
    this.card.applyPatch(patch);
  }

  async setMinimized(minimized) {
    this.minimized = minimized;
    if (!this.view) return;
    if (minimized) {
      this.card.renderMinimized(this.view);
      this.controller.pointer.hide();
      const dock = this.controller.dockPosition();
      await this.card.moveTo(dock.x, dock.y, { animateMove: true });
    } else {
      await this.controller.transitionToStep(this.view, this.current());
    }
  }

  async setPaused(paused, { rerender = true } = {}) {
    this.paused = paused;
    if (paused) {
      await this.spotlight.fadeOut();
      this.controller.pointer.hide();
      this.card.renderPaused();
      const dock = this.controller.dockPosition();
      await this.card.moveTo(dock.x, dock.y, { animateMove: true });
    } else if (rerender && this.view) {
      await this.controller.transitionToStep(this.view, this.current());
    }
  }

  // ---- auxiliary states ----------------------------------------------------

  async showCompact(renderer) {
    const isCurrent = this.current();
    const first = !this.card.visible;
    if (!first) await this.card.fadeOutContent();
    if (!isCurrent()) return;
    renderer();
    if (first) {
      this.card.el.hidden = false;
      this.card.visible = true;
      this.card.el.style.visibility = "hidden";
      const dock = this.controller.dockPosition();
      this.card.setSheet(this.controller.viewport().width <= 640);
      this.card.place(dock.x, dock.y);
      this.card.el.style.visibility = "";
    }
    await this.card.fadeInContent();
    this.card.el.classList.remove("is-transitioning");
  }

  async showNavigating(text) {
    this.spotlight.fadeOut();
    this.controller.pointer.hide();
    this.controller.rememberPosition();
    await this.showCompact(() => this.card.renderLoading(text));
  }

  async showRecovery(model) {
    const isCurrent = this.current();
    this.spotlight.fadeOut();
    this.controller.pointer.hide();
    await this.dockedContent(() => this.card.renderRecovery(model), isCurrent);
  }

  async showResult(model) {
    const isCurrent = this.current();
    this.spotlight.fadeOut();
    this.controller.pointer.hide();
    await this.dockedContent(() => this.card.renderResult(model), isCurrent);
  }

  /** Swap card content in place and slide the same card to the dock position. */
  async dockedContent(render, isCurrent) {
    const first = !this.card.visible;
    const before = first ? 0 : this.card.el.offsetHeight;
    if (!first) await this.card.fadeOutContent();
    if (!isCurrent()) return;
    this.card.el.hidden = false;
    render();
    this.card.setSheet(this.controller.viewport().width <= 640);
    const after = this.card.el.offsetHeight;
    const dock = this.controller.dockPosition();
    this.card.el.dataset.tutorSide = "dock";
    if (first) {
      this.card.el.style.visibility = "hidden";
      this.card.place(dock.x, dock.y);
      this.card.el.style.visibility = "";
      await this.card.intro();
    } else {
      const move = this.card.sheet ? Promise.resolve() : this.card.moveTo(dock.x, dock.y, { animateMove: true });
      await Promise.all([move, this.card.animateHeight(before, after), this.card.fadeInContent()]);
    }
    this.card.el.classList.remove("is-transitioning");
    this.card.inner.style.opacity = "";
  }

  async flashSuccess(text) {
    const isCurrent = this.current();
    this.spotlight.flashSuccess();
    await this.showCompact(() => this.card.renderSuccessFlash(text));
    if (!isCurrent()) return;
    await new Promise((resolve) => setTimeout(resolve, this.motion.ms("success")));
  }

  async shake(text) {
    this.update({ notice: { kind: "info", text } });
    await this.card.shake();
  }

  async confirm(text, { title = "إنهاء التعليم؟", confirmLabel = "إنهاء", continueLabel = "متابعة التعليم" } = {}) {
    if (!this.card.visible) return true;
    this.asking = true;
    try {
      return await this.card.ask({ title, message: text, confirmLabel, continueLabel });
    } finally {
      this.asking = false;
    }
  }

  // ---- lifecycle -----------------------------------------------------------

  /** Page just loaded in the middle of a tutorial: appear exactly where the card was (no pop-in). */
  resumeFromNavigation() {
    const stored = this.controller.readRememberedPosition();
    if (!stored) return false;
    this.card.renderLoading("لحظة…");
    this.card.el.hidden = false;
    this.card.visible = true;
    this.card.setSheet(this.controller.viewport().width <= 640);
    this.card.place(stored.x, stored.y);
    this.card.el.dataset.tutorSide = "restored";
    return true;
  }

  async hide() {
    this.token += 1;
    this.controller.pointer.hide();
    this.controller.clearRememberedPosition();
    await Promise.all([this.card.exit(), this.spotlight.fadeOut()]);
    this.view = null;
  }

  destroy() {
    this.token += 1;
    this.win.document.removeEventListener("keydown", this.keydown, true);
    this.win.removeEventListener("resize", this.resize);
    this.spotlight.clear();
    this.overlay.destroy();
  }
}

export function createPresenter({ doc = document, win = window, parts = {} } = {}) {
  const motion = parts.motion || motionFor(win);
  const overlay = parts.overlay || new TutorOverlay(doc);
  const spotlight = parts.spotlight || new TutorSpotlight(overlay, motion, win);
  const pointer = parts.pointer || new TutorPointer(overlay, motion);
  const card = parts.card || new TutorCard(overlay, motion, doc);
  const controller = parts.controller || new MotionController({ overlay, spotlight, card, pointer, motion, win });
  return new TutorPresenter({ overlay, spotlight, pointer, card, controller, motion, win });
}
