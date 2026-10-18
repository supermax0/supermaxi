/*
 * Show Me V1: visual guidance only. It scrolls to the target, spotlights it and glides a virtual pointer
 * onto it. It NEVER clicks, types or saves anything. Targets are registry ids resolved by the same
 * stable-identifier code the tutorial engine uses (no free-form selectors).
 */
import { acquireTarget, isVisible } from "../engine/targets.js";
import { animate, tutorMotion } from "../motion/tokens.js";

export class ShowMe {
  constructor({ presenter, engine, overlay, motion, doc = document, win = window }) {
    this.presenter = presenter;
    this.engine = engine;
    this.overlay = overlay;
    this.motion = motion;
    this.doc = doc;
    this.win = win;
    this.active = false;
    this.cursor = doc.createElement("div");
    this.cursor.className = "ft-vcursor";
    this.cursor.dataset.tutorUi = "virtual-pointer";
    this.cursor.hidden = true;
    this.cursor.innerHTML = '<i class="ft-vcursor__dot"></i><i class="ft-vcursor__ripple"></i>';
    overlay.mount(this.cursor);
  }

  isRunning() {
    return this.active;
  }

  /** Glide the virtual pointer from `from` (x,y) to the centre of `el`, then ripple once. */
  async point(el, from) {
    const rect = el.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + Math.min(rect.height / 2, 40);
    this.cursor.hidden = false;
    this.cursor.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    this.cursor.classList.remove("is-rippling");
    await animate(this.cursor, [
      { transform: `translate3d(${from.x}px, ${from.y}px, 0)`, opacity: 0.2 },
      { transform: `translate3d(${x}px, ${y}px, 0)`, opacity: 1 },
    ], this.motion.reduced ? 0 : 600, tutorMotion.easeOut);
    this.cursor.classList.add("is-rippling"); // visual ripple only: no click event is ever dispatched
  }

  hidePointer() {
    this.cursor.hidden = true;
    this.cursor.classList.remove("is-rippling");
  }

  cardCentre() {
    const rect = this.presenter.card.el.getBoundingClientRect();
    const usable = rect.width > 0 && !this.presenter.card.el.hidden;
    return usable ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : { x: this.win.innerWidth / 2, y: this.win.innerHeight - 80 };
  }

  /**
   * Highlight a registry target. Returns {found:boolean}. While it is shown the card offers a single
   * "تمام" button; Escape/× also close it.
   */
  async run({ target, reveal = [], message = "" }) {
    if (this.active || this.engine.isBusy()) return { found: false, busy: true };
    const el = await acquireTarget(target, { reveal, root: this.doc });
    if (!el) return { found: false, busy: false };
    this.active = true;
    const finished = new Promise((resolve) => {
      const release = this.presenter.pushHandler((action) => {
        if (action === "next" || action === "cancel" || action === "end") {
          release();
          resolve();
        }
      });
    });
    await this.presenter.present({
      tutorialTitle: "وريني وين", stepId: "show-me", stepNumber: 1, totalSteps: 1, showProgress: false,
      message: message || "هذا هو المكان.", chip: null, kind: "information", nextLabel: "تمام", canBack: false,
      review: false, mode: "info", target: el, nextVisible: true, nextEnabled: true, notice: null,
      hint: "هذا توجيه بصري فقط، ما راح أضغط أو أحفظ أي شي.",
    });
    await this.point(el, this.cardCentre());
    await finished;
    this.hidePointer();
    await this.presenter.hide();
    this.active = false;
    return { found: true, busy: false };
  }

  /** During a running lesson: re-point at the current step's target (no new card, no state change). */
  async pointAtCurrent() {
    const el = this.engine.currentTargetEl;
    if (!el || !el.isConnected || !isVisible(el, this.win)) return false;
    await this.point(el, this.cardCentre());
    await new Promise((resolve) => setTimeout(resolve, 2400));
    this.hidePointer();
    return true;
  }
}
