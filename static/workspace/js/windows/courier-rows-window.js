const CourierRowsWindow = {
  _reconciledBankRows: new Set(),
  _filters: ["all", "matched", "review", "unmatched", "duplicate"],
  _labels: {
    all: "الكل",
    matched: "مطابق تلقائياً",
    review: "تحتاج مراجعة",
    unmatched: "غير موجود بالنظام",
    duplicate: "مكرر",
  },
  _statusLabels: {
    matched: "مطابق تلقائياً",
    review: "تحتاج مراجعة",
    unmatched: "غير موجود بالنظام",
    duplicate: "مكرر في الكشف",
  },

  render(container, spec, handlers = {}) {
    const p = spec.props || {};
    const current = p.filter || "all";
    const isReturn = p.analysisMode === "return";
    container.innerHTML = `
      <div class="ws-courier-rows" data-current-filter="${this._esc(current)}" data-analysis-mode="${isReturn ? "return" : "courier"}">
        <div class="ws-courier-rows-guide">
          <strong>${isReturn ? "راجع الصفوف قبل تنفيذ الراجع" : "كيف تقرأ النتيجة؟"}</strong>
          <span><b class="ok">مطابق:</b> الأدلة كافية واعتمده النظام تلقائياً.</span>
          <span><b class="review">مراجعة:</b> يوجد طلب محتمل لكن بعض البيانات مختلفة.</span>
          <span><b class="bad">غير موجود:</b> لا توجد أدلة كافية لربطه بطلب بأمان.</span>
          ${isReturn ? `<span><b class="review">الحذف:</b> يستبعد الصف من التنفيذ فقط ولا يحذف الطلب الأصلي.</span>` : ""}
        </div>
        <div class="ws-courier-row-filters"></div>
        <div class="ws-courier-live-progress" ${p.streaming ? "" : "hidden"}>
          جاري تحليل الصفوف: <strong>${this._esc(String(p.processedRows || 0))}</strong>
          من <strong>${this._esc(String(p.totalRows || 0))}</strong>
        </div>
        <div class="ws-courier-rows-loading">جاري تحميل الصفوف...</div>
        <div class="ws-courier-rows-table-wrap"></div>
      </div>`;
    const root = container.querySelector(".ws-courier-rows") || container;
    root.__courierRowsHandlers = handlers;
    this._renderFilters(container, current, p.counts || {}, handlers);
    if (p.rows) {
      this._renderTable(container, p.rows, {
        filter: current,
        total: p.rows.length,
        paymentMethods: p.paymentMethods || [],
      });
      if (
        p.analysisId
        && !p.streaming
        && handlers.loadRows
        && !(p.paymentMethods || []).length
      ) {
        handlers.loadRows(p.analysisId, current);
      }
    } else if (p.analysisId && handlers.loadRows) {
      handlers.loadRows(p.analysisId, current);
    }
  },

  _renderFilters(container, current, counts, handlers) {
    const root = container.querySelector(".ws-courier-rows") || container;
    const filterEl = root.querySelector(".ws-courier-row-filters");
    if (!filterEl) return;
    filterEl.innerHTML = "";
    this._filters.forEach((filter) => {
      const count = counts && counts[filter] != null ? ` (${counts[filter]})` : "";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `ws-btn ws-btn-ghost ws-courier-filter${filter === current ? " active" : ""}`;
      btn.textContent = `${this._labels[filter]}${count}`;
      btn.dataset.filter = filter;
      btn.addEventListener("click", () => {
        root.dataset.currentFilter = filter;
        filterEl.querySelectorAll(".ws-courier-filter").forEach((item) => {
          item.classList.toggle("active", item.dataset.filter === filter);
        });
        const loading = root.querySelector(".ws-courier-rows-loading");
        if (loading) {
          loading.style.display = "block";
          loading.textContent = "جاري تحميل النتيجة...";
        }
        if (handlers.onFilter) handlers.onFilter(filter);
      });
      filterEl.appendChild(btn);
    });
  },

  _renderTable(container, rows, meta = {}) {
    const root = container.querySelector(".ws-courier-rows") || container;
    const loading = root.querySelector(".ws-courier-rows-loading");
    const wrap = root.querySelector(".ws-courier-rows-table-wrap");
    if (!wrap) return;
    if (loading) loading.style.display = "none";
    if (meta.filter) root.dataset.currentFilter = meta.filter;
    root.__courierRowsCache = rows;
    root.__courierRowsMeta = meta;

    if (!rows.length) {
      wrap.innerHTML = `
        <div class="ws-courier-empty">
          <strong>لا توجد صفوف بهذه الحالة</strong>
          <span>غيّر الفلتر لعرض بقية صفوف الكشف.</span>
        </div>`;
      return;
    }

    const isReturn = root.dataset.analysisMode === "return";
    const table = document.createElement("table");
    table.className = "ws-courier-table ws-courier-table-detailed";
    table.innerHTML = `<thead><tr>
      <th class="ws-col-index">#</th>
      <th>بيانات صف الكشف</th>
      <th>المبالغ</th>
      ${isReturn ? "" : "<th class=\"ws-col-payment-method\">طريقة الدفع</th>"}
      <th>الحالة</th>
      <th class="ws-col-reason">لماذا هذه النتيجة؟</th>
      <th>الطلب المحتمل في النظام</th>
      <th>الثقة</th>
    </tr></thead>`;
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const explanation = row.match_explanation || this._fallbackExplanation(row);
      const candidate = explanation.candidate || null;
      const tr = document.createElement("tr");
      tr.className = `ws-courier-row ws-courier-row-${row.match_status || "unmatched"}`;
      tr.innerHTML = `
        <td class="ws-col-index"><strong>${this._esc(String(row.row_index ?? "—"))}</strong>${row.source_page ? `<small>ص ${this._esc(String(row.source_page))}</small>` : ""}</td>
        <td>
          <div class="ws-courier-primary">${this._esc(row.normalized_order_number || row.raw_order_number || "رقم غير مقروء")}</div>
          ${explanation.manually_corrected && row.raw_order_number
            && String(row.raw_order_number) !== String(row.normalized_order_number || "")
            ? `<div class="ws-courier-original-order">المقروء أولاً: ${this._esc(row.raw_order_number)}</div>`
            : ""}
          <div class="ws-courier-secondary">${this._esc(row.customer_name || "الاسم/العنوان غير مقروء")}</div>
          <div class="ws-courier-secondary" dir="ltr">${this._esc(row.customer_phone || "—")}</div>
        </td>
        <td class="ws-courier-money">
          <span><small>التحصيل</small>${this._fmt(row.collected_amount)}</span>
          <span><small>الأجور</small>${this._fmt(row.delivery_fee)}</span>
          <span><small>الصافي</small>${this._fmt(row.net_amount)}</span>
        </td>
        ${isReturn ? "" : this._paymentMethodCell(row, meta)}
        <td>
          <span class="ws-courier-status ws-courier-status-${this._esc(row.match_status || "unmatched")}">${this._esc(explanation.status_label || this._statusLabels[row.match_status] || "غير معروف")}</span>
        </td>
        <td class="ws-col-reason">
          <div class="ws-courier-reason">${this._esc(explanation.message || "لا توجد تفاصيل.")}</div>
          <div class="ws-courier-action"><strong>المطلوب:</strong> ${this._esc(explanation.suggested_action || "راجع بيانات الصف.")}</div>
          ${this._checks(explanation.checks)}
        </td>
        <td class="ws-courier-candidate-cell">${this._candidate(candidate, row)}</td>
        <td>
          <div class="ws-courier-score"><strong>${Number(row.match_score || 0).toFixed(0)}%</strong><span>${this._scoreLabel(row.match_score)}</span></div>
        </td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.innerHTML = "";
    wrap.appendChild(table);
    this._bindRowActions(root);
  },

  _fallbackExplanation(row) {
    const candidate = row.invoice_snapshot || null;
    const label = this._statusLabels[row.match_status] || "غير معروف";
    if (row.match_status === "matched") {
      return {
        status_label: label,
        message: "تمت المطابقة اعتماداً على بيانات الطلب الموجودة في الكشف.",
        suggested_action: "لا يحتاج تدخلاً ما لم تظهر مشكلة مالية.",
        candidate,
      };
    }
    return {
      status_label: label,
      message: candidate
        ? "يوجد طلب محتمل، لكن بعض بيانات الكشف تختلف عن النظام."
        : "لم يُعثر على طلب مطابق بشكل كافٍ.",
      suggested_action: "قارن رقم الطلب والهاتف والمبلغ مع الصورة.",
      candidate,
    };
  },

  _candidate(candidate, row = {}) {
    const editButton = row.id
      ? `<button type="button" class="ws-courier-edit-order" data-row-id="${this._esc(row.id)}" title="صحح رقم الطلب المقروء من الكشف">✎ تصحيح رقم الطلب</button>`
      : "";
    const approveButton = (
      row.id
      && row.match_status === "review"
      && candidate
      && candidate.invoice_id
    )
      ? `<button type="button" class="ws-courier-approve-candidate" data-row-id="${this._esc(row.id)}" title="اعتماد الطلب المقترح كطلب صحيح">✓ هذا الطلب الصحيح</button>`
      : "";
    const canConfirmReplacement = Boolean(
      row.id
      && row.match_status === "matched"
      && candidate
      && candidate.invoice_id
      && !candidate.piece_settlement
      && !candidate.price_adjustment_plan
      && Number(row.collected_amount || 0) > 0
      && Number(candidate.total || 0) > 0
      && Number(row.collected_amount) !== Number(candidate.total)
    );
    const replacementButton = canConfirmReplacement
      ? `<button type="button" class="ws-courier-confirm-replacement" data-row-id="${this._esc(row.id)}">↺ اعتماد كاستبدال</button>`
      : "";
    if (!candidate) {
      return `
        <div class="ws-courier-candidate">
          <span class="ws-courier-no-candidate">لا يوجد طلب محتمل موثوق</span>
          ${editButton}
        </div>`;
    }
    const order = candidate.order_number || candidate.shipping_barcode || candidate.invoice_id || "—";
    const phones = Array.isArray(candidate.customer_phones) && candidate.customer_phones.length
      ? candidate.customer_phones
      : [candidate.customer_phone].filter(Boolean);
    return `
      <div class="ws-courier-candidate">
        <strong>${this._esc(String(order))}</strong>
        ${Array.isArray(candidate.shipping_barcodes) && candidate.shipping_barcodes.length > 1
          ? `<span class="ws-courier-all-barcodes">كل الباركودات: ${this._esc(candidate.shipping_barcodes.join(" · "))}</span>`
          : ""}
        ${candidate.piece_settlement
          ? `<span class="ws-courier-piece-settlement">تسديد قطعة فقط · المتبقي بعد التنفيذ: ${this._fmt(candidate.remaining_after_piece)}</span>`
          : ""}
        <span>${this._esc(candidate.customer_name || "اسم غير متوفر")}</span>
        <span dir="ltr">${this._esc(phones.length ? phones.join(" · ") : "—")}</span>
        <span>${this._fmt(candidate.total)} د.ع</span>
        ${Number(candidate.paid_amount || 0) > 0
          ? `<span class="ws-courier-payment-balance">المدفوع سابقاً: ${this._fmt(candidate.paid_amount)} · المتبقي: ${this._fmt(candidate.remaining_amount)}</span>`
          : ""}
        ${candidate.price_adjustment_plan
          ? `<span class="ws-courier-price-adjustment ${candidate.price_adjustment_plan.kind === "replacement" ? "is-replacement" : ""}">
              ${candidate.price_adjustment_plan.kind === "replacement" ? "استبدال" : "تصحيح سعر"}:
              ${this._fmt(candidate.price_adjustment_plan.original_total)} ← ${this._fmt(candidate.price_adjustment_plan.target_total)}
              عند التنفيذ
            </span>`
          : ""}
        ${candidate.payment_verified_in_accounts
          ? `<span class="ws-courier-payment-verified">✓ الدفعة مطابقة في الحسابات</span>`
          : ""}
        ${candidate.status ? `<span class="ws-courier-candidate-state">${this._esc(candidate.status)}${candidate.payment_status ? ` · ${this._esc(candidate.payment_status)}` : ""}</span>` : ""}
        ${this._allocations(candidate.payment_allocations)}
        ${replacementButton}
        ${approveButton}
        ${editButton}
      </div>`;
  },

  _bindRowActions(root) {
    root.querySelectorAll(".ws-courier-payment-method-select").forEach((select) => {
      select.addEventListener("change", async () => {
        const row = (root.__courierRowsCache || []).find(
          (item) => String(item.id) === String(select.dataset.rowId)
        );
        if (!row) return;
        const handler = (
          root.__courierRowsHandlers
          && root.__courierRowsHandlers.onPaymentMethodChange
        );
        if (!handler) {
          window.alert("حفظ طريقة الدفع غير متاح حالياً.");
          return;
        }
        const previous = String(row.treasury_account_id || select.dataset.previousValue || "");
        const status = select.parentElement.querySelector(".ws-courier-payment-method-status");
        select.disabled = true;
        select.classList.add("is-saving");
        if (status) status.textContent = "جاري الحفظ...";
        try {
          const data = await handler(row, Number(select.value));
          if (data && data.row) {
            root.__courierRowsCache = (root.__courierRowsCache || []).map(
              (item) => String(item.id) === String(row.id) ? data.row : item
            );
          } else {
            row.treasury_account_id = Number(select.value);
          }
          select.dataset.previousValue = select.value;
          select.classList.remove("is-saving");
          select.classList.add("is-saved");
          if (status) {
            status.textContent = data && data.bank_transfer_confirmed
              ? "تحصيل 0 — سيُسدد للبنك ✓"
              : "تم الحفظ ✓";
          }
          window.setTimeout(() => {
            select.classList.remove("is-saved");
            if (status) status.textContent = "";
          }, 1800);
        } catch (err) {
          select.value = previous;
          select.classList.remove("is-saving");
          if (status) status.textContent = "لم يُحفظ";
          window.alert(err.message || "تعذّر حفظ طريقة الدفع لهذا الصف.");
        } finally {
          select.disabled = false;
        }
      });
      const savedRow = (root.__courierRowsCache || []).find(
        (item) => String(item.id) === String(select.dataset.rowId)
      );
      const selectedOption = select.selectedOptions && select.selectedOptions[0];
      const savedAsZeroBankTransfer = Boolean(
        savedRow
        && Number(savedRow.collected_amount || 0) === 0
      );
      if (
        savedRow
        && Number(savedRow.treasury_account_id || 0) > 0
        && selectedOption
        && selectedOption.dataset.accountType === "bank"
        && (savedRow.collected_amount == null || savedAsZeroBankTransfer)
        && !this._reconciledBankRows.has(String(savedRow.id))
      ) {
        // Re-save every selected bank row whose statement collection is blank
        // or zero. Older rows may not have the confirmation marker yet, and
        // the one-shot guard prevents a render/save loop.
        this._reconciledBankRows.add(String(savedRow.id));
        window.setTimeout(() => {
          if (select.isConnected && !select.disabled) {
            select.dispatchEvent(new Event("change"));
          }
        }, 0);
      }
    });
    root.querySelectorAll(".ws-courier-approve-candidate").forEach((button) => {
      button.addEventListener("click", async () => {
        const row = (root.__courierRowsCache || []).find(
          (item) => String(item.id) === String(button.dataset.rowId)
        );
        if (!row) return;
        const handler = (
          root.__courierRowsHandlers
          && root.__courierRowsHandlers.onApproveCandidate
        );
        if (!handler) {
          window.alert("اعتماد الطلب غير متاح حالياً.");
          return;
        }
        button.disabled = true;
        button.textContent = "جاري الاعتماد...";
        try {
          const data = await handler(row);
          if (!data || !data.row) return;
          const currentFilter = root.dataset.currentFilter || "all";
          const rows = (root.__courierRowsCache || [])
            .map((item) => item.id === row.id ? data.row : item)
            .filter((item) => currentFilter === "all" || item.match_status === currentFilter);
          this.showRows(root, rows, {
            ...(root.__courierRowsMeta || {}),
            filter: currentFilter,
            counts: data.counts,
            total: data.counts
              ? (currentFilter === "all" ? data.counts.all : data.counts[currentFilter])
              : rows.length,
          });
        } catch (err) {
          if (err && err.status === 404) {
            const refresh = root.__courierRowsHandlers && root.__courierRowsHandlers.onFilter;
            if (refresh) await refresh(root.dataset.currentFilter || "all");
            window.alert("تم تحديث التحليل أو الصف؛ أعد المحاولة على الصف الحالي.");
            return;
          }
          button.disabled = false;
          button.textContent = "✓ هذا الطلب الصحيح";
          window.alert(err.message || "تعذّر اعتماد الطلب المقترح.");
        }
      });
    });
    root.querySelectorAll(".ws-courier-confirm-replacement").forEach((button) => {
      button.addEventListener("click", async () => {
        const row = (root.__courierRowsCache || []).find(
          (item) => String(item.id) === String(button.dataset.rowId)
        );
        if (!row) return;
        const explanation = row.match_explanation || this._fallbackExplanation(row);
        const candidate = explanation.candidate || {};
        const oldTotal = this._fmt(candidate.total);
        const newTotal = this._fmt(row.collected_amount);
        if (!window.confirm(
          `اعتماد هذا الطلب كاستبدال؟\nسيتغير السعر عند التنفيذ من ${oldTotal} إلى ${newTotal} د.ع وتصبح حالة الطلب استبدال.`
        )) return;
        const handler = (
          root.__courierRowsHandlers
          && root.__courierRowsHandlers.onConfirmReplacement
        );
        if (!handler) {
          window.alert("اعتماد الاستبدال غير متاح حالياً.");
          return;
        }
        button.disabled = true;
        button.textContent = "جاري الاعتماد...";
        try {
          const data = await handler(row);
          if (data && data.row) {
            root.__courierRowsCache = (root.__courierRowsCache || []).map(
              (item) => String(item.id) === String(row.id) ? data.row : item
            );
            this._renderTable(
              root,
              root.__courierRowsCache,
              { ...(root.__courierRowsMeta || {}), counts: data.counts }
            );
          }
        } catch (err) {
          button.disabled = false;
          button.textContent = "↺ اعتماد كاستبدال";
          window.alert(err.message || "تعذّر اعتماد الصف كاستبدال.");
        }
      });
    });
    root.querySelectorAll(".ws-courier-edit-order").forEach((button) => {
      button.addEventListener("click", () => {
        const row = (root.__courierRowsCache || []).find(
          (item) => String(item.id) === String(button.dataset.rowId)
        );
        if (row) this._openOrderEditor(root, row, button.closest("td"));
      });
    });
    root.querySelectorAll(".ws-courier-edit-order").forEach((editButton) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ws-courier-delete-row";
      button.dataset.rowId = editButton.dataset.rowId;
      button.textContent = root.dataset.analysisMode === "return" ? "استبعاد من الراجع" : "حذف من الحساب";
      editButton.insertAdjacentElement("afterend", button);
    });
    root.querySelectorAll(".ws-courier-delete-row").forEach((button) => {
      button.addEventListener("click", async () => {
        const row = (root.__courierRowsCache || []).find(
          (item) => String(item.id) === String(button.dataset.rowId)
        );
        if (!row) return;
        const order = row.normalized_order_number || row.raw_order_number || row.row_index;
        const isReturn = root.dataset.analysisMode === "return";
        if (!window.confirm(
          isReturn
            ? `استبعاد الصف ${order} من تنفيذ كشف الراجع؟\nلن يُرجع هذا الصف إلى المخزون، ولن يُحذف الطلب أو الصورة الأصلية.`
            : `حذف الصف ${order} من حسابات هذا الكشف؟\nلن يُحذف الطلب من النظام أو الصورة الأصلية.`
        )) return;
        const handler = root.__courierRowsHandlers && root.__courierRowsHandlers.onDeleteRow;
        if (!handler) {
          window.alert("حذف الصف غير متاح حالياً.");
          return;
        }
        button.disabled = true;
        button.textContent = "جاري الحذف...";
        try {
          const data = await handler(row);
          const remaining = (root.__courierRowsCache || []).filter(
            (item) => String(item.id) !== String(row.id)
          );
          this.showRows(root, remaining, {
            ...(root.__courierRowsMeta || {}),
            counts: data && data.counts,
            total: data && data.counts ? data.counts.all : remaining.length,
          });
        } catch (err) {
          button.disabled = false;
        button.textContent = root.dataset.analysisMode === "return" ? "استبعاد من الراجع" : "حذف من الحساب";
          window.alert(err.message || "تعذّر حذف الصف من الحساب.");
        }
      });
    });
  },

  _openOrderEditor(root, row, cell) {
    if (!cell) return;
    const explanation = row.match_explanation || this._fallbackExplanation(row);
    const candidate = explanation.candidate || {};
    const initial = row.normalized_order_number
      || row.raw_order_number
      || candidate.order_number
      || candidate.shipping_barcode
      || candidate.invoice_id
      || "";
    cell.innerHTML = `
      <form class="ws-courier-order-editor">
        <label>رقم الطلب الصحيح</label>
        <input type="text" inputmode="numeric" dir="ltr"
          placeholder="مثال: 210771" autocomplete="off">
        <div class="ws-courier-order-editor-actions">
          <button type="submit" class="ws-courier-order-save">حفظ</button>
          <button type="button" class="ws-courier-order-cancel">إلغاء</button>
        </div>
        <span class="ws-courier-order-error" role="alert"></span>
      </form>`;
    const form = cell.querySelector("form");
    const input = form.querySelector("input");
    const save = form.querySelector(".ws-courier-order-save");
    const error = form.querySelector(".ws-courier-order-error");
    input.value = String(initial);
    input.focus();
    input.select();

    form.querySelector(".ws-courier-order-cancel").addEventListener("click", () => {
      this._renderTable(root, root.__courierRowsCache || [], root.__courierRowsMeta || {});
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value) {
        error.textContent = "أدخل رقم الطلب الصحيح.";
        input.focus();
        return;
      }
      const handler = root.__courierRowsHandlers && root.__courierRowsHandlers.onChangeOrder;
      if (!handler) {
        error.textContent = "الحفظ غير متاح حالياً.";
        return;
      }
      input.disabled = true;
      save.disabled = true;
      save.textContent = "جاري الحفظ...";
      error.textContent = "";
      try {
        const data = await handler(row, value);
        if (data && data.row) {
          root.__courierRowsCache = (root.__courierRowsCache || []).map(
            (item) => item.id === row.id ? data.row : item
          );
          this._renderTable(root, root.__courierRowsCache, {
            ...(root.__courierRowsMeta || {}),
            counts: data.counts,
          });
        }
      } catch (err) {
        if (err && err.status === 404) {
          const remaining = (root.__courierRowsCache || []).filter(
            (item) => String(item.id) !== String(row.id)
          );
          this._renderTable(root, remaining, root.__courierRowsMeta || {});
          const refresh = root.__courierRowsHandlers && root.__courierRowsHandlers.onFilter;
          if (refresh) await refresh(root.dataset.currentFilter || "all");
          window.alert("هذا الصف يعود إلى تحليل سابق أو تم تحديثه. تم تحديث قائمة الصفوف، أعد المحاولة على الصف الحالي.");
          return;
        }
        input.disabled = false;
        save.disabled = false;
        save.textContent = "حفظ";
        error.textContent = err.message || "تعذر تغيير الطلب.";
        input.focus();
      }
    });
  },

  _checks(checks) {
    if (!Array.isArray(checks) || !checks.length) return "";
    const icons = { match: "✓", near: "~", mismatch: "×", unknown: "؟" };
    return `
      <div class="ws-courier-checks">
        ${checks.map((check) => `
          <span class="ws-courier-check ws-courier-check-${this._esc(check.state || "unknown")}" title="${this._esc(this._checkTitle(check))}">
            ${icons[check.state] || "؟"} ${this._esc(check.label || "")}
          </span>`).join("")}
      </div>`;
  },

  _paymentMethodCell(row, meta = {}) {
    const choices = Array.isArray(meta.paymentMethods) ? meta.paymentMethods : [];
    const fallback = choices.find((item) => item.is_default) || choices[0] || null;
    const selected = Number(row.treasury_account_id || (fallback && fallback.id) || 0);
    if (!choices.length) {
      return `
        <td class="ws-col-payment-method">
          <span class="ws-courier-payment-method-empty">الصندوق الافتراضي</span>
        </td>`;
    }
    return `
      <td class="ws-col-payment-method">
        <label class="ws-courier-payment-method">
          <span>اختر لكل صف</span>
          <select class="ws-courier-payment-method-select"
            data-row-id="${this._esc(row.id)}"
            data-previous-value="${this._esc(String(selected))}">
            ${choices.map((choice) => `
              <option value="${this._esc(String(choice.id))}"
                data-account-type="${this._esc(choice.account_type || "")}"${Number(choice.id) === selected ? " selected" : ""}>
                ${this._esc(choice.label || choice.name || "طريقة دفع")}
              </option>`).join("")}
          </select>
          <small class="ws-courier-payment-method-status" aria-live="polite"></small>
        </label>
      </td>`;
  },

  _checkTitle(check) {
    if (check.state === "match") return `${check.label}: مطابق`;
    if (check.state === "near") return `${check.label}: قريب ويحتمل خطأ قراءة`;
    if (check.state === "mismatch") {
      const left = check.key === "amount" ? this._fmt(check.statement) : (check.statement || "—");
      const right = check.key === "amount" ? this._fmt(check.system) : (check.system || "—");
      return `${check.label}: الكشف ${left} — النظام ${right}`;
    }
    return `${check.label}: لا توجد بيانات كافية`;
  },

  _scoreLabel(score) {
    const value = Number(score || 0);
    if (value >= 75) return "عالية";
    if (value >= 45) return "متوسطة";
    return "ضعيفة";
  },

  _fmt(value) {
    if (value == null) return "—";
    return Number(value).toLocaleString("en-US");
  },

  _allocations(items) {
    if (!items || !items.length) return "";
    return `<span class="ws-courier-allocation">${items
      .map((item) => `${this._esc(item.account_name || "حساب")}: ${this._fmt(item.amount)}`)
      .join(" + ")}</span>`;
  },

  _esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  },

  showRows(container, rows, meta = {}) {
    this._renderTable(container, rows || [], meta);
    const root = container.querySelector(".ws-courier-rows") || container;
    const progress = root.querySelector(".ws-courier-live-progress");
    if (progress) {
      progress.hidden = !meta.streaming;
      if (meta.streaming) {
        progress.innerHTML = `جاري تحليل الصفوف: <strong>${this._esc(String(meta.processed || 0))}</strong> من <strong>${this._esc(String(meta.total || 0))}</strong>`;
      }
    }
    if (meta.counts) {
      root.querySelectorAll(".ws-courier-filter").forEach((button) => {
        const filter = button.dataset.filter;
        const count = meta.counts[filter];
        button.textContent = `${this._labels[filter] || filter}${count != null ? ` (${count})` : ""}`;
      });
    }
  },

  upsertLiveRow(container, row, meta = {}) {
    const root = container.querySelector(".ws-courier-rows") || container;
    const cache = Array.isArray(root.__courierRowsCache)
      ? [...root.__courierRowsCache]
      : [];
    const existingIndex = cache.findIndex((item) => String(item.id) === String(row.id));
    if (existingIndex >= 0) cache[existingIndex] = row;
    else cache.push(row);
    cache.sort((left, right) => Number(left.row_index || 0) - Number(right.row_index || 0));

    const filter = root.dataset.currentFilter || "all";
    const visibleRows = filter === "all"
      ? cache
      : cache.filter((item) => item.match_status === filter);
    this.showRows(container, visibleRows, {
      ...meta,
      filter,
      streaming: true,
    });
    root.__courierRowsCache = cache;
  },
};

window.CourierRowsWindow = CourierRowsWindow;
