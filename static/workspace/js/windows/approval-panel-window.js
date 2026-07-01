const ApprovalPanelWindow = {
  render(container, spec, handlers = {}) {
    const props = spec.props || {};
    const message = props.message || "هذه موافقة تجريبية في Phase 3 ولا تنفذ أي ترحيل.";
    const stepId = props.step_id || "approval_demo";

    container.innerHTML = `
      <div class="ws-approval-panel">
        <p class="ws-approval-message">${this._esc(message)}</p>
        <p class="ws-approval-hint">لا يتم تعديل أي بيانات مالية أو مخزنية.</p>
        <div class="ws-approval-actions">
          <button type="button" class="ws-btn ws-btn-primary ws-approval-accept">موافقة</button>
          <button type="button" class="ws-btn ws-btn-danger ws-approval-reject">رفض</button>
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

  _esc(t) {
    const d = document.createElement("div");
    d.textContent = t || "";
    return d.innerHTML;
  },
};

window.ApprovalPanelWindow = ApprovalPanelWindow;
