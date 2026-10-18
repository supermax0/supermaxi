/*
 * TutorCard: ONE persistent element for the whole tutorial. It moves, resizes and swaps
 * content in place (never unmounted between steps). Visuals use transform/opacity.
 */
import { animate } from "../motion/tokens.js";

const SPARK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l1.9 5.6 5.6 1.9-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.9L12 2.5zM18.5 15l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6z"/></svg>';
const CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const ICON_MIN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6v12M15 6v12"/></svg>';

const STATES = ["instruction", "information", "success", "warning", "loading", "question", "error", "paused"];

export class TutorCard {
  constructor(overlay, motion, doc = document) {
    this.doc = doc;
    this.motion = motion;
    this.el = doc.createElement("section");
    this.el.className = "ft-card";
    this.el.dataset.tutorUi = "card";
    this.el.setAttribute("role", "dialog");
    this.el.setAttribute("aria-label", "مدرس Finora");
    this.el.setAttribute("aria-live", "polite");
    this.el.hidden = true;
    this.inner = doc.createElement("div");
    this.inner.className = "ft-card__inner";
    this.el.appendChild(this.inner);
    overlay.mount(this.el);

    this.pos = null; // last applied {x, y}
    this.sheet = false;
    this.visible = false;
    this.shownToken = 0; // a late exit animation must never hide content rendered after it started
    this.nextBtn = null;
    this.noticeEl = null;
    this.questionResolver = null;
    this.onAction = () => undefined;
    this.el.addEventListener("click", (event) => this.handleClick(event));
  }

  // ---- generic helpers -----------------------------------------------------

