/** Shared order-return dialog: barcode verification + required stock destination. */
(function (global) {
  "use strict";

  const STYLE_ID = "return-stock-modal-styles";

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .rsm-overlay { position:fixed; inset:0; z-index:10070; display:flex; align-items:center; justify-content:center; padding:18px; background:rgba(2,6,23,.8); backdrop-filter:blur(9px); }
      .rsm-box { width:100%; max-width:500px; overflow:hidden; border-radius:24px; direction:rtl; color:#f8fafc; background:linear-gradient(155deg,#111c30,#172238); border:1px solid rgba(245,158,11,.3); box-shadow:0 30px 90px rgba(0,0,0,.58); animation:rsmIn .22s ease-out; }
      @keyframes rsmIn { from { opacity:0; transform:translateY(12px) scale(.98); } to { opacity:1; transform:none; } }
      .rsm-head { position:relative; display:flex; gap:14px; align-items:center; padding:23px 24px 18px; border-bottom:1px solid rgba(148,163,184,.13); }
      .rsm-icon { width:52px; height:52px; flex:0 0 auto; display:grid; place-items:center; border-radius:16px; font-size:25px; background:rgba(245,158,11,.14); color:#fbbf24; }
      .rsm-title { margin:0 0 5px; font-size:20px; font-weight:850; }
      .rsm-subtitle { margin:0; color:#94a3b8; font-size:13px; line-height:1.55; }
      .rsm-close { position:absolute; top:13px; left:13px; width:34px; height:34px; border-radius:11px; border:1px solid rgba(148,163,184,.16); background:rgba(15,23,42,.5); color:#94a3b8; font-size:20px; cursor:pointer; }
      .rsm-body { display:grid; gap:15px; padding:20px 24px; }
      .rsm-field { padding:15px; border:1px solid rgba(148,163,184,.13); border-radius:16px; background:rgba(15,23,42,.44); }
      .rsm-label { display:block; margin-bottom:9px; color:#e2e8f0; font-size:13px; font-weight:800; }
      .rsm-input,.rsm-select { width:100%; box-sizing:border-box; padding:13px 14px; border-radius:13px; border:1px solid rgba(148,163,184,.22); background:#0f1a2d; color:#f8fafc; font:700 14px inherit; }
      .rsm-input { direction:ltr; text-align:center; font-size:16px; }
      .rsm-input:focus,.rsm-select:focus { outline:none; border-color:#f59e0b; box-shadow:0 0 0 3px rgba(245,158,11,.13); }
      .rsm-readonly { opacity:.72; }
      .rsm-hint { margin:8px 0 0; color:#94a3b8; font-size:12px; line-height:1.45; }
      .rsm-error { display:none; margin:0; color:#fca5a5; font-size:12px; font-weight:700; }
      .rsm-error.show { display:block; }
      .rsm-foot { display:flex; gap:10px; padding:16px 24px 22px; border-top:1px solid rgba(148,163,184,.13); }
      .rsm-btn { flex:1; padding:14px; border-radius:13px; border:0; font:800 14px inherit; cursor:pointer; }
      .rsm-confirm { color:#fff; background:linear-gradient(135deg,#f59e0b,#d97706); box-shadow:0 10px 25px rgba(217,119,6,.2); }
      .rsm-cancel { color:#e2e8f0; background:rgba(148,163,184,.11); border:1px solid rgba(148,163,184,.17); }
      .rsm-btn:disabled { opacity:.55; cursor:not-allowed; }
      @media (max-width:540px) { .rsm-overlay{padding:10px;align-items:flex-end}.rsm-box{border-radius:23px 23px 15px 15px}.rsm-head,.rsm-body,.rsm-foot{padding-left:18px;padding-right:18px} }
    `;
    document.head.appendChild(style);
  }

  async function loadBranches() {
    const response = await fetch("/api/branch/list", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("تعذر تحميل الفروع");
    const data = await response.json();
    return (data.branches || []).filter(function (branch) {
      return Number(branch.id) > 0 && branch.is_active !== false;
    });
  }

  function openReturnStockModal(options) {
    ensureStyles();
    const opts = options || {};
    const orderId = Number(opts.orderId) || 0;
    const suppliedBarcode = String(opts.barcode || "").trim();
    const requireBarcode = opts.requireBarcode !== false;
    const onConfirm = typeof opts.onConfirm === "function" ? opts.onConfirm : function () {};
    const onCancel = typeof opts.onCancel === "function" ? opts.onCancel : function () {};

    const overlay = document.createElement("div");
    overlay.className = "rsm-overlay";
    overlay.setAttribute("data-return-stock-modal", "1");
    overlay.setAttribute("data-order-id", String(orderId));
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML = `
      <div class="rsm-box">
        <div class="rsm-head">
          <button type="button" class="rsm-close" aria-label="إغلاق">×</button>
          <div class="rsm-icon">↩</div>
          <div><h3 class="rsm-title">${opts.title || ("ترجيع الطلب #" + orderId)}</h3><p class="rsm-subtitle">حدد الفرع الذي ستُعاد إليه أصناف الطلب.</p></div>
        </div>
        <div class="rsm-body">
          <div class="rsm-field" ${requireBarcode || suppliedBarcode ? "" : "hidden"}>
            <label class="rsm-label" for="rsmBarcode">باركود الطلب</label>
            <input id="rsmBarcode" class="rsm-input ${suppliedBarcode ? "rsm-readonly" : ""}" type="text" value="${suppliedBarcode.replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;")}" ${suppliedBarcode ? "readonly" : ""} autocomplete="off" placeholder="امسح الباركود أو أدخله يدوياً">
          </div>
          <div class="rsm-field">
            <label class="rsm-label" for="rsmBranch">فرع إرجاع المخزون</label>
            <select id="rsmBranch" class="rsm-select" disabled><option value="">جاري تحميل الفروع...</option></select>
            <p class="rsm-hint">لن يُختار أي فرع افتراضياً؛ يجب تحديد وجهة المرتجع قبل التنفيذ.</p>
          </div>
          <p class="rsm-error" id="rsmError"></p>
        </div>
        <div class="rsm-foot"><button type="button" class="rsm-btn rsm-cancel">إلغاء</button><button type="button" class="rsm-btn rsm-confirm" disabled>تأكيد الترجيع</button></div>
      </div>`;
    document.body.appendChild(overlay);

    const barcodeInput = overlay.querySelector("#rsmBarcode");
    const branchSelect = overlay.querySelector("#rsmBranch");
    const errorEl = overlay.querySelector("#rsmError");
    const confirmBtn = overlay.querySelector(".rsm-confirm");

    function close(cancelled) { overlay.remove(); if (cancelled) onCancel(); }
    function showError(message) { errorEl.textContent = message; errorEl.classList.add("show"); }
    overlay.querySelector(".rsm-close").addEventListener("click", function () { close(true); });
    overlay.querySelector(".rsm-cancel").addEventListener("click", function () { close(true); });
    overlay.addEventListener("click", function (event) { if (event.target === overlay) close(true); });

    loadBranches().then(function (branches) {
      branchSelect.innerHTML = '<option value="">— اختر فرع إرجاع المخزون —</option>';
      branches.forEach(function (branch) {
        const option = document.createElement("option");
        option.value = String(branch.id);
        option.textContent = branch.name;
        branchSelect.appendChild(option);
      });
      branchSelect.disabled = !branches.length;
      confirmBtn.disabled = !branches.length;
      if (!branches.length) showError("لا توجد فروع نشطة متاحة لإرجاع المخزون.");
    }).catch(function (error) { branchSelect.innerHTML = '<option value="">تعذر تحميل الفروع</option>'; showError(error.message); });

    confirmBtn.addEventListener("click", function () {
      const barcode = String(barcodeInput ? barcodeInput.value : suppliedBarcode).trim();
      const returnBranchId = Number(branchSelect.value) || 0;
      errorEl.classList.remove("show");
      if (requireBarcode && !barcode) { showError("يجب مسح أو إدخال باركود الطلب."); if (barcodeInput) barcodeInput.focus(); return; }
      if (!returnBranchId) { showError("اختر الفرع الذي سيُعاد إليه المخزون."); branchSelect.focus(); return; }
      confirmBtn.disabled = true;
      close(false);
      onConfirm({ barcode: barcode, returnBranchId: returnBranchId });
    });

    overlay.addEventListener("keydown", function (event) {
      if (event.key === "Escape") close(true);
      if (event.key === "Enter") { event.preventDefault(); confirmBtn.click(); }
    });
    setTimeout(function () { (suppliedBarcode ? branchSelect : barcodeInput).focus(); }, 60);
  }

  global.openReturnStockModal = openReturnStockModal;
})(window);
