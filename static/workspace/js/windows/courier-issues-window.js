const CourierIssuesWindow = {
  render(container, spec) {
    const p = spec.props || {};
    container.innerHTML = `<div class="ws-courier-issues"><p class="ws-courier-issues-loading">جاري تحميل المشاكل...</p></div>`;
    if (p.issues) {
      this.showIssues(container, p.issues);
    }
  },

  showIssues(container, issues) {
    const root = container.querySelector(".ws-courier-issues") || container;
    const groups = { critical: [], error: [], warning: [], info: [] };
    (issues || []).forEach((i) => {
      const sev = i.severity || "info";
      if (!groups[sev]) groups[sev] = [];
      groups[sev].push(i);
    });
    root.innerHTML = "";
    ["critical", "error", "warning", "info"].forEach((sev) => {
      if (!groups[sev].length) return;
      const block = document.createElement("div");
      block.className = `ws-courier-issue-group ws-courier-sev-${sev}`;
      block.innerHTML = `<h4>${this._sevLabel(sev)} (${groups[sev].length})</h4>`;
      const ul = document.createElement("ul");
      groups[sev].forEach((issue) => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${this._esc(this._typeLabel(issue.issue_type))}</strong> — ${this._esc(issue.message || "")}`;
        ul.appendChild(li);
      });
      block.appendChild(ul);
      root.appendChild(block);
    });
    if (!issues || !issues.length) {
      root.innerHTML = "<p>لا توجد مشاكل مكتشفة</p>";
    }
  },

  _sevLabel(sev) {
    return { critical: "حرج", error: "خطأ", warning: "تحذير", info: "معلومة" }[sev] || sev;
  },

  _typeLabel(type) {
    return {
      ORDER_ALREADY_SETTLED: "الطلب مسدد مسبقاً",
      STATEMENT_TOTAL_MISMATCH: "مجموع الكشف غير مطابق",
      STATEMENT_TOTAL_NOT_READ: "مجموع الكشف غير مقروء",
      MISSING_REQUIRED_AMOUNT: "مبلغ مفقود في الصف",
      ORDER_PRICE_ADJUSTMENT_PLANNED: "تعديل سعر مخطط",
      MANUAL_ROW_EXCLUSION: "صف مستبعد يدوياً",
      PIECE_PARTIAL_SETTLEMENT: "تسديد قطعة من طلب متعدد",
      ORDER_PARTIALLY_PAID: "طلب مسدد جزئياً",
      AMOUNT_MISMATCH: "المبلغ غير مطابق",
      ROW_ARITHMETIC_MISMATCH: "حسبة الصف غير صحيحة",
      ORDER_NOT_FOUND: "الطلب غير موجود",
      DUPLICATE_ORDER_IN_STATEMENT: "طلب مكرر في الكشف",
      LOW_EXTRACTION_CONFIDENCE: "دقة القراءة منخفضة",
      PHONE_MISMATCH: "رقم الهاتف غير مطابق",
      DELIVERY_FEE_MISMATCH: "أجرة التوصيل غير مطابقة",
      INVALID_ORDER_STATUS: "حالة الطلب غير صالحة",
    }[type] || type || "مشكلة";
  },

  _esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  },
};

window.CourierIssuesWindow = CourierIssuesWindow;
