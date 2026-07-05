/* Finora POS White Pro — client logic */
(function () {
  "use strict";

  const bootstrapEl = document.getElementById("posBootstrapData");
  const bootstrap = bootstrapEl ? JSON.parse(bootstrapEl.textContent || "{}") : {};
  const canEditPrice = !!bootstrap.canEditPrice;
  const allProducts = Array.isArray(bootstrap.products) ? bootstrap.products : [];

  let items = [];
  let selectedCustomerId = null;
  let selectedCustomerName = "";
  let selectedCustomerCity = "";
  let selectedCustomerPhone = "";
  let customerSearchCache = Object.create(null);
  let editingOrderId = null;
  let currentPriceEditIndex = -1;
  let activeCategory = "all";
  let productSearchQuery = "";
  let discountType = "amount";
  let discountValue = 0;
  let shippingValue = 0;
  let isSubmitting = false;
  let currentPage = 1;
  let pageSize = 20;

  const initialOrderData = bootstrap.orderData ?? null;
  if (initialOrderData) {
    editingOrderId = initialOrderData.id ?? null;
    selectedCustomerId = initialOrderData.customer_id ?? null;
    selectedCustomerName = initialOrderData.customer_name || "";
    items = Array.isArray(initialOrderData.items) ? initialOrderData.items.slice() : [];
  }

  const $ = (id) => document.getElementById(id);

  function debounce(fn, ms) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function toast(msg, type) {
    const t = $("posToast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 3000);

    if (typeof window.playNotificationSound === "function") {
      var soundType = type;
      if (!soundType) {
        if (/خطأ|فشل|غير|لا يُسمح|لا توجد|يرجى|اختر|اسمح/i.test(String(msg))) {
          soundType = /تم |نجاح|حفظ|تنفيذ|إضافة|تطبيق/i.test(String(msg)) ? "success" : "warning";
        } else if (/تم |نجاح|حفظ|تنفيذ|إضافة|تطبيق/i.test(String(msg))) {
          soundType = "success";
        } else {
          soundType = "info";
        }
      }
      window.playNotificationSound(soundType, { soundType: soundType });
    }
  }

  function fmt(n) {
    return (Number(n) || 0).toLocaleString("ar-IQ");
  }

  function getProductById(id) {
    return allProducts.find((p) => p.id === id);
  }

  function calcSubtotal() {
    return items.reduce((s, i) => s + (i.price || 0) * (i.qty || 0), 0);
  }

  function calcDiscount(sub) {
    const v = Number(discountValue) || 0;
    if (v <= 0) return 0;
    if (discountType === "percent") return Math.min(sub, Math.round(sub * v / 100));
    return Math.min(sub, v);
  }

  function calcTotal() {
    const sub = calcSubtotal();
    const disc = calcDiscount(sub);
    const ship = Number(shippingValue) || 0;
    return Math.max(0, sub - disc + ship);
  }

  function stockBadge(product, qty) {
    const threshold = product?.low_stock_threshold ?? 5;
    if (qty <= 0) return { cls: "out", text: "نفد", overlay: false };
    if (qty <= threshold) return { cls: "low", text: "مخزون منخفض", overlay: true };
    return { cls: "ok", text: "متوفر", overlay: false };
  }

  function cartThumbHtml(item) {
    if (item.image_url) {
      return `<img src="${item.image_url}" alt="" class="pos-cart-thumb">`;
    }
    return `<span class="pos-cart-thumb pos-cart-thumb--placeholder"><i class="fas fa-box"></i></span>`;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function customerLabel(c) {
    const name = (c && c.name) || selectedCustomerName || "";
    const phone = (c && c.phone) || selectedCustomerPhone || "";
    if (name && phone) return name + " — " + phone;
    return name || phone || "";
  }

  function updateCustomerDisplay(c) {
    if (c?.name) selectedCustomerName = c.name;
    if (c?.city) selectedCustomerCity = c.city;
    if (c?.phone) selectedCustomerPhone = c.phone;

    const label = customerLabel(c);
    const badge = $("selectedCustomer");
    if (badge) {
      if (selectedCustomerId && label) {
        badge.textContent = label;
        badge.classList.add("is-selected");
        badge.hidden = false;
      } else {
        badge.textContent = "لم يتم اختيار زبون";
        badge.classList.remove("is-selected");
      }
    }

    const sc = $("searchCustomer");
    if (sc) {
      if (selectedCustomerId && label) {
        sc.value = label;
        sc.classList.add("pos-input--selected");
      } else {
        sc.classList.remove("pos-input--selected");
      }
    }

    quoteDeliveryFee();
  }

  function clearCustomerDisplay() {
    selectedCustomerName = "";
    selectedCustomerCity = "";
    selectedCustomerPhone = "";
    shippingValue = 0;
    const shipInput = $("shippingValue");
    if (shipInput) shipInput.value = "";
    const badge = $("selectedCustomer");
    if (badge) {
      badge.textContent = "لم يتم اختيار زبون";
      badge.classList.remove("is-selected");
    }
    const sc = $("searchCustomer");
    if (sc) {
      sc.value = "";
      sc.classList.remove("pos-input--selected");
    }
  }

  function quoteDeliveryFee() {
    if (!selectedCustomerId || !selectedCustomerCity || !items.length) return;
    fetch("/api/delivery-fee/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        city: selectedCustomerCity,
        items: items.map(({ product_id, qty }) => ({ product_id, qty })),
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) return;
        shippingValue = Number(d.fee) || 0;
        const shipInput = $("shippingValue");
        if (shipInput) shipInput.value = shippingValue;
        updateSummary();
      })
      .catch(() => { /* ignore */ });
  }

  function updateStats() {
    const total = calcTotal();
    const count = items.reduce((s, i) => s + (i.qty || 0), 0);
    const countLabel = count + " منتج";
    const itemCountEl = $("itemCount");
    if (itemCountEl) itemCountEl.textContent = countLabel;
    const itemCountMobile = $("itemCountMobile");
    if (itemCountMobile) itemCountMobile.textContent = countLabel;
    const execBtn = $("btnExecute");
    if (execBtn) execBtn.disabled = items.length === 0 || isSubmitting;
    const execMobile = $("btnExecuteMobile");
    if (execMobile) execMobile.disabled = items.length === 0 || isSubmitting;
  }

  function updateSummary() {
    const sub = calcSubtotal();
    const disc = calcDiscount(sub);
    const ship = Number(shippingValue) || 0;
    const total = calcTotal();
    const discStr = disc > 0 ? "−" + fmt(disc) + " د.ع" : "0 د.ع";
    const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
    set("summarySubtotal", fmt(sub) + " د.ع");
    set("summaryDiscount", discStr);
    set("summaryShipping", fmt(ship) + " د.ع");
    set("summaryTotal", fmt(total) + " د.ع");
    set("summaryTotalFixed", fmt(total) + " د.ع");
    set("summaryDiscountFixed", disc > 0 ? "−" + fmt(disc) + " د.ع" : "0 د.ع");
    document.querySelector(".pos-mobile-discount-row")?.classList.toggle("has-discount", disc > 0);
    const tp = $("totalPrice");
    if (tp) tp.textContent = fmt(total);
    updateStats();
  }

  function renderItems() {
    const tbody = $("orderItems");
    const mobileList = $("cartMobileList");
    const itemCountEl = $("itemCount");
    const count = items.reduce((s, i) => s + (i.qty || 0), 0);
    if (itemCountEl) itemCountEl.textContent = count + " منتج";

    const rowHtml = items.map((i, idx) => {
      const t = (i.price || 0) * (i.qty || 0);
      const sku = i.sku || "";
      const priceEdit = canEditPrice
        ? `<button type="button" class="pos-qty-btn" onclick="PosWP.changePrice(${idx})" title="تعديل السعر"><i class="fas fa-pen"></i></button>`
        : "";
      return `<tr>
        <td>
          <div class="pos-cart-product-cell">
            ${cartThumbHtml(i)}
            <div>
              <strong>${i.name}</strong>
              ${sku ? `<div class="pos-cart-sku">${sku}</div>` : ""}
            </div>
          </div>
        </td>
        <td>${fmt(i.price)} د.ع ${priceEdit}</td>
        <td>
          <div class="pos-qty-stepper">
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},-1)">−</button>
            <span class="pos-qty-value">${i.qty}</span>
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},1)">+</button>
          </div>
        </td>
        <td class="pos-cart-line-total">${fmt(t)} د.ع</td>
        <td><button type="button" class="pos-btn-remove" onclick="PosWP.removeItem(${idx})" title="حذف"><i class="fas fa-trash-alt"></i></button></td>
      </tr>`;
    }).join("");

    if (tbody) tbody.innerHTML = rowHtml;

    const mobileHtml = items.map((i, idx) => {
      const t = (i.price || 0) * (i.qty || 0);
      return `<div class="pos-cart-mobile-item">
        <div class="pos-cart-mobile-thumb-wrap">${cartThumbHtml(i)}</div>
        <div class="pos-cart-mobile-main">
          <div class="pos-cart-mobile-item-name">${i.name}</div>
          <div class="pos-cart-mobile-meta">
            ${i.sku ? `<span class="pos-cart-sku">${i.sku}</span>` : "<span></span>"}
            <span class="pos-cart-mobile-unit">${fmt(i.price)} د.ع</span>
          </div>
          <div class="pos-cart-mobile-controls">
            <div class="pos-qty-stepper pos-qty-stepper--sm">
              <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},-1)">−</button>
              <span class="pos-qty-value">${i.qty}</span>
              <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},1)">+</button>
            </div>
            <span class="pos-cart-line-total">${fmt(t)} د.ع</span>
          </div>
        </div>
        <button type="button" class="pos-btn-remove pos-btn-remove--sm" onclick="PosWP.removeItem(${idx})" title="حذف"><i class="fas fa-trash-alt"></i></button>
      </div>`;
    }).join("");

    if (mobileList) {
      mobileList.innerHTML = items.length
        ? mobileHtml
        : '<div class="pos-empty pos-empty--compact"><p>السلة فارغة</p></div>';
    }

    updateSummary();
    quoteDeliveryFee();
  }

  function filteredProducts() {
    let list = allProducts.slice();
    const q = productSearchQuery.trim().toLowerCase();
    if (q) {
      list = list.filter((p) => {
        const name = (p.name || "").toLowerCase();
        const sku = (p.sku || "").toLowerCase();
        const bc = (p.barcode || "").toLowerCase();
        return name.includes(q) || sku.includes(q) || bc.includes(q);
      });
    }
    if (activeCategory === "offers") {
      list = list.filter((p) => !!(p.store_badge || "").trim());
    } else if (activeCategory === "low") {
      list = list.filter((p) => {
        const qty = p.quantity || 0;
        const th = p.low_stock_threshold ?? 5;
        return qty > 0 && qty <= th;
      });
    } else if (activeCategory === "out") {
      list = list.filter((p) => (p.quantity || 0) <= 0);
    } else if (activeCategory === "available") {
      list = list.filter((p) => {
        const qty = p.quantity || 0;
        const th = p.low_stock_threshold ?? 5;
        return qty > th;
      });
    } else if (activeCategory !== "all") {
      list = list.filter((p) => (p.category || "") === activeCategory);
    }
    return list;
  }

  function updatePagination(list) {
    const total = list.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const start = total === 0 ? 0 : (currentPage - 1) * pageSize + 1;
    const end = Math.min(currentPage * pageSize, total);
    const info = $("paginationInfo");
    if (info) {
      info.textContent = total === 0 ? "0 من 0" : `${start}-${end} من ${total}`;
    }
    const prev = $("btnPrevPage");
    const next = $("btnNextPage");
    if (prev) prev.disabled = currentPage <= 1;
    if (next) next.disabled = currentPage >= totalPages;
  }

  function renderProductGrid() {
    if (window.innerWidth < 768) return;
    const grid = $("productGrid");
    const empty = $("productEmpty");
    if (!grid) return;

    const list = filteredProducts();
    updatePagination(list);

    if (!list.length) {
      grid.innerHTML = "";
      if (empty) empty.style.display = "block";
      return;
    }
    if (empty) empty.style.display = "none";

    const pageList = list;

    grid.innerHTML = pageList.map((p) => {
      const qty = p.quantity || 0;
      const badge = stockBadge(p, qty);
      const imgInner = p.image_url
        ? `<img src="${p.image_url}" alt="" loading="lazy">`
        : '<i class="fas fa-box"></i>';
      const overlay = badge.overlay
        ? `<span class="pos-stock-overlay ${badge.cls}">${badge.text}</span>`
        : "";
      const sku = p.sku || p.barcode || ("#" + p.id);
      const nameEsc = (p.name || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
      const stockLabel = qty <= 0 ? "نفد" : `المخزون: ${qty}`;
      return `<article class="pos-product-card" data-id="${p.id}">
        <div class="pos-product-img">${imgInner}${overlay}</div>
        <div class="pos-product-name">${p.name}</div>
        <div class="pos-product-sku">${sku}</div>
        <div class="pos-product-row">
          <span class="pos-product-price">${fmt(p.sale_price)} د.ع</span>
          ${!badge.overlay ? `<span class="pos-stock-badge ${badge.cls}">${badge.text}</span>` : ""}
        </div>
        <div class="pos-product-stock">${stockLabel}</div>
        <button type="button" class="pos-btn-add" ${qty <= 0 ? "disabled" : ""}
          onclick="PosWP.addItemById(${p.id})"><i class="fas fa-cart-plus"></i> إضافة</button>
      </article>`;
    }).join("");
  }

  function syncLocalStock(productId, delta) {
    const p = allProducts.find((x) => x.id === productId);
    if (p) p.quantity = Math.max(0, (p.quantity || 0) - delta);
    renderProductGrid();
  }

  function addItemById(id) {
    const p = getProductById(id);
    if (!p) return;
    addItem(p.id, p.name, p.sale_price, p.quantity, p.image_url, p.sku);
  }

  function addItemFromCard(el) {
    if (!el) return;
    addItem(
      parseInt(el.getAttribute("data-id"), 10),
      el.querySelector(".pos-product-name")?.textContent || "",
      parseInt(el.getAttribute("data-price"), 10) || 0,
      parseInt(el.getAttribute("data-stock"), 10) || 0,
      el.getAttribute("data-image") || "",
      ""
    );
  }

  function addItem(id, name, price, stock, imageUrl, sku) {
    const idNum = typeof id === "string" ? parseInt(id, 10) : id;
    const stockNum = typeof stock === "string" ? parseInt(stock, 10) : (stock || 0);
    const product = getProductById(idNum);
    const img = imageUrl || product?.image_url || "";
    const itemSku = sku || product?.sku || product?.barcode || "";
    const item = items.find((i) => i.product_id === idNum);

    if (item) {
      if (item.qty + 1 > stockNum) {
        toast("الكمية المطلوبة أكبر من المخزون (" + stockNum + ")");
        return;
      }
      item.qty++;
      toast("تم زيادة كمية " + name);
    } else {
      if (stockNum <= 0) {
        toast("المنتج غير متوفر في المخزون");
        return;
      }
      items.push({
        product_id: idNum,
        name: name || "",
        price: Number(price) || 0,
        qty: 1,
        stock: stockNum,
        image_url: img,
        sku: itemSku,
      });
      toast("تم إضافة " + (name || "منتج") + " للسلة");
    }
    const sp = $("searchProduct");
    if (sp) sp.value = "";
    productSearchQuery = "";
    $("productResults")?.classList.remove("open");
    renderItems();
  }

  function updateQty(i, d) {
    const item = items[i];
    if (!item) return;
    const newQty = item.qty + d;
    if (newQty > item.stock) {
      toast("الكمية المطلوبة أكبر من المخزون (" + item.stock + ")");
      return;
    }
    if (newQty <= 0) {
      if (confirm("حذف " + item.name + " من السلة؟")) {
        items.splice(i, 1);
        toast("تم حذف المنتج من السلة");
      }
    } else {
      item.qty = newQty;
    }
    renderItems();
  }

  function removeItem(i) {
    items.splice(i, 1);
    toast("تم حذف المنتج من السلة");
    renderItems();
  }

  function changePrice(idx) {
    const item = items[idx];
    if (!item) return;
    currentPriceEditIndex = idx;
    const nameEl = $("priceModalProductName");
    const input = $("priceModalInput");
    if (nameEl) nameEl.textContent = item.name + " — السعر الحالي: " + fmt(item.price) + " د.ع";
    if (input) input.value = item.price;
    $("priceModal")?.classList.add("show");
    input?.focus();
  }

  function confirmPriceChange() {
    if (currentPriceEditIndex < 0) return;
    const input = $("priceModalInput");
    const price = parseFloat(input?.value);
    if (isNaN(price) || price <= 0) {
      toast("يرجى إدخال سعر صحيح");
      return;
    }
    items[currentPriceEditIndex].price = price;
    renderItems();
    toast("تم تغيير السعر إلى " + fmt(price) + " د.ع");
    closePriceModal();
  }

  function closePriceModal() {
    $("priceModal")?.classList.remove("show");
    currentPriceEditIndex = -1;
  }

  function selectCustomer(c) {
    if (!c || c.id == null || c.id === "") {
      toast("تعذر اختيار الزبون");
      return;
    }
    if (c.blacklisted) {
      toast(c.blacklist_message || "هذا الزبون في القائمة السوداء");
      return;
    }
    selectedCustomerId = c.id;
    selectedCustomerName = c.name || "";
    selectedCustomerCity = c.city || "";
    selectedCustomerPhone = c.phone || "";
    updateCustomerDisplay(c);
    $("customerResults")?.classList.remove("open");
    toast("تم اختيار الزبون: " + (c.name || ""));
  }

  function pickCustomerFromSearch(id) {
    const c = customerSearchCache[id] || customerSearchCache[String(id)] || customerSearchCache[Number(id)];
    if (c) {
      selectCustomer(c);
      return;
    }
    // توافق مع النسخة القديمة التي كانت تمرّر JSON مرمّز
    try {
      const parsed = JSON.parse(decodeURIComponent(String(id)));
      if (parsed && parsed.id != null) selectCustomer(parsed);
    } catch (e) {
      toast("تعذر اختيار الزبون");
    }
  }

  function resetCustomerForm() {
    const name = $("name");
    const phone = $("phone");
    const phone2 = $("phone2");
    const address = $("address");
    const city = $("city");
    if (name) name.value = "";
    if (phone) phone.value = "";
    if (phone2) phone2.value = "";
    if (address) address.value = "";
    if (city && city.options.length) city.selectedIndex = 0;
  }

  function openCustomerModal() {
    resetCustomerForm();
    $("customerModal")?.classList.add("show");
    $("name")?.focus();
  }

  function closeCustomerModal() {
    $("customerModal")?.classList.remove("show");
    closeOCR();
  }

  function isPhone11Digits(value) {
    return /^\d{11}$/.test(String(value || "").trim());
  }

  function saveCustomer() {
    const name = ($("name")?.value || "").trim();
    const phone = ($("phone")?.value || "").trim();
    const phone2 = ($("phone2")?.value || "").trim();
    if (!name) { toast("يرجى إدخال اسم الزبون"); return; }
    if (!phone) { toast("يرجى إدخال رقم الهاتف"); return; }
    if (!isPhone11Digits(phone)) { toast("رقم الهاتف يجب أن يكون 11 رقم"); $("phone")?.focus(); return; }
    if (phone2 && !isPhone11Digits(phone2)) { toast("رقم الهاتف الثاني يجب أن يكون 11 رقم"); $("phone2")?.focus(); return; }
    const addressValue = ($("address")?.value || "").trim();
    if (!addressValue) { toast("يرجى إدخال العنوان"); $("address")?.focus(); return; }

    const saveBtn = document.querySelector("#customerModal .pos-btn-primary");
    if (saveBtn?.dataset.busy === "1") return;
    if (saveBtn) saveBtn.dataset.busy = "1";

    const cityValue = ($("city")?.value || "").trim();

    fetch("/pos/add-customer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        phone,
        phone2,
        city: cityValue,
        address: addressValue,
      }),
    })
      .then(async (r) => {
        let d = {};
        try { d = await r.json(); } catch (_) { /* non-json body */ }
        if (!r.ok || d.blacklisted || d.status === "fail") {
          toast(d.msg || "فشل حفظ الزبون");
          return;
        }
        if (d.status === "success" && d.id) {
          selectedCustomerId = d.id;
          selectedCustomerName = d.name || name;
          selectedCustomerPhone = d.phone || phone;
          selectedCustomerCity = cityValue;
          updateCustomerDisplay({
            id: d.id,
            name: selectedCustomerName,
            phone: selectedCustomerPhone,
            city: selectedCustomerCity,
          });
          resetCustomerForm();
          toast("تم حفظ الزبون بنجاح");
          closeCustomerModal();
        } else {
          toast(d.msg || "فشل حفظ الزبون");
        }
      })
      .catch(() => toast("حدث خطأ في الاتصال"))
      .finally(() => { if (saveBtn) saveBtn.dataset.busy = "0"; });
  }

  function openOrderNotesModal() {
    if (!selectedCustomerId) { toast("اختر زبوناً"); return; }
    if (!items.length) { toast("لا توجد منتجات"); return; }
    $("orderNotesModal")?.classList.add("show");
    $("orderNotesInput")?.focus();
  }

  function closeOrderNotesModal() {
    $("orderNotesModal")?.classList.remove("show");
    const ni = $("orderNotesInput");
    if (ni) ni.value = "";
    const ps = $("pageSelect");
    if (ps) ps.value = "";
  }

  function confirmOrderWithNotes() {
    if (isSubmitting) return;
    if (!selectedCustomerId) { toast("اختر زبوناً"); return; }
    if (!items.length) { toast("لا توجد منتجات"); return; }

    const pageSelect = $("pageSelect");
    if (pageSelect && !pageSelect.value) {
      toast("يرجى اختيار البيج أو 'لا يوجد بيج'");
      pageSelect.focus();
      return;
    }

    let pageId = null;
    let pageName = null;
    if (pageSelect && pageSelect.value && pageSelect.value !== "no_page") {
      pageId = pageSelect.value;
      const opt = pageSelect.options[pageSelect.selectedIndex];
      pageName = opt ? opt.getAttribute("data-name") || opt.text : null;
    }

    const notes = ($("orderNotesInput")?.value || "").trim()
      || ($("invoiceNotes")?.value || "").trim();

    isSubmitting = true;
    updateStats();
    const btn = $("btnExecute");
    const btnM = $("btnExecuteMobile");
    if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> جاري التنفيذ...';
    if (btnM) btnM.innerHTML = '<i class="fas fa-spinner fa-spin"></i> ...';

    fetch("/pos/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_id: selectedCustomerId,
        items: items.map(({ product_id, qty, price }) => ({ product_id, qty, price })),
        note: notes || null,
        scheduled_date: null,
        page_id: pageId || null,
        page_name: pageName || null,
        shipping_fee: Number(shippingValue) || 0,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        isSubmitting = false;
        if (btn) btn.innerHTML = '<i class="fas fa-print"></i> تنفيذ و طباعة';
        if (btnM) btnM.innerHTML = '<i class="fas fa-print"></i> تنفيذ';
        if (d.error) {
          toast(d.error);
          updateStats();
          return;
        }
        toast("تم تنفيذ البيع وإنشاء الفاتورة");
        items.forEach((i) => syncLocalStock(i.product_id, i.qty));
        closeOrderNotesModal();
        printServerInvoice(d.invoice_id);
        items = [];
        selectedCustomerId = null;
        clearCustomerDisplay();
        if (pageSelect) pageSelect.value = "";
        renderItems();
      })
      .catch((err) => {
        isSubmitting = false;
        if (btn) btn.innerHTML = '<i class="fas fa-print"></i> تنفيذ و طباعة';
        if (btnM) btnM.innerHTML = '<i class="fas fa-print"></i> تنفيذ';
        toast("حدث خطأ: " + err.message);
        updateStats();
      });
  }

  function printServerInvoice(invoiceId) {
    finoraPrintUrl("/orders/invoice/" + encodeURIComponent(invoiceId));
  }

  function openScheduleModal() {
    if (!selectedCustomerId) { toast("اختر زبوناً"); return; }
    if (!items.length) { toast("لا توجد منتجات"); return; }
    const today = new Date().toISOString().split("T")[0];
    const di = $("scheduleDateInput");
    if (di) { di.min = today; di.value = today; }
    $("scheduleOrderModal")?.classList.add("show");
  }

  function closeScheduleModal() {
    $("scheduleOrderModal")?.classList.remove("show");
  }

  function confirmScheduleOrder() {
    const scheduleDate = $("scheduleDateInput")?.value;
    if (!scheduleDate) { toast("اختر تاريخ التأجيل"); return; }
    if (!selectedCustomerId || !items.length) return;

    const notes = ($("scheduleNotesInput")?.value || "").trim();
    const pageSelect = $("pageSelect");

    fetch("/pos/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_id: selectedCustomerId,
        items: items.map(({ product_id, qty, price }) => ({ product_id, qty, price })),
        note: notes || null,
        scheduled_date: scheduleDate,
        page_id: pageSelect?.value && pageSelect.value !== "no_page" ? pageSelect.value : null,
        shipping_fee: Number(shippingValue) || 0,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.error) { toast(d.error); return; }
        items.forEach((i) => syncLocalStock(i.product_id, i.qty));
        toast("تم تأجيل الطلب — رقم " + d.invoice_id);
        closeScheduleModal();
        items = [];
        selectedCustomerId = null;
        clearCustomerDisplay();
        renderItems();
      })
      .catch((err) => toast("حدث خطأ: " + err.message));
  }

  function openClearCartDialog() {
    if (!items.length) return;
    $("clearCartModal")?.classList.add("show");
  }

  function closeClearCartDialog() {
    $("clearCartModal")?.classList.remove("show");
  }

  function confirmClearCart() {
    items = [];
    closeClearCartDialog();
    renderItems();
    toast("تم إفراغ السلة");
  }

  function openInventoryModal() {
    $("inventoryModal")?.classList.add("show");
    $("inventorySearch")?.focus();
  }

  function closeInventoryModal() {
    $("inventoryModal")?.classList.remove("show");
    const is = $("inventorySearch");
    if (is) is.value = "";
    filterInventory();
  }

  function filterInventory() {
    const q = ($("inventorySearch")?.value || "").toLowerCase();
    document.querySelectorAll("#inventoryModalList .inventory-card").forEach((card) => {
      const name = (card.getAttribute("data-name") || "").toLowerCase();
      card.style.display = name.includes(q) ? "" : "none";
    });
  }

  function buildCategoryTabs() {
    const container = $("categoryPills");
    if (!container) return;

    const cats = new Set();
    let hasOffers = false;
    allProducts.forEach((p) => {
      if (p.category) cats.add(p.category);
      if (p.store_badge) hasOffers = true;
    });

    let html = '<button type="button" class="pos-pill active" data-cat="all">الكل</button>';
    Array.from(cats).sort().forEach((cat) => {
      html += `<button type="button" class="pos-pill" data-cat="${cat.replace(/"/g, "&quot;")}">${cat}</button>`;
    });
    if (hasOffers) {
      html += '<button type="button" class="pos-pill" data-cat="offers">عروض</button>';
    }
    container.innerHTML = html;
    bindCategoryPills(container);
  }

  function bindCategoryPills(container) {
    container.querySelectorAll(".pos-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        container.querySelectorAll(".pos-pill").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeCategory = btn.getAttribute("data-cat") || "all";
        currentPage = 1;
        renderProductGrid();
      });
    });
  }

  function bindStockPills() {
    document.querySelectorAll(".pos-pill--stock").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#categoryPills .pos-pill").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".pos-pill--stock").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeCategory = btn.getAttribute("data-cat") || "all";
        currentPage = 1;
        renderProductGrid();
      });
    });
  }

  function toggleStockFilter() {
    const el = $("stockFilterPills");
    if (!el) return;
    const show = el.style.display === "none" || !el.style.display;
    el.style.display = show ? "flex" : "none";
    $("btnToggleStockFilter")?.classList.toggle("active", show);
  }

  function focusBarcode() {
    const sp = $("searchProduct");
    if (sp) { sp.focus(); sp.select(); }
  }

  function prevPage() {
    if (currentPage > 1) {
      currentPage--;
      renderProductGrid();
    }
  }

  function nextPage() {
    const totalPages = Math.ceil(filteredProducts().length / pageSize);
    if (currentPage < totalPages) {
      currentPage++;
      renderProductGrid();
    }
  }

  function changePageSize(val) {
    pageSize = parseInt(val, 10) || 12;
    currentPage = 1;
    renderProductGrid();
  }

  function clearProductSearch() {
    const sp = $("searchProduct");
    if (sp) sp.value = "";
    productSearchQuery = "";
    activeCategory = "all";
    currentPage = 1;
    document.querySelectorAll("#categoryPills .pos-pill").forEach((b, i) => b.classList.toggle("active", i === 0));
    document.querySelectorAll(".pos-pill--stock").forEach((b) => b.classList.remove("active"));
    $("stockFilterPills").style.display = "none";
    $("btnToggleStockFilter")?.classList.remove("active");
    $("productResults")?.classList.remove("open");
    renderProductGrid();
  }

  /* OCR */
  function openCamera() { $("cameraInput")?.click(); }
  function uploadImage() { $("imageInput")?.click(); }
  function closeOCR() { const m = $("ocrModal"); if (m) m.style.display = "none"; }

  function sendToOCR(file) {
    if (!file) return;
    $("ocrLoaderWrapper")?.classList.add("active");
    const f = new FormData();
    f.append("image", file);
    fetch("/ai/ocr", { method: "POST", body: f })
      .then((r) => r.json())
      .then((d) => {
        $("ocrLoaderWrapper")?.classList.remove("active");
        if (d.status === "fail") {
          alert(d.error || "فشل OCR");
          return;
        }
        const om = $("ocrModal");
        if (om) om.style.display = "block";
        if ($("ocrText")) $("ocrText").value = d.raw_text || "";
        if ($("ocrName")) $("ocrName").value = d.name || "";
        if ($("ocrPhone")) $("ocrPhone").value = d.phone || "";
        if ($("ocrAddress")) $("ocrAddress").value = d.address || "";
      })
      .catch(() => {
        $("ocrLoaderWrapper")?.classList.remove("active");
        toast("خطأ في معالجة الصورة");
      });
  }

  function confirmOCR() {
    fetch("/ai/ocr/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        raw_text: $("ocrText")?.value,
        name: $("ocrName")?.value,
        phone: $("ocrPhone")?.value,
        address: $("ocrAddress")?.value || "",
        city: $("ocrCity")?.value || "",
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.status === "success" || d.status === "exists") {
          selectedCustomerId = d.id;
          selectedCustomerName = d.name || "";
          selectedCustomerPhone = d.phone || "";
          selectedCustomerCity = ($("ocrCity")?.value || "").trim();
          updateCustomerDisplay({
            id: d.id,
            name: selectedCustomerName,
            phone: selectedCustomerPhone,
            city: selectedCustomerCity,
          });
          closeOCR();
          toast("تم حفظ بيانات OCR");
        }
      });
  }

  function initSearch() {
    const searchCustomer = $("searchCustomer");
    const customerResults = $("customerResults");
    if (customerResults && !customerResults.dataset.bound) {
      customerResults.dataset.bound = "1";
      customerResults.addEventListener("click", (e) => {
        const row = e.target.closest("[data-customer-id]");
        if (!row || !customerResults.contains(row)) return;
        e.preventDefault();
        e.stopPropagation();
        const id = row.getAttribute("data-customer-id");
        const c = customerSearchCache[id] || customerSearchCache[Number(id)];
        if (c) selectCustomer(c);
        else toast("تعذر اختيار الزبون");
      });
    }
    if (searchCustomer) {
      searchCustomer.addEventListener("input", debounce(() => {
        const val = searchCustomer.value.trim();
        if (val.length < 2) {
          customerResults?.classList.remove("open");
          return;
        }
        // إذا كان النص هو الزبون المختار حالياً فلا نعيد البحث
        if (selectedCustomerId && val === customerLabel()) return;
        fetch("/pos/search-customer?q=" + encodeURIComponent(val))
          .then((r) => r.json())
          .then((d) => {
            if (!customerResults) return;
            if (!Array.isArray(d) || !d.length) {
              customerResults.innerHTML = '<div class="pos-dropdown-empty">لا توجد نتائج</div>';
              customerResults.classList.add("open");
              return;
            }
            customerResults.innerHTML = d.map((c) => {
              customerSearchCache[c.id] = c;
              customerSearchCache[String(c.id)] = c;
              const bl = c.blacklisted ? " pos-cust-bl" : "";
              return `<div class="pos-customer-result${bl}" data-customer-id="${escapeHtml(c.id)}">${escapeHtml(c.name)} — ${escapeHtml(c.phone)}</div>`;
            }).join("");
            customerResults.classList.add("open");
          })
          .catch(() => toast("فشل البحث عن الزبون"));
      }, 250));
      searchCustomer.addEventListener("focus", () => {
        if (selectedCustomerId && searchCustomer.classList.contains("pos-input--selected")) {
          searchCustomer.select();
        }
      });
    }

    const searchProduct = $("searchProduct");
    const productResults = $("productResults");
    const runProductSearch = (val) => {
      if (!val) {
        productSearchQuery = "";
        currentPage = 1;
        renderProductGrid();
        productResults?.classList.remove("open");
        return;
      }
      fetch("/pos/search-product?q=" + encodeURIComponent(val))
        .then((r) => r.json())
        .then((d) => {
          if (d.length === 1 && d[0].is_barcode) {
            const p = getProductById(d[0].id);
            addItem(d[0].id, d[0].name, d[0].price, d[0].quantity, d[0].image_url || p?.image_url, p?.sku);
            if (searchProduct) searchProduct.value = "";
            productSearchQuery = "";
            return;
          }
          productSearchQuery = val.toLowerCase();
          currentPage = 1;
          renderProductGrid();
          if (d.length > 0 && productResults) {
            productResults.innerHTML = d.map((p) => {
              const prod = getProductById(p.id);
              const nameEsc = (p.name || "").replace(/'/g, "\\'");
              return `<div class="pos-product-item" onclick="PosWP.addItem(${p.id},'${nameEsc}',${p.price},${p.quantity || 0},'${(p.image_url || prod?.image_url || "").replace(/'/g, "\\'")}','${(prod?.sku || "").replace(/'/g, "\\'")}')">${p.name} — ${fmt(p.price)} <small>(${p.quantity || 0})</small></div>`;
            }).join("");
            productResults.classList.add("open");
          } else if (productResults) {
            productResults.innerHTML = '<div class="pos-dropdown-empty">لا توجد نتائج</div>';
            productResults.classList.add("open");
          }
        });
    };

    if (searchProduct) {
      searchProduct.addEventListener("input", debounce(() => runProductSearch(searchProduct.value.trim()), 200));
      searchProduct.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          runProductSearch(searchProduct.value.trim());
        }
      });
    }
  }

  function openDiscountModal() {
    discountType = "amount";
    const dt = $("discountType");
    if (dt) dt.value = "amount";
    const input = $("discountModalInput");
    if (input) input.value = Number(discountValue) || 0;
    $("discountModal")?.classList.add("show");
    input?.focus();
  }

  function closeDiscountModal() {
    $("discountModal")?.classList.remove("show");
  }

  function confirmDiscount() {
    const input = $("discountModalInput");
    const val = Math.max(0, parseInt(input?.value, 10) || 0);
    discountType = "amount";
    discountValue = val;
    const dv = $("discountValue");
    if (dv) dv.value = val;
    const dt = $("discountType");
    if (dt) dt.value = "amount";
    updateSummary();
    closeDiscountModal();
    toast(val > 0 ? "تم تطبيق خصم " + fmt(val) + " د.ع" : "تم إلغاء الخصم");
  }

  function initDiscountShipping() {
    $("discountType")?.addEventListener("change", (e) => {
      discountType = e.target.value;
      updateSummary();
    });
    $("discountValue")?.addEventListener("input", (e) => {
      discountValue = e.target.value;
      updateSummary();
    });
    $("shippingValue")?.addEventListener("input", (e) => {
      shippingValue = e.target.value;
      updateSummary();
    });
  }

  function initKeyboard() {
    document.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key === "k") {
        e.preventDefault();
        $("searchProduct")?.focus();
      }
      if (e.key === "Escape") {
        closeDiscountModal();
        closeOrderNotesModal();
        closeScheduleModal();
        closeClearCartDialog();
        closeCustomerModal();
        closePriceModal();
      }
      if (e.key === "F2") {
        e.preventDefault();
        $("searchCustomer")?.focus();
      }
      if (e.key === "F4") {
        e.preventDefault();
        $("searchProduct")?.focus();
      }
      if (e.ctrlKey && e.key === "Enter" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
        openOrderNotesModal();
      }
    });
  }

  function initHorizontalProductWheel() {
    const grid = $("productGrid");
    if (!grid) return;
    grid.addEventListener("wheel", (e) => {
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      const maxScroll = grid.scrollWidth - grid.clientWidth;
      if (maxScroll <= 0) return;

      e.preventDefault();
      grid.scrollLeft += e.deltaY;
    }, { passive: false });
  }

  function init() {
    buildCategoryTabs();
    bindStockPills();
    initSearch();
    initDiscountShipping();
    initKeyboard();
    initHorizontalProductWheel();

    $("cameraInput")?.addEventListener("change", (e) => {
      if (e.target.files?.[0]) sendToOCR(e.target.files[0]);
    });
    $("imageInput")?.addEventListener("change", (e) => {
      if (e.target.files?.[0]) sendToOCR(e.target.files[0]);
    });

    if (initialOrderData) {
      if (initialOrderData.customer_id || initialOrderData.customer_name) {
        selectedCustomerId = initialOrderData.customer_id ?? selectedCustomerId;
        selectedCustomerName = initialOrderData.customer_name || selectedCustomerName;
        selectedCustomerPhone = initialOrderData.customer_phone || selectedCustomerPhone;
        selectedCustomerCity = initialOrderData.customer_city || selectedCustomerCity;
        updateCustomerDisplay({
          id: selectedCustomerId,
          name: selectedCustomerName,
          phone: selectedCustomerPhone,
          city: selectedCustomerCity,
        });
      }
      if (initialOrderData.note && $("invoiceNotes")) {
        $("invoiceNotes").value = initialOrderData.note;
      }
      if (initialOrderData.page_id && $("pageSelect")) {
        $("pageSelect").value = String(initialOrderData.page_id);
      }
    }

    renderProductGrid();
    renderItems();
    updateStats();
  }

  window.PosWP = {
    addItem,
    addItemById,
    addItemFromCard,
    updateQty,
    removeItem,
    changePrice,
    confirmPriceChange,
    closePriceModal,
    pickCustomerFromSearch,
    openCustomerModal,
    closeCustomerModal,
    saveCustomer,
    openOrderNotesModal,
    closeOrderNotesModal,
    confirmOrderWithNotes,
    openScheduleModal,
    closeScheduleModal,
    confirmScheduleOrder,
    openClearCartDialog,
    closeClearCartDialog,
    confirmClearCart,
    openInventoryModal,
    closeInventoryModal,
    filterInventory,
    openCamera,
    uploadImage,
    confirmOCR,
    closeOCR,
    clearProductSearch,
    openDiscountModal,
    closeDiscountModal,
    confirmDiscount,
    toggleStockFilter,
    focusBarcode,
    prevPage,
    nextPage,
    changePageSize,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
