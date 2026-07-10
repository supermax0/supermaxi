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
        width: 100%; max-width: 440px;
        border-radius: 22px;
        border: 1px solid rgba(59, 130, 246, 0.28);
        background: linear-gradient(165deg, rgba(15, 23, 42, 0.99), rgba(30, 41, 59, 0.98));
        box-shadow: 0 28px 80px rgba(0, 0, 0, 0.55);
        overflow: hidden;
        animation: dfpSlideUp 0.26s cubic-bezier(0.16, 1, 0.3, 1);
      }
      .dfp-header {
        padding: 22px 24px 16px;
        border-bottom: 1px solid rgba(59, 130, 246, 0.16);
      }
      .dfp-icon {
        width: 52px; height: 52px; border-radius: 16px;
        display: flex; align-items: center; justify-content: center;
        font-size: 24px; margin-bottom: 12px;
        background: linear-gradient(135deg, rgba(34, 197, 94, 0.22), rgba(59, 130, 246, 0.18));
      }
      .dfp-title { margin: 0 0 6px; font-size: 20px; font-weight: 800; color: #f8fafc; }
      .dfp-subtitle { margin: 0; font-size: 13px; color: #94a3b8; line-height: 1.5; }
      .dfp-body { padding: 20px 24px; display: grid; gap: 14px; }
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
      }
      .dfp-btn.ghost {
        background: rgba(148, 163, 184, 0.1);
        color: #e2e8f0;
        border: 1px solid rgba(148, 163, 184, 0.18);
      }
      .dfp-btn:disabled { opacity: 0.6; cursor: not-allowed; }
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
      };
    } catch (_err) {
      return { city: "", items: [], total: 0 };
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
          <div class="dfp-icon">💰</div>
          <h3 class="dfp-title">${title}</h3>
          <p class="dfp-subtitle">أدخل أجرة التوصيل يدوياً. تُخصم من الإجمالي وتُسجّل كمصروف عند التسديد.</p>
        </div>
        <div class="dfp-body">
          <div class="dfp-row">
            <span>إجمالي الطلب</span>
            <strong id="dfpOrderTotal">${fmtMoney(orderTotal)}</strong>
          </div>
          <div class="dfp-field">
            <label for="dfpFeeInput">أجرة التوصيل</label>
            <div class="dfp-input-wrap">
              <input id="dfpFeeInput" class="dfp-input" type="text" inputmode="numeric" value="0" autocomplete="off">
              <button type="button" class="dfp-suggest" id="dfpSuggestBtn">اقتراح</button>
            </div>
            <p class="dfp-hint">اتركها 0 إذا لا توجد أجرة توصيل.</p>
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

    cancelBtn.addEventListener("click", function () {
      close();
      onCancel();
    });

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
      onConfirm(fee);
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
      suggestBtn.textContent = "اقتراح";
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
