/*
 * TutorEngine — UI-agnostic tutorial runtime.
 *
 * It only talks to a `presenter` port (see ui/presenter.js for the contract), so
 * TutorCard / TutorOverlay / TutorSpotlight / TutorPositioner / MotionController
 * can be replaced later without touching this file.
 */
import { FeatureDisabledError } from "./api.js";
import { factMet, nextStepIndex, previousTeachingIndex, recoveryAnchorIndex, REVIEWABLE_TYPES, routeForPage } from "./core.js";
import { STATES, TutorStateMachine } from "./machine.js";
import { acquireTarget, currentPage, exists, resolve, waitForTarget } from "./targets.js";
import { FetchObserver, waitApiSuccess, waitClick, waitState, watchCondition } from "./waiters.js";

const MARKER_KEY = "finora.tutor.resume";
const HALT = Symbol("halt");
const HALT_LOST = Symbol("target-lost");
const NON_COUNTED = new Set(["branch", "error"]);
const WRONG_CLICK_SELECTOR = "a[href], button, [role=button], input, select, textarea, label";

const isAbort = (error) => error?.name === "AbortError";

export class TutorEngine {
  constructor({ api, presenter, root = document, win = window, storage = null }) {
    this.api = api;
    this.presenter = presenter;
    this.root = root;
    this.win = win;
    this.storage = storage ?? (() => { try { return win.sessionStorage; } catch (_) { return null; } })();
    this.machine = new TutorStateMachine();
    this.observer = new FetchObserver(win);
    this.tutorial = null;
    this.controller = null;
    this.pending = new Map();
    this.stepCtl = null;
    this.currentIndex = 0;
    this.frontier = 0; // furthest step reached; anything before it is shown in review mode
    this.navRequest = null;
    this.issue = null; // 'target_missing' | 'validation_failed' | 'dependency_missing' (chat context only)
    this.currentTargetEl = null;
    this.disabled = false;
    this.presenter.setHandler((action) => this.onAction(action));
  }

  get state() {
    return this.machine.state;
  }

  isBusy() {
    return ![STATES.IDLE, STATES.COMPLETED, STATES.FAILED, STATES.CANCELLED].includes(this.machine.state);
  }

  /** Small, patient-data-free description of the running lesson for the chat context. */
  describeState() {
    if (!this.tutorial || !this.isBusy()) return null;
    const step = this.tutorial.steps[Math.min(this.currentIndex, this.tutorial.steps.length - 1)];
    return { tutorial_id: this.tutorial.id, step_id: step.id, issue: this.issue };
  }

  // ---- entry points -------------------------------------------------------

  /** Called on every page load: resume an in-progress tutorial, if any. */
  async boot() {
    const { active } = await this.api.active();
    if (!active) return false;
    const marker = this.readMarker(active.tutorial);
    const index = marker && marker.index > active.progress.step_index ? marker.index : active.progress.step_index;
    await this.begin(active.tutorial, index);
    return true;
  }

  async startTutorial(tutorialId) {
    if (this.machine.isTerminal()) this.machine.send("reset");
    if (this.machine.state !== STATES.IDLE) throw new Error("A tutorial is already running");
    const { tutorial } = await this.api.start(tutorialId);
    this.clearMarker();
    await this.begin(tutorial, 0);
  }

  /** Continue a tutorial the user paused/exited earlier ("متابعة" in Tutor Home). */
  async resumeTutorial(tutorialId) {
    if (this.machine.isTerminal()) this.machine.send("reset");
    if (this.machine.state !== STATES.IDLE) throw new Error("A tutorial is already running");
    const { tutorial, progress } = await this.api.resume(tutorialId);
    this.clearMarker();
    await this.begin(tutorial, progress.step_index);
  }

  async begin(tutorial, index) {
    if (this.machine.isTerminal()) this.machine.send("reset");
    this.frontier = index;
    this.tutorial = tutorial;
    this.controller = new AbortController();
    this.machine.send("start");
    this.observer.install();
    this.machine.send("ready");
    this.running = this.run(index);
    return this.running;
  }

  // ---- main loop -----------------------------------------------------------