  node(tag, className, text) {
    const n = this.doc.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  button(action, label, { primary = false, disabled = false, icon = null, title = null } = {}) {
    const b = this.node("button", primary ? "ft-btn ft-btn--primary" : "ft-btn");
    b.type = "button";
    b.dataset.tutorAction = action;
    b.disabled = disabled;
    if (icon) {
      b.classList.add("ft-btn--icon");
      b.innerHTML = icon;
      b.setAttribute("aria-label", title || label);
      b.title = title || label;
    } else {
      b.textContent = label;
    }
    return b;
  }

  setState(state) {
    if (!STATES.includes(state)) throw new RangeError(`unknown card state: ${state}`);
    this.el.dataset.state = state;
  }

  handleClick(event) {
    const button = event.target.closest("[data-tutor-action]");
    if (!button || button.disabled) return;
    const action = button.dataset.tutorAction;
    if (action === "confirm-end" || action === "confirm-continue") {
      this.answer(action === "confirm-end");
      return;
    }
    this.onAction(action);
  }

  /** Resolve the in-card question (true = the destructive choice). */
  answer(endChosen) {
    if (!this.questionResolver) return;
    const resolve = this.questionResolver;
    this.questionResolver = null;
    resolve(endChosen);
  }

  header({ counter = null, minimizable = false } = {}) {
    const head = this.node("header", "ft-head");
    const orb = this.node("span", "ft-orb");
    orb.innerHTML = SPARK;
    head.append(orb, this.node("strong", "ft-brand", "Finora Tutor"));
    head.appendChild(this.node("span", "ft-spacer"));
    if (counter) head.appendChild(this.node("span", "ft-count", counter));
    if (minimizable) {
      head.appendChild(this.button("pause", "إيقاف مؤقت", { icon: ICON_PAUSE, title: "إيقاف مؤقت" }));
      head.appendChild(this.button("minimize", "تصغير", { icon: ICON_MIN, title: "تصغير" }));
    }
    return head;
  }

  progress(view) {
    const wrap = this.node("div", "ft-progress");
    const line = this.node("div", "ft-progress__line");
    const bar = this.node("i");
    bar.style.width = `${Math.round((view.stepNumber / view.totalSteps) * 100)}%`;
    line.appendChild(bar);
    wrap.appendChild(line);
    if (view.totalSteps <= 8) {
      const dots = this.node("div", "ft-dots");
      for (let i = 1; i <= view.totalSteps; i += 1) dots.appendChild(this.node("i", i <= view.stepNumber ? "is-done" : ""));
      wrap.appendChild(dots);
    }
    return wrap;
  }

  // ---- content renderers (no animation: the presenter sequences them) -----

  renderStep(view) {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.el.classList.remove("is-min");
    this.setState(view.kind === "information" ? "information" : "instruction");
    this.el.dataset.tutorKind = "step";
    this.el.dataset.tutorMode = view.mode;
    const inner = this.inner;
    const withProgress = view.showProgress !== false;
    inner.appendChild(this.header({ counter: withProgress ? `${view.stepNumber} / ${view.totalSteps}` : null, minimizable: withProgress }));
    if (withProgress) inner.appendChild(this.progress(view));
    if (view.chip) inner.appendChild(this.node("span", "ft-chip", view.chip));
    inner.appendChild(this.node("h3", "ft-title", view.tutorialTitle));
    inner.appendChild(this.node("p", "ft-message", view.message));
    if (view.review) inner.appendChild(this.node("p", "ft-hint", "مراجعة لخطوة سابقة — لن يتغير شيء من بياناتك."));
    this.noticeEl = this.node("p", "ft-notice");
    this.noticeEl.setAttribute("role", "alert");
    this.noticeEl.hidden = true;
    inner.appendChild(this.noticeEl);
    if (!view.nextVisible && view.hint) inner.appendChild(this.node("p", "ft-hint", view.hint));

    const row = this.node("footer", "ft-actions");
    this.nextBtn = null;
    if (view.mode === "navigate") row.appendChild(this.button("goto", "افتح الصفحة", { primary: true }));
    if (view.nextVisible) {
      this.nextBtn = this.button("next", view.nextLabel || "التالي", { primary: true, disabled: !view.nextEnabled });
      row.appendChild(this.nextBtn);
    }
    if (view.canBack) row.appendChild(this.button("back", "السابق"));
    row.appendChild(this.node("span", "ft-spacer"));
    row.appendChild(this.button("cancel", view.nextVisible ? "إنهاء" : "إنهاء التعليم"));
    inner.appendChild(row);
    this.applyPatch(view);
  }

  applyPatch(patch) {
    if (patch.nextEnabled !== undefined && this.nextBtn) this.nextBtn.disabled = !patch.nextEnabled;
    if (patch.notice !== undefined && this.noticeEl) {
      this.noticeEl.hidden = !patch.notice;
      this.noticeEl.textContent = patch.notice ? patch.notice.text : "";
    }
  }

  renderLoading(text) {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.el.classList.remove("is-min");
    this.setState("loading");
    this.el.dataset.tutorKind = "loading";
    const row = this.node("div", "ft-loading");
    const orb = this.node("span", "ft-orb");
    orb.innerHTML = SPARK;
    const dots = this.node("span", "ft-loading__dots");
    dots.append(this.node("i"), this.node("i"), this.node("i"));
    row.append(orb, this.node("span", "ft-loading__text", text), dots);
    this.inner.appendChild(row);
  }

  renderSuccessFlash(text) {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.setState("success");
    this.el.dataset.tutorKind = "success";
    const row = this.node("div", "ft-loading ft-flash");
    const check = this.node("span", "ft-check-badge");
    check.innerHTML = CHECK;
    row.append(check, this.node("span", "ft-loading__text", text));
    this.inner.appendChild(row);
  }

  renderRecovery({ message, actions, kind = "warning" }) {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.el.classList.remove("is-min");
    this.setState(kind);
    this.el.dataset.tutorKind = "recovery";
    this.inner.appendChild(this.header());
    this.inner.appendChild(this.node("p", "ft-message", message));
    const row = this.node("footer", "ft-actions");
    actions.forEach((a, i) => row.appendChild(this.button(a.id, a.label, { primary: i === 0 })));
    this.inner.appendChild(row);
  }

  renderResult({ kind, title, message, suggestion = null, actions = null }) {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.el.classList.remove("is-min");
    this.setState(kind === "success" ? "success" : "error");
    this.el.dataset.tutorKind = kind === "success" ? "success" : "error";
    this.inner.appendChild(this.header());
    if (kind === "success") {
      const badge = this.node("div", "ft-result-badge");
      badge.innerHTML = CHECK;
      this.inner.appendChild(badge);
    }
    this.inner.appendChild(this.node("h3", "ft-title ft-title--center", title));
    this.inner.appendChild(this.node("p", "ft-message ft-message--center", message));
    if (suggestion) this.inner.appendChild(this.node("p", "ft-suggestion", `التالي المقترح: ${suggestion}`));
    const row = this.node("footer", "ft-actions ft-actions--center");
    (actions || [{ id: "end", label: "إغلاق" }]).forEach((a, i) => row.appendChild(this.button(a.id, a.label, { primary: i === 0 })));
    this.inner.appendChild(row);
  }

  renderMinimized(view) {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.el.classList.add("is-min");
    this.setState("information");
    this.el.dataset.tutorKind = "minimized";
    const row = this.node("div", "ft-minrow");
    const orb = this.node("span", "ft-orb");
    orb.innerHTML = SPARK;
    row.append(orb, this.node("span", "ft-minrow__text", `التعليم  ${view.stepNumber}/${view.totalSteps}`),
      this.button("expand", "فتح", { icon: ICON_MIN, title: "فتح بطاقة التعليم" }));
    this.inner.appendChild(row);
  }

  renderPaused() {
    this.shownToken += 1;
    this.inner.replaceChildren();
    this.el.classList.add("is-min");
    this.setState("paused");
    this.el.dataset.tutorKind = "paused";
    const row = this.node("div", "ft-minrow");
    const orb = this.node("span", "ft-orb");
    orb.innerHTML = SPARK;
    row.append(orb, this.node("span", "ft-minrow__text", "التعليم متوقف"), this.button("resume", "متابعة", { primary: true }));
    this.inner.appendChild(row);
  }

  /** In-card yes/no question (e.g. exit confirmation). Resolves true when the destructive choice is made. */
  ask({ title, message, confirmLabel, continueLabel }) {
    const saved = [...this.inner.childNodes];
    const savedState = this.el.dataset.state;
    const savedKind = this.el.dataset.tutorKind;
    this.inner.replaceChildren();
    this.setState("question");
    this.el.dataset.tutorKind = "question";
    this.inner.appendChild(this.header());
    this.inner.appendChild(this.node("h3", "ft-title", title));
    this.inner.appendChild(this.node("p", "ft-message", message));
    const row = this.node("footer", "ft-actions");
    row.append(this.button("confirm-continue", continueLabel, { primary: true }), this.node("span", "ft-spacer"), this.button("confirm-end", confirmLabel));
    this.inner.appendChild(row);
    this.el.hidden = false;
    return new Promise((resolve) => {
      this.questionResolver = (endChosen) => {
        if (!endChosen) {
          this.inner.replaceChildren(...saved);
          this.setState(savedState);
          this.el.dataset.tutorKind = savedKind;
        }
        resolve(endChosen);
      };
    });
  }

  // ---- motion --------------------------------------------------------------

  size() {
    return { width: this.el.offsetWidth, height: this.el.offsetHeight };
  }

  async fadeOutContent() {
    this.el.classList.add("is-transitioning");
    await animate(this.inner, [{ opacity: 1 }, { opacity: 0 }], this.motion.ms("contentOut"));
    this.inner.style.opacity = "0";
  }

  async fadeInContent() {
    this.inner.style.opacity = "";
    await animate(this.inner, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "translateY(0)" }], this.motion.ms("contentIn"));
  }

  async animateHeight(from, to) {
    if (Math.abs(from - to) < 2) return;
    this.el.style.overflow = "hidden";
    await animate(this.el, [{ height: `${from}px` }, { height: `${to}px` }], this.motion.ms("heightChange"));
    this.el.style.overflow = "";
  }

  setSheet(isSheet) {
    this.sheet = isSheet;
    this.el.classList.toggle("is-sheet", isSheet);
    if (isSheet) {
      this.el.style.transform = "";
      this.pos = null;
    }
  }

  place(x, y) {
    this.pos = { x, y };
    this.el.style.transform = `translate3d(${x}px, ${y}px, 0)`;
  }

  /** Slide the same element to a new position (never remounts). */
  async moveTo(x, y, { animateMove = true, from = null } = {}) {
    const start = from || this.pos;
    this.place(x, y);
    if (!animateMove || !start) return;
    await animate(this.el, [
      { transform: `translate3d(${start.x}px, ${start.y}px, 0)` },
      { transform: `translate3d(${x}px, ${y}px, 0)` },
    ], this.motion.ms("move"));
  }

  async intro() {
    this.el.hidden = false;
    this.visible = true;
    const dy = "8px";
    const base = this.pos ? `translate3d(${this.pos.x}px, ${this.pos.y}px, 0)` : "";
    if (this.sheet) {
      const from = this.el.dataset.tutorEdge === "top" ? "translateY(-100%)" : "translateY(100%)";
      await animate(this.el, [{ transform: from }, { transform: "translateY(0)" }], this.motion.ms("sheet"));
    } else {
      await animate(this.el, [
        { opacity: 0, transform: `${base} translateY(${dy}) scale(.96)` },
        { opacity: 1, transform: `${base} translateY(0) scale(1)` },
      ], this.motion.ms("intro"));
    }
  }

  async exit() {
    if (!this.visible) return;
    const token = ++this.shownToken;
    await animate(this.el, [{ opacity: 1 }, { opacity: 0 }], this.motion.ms("exit"));
    if (token !== this.shownToken) return;
    this.el.hidden = true;
    this.visible = false;
  }

  async shake() {
    if (this.sheet || !this.pos) return;
    const t = (dx) => `translate3d(${this.pos.x + dx}px, ${this.pos.y}px, 0)`;
    await animate(this.el, [{ transform: t(0) }, { transform: t(4) }, { transform: t(-3) }, { transform: t(0) }], this.motion.ms("shake"), "ease-in-out");
  }

  hide() {
    this.el.hidden = true;
    this.visible = false;
  }
}
