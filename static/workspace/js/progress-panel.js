/**
 * "جاري التحليل" floating progress checklist for courier analysis.
 * Purely visual; driven by SSE step events from workspace-app.
 */
class WorkspaceProgressPanel {
  constructor(canvasEl) {
    this.canvasEl = canvasEl;
    this.el = null;
    this.steps = [
      { key: "read", label: "\u0642\u0631\u0627\u0621\u0629 \u0627\u0644\u0643\u0634\u0641" },
      { key: "extract", label: "\u0627\u0633\u062a\u062e\u0631\u0627\u062c \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a" },
      { key: "match", label: "\u0645\u0637\u0627\u0628\u0642\u0629 \u0627\u0644\u0637\u0644\u0628\u0627\u062a" },
      { key: "fees", label: "\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0623\u0633\u0639\u0627\u0631 \u0648\u0627\u0644\u0623\u062c\u0648\u0631" },
      { key: "profit", label: "\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0623\u0631\u0628\u0627\u062d \u0648\u0627\u0644\u062e\u0633\u0627\u0626\u0631" },
      { key: "report", label: "\u0625\u0646\u0634\u0627\u0621 \u0627\u0644\u062a\u0642\u0631\u064a\u0631" },
    ];
    this._build();
  }

  _build() {
    this.el = document.createElement("div");
    this.el.className = "ws-progress-panel";
    this.el.style.display = "none";
    this.el.innerHTML = `
      <p class="ws-progress-title">\u25c9 \u062c\u0627\u0631\u064a \u0627\u0644\u062a\u062d\u0644\u064a\u0644</p>
      <ul class="ws-progress-list">
        ${this.steps
          .map(
            (s) => `<li class="ws-progress-item" data-step="${s.key}">
              <span class="ws-progress-check"></span>
              <span>${s.label}</span>
            </li>`
          )
          .join("")}
      </ul>`;
    this.canvasEl.appendChild(this.el);
    this._reposition();
    window.addEventListener("resize", () => this._reposition());
  }

  _reposition() {
    const rect = this.canvasEl.getBoundingClientRect();
    this.el.style.left = `${rect.width / 2 - 110}px`;
    this.el.style.top = `${rect.height * 0.5 + 70}px`;
  }

  show() {
    this._reposition();
    this.el.style.display = "block";
  }

  hide() {
    this.el.style.display = "none";
  }

  reset() {
    this.steps.forEach((s) => this._set(s.key, "pending"));
  }

  /** advance up to and including `key` as done, and mark `active` next */
  markActive(key) {
    const idx = this.steps.findIndex((s) => s.key === key);
    if (idx < 0) return;
    this.steps.forEach((s, i) => {
      if (i < idx) this._set(s.key, "done");
      else if (i === idx) this._set(s.key, "active");
      else this._set(s.key, "pending");
    });
  }

  markDoneThrough(key) {
    const idx = this.steps.findIndex((s) => s.key === key);
    if (idx < 0) return;
    this.steps.forEach((s, i) => {
      this._set(s.key, i <= idx ? "done" : "pending");
    });
  }

  completeAll() {
    this.steps.forEach((s) => this._set(s.key, "done"));
  }

  _set(key, state) {
    const li = this.el.querySelector(`[data-step="${key}"]`);
    if (!li) return;
    li.classList.remove("done", "active");
    if (state === "done") {
      li.classList.add("done");
      li.querySelector(".ws-progress-check").textContent = "\u2713";
    } else if (state === "active") {
      li.classList.add("active");
      li.querySelector(".ws-progress-check").textContent = "";
    } else {
      li.querySelector(".ws-progress-check").textContent = "";
    }
  }
}

window.WorkspaceProgressPanel = WorkspaceProgressPanel;
