/**
 * Courier settlement analysis report window — polished LEON UI.
 * Read-only: no posting. Renders stat cards, donut, bar chart,
 * issues table, and a profit/loss preview.
 */
const CourierSettlementAnalysisWindow = {
  render(container, spec, handlers = {}) {
    const activeHandlers = Object.keys(handlers || {}).length
      ? handlers
      : (container.__courierReportHandlers || {});
    container.__courierReportHandlers = activeHandlers;
    const p = spec.props || {};
    const s = p.summary || p;
    const isReturn = p.analysisMode === "return"
      || s.document_kind === "return_statement"
      || (s.summary && s.summary.analysis_mode === "return");
    if (isReturn) {
      this._renderReturn(container, spec, activeHandlers);
      return;
    }

    // Server window props are the reconciled source of truth. Historical
    // completion events may be replayed after a manual correction.
    const totalRows = p.totalRows ?? s.total_rows ?? 0;
    const matched = p.matchedRows ?? s.matched_rows ?? 0;
    const review = p.reviewRows ?? s.review_rows ?? 0;
    const unmatched = p.unmatchedRows ?? s.unmatched_rows ?? 0;
    const collected = p.totalCollected ?? s.total_collected_amount ?? 0;
    const fees = p.totalFees ?? s.total_delivery_fees ?? 0;
    const computedNet = p.expectedNet ?? s.expected_net_amount ?? (collected - fees);
    const financialPreview = p.financial_preview || s.financial_preview || (s.summary && s.summary.financial_preview) || {};
    const statementTotals = p.statementTotals || (s.summary && s.summary.statement_totals) || {};
    const manualExclusions = p.manualExclusions
      || (s.summary && s.summary.excluded_rows)
      || [];
    const hasManualExclusions = manualExclusions.length > 0;
    const amountRepairs = p.amountRepairs
      || (s.summary && s.summary.amount_repairs)
      || [];
    const exclusionReference = statementTotals.manual_exclusion_reference || "deducted";
    const posting = p.posting || (s.summary && s.summary.posting) || {};
    const isStreaming = Boolean(p.streaming);
    const processedRows = Number(p.processedRows || 0);
    const safeToPost = financialPreview.safe_to_post_rows ?? p.safeToPostRows ?? matched;
    const isPosted = posting.status === "posted" || s.status === "posted";
    const printedFees = statementTotals.total_delivery_fees ?? null;
    const feeDiff = printedFees == null ? null : Math.abs(fees - printedFees);
    const audit = this._audit(
      {
        row_count: totalRows,
        total_collected_amount: collected,
        total_delivery_fees: fees,
        expected_net_amount: computedNet,
      },
      isStreaming ? {} : statementTotals
    );
    const issues = p.issues || [];

    const profit = p.profit || financialPreview.profit || {};
    const totalProfit = profit.total_profit ?? null;
    const totalLoss = profit.total_loss ?? null;
    const netProfit = profit.net_profit ?? null;
    const avgProfit = profit.avg_profit ?? null;
    const profitEligible = profit.eligible_rows ?? 0;
    const profitSkipped = profit.skipped_rows ?? Math.max(totalRows - profitEligible, 0);
    const globalBlockers = Number(financialPreview.global_blockers || 0);
    const canSettle = !isStreaming && safeToPost > 0 && !isPosted && !audit.hasMismatch && globalBlockers === 0;
    const settleDisabledReason = isStreaming
      ? "انتظر اكتمال تحليل جميع صفوف الكشف."
      : isPosted
        ? "تم تنفيذ هذا الكشف مسبقاً."
      : audit.hasMismatch
        ? "التنفيذ متوقف لأن مجاميع الصفوف لا تطابق المجاميع المطبوعة."
        : globalBlockers > 0
          ? "التنفيذ متوقف لوجود مشكلة عامة حرجة في الكشف."
          : safeToPost <= 0
            ? "لا توجد طلبات مطابقة سليمة قابلة للتنفيذ حالياً."
            : "فتح معاينة التنفيذ الآمن.";

    container.innerHTML = `
      <div class="ws-report">
        ${isStreaming ? `<div class="ws-courier-live-progress">جاري تحليل الكشف: <strong>${processedRows}</strong> من <strong>${totalRows}</strong> صف — تظهر النتائج تباعاً</div>` : ""}
        ${hasManualExclusions ? `<div class="ws-manual-exclusion-note">تم اعتماد استبعاد <strong>${manualExclusions.length}</strong> صف يدوياً. ${exclusionReference === "original" ? "تبيّن أنه صف قراءة زائد، لذلك لم تُطرح قيمته من المجموع المطبوع." : "تدقيق المجاميع أدناه محسوب بعد طرح الصف الحقيقي المستبعد."}</div>` : ""}
        ${amountRepairs.length ? `<div class="ws-manual-exclusion-note">تم تصحيح <strong>${amountRepairs.length}</strong> صف تلقائياً بعد تأكيد المبلغ من حسبة الصف والمجموع المطبوع والطلب المطابق.</div>` : ""}
        <div class="ws-stat-row">
          ${this._stat("green", "\u2713", collected != null ? this._fmt(collected) : "\u2014", "مجموع الصفوف المستخرج")}
          ${this._stat("blue", "\u2691", matched, "\u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629")}
          ${this._stat("amber", "?", review, "تحتاج مراجعة")}
          ${this._stat("red", "!", unmatched, "غير موجودة بالنظام")}
          ${this._stat("violet", "\u25a4", totalRows, "\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0637\u0644\u0628\u0627\u062a")}
          ${this._stat("violet", "\u2609", this._fmt(fees), "\u0623\u062c\u0648\u0631 \u0627\u0644\u062a\u0648\u0635\u064a\u0644")}
        </div>

        ${this._auditBanner(audit)}

        <div class="ws-section-grid">
          <div class="ws-section">
            <h4 class="ws-section-title">\u0645\u0644\u062e\u0635 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629</h4>
            ${this._donut(totalRows, matched, review, unmatched)}
          </div>
          <div class="ws-section">
            <h4 class="ws-section-title">\u0623\u062c\u0648\u0631 \u0627\u0644\u062a\u0648\u0635\u064a\u0644</h4>
            ${this._bars(printedFees, fees, feeDiff)}
          </div>
        </div>

        <div class="ws-section">
          <h4 class="ws-section-title">تدقيق مجاميع الكشف</h4>
          <div class="ws-profit-row">
            <div class="ws-profit blue"><span class="ws-profit-label">${hasManualExclusions ? "عدد الصفوف بعد الاستبعاد" : "عدد الصفوف المطبوع"}</span><span class="ws-profit-value">${statementTotals.row_count ?? "—"}</span></div>
            <div class="ws-profit green"><span class="ws-profit-label">${hasManualExclusions ? "التحصيل بعد الاستبعاد" : "إجمالي التحصيل المطبوع"}</span><span class="ws-profit-value">${this._fmt(statementTotals.total_collected_amount)}</span><span class="ws-profit-sub">د.ع</span></div>
            <div class="ws-profit violet"><span class="ws-profit-label">${hasManualExclusions ? "الأجور بعد الاستبعاد" : "الأجور المطبوعة"}</span><span class="ws-profit-value">${this._fmt(statementTotals.total_delivery_fees)}</span><span class="ws-profit-sub">د.ع</span></div>
            <div class="ws-profit blue"><span class="ws-profit-label">${hasManualExclusions ? "الصافي بعد الاستبعاد" : "الصافي المطبوع"}</span><span class="ws-profit-value">${this._fmt(statementTotals.expected_net_amount)}</span><span class="ws-profit-sub">د.ع</span></div>
          </div>
        </div>

        <div class="ws-section">
          <h4 class="ws-section-title">\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0644\u0645\u0634\u0627\u0643\u0644</h4>
          ${this._issuesTable(issues)}
        </div>

        <div class="ws-section">
          <h4 class="ws-section-title">\u062a\u062d\u0644\u064a\u0644 \u0627\u0644\u0623\u0631\u0628\u0627\u062d \u0648\u0627\u0644\u062e\u0633\u0627\u0626\u0631</h4>
          <div class="ws-profit-row">
            <div class="ws-profit green">
              <span class="ws-profit-label">\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0623\u0631\u0628\u0627\u062d</span>
              <span class="ws-profit-value">${this._fmt(totalProfit)}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
            <div class="ws-profit red">
              <span class="ws-profit-label">\u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u062e\u0633\u0627\u0626\u0631</span>
              <span class="ws-profit-value">${totalLoss != null ? "-" + this._fmt(totalLoss) : "\u2014"}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
            <div class="ws-profit blue">
              <span class="ws-profit-label">\u0635\u0627\u0641\u064a \u0627\u0644\u0631\u0628\u062d</span>
              <span class="ws-profit-value">${this._fmt(netProfit)}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
            <div class="ws-profit violet">
              <span class="ws-profit-label">\u0645\u062a\u0648\u0633\u0637 \u0631\u0628\u062d \u0627\u0644\u0637\u0644\u0628</span>
              <span class="ws-profit-value">${this._fmt(avgProfit)}</span>
              <span class="ws-profit-sub">\u062f.\u0639</span>
            </div>
          </div>
          <p class="ws-financial-note">
            الربح = قيمة الطلب − كلفة البضاعة − أجرة التوصيل.
            تم الحساب لـ ${profitEligible} طلب مطابق مؤكداً${profitSkipped ? `، واستُبعد ${profitSkipped} صف غير مؤكد أو ناقص الكلفة` : ""}.
          </p>
        </div>

        <div class="ws-report-actions">
          <button type="button" class="ws-btn ws-btn-primary" data-act="settle" title="${this._esc(settleDisabledReason)}" ${canSettle ? "" : "disabled"}>${isPosted ? "\u062a\u0645 \u0627\u0644\u062a\u0646\u0641\u064a\u0630" : "\u062a\u0646\u0641\u064a\u0630 \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u0633\u0644\u064a\u0645\u0629"} (${safeToPost})</button>
          ${audit.hasMismatch ? `<button type="button" class="ws-btn ws-btn-ghost ws-btn-audit" data-act="reanalyze">إعادة التحليل الدقيق</button>` : ""}
          <button type="button" class="ws-btn ws-btn-ghost" data-act="export">\u062a\u0635\u062f\u064a\u0631 \u0627\u0644\u062a\u0642\u0631\u064a\u0631</button>
          <div class="ws-report-more">
            <button type="button" class="ws-btn ws-btn-ghost" data-act="more" aria-expanded="false">\u2807 \u0625\u062c\u0631\u0627\u0621\u0627\u062a \u0623\u062e\u0631\u0649</button>
            <div class="ws-report-more-menu" hidden>
              <button type="button" data-act="print-courier-report">طباعة كشف احترافي</button>
              <button type="button" data-open-window="courier_rows">عرض صفوف الكشف</button>
              <button type="button" data-open-window="courier_issues">عرض جميع المشاكل</button>
              <button type="button" data-open-window="financial_preview">فتح المعاينة المالية</button>
            </div>
          </div>
        </div>
        ${!canSettle && !isPosted ? `<p class="ws-action-disabled-reason">${this._esc(settleDisabledReason)}</p>` : ""}
        <p class="ws-readonly-note">${isPosted ? "\u062a\u0645 \u062a\u0646\u0641\u064a\u0630 \u0627\u0644\u0635\u0641\u0648\u0641 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629 \u0627\u0644\u0633\u0644\u064a\u0645\u0629 \u0641\u0642\u0637\u060c \u0648\u0628\u0642\u064a\u062a \u0628\u0627\u0642\u064a \u0627\u0644\u0635\u0641\u0648\u0641 \u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629." : "\u0627\u0644\u062a\u0646\u0641\u064a\u0630 \u064a\u0645\u0631 \u0639\u0628\u0631 \u0645\u0648\u0627\u0641\u0642\u0629 \u0635\u0631\u064a\u062d\u0629 \u0648\u064a\u0634\u0645\u0644 \u0627\u0644\u0635\u0641\u0648\u0641 \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629 \u0628\u0644\u0627 \u0645\u0634\u0627\u0643\u0644 \u062d\u0631\u062c\u0629 \u0641\u0642\u0637."}</p>
      </div>`;

    const exportBtn = container.querySelector('[data-act="export"]');
    if (exportBtn && activeHandlers.onExport) {
      exportBtn.addEventListener("click", () => activeHandlers.onExport(spec));
    }
    const settleBtn = container.querySelector('[data-act="settle"]');
    if (settleBtn && activeHandlers.onSettle && !settleBtn.disabled) {
      settleBtn.addEventListener("click", async () => {
        if (settleBtn.disabled) return;
        const original = settleBtn.textContent;
        settleBtn.disabled = true;
        settleBtn.textContent = "جاري تجهيز الموافقة...";
        try {
          await activeHandlers.onSettle(spec);
        } finally {
          if (settleBtn.isConnected) {
            settleBtn.disabled = false;
            settleBtn.textContent = original;
          }
        }
      });
    }
    const reanalyzeBtn = container.querySelector('[data-act="reanalyze"]');
    if (reanalyzeBtn && activeHandlers.onReanalyze) {
      reanalyzeBtn.addEventListener("click", async () => {
        const original = reanalyzeBtn.textContent;
        reanalyzeBtn.disabled = true;
        reanalyzeBtn.textContent = "جاري إعادة التحليل...";
        try {
          await activeHandlers.onReanalyze(spec);
        } finally {
          if (reanalyzeBtn.isConnected) {
            reanalyzeBtn.disabled = false;
            reanalyzeBtn.textContent = original;
          }
        }
      });
    }
    const moreBtn = container.querySelector('[data-act="more"]');
    const moreMenu = container.querySelector(".ws-report-more-menu");
    if (moreBtn && moreMenu) {
      moreBtn.addEventListener("click", () => {
        const willOpen = moreMenu.hidden;
        moreMenu.hidden = !willOpen;
        moreBtn.setAttribute("aria-expanded", String(willOpen));
      });
      moreMenu.querySelectorAll("[data-open-window]").forEach((button) => {
        button.addEventListener("click", () => {
          moreMenu.hidden = true;
          moreBtn.setAttribute("aria-expanded", "false");
          if (activeHandlers.onShowWindow) {
            activeHandlers.onShowWindow(button.dataset.openWindow);
          }
        });
      });
      const printCourierButton = moreMenu.querySelector('[data-act="print-courier-report"]');
      if (printCourierButton && activeHandlers.onPrintCourier) {
        printCourierButton.addEventListener("click", () => {
          moreMenu.hidden = true;
          moreBtn.setAttribute("aria-expanded", "false");
          activeHandlers.onPrintCourier(spec);
        });
      }
    }
  },

  _renderReturn(container, spec, handlers = {}) {
    const p = spec.props || {};
    const s = p.summary || p;
    const totalRows = Number(p.totalRows ?? s.total_rows ?? 0);
    const matched = Number(p.matchedRows ?? s.matched_rows ?? 0);
    const review = Number(p.reviewRows ?? s.review_rows ?? 0);
    const unmatched = Number(p.unmatchedRows ?? s.unmatched_rows ?? 0);
    const duplicate = Number(p.duplicateRows ?? s.duplicate_rows ?? 0);
    const preview = p.returnPreview || (s.summary && s.summary.return_preview) || {};
    const posting = p.returnPosting || (s.summary && s.summary.return_posting) || {};
    const issues = p.issues || [];
    const safeRows = Number(preview.safe_rows ?? matched);
    const blockedRows = Number(preview.blocked_rows ?? Math.max(totalRows - safeRows, 0));
    const totalUnits = Number(preview.total_units || 0);
    const isStreaming = Boolean(p.streaming);
    const isPosted = posting.status === "posted" || preview.status === "posted" || s.status === "posted";
    const canExecute = !isStreaming && safeRows > 0 && !isPosted;
    const disabledReason = isStreaming
      ? "انتظر اكتمال مطابقة جميع الصفوف."
      : isPosted
        ? "تم تنفيذ كشف الراجع مسبقاً."
        : safeRows <= 0
          ? "لا توجد طلبات مطابقة مؤكدة قابلة للترجيع."
          : "افتح معاينة التنفيذ ثم وافق على إعادة المخزون.";
    const excluded = p.manualExclusions || (s.summary && s.summary.excluded_rows) || [];

    container.innerHTML = `
      <div class="ws-report ws-return-report">
        ${isStreaming ? `<div class="ws-courier-live-progress">جاري تحليل كشف الراجع: <strong>${Number(p.processedRows || 0)}</strong> من <strong>${totalRows}</strong> صف</div>` : ""}
        ${excluded.length ? `<div class="ws-manual-exclusion-note">تم حذف <strong>${excluded.length}</strong> صف من هذا التحليل. الصورة الأصلية والطلب في النظام لم يُحذفا.</div>` : ""}
        <div class="ws-return-hero">
          <div><span>LEON · إدارة المرتجعات</span><h3>تقرير تحليل كشف الراجع</h3><p>مطابقة آمنة مع الطلبات قبل إعادة أي كمية إلى المخزون.</p></div>
          <b class="${isPosted ? "is-posted" : ""}">${isPosted ? "تم التنفيذ" : "بانتظار المراجعة"}</b>
        </div>
        <div class="ws-stat-row">
          ${this._stat("green", "✓", safeRows, "جاهزة للترجيع")}
          ${this._stat("blue", "▣", totalUnits, "قطع ستعود للمخزون")}
          ${this._stat("amber", "?", review, "تحتاج مراجعة")}
          ${this._stat("red", "!", unmatched, "غير موجودة بالنظام")}
          ${this._stat("violet", "▤", totalRows, "إجمالي الصفوف")}
          ${this._stat("red", "×", duplicate, "صفوف مكررة")}
        </div>
        <div class="ws-section-grid">
          <section class="ws-section">
            <h4 class="ws-section-title">ملخص المطابقة</h4>
            ${this._donut(totalRows, matched, review, unmatched + duplicate)}
          </section>
          <section class="ws-section ws-return-execution-card">
            <h4 class="ws-section-title">معاينة تنفيذ الراجع</h4>
            <div class="ws-return-preview-grid">
              <div><span>طلبات مطابقة</span><strong>${safeRows}</strong></div>
              <div><span>صفوف مستبعدة</span><strong>${blockedRows}</strong></div>
              <div><span>قطع ستعود</span><strong>${totalUnits}</strong></div>
            </div>
            <p>عند الموافقة ستتغير حالة الطلب إلى «راجع»، يُصفّر المسدد، وتعود الأصناف إلى مخزون فرعها الأصلي مرة واحدة فقط.</p>
          </section>
        </div>
        <section class="ws-section">
          <h4 class="ws-section-title">المشاكل التي تحتاج مراجعة</h4>
          ${this._issuesTable(issues)}
        </section>
        <div class="ws-report-actions">
          <button type="button" class="ws-btn ws-btn-primary" data-act="return-execute" title="${this._esc(disabledReason)}" ${canExecute ? "" : "disabled"}>${isPosted ? "تم تنفيذ الراجع" : `تنفيذ الراجع وإعادة المخزون (${safeRows})`}</button>
          <button type="button" class="ws-btn ws-btn-ghost" data-open-return-window="courier_rows">مراجعة الصفوف وحذف صف</button>
          <button type="button" class="ws-btn ws-btn-ghost" data-open-return-window="courier_issues">عرض المشاكل</button>
        </div>
        ${!canExecute && !isPosted ? `<p class="ws-action-disabled-reason">${this._esc(disabledReason)}</p>` : ""}
        <p class="ws-readonly-note">لا يحدث أي تغيير على الطلبات أو المخزون قبل الضغط على التنفيذ ثم الموافقة الصريحة.</p>
      </div>`;

    const execute = container.querySelector('[data-act="return-execute"]');
    if (execute && handlers.onSettle && !execute.disabled) {
      execute.addEventListener("click", async () => {
        const label = execute.textContent;
        execute.disabled = true;
        execute.textContent = "جاري تجهيز الموافقة...";
        try {
          await handlers.onSettle(spec);
        } finally {
          if (execute.isConnected) {
            execute.disabled = false;
            execute.textContent = label;
          }
        }
      });
    }
    container.querySelectorAll("[data-open-return-window]").forEach((button) => {
      button.addEventListener("click", () => {
        if (handlers.onShowWindow) handlers.onShowWindow(button.dataset.openReturnWindow);
      });
    });
  },

  _stat(color, icon, value, label) {
    return `
      <div class="ws-stat">
        <span class="ws-stat-ico ${color}">${icon}</span>
        <span class="ws-stat-value">${value ?? "\u2014"}</span>
        <span class="ws-stat-label">${label}</span>
      </div>`;
  },

  _donut(total, matched, review, unmatched) {
    const segs = [
      { val: matched, color: "#22b573", label: "مطابقة مع طلب في النظام" },
      { val: review, color: "#f5a524", label: "\u062a\u062d\u062a\u0627\u062c \u0645\u0631\u0627\u062c\u0639\u0629" },
      { val: unmatched, color: "#ef4d5c", label: "\u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f\u0629 \u0641\u064a \u0627\u0644\u0646\u0638\u0627\u0645" },
    ];
    const sum = segs.reduce((a, b) => a + (b.val || 0), 0) || 1;
    const r = 52;
    const c = 2 * Math.PI * r;
    let offset = 0;
    const circles = segs
      .map((seg) => {
        const frac = (seg.val || 0) / sum;
        const len = frac * c;
        const dash = `${len} ${c - len}`;
        const circle = `<circle cx="65" cy="65" r="${r}" fill="none" stroke="${seg.color}" stroke-width="16" stroke-dasharray="${dash}" stroke-dashoffset="${-offset}" stroke-linecap="butt"></circle>`;
        offset += len;
        return circle;
      })
      .join("");

    const legend = segs
      .map((seg) => {
        const pct = Math.round(((seg.val || 0) / sum) * 100);
        return `
        <div class="ws-legend-item">
          <span class="ws-legend-dot" style="background:${seg.color}"></span>
          <span>${seg.label}</span>
          <span class="ws-legend-val">${seg.val || 0} (${pct}%)</span>
        </div>`;
      })
      .join("");

    return `
      <div class="ws-donut-wrap">
        <div class="ws-donut">
          <svg width="130" height="130" viewBox="0 0 130 130">
            <circle cx="65" cy="65" r="${r}" fill="none" stroke="#eef1f8" stroke-width="16"></circle>
            ${circles}
          </svg>
          <div class="ws-donut-center"><strong>${total}</strong><span>\u0637\u0644\u0628</span></div>
        </div>
        <div class="ws-legend">${legend}</div>
      </div>`;
  },

  _bars(printed, computed, diff) {
    const expected = printed == null ? computed : printed;
    const max = Math.max(expected || 0, computed || 0, diff || 0, 1);
    const h = (v) => `${Math.max(6, Math.round((v / max) * 120))}px`;
    return `
      <div class="ws-bars">
        <div class="ws-bar-col">
          <span class="ws-bar-value">${this._fmtShort(expected)}</span>
          <div class="ws-bar expected" style="height:${h(expected)}"></div>
          <span class="ws-bar-label">المطبوع</span>
        </div>
        <div class="ws-bar-col">
          <span class="ws-bar-value">${this._fmtShort(computed)}</span>
          <div class="ws-bar computed" style="height:${h(computed)}"></div>
          <span class="ws-bar-label">مجموع الصفوف</span>
        </div>
        <div class="ws-bar-col">
          <span class="ws-bar-value">${this._fmtShort(diff)}</span>
          <div class="ws-bar diff" style="height:${h(diff)}"></div>
          <span class="ws-bar-label">الفرق</span>
        </div>
      </div>`;
  },

  _audit(computed, printed) {
    const fields = [
      ["row_count", "عدد الصفوف"],
      ["total_collected_amount", "إجمالي التحصيل"],
      ["total_delivery_fees", "أجور التوصيل"],
      ["expected_net_amount", "الصافي"],
    ];
    const differences = fields
      .filter(([key]) => printed[key] != null && computed[key] != null && Number(printed[key]) !== Number(computed[key]))
      .map(([key, label]) => ({
        key,
        label,
        printed: Number(printed[key]),
        computed: Number(computed[key]),
        difference: Number(computed[key]) - Number(printed[key]),
      }));
    return { hasMismatch: differences.length > 0, differences };
  },

  _auditBanner(audit) {
    if (!audit.hasMismatch) {
      return `
        <div class="ws-audit-banner ws-audit-ok">
          <strong>✓ مجاميع الصفوف مطابقة للمجاميع المطبوعة</strong>
          <span>يمكن متابعة مراجعة الطلبات الفردية.</span>
        </div>`;
    }
    const details = audit.differences
      .map((item) => {
        const direction = item.difference < 0 ? "أقل" : "أعلى";
        return `${item.label}: مجموع الصفوف ${direction} من المطبوع بـ ${this._fmt(Math.abs(item.difference))}`;
      })
      .join(" • ");
    return `
      <div class="ws-audit-banner ws-audit-error">
        <strong>⚠ قراءة الصفوف غير مطابقة للكشف المطبوع — التنفيذ متوقف</strong>
        <span>${this._esc(details)}</span>
        <small>غالباً انتقلت بيانات صف إلى صف مجاور أثناء قراءة الصورة. أعد التحليل الدقيق أو راجع الصفوف المعلّمة.</small>
      </div>`;
  },

  _issuesTable(issues) {
    if (!issues || !issues.length) {
      return `<p style="color:#7c869c;font-size:12.5px;margin:0">\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0634\u0627\u0643\u0644 \u062c\u0648\u0647\u0631\u064a\u0629 \u2014 \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u0633\u0644\u064a\u0645\u0629.</p>`;
    }
    const rows = issues
      .slice(0, 8)
      .map((i) => {
        const badge = this._sevBadge(i.severity);
        const order = (i.details && (i.details.order_number || i.details.invoice_id)) || "\u2014";
        return `
        <tr>
          <td>${badge}</td>
          <td>${this._esc(i.message || i.issue_type || "")}</td>
          <td>${this._esc(String(order))}</td>
        </tr>`;
      })
      .join("");
    return `
      <table class="ws-issues-table">
        <thead><tr><th>\u0646\u0648\u0639 \u0627\u0644\u0645\u0634\u0643\u0644\u0629</th><th>\u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644</th><th>\u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  },

  _sevBadge(sev) {
    const map = {
      critical: ["red", "\u062d\u0631\u062c"],
      error: ["red", "\u062e\u0637\u0623"],
      warning: ["amber", "\u062a\u062d\u0630\u064a\u0631"],
      info: ["violet", "\u0645\u0639\u0644\u0648\u0645\u0629"],
    };
    const [cls, label] = map[sev] || ["violet", sev || "\u2014"];
    return `<span class="ws-badge ${cls}">${label}</span>`;
  },

  _fmt(n) {
    if (n == null) return "\u2014";
    return Number(n).toLocaleString("en-US");
  },

  _fmtShort(n) {
    if (n == null) return "\u2014";
    const v = Number(n);
    if (v >= 1000) return (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + "K";
    return String(v);
  },

  _esc(text) {
    const d = document.createElement("div");
    d.textContent = text || "";
    return d.innerHTML;
  },

  patchFromEvent(container, payload) {
    const spec = JSON.parse(container.closest(".ws-window")?.dataset.spec || "{}");
    const props = { ...(spec.props || {}), ...payload };
    if (payload.summary) props.summary = { ...(props.summary || {}), ...payload.summary };
    if (payload.issues) props.issues = payload.issues;
    CourierSettlementAnalysisWindow.render(
      container,
      { ...spec, props },
      container.__courierReportHandlers || {}
    );
  },
};

window.CourierSettlementAnalysisWindow = CourierSettlementAnalysisWindow;
