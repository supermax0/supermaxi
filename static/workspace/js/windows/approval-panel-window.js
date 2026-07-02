const ApprovalPanelWindow = {
  render(container, spec, handlers = {}) {
    const props = spec.props || {};
    const message = props.message || "هذه موافقة تجريبية في Phase 3 ولا تنفذ أي ترحيل.";
    const hint = props.hint || "لا يتم تعديل أي بيانات مالية أو مخزنية.";
    const stepId = props.step_id || "approval_demo";
    const preview = props.preview || null;

    container.innerHTML = `
      <div class="ws-approval-panel">
        <p class="ws-approval-message">${this._esc(message)}</p>
        ${preview ? this._preview(preview) : ""}
        <p class="ws-approval-hint">${this._esc(hint)}</p>
        <div class="ws-approval-actions">
          <button type="button" class="ws-btn ws-btn-primary ws-approval-accept">${this._esc(props.acceptText || "موافقة")}</button>
          <button type="button" class="ws-btn ws-btn-danger ws-approval-reject">${this._esc(props.rejectText || "رفض")}</button>
        </div>
      </div>
    `;

    const accept = container.querySelector(".ws-approval-accept");
    const reject = container.querySelector(".ws-approval-reject");
    if (accept) {
      accept.addEventListener("click", () => {
        if (handlers.onApprove) handlers.onApprove(stepId);
      });
    }
    if (reject) {
      reject.addEventListener("click", () => {
        if (handlers.onReject) handlers.onReject(stepId);
      });
    }
  },

  _preview(p) {
    const fmt = (v) => typeof v === "number" ? Number(v).toLocaleString("ar-IQ") : (v ?? "—");
    return `
      <div class="ws-approval-preview">
        <div><span>صفوف ستنفذ</span><strong>${fmt(p.safe_rows)}</strong></div>
        <div><span>صفوف مستبعدة</span><strong>${fmt(p.blocked_rows)}</strong></div>
        <div><span>إجمالي التحصيل</span><strong>${fmt(p.total_collected_amount)}</strong></div>
        <div><span>مصروف التوصيل</span><strong>${fmt(p.delivery_fee_expense_amount)}</strong></div>
      </div>
    `;
  },

  _esc(t) {
    const d = document.createElement("div");
    d.textContent = t || "";
    return d.innerHTML;
  },
};

window.ApprovalPanelWindow = ApprovalPanelWindow;
