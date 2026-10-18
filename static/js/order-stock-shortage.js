(function () {
  "use strict";

  var state = {
    orderIds: [],
    targetBranchId: null,
    context: null,
    currentItem: null,
    onRetry: null,
    trigger: null,
    blockingError: ""
  };
  var root = null;

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function number(value) {
    return Number(value || 0).toLocaleString("ar-IQ");
  }

  function localDateValue() {
    var date = new Date();
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0")
    ].join("-");
  }

  function notify(message, type) {
    if (typeof window.showToast === "function") {
      window.showToast(message, type || "info");
    }
  }

  function iconMarkup() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">' +
      '<path d="M21 8.5 12 3 3 8.5m18 0v7L12 21m9-12.5L12 14M3 8.5v7L12 21m-9-12.5L12 14m0 0v7"/>' +
      '<path d="M18.5 3.5v5m0 3v.1" stroke-width="2.3" stroke-linecap="round"/>' +
      '</svg>';
  }

  function ensureRoot() {
    if (root) return root;
    root = document.createElement("div");
    root.className = "stock-remedy";
    root.id = "agentStockRemedyModal";
    root.setAttribute("aria-hidden", "true");
    root.innerHTML =
      '<div class="stock-remedy__backdrop" data-sr-close></div>' +
      '<section class="stock-remedy__dialog" role="dialog" aria-modal="true" aria-labelledby="stockRemedyTitle">' +
        '<header class="stock-remedy__header">' +
          '<div class="stock-remedy__icon">' + iconMarkup() + '</div>' +
          '<div class="stock-remedy__heading">' +
            '<p class="stock-remedy__eyebrow">إجراء مطلوب قبل إنشاء الكشف</p>' +
            '<h2 class="stock-remedy__title" id="stockRemedyTitle">معالجة نقص المخزون</h2>' +
            '<p class="stock-remedy__subtitle">جمعنا كل المنتجات غير المتوفرة. عالج كل منتج بشراء سريع أو نقل مباشر بين الفروع.</p>' +
          '</div>' +
          '<button type="button" class="stock-remedy__close" data-sr-close aria-label="إغلاق">×</button>' +
        '</header>' +
        '<div class="stock-remedy__summary" id="stockRemedySummary"></div>' +
        '<main class="stock-remedy__body" id="stockRemedyBody" aria-live="polite"></main>' +
        '<footer class="stock-remedy__footer">' +
          '<span class="stock-remedy__footer-note">بعد إكمال الشراء أو النقل سنفحص المخزون مرة ثانية تلقائياً.</span>' +
          '<div style="display:flex;gap:9px;margin-inline-start:auto">' +
            '<button type="button" class="stock-remedy__btn stock-remedy__btn--ghost" data-sr-close>إغلاق</button>' +
            '<button type="button" class="stock-remedy__btn stock-remedy__btn--retry" id="stockRemedyRetry" hidden>إعادة محاولة الكشف</button>' +
          '</div>' +
        '</footer>' +
        '<aside class="stock-remedy__sheet" id="stockRemedySheet" aria-label="إجراء سريع">' +
          '<div class="stock-remedy__sheet-header">' +
            '<button type="button" class="stock-remedy__close" data-sr-sheet-close aria-label="رجوع">×</button>' +
            '<h3 id="stockRemedySheetTitle"></h3>' +
          '</div>' +
          '<div class="stock-remedy__sheet-body" id="stockRemedySheetBody"></div>' +
          '<div class="stock-remedy__sheet-footer">' +
            '<button type="button" class="stock-remedy__btn stock-remedy__btn--ghost" data-sr-sheet-close>رجوع</button>' +
            '<button type="button" class="stock-remedy__btn stock-remedy__btn--purchase" id="stockRemedySubmit">حفظ وتنفيذ</button>' +
          '</div>' +
        '</aside>' +
      '</section>';
    document.body.appendChild(root);

    root.addEventListener("click", function (event) {
      var close = event.target.closest("[data-sr-close]");
      if (close) { closeModal(); return; }
      var sheetClose = event.target.closest("[data-sr-sheet-close]");
      if (sheetClose) { closeSheet(); return; }
      var action = event.target.closest("[data-sr-action]");
      if (action) {
        var index = Number(action.getAttribute("data-sr-index"));
        var item = state.context && state.context.shortages ? state.context.shortages[index] : null;
        if (item) openSheet(action.getAttribute("data-sr-action"), item);
      }
    });
    root.querySelector("#stockRemedyRetry").addEventListener("click", retryReport);
    root.querySelector("#stockRemedySubmit").addEventListener("click", submitSheet);
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !root.classList.contains("is-open")) return;
      if (root.querySelector("#stockRemedySheet").classList.contains("is-open")) closeSheet();
      else closeModal();
    });
    return root;
  }

  function renderSummary(summary) {
    summary = summary || {};
    root.querySelector("#stockRemedySummary").innerHTML =
      '<div class="stock-remedy__stat"><span>منتجات ناقصة</span><strong>' + number(summary.products_count) + '</strong></div>' +
      '<div class="stock-remedy__stat"><span>وحدات مطلوبة</span><strong>' + number(summary.units_short) + '</strong></div>' +
      '<div class="stock-remedy__stat"><span>طلبات متأثرة</span><strong>' + number(summary.orders_count) + '</strong></div>';
  }

  function thumb(item) {
    if (item.image_url) {
      return '<div class="stock-remedy__thumb"><img src="' + escapeHtml(item.image_url) + '" alt=""></div>';
    }
    var initial = String(item.product_name || "م").trim().slice(0, 1);
    return '<div class="stock-remedy__thumb">' + escapeHtml(initial) + '</div>';
  }

  function renderCard(item, index) {
    var permissions = state.context.permissions || {};
    var branches = (item.branches || []).map(function (branch) {
      var target = Number(branch.id) === Number(item.target_branch_id) ? " • الوجهة" : "";
      return '<span class="stock-remedy__branch">' + escapeHtml(branch.name) + target + ' <b>' + number(branch.quantity) + '</b></span>';
    }).join("");
    var meta = "";
    if (item.sku) meta += '<span class="stock-remedy__tag">' + escapeHtml(item.sku) + '</span>';
    if (item.variant_color) meta += '<span class="stock-remedy__tag">اللون: ' + escapeHtml(item.variant_color) + '</span>';
    meta += '<span class="stock-remedy__tag">الطلبات: ' + (item.order_ids || []).map(function (id) { return "#" + number(id); }).join("، ") + '</span>';
    var colorNeedsPurchase = item.variant_color && Number(item.color_available || 0) < Number(item.required || 0);
    var canTransfer = !colorNeedsPurchase && permissions.can_complete_transfer && (item.branches || []).some(function (branch) {
      return Number(branch.id) !== Number(item.target_branch_id) && Number(branch.quantity) > 0;
    });
    var colorHint = item.variant_color
      ? '<div class="stock-remedy__hint" style="margin:0 0 8px">يُنقل اللون المطلوب فقط: <b>' + escapeHtml(item.variant_color) + '</b></div>'
      : '';
    return '<article class="stock-remedy__card">' +
      thumb(item) +
      '<div class="stock-remedy__product"><h3>' + escapeHtml(item.product_name) + '</h3><div class="stock-remedy__meta">' + meta + '</div></div>' +
      '<div class="stock-remedy__metrics">' +
        '<div class="stock-remedy__metric"><span>المطلوب</span><strong>' + number(item.required) + '</strong></div>' +
        '<div class="stock-remedy__metric"><span>المتوفر بالشركة</span><strong>' + number(item.available_total) + '</strong></div>' +
        '<div class="stock-remedy__metric stock-remedy__metric--danger"><span>النقص</span><strong>' + number(item.shortage) + '</strong></div>' +
      '</div>' +
      '<div class="stock-remedy__actions">' +
        '<button type="button" class="stock-remedy__btn stock-remedy__btn--purchase" data-sr-action="purchase" data-sr-index="' + index + '"' + (permissions.can_manage_inventory ? '' : ' disabled') + '>شراء سريع</button>' +
        '<button type="button" class="stock-remedy__btn stock-remedy__btn--transfer" data-sr-action="transfer" data-sr-index="' + index + '"' + (canTransfer ? '' : ' disabled') + '>نقل من فرع</button>' +
      '</div>' +
      colorHint +
      '<div class="stock-remedy__branches">' + branches + '</div>' +
    '</article>';
  }

  function renderContext(context) {
    state.context = context || {};
    var shortages = Array.isArray(state.context.shortages) ? state.context.shortages : [];
    renderSummary(state.context.summary || {
      products_count: shortages.length,
      units_short: shortages.reduce(function (sum, row) { return sum + Number(row.shortage || 0); }, 0),
      orders_count: state.orderIds.length
    });
    var body = root.querySelector("#stockRemedyBody");
    var retry = root.querySelector("#stockRemedyRetry");
    if (!shortages.length) {
      if (state.blockingError) {
        body.innerHTML = '<div class="stock-remedy__error"><h3>تعذر تأكيد جاهزية المخزون</h3><p>' + escapeHtml(state.blockingError) + '</p></div>';
        retry.hidden = typeof state.onRetry !== "function";
        return;
      }
      body.innerHTML = '<div class="stock-remedy__empty"><div class="stock-remedy__empty-icon">✓</div><h3>المخزون صار جاهزاً</h3><p>تمت معالجة كل النواقص. تقدر الآن تعيد إنشاء كشف المندوب.</p></div>';
      retry.hidden = typeof state.onRetry !== "function";
      return;
    }
    retry.hidden = true;
    body.innerHTML = '<div class="stock-remedy__list">' + shortages.map(renderCard).join("") + '</div>';
  }

  function renderLoading() {
    root.querySelector("#stockRemedySummary").innerHTML = "";
    root.querySelector("#stockRemedyBody").innerHTML = '<div class="stock-remedy__loading"><div class="stock-remedy__spinner"></div><p>جاري فحص مخزون كل المنتجات والفروع…</p></div>';
  }

  async function parseResponse(response) {
    var type = String(response.headers.get("content-type") || "");
    if (type.indexOf("application/json") !== -1) return response.json();
    var text = await response.text();
    return { success: false, error: text || "تعذر إكمال العملية" };
  }

  async function refreshContext() {
    renderLoading();
    try {
      var response = await fetch("/orders/stock-shortage-context", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ order_ids: state.orderIds, target_branch_id: state.targetBranchId })
      });
      var data = await parseResponse(response);
      if (!response.ok || data.success === false) throw new Error(data.error || "تعذر فحص المخزون");
      renderContext(data);
    } catch (error) {
      root.querySelector("#stockRemedyBody").innerHTML = '<div class="stock-remedy__error"><h3>تعذر تحميل تفاصيل المخزون</h3><p>' + escapeHtml(error.message) + '</p><button type="button" class="stock-remedy__btn stock-remedy__btn--ghost" id="stockRemedyRefresh" style="margin-top:14px">إعادة المحاولة</button></div>';
      var refresh = root.querySelector("#stockRemedyRefresh");
      if (refresh) refresh.addEventListener("click", refreshContext);
    }
  }

  function supplierOptions() {
    var suppliers = state.context.suppliers || [];
    return '<option value="">اختر المورد</option>' + suppliers.map(function (supplier) {
      return '<option value="' + Number(supplier.id) + '">' + escapeHtml(supplier.name) + '</option>';
    }).join("");
  }

  function branchOptions(selectedId) {
    return (state.context.branches || []).map(function (branch) {
      return '<option value="' + Number(branch.id) + '"' + (Number(branch.id) === Number(selectedId) ? ' selected' : '') + '>' + escapeHtml(branch.name) + '</option>';
    }).join("");
  }

  function purchaseForm(item) {
    var noSuppliers = !(state.context.suppliers || []).length;
    return '<form class="stock-remedy__form" id="stockRemedyActionForm" data-mode="purchase">' +
      '<div class="stock-remedy__hint">سيتم إنشاء فاتورة شراء مؤكدة وإضافة الكمية مباشرة إلى <b>' + escapeHtml(item.target_branch_name || "الفرع المختار") + '</b>.</div>' +
      '<div class="stock-remedy__field"><label>المورد</label><select name="supplier_id" required>' + supplierOptions() + '</select></div>' +
      (noSuppliers ? '<div class="stock-remedy__hint">لا يوجد مورد مسجل. أضف مورداً من صفحة الموردين ثم أعد المحاولة.</div>' : '') +
      '<div class="stock-remedy__field"><label>فرع الاستلام</label><select name="branch_id" required>' + branchOptions(item.target_branch_id) + '</select></div>' +
      '<div class="stock-remedy__field"><label>الكمية</label><input name="quantity" type="number" inputmode="numeric" min="1" value="' + Number(item.purchase_quantity || item.shortage || 1) + '" required></div>' +
      '<div class="stock-remedy__field"><label>سعر شراء الوحدة (د.ع)</label><input name="unit_cost" type="number" inputmode="numeric" min="0" value="' + Number(item.buy_price || 0) + '" required></div>' +
      '<div class="stock-remedy__field"><label>طريقة الشراء</label><select name="purchase_mode"><option value="credit">آجل — يضاف لحساب المورد</option><option value="cash">نقدي — يُخصم من الصندوق</option></select></div>' +
      '<div class="stock-remedy__field"><label>ملاحظة</label><textarea name="notes">شراء سريع لمعالجة نقص مخزون كشف المندوب</textarea></div>' +
    '</form>';
  }

  function transferForm(item) {
    var sources = (item.branches || []).filter(function (branch) {
      return Number(branch.id) !== Number(item.target_branch_id) && Number(branch.quantity) > 0;
    });
    var max = sources.reduce(function (value, branch) { return Math.max(value, Number(branch.quantity || 0)); }, 0);
    var qty = Math.max(1, Math.min(Number(item.transfer_quantity || item.shortage || 1), max || 1));
    var destination = (state.context.branches || []).find(function (branch) {
      return Number(branch.id) === Number(item.target_branch_id);
    }) || { id: item.target_branch_id, name: item.target_branch_name || "الفرع المطلوب" };
    var sourceOptions = sources.map(function (branch) {
      return '<option value="' + Number(branch.id) + '" data-stock="' + Number(branch.quantity) + '">' + escapeHtml(branch.name) + ' — متوفر ' + number(branch.quantity) + '</option>';
    }).join("");
    return '<form class="stock-remedy__form" id="stockRemedyActionForm" data-mode="transfer">' +
      '<div class="stock-remedy__hint">سيتم إنشاء حركة نقل رسمية وإكمال الإرسال والاستلام فوراً حتى يصبح المنتج جاهزاً للكشف.' +
        (item.variant_color ? ' اللون المنقول: <b>' + escapeHtml(item.variant_color) + '</b>.' : '') +
      '</div>' +
      '<div class="stock-remedy__field"><label>من فرع</label><select name="from_branch_id" required>' + sourceOptions + '</select></div>' +
      '<div class="stock-remedy__field"><label>إلى فرع</label><select name="to_branch_id" required><option value="' + Number(destination.id) + '">' + escapeHtml(destination.name) + '</option></select></div>' +
      '<div class="stock-remedy__field"><label>الكمية</label><input name="quantity" type="number" inputmode="numeric" min="1" max="' + max + '" value="' + qty + '" required></div>' +
      '<div class="stock-remedy__field"><label>ملاحظة</label><textarea name="note">نقل سريع لمعالجة نقص مخزون كشف المندوب</textarea></div>' +
    '</form>';
  }

  function openSheet(mode, item) {
    state.currentItem = item;
    var sheet = root.querySelector("#stockRemedySheet");
    sheet.setAttribute("data-mode", mode);
    root.querySelector("#stockRemedySheetTitle").textContent = (mode === "purchase" ? "شراء سريع — " : "نقل سريع — ") + item.product_name;
    root.querySelector("#stockRemedySheetBody").innerHTML = mode === "purchase" ? purchaseForm(item) : transferForm(item);
    var submit = root.querySelector("#stockRemedySubmit");
    submit.textContent = mode === "purchase" ? "حفظ فاتورة الشراء" : "نقل واستلام الآن";
    submit.className = "stock-remedy__btn " + (mode === "purchase" ? "stock-remedy__btn--purchase" : "stock-remedy__btn--transfer");
    submit.disabled = mode === "purchase" && !(state.context.suppliers || []).length;
    sheet.classList.add("is-open");
    var first = sheet.querySelector("select, input, textarea");
    if (first) first.focus();
  }

  function closeSheet() {
    if (!root) return;
    root.querySelector("#stockRemedySheet").classList.remove("is-open");
    state.currentItem = null;
  }

  async function submitSheet() {
    var form = root.querySelector("#stockRemedyActionForm");
    if (!form || !form.reportValidity() || !state.currentItem) return;
    var submit = root.querySelector("#stockRemedySubmit");
    var mode = form.getAttribute("data-mode");
    var values = new FormData(form);
    var item = state.currentItem;
    var endpoint;
    var payload;
    if (mode === "purchase") {
      endpoint = "/purchases/create";
      payload = {
        supplier_id: Number(values.get("supplier_id")),
        purchase_date: localDateValue(),
        purchase_mode: values.get("purchase_mode") || "credit",
        status: "confirmed",
        branch_id: Number(values.get("branch_id")),
        notes: values.get("notes") || "",
        items: [{
          product_id: Number(item.product_id),
          quantity: Number(values.get("quantity")),
          unit_cost: Number(values.get("unit_cost")),
          variant_color: item.variant_color || null
        }]
      };
    } else {
      endpoint = "/inventory/transfers/quick";
      payload = {
        from_branch_id: Number(values.get("from_branch_id")),
        to_branch_id: Number(values.get("to_branch_id")),
        product_id: Number(item.product_id),
        quantity: Number(values.get("quantity")),
        variant_color: item.variant_color || null,
        note: values.get("note") || ""
      };
    }
    submit.disabled = true;
    var original = submit.textContent;
    submit.textContent = "جاري التنفيذ…";
    try {
      var response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(payload)
      });
      var data = await parseResponse(response);
      if (!response.ok || data.success === false) throw new Error(data.error || "تعذر إكمال العملية");
      notify(data.message || (mode === "purchase" ? "تمت إضافة المشتريات للمخزون" : "تم نقل المخزون"), "success");
      closeSheet();
      state.blockingError = "";
      await refreshContext();
    } catch (error) {
      notify(error.message, "error");
      submit.disabled = false;
      submit.textContent = original;
    }
  }

  function closeModal() {
    if (!root) return;
    closeSheet();
    root.classList.remove("is-open");
    root.setAttribute("aria-hidden", "true");
    document.body.style.removeProperty("overflow");
    if (state.trigger && typeof state.trigger.focus === "function") state.trigger.focus();
  }

  function retryReport() {
    var callback = state.onRetry;
    closeModal();
    if (typeof callback === "function") callback();
  }

  function open(options) {
    options = options || {};
    ensureRoot();
    state.orderIds = (options.orderIds || (options.data && options.data.order_ids) || []).map(Number).filter(Boolean);
    state.targetBranchId = options.targetBranchId ? Number(options.targetBranchId) : null;
    state.onRetry = options.onRetry || null;
    state.blockingError = String(options.data && options.data.error || "");
    state.trigger = document.activeElement;
    root.classList.add("is-open");
    root.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    root.querySelector(".stock-remedy__close").focus();
    if (options.context && Array.isArray(options.context.shortages)) renderContext(options.context);
    else refreshContext();
  }

  window.FinoraStockShortage = { open: open, close: closeModal, refresh: refreshContext };
})();
