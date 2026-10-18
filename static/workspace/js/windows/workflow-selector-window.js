const WorkflowSelectorWindow = {
  OPTIONS: [
    { type: "inventory_forensics", label: "المحقق الذكي للمخزون" },
    { type: "mock_workspace", label: "تجربة Workspace" },
    { type: "courier_settlement", label: "كشف تسديد شركة توصيل" },
    { type: "return_statement", label: "كشف راجع" },
    { type: "purchase_invoice", label: "مستند شراء" },
    { type: "unknown_document", label: "مستند غير معروف" },
  ],

  render(container, spec, handlers = {}) {
    const props = spec.props || {};
    const recommended = props.recommendedWorkflow;
    const recConf = props.recommendedConfidence;

    container.innerHTML = `
      <div class="ws-workflow-selector">
        <p class="ws-workflow-selector-hint">اختر نوع العمل المناسب للمستند:</p>
        ${recommended ? `<p class="ws-workflow-recommended">مقترح: <strong>${this._label(recommended)}</strong>${recConf != null ? ` (${Math.round(recConf * 100)}%)` : ""}</p>` : ""}
        <div class="ws-workflow-options"></div>
      </div>
    `;
    const wrap = container.querySelector(".ws-workflow-options");
    const buttons = [];
    this.OPTIONS.forEach((opt) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ws-workflow-option";
      if (opt.type === recommended) btn.classList.add("ws-workflow-option-recommended");
      btn.textContent = opt.label;
      btn.dataset.workflowType = opt.type;
      btn.addEventListener("click", async () => {
        if (!handlers.onSelect || btn.disabled) return;
        const originalLabel = opt.label;
        buttons.forEach((item) => { item.disabled = true; });
        btn.classList.add("is-loading");
        btn.textContent = "جاري التشغيل...";
        try {
          await handlers.onSelect(opt.type);
        } finally {
          buttons.forEach((item) => { item.disabled = false; });
          btn.classList.remove("is-loading");
          btn.textContent = originalLabel;
        }
      });
      wrap.appendChild(btn);
      buttons.push(btn);
    });
  },

  _label(type) {
    const found = this.OPTIONS.find((o) => o.type === type);
    return found ? found.label : type;
  },
};

window.WorkflowSelectorWindow = WorkflowSelectorWindow;