  async run(startIndex) {
    const steps = this.tutorial.steps;
    let index = startIndex;
    try {
      if (!(await this.satisfyDependencies())) return;
      index = await this.reconcileTutorialState(index);
      while (index !== null && index !== HALT && !this.machine.isTerminal()) {
        const step = steps[index];
        this.frontier = Math.max(this.frontier, index);
        const outcome = await this.runStep(step, index);
        if (outcome === HALT) return;
        const next = outcome.next;
        if (next !== null && !outcome.persisted) {
          await this.persist(step, next);
        }
        index = next;
      }
    } catch (error) {
      if (isAbort(error) || error instanceof FeatureDisabledError) return;
      await this.fail(error.message || String(error));
    }
  }

  stepSignal() {
    return this.stepCtl ? this.stepCtl.signal : this.controller.signal;
  }

  /** Runs one step under its own AbortController so "Back" can interrupt it cleanly. */
  async runStep(step, index) {
    const ctl = new AbortController();
    const forward = () => ctl.abort();
    this.controller.signal.addEventListener("abort", forward, { once: true });
    this.stepCtl = ctl;
    this.currentIndex = index;
    this.currentStepRef = { tutorial: this.tutorial.id, step: step.id }; // atomic with the index: lets tests/diagnostics detect a stale read while lessons switch
    try {
      return await this.executeStep(step, index);
    } catch (error) {
      if (isAbort(error) && this.navRequest !== null) {
        const to = this.navRequest;
        this.navRequest = null;
        if (this.machine.state === STATES.WAITING_FOR_USER) this.machine.send("satisfied");
        else if (this.machine.state === STATES.VALIDATING) this.machine.send("valid");
        return { next: to, persisted: true };
      }
      throw error;
    } finally {
      ctl.abort();
      this.stepCtl = null;
      this.controller.signal.removeEventListener("abort", forward);
    }
  }

  // ---- reconciliation (never trust the saved step blindly) -----------------

  /**
   * Compare the saved step with the REAL current state before showing it. A step may be skipped only
   * when the step declares how to prove it is already done:
   *   kind "ui"       a UI fact that is safe to infer (page open, modal visible)
   *   kind "backend"  a server-side validator (anything irreversible, e.g. "doctor saved")
   * Steps without a `reconcile` block are never auto-skipped (user input is never assumed).
   */
  async reconcileTutorialState(startIndex) {
    const steps = this.tutorial.steps;
    let index = startIndex;
    while (index !== null && index + 1 < steps.length) {
      const step = steps[index];
      if (!(await this.isAlreadySatisfied(step))) break;
      const next = index + 1;
      this.frontier = Math.max(this.frontier, next);
      await this.persist(step, next);
      index = next;
    }
    return index;
  }

  async isAlreadySatisfied(step) {
    const rec = step.reconcile;
    if (!rec) return false;
    if (rec.kind === "ui") return this.uiPredicate(rec.when);
    const { verified } = await this.api.verify(this.tutorial.id, rec.validator);
    return Boolean(verified);
  }

  uiPredicate(when) {
    if (when.page) return currentPage(this.root) === when.page;
    if (when.visible) return exists(when.visible, this.root);
    return false;
  }

  // ---- dependency tutorials (resume the parent afterwards) -----------------

  async satisfyDependencies() {
    const deps = this.tutorial.dependencies || [];
    if (!deps.length) return true;
    const { facts } = await this.api.facts();
    const unmet = deps.find((dep) => !factMet(dep.fact, facts));
    if (!unmet) return true;
    this.issue = "dependency_missing";
    const choice = await this.askRecovery(unmet.message_ar, [
      { id: "dependency_start", label: unmet.action_label_ar },
      { id: "end", label: "إيقاف التعليم" },
    ], async (action) => action, "question");
    if (choice === "end") {
      await this.endWithoutConfirm();
      return false;
    }
    const parent = { tutorial_id: this.tutorial.id, step_id: this.tutorial.steps[0].id };
    const { tutorial } = await this.api.start(unmet.tutorial, { parent });
    await this.switchTo(tutorial, 0);
    return false;
  }

