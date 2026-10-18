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
      accept.addEventListener("click", async () => {
        if (!handlers.onApprove || accept.disabled) return;
        const acceptText = accept.textContent;
        const rejectWasDisabled = reject ? reject.disabled : false;
        accept.disabled = true;
        if (reject) reject.disabled = true;
        accept.textContent = "جاري التنفيذ...";
        try {
          await handlers.onApprove(stepId);
        } finally {
          if (accept.isConnected) {
            accept.disabled = false;
            accept.textContent = acceptText;
          }
          if (reject && reject.isConnected) reject.disabled = rejectWasDisabled;
        }
      });
    }
    if (reject) {
      reject.addEventListener("click", async () => {
        if (!handlers.onReject || reject.disabled) return;
        const rejectText = reject.textContent;
        const acceptWasDisabled = accept ? accept.disabled : false;
        reject.disabled = true;
        if (accept) accept.disabled = true;
        reject.textContent = "جاري الإلغاء...";
        try {
          await handlers.onReject(stepId);
        } finally {
          if (reject.isConnected) {
            reject.disabled = false;
            reject.textContent = rejectText;
          }
          if (accept && accept.isConnected) accept.disabled = acceptWasDisabled;
        }
      });
    }
  },

  _preview(p) {
    const fmt = (v) => typeof v === "number" ? Number(v).toLocaleString("ar-IQ") : (v ?? "—");
    if (p.kind === "return") {
      return `
        <div class="ws-approval-preview ws-return-approval-preview">
          <div><span>طلبات ستُرجع</span><strong>${fmt(p.safe_rows)}</strong></div>
          <div><span>صفوف مستبعدة</span><strong>${fmt(p.blocked_rows)}</strong></div>
          <div><span>قطع تعود للمخزون</span><strong>${fmt(p.total_units)}</strong></div>
          <div><span>إجمالي الصفوف</span><strong>${fmt(p.total_rows)}</strong></div>
        </div>
      `;
    }
    if (p.kind === "purchase") {
      const supplier = p.supplier || {};
      const supplierName = (supplier.matched || {}).name || supplier.source_name || "مورد جديد";
      return `
        <div class="ws-approval-preview ws-purchase-approval-preview">
          <div><span>المورد</span><strong>${this._esc(supplierName)}</strong></div>
          <div><span>منتجات مطابقة</span><strong>${fmt(p.matched_products)}</strong></div>
          <div><span>منتجات ستُنشأ</span><strong>${fmt(p.new_products)}</strong></div>
          <div><span>القطع للمخزون</span><strong>${fmt(p.total_units)}</strong></div>
          <div><span>إجمالي الشراء</span><strong>${fmt(p.grand_total)}</strong></div>
        </div>
      `;
    }
    const accounts = Array.isArray(p.payment_accounts) ? p.payment_accounts : [];
    const accountCards = accounts.map((account) => {
      const isBank = account.account_type === "bank";
      return `
        <article class="ws-approval-account ${isBank ? "is-bank" : "is-cash"}">
          <div class="ws-approval-account-icon" aria-hidden="true">${isBank ? "▣" : "●"}</div>
          <div class="ws-approval-account-main">
            <div class="ws-approval-account-title">
              <strong>${this._esc(account.account_name || (isBank ? "بطاقة البنك" : "الصندوق"))}</strong>
              <span>${isBank ? "بطاقة بنكية" : "صندوق نقدي"}</span>
            </div>
            <div class="ws-approval-account-amount">${fmt(account.settlement_amount)} <small>د.ع</small></div>
            <div class="ws-approval-account-meta">
              <span>${fmt(account.rows_count)} طلب</span>
              <span>أجور ${fmt(account.delivery_fee_amount)}</span>
              ${Number(account.direct_bank_amount || 0) > 0
                ? `<span class="is-direct">تحويل مباشر ${fmt(account.direct_bank_amount)}</span>`
                : ""}
              ${Number(account.reclassified_amount || 0) > 0
                ? `<span class="is-direct">نقل من الصندوق ${fmt(account.reclassified_amount)}</span>`
                : ""}
            </div>
          </div>
        </article>`;
    }).join("");
    return `
      <div class="ws-courier-approval-preview">
        <div class="ws-approval-summary-strip">
          <div class="is-primary"><span>طلبات ستنفذ</span><strong>${fmt(p.safe_rows)}</strong></div>
          <div class="${Number(p.blocked_rows || 0) ? "is-warning" : "is-success"}"><span>مستبعدة</span><strong>${fmt(p.blocked_rows)}</strong></div>
          <div><span>إجمالي التسديد</span><strong>${fmt(p.total_collected_amount)} <small>د.ع</small></strong></div>
          <div><span>أجور التوصيل</span><strong>${fmt(p.delivery_fee_expense_amount)} <small>د.ع</small></strong></div>
        </div>
        ${accountCards ? `
          <section class="ws-approval-accounts">
            <div class="ws-approval-section-title">
              <strong>توزيع التسديد على الحسابات</strong>
              <span>راجع وجهة كل مبلغ قبل التنفيذ</span>
            </div>
            <div class="ws-approval-account-grid">${accountCards}</div>
          </section>` : ""}
        ${Number(p.direct_bank_transfer_amount || 0) > 0 ? `
          <div class="ws-approval-bank-note">
            <span>تحويلات بنكية مباشرة</span>
            <strong>${fmt(p.direct_bank_transfer_amount)} د.ع</strong>
            <small>مضافة إلى تسديد الطلبات وليست ضمن تحصيل شركة التوصيل.</small>
          </div>` : ""}
        ${Number(p.reclassified_payment_amount || 0) > 0 ? `
          <div class="ws-approval-bank-note">
            <span>تصحيح وجهة تسديد سابق</span>
            <strong>${fmt(p.reclassified_payment_amount)} د.ع</strong>
            <small>سيُنقل هذا المبلغ من الصندوق إلى الحساب البنكي المختار من دون احتسابه كتسديد جديد.</small>
          </div>` : ""}
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
