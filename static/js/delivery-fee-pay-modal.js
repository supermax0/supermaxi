/**
 * نافذة إدخال أجرة التوصيل عند التسديد — يدوياً فقط.
 */
(function (global) {
  "use strict";

  const STYLE_ID = "delivery-fee-pay-modal-styles";

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .dfp-overlay {
        position: fixed; inset: 0; z-index: 10050;
        background: rgba(2, 6, 23, 0.78);
        backdrop-filter: blur(10px);
        display: flex; align-items: center; justify-content: center;
        padding: 20px;
        animation: dfpFadeIn 0.2s ease-out;
      }
      @keyframes dfpFadeIn { from { opacity: 0; } to { opacity: 1; } }
      @keyframes dfpSlideUp {
        from { opacity: 0; transform: translateY(14px) scale(0.98); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      .dfp-box {
        width: 100%; max-width: 520px;
        border-radius: 26px;
        border: 1px solid rgba(59, 130, 246, 0.28);
        background: linear-gradient(165deg, rgba(15, 23, 42, 0.99), rgba(30, 41, 59, 0.98));
        box-shadow: 0 28px 80px rgba(0, 0, 0, 0.55);
        overflow: hidden;
        animation: dfpSlideUp 0.26s cubic-bezier(0.16, 1, 0.3, 1);
      }
      .dfp-header {
        position: relative;
        padding: 24px 26px 18px;
        border-bottom: 1px solid rgba(59, 130, 246, 0.16);
      }
      .dfp-header-main { display: flex; align-items: center; gap: 14px; }
      .dfp-icon {
        width: 54px; height: 54px; border-radius: 17px; flex: 0 0 auto;
        display: flex; align-items: center; justify-content: center;
        font-size: 25px;
        background: linear-gradient(135deg, rgba(34, 197, 94, 0.22), rgba(59, 130, 246, 0.18));
      }
      .dfp-title { margin: 0 0 6px; font-size: 20px; font-weight: 800; color: #f8fafc; }
      .dfp-subtitle { margin: 0; font-size: 13px; color: #94a3b8; line-height: 1.5; }
      .dfp-close {
        position: absolute; top: 14px; left: 14px; width: 34px; height: 34px;
        border: 1px solid rgba(148,163,184,.16); border-radius: 11px;
        background: rgba(15,23,42,.45); color: #94a3b8; cursor: pointer;
        font-size: 20px; line-height: 1;
      }
      .dfp-close:hover { color: #fff; background: rgba(148,163,184,.14); }
      .dfp-body { padding: 20px 26px; display: grid; gap: 16px; }
      .dfp-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 12px 14px; border-radius: 14px;
        background: rgba(15, 23, 42, 0.55);
        border: 1px solid rgba(148, 163, 184, 0.12);
      }
      .dfp-row span { color: #94a3b8; font-size: 13px; }
      .dfp-row strong { color: #f8fafc; font-size: 16px; font-weight: 800; }
      .dfp-row.net strong { color: #4ade80; }
      .dfp-field label {
        display: block; margin-bottom: 8px; font-size: 13px; font-weight: 700; color: #cbd5e1;
      }
      .dfp-section {
        padding: 15px; border-radius: 17px;
        background: rgba(15, 23, 42, 0.42);
        border: 1px solid rgba(148, 163, 184, 0.12);
      }
      .dfp-section-title { display:flex; align-items:center; gap:8px; margin-bottom:12px; color:#f1f5f9; font-size:14px; font-weight:800; }
      .dfp-input-wrap { display: flex; gap: 8px; }
      .dfp-input {
        flex: 1; padding: 14px 16px; border-radius: 14px;
        border: 1px solid rgba(148, 163, 184, 0.2);
        background: rgba(15, 23, 42, 0.7); color: #f8fafc;
        font-size: 18px; font-weight: 700; text-align: center; direction: ltr;
        font-family: inherit;
      }
      .dfp-input:focus {
        outline: none;
        border-color: rgba(59, 130, 246, 0.55);
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15);
      }
      .dfp-suggest {
        border: 1px solid rgba(148, 163, 184, 0.2);
        background: rgba(148, 163, 184, 0.1);
        color: #e2e8f0; border-radius: 14px; padding: 0 14px;
        font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap;
        font-family: inherit;
      }
      .dfp-suggest:hover { background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.35); }
      .dfp-hint { margin: 0; font-size: 12px; color: #64748b; }
      .dfp-select {
        width: 100%; padding: 13px 14px; border-radius: 13px;
        border: 1px solid rgba(148, 163, 184, 0.22);
        background: #111c30; color: #f8fafc; font: 700 14px inherit;
        cursor: pointer;
      }
      .dfp-select:focus { outline:none; border-color:rgba(59,130,246,.65); box-shadow:0 0 0 3px rgba(59,130,246,.13); }
      .dfp-select:disabled { opacity:.65; cursor:not-allowed; }
      .dfp-branch-hint { margin:8px 0 0; color:#94a3b8; font-size:12px; line-height:1.45; }
      .dfp-branch-hint.locked { color:#fbbf24; }
      .dfp-footer {
        padding: 16px 24px 22px;
        display: flex; gap: 10px;
        border-top: 1px solid rgba(59, 130, 246, 0.12);
      }
      .dfp-btn {
        flex: 1; border: 0; border-radius: 14px; padding: 14px 16px;
        font-size: 15px; font-weight: 800; cursor: pointer; font-family: inherit;
      }
      .dfp-btn.primary {
        background: linear-gradient(135deg, #22c55e, #16a34a);
        color: #fff;
        box-shadow: 0 10px 28px rgba(22, 163, 74, .22);
      }
      .dfp-btn.ghost {
        background: rgba(148, 163, 184, 0.1);
        color: #e2e8f0;
        border: 1px solid rgba(148, 163, 184, 0.18);
      }
      .dfp-btn:disabled { opacity: 0.6; cursor: not-allowed; }
      @media (max-width: 560px) {
        .dfp-overlay { padding: 10px; align-items: flex-end; }
        .dfp-box { border-radius: 24px 24px 16px 16px; max-height: 92vh; overflow-y: auto; }
        .dfp-header, .dfp-body, .dfp-footer { padding-left: 18px; padding-right: 18px; }
        .dfp-input-wrap { flex-direction: column; }
        .dfp-suggest { padding: 11px; }
      }
    `;
    document.head.appendChild(style);
  }

  function fmtMoney(n) {
    return new Intl.NumberFormat("ar-IQ").format(Math.max(0, Number(n) || 0)) + " د.ع";
  }

  function parseFee(value) {
    const n = parseInt(String(value || "").replace(/[^\d]/g, ""), 10);
    return Number.isFinite(n) ? Math.max(0, n) : 0;
  }

  async function fetchSuggestedFee(city, items) {
    const cleanItems = (items || [])
      .map((it) => ({
        product_id: it.product_id,
        qty: it.qty || it.quantity || 1,
      }))
      .filter((it) => it.product_id);
    if (!city || !cleanItems.length) return 0;
    try {
      const res = await fetch("/api/delivery-fee/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          city,
          items: cleanItems,
        }),
      });
      const data = await res.json();
      return data.ok ? Math.max(0, Number(data.fee) || 0) : 0;
    } catch (_err) {
      return 0;
    }
  }

  async function fetchOrderQuote(orderId) {
    try {
      const res = await fetch(`/orders/details/${orderId}`);
      if (!res.ok) return { city: "", items: [], total: 0 };
      const data = await res.json();
      const order = data.order || {};
      const items = (data.items || []).filter((it) => {
        const name = String(it.name || "").trim();
        if (name === "خصم كوبون") return false;
        if (Number(it.total || 0) < 0) return false;
        return !!it.product_id;
      });
      return {
        city: order.city || "",
        items,
        total: Number(order.total) || 0,
        branchId: Number(order.branch_id) || 0,
        branchName: order.branch_name || "",
        stockDeducted: !!order.stock_is_deducted,
      };
    } catch (_err) {
      return { city: "", items: [], total: 0 };
    }
  }

  async function fetchBranches() {
    try {
      const res = await fetch("/api/branch/list", { headers: { Accept: "application/json" } });
      if (!res.ok) return { branches: [], scheduledBranchId: 0, scheduleEnabled: false };
      const data = await res.json();
      return {
        branches: (data.branches || []).filter((branch) => Number(branch.id) > 0 && branch.is_active !== false),
        scheduledBranchId: Number(data.scheduled_branch_id) || 0,
        scheduleEnabled: !!data.branch_schedule_enabled,
      };
    } catch (_err) {
      return { branches: [], scheduledBranchId: 0, scheduleEnabled: false };
    }
  }

  /**
   * @param {object} opts
   * @param {number} [opts.orderId]
   * @param {number} [opts.orderTotal]
   * @param {string} [opts.customerCity]
   * @param {Array} [opts.items]
   * @param {string} [opts.title]
   * @param {string} [opts.confirmLabel]
   * @param {function(number): void} opts.onConfirm
   * @param {function(): void} [opts.onCancel]
   */
  function openDeliveryFeePayModal(opts) {
    ensureStyles();
    const options = opts || {};
    const onConfirm = typeof options.onConfirm === "function" ? options.onConfirm : function () {};
    const onCancel = typeof options.onCancel === "function" ? options.onCancel : function () {};

    let orderTotal = Math.max(0, Number(options.orderTotal) || 0);
    let customerCity = String(options.customerCity || "").trim();
    let quoteItems = Array.isArray(options.items) ? options.items.slice() : [];
    const orderId = options.orderId ? Number(options.orderId) : null;

    const overlay = document.createElement("div");
    overlay.className = "dfp-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const title = options.title || (orderId ? `تسديد الطلب #${orderId}` : "تسديد الطلب");
    const confirmLabel = options.confirmLabel || "تأكيد التسديد";

    overlay.innerHTML = `
      <div class="dfp-box">
        <div class="dfp-header">
          <button type="button" class="dfp-close" id="dfpCloseBtn" aria-label="إغلاق">×</button>
          <div class="dfp-header-main">
            <div class="dfp-icon">✓</div>
            <div>
              <h3 class="dfp-title">${title}</h3>
              <p class="dfp-subtitle">راجع تفاصيل التسديد وحدد أجرة التوصيل وفرع خصم المخزون.</p>
            </div>
          </div>
        </div>
        <div class="dfp-body">
          <div class="dfp-row">
            <span>إجمالي الطلب</span>
            <strong id="dfpOrderTotal">${fmtMoney(orderTotal)}</strong>
          </div>
          <div class="dfp-section">
            <div class="dfp-section-title"><span>🚚</span> أجرة التوصيل</div>
            <div class="dfp-field">
              <div class="dfp-input-wrap">
                <input id="dfpFeeInput" class="dfp-input" type="text" inputmode="numeric" value="0" autocomplete="off" aria-label="أجرة التوصيل">
                <button type="button" class="dfp-suggest" id="dfpSuggestBtn">احتساب المقترح</button>
              </div>
              <p class="dfp-hint">اتركها 0 إذا لم توجد أجرة توصيل.</p>
            </div>
          </div>
          <div class="dfp-section" id="dfpBranchSection" ${orderId ? "" : "hidden"}>
            <div class="dfp-section-title"><span>🏬</span> خصم المخزون</div>
            <div class="dfp-field">
              <label for="dfpBranchSelect">الفرع الذي تُخصم منه أصناف الطلب</label>
              <select id="dfpBranchSelect" class="dfp-select" disabled>
                <option value="">جاري تحميل الفروع...</option>
              </select>
              <p class="dfp-branch-hint" id="dfpBranchHint">سيتم التحقق من توفر الكميات في الفرع قبل إكمال التسديد.</p>
            </div>
          </div>
          <div class="dfp-row net">
            <span>الصافي بعد الأجرة</span>
            <strong id="dfpNetTotal">${fmtMoney(orderTotal)}</strong>
          </div>
        </div>
        <div class="dfp-footer">
          <button type="button" class="dfp-btn ghost" id="dfpCancelBtn">إلغاء</button>
          <button type="button" class="dfp-btn primary" id="dfpConfirmBtn">${confirmLabel}</button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    const feeInput = overlay.querySelector("#dfpFeeInput");
    const orderTotalEl = overlay.querySelector("#dfpOrderTotal");
    const netTotalEl = overlay.querySelector("#dfpNetTotal");
    const suggestBtn = overlay.querySelector("#dfpSuggestBtn");
    const confirmBtn = overlay.querySelector("#dfpConfirmBtn");
    const cancelBtn = overlay.querySelector("#dfpCancelBtn");
    const closeBtn = overlay.querySelector("#dfpCloseBtn");
    const branchSelect = overlay.querySelector("#dfpBranchSelect");
    const branchHint = overlay.querySelector("#dfpBranchHint");
    let currentBranchId = Number(options.branchId) || 0;
    let stockDeducted = !!options.stockDeducted;
    if (orderId) confirmBtn.disabled = true;

    function close() {
      overlay.remove();
    }

    function refreshNet() {
      const fee = parseFee(feeInput.value);
      const net = Math.max(0, orderTotal - fee);
      netTotalEl.textContent = fmtMoney(net);
    }

    feeInput.addEventListener("input", function () {
      feeInput.value = String(parseFee(feeInput.value));
      refreshNet();
    });

    function cancel() {
      close();
      onCancel();
    }

    cancelBtn.addEventListener("click", cancel);
    closeBtn.addEventListener("click", cancel);

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) {
        close();
        onCancel();
      }
    });

    confirmBtn.addEventListener("click", function () {
      const fee = parseFee(feeInput.value);
      if (fee > orderTotal) {
        alert("أجرة التوصيل لا يمكن أن تتجاوز إجمالي الطلب.");
        return;
      }
      confirmBtn.disabled = true;
      close();
      onConfirm(fee, { branchId: branchSelect ? (Number(branchSelect.value) || null) : null });
    });

    suggestBtn.addEventListener("click", async function () {
      suggestBtn.disabled = true;
      suggestBtn.textContent = "...";
      let fee = 0;
      if (orderId && (!customerCity || !quoteItems.length)) {
        const details = await fetchOrderQuote(orderId);
        if (details.total > 0) orderTotal = details.total;
        if (details.city) customerCity = details.city;
        if (details.items.length) quoteItems = details.items;
        orderTotalEl.textContent = fmtMoney(orderTotal);
      }
      fee = await fetchSuggestedFee(customerCity, quoteItems);
      feeInput.value = String(fee);
      refreshNet();
      suggestBtn.disabled = false;
      suggestBtn.textContent = "احتساب المقترح";
    });

    document.addEventListener("keydown", function onKey(e) {
      if (!document.body.contains(overlay)) {
        document.removeEventListener("keydown", onKey);
        return;
      }
      if (e.key === "Escape") {
        close();
        onCancel();
      }
      if (e.key === "Enter" && document.activeElement === feeInput) {
        e.preventDefault();
        confirmBtn.click();
      }
    });

    setTimeout(function () {
      feeInput.focus();
      feeInput.select();
    }, 60);

    if (orderId && (!customerCity || !quoteItems.length)) {
      fetchOrderQuote(orderId).then(function (details) {
        if (details.total > 0 && !options.orderTotal) {
          orderTotal = details.total;
          orderTotalEl.textContent = fmtMoney(orderTotal);
          refreshNet();
        }
        if (details.city) customerCity = details.city;
        if (details.items.length) quoteItems = details.items;
      });
    }

    if (orderId && branchSelect) {
      Promise.all([fetchBranches(), fetchOrderQuote(orderId)]).then(function (results) {
        const branchData = results[0];
        const branches = branchData.branches;
        const details = results[1];
        stockDeducted = details.stockDeducted;
        if (stockDeducted && details.branchId) {
          currentBranchId = details.branchId;
        } else if (branchData.scheduledBranchId) {
          currentBranchId = branchData.scheduledBranchId;
        } else if (details.branchId) {
          currentBranchId = details.branchId;
        }
        branchSelect.innerHTML = "";
        if (stockDeducted && currentBranchId && !branches.some((branch) => Number(branch.id) === currentBranchId)) {
          branches.unshift({
            id: currentBranchId,
            name: details.branchName || ("الفرع المسجّل #" + currentBranchId),
            is_active: false,
          });
        }
        if (!branches.length) {
          branchSelect.innerHTML = '<option value="">لا توجد فروع متاحة</option>';
          branchHint.textContent = "سيُستخدم فرع الطلب الافتراضي عند التسديد.";
          return;
        }
        branches.forEach(function (branch) {
          const option = document.createElement("option");
          option.value = String(branch.id);
          option.textContent = branch.name + (
            Number(branch.id) === branchData.scheduledBranchId ? " — حسب جدول الوقت" : ""
          );
          branchSelect.appendChild(option);
        });
        const fallback = branches[0];
        branchSelect.value = String(currentBranchId || fallback.id);
        branchSelect.disabled = stockDeducted;
        if (stockDeducted) {
          branchHint.textContent = "تم خصم مخزون الطلب سابقاً؛ لا يمكن تغيير الفرع عند التسديد.";
          branchHint.classList.add("locked");
        } else if (branchData.scheduledBranchId) {
          branchHint.textContent = "تم اختيار الفرع تلقائياً حسب جدول الوقت في الإعدادات، ويمكنك تغييره يدوياً.";
        } else if (branchData.scheduleEnabled) {
          branchHint.textContent = "جدول الوقت مفعّل لكنه غير مكتمل؛ اختر فرع الخصم يدوياً.";
          branchHint.classList.add("locked");
        }
      }).finally(function () {
        confirmBtn.disabled = false;
      });
    }
  }

  global.openDeliveryFeePayModal = openDeliveryFeePayModal;
  global.suggestDeliveryFeeForOrder = async function (orderId) {
    try {
      const res = await fetch(`/api/index/order-delivery-fee/${orderId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.ok) {
          return {
            fee: Math.max(0, Number(data.fee) || 0),
            city: data.city || "",
            total: Number(data.total) || 0,
          };
        }
      }
    } catch (_err) {
      /* fallback below */
    }
    const details = await fetchOrderQuote(orderId);
    const fee = await fetchSuggestedFee(details.city, details.items);
    return { fee, city: details.city, total: details.total };
  };
})(window);