  /** Replace the running tutorial with another one (child/parent) without closing the UI. */
  async switchTo(tutorial, index) {
    this.clearMarker();
    this.controller.abort();
    this.pending.clear();
    this.observer.uninstall();
    if (!this.machine.isTerminal()) this.machine.send("cancel");
    this.machine.send("reset");
    await this.begin(tutorial, index);
  }

  async executeStep(step, index) {
    if (step.page && step.type !== "navigate" && currentPage(this.root) !== step.page) {
      return this.pageMismatch(step, index);
    }
    const signal = this.stepSignal();
    this.issue = null;
    if (index < this.frontier) {
      // The user pressed "Back": earlier steps are re-shown for explanation only, never re-executed.
      if (REVIEWABLE_TYPES.has(step.type)) return this.stepReview(step, index);
      if (step.type === "navigate" || step.type === "wait_modal" || step.type === "wait_state") return { next: index + 1, persisted: true };
    }
    switch (step.type) {
      case "navigate":
        return this.stepNavigate(step, index);
      case "highlight":
      case "explain":
        return this.stepInfo(step, index);
      case "wait_click":
        return this.stepWaitClick(step, index);
      case "wait_input":
      case "wait_select":
        return this.stepWaitCondition(step, index);
      case "wait_modal":
        return this.stepWaitModal(step, index, signal);
      case "branch":
        return { next: nextStepIndex(this.tutorial.steps, index, exists(step.if.exists, this.root) ? step.then : step.else) };
      case "wait_api_success":
        return this.stepWaitApi(step, index);
      case "wait_state":
        return this.stepWaitState(step, index, signal);
      case "complete":
        return this.stepComplete(step, index);
      case "error":
        return this.stepError(step);
      default:
        throw new Error(`Unsupported step type: ${step.type}`);
    }
  }

  // ---- step implementations ------------------------------------------------

  view(step, index, extra = {}) {
    const steps = this.tutorial.steps;
    const counted = steps.filter((s) => !NON_COUNTED.has(s.type));
    return {
      tutorialTitle: this.tutorial.title_ar,
      stepId: step.id,
      stepNumber: Math.max(1, counted.indexOf(step) + 1),
      totalSteps: counted.length,
      message: step.message_ar || "",
      chip: this.tutorial.chip_ar || null,
      kind: "instruction",
      nextLabel: "التالي",
      canBack: this.backTarget(index) !== null,
      review: false,
      mode: "info",
      target: null,
      nextVisible: false,
      nextEnabled: false,
      notice: null,
      ...extra,
    };
  }

  async withTarget(step, index, body) {
    const target = await acquireTarget(step.target, { reveal: step.reveal, signal: this.stepSignal(), root: this.root });
    if (!target) return this.targetMissing(step, index);
    // Per-step controller: cancelling it detaches every listener the step registered.
    const stepAbort = new AbortController();
    const parentSignal = this.stepSignal();
    const forward = () => stepAbort.abort();
    parentSignal.addEventListener("abort", forward, { once: true });
    const lost = this.targetLostWatcher(step.target);
    this.currentTargetEl = target;
    const work = body(target, stepAbort.signal);
    work.catch((error) => {
      if (!isAbort(error)) console.warn("[tutor] step error", error);
    });
    try {
      return await Promise.race([work, lost.promise]);
    } finally {
      lost.stop();
      stepAbort.abort();
      parentSignal.removeEventListener("abort", forward);
    }
  }

  targetLostWatcher(ref) {
    let timer = null;
    let misses = 0;
    const promise = new Promise((resolveLost) => {
      timer = setInterval(() => {
        misses = resolve(ref, this.root) ? 0 : misses + 1;
        if (misses >= 4) resolveLost(HALT_LOST);
      }, 400);
    });
    return { promise, stop: () => clearInterval(timer) };
  }

  async stepInfo(step, index) {
    const body = async (target, signal) => {
      this.machine.send("await");
      this.presenter.present(this.view(step, index, { mode: "info", kind: "information", nextLabel: "فهمت", target, nextVisible: true, nextEnabled: true }));
      await this.awaitAction(["next"], signal);
      this.machine.send("satisfied");
      return { next: index + 1 };
    };
    return this.guardLost(step, index, step.target ? await this.withTarget(step, index, body) : await body(null, this.stepSignal()));
  }

