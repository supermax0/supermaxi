/*
 * TutorChat: compact chat inside Tutor Home. The server returns structured, registry-only responses;
 * this component renders them as plain text + buttons and routes the buttons to the existing
 * engine / Show Me. It never builds HTML from model output and never sends page content.
 */
const HISTORY_KEY = "finora.tutor.chat";
const HISTORY_LIMIT = 20;
const MAX_INPUT = 300;
const DIGITS = /\d{5,}/g;

export class TutorChat {
  constructor({ api, engine, showMe, home, doc = document, win = window }) {
    this.api = api;
    this.engine = engine;
    this.showMe = showMe;
    this.home = home;
    this.doc = doc;
    this.win = win;
    this.pending = false;
    this.history = this.loadHistory();
    this.root = doc.createElement("section");
    this.root.className = "ft-chat";
    this.root.dataset.tutorUi = "chat";
    this.log = this.node("div", "ft-chat__log");
    this.log.setAttribute("role", "log");
    this.log.setAttribute("aria-live", "polite");
    this.log.dataset.tutorUi = "chat-log";
    this.form = this.node("form", "ft-chat__form");
    this.input = this.node("input", "ft-chat__input");
    this.input.type = "text";
    this.input.maxLength = MAX_INPUT;
    this.input.placeholder = "اسأل عن أي شي بالنظام…";
    this.input.setAttribute("aria-label", "اسأل Finora Tutor");
    this.input.dataset.tutorUi = "chat-input";
    this.input.autocomplete = "off";
    this.send = this.node("button", "ft-btn ft-btn--primary ft-chat__send", "إرسال");
    this.send.type = "submit";
    this.send.dataset.tutorUi = "chat-send";
    this.form.append(this.input, this.send);
    this.form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = this.input.value.trim();
      if (text) this.ask(text);
    });
    this.root.append(this.log, this.form);
    this.history.forEach((entry) => this.paint(entry, { restored: true }));
  }

  node(tag, className, text) {
    const n = this.doc.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // ---- history (session scoped, last 20, digits redacted, never page data) ----

  loadHistory() {
    try {
      const stored = JSON.parse(this.win.sessionStorage.getItem(HISTORY_KEY) || "[]");
      return Array.isArray(stored) ? stored.slice(-HISTORY_LIMIT) : [];
    } catch (error) {
      console.warn("[tutor] ignoring unreadable chat history", error);
      return [];
    }
  }

  remember(entry) {
    this.history.push({ ...entry, text: entry.text.replace(DIGITS, "[رقم]"), actions: [] });
    this.history = this.history.slice(-HISTORY_LIMIT);
    try {
      this.win.sessionStorage.setItem(HISTORY_KEY, JSON.stringify(this.history));
    } catch (error) {
      console.warn("[tutor] could not store chat history", error);
    }
  }

  // ---- rendering ----

  paint(entry, { restored = false } = {}) {
    const bubble = this.node("div", `ft-msg ft-msg--${entry.role}`);
    bubble.dataset.tutorMsg = entry.role;
    if (entry.type) bubble.dataset.tutorType = entry.type;
    bubble.append(this.node("p", "ft-msg__text", entry.text)); // textContent only: model text is never HTML
    if (!restored && entry.actions?.length) {
      const row = this.node("div", "ft-msg__actions");
      entry.actions.forEach((action) => row.append(this.actionButton(action, row)));
      bubble.append(row);
    }
    this.log.append(bubble);
    this.log.scrollTop = this.log.scrollHeight;
    return bubble;
  }

  actionButton(action, row) {
    const b = this.node("button", "ft-btn ft-msg__btn", action.label);
    b.type = "button";
    b.dataset.tutorChatAction = action.type;
    if (action.intent) b.dataset.intent = action.intent;
    if (action.tutorial_id) b.dataset.tutorId = action.tutorial_id;
    if (action.type === "start_tutorial") b.classList.add("ft-btn--primary");
    b.addEventListener("click", () => {
      row.querySelectorAll("button").forEach((x) => { x.disabled = true; });
      this.runAction(action);
    });
    return b;
  }

  say(role, text, extra = {}) {
    const entry = { role, text, ...extra };
    this.remember(entry);
    return this.paint(entry);
  }

  // ---- talking to the server ----

  context() {
    const page = this.doc.querySelector("[data-finora-page]")?.dataset.finoraPage || null;
    const active = this.engine.describeState();
    const out = { page, route: this.win.location.pathname, active: active ? { issue: active.issue } : null };
    // The invoice the user already has open (its own numbers, never its content): lets the chat answer about
    // THIS invoice instead of guessing. Absent whenever no invoice balance is visible on the page.
    const balance = this.doc.querySelector('[data-finora-section="invoice.balance"]');
    if (balance) {
      const remaining = Number(balance.dataset.remaining);
      if (Number.isFinite(remaining)) out.invoice = { remaining, status: balance.dataset.status || null };
    }
    return out;
  }

  async ask(text, { intent = null, shown = text } = {}) {
    if (this.pending) return;
    this.pending = true;
    this.input.value = "";
    this.input.disabled = this.send.disabled = true;
    this.say("user", shown);
    const typing = this.paint({ role: "bot", text: "دا أراجع خطوات النظام…", type: "loading" });
    typing.classList.add("is-typing");
    try {
      const { response } = await this.api.ask({ message: intent ? "" : text, intent, ...this.context() });
      typing.remove();
      this.say("bot", response.message, { type: response.type, actions: response.actions });
    } catch (error) {
      typing.remove();
      if (error.name === "FeatureDisabledError") return;
      const wait = error.status === 429 ? "كثرت الأسئلة بوقت قصير، جرب بعد لحظات." : "تعذر الوصول للمساعد حالياً، لكن تكدر تستخدم الدروس الجاهزة.";
      this.say("bot", wait, { type: "error" });
    } finally {
      this.pending = false;
      this.input.disabled = this.send.disabled = false;
      if (this.home.isOpen) this.input.focus();
    }
  }

  async runAction(action) {
    switch (action.type) {
      case "start_tutorial":
        if (this.engine.isBusy()) return this.say("bot", "هناك درس قيد التنفيذ. أكمله أو أنهِه وبعدها نبدأ الدرس الجديد.", { type: "explanation" });
        this.say("bot", `بدأنا الدرس.`, { type: "tutorial_started" });
        await this.home.close();
        return this.engine.startTutorial(action.tutorial_id);
      case "show_me":
        if (this.engine.isBusy()) return this.say("bot", "كمّل الدرس الحالي أو أنهِه أولاً، وبعدها أوريك المكان.", { type: "explanation" });
        await this.home.close();
        if (!(await this.showMe.run({ target: action.target, reveal: action.reveal, message: action.message })).found) {
          return this.say("bot", "ما كدرت ألقى هذا العنصر بالصفحة الحالية.", { type: "not_found" });
        }
        return undefined;
      case "show_current":
        await this.home.close();
        if (!(await this.showMe.pointAtCurrent())) this.say("bot", "العنصر المطلوب مو ظاهر هسه. افتح الصفحة أو النموذج المطلوب.", { type: "explanation" });
        return undefined;
      case "choose":
        return this.ask("", { intent: action.intent, shown: action.label });
      case "resume_dependency":
        await this.home.close();
        return this.engine.onAction("dependency_start");
      default: // dismiss
        return this.say("bot", "تمام.", { type: "explanation" });
    }
  }

  focus() {
    this.input.focus();
  }
}
