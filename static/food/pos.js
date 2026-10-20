(() => {
  "use strict";
  const root = document.querySelector('[data-food-page="cashier"]');
  if (!root) return;

  const $ = (selector, within = document) => within.querySelector(selector);
  const $$ = (selector, within = document) => [...within.querySelectorAll(selector)];
  const money = value => `${Number(value || 0).toLocaleString("en-IQ", {maximumFractionDigits: 3})} د.ع`;
  const esc = value => String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
  const storageKey = "finora.food.pos.cart.v2";
  const state = {
    config: null, products: [], categories: [], subcategories: {}, cart: [], customer: null,
    warehouseId: null, saleMode: "RETAIL", category: "", subcategory: "", feed: "catalog",
    page: 1, hasMore: false, view: localStorage.getItem("finora.food.pos.view") || "grid",
    invoiceDiscount: 0, note: "", totals: {subtotal: 0, discount: 0, tax: 0, total: 0},
    searchIndex: -1, priceCheck: false, validating: false, checkoutKey: null, lastInvoice: null,
  };

  async function api(path, options = {}) {
    const {headers: optionHeaders, ...rest} = options;
    const response = await fetch(`/food/api${path}`, {
      ...rest,
      headers: {"Content-Type": "application/json", ...(optionHeaders || {})},
    });
    const payload = await response.json().catch(() => ({ok: false, error: "استجابة غير صالحة"}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || "تعذر إكمال العملية");
    return payload.data;
  }
  function notify(message, error = false, undo = null) {
    const box = $("#foodNotice");
    box.className = `food-notice${error ? " error" : ""}`;
    box.innerHTML = `<span>${esc(message)}</span>${undo ? '<button type="button">تراجع</button>' : ""}`;
    box.hidden = false;
    if (undo) $("button", box).onclick = () => { undo(); box.hidden = true; };
    clearTimeout(box._timer);
    box._timer = setTimeout(() => box.hidden = true, 4200);
  }
  function openDialog(dialog) { if (!dialog.open) dialog.showModal(); }
  function closeDialogs() { $$("dialog[open]").forEach(dialog => dialog.close()); }
  function focusSearch() { requestAnimationFrame(() => $("#productSearch")?.focus()); }
  function newKey() { return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`; }
  function openPrint(url) {
    if (!url) return false;
    const popup = window.open(url, "_blank", "noopener");
    return Boolean(popup);
  }
  function lineUnit(line) { return line.product.units.find(unit => Number(unit.id) === Number(line.unitId)); }
  function lineMode(line) {
    const unit = lineUnit(line);
    return unit?.auto_wholesale && Number(line.quantity) >= Number(unit.wholesale_minimum || 1) && Number(unit.wholesale_price) > 0
      ? "WHOLESALE" : line.saleMode;
  }
  function linePrice(line) { const unit = lineUnit(line); return line.customPrice != null ? Number(line.customPrice) : (Number(lineMode(line) === "WHOLESALE" ? unit?.wholesale_price : unit?.retail_price) || 0); }
  function lineDiscount(line) {
    const gross = linePrice(line) * Number(line.quantity || 0), value = Number(line.discountValue ?? line.discount ?? 0);
    return line.discountType === "percent" ? Math.round(gross * value / 100) : value;
  }
  function persist() {
    localStorage.setItem(storageKey, JSON.stringify({cart: state.cart, customer: state.customer,
      warehouseId: state.warehouseId, saleMode: state.saleMode, invoiceDiscount: state.invoiceDiscount,
      note: state.note, savedAt: new Date().toISOString()}));
  }
  function restoreDraft() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (!saved?.cart?.length) return;
      state.cart = saved.cart; state.customer = saved.customer || null;
      state.saleMode = saved.saleMode === "WHOLESALE" ? "WHOLESALE" : "RETAIL";
      state.invoiceDiscount = Number(saved.invoiceDiscount || 0); state.note = saved.note || "";
      notify("تم استرجاع السلة غير المكتملة، وسيُراجع المخزون قبل الدفع");
    } catch (_) { localStorage.removeItem(storageKey); }
  }
  function cartPayload() {
    return {warehouse_id: state.warehouseId, customer_id: state.customer?.id || null,
      default_sale_mode: state.saleMode, invoice_discount: state.invoiceDiscount, note: state.note,
      items: state.cart.map(line => ({variant_id: line.product.id, unit_id: line.unitId,
        sale_mode: line.saleMode, quantity: line.quantity, price: line.customPrice,
        price_override_reason: line.priceReason || "", discount: lineDiscount(line),
        discount_type: line.discountType || "amount",
        discount_value: line.discountValue ?? line.discount ?? 0, note: line.note || ""}))};
  }

  async function loadCatalog({append = false, query = $("#productSearch").value.trim()} = {}) {
    if (!append) state.page = 1;
    const params = new URLSearchParams({q: query, category: state.category, subcategory: state.subcategory, mode: state.feed,
      page: state.page, per_page: 48});
    if (state.warehouseId) params.set("warehouse_id", state.warehouseId);
    const data = await api(`/cashier/products?${params}`);
    state.products = append ? [...state.products, ...data.products] : data.products;
    state.categories = data.categories; state.subcategories = data.subcategories || {}; state.hasMore = data.has_more;
    renderProducts(); renderCategories();
  }
  function renderCategories() {
    const values = [{key: "best", label: "⭐ الأكثر مبيعاً", feed: "best"},
      {key: "recent", label: "🕘 الأخيرة", feed: "recent"},
      {key: "", label: "الكل", feed: "catalog"},
      ...state.categories.map(value => ({key: value, label: value, feed: "catalog"}))];
    $("#categoryChips").innerHTML = values.map(item => `<button type="button" class="food-chip ${item.feed === "catalog" ? (state.feed === "catalog" && state.category === item.key ? "active" : "") : (state.feed === item.feed ? "active" : "")}" data-category="${esc(item.key)}" data-feed="${item.feed}">${esc(item.label)}</button>`).join("");
    $$(".food-chip", $("#categoryChips")).forEach(button => button.onclick = async () => {
      state.feed = button.dataset.feed; state.category = state.feed === "catalog" ? button.dataset.category : "";
      state.subcategory = "";
      await loadCatalog(); focusSearch();
    });
    const subBox = $("#subcategoryChips"), subs = state.feed === "catalog" ? (state.subcategories[state.category] || []) : [];
    subBox.hidden = !subs.length;
    subBox.innerHTML = subs.length ? ["", ...subs].map(value => `<button type="button" class="food-chip ${state.subcategory === value ? "active" : ""}" data-subcategory="${esc(value)}">${value ? esc(value) : "كل الفرعي"}</button>`).join("") : "";
    $$("[data-subcategory]", subBox).forEach(button => button.onclick = async () => {
      state.subcategory = button.dataset.subcategory;
      await loadCatalog(); focusSearch();
    });
  }
  function renderProducts() {
    const holder = $("#cashierProducts");
    holder.classList.toggle("food-product-list", state.view === "list");
    holder.innerHTML = state.products.length ? state.products.map(product => {
      const unit = product.units.find(row => row.id === product.default_sale_unit_id && row.can_sell !== false)
        || product.units.find(row => row.is_base && row.can_sell !== false) || product.units.find(row => row.can_sell !== false) || {};
      const disabled = product.track_stock && Number(product.stock_base) <= 0
        && !state.config?.settings?.allow_negative_stock;
      const variant = [product.flavor || product.variant_name, product.size].filter(Boolean).join(" • ");
      return `<article class="food-product-card ${disabled ? "is-disabled" : ""}" data-variant="${product.id}" tabindex="${disabled ? -1 : 0}" aria-disabled="${disabled}">
        <div class="food-product-main"><h3>${esc(product.product_name)}</h3><p>${esc(variant)}</p></div>
        <div class="food-product-price"><strong>${money(state.saleMode === "WHOLESALE" && unit.wholesale_price ? unit.wholesale_price : unit.retail_price)}</strong>${unit.wholesale_price ? `<small>جملة ${money(unit.wholesale_price)}</small>` : ""}</div>
        <button class="food-stock" data-stock="${product.id}" type="button">${Number(product.stock_base) <= Number(product.minimum_stock) && Number(product.stock_base) > 0 ? "⚠ منخفض · " : ""}${esc(product.stock_display)}</button>
      </article>`;
    }).join("") : '<div class="food-empty"><i class="fa fa-box-open"></i><b>لا توجد منتجات مطابقة</b><span>جرّب كلمة أخرى أو تصنيفًا مختلفًا.</span></div>';
    $$(".food-product-card:not(.is-disabled)", holder).forEach(card => {
      const add = event => { if (event.target.closest("[data-stock]")) return; addProduct(Number(card.dataset.variant)); };
      card.onclick = add; card.onkeydown = event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); add(event); } };
    });
    $$('[data-stock]', holder).forEach(button => button.onclick = event => { event.stopPropagation(); showBranchStock(Number(button.dataset.stock)); });
    $("#loadMoreProducts").hidden = !state.hasMore;
  }
  function addProduct(variantId, selectedUnitId = null, increment = 1) {
    const product = state.products.find(row => Number(row.id) === Number(variantId));
    if (!product) return;
    const unit = product.units.find(row => Number(row.id) === Number(selectedUnitId) && row.can_sell !== false)
      || product.units.find(row => Number(row.id) === Number(product.default_sale_unit_id) && row.can_sell !== false)
      || product.units.find(row => row.is_base && row.can_sell !== false) || product.units.find(row => row.can_sell !== false);
    if (!unit) return notify("لا توجد وحدة مفعلة للبيع لهذا المنتج", true);
    const existing = state.cart.find(line => Number(line.product.id) === Number(product.id)
      && Number(line.unitId) === Number(unit.id) && line.saleMode === state.saleMode);
    const amount = Number(increment);
    if (!(amount > 0)) return notify("كمية الباركود غير صالحة", true);
    if (existing) existing.quantity = Number(existing.quantity) + amount;
    else state.cart.push({product, unitId: unit.id, saleMode: state.saleMode, quantity: amount,
      discount: 0, discountType: "amount", discountValue: 0, note: ""});
    state.checkoutKey = null; persist(); renderCart(); validateCart(); focusSearch();
  }
  function updateQuantity(index, quantity) {
    const value = Number(quantity);
    if (!(value > 0)) return;
    state.cart[index].quantity = value; state.checkoutKey = null; persist(); renderCart(); validateCart();
  }
  function stageQuantity(index, quantity, row) {
    const value = Number(quantity);
    if (!(value > 0)) return;
    const line = state.cart[index];
    line.quantity = value; state.checkoutKey = null; persist();
    const price = linePrice(line), total = Math.max(0, price * value - lineDiscount(line));
    const summary = $('.food-cart-quantity span', row), amount = $('.food-cart-quantity strong', row);
    if (summary) summary.textContent = `${money(price)} × ${value.toLocaleString("en-IQ")}`;
    if (amount) amount.textContent = money(total);
    updateTotalsLocal(); validateCart();
  }
  function updateLineDiscount(index, discount) {
    const value = Math.max(0, Number(discount || 0));
    state.cart[index].discountValue = value; state.cart[index].discount = value;
    state.checkoutKey = null; persist(); renderCart(); validateCart();
  }
  function removeLine(index) {
    const [removed] = state.cart.splice(index, 1); state.checkoutKey = null; persist(); renderCart(); validateCart();
    notify(`تم حذف ${removed.product.product_name}`, false, () => { state.cart.splice(index, 0, removed); persist(); renderCart(); validateCart(); });
  }
  function renderCart() {
    const holder = $("#cartLines");
    const unitsCount = state.cart.reduce((sum, line) => sum + Number(line.quantity || 0), 0);
    $("#cartCount").textContent = `${state.cart.length} مادة · ${unitsCount.toLocaleString("en-IQ")} وحدة`;
    holder.innerHTML = state.cart.length ? state.cart.map((line, index) => {
      const unit = lineUnit(line), mode = lineMode(line), price = linePrice(line), total = price * Number(line.quantity) - lineDiscount(line) - Number(line.promotionDiscount || 0);
      const variant = [line.product.flavor || line.product.variant_name, line.product.size].filter(Boolean).join(" • ");
      return `<article class="food-cart-line ${mode !== line.saleMode ? "auto-wholesale" : ""}" data-line="${index}">
        <div class="food-cart-line-head"><div><h4>${esc(line.product.product_name)}</h4><small>${esc(variant)}</small></div><button data-remove type="button" aria-label="حذف"><i class="fa fa-trash"></i></button></div>
        <div class="food-cart-selectors"><select data-unit aria-label="الوحدة">${line.product.units.filter(row => row.can_sell !== false).map(row => `<option value="${row.id}" ${Number(row.id) === Number(line.unitId) ? "selected" : ""}>${esc(row.name)} · ${money(mode === "WHOLESALE" ? row.wholesale_price : row.retail_price)}</option>`).join("")}</select><select data-mode aria-label="السعر"><option value="RETAIL" ${mode === "RETAIL" ? "selected" : ""}>مفرد</option><option value="WHOLESALE" ${mode === "WHOLESALE" ? "selected" : ""}>جملة</option></select></div>
        <div class="food-cart-quantity"><button data-minus type="button">−</button><input data-quantity type="number" inputmode="decimal" min="${unit.quantity_step || 1}" step="${unit.quantity_step || 1}" value="${line.quantity}" aria-label="الكمية"><button data-plus type="button">+</button><span>${money(price)} × ${Number(line.quantity).toLocaleString("en-IQ", {maximumFractionDigits: 3})}</span><strong>${money(total)}</strong></div>
        ${state.config?.permissions?.["cashier.override_price"] ? `<label class="food-line-discount"><span>سعر مخصص</span><input data-custom-price type="number" inputmode="decimal" min="0" step="1" placeholder="${price}" value="${line.customPrice ?? ""}" aria-label="سعر مخصص"></label>` : ""}
        ${state.config?.permissions?.["cashier.discount_item"] ? `<label class="food-line-discount"><select data-discount-type aria-label="نوع خصم السطر"><option value="amount" ${line.discountType !== "percent" ? "selected" : ""}>خصم مبلغ</option><option value="percent" ${line.discountType === "percent" ? "selected" : ""}>خصم %</option></select><input data-line-discount type="number" inputmode="decimal" min="0" step="0.001" value="${Number(line.discountValue ?? line.discount ?? 0)}" aria-label="خصم السطر"></label>` : ""}
        ${line.promotionName ? `<small class="food-auto-price"><i class="fa fa-gift"></i> ${esc(line.promotionName)} · خصم ${money(line.promotionDiscount)}</small>` : ""}
        <button class="food-line-note" data-line-note type="button">${line.note ? `ملاحظة: ${esc(line.note)}` : "+ ملاحظة للسطر"}</button>
        ${mode !== line.saleMode ? '<small class="food-auto-price">تم تطبيق سعر الجملة تلقائياً</small>' : ""}
      </article>`;
    }).join("") : '<div class="food-empty"><i class="fa fa-barcode"></i><b>السلة فارغة</b><span>امسح باركود أو اختر منتجاً للبدء.</span></div>';
    $$('[data-line]', holder).forEach(row => {
      const index = Number(row.dataset.line);
      $('[data-minus]', row).onclick = () => { const step = Number(lineUnit(state.cart[index])?.quantity_step || 1); return state.cart[index].quantity > step ? updateQuantity(index, Number(state.cart[index].quantity) - step) : removeLine(index); };
      $('[data-plus]', row).onclick = () => updateQuantity(index, Number(state.cart[index].quantity) + Number(lineUnit(state.cart[index])?.quantity_step || 1));
      $('[data-quantity]', row).oninput = event => stageQuantity(index, event.target.value, row);
      $('[data-quantity]', row).onchange = event => updateQuantity(index, event.target.value);
      const lineDiscount = $('[data-line-discount]', row);
      if (lineDiscount) lineDiscount.onchange = event => updateLineDiscount(index, event.target.value);
      const discountType = $('[data-discount-type]', row);
      if (discountType) discountType.onchange = event => { state.cart[index].discountType = event.target.value; state.checkoutKey = null; persist(); renderCart(); validateCart(); };
      const customPrice = $('[data-custom-price]', row);
      if (customPrice) customPrice.onchange = event => { const value = event.target.value; state.cart[index].customPrice = value === "" ? null : Math.max(0, Number(value)); state.cart[index].priceReason = state.cart[index].customPrice == null ? "" : (prompt("سبب تغيير السعر", state.cart[index].priceReason || "") || ""); state.checkoutKey = null; persist(); renderCart(); validateCart(); };
      $('[data-line-note]', row).onclick = () => { const value = prompt("ملاحظة السطر", state.cart[index].note || ""); if (value !== null) { state.cart[index].note = value.trim(); persist(); renderCart(); } };
      $('[data-unit]', row).onchange = event => { state.cart[index].unitId = Number(event.target.value); state.checkoutKey = null; persist(); renderCart(); validateCart(); };
      $('[data-mode]', row).onchange = event => { state.cart[index].saleMode = event.target.value; state.checkoutKey = null; persist(); renderCart(); validateCart(); };
      $('[data-remove]', row).onclick = () => removeLine(index);
    });
    updateTotalsLocal();
  }
  function updateTotalsLocal() {
    const subtotal = state.cart.reduce((sum, line) => sum + linePrice(line) * Number(line.quantity) - lineDiscount(line) - Number(line.promotionDiscount || 0), 0);
    state.totals = {subtotal, discount: state.invoiceDiscount, tax: 0, total: Math.max(0, subtotal - state.invoiceDiscount)};
    $("#cartSubtotal").textContent = money(subtotal); $("#cartDiscount").textContent = money(state.invoiceDiscount);
    $("#cartTax").textContent = money(0); $("#cartTotal").textContent = money(state.totals.total);
    $("#completeSale span").textContent = `الدفع • ${money(state.totals.total)}`;
    $("#completeSale").disabled = !state.cart.length || state.validating;
    $("#mobileCartButton").textContent = `السلة • ${state.cart.length} مادة • ${money(state.totals.total)}`;
  }
  let validationTimer;
  function validateCart() {
    clearTimeout(validationTimer);
    validationTimer = setTimeout(async () => {
      if (!state.cart.length) return;
      state.validating = true; updateTotalsLocal();
      try {
        const result = await api('/cashier/validate-cart', {method: 'POST', body: JSON.stringify(cartPayload())});
        state.totals = result;
        result.items.forEach((item, index) => {
          const line = state.cart[index]; if (!line) return;
          if (item.auto_wholesale_applied && lineMode(line) !== "WHOLESALE") notify(`تم تطبيق سعر الجملة على ${line.product.product_name}`);
          if (item.promotion_name && line.promotionName !== item.promotion_name)
            notify(`تم تطبيق عرض ${item.promotion_name} على ${line.product.product_name}`);
          line.promotionName = item.promotion_name || null;
          line.promotionDiscount = Number(item.promotion_discount || 0);
        });
        renderCart(); state.totals = result;
        const shortage = result.items.find(item => !item.stock_ok);
        if (shortage) notify(`المخزون غير كافٍ. المتاح: ${shortage.available_display}`, true);
        $("#cartSubtotal").textContent = money(result.subtotal); $("#cartDiscount").textContent = money(result.discount);
        $("#cartTotal").textContent = money(result.total); $("#completeSale span").textContent = `الدفع • ${money(result.total)}`;
        $("#completeSale").disabled = !result.valid;
      } catch (error) { notify(error.message, true); }
      finally { state.validating = false; }
    }, 180);
  }

  async function scanOrSearch(value, forceScan = false) {
    const query = String(value || "").trim(); if (!query) return;
    if (forceScan) {
      try {
        const params = new URLSearchParams(); if (state.warehouseId) params.set("warehouse_id", state.warehouseId);
        const product = await api(`/barcode/${encodeURIComponent(query)}?${params}`);
        if (state.priceCheck) { showPriceCheck(product); state.priceCheck = false; return; }
        if (!state.products.some(row => row.id === product.id)) state.products.push(product);
        addProduct(product.id, product.selected_unit_id, product.scale_quantity || 1); $("#productSearch").value = ""; hideSuggestions(); return;
      } catch (_) { /* Continue with ranked text results. */ }
    }
    await loadCatalog({query});
    renderSuggestions(query);
  }
  function renderSuggestions(query) {
    const box = $("#searchSuggestions");
    if (!query || !state.products.length) return hideSuggestions();
    box.innerHTML = state.products.slice(0, 8).map((product, index) => `<button type="button" data-index="${index}" class="${index === state.searchIndex ? "active" : ""}"><span><b>${esc(product.product_name)}</b><small>${esc([product.variant_name, product.flavor, product.size].filter(Boolean).join(" • "))}</small></span><strong>${money((product.units.find(unit => unit.id === product.default_sale_unit_id) || product.units[0])?.retail_price)}</strong></button>`).join("");
    box.hidden = false;
    $$('button', box).forEach(button => button.onclick = () => { addProduct(state.products[Number(button.dataset.index)].id); $("#productSearch").value = ""; hideSuggestions(); });
  }
  function hideSuggestions() { state.searchIndex = -1; $("#searchSuggestions").hidden = true; }

  function renderCustomerResults(customers) {
    $("#customerResults").innerHTML = `<button type="button" data-customer="cash"><span><b>عميل نقدي</b><small>العميل الافتراضي</small></span></button>` + customers.filter(row => row.phone !== "FOOD-WALK-IN").map(row => `<button type="button" data-customer="${row.id}"><span><b>${esc(row.name)}</b><small>${esc(row.phone || "")}${row.address ? ` · ${esc(row.address)}` : ""}</small></span><strong>الرصيد: ${money(row.debt)}</strong></button>`).join("");
    $$('[data-customer]', $("#customerResults")).forEach(button => button.onclick = () => {
      state.customer = button.dataset.customer === "cash" ? null : customers.find(row => Number(row.id) === Number(button.dataset.customer));
      $("#customerButton span").textContent = state.customer?.name || "عميل نقدي"; persist(); $("#customerDialog").close(); focusSearch();
    });
  }
  async function openCustomers() { openDialog($("#customerDialog")); $("#customerSearch").value = ""; renderCustomerResults(await api('/customers')); $("#customerSearch").focus(); }
  let customerTimer;
  $("#customerSearch").oninput = () => { clearTimeout(customerTimer); customerTimer = setTimeout(async () => renderCustomerResults(await api(`/customers?q=${encodeURIComponent($("#customerSearch").value)}`)), 220); };
  $("#showNewCustomer").onclick = () => $("#quickCustomerForm").hidden = !$("#quickCustomerForm").hidden;
  $("#quickCustomerForm").onsubmit = async event => { event.preventDefault(); try { const customer = await api('/customers', {method: 'POST', body: JSON.stringify({name: $("#newCustomerName").value, phone: $("#newCustomerPhone").value, address: $("#newCustomerAddress").value})}); state.customer = customer; $("#customerButton span").textContent = customer.name; persist(); $("#customerDialog").close(); focusSearch(); } catch (error) { notify(error.message, true); } };

  function quickCashValues(total) {
    if (total <= 0) return [];
    const scales = [1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000];
    const values = scales.map(scale => Math.ceil(total / scale) * scale).filter(value => value >= total);
    return [...new Set([total, ...values])].sort((a, b) => a - b).slice(0, 4);
  }
  function setPaymentMethod(method) {
    $$('#paymentMethods button').forEach(button => button.classList.toggle('active', button.dataset.method === method));
    $("#singlePayment").hidden = method === 'mixed'; $("#mixedPayment").hidden = method !== 'mixed';
    if (method === 'cash') { $("#cashReceived").value = state.totals.total; renderCashChange(); }
    if (method === 'mixed') renderMixedPayments();
  }
  function openPayment() {
    if (!state.cart.length) return;
    $("#paymentTotal").textContent = money(state.totals.total);
    $("#quickCash").innerHTML = quickCashValues(state.totals.total).map(value => `<button type="button" data-cash="${value}">${money(value)}</button>`).join("");
    $$('[data-cash]').forEach(button => button.onclick = () => { $("#cashReceived").value = button.dataset.cash; renderCashChange(); });
    state.checkoutKey = state.checkoutKey || newKey(); setPaymentMethod('cash'); openDialog($("#paymentDialog")); $("#cashReceived").focus();
  }
  function renderCashChange() { $("#cashChange").textContent = money(Math.max(0, Number($("#cashReceived").value || 0) - state.totals.total)); }
  $("#cashReceived").oninput = renderCashChange;
  $$('#paymentMethods button').forEach(button => button.onclick = () => setPaymentMethod(button.dataset.method));
  function renderMixedPayments() {
    const creditButton = state.config.permissions['cashier.sell_credit'] ? '<option value="credit">آجل</option>' : '';
    $("#mixedPayment").innerHTML = ['cash', 'card', 'transfer', 'credit'].filter(method => method !== 'credit' || creditButton).map((method, index) => `<label>${{cash:'نقدي',card:'بطاقة',transfer:'تحويل',credit:'آجل'}[method]}<input data-mixed="${method}" type="number" min="0" value="${index === 0 ? state.totals.total : 0}"></label>`).join('') + '<div>المتبقي <strong id="mixedRemaining">0 د.ع</strong></div>';
    $$('[data-mixed]').forEach(input => input.oninput = renderMixedRemaining); renderMixedRemaining();
  }
  function renderMixedRemaining() { const paid = $$('[data-mixed]').reduce((sum, input) => sum + Number(input.value || 0), 0); $("#mixedRemaining").textContent = money(state.totals.total - paid); }
  function paymentPayload() {
    const method = $('#paymentMethods button.active').dataset.method;
    if (method === 'mixed') return $$('[data-mixed]').map(input => ({method: input.dataset.mixed, amount: Number(input.value || 0), received: Number(input.value || 0)})).filter(row => row.amount > 0);
    if (method === 'credit') return [{method, amount: state.totals.total}];
    if (method === 'cash') return [{method, amount: state.totals.total, received: Number($("#cashReceived").value || 0)}];
    return [{method, amount: state.totals.total}];
  }
  $("#confirmPayment").onclick = async () => {
    const button = $("#confirmPayment"); button.disabled = true; $("#paymentError").hidden = true;
    try {
      const payload = {...cartPayload(), payments: paymentPayload(), idempotency_key: state.checkoutKey};
      const result = await api('/sales', {method: 'POST', headers: {'Idempotency-Key': state.checkoutKey}, body: JSON.stringify(payload)});
      state.lastInvoice = result;
      $("#paymentDialog").close(); notify(`✓ تمت عملية البيع · فاتورة ${result.invoice_no}`);
      if (state.config.settings.auto_print === 'always' && !openPrint(result.print_url))
        notify("تم حفظ الفاتورة، تعذر فتح نافذة الطباعة. استخدم إعادة الطباعة.", true);
      if (state.config.settings.auto_print === 'ask' && confirm("تم حفظ الفاتورة. هل تريد طباعتها الآن؟"))
        openPrint(result.print_url);
      state.cart = []; state.invoiceDiscount = 0; state.note = ''; state.customer = null; state.checkoutKey = null;
      localStorage.removeItem(storageKey); $("#customerButton span").textContent = "عميل نقدي"; renderCart();
      await loadCatalog(); focusSearch();
    } catch (error) { $("#paymentError").textContent = error.message; $("#paymentError").hidden = false; }
    finally { button.disabled = false; }
  };

  async function openHolds() { openDialog($("#holdsDialog")); const rows = await api('/cashier/holds'); renderHolds(rows); }
  function renderHolds(rows) {
    $("#holdsCount").textContent = rows.length;
    $("#holdsList").innerHTML = rows.length ? rows.map(row => `<article class="food-hold-row"><div><b>#${esc(row.hold_no)}</b><span>${esc(row.customer_name)} · ${money(row.total)}</span><small>${window.FinoraTime.dateTime(row.created_at)}</small></div><button data-restore="${row.id}" class="food-primary" type="button">استرجاع</button>${state.config.permissions['cashier.void_sale'] ? `<button data-delete-hold="${row.id}" class="food-remove" type="button">إلغاء</button>` : ''}</article>`).join('') : '<div class="food-empty">لا توجد فواتير معلقة</div>';
    $$('[data-restore]').forEach(button => button.onclick = async () => { try { const hold = await api(`/cashier/holds/${button.dataset.restore}/restore`, {method: 'POST'}); (hold.products || []).forEach(product => { if (!state.products.some(row => row.id === product.id)) state.products.push(product); }); state.cart = hold.items.map(item => { const product = state.products.find(row => row.id === item.variant_id); return product ? {product, unitId: item.unit_id, quantity: item.quantity, saleMode: item.sale_mode, discount: item.discount || 0, discountType: item.discount_type || 'amount', discountValue: item.discount_value ?? item.discount ?? 0, customPrice: item.price ?? null, priceReason: item.price_override_reason || '', note: item.note || ''} : null; }).filter(Boolean); state.customer = hold.customer_id ? {id: hold.customer_id, name: hold.customer_name} : null; state.invoiceDiscount = hold.invoice_discount; state.note = hold.note || ''; persist(); renderCart(); validateCart(); $("#holdsDialog").close(); focusSearch(); } catch (error) { notify(error.message, true); } });
    $$('[data-delete-hold]').forEach(button => button.onclick = async () => { try { await api(`/cashier/holds/${button.dataset.deleteHold}`, {method: 'DELETE'}); renderHolds(await api('/cashier/holds')); } catch (error) { notify(error.message, true); } });
  }
  $("#holdSale").onclick = async () => { if (!state.cart.length) return; try { await api('/cashier/holds', {method: 'POST', body: JSON.stringify(cartPayload())}); state.cart = []; state.invoiceDiscount = 0; state.note = ''; localStorage.removeItem(storageKey); renderCart(); const rows = await api('/cashier/holds'); $("#holdsCount").textContent = rows.length; notify("تم تعليق الفاتورة"); focusSearch(); } catch (error) { notify(error.message, true); } };

  async function showBranchStock(variantId) { try { const rows = await api(`/cashier/stock/${variantId}`); $("#infoDialogTitle").textContent = "مخزون الفروع"; $("#infoDialogSubtitle").textContent = "للعرض فقط"; $("#infoDialogBody").innerHTML = rows.map(row => `<div class="food-stock-row"><span>${esc(row.branch_name)}</span><strong>${esc(row.stock_display || '0')}</strong></div>`).join('') || '<div class="food-empty">لا يوجد مخزون مسجل</div>'; openDialog($("#infoDialog")); } catch (error) { notify(error.message, true); } }
  function showPriceCheck(product) { $("#infoDialogTitle").textContent = product.product_name; $("#infoDialogSubtitle").textContent = [product.variant_name, product.flavor, product.size].filter(Boolean).join(' • '); $("#infoDialogBody").innerHTML = `<div class="food-price-check">${product.units.filter(unit => unit.can_sell !== false).map(unit => `<div><b>${esc(unit.name)}</b><span>${money(unit.retail_price)}</span><small>جملة ${money(unit.wholesale_price)}</small></div>`).join('')}<p>المخزون: ${esc(product.stock_display)}</p><button id="addCheckedProduct" class="food-primary" type="button">إضافة للسلة</button></div>`; openDialog($("#infoDialog")); $("#addCheckedProduct").onclick = () => { if (!state.products.some(row => row.id === product.id)) state.products.push(product); addProduct(product.id, product.selected_unit_id); $("#infoDialog").close(); }; }
  async function openReturns() { if (!state.config.permissions['cashier.return']) return; openDialog($("#returnDialog")); $("#returnSearch").value = ''; renderReturnResults(await api('/cashier/returns/search')); $("#returnSearch").focus(); }
  function renderReturnResults(rows) { $("#returnResults").innerHTML = rows.map(invoice => `<article class="food-return-invoice"><header><b>${esc(invoice.invoice_no)}</b><span>${esc(invoice.customer_name)} · ${money(invoice.total)}</span></header>${invoice.items.map(item => `<label>${esc(item.product_name)} · ${esc(item.unit_name)}<small>متاح ${esc(item.returnable_quantity)} من ${esc(item.quantity)}</small><input data-return-line="${item.snapshot_id}" type="number" min="0" max="${item.returnable_quantity}" value="0"></label>`).join('')}<select data-refund><option value="cash">استرداد نقدي</option><option value="card">بطاقة</option><option value="transfer">تحويل</option><option value="credit">تخفيض الذمة</option></select><input data-reason placeholder="سبب المرتجع"><button data-return-invoice="${invoice.id}" class="food-primary" type="button">تأكيد المرتجع</button></article>`).join('') || '<div class="food-empty">لا توجد فواتير مطابقة</div>'; $$('[data-return-invoice]').forEach(button => button.onclick = async () => { const card = button.closest('.food-return-invoice'); const items = $$('[data-return-line]', card).map(input => ({snapshot_id: Number(input.dataset.returnLine), quantity: Number(input.value || 0)})).filter(item => item.quantity > 0); try { const result = await api('/cashier/returns', {method: 'POST', body: JSON.stringify({invoice_id: Number(button.dataset.returnInvoice), warehouse_id: state.warehouseId, refund_method: $('[data-refund]', card).value, reason: $('[data-reason]', card).value, idempotency_key: newKey(), items})}); notify(`تم حفظ المرتجع ${result.return_no} · ${money(result.total)}`); $("#returnDialog").close(); await loadCatalog(); focusSearch(); } catch (error) { notify(error.message, true); } }); }
  let returnTimer; $("#returnSearch").oninput = () => { clearTimeout(returnTimer); returnTimer = setTimeout(async () => renderReturnResults(await api(`/cashier/returns/search?q=${encodeURIComponent($("#returnSearch").value)}`)), 250); };

  function showInfo(title, subtitle, html) { $("#infoDialogTitle").textContent = title; $("#infoDialogSubtitle").textContent = subtitle || ''; $("#infoDialogBody").innerHTML = html; openDialog($("#infoDialog")); }
  async function action(name) {
    $("#actionsMenu").hidden = true;
    if (name === 'price-check') { state.priceCheck = true; notify("فحص السعر مفعّل — امسح الباركود"); return focusSearch(); }
    if (name === 'return') return openReturns();
    if (name === 'note') { const value = prompt("ملاحظة الفاتورة", state.note); if (value !== null) { state.note = value.trim(); persist(); } return focusSearch(); }
    if (name === 'last-invoice') { const rows = await api('/cashier/returns/search'); const row = rows[0]; if (row) state.lastInvoice = {id: row.id, invoice_no: row.invoice_no, print_url: `/orders/invoice/${row.id}`}; return showInfo("آخر فاتورة", row ? row.invoice_no : "", row ? `<div class="food-last-invoice"><strong>${money(row.total)}</strong><span>${esc(row.customer_name)}</span><a class="food-primary" href="/food/orders?open=${row.id}">عرض الفاتورة</a><a class="food-ghost" href="/orders/invoice/${row.id}" target="_blank" rel="noopener">طباعة</a></div>` : '<div class="food-empty">لا توجد فاتورة سابقة</div>'); }
    if (name === 'reprint') { if (!state.config.permissions['cashier.reprint']) return; if (!state.lastInvoice) { const rows = await api('/cashier/returns/search'); const row = rows[0]; if (row) state.lastInvoice = {id: row.id, invoice_no: row.invoice_no, print_url: `/orders/invoice/${row.id}`}; } if (!state.lastInvoice || !openPrint(state.lastInvoice.print_url)) notify("لا توجد فاتورة قابلة للطباعة أو منع المتصفح النافذة", true); return; }
    if (name === 'open-drawer') { if (!state.config.permissions['cashier.open_drawer']) return; const result = await api('/cashier/open-drawer', {method:'POST', body:'{}'}); window.dispatchEvent(new CustomEvent(result.signal)); notify("تم إرسال أمر فتح الدرج"); return focusSearch(); }
    if (name === 'shift') { window.location.href = state.config.cashier?.shift_url || '/reports/daily-closing'; return; }
    if (name === 'shortcuts') return showInfo("اختصارات الكيبورد", "للعمل السريع دون فأرة", '<div class="food-shortcut-list"><span><kbd>F2</kbd> البحث</span><span><kbd>F3</kbd> العميل</span><span><kbd>F4</kbd> تعليق</span><span><kbd>F7</kbd> فحص سعر</span><span><kbd>F8</kbd> مفرد/جملة</span><span><kbd>F9</kbd> الدفع</span><span><kbd>Esc</kbd> إغلاق</span></div>');
  }

  async function init() {
    state.config = await api('/cashier-config'); state.warehouseId = state.config.default_warehouse_id;
    state.saleMode = state.config.default_sale_mode === 'WHOLESALE' ? 'WHOLESALE' : 'RETAIL'; restoreDraft();
    root.classList.toggle('fast-pos-mode', Boolean(state.config.settings.fast_pos_mode));
    $("#cashierIdentity").innerHTML = `<i class="fa fa-user-clock"></i> ${esc(state.config.cashier?.name || 'الكاشير')} · ${esc(state.config.cashier?.register || 'POS')}`;
    $("#cashierWarehouse").innerHTML = state.config.warehouses.map(row => `<option value="${row.id}" ${Number(row.id) === Number(state.warehouseId) ? 'selected' : ''}>${esc(row.name)}</option>`).join('');
    $("#holdsCount").textContent = state.config.held_count || 0;
    $$('#defaultSaleMode button').forEach(button => { button.classList.toggle('active', button.dataset.mode === state.saleMode); button.onclick = () => { state.saleMode = button.dataset.mode; $$('#defaultSaleMode button').forEach(item => item.classList.toggle('active', item === button)); persist(); renderProducts(); focusSearch(); }; });
    $$('.food-view-toggle button').forEach(button => { button.classList.toggle('active', button.dataset.view === state.view); button.onclick = () => { state.view = button.dataset.view; localStorage.setItem('finora.food.pos.view', state.view); $$('.food-view-toggle button').forEach(item => item.classList.toggle('active', item === button)); renderProducts(); }; });
    if (!state.config.permissions['cashier.return']) $('[data-action="return"]').hidden = true;
    if (!state.config.permissions['cashier.reprint']) $('[data-action="reprint"]').hidden = true;
    if (!state.config.permissions['cashier.open_drawer']) $('[data-action="open-drawer"]').hidden = true;
    if (!state.config.permissions['cashier.discount_invoice']) $("#invoiceDiscountButton").hidden = true;
    await loadCatalog(); renderCart(); if (state.cart.length) validateCart();
    $("#customerButton span").textContent = state.customer?.name || 'عميل نقدي';
    focusSearch();
  }

  let searchTimer, lastInputAt = 0;
  $("#productSearch").addEventListener('input', event => { const now = performance.now(); const scannerLike = now - lastInputAt < 45; lastInputAt = now; clearTimeout(searchTimer); searchTimer = setTimeout(() => scanOrSearch(event.target.value, scannerLike && event.target.value.length >= 6).catch(error => notify(error.message, true)), scannerLike ? 70 : 220); });
  $("#productSearch").addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); const selected = $('#searchSuggestions button.active'); if (selected) selected.click(); else scanOrSearch(event.target.value, true).catch(error => notify(error.message, true)); }
    if (["ArrowDown", "ArrowUp"].includes(event.key) && !$("#searchSuggestions").hidden) { event.preventDefault(); const max = Math.min(8, state.products.length); state.searchIndex = (state.searchIndex + (event.key === 'ArrowDown' ? 1 : -1) + max) % max; renderSuggestions(event.target.value); }
    if (event.key === 'Escape') hideSuggestions();
  });
  $("#cashierWarehouse").onchange = async event => { if (state.cart.length && !confirm("سيتم تفريغ السلة عند تغيير المخزن. متابعة؟")) { event.target.value = state.warehouseId; return; } state.warehouseId = Number(event.target.value); state.cart = []; localStorage.removeItem(storageKey); renderCart(); await loadCatalog(); focusSearch(); };
  $("#customerButton").onclick = openCustomers; $("#holdsButton").onclick = openHolds; $("#completeSale").onclick = openPayment;
  $("#clearCart").onclick = () => { if (!state.cart.length) return; const previous = [...state.cart]; state.cart = []; state.invoiceDiscount = 0; persist(); renderCart(); notify("تم تفريغ السلة", false, () => { state.cart = previous; persist(); renderCart(); validateCart(); }); };
  $("#invoiceDiscountButton").onclick = () => { const value = prompt("خصم الفاتورة: اكتب المبلغ أو النسبة مثل 5%", state.invoiceDiscount); if (value !== null) { const raw = String(value).trim(); const subtotal = state.cart.reduce((sum, line) => sum + linePrice(line) * Number(line.quantity) - lineDiscount(line), 0); state.invoiceDiscount = raw.endsWith('%') ? Math.round(subtotal * Math.max(0, Number(raw.slice(0, -1)) || 0) / 100) : Math.max(0, Number(raw || 0)); state.checkoutKey = null; persist(); renderCart(); validateCart(); } };
  $("#loadMoreProducts").onclick = async () => { state.page += 1; await loadCatalog({append: true}); };
  $("#actionsButton").onclick = () => { $("#actionsMenu").hidden = !$("#actionsMenu").hidden; $("#actionsButton").setAttribute('aria-expanded', String(!$("#actionsMenu").hidden)); };
  $$('[data-action]').forEach(button => button.onclick = () => action(button.dataset.action).catch(error => notify(error.message, true)));
  $$('dialog [data-close]').forEach(button => button.onclick = () => button.closest('dialog').close());
  $$('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); }));
  $("#mobileCartButton").onclick = () => $("#cashierCart").classList.toggle('mobile-open');
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') return closeDialogs();
    if ($("#paymentDialog").open || $("#returnDialog").open) return;
    if (event.key === 'F2') { event.preventDefault(); focusSearch(); }
    if (event.key === 'F3') { event.preventDefault(); openCustomers(); }
    if (event.key === 'F4') { event.preventDefault(); $("#holdSale").click(); }
    if (event.key === 'F7') { event.preventDefault(); action('price-check'); }
    if (event.key === 'F8') { event.preventDefault(); const mode = state.saleMode === 'RETAIL' ? 'WHOLESALE' : 'RETAIL'; $(`#defaultSaleMode button[data-mode="${mode}"]`).click(); }
    if (event.key === 'F9') { event.preventDefault(); if (!$("#completeSale").disabled) openPayment(); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) focusSearch(); });
  function updateConnection() { const badge = $("#connectionStatus"); if (!badge) return; badge.classList.toggle('online', navigator.onLine); badge.classList.toggle('offline', !navigator.onLine); badge.innerHTML = `<i class="fa fa-circle"></i> ${navigator.onLine ? 'متصل' : 'دون اتصال'}`; }
  window.addEventListener('online', updateConnection); window.addEventListener('offline', updateConnection); updateConnection();
  init().catch(error => notify(error.message, true));
})();