  async stepWaitClick(step, index) {
    return this.guardLost(step, index, await this.withTarget(step, index, async (target, signal) => {
      this.machine.send("await");
      this.presenter.present(this.view(step, index, { mode: "click", target, hint: "اضغط على العنصر المحدد للمتابعة." }));
      const stopWrongClicks = this.watchWrongClicks(step, signal);
      try {
        await waitClick(step.target, { signal, root: this.root });
      } finally {
        stopWrongClicks();
      }
      const next = index + 1;
      // The click may navigate: store the next step synchronously and fire the save with keepalive.
      this.writeMarker(step, next);
      this.persist(step, next, { keepalive: true }).catch((error) => this.reportError(error));
      if (step.nav_message_ar && typeof this.presenter.showNavigating === "function") this.presenter.showNavigating(step.nav_message_ar);
      this.machine.send("satisfied");
      return { next, persisted: true };
    }));
  }

  async stepWaitCondition(step, index) {
    return this.guardLost(step, index, await this.withTarget(step, index, async (target, signal) => {
      this.machine.send("await");
      this.presenter.present(this.view(step, index, { mode: step.type === "wait_input" ? "input" : "select", target, nextVisible: true, nextEnabled: false, hint: "أكمل الحقل المحدد ثم اضغط التالي." }));
      const stop = watchCondition({
        target: step.target,
        watch: step.watch,
        condition: step.condition,
        onChange: (ok) => this.presenter.update({ nextEnabled: ok }),
        signal,
        root: this.root,
      });
      try {
        await this.awaitAction(["next"], signal);
      } finally {
        stop();
      }
      this.machine.send("satisfied");
      return { next: index + 1 };
    }));
  }

  async stepWaitModal(step, index, signal) {
    this.machine.send("await");
    this.presenter.present(this.view(step, index, { mode: "wait" }));
    const target = await waitForTarget(step.target, { timeoutMs: 8000, signal, root: this.root });
    if (!target) return this.targetMissing(step, index);
    this.machine.send("satisfied");
    return { next: index + 1 };
  }

  async stepWaitApi(step, index) {
    const outcome = await this.withTarget(step, index, async (target, signal) => {
      this.machine.send("await");
      this.presenter.present(this.view(step, index, { mode: "api", target }));
      await waitApiSuccess(this.observer, step.match, {
        signal,
        onFailure: (event) => this.noteIssue("validation_failed") || this.presenter.update({
          notice: { kind: "error", text: `لم يتم الحفظ: ${event.error || "حدث خطأ"}. صحّح البيانات ثم اضغط حفظ مرة أخرى.` },
        }),
      });
      this.presenter.update({ notice: null });
      this.machine.send("satisfied");
      return { next: index + 1 };
    });
    // The success flash is purely cosmetic and must never race the target-lost watcher: by the time we get here,
    // waitApiSuccess already matched the real backend response, so the save itself is done regardless of whether
    // the real page's target (e.g. a modal's Save button) still exists. Flashing it INSIDE withTarget's raced body
    // let a slow page refresh (observed with payment.record: the backend also posts a journal entry, and the
    // billing list re-fetches before the modal closes) make the 1.6s target-lost window fire first, failing a
    // tutorial whose save had already succeeded.
    if (outcome !== HALT_LOST && step.success_ar && typeof this.presenter.flashSuccess === "function") {
      await this.presenter.flashSuccess(step.success_ar);
    }
    return this.guardLost(step, index, outcome);
  }

  async stepWaitState(step, index, signal) {
    this.machine.send("validate");
    this.presenter.present(this.view(step, index, { mode: "wait" }));
    const ok = await waitState(async () => (await this.api.verify(this.tutorial.id, step.validator)).verified, { signal });
    if (ok) {
      this.machine.send("valid");
      return { next: index + 1 };
    }
    this.machine.send("invalid");
    // A step may override the wording for an operation where blindly retrying could duplicate a real-world effect
    // (e.g. payment.record): "retry" here only re-checks the backend, it never re-submits anything by itself.
    return this.askRecovery(step.recovery_message_ar || "لم نتمكن من التأكد من نجاح العملية في النظام.", [
      { id: "retry", label: step.recovery_retry_label_ar || "إعادة المحاولة" },
      { id: "end", label: "إنهاء التعليم" },
    ], async (action) => (action === "retry" ? { next: index } : this.endWithoutConfirm()));
  }

