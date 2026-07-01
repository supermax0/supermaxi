const CourierSettlementAnalysisWindow = {
  render(container, spec) {
    const p = spec.props || {};
    container.innerHTML = `
      <div class="ws-courier-summary">
        <p class="ws-doc-intel-disclaimer">${p.disclaimer || "قراءة فقط — لم يتم تسديد أو ترحيل أي طلب."}</p>
        <div class="ws-courier-cards">
          ${this._card("إجمالي الصفوف", p.totalRows)}
          ${this._card("مطابق", p.matchedRows, "ws-confidence-high")}
          ${this._card("مراجعة", p.reviewRows, "ws-confidence-mid")}
          ${this._card("غير مطابق", p.unmatchedRows, "ws-confidence-low")}
          ${this._card("مكرر", p.duplicateRows)}
          ${this._card("مشاكل", p.issueRows, "ws-confidence-low")}
          ${this._card("إجمالي التحصيل", this._fmt(p.totalCollected))}
          ${this._card("أجور التوصيل", this._fmt(p.totalFees))}
          ${this._card("الصافي المتوقع", this._fmt(p.expectedNet))}
          ${this._card("حالة التحليل", p.status || spec.status)}
        </div>
      </div>`;
  },

  _card(label, value, cls = "") {
    return `<div class="ws-courier-card ${cls}"><span class="ws-courier-card-label">${label}</span><strong>${value ?? "—"}</strong></div>`;
  },

  _fmt(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString("ar-IQ");
  },

  patchFromEvent(container, payload) {
    const spec = JSON.parse(container.closest(".ws-window")?.dataset.spec || "{}");
    const props = { ...(spec.props || {}), ...payload.summary, ...payload };
    CourierSettlementAnalysisWindow.render(container, { ...spec, props });
  },
};

window.CourierSettlementAnalysisWindow = CourierSettlementAnalysisWindow;
