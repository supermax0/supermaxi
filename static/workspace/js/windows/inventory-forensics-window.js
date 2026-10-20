const InventoryForensicsWindow = {
  render(container, spec, handlers = {}) {
    const props = spec.props || {};
    const catalog = props.catalog || { products: [], branches: [] };
    const analysis = props.analysis || null;
    container.innerHTML = `
      <section class="ws-forensics" dir="rtl">
        ${this._controls(catalog, analysis)}
        ${analysis ? this._report(analysis) : this._empty()}
      </section>
    `;
    this._bindControls(container, spec, handlers);
    this._bindTabs(container);
    this._bindUnitFilter(container);
  },

  _controls(catalog, analysis) {
    const filters = analysis?.filters || {};
    return `
      <div class="ws-forensics-controls">
        <div class="ws-forensics-brand">
          <span class="ws-forensics-mark">⌁</span>
          <div><strong>المحقق الذكي للمخزون</strong><small>إعادة بناء الرصيد وربط كل قطعة بمصدرها</small></div>
        </div>
        <label><span>بحث سريع</span><input data-forensics-search type="search" placeholder="اسم المنتج أو الباركود أو SKU"></label>
        <label><span>المنتج</span><select data-forensics-product>
          <option value="">اختر المنتج المشكوك بكميته</option>
          ${(catalog.products || []).map((p) => `<option value="${p.id}" ${Number(filters.product_id) === Number(p.id) ? "selected" : ""}>${this._esc(p.name)} — ${this._esc(p.barcode || p.sku || `#${p.id}`)} (${this._fmt(p.quantity)})</option>`).join("")}
        </select></label>
        <label><span>الفرع</span><select data-forensics-branch>
          <option value="">كل الفروع</option>
          ${(catalog.branches || []).map((b) => `<option value="${b.id}" ${Number(filters.branch_id) === Number(b.id) ? "selected" : ""}>${this._esc(b.name)}</option>`).join("")}
        </select></label>
        <label><span>من</span><input data-forensics-from type="date" value="${this._esc(filters.date_from || "")}"></label>
        <label><span>إلى</span><input data-forensics-to type="date" value="${this._esc(filters.date_to || "")}"></label>
        <button type="button" class="ws-btn ws-btn-primary ws-forensics-run">تحليل كل الحركات</button>
      </div>`;
  },

  _empty() {
    return `<div class="ws-forensics-empty">
      <div class="ws-forensics-radar"><i></i><i></i><span>⌕</span></div>
      <h3>حدد المنتج حتى أحقق بسبب تغير كميته</h3>
      <p>سأراجع البيع والشراء والراجع والنقل بين الفروع والتعديلات المباشرة، ثم أربط كل حركة بالطلب والموظف والوقت.</p>
      <div class="ws-forensics-capabilities"><span>تتبع قطعة بقطعة</span><span>كشف فرق الفروع</span><span>قبل وبعد كل حركة</span><span>ربط الطلبات</span></div>
    </div>`;
  },

  _report(a) {
    const s = a.summary || {};
    const health = s.health || "healthy";
    const healthLabel = { healthy: "الرصيد سليم", warning: "يحتاج مراجعة", critical: "يوجد خلل محتمل" }[health];
    return `<div class="ws-forensics-report">
      <div class="ws-forensics-hero is-${health}">
        <div class="ws-forensics-product"><span>${this._esc(a.product?.barcode || a.product?.sku || `#${a.product?.id}`)}</span><h2>${this._esc(a.product?.name || "")}</h2><p>${a.selected_branch ? this._esc(a.selected_branch.name) : "جميع الفروع"}</p></div>
        <div class="ws-forensics-health"><span class="ws-forensics-health-dot"></span><strong>${healthLabel}</strong><small>${this._fmt(s.critical_issues)} حرجة · ${this._fmt(s.warnings)} تحذير</small></div>
      </div>

      <div class="ws-forensics-metrics">
        ${this._metric("الكمية الفعلية", s.actual_quantity, "actual")}
        ${this._metric("دخول بالفترة", s.total_in, "in")}
        ${this._metric("خروج بالفترة", s.total_out, "out")}
        ${this._metric("الحركات", s.movements_count, "moves")}
        ${this._metric("غير مصنفة", s.unclassified_movements, "risk")}
      </div>

      ${this._diagnosis(a.diagnosis || {})}
      ${this._snapshotAlert(a.snapshot_comparisons || [])}
      ${this._issues(a.issues || [])}

      <div class="ws-forensics-tabs" role="tablist">
        <button class="is-active" data-forensics-tab="timeline">سجل الحركات <b>${this._fmt((a.movements || []).length)}</b></button>
        <button data-forensics-tab="units">تتبع القطع <b>${this._fmt(a.units?.total || 0)}</b></button>
        <button data-forensics-tab="reconcile">مطابقة الفروع <b>${this._fmt((a.reconciliations || []).length)}</b></button>
      </div>
      <div class="ws-forensics-panel is-active" data-forensics-panel="timeline">${this._timeline(a.movements || [])}</div>
      <div class="ws-forensics-panel" data-forensics-panel="units">${this._units(a.units || {}, a.coverage || {})}</div>
      <div class="ws-forensics-panel" data-forensics-panel="reconcile">${this._reconciliations(a.reconciliations || [])}</div>
    </div>`;
  },

  _metric(label, value, tone) {
    return `<div class="ws-forensics-metric is-${tone}"><span>${label}</span><strong>${this._fmt(value)}</strong></div>`;
  },

  _diagnosis(diagnosis) {
    const primary = diagnosis.primary;
    if (!primary) return "";
    const tone = primary.severity || "info";
    const evidence = primary.evidence || [];
    const alternatives = diagnosis.alternatives || [];
    return `<section class="ws-forensics-diagnosis is-${tone}">
      <header>
        <div><span class="ws-forensics-diagnosis-kicker">تفسير LEON للخلل</span><h3>${this._esc(primary.title)}</h3></div>
        <strong class="ws-forensics-confidence">ثقة ${this._fmt(primary.confidence)}%</strong>
      </header>
      <p class="ws-forensics-cause">${this._esc(primary.explanation || "")}</p>
      <div class="ws-forensics-diagnosis-grid">
        <div><strong>ليش وصل لهذا السبب؟</strong><ul>${evidence.map((item) => `<li>${this._esc(item)}</li>`).join("")}</ul></div>
        <div class="ws-forensics-action"><strong>الإجراء المقترح</strong><p>${this._esc(primary.recommended_action || "راجع الحركة والجرد قبل أي تصحيح.")}</p></div>
      </div>
      ${alternatives.length ? `<details class="ws-forensics-alternatives"><summary>أسباب إضافية محتملة ومثبتة (${alternatives.length})</summary><div>${alternatives.map((item) => `<article class="is-${item.severity}"><header><strong>${this._esc(item.title)}</strong><span>ثقة ${this._fmt(item.confidence)}%</span></header><p>${this._esc(item.explanation)}</p><small>${this._esc(item.recommended_action || "")}</small></article>`).join("")}</div></details>` : ""}
    </section>`;
  },

  _snapshotAlert(rows) {
    const broken = rows.filter((item) => item.has_baseline && !item.is_balanced);
    if (broken.length) return `<div class="ws-forensics-exact-alert"><strong>تم إثبات تغير بلا حركة موثقة</strong>${broken.map((item) => `<span>${this._esc(item.branch_name)}: كان ${this._fmt(item.baseline_quantity)}، الحركات ${this._signed(item.documented_delta)}، المفروض ${this._fmt(item.expected)}، الموجود ${this._fmt(item.actual)}.</span>`).join("")}</div>`;
    const hasBaseline = rows.some((item) => item.has_baseline);
    return `<div class="ws-forensics-baseline ${hasBaseline ? "is-good" : ""}">${hasBaseline ? "✓ التغير منذ الفحص السابق مطابق للحركات المسجلة." : "تم حفظ هذه الكمية كخط أساس. من الفحص القادم سيظهر أي تغير غير موثق بين الفحصين بدقة."}</div>`;
  },

  _issues(issues) {
    if (!issues.length) return `<div class="ws-forensics-clean">✓ لم يظهر فرق غير مبرر ضمن الأدلة المتاحة.</div>`;
    const important = issues.filter((item) => ["critical", "warning"].includes(item.severity)).slice(0, 8);
    return `<details class="ws-forensics-issues" ${important.some((i) => i.severity === "critical") ? "open" : ""}><summary><span>نتائج التحقيق</span><b>${important.length}</b></summary><div>${important.map((item) => `<article class="is-${item.severity}"><i>${item.severity === "critical" ? "!" : "?"}</i><p><strong>${this._esc(item.title || "ملاحظة مخزنية")}</strong><span>${this._esc(item.message || "")}</span></p></article>`).join("")}</div></details>`;
  },

  _timeline(rows) {
    if (!rows.length) return `<div class="ws-forensics-no-data">لا توجد حركات في الفترة المختارة.</div>`;
    return `<div class="ws-forensics-timeline">${rows.map((row) => {
      const src = row.source || {};
      const sourceLabel = src.kind === "invoice" ? `طلب #${src.number}` : src.kind === "purchase" ? `شراء #${src.number}` : src.kind === "stock_transfer" ? `نقل #${src.number}` : `${row.source_type} #${row.source_id}`;
      return `<details class="ws-forensics-move is-${row.risk}">
        <summary>
          <span class="ws-forensics-direction is-${row.direction}">${row.direction === "in" ? "داخل" : "خارج"}</span>
          <div class="ws-forensics-move-main"><strong>${this._esc(row.label)}</strong><small>${this._esc(sourceLabel)} · ${this._esc(row.branch_name)}</small></div>
          <div class="ws-forensics-balance"><span>${this._fmt(row.before)}</span><i>←</i><strong>${this._fmt(row.after)}</strong><small>${this._signed(row.delta)}</small></div>
          <time>${this._date(row.created_at)}</time>
        </summary>
        <div class="ws-forensics-move-detail">
          <div class="ws-forensics-detail-grid">
            <p><span>الموظف/المنفذ</span><strong>${this._esc(row.actor || "غير مسجل")}</strong></p>
            <p><span>الكمية</span><strong>${this._fmt(row.quantity)} قطعة</strong></p>
            <p><span>سعر التكلفة</span><strong>${this._fmt(row.unit_cost)}</strong></p>
            <p><span>مفتاح الحركة</span><code>${this._esc(row.movement_key)}</code></p>
            ${row.reason ? `<p class="is-wide"><span>السبب</span><strong>${this._esc(row.reason)}</strong></p>` : ""}
            ${row.risk_reason ? `<p class="is-wide is-risk"><span>سبب الاشتباه</span><strong>${this._esc(row.risk_reason)}</strong></p>` : ""}
          </div>
          ${this._sourceCard(src)}
        </div>
      </details>`;
    }).join("")}</div>`;
  },

  _sourceCard(src) {
    if (!src || !src.kind) return "";
    if (src.kind === "invoice") return `<div class="ws-forensics-source-card"><header><strong>تفاصيل الطلب #${this._esc(src.number)}</strong><span>${this._esc(src.status || "")}</span></header><div class="ws-forensics-source-info"><span>الزبون: <b>${this._esc(src.customer || "—")}</b></span><span>الدفع: <b>${this._esc(src.payment_status || "—")}</b></span><span>الموظف: <b>${this._esc(src.employee_name || "—")}</b></span></div>${this._relatedItems(src.related_items || [], "invoice")}</div>`;
    if (src.kind === "purchase") return `<div class="ws-forensics-source-card"><header><strong>فاتورة الشراء #${this._esc(src.number)}</strong><span>${this._esc(src.status || "")}</span></header><div class="ws-forensics-source-info"><span>المورد: <b>${this._esc(src.supplier || "—")}</b></span></div>${this._relatedItems(src.related_items || [], "purchase")}</div>`;
    if (src.kind === "stock_transfer") return `<div class="ws-forensics-source-card"><header><strong>نقل مخزون #${this._esc(src.number)}</strong><span>${this._esc(src.status || "")}</span></header><div class="ws-forensics-source-info"><span>من: <b>${this._esc(src.from_branch || "—")}</b></span><span>إلى: <b>${this._esc(src.to_branch || "—")}</b></span><span>أنشأه: <b>${this._esc(src.created_by || "—")}</b></span><span>استلمه: <b>${this._esc(src.received_by || "—")}</b></span></div>${this._relatedItems(src.related_items || [], "transfer")}</div>`;
    return "";
  },

  _relatedItems(items, kind) {
    if (!items.length) return "";
    return `<div class="ws-forensics-related"><span>كل الأصناف المرتبطة بنفس ${kind === "invoice" ? "الطلب" : kind === "purchase" ? "الفاتورة" : "النقل"}</span><table><tbody>${items.map((item) => `<tr><td>${this._esc(item.name || `منتج #${item.product_id}`)}</td><td>${this._fmt(item.quantity)}</td><td>${this._fmt(item.price ?? item.unit_cost ?? 0)}</td></tr>`).join("")}</tbody></table></div>`;
  },

  _units(units, coverage) {
    const items = units.items || [];
    return `<div class="ws-forensics-units-head"><div><strong>هوية تتبع لكل قطعة</strong><span>بالمخزون ${this._fmt(units.in_stock)} · خرجت ${this._fmt(units.out)} · مفقودة/غامضة ${this._fmt(units.missing)}</span></div><input type="search" data-forensics-unit-search placeholder="ابحث بمعرف القطعة أو الباركود"></div>
      <p class="ws-forensics-coverage">${this._esc(coverage.note || "")}</p>
      <div class="ws-forensics-units"><table><thead><tr><th>معرف التتبع</th><th>المصدر</th><th>الفرع الحالي</th><th>الحالة</th><th>دخول</th><th>خروج</th></tr></thead><tbody>${items.slice(0, 500).map((unit) => `<tr data-unit-row data-unit-search="${this._esc(`${unit.trace_id} ${unit.barcode || ""}`.toLowerCase())}" class="is-${unit.status}"><td><code>${this._esc(unit.trace_id)}</code><small>${this._esc(unit.barcode || "")}</small></td><td>${this._esc(unit.origin)}</td><td>${unit.current_branch_id ?? "عام"}</td><td><span>${this._unitStatus(unit.status)}</span></td><td>${this._date(unit.entered_at)}</td><td>${this._date(unit.exited_at)}</td></tr>`).join("")}</tbody></table>${items.length > 500 ? `<p class="ws-forensics-limit">يُعرض أول 500 من ${this._fmt(items.length)} قطعة. استخدم البحث للوصول السريع ضمن المعروض.</p>` : ""}</div>`;
  },

  _reconciliations(rows) {
    return `<div class="ws-forensics-reconcile">${rows.map((row) => `<article class="${row.is_balanced ? "is-balanced" : "is-broken"}"><header><strong>${this._esc(row.branch_name)}</strong><span>${row.is_balanced ? "متوازن" : "فرق يحتاج تحقيق"}</span></header><div><p><span>الفعلي</span><strong>${this._fmt(row.actual)}</strong></p><p><span>حسب السجل الثابت</span><strong>${this._fmt(row.ledger_expected)}</strong><small>${this._signed(row.ledger_difference)} فرق</small></p><p><span>حسب الطلبات والشراء</span><strong>${this._fmt(row.source_expected)}</strong><small>${this._signed(row.source_difference)} فرق</small></p><p><span>افتتاحي</span><strong>${this._fmt(row.opening)}</strong></p></div></article>`).join("")}</div>`;
  },

  _bindControls(container, spec, handlers) {
    const run = container.querySelector(".ws-forensics-run");
    const search = container.querySelector("[data-forensics-search]");
    const productSelect = container.querySelector("[data-forensics-product]");
    search?.addEventListener("input", () => {
      const term = String(search.value || "").trim().toLowerCase();
      Array.from(productSelect?.options || []).forEach((option, index) => {
        if (index === 0) return;
        option.hidden = Boolean(term) && !String(option.textContent || "").toLowerCase().includes(term);
      });
    });
    run?.addEventListener("click", async () => {
      const productId = Number(container.querySelector("[data-forensics-product]")?.value || 0);
      if (!productId || !handlers.onAnalyze) return;
      const branchId = Number(container.querySelector("[data-forensics-branch]")?.value || 0) || null;
      const payload = { product_id: productId, branch_id: branchId, date_from: container.querySelector("[data-forensics-from]")?.value || null, date_to: container.querySelector("[data-forensics-to]")?.value || null };
      run.disabled = true;
      run.textContent = "جاري إعادة بناء الحركات...";
      try { await handlers.onAnalyze(spec, payload); }
      finally { if (run.isConnected) { run.disabled = false; run.textContent = "تحليل كل الحركات"; } }
    });
  },

  _bindTabs(container) {
    container.querySelectorAll("[data-forensics-tab]").forEach((button) => button.addEventListener("click", () => {
      container.querySelectorAll("[data-forensics-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
      container.querySelectorAll("[data-forensics-panel]").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.forensicsPanel === button.dataset.forensicsTab));
    }));
  },

  _bindUnitFilter(container) {
    container.querySelector("[data-forensics-unit-search]")?.addEventListener("input", (event) => {
      const query = String(event.target.value || "").trim().toLowerCase();
      container.querySelectorAll("[data-unit-row]").forEach((row) => { row.hidden = query && !String(row.dataset.unitSearch || "").includes(query); });
    });
  },

  _unitStatus(status) { return ({ in_stock: "بالمخزون", sold_or_out: "خرج/بيع", transferred: "قيد النقل", unverified_extra: "زيادة غير موثقة", missing_unexplained: "مفقودة", unknown_out: "خروج بلا دخول" })[status] || status; },
  _fmt(value) { return Number(value || 0).toLocaleString("en-US"); },
  _signed(value) { const n = Number(value || 0); return `${n > 0 ? "+" : ""}${this._fmt(n)}`; },
  _date(value) { if (!value) return "—"; try { return window.FinoraTime.format(new Date(value), { dateStyle: "medium", timeStyle: "short" }); } catch (_) { return String(value); } },
  _esc(value) { const node = document.createElement("div"); node.textContent = String(value ?? ""); return node.innerHTML; },
};

window.InventoryForensicsWindow = InventoryForensicsWindow;