  async stepComplete(step) {
    this.presenter.present(this.view(step, 0, { mode: "wait" }));
    const result = await this.api.complete(this.tutorial.id);
    this.machine.send("finish");
    this.clearMarker();
    if (result.parent) {
      // Dependency done: confirm briefly, then return to the parent tutorial at the saved point.
      await this.presenter.flashSuccess(step.message_ar);
      const resumed = await this.api.resume(result.parent.tutorial_id, { step_id: result.parent.step_id });
      await this.switchTo(resumed.tutorial, resumed.progress.step_index);
      return HALT;
    }
    // Recommended next lessons come from the registry graph (server-filtered); they only start when the user asks.
    const lessons = Array.isArray(result.next_lessons) ? result.next_lessons : [];
    this.presenter.showResult({
      kind: "success",
      title: `اكتمل الدرس: ${this.tutorial.title_ar}`,
      message: step.message_ar,
      suggestion: lessons.length ? lessons.map((l) => l.title_ar).join(" · ") : null,
      actions: [
        ...lessons.map((l) => ({ id: `lesson:${l.id}`, label: `ابدأ: ${l.title_ar}` })),
        { id: "end", label: "إغلاق" },
      ],
    });
    const choice = await this.awaitAction(["end", ...lessons.map((l) => `lesson:${l.id}`)], this.controller.signal);
    this.teardown();
    if (choice.startsWith("lesson:")) {
      try {
        await this.startTutorial(choice.slice("lesson:".length));
      } catch (error) {
        console.warn("[tutor] could not start the recommended lesson", error);
      }
    }
    return HALT;
  }

  /** Review of an earlier step (semantic Back): explanation only, nothing is executed or undone. */
  async stepReview(step, index) {
    const body = async (target, signal) => {
      this.machine.send("await");
      this.presenter.present(this.view(step, index, {
        mode: "info", kind: "information", nextLabel: "فهمت", target, nextVisible: true, nextEnabled: true, review: true,
      }));
      await this.awaitAction(["next"], signal);
      this.machine.send("satisfied");
      return { next: index + 1, persisted: true };
    };
    if (!step.target) return body(null, this.stepSignal());
    const target = await acquireTarget(step.target, { reveal: step.reveal, signal: this.stepSignal(), root: this.root });
    if (!target) return { next: index + 1, persisted: true }; // cannot be shown here: skip quietly
    return this.guardLost(step, index, await this.withTarget(step, index, body));
  }

  backTarget(index) {
    return previousTeachingIndex(this.tutorial.steps, index, currentPage(this.root));
  }

  watchWrongClicks(step, signal) {
    const selector = Object.entries(step.target).length ? this.targetSelector(step.target) : null;
    const handler = (event) => {
      const node = event.target instanceof Element ? event.target : null;
      if (!node || node.closest("[data-tutor-ui]") || !node.closest(WRONG_CLICK_SELECTOR) || (selector && node.closest(selector))) return;
      if (typeof this.presenter.shake === "function") this.presenter.shake(step.wrong_ar || "مو هذا الزر، اضغط على العنصر المحدد.");
    };
    this.root.addEventListener("click", handler, true);
    const stop = () => this.root.removeEventListener("click", handler, true);
    signal.addEventListener("abort", stop, { once: true });
    return stop;
  }

  targetSelector(ref) {
    const [kind, id] = Object.entries(ref)[0];
    return `[data-finora-${kind}="${id}"]`;
  }

  async stepError(step) {
    await this.api.progress(this.tutorial.id, { event: "step_failed", step_id: step.id, detail: "tutorial_error_step" });
    return this.failWith(step.message_ar);
  }

  // ---- navigation & recovery ----------------------------------------------

