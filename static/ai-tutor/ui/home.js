/*
 * Tutor Home: small, system-focused. Quick actions, setup progress and suggested prompts all come from the
 * server registry (/knowledge); nothing about lessons is hard-coded here. The chat lives below them.
 */
import { animate } from "../motion/tokens.js";
import { TutorChat } from "./chat.js";

export class TutorHome {
  constructor({ overlay, engine, api, motion, showMe, win = window }) {
    this.engine = engine;
    this.api = api;
    this.motion = motion;
    this.win = win;
    const doc = overlay.doc;
    this.doc = doc;
    this.panel = doc.createElement("section");
    this.panel.className = "ft-home";
    this.panel.dataset.tutorUi = "home";
    this.panel.setAttribute("role", "dialog");
    this.panel.setAttribute("aria-label", "تعلّم النظام");
    this.panel.hidden = true;
    overlay.mount(this.panel);
    this.isOpen = false;
    this.token = 0; // guards late animation callbacks after a quick close/re-open
    this.chat = new TutorChat({ api, engine, showMe, home: this, doc, win });
  }

  node(tag, className, text) {
    const n = this.doc.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  isBusy() {
    return this.engine.isBusy();
  }

  async render() {
    const body = this.node("div", "ft-home__body");
    const head = this.node("header", "ft-home__head");
    head.append(this.node("strong", "", "تعلّم النظام"));
    const close = this.node("button", "ft-home__close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "إغلاق");
    close.addEventListener("click", () => this.close());
    head.append(close);
    this.panel.replaceChildren(head, body, this.chat.root);

    let knowledge;
    let tutorials;
    try {
      [knowledge, { tutorials }] = await Promise.all([this.api.knowledge(), this.api.list()]);
    } catch (error) {
      if (error.name === "FeatureDisabledError") return;
      body.append(this.node("p", "ft-home__empty", "تعذر تحميل الدروس حالياً."));
      return;
    }

    const busy = this.isBusy();
    if (busy) body.append(this.node("p", "ft-home__note", "هناك درس قيد التنفيذ الآن."));
    body.append(this.node("h3", "ft-home__ask", "شنو تريد تتعلم؟"));

    const status = new Map(tutorials.map((t) => [t.id, t.progress?.status]));
    if (!knowledge.quick_actions.length) {
      body.append(this.node("p", "ft-home__empty", "لا توجد دروس متاحة لحسابك حالياً."));
    } else {
      const list = this.node("div", "ft-home__list");
      knowledge.quick_actions.forEach((item) => {
        const row = this.node("button", "ft-home__item");
        row.type = "button";
        row.disabled = busy;
        row.dataset.tutorStart = item.tutorial_id;
        row.append(this.node("span", "ft-home__item-title", item.label));
        row.append(this.node("span", "ft-home__item-meta", status.get(item.tutorial_id) === "completed" ? "تم ✓" : "ابدأ"));
        row.addEventListener("click", async () => {
          await this.close();
          await this.engine.startTutorial(item.tutorial_id);
        });
        list.append(row);
      });
      body.append(list);
    }

    this.renderPlan(body, knowledge.plan);
    if (!this.chat.history.length) this.renderPrompts(body, knowledge.suggested_prompts); // suggestions only until the conversation starts

    const resumable = tutorials.find((t) => t.progress?.status === "paused");
    if (resumable && !busy) {
      const resume = this.node("button", "ft-btn ft-btn--primary ft-home__continue", `متابعة: ${resumable.title_ar}`);
      resume.type = "button";
      resume.dataset.tutorContinue = resumable.id;
      resume.addEventListener("click", async () => {
        await this.close();
        await this.engine.resumeTutorial(resumable.id);
      });
      body.append(resume);
    }
  }

  /** The curriculum comes from the lesson registry: one progress block per group, only lessons this user can run. */
  renderPlan(body, plan) {
    (plan.groups || []).forEach((group) => {
      const completed = group.items.filter((i) => i.state === "completed").length;
      const box = this.node("div", "ft-home__progress");
      box.dataset.tutorUi = "plan";
      box.dataset.tutorPlanGroup = group.id;
      box.append(this.node("span", "ft-home__plan-title", `${group.title_ar} — ${completed} من ${group.items.length}`));
      const line = this.node("div", "ft-progress__line");
      const bar = this.node("i");
      bar.style.width = `${group.items.length ? Math.round((completed / group.items.length) * 100) : 0}%`;
      line.append(bar);
      box.append(line);
      body.append(box);
    });
  }

  renderPrompts(body, prompts) {
    if (!prompts.length) return;
    const row = this.node("div", "ft-home__prompts");
    prompts.forEach((text) => {
      const chip = this.node("button", "ft-chipbtn", text);
      chip.type = "button";
      chip.dataset.tutorPrompt = "1";
      chip.addEventListener("click", () => this.chat.ask(text.replace(/[؟?]$/, "")));
      row.append(chip);
    });
    body.append(row);
  }

  async open() {
    this.isOpen = true;
    const token = ++this.token;
    await this.render();
    if (!this.isOpen || token !== this.token) return;
    this.panel.hidden = false;
    this.chat.log.scrollTop = this.chat.log.scrollHeight;
    await animate(this.panel, [
      { opacity: 0, transform: "translateY(10px) scale(.97)" },
      { opacity: 1, transform: "translateY(0) scale(1)" },
    ], this.motion.ms("normal"));
  }

  async close() {
    if (!this.isOpen) return;
    this.isOpen = false;
    const token = ++this.token;
    await animate(this.panel, [{ opacity: 1 }, { opacity: 0, transform: "translateY(6px)" }], this.motion.ms("fast"));
    if (token === this.token) this.panel.hidden = true;
  }

  toggle() {
    return this.isOpen ? this.close() : this.open();
  }

  destroy() {
    this.panel.remove();
  }
}
