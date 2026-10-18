const FinancialPreviewWindow = {
  render(container, spec) {
    const p = spec.props || {};
    const preview = p.preview || {};
    const posting = p.posting || {};
    const postingPreview = preview.posting_preview || {};
    const profit = preview.profit || {};
    const posted = posting.status === "posted" || postingPreview.status === "posted";
    container.innerHTML = `
      <div class="ws-financial-preview">
        <p class="ws-doc-intel-disclaimer">${posted ? "تم تنفيذ الصفوف المطابقة السليمة فقط." : "هذه ليست عملية تسديد بعد. التنفيذ يحتاج موافقة صريحة."}</p>
        ${preview.global_blockers ? `<p class="ws-financial-note" style="color:#b42318">التنفيذ متوقف: يوجد ${preview.global_blockers} خلل في مجاميع الكشف أو بنيته.</p>` : ""}
        <div class="ws-courier-cards">
          ${this._card("إجمالي التحصيل", preview.total_collected_amount)}
          ${this._card("إجمالي أجور التوصيل", preview.total_delivery_fees)}
          ${this._card("الصافي المتوقع", preview.expected_net_amount)}
          ${this._card("مبالغ بها مشكلة", preview.issue_amount)}
          ${this._card("صفوف آمنة نظرياً", preview.safe_to_post_rows)}
          ${this._card("صفوف ممنوعة", preview.blocked_rows)}
          ${this._card("صافي ربح الطلبات المطابقة", profit.net_profit)}
          ${this._card("متوسط ربح الطلب", profit.avg_profit)}
        </div>
        <p class="ws-financial-note">احتُسب الربح من قيمة الطلب ناقص كلفة البضاعة وأجرة التوصيل، وللطلبات المطابقة مؤكداً فقط.</p>
        <p class="ws-financial-note">${(preview.posting_preview && preview.posting_preview.message) || (posting.message || "")}</p>
      </div>`;
  },

  _card(label, value) {
    const fmt = value != null && typeof value === "number" ? Number(value).toLocaleString("ar-IQ") : (value ?? "—");
    return `<div class="ws-courier-card"><span class="ws-courier-card-label">${label}</span><strong>${fmt}</strong></div>`;
  },

  patchFromEvent(container, payload) {
    const spec = JSON.parse(container.closest(".ws-window")?.dataset.spec || "{}");
    FinancialPreviewWindow.render(container, {
      ...spec,
      props: { ...(spec.props || {}), preview: payload.preview || payload },
    });
  },
};

window.FinancialPreviewWindow = FinancialPreviewWindow;