  async stepNavigate(step, index) {
    if (currentPage(this.root) === step.page) return { next: index + 1 };
    this.machine.send("await");
    this.presenter.present(this.view(step, index, { mode: "navigate" }));
    const action = await Promise.race([
      this.awaitAction(["goto"]),
      this.waitForPage(step.page),
    ]);
    if (action === "goto") {
      this.win.location.assign(step.route);
      return HALT;
    }
    this.machine.send("satisfied");
    return { next: index + 1 };
  }

  waitForPage(page) {
    return new Promise((resolvePage) => {
      const timer = setInterval(() => {
        if (currentPage(this.root) === page) {
          clearInterval(timer);
          resolvePage("arrived");
        }
      }, 300);
      this.stepSignal().addEventListener("abort", () => clearInterval(timer), { once: true });
    });
  }

  async pageMismatch(step, index) {
    this.machine.send("pause");
    return this.askRecovery("ابتعدت عن خطوة التعليم الحالية.", [
      { id: "return", label: "العودة للخطوة" },
      { id: "end", label: "إنهاء التعليم" },
    ], async (action) => {
      if (action === "end") return this.endWithoutConfirm();
      const route = routeForPage(this.tutorial.steps, index, step.page);
      if (!route) return this.endWithoutConfirm();
      this.win.location.assign(route);
      return HALT;
    });
  }

  guardLost(step, index, outcome) {
    return outcome === HALT_LOST ? this.targetMissing(step, index) : outcome;
  }

  async targetMissing(step, index) {
    const ref = step.target ? Object.entries(step.target)[0].join(":") : step.id;
    this.issue = "target_missing";
    await this.api.progress(this.tutorial.id, { event: "target_missing", step_id: step.id, detail: ref });
    if (this.machine.state === STATES.WAITING_FOR_USER || this.machine.state === STATES.RUNNING) {
      this.machine.send("pause");
    }
    const anchor = recoveryAnchorIndex(this.tutorial.steps, index);
    const actions = [];
    if (anchor !== null) actions.push({ id: "rewind", label: "العودة للخطوة السابقة" });
    actions.push({ id: "end", label: "إنهاء التعليم" });
    return this.askRecovery("تعذر العثور على العنصر المطلوب في هذه النسخة.", actions, async (action) => {
      if (action !== "rewind") return this.endWithoutConfirm();
      const anchorStep = this.tutorial.steps[anchor];
      await this.api.progress(this.tutorial.id, { event: "rewind", step_id: anchorStep.id });
      this.writeMarker(anchorStep, anchor, true);
      this.frontier = anchor; // recovery re-does the step; it is not a review
      this.machine.send("resume");
      return { next: anchor, persisted: true };
    });
  }

  async askRecovery(message, actions, onChoice, kind = "warning") {
    this.presenter.showRecovery({ message, actions, kind });
    const choice = await this.awaitAction(actions.map((a) => a.id), this.controller.signal);
    return onChoice(choice);
  }

  async fail(message) {
    try {
      await this.api.progress(this.tutorial.id, { event: "step_failed", step_id: this.tutorial.steps[0].id, detail: "engine_error" });
    } catch (error) {
      if (!(error instanceof FeatureDisabledError)) console.warn("[tutor] could not record failure", error);
    }
    return this.failWith(`تعذر متابعة الدرس: ${message}`);
  }

  async failWith(message) {
    if (!this.machine.isTerminal()) this.machine.send("fail");
    this.presenter.showResult({ kind: "error", title: this.tutorial.title_ar, message });
    await this.awaitAction(["end"]);
    this.teardown();
    return HALT;
  }

  // ---- user actions --------------------------------------------------------

  awaitAction(ids, signal = this.stepSignal()) {
    return new Promise((resolveAction, reject) => {
      const entry = { ids };
      const cleanup = () => {
        signal.removeEventListener("abort", onAbort);
        this.pending.delete(entry);
      };
      const onAbort = () => {
        cleanup();
        reject(new DOMException("aborted", "AbortError"));
      };
      entry.resolve = (id) => {
        cleanup();
        resolveAction(id);
      };
      this.pending.set(entry, true);
      if (signal.aborted) return onAbort();
      signal.addEventListener("abort", onAbort, { once: true });
      return undefined;
    });
  }

