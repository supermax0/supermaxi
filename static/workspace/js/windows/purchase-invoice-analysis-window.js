const PurchaseInvoiceAnalysisWindow = {
  USD_TO_IQD_RATE: 1350,

  render(container, spec, handlers = {}) {
    const analysis = (spec.props || {}).analysis || {};
    const summary = analysis.summary || {};
    const supplier = analysis.supplier || {};
    const invoice = analysis.invoice || {};
    const posted = (analysis.posting || {}).status === "posted";
    const supplierMatch = supplier.matched || {};
    const supplierName = supplierMatch.name || supplier.source_name || "غير مقروء";
    const supplierStatus = supplier.status === "matched" ? "مطابق" : "سيُنشأ بعد الموافقة";
    const supplierOptions = [supplierMatch, ...(supplier.candidates || [])]
      .filter((item, index, list) => item?.id && list.findIndex((candidate) => Number(candidate?.id) === Number(item.id)) === index);
    const rows = analysis.rows || [];

    container.innerHTML = `
      <section class="ws-purchase-analysis" dir="rtl">
        <div class="ws-purchase-hero">
          <div class="ws-purchase-identity">
            <span class="ws-purchase-identity-icon" aria-hidden="true">▤</span>
            <div>
              <span class="ws-purchase-eyebrow">فاتورة شراء ذكية</span>
              <h3>${this._esc(supplierName)}</h3>
              <p>رقم فاتورة المورد: <strong>${this._esc(invoice.supplier_invoice_no || "—")}</strong></p>
            </div>
          </div>
          <div class="ws-purchase-supplier-state ${supplier.status === "matched" ? "is-match" : "is-new"}">
            <span>${this._esc(supplierStatus)}</span>
            ${supplierMatch.score ? `<strong>${Math.round(Number(supplierMatch.score) * 100)}%</strong>` : ""}
          </div>
        </div>

        ${posted ? "" : `<div class="ws-purchase-supplier-editor">
          <div><span>تصحيح المورد قبل الاعتماد</span><strong>المورد الحالي: ${this._esc(supplierName)}</strong></div>
          <select class="ws-purchase-supplier-select" data-purchase-supplier-select>
            <option value="">اختر مورداً موجوداً…</option>
            ${supplierOptions.map((item) => `<option value="${Number(item.id)}" ${Number(item.id) === Number(supplierMatch.id) ? "selected" : ""}>${this._esc(item.name)}${item.phone ? ` — ${this._esc(item.phone)}` : ""}</option>`).join("")}
          </select>
          <button type="button" data-purchase-save-supplier="existing">اعتماد المورد المختار</button>
          <input type="text" data-purchase-new-supplier value="${this._esc(supplier.source_name || "")}" placeholder="أو اكتب اسم مورد جديد">
          <button type="button" data-purchase-save-supplier="new" class="is-ghost">اعتماد كمورد جديد</button>
        </div>`}

        <div class="ws-purchase-metrics">
          ${this._metric("مطابق", summary.matched_rows || 0, "green")}
          ${this._metric("منتج جديد", summary.new_product_rows || 0, "purple")}
          ${this._metric("يحتاج قرار", summary.review_rows || 0, "amber")}
          ${this._metric("القطع", summary.total_units || 0, "blue", "purchase-total-units")}
          ${this._metric("الإجمالي", this._fmt(summary.grand_total || 0), "dark", "purchase-grand-total")}
        </div>

        ${summary.blocking && summary.blocking.length ? `
          <div class="ws-purchase-alert">
            <strong>يلزم إكمال المراجعة</strong>
            <ul>${summary.blocking.slice(0, 5).map((item) => `<li>${this._esc(item)}</li>`).join("")}</ul>
          </div>` : `
          <div class="ws-purchase-ready">✓ المجاميع والقرارات جاهزة. لن يتم إدخال شيء قبل موافقتك.</div>`}
        ${Number(summary.new_product_rows || 0) > 0 ? `<div class="ws-purchase-new-note">المنتجات الجديدة ستُنشأ مخفية عن المتجر، ويُضبط سعر بيعها مؤقتاً بسعر الشراء لحين مراجعته.</div>` : ""}

        <div class="ws-purchase-unsaved" data-purchase-unsaved hidden>
          <span>●</span>
          <div><strong>توجد تغييرات غير محفوظة</strong><small>احفظ السطر المعدّل حتى تُعتمد الأسعار الجديدة في الفاتورة.</small></div>
        </div>

        <div class="ws-purchase-table-heading">
          <div><strong>تفاصيل الأصناف والأسعار</strong><small>يمكنك الكتابة بالدينار أو بالدولار، وسيُحسب الإجمالي فوراً.</small></div>
          <span>${rows.length} أصناف</span>
        </div>

        <div class="ws-purchase-table-wrap">
          <table class="ws-purchase-table">
            <thead><tr><th>الصنف في الفاتورة</th><th>نتيجة المطابقة</th><th>الكمية</th><th>سعر الشراء</th><th>الإجمالي</th><th>القرار</th></tr></thead>
            <tbody>${rows.map((row) => this._row(row, posted)).join("")}</tbody>
          </table>
        </div>

        <div class="ws-purchase-footer">
          <div class="ws-purchase-total">
            <span>الإجمالي النهائي</span>
            <strong><b data-purchase-footer-total>${this._fmt(summary.grand_total || 0)}</b> <small>IQD</small></strong>
            <em>محسوب من جميع الأسطر المحفوظة والمعدّلة</em>
          </div>
          ${posted ? `
            <div class="ws-purchase-posted">✓ تم إدخال الفاتورة للمخزون — عملية شراء #${this._esc(String((analysis.posting || {}).purchase_id || ""))}</div>
          ` : `
            <button type="button" class="ws-btn ws-btn-primary ws-purchase-prepare" ${summary.ready ? "" : "disabled"}>مراجعة أخيرة واعتماد الشراء</button>
          `}
        </div>
      </section>
    `;

    container.querySelectorAll("[data-purchase-decision]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!handlers.onDecision || button.disabled) return;
        const rowIndex = Number(button.dataset.rowIndex);
        const decision = button.dataset.purchaseDecision;
        let productId = null;
        if (decision === "use_existing") {
          productId = Number(container.querySelector(`[data-candidate-row="${rowIndex}"]`)?.value || 0);
          if (!productId) return;
        }
        button.disabled = true;
        try { await handlers.onDecision(spec, rowIndex, decision, productId); }
        finally { if (button.isConnected) button.disabled = false; }
      });
    });
    container.querySelectorAll("[data-purchase-values]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!handlers.onValues || button.disabled) return;
        const rowIndex = Number(button.dataset.purchaseValues);
        const quantity = Number(container.querySelector(`[data-purchase-qty="${rowIndex}"]`)?.value || 0);
        const unitPrice = Number(container.querySelector(`[data-purchase-price="${rowIndex}"]`)?.value || 0);
        const usdInput = container.querySelector(`[data-purchase-price-usd="${rowIndex}"]`);
        const unitPriceUsd = usdInput && usdInput.value.trim() !== "" ? Number(usdInput.value) : null;
        const productName = container.querySelector(`[data-purchase-name="${rowIndex}"]`)?.value || "";
        button.disabled = true;
        button.textContent = "جاري حفظ السطر…";
        try { await handlers.onValues(spec, rowIndex, quantity, unitPrice, productName, unitPriceUsd); }
        finally {
          if (button.isConnected) {
            button.disabled = false;
            button.textContent = "حفظ تغييرات السطر";
          }
        }
      });
    });
    container.querySelectorAll("[data-purchase-price-usd]").forEach((input) => {
      input.addEventListener("input", () => {
        const rowIndex = Number(input.dataset.purchasePriceUsd);
        const dollars = Number(input.value || 0);
        const iqPrice = container.querySelector(`[data-purchase-price="${rowIndex}"]`);
        const quantity = Number(container.querySelector(`[data-purchase-qty="${rowIndex}"]`)?.value || 0);
        const lineTotal = container.querySelector(`[data-purchase-line-total="${rowIndex}"]`);
        const converted = dollars > 0 ? Math.round(dollars * this.USD_TO_IQD_RATE) : 0;
        if (iqPrice && converted > 0) iqPrice.value = String(converted);
        if (lineTotal && converted > 0) this._setLineTotal(lineTotal, quantity * converted);
        this._markRowDirty(container, rowIndex);
        this._recalculateLiveSummary(container, invoice);
      });
    });
    container.querySelectorAll("[data-purchase-price]").forEach((input) => {
      input.addEventListener("input", () => {
        const rowIndex = Number(input.dataset.purchasePrice);
        const usdInput = container.querySelector(`[data-purchase-price-usd="${rowIndex}"]`);
        const quantity = Number(container.querySelector(`[data-purchase-qty="${rowIndex}"]`)?.value || 0);
        const lineTotal = container.querySelector(`[data-purchase-line-total="${rowIndex}"]`);
        if (usdInput) usdInput.value = "";
        if (lineTotal) this._setLineTotal(lineTotal, quantity * Number(input.value || 0));
        this._markRowDirty(container, rowIndex);
        this._recalculateLiveSummary(container, invoice);
      });
    });
    container.querySelectorAll("[data-purchase-qty]").forEach((input) => {
      input.addEventListener("input", () => {
        const rowIndex = Number(input.dataset.purchaseQty);
        const quantity = Number(input.value || 0);
        const unitPrice = Number(container.querySelector(`[data-purchase-price="${rowIndex}"]`)?.value || 0);
        const lineTotal = container.querySelector(`[data-purchase-line-total="${rowIndex}"]`);
        if (lineTotal) this._setLineTotal(lineTotal, quantity * unitPrice);
        this._markRowDirty(container, rowIndex);
        this._recalculateLiveSummary(container, invoice);
      });
    });
    container.querySelectorAll("[data-purchase-name]").forEach((input) => {
      input.addEventListener("input", () => {
        this._markRowDirty(container, Number(input.dataset.purchaseName));
      });
    });
    container.querySelectorAll("[data-purchase-product-search]").forEach((input) => {
      let timer = null;
      input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          if (!handlers.onCatalogSearch) return;
          const rowIndex = Number(input.dataset.purchaseProductSearch);
          const select = container.querySelector(`[data-candidate-row="${rowIndex}"]`);
          if (!select) return;
          const data = await handlers.onCatalogSearch(input.value || "");
          const products = Array.isArray(data?.products) ? data.products : [];
          select.innerHTML = products.length
            ? products.map((item) => `<option value="${Number(item.id)}">${this._esc(item.name)}${item.sku ? ` — ${this._esc(item.sku)}` : ""}</option>`).join("")
            : '<option value="">لا توجد نتائج</option>';
        }, 280);
      });
    });
    container.querySelectorAll("[data-purchase-save-supplier]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!handlers.onSupplier || button.disabled) return;
        const mode = button.dataset.purchaseSaveSupplier;
        const supplierId = mode === "existing" ? Number(container.querySelector("[data-purchase-supplier-select]")?.value || 0) : null;
        const supplierName = mode === "new" ? String(container.querySelector("[data-purchase-new-supplier]")?.value || "").trim() : null;
        if (mode === "existing" && !supplierId) return;
        if (mode === "new" && !supplierName) return;
        button.disabled = true;
        try { await handlers.onSupplier(spec, { supplierId, supplierName }); }
        finally { if (button.isConnected) button.disabled = false; }
      });
    });
    if (!posted && handlers.onCatalogSearch) {
      handlers.onCatalogSearch("").then((data) => {
        const select = container.querySelector("[data-purchase-supplier-select]");
        if (!select) return;
        const existing = new Set([...select.options].map((option) => Number(option.value || 0)));
        (data?.suppliers || []).forEach((item) => {
          if (existing.has(Number(item.id))) return;
          const option = document.createElement("option");
          option.value = String(item.id);
          option.textContent = `${item.name}${item.phone ? ` — ${item.phone}` : ""}`;
          select.appendChild(option);
        });
      }).catch(() => {});
    }
    container.querySelector(".ws-purchase-prepare")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      if (!handlers.onPrepare || button.disabled) return;
      button.disabled = true;
      button.textContent = "جاري تجهيز الموافقة...";
      try { await handlers.onPrepare(spec); }
      finally {
        if (button.isConnected) {
          button.disabled = false;
          button.textContent = "مراجعة أخيرة واعتماد الشراء";
        }
      }
    });
  },

  _row(row, posted) {
    const matched = row.matched_product || {};
    const suggestion = row.suggestion || {};
    const candidates = row.candidates || [];
    const status = row.status || "review";
    const isNewProduct = row.decision === "create_new";
    const labels = { matched: "مطابق", new_product: "جديد", review: "مراجعة", invalid: "قيمة غير صحيحة", excluded: "مستبعد" };
    let result = matched.name || (status === "new_product" ? "إنشاء منتج جديد" : suggestion.name || "لا يوجد تطابق");
    let decision = `<span class="ws-purchase-decision-final">${this._esc(labels[status] || status)}</span>`;
    if (!posted && status !== "excluded") {
      const current = row.matched_product ? [row.matched_product] : [];
      const options = [...current, ...candidates].filter((item, index, list) => item?.id && list.findIndex((candidate) => Number(candidate?.id) === Number(item.id)) === index);
      decision = `
        <input data-purchase-product-search="${row.row_index}" class="ws-purchase-product-search" placeholder="ابحث عن صنف موجود">
        <select data-candidate-row="${row.row_index}" class="ws-purchase-candidate">
          ${options.length ? options.map((item) => `<option value="${item.id}">${this._esc(item.name)}${item.score ? ` — ${Math.round(Number(item.score || 0) * 100)}%` : ""}</option>`).join("") : '<option value="">ابحث أولاً…</option>'}
        </select>
        <div class="ws-purchase-row-actions">
          <button data-purchase-decision="use_existing" data-row-index="${row.row_index}">ربط الموجود</button>
          <button data-purchase-decision="create_new" data-row-index="${row.row_index}" class="${isNewProduct ? "is-selected" : ""}" aria-pressed="${isNewProduct ? "true" : "false"}">${isNewProduct ? "✓ منتج جديد" : "منتج جديد"}</button>
          <button data-purchase-decision="exclude" data-row-index="${row.row_index}" class="is-danger">استبعاد</button>
        </div>`;
    } else if (!posted && status === "excluded") {
      decision = `<button data-purchase-decision="create_new" data-row-index="${row.row_index}" class="ws-purchase-restore">إرجاع كجديد</button>`;
    }
    if (!posted && status !== "excluded") {
      decision += `<button data-purchase-values="${row.row_index}" class="ws-purchase-save-values">حفظ تغييرات السطر</button>`;
    }
    return `<tr class="is-${this._esc(status)}" data-purchase-row="${row.row_index}" data-purchase-active="${row.decision !== "exclude" ? "true" : "false"}">
      <td>${posted ? `<strong>${this._esc(row.product_name || "—")}</strong>` : `<input class="ws-purchase-name" data-purchase-name="${row.row_index}" value="${this._esc(row.product_name || "")}" placeholder="اسم المنتج">`}<small>${this._esc(row.barcode || row.sku || "بلا رمز")}</small></td>
      <td><span class="ws-purchase-badge is-${this._esc(status)}">${this._esc(labels[status] || status)}</span><small>${this._esc(result)}</small></td>
      <td>${posted ? this._fmt(row.quantity || 0) : `<input class="ws-purchase-number" data-purchase-qty="${row.row_index}" type="number" min="1" step="1" value="${Number(row.quantity || 0)}">`}</td>
      <td>${posted
        ? `${this._fmt(row.unit_price || 0)}${row.unit_price_usd ? `<small>${this._esc(row.unit_price_usd)}$ × ${this._fmt(row.exchange_rate || this.USD_TO_IQD_RATE)}</small>` : ""}`
        : `<div class="ws-purchase-price-fields">
            <label><span>دينار</span><input class="ws-purchase-number" data-purchase-price="${row.row_index}" type="number" min="1" step="1" value="${Number(row.unit_price || 0)}"></label>
            <label class="is-usd"><span>دولار</span><input class="ws-purchase-number" data-purchase-price-usd="${row.row_index}" type="number" min="0" step="0.01" value="${this._esc(row.unit_price_usd || "")}" placeholder="$"></label>
            <small>1$ = ${this._fmt(this.USD_TO_IQD_RATE)} د.ع</small>
          </div>`}</td>
      <td><strong class="ws-purchase-line-total" data-purchase-line-total="${row.row_index}" data-value="${Number(row.line_total || 0)}">${this._fmt(row.line_total || 0)}</strong><small>د.ع</small></td>
      <td>${decision}</td>
    </tr>`;
  },

  _setLineTotal(element, value) {
    const safeValue = Math.max(Math.round(Number(value || 0)), 0);
    element.dataset.value = String(safeValue);
    element.textContent = this._fmt(safeValue);
  },

  _markRowDirty(container, rowIndex) {
    container.querySelector(`[data-purchase-row="${rowIndex}"]`)?.classList.add("is-dirty");
    const unsaved = container.querySelector("[data-purchase-unsaved]");
    if (unsaved) unsaved.hidden = false;
    const prepare = container.querySelector(".ws-purchase-prepare");
    if (prepare) {
      prepare.disabled = true;
      prepare.textContent = "احفظ تغييرات الأسعار أولاً";
    }
  },

  _recalculateLiveSummary(container, invoice = {}) {
    const activeRows = [...container.querySelectorAll('[data-purchase-row][data-purchase-active="true"]')];
    const subtotal = activeRows.reduce((sum, row) => {
      return sum + Number(row.querySelector("[data-purchase-line-total]")?.dataset.value || 0);
    }, 0);
    const discount = Number(invoice.discount_value || 0);
    const shipping = Number(invoice.shipping_extra || 0);
    const grandTotal = Math.max(subtotal - discount + shipping, 0);
    const totalUnits = activeRows.reduce((sum, row) => {
      const input = row.querySelector("[data-purchase-qty]");
      return sum + Number(input ? input.value : 0);
    }, 0);
    container.querySelectorAll('[data-metric-key="purchase-grand-total"] strong, [data-purchase-footer-total]').forEach((element) => {
      element.textContent = this._fmt(grandTotal);
    });
    container.querySelectorAll('[data-metric-key="purchase-total-units"] strong').forEach((element) => {
      element.textContent = this._fmt(totalUnits);
    });
  },

  _metric(label, value, tone, dataKey = "") {
    return `<div class="ws-purchase-metric is-${tone}"${dataKey ? ` data-metric-key="${dataKey}"` : ""}><span>${this._esc(label)}</span><strong>${this._esc(String(value))}</strong></div>`;
  },
  _fmt(value) { return Number(value || 0).toLocaleString("en-US"); },
  _esc(value) {
    const node = document.createElement("div");
    node.textContent = String(value ?? "");
    return node.innerHTML;
  },
};

window.PurchaseInvoiceAnalysisWindow = PurchaseInvoiceAnalysisWindow;