  onAction(action) {
    if (action === "cancel") return void this.requestCancel();
    if (action === "back") return void this.requestBack();
    for (const entry of [...this.pending.keys()]) {
      if (entry.ids.includes(action)) return void entry.resolve(action);
    }
    return undefined;
  }

  requestBack() {
    const to = this.backTarget(this.currentIndex);
    if (to === null || !this.stepCtl) return;
    this.navRequest = to;
    this.stepCtl.abort();
  }

  /** User exit: the place is saved (status "paused") and can be continued from Tutor Home. */
  async requestCancel() {
    if (!this.tutorial || this.machine.isTerminal() || this.machine.state === STATES.IDLE) return;
    if (!(await this.presenter.confirm("راح نحفظ مكانك وتكدر ترجعله لاحقاً."))) return;
    await this.exitKeepingProgress();
  }

  async exitKeepingProgress() {
    try {
      const step = this.tutorial.steps[Math.min(this.currentIndex, this.tutorial.steps.length - 1)];
      await this.api.progress(this.tutorial.id, { event: "paused", step_id: step.id, detail: "user_exit" });
    } catch (error) {
      if (!(error instanceof FeatureDisabledError)) console.warn("[tutor] could not save place on exit", error);
    }
    if (!this.machine.isTerminal()) this.machine.send("cancel");
    this.clearMarker();
    this.teardown();
  }

  async endWithoutConfirm() {
    try {
      if (this.tutorial) {
        await this.api.progress(this.tutorial.id, { event: "abandoned", step_id: this.tutorial.steps[0].id });
      }
    } catch (error) {
      if (!(error instanceof FeatureDisabledError)) console.warn("[tutor] could not record abandonment", error);
    }
    if (!this.machine.isTerminal()) this.machine.send("cancel");
    this.clearMarker();
    this.teardown();
    return HALT;
  }

  // ---- persistence ---------------------------------------------------------

  persist(step, nextIndex, opts = {}) {
    const nextStep = this.tutorial.steps[nextIndex];
    this.writeMarker(step, nextIndex);
    return this.api.progress(this.tutorial.id, { event: "step_completed", step_id: step.id, next_step_id: nextStep.id }, opts);
  }

  writeMarker(step, nextIndex, force = false) {
    if (!this.storage) return;
    const next = this.tutorial.steps[nextIndex];
    const previous = this.readMarker(this.tutorial);
    if (!force && previous && previous.index > nextIndex) return;
    this.storage.setItem(MARKER_KEY, JSON.stringify({
      tutorial_id: this.tutorial.id, version: this.tutorial.version, index: nextIndex, step_id: next.id, at: Date.now(),
    }));
  }

  readMarker(tutorial) {
    if (!this.storage) return null;
    try {
      const marker = JSON.parse(this.storage.getItem(MARKER_KEY) || "null");
      if (marker && marker.tutorial_id === tutorial.id && marker.version === tutorial.version
        && Number.isInteger(marker.index) && marker.index >= 0 && marker.index < tutorial.steps.length) return marker;
    } catch (error) {
      console.warn("[tutor] ignoring unreadable resume marker", error);
    }
    return null;
  }

  clearMarker() {
    this.storage?.removeItem(MARKER_KEY);
  }

  noteIssue(issue) {
    this.issue = issue;
    return false; // lets callers chain `|| doSomethingElse()`
  }

  reportError(error) {
    if (error instanceof FeatureDisabledError) return;
    this.presenter.update({ notice: { kind: "error", text: `تعذر حفظ التقدم: ${error.message}` } });
  }

  // ---- lifecycle -----------------------------------------------------------

  teardown() {
    this.controller?.abort();
    this.pending.clear();
    this.observer.uninstall();
    this.presenter.hide();
  }

  /** Feature switched off (server answered FEATURE_NOT_ENABLED): close everything now. */
  shutdown() {
    this.disabled = true;
    this.clearMarker();
    this.controller?.abort();
    this.pending.clear();
    this.observer.uninstall();
    this.presenter.destroy();
  }
}

