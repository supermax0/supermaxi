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
  let pendingColorCtx = null;
  let colorEditCartIndex = -1;
  let activeCategory = "all";
  let productSearchQuery = "";
  let discountType = "amount";
  let discountValue = 0;
  let isSubmitting = false;
  let activeSubmissionToken = null;
  let currentPage = 1;
  let pageSize = 20;

  const initialOrderData = bootstrap.orderData ?? null;
  if (initialOrderData) {
    editingOrderId = initialOrderData.id ?? null;
    selectedCustomerId = initialOrderData.customer_id ?? null;
    selectedCustomerName = initialOrderData.customer_name || "";
    discountValue = Number(initialOrderData.discount_amount) || 0;
    items = Array.isArray(initialOrderData.items)
      ? initialOrderData.items.map((it) => ({
          product_id: it.product_id,
          name: it.name || it.product_name || "",
          price: Number(it.price) || 0,
          qty: Number(it.qty ?? it.quantity) || 0,
          stock: Number(it.stock) || 0,
          color: (it.color || "").trim(),
          color_stock: Number(it.color_stock) || 0,
          fulfillment_branch_id: it.fulfillment_branch_id || null,
          image_url: it.image_url || "",
          sku: it.sku || "",
        }))
      : [];
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
    return (Number(n) || 0).toLocaleString("en-US");
  }

  function getProductById(id) {
    return allProducts.find((p) => p.id === id);
  }

  function cartLineKey(productId, color) {
    return String(productId) + "::" + ((color || "").trim() || "");
  }

  function serializeCartItems() {
    return items.map(({ product_id, qty, price, color, fulfillment_branch_id }) => ({
      product_id,
      qty,
      price,
      color: (color || "").trim() || null,
      fulfillment_branch_id: fulfillment_branch_id || null,
    }));
  }

  function createSubmissionToken() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "pos-" + Date.now() + "-" + Math.random().toString(36).slice(2);
  }

  function setSubmitBusy(busy) {
    const buttons = [
      $("btnExecute"),
      $("btnExecuteMobile"),
      document.querySelector("#orderNotesModal .pos-btn-primary"),
      document.querySelector("#scheduleOrderModal .pos-btn-primary"),
    ];
    buttons.forEach((button) => {
      if (!button) return;
      button.disabled = !!busy;
      button.classList.toggle("is-busy", !!busy);
    });
  }

  function effectiveItemStock(item) {
    if (item.color) {
      return Number(item.color_stock || item.stock) || 0;
    }
    return Number(item.stock) || 0;
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
    return Math.max(0, sub - disc);
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

  function getLockedPagePayload() {
    if (!editingOrderId || !initialOrderData) return { pageId: null, pageName: null };
    return {
      pageId: initialOrderData.page_id || null,
      pageName: initialOrderData.page_name || null,
    };
  }

  function lockEditModeUi() {
    if (!editingOrderId) return;
    const sc = $("searchCustomer");
    if (sc) {
      sc.readOnly = true;
      sc.disabled = true;
      sc.title = "لا يمكن تغيير الزبون أثناء التعديل";
    }
    document.querySelector(".pos-customer-row .pos-btn-icon-only")?.setAttribute("disabled", "disabled");
    const ps = $("pageSelect");
    if (ps) ps.disabled = true;
    const btn = $("btnExecute");
    const btnM = $("btnExecuteMobile");
    if (btn) btn.innerHTML = '<i class="fas fa-save"></i> حفظ التعديل';
    if (btnM) btnM.innerHTML = '<i class="fas fa-save"></i> حفظ';
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

    updateSummary();
  }

  function clearCustomerDisplay() {
    selectedCustomerName = "";
    selectedCustomerCity = "";
    selectedCustomerPhone = "";
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
    const total = calcTotal();
    const discStr = disc > 0 ? "−" + fmt(disc) + " د.ع" : "0 د.ع";
    const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
    set("summarySubtotal", fmt(sub) + " د.ع");
    set("summaryDiscount", discStr);
    set("summaryTotal", fmt(total) + " د.ع");
    set("summaryTotalFixed", fmt(total) + " د.ع");
    set("summaryDiscountFixed", disc > 0 ? "−" + fmt(disc) + " د.ع" : "0 د.ع");
    document.querySelector(".pos-mobile-discount-row")?.classList.toggle("has-discount", disc > 0);
    const tp = $("totalPrice");
    if (tp) tp.textContent = fmt(total);
    updateStats();
  }

  function cartPriceHtml(price, idx, extraClass) {
    const text = fmt(price) + " د.ع";
    const cls = ["pos-cart-price", extraClass].filter(Boolean).join(" ");
    if (!canEditPrice) return `<span class="${cls}">${text}</span>`;
    return `<span class="${cls} pos-cart-price-editable" role="button" tabindex="0" onclick="PosWP.changePrice(${idx})" title="اضغط لتعديل السعر">${text}</span>`;
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
      const color = (i.color || "").trim();
      const colorBadge = color
        ? `<button type="button" class="pos-color-badge" onclick="PosWP.changeCartColor(${idx})" title="تغيير اللون">${color}</button>`
        : "";
      const priceLabel = cartPriceHtml(i.price, idx);
      return `<tr>
        <td>
          <div class="pos-cart-product-cell">
            ${cartThumbHtml(i)}
            <div>
              <strong>${i.name}</strong>
              ${colorBadge}
              ${sku ? `<div class="pos-cart-sku">${sku}</div>` : ""}
            </div>
          </div>
        </td>
        <td>${priceLabel}</td>
        <td>
          <div class="pos-qty-stepper">
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},-1)">−</button>
            <span class="pos-qty-value">${fmt(i.qty)}</span>
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
      const color = (i.color || "").trim();
      return `<div class="pos-cart-mobile-item">
        <div class="pos-cart-mobile-thumb-wrap">${cartThumbHtml(i)}</div>
        <div class="pos-cart-mobile-main">
          <div class="pos-cart-mobile-item-name">${i.name}</div>
          <div class="pos-cart-mobile-meta">
            ${color ? `<span class="pos-color-badge pos-color-badge--sm" onclick="PosWP.changeCartColor(${idx})">${color}</span>` : ""}
            ${i.sku ? `<span class="pos-cart-sku">${i.sku}</span>` : "<span></span>"}
            ${cartPriceHtml(i.price, idx, "pos-cart-mobile-unit")}
          </div>
          <div class="pos-cart-mobile-controls">
            <div class="pos-qty-stepper pos-qty-stepper--sm">
              <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},-1)">−</button>
              <span class="pos-qty-value">${fmt(i.qty)}</span>
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
      const stockLabel = qty <= 0 ? "نفد" : `المخزون: ${fmt(qty)}`;
      return `<article class="pos-product-card" data-id="${p.id}">
        <div class="pos-product-img">${imgInner}${overlay}</div>
        <div class="pos-product-name">${p.name}</div>
        <div class="pos-product-sku">${sku}</div>
        <div class="pos-product-row">
          <span class="pos-product-price">${fmt(p.sale_price)} د.ع</span>
          ${!badge.overlay ? `<span class="pos-stock-badge ${badge.cls}">${badge.text}</span>` : ""}
        </div>
        <div class="pos-product-stock">${stockLabel}</div>
        <button type="button" class="pos-btn-add"
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
    if (p.has_colors && Array.isArray(p.colors) && p.colors.length) {
      openColorPickerModal({
        id: p.id,
        name: p.name,
        price: p.sale_price,
        stock: p.quantity,
        image_url: p.image_url,
        sku: p.sku,
        colors: p.colors,
      });
      return;
    }
    addItem(p.id, p.name, p.sale_price, p.quantity, p.image_url, p.sku, "");
  }

  function openColorPickerModal(product, cartIndex) {
    pendingColorCtx = product;
    colorEditCartIndex = typeof cartIndex === "number" ? cartIndex : -1;
    const modal = $("colorPickerModal");
    const list = $("colorPickerList");
    const title = $("colorPickerProductName");
    if (title) title.textContent = product.name || "اختر اللون";
    if (!list) {
      modal?.classList.add("show");
      return;
    }
    const colors = Array.isArray(product.colors) ? product.colors : [];
    if (!colors.length) {
      list.innerHTML = '<div class="pos-dropdown-empty">لا توجد ألوان معرّفة</div>';
    } else {
      list.innerHTML = colors.map((c) => {
        const name = (c.name || c).toString().replace(/"/g, "&quot;");
        const qty = Number(c.qty ?? c.quantity) || 0;
        return `<button type="button" class="pos-color-option" data-color="${name}" onclick="PosWP.selectColor('${name.replace(/'/g, "\\'")}')">
          <span>${name}</span><small>${qty > 0 ? "متوفر: " + fmt(qty) : "نفد"}</small>
        </button>`;
      }).join("");
    }
    modal?.classList.add("show");
  }

  function closeColorPickerModal() {
    $("colorPickerModal")?.classList.remove("show");
    pendingColorCtx = null;
    colorEditCartIndex = -1;
  }

  function selectColor(colorName) {
    if (!pendingColorCtx) return;
    const color = (colorName || "").trim();
    if (!color) return;
    const p = pendingColorCtx;
    const colorRow = (p.colors || []).find((c) => (c.name || c) === color);
    const colorStock = colorRow ? Number(colorRow.qty ?? colorRow.quantity) || 0 : 0;
    if (colorEditCartIndex >= 0) {
      const item = items[colorEditCartIndex];
      if (item) {
        item.color = color;
        item.color_stock = colorStock + (item.qty || 0);
        const dup = items.find((it, idx) => idx !== colorEditCartIndex && cartLineKey(it.product_id, it.color) === cartLineKey(item.product_id, color));
        if (dup) {
          toast("هذا اللون موجود مسبقاً في السلة");
        } else {
          toast("تم تغيير اللون إلى " + color);
        }
      }
      closeColorPickerModal();
      renderItems();
      return;
    }
    addItem(p.id, p.name, p.price ?? p.sale_price, p.stock ?? p.quantity, p.image_url, p.sku, color, colorStock);
    closeColorPickerModal();
  }

  function changeCartColor(idx) {
    const item = items[idx];
    if (!item) return;
    const p = getProductById(item.product_id);
    if (!p || !p.has_colors) return;
    openColorPickerModal({
      id: p.id,
      name: item.name,
      price: item.price,
      stock: item.stock,
      image_url: item.image_url,
      sku: item.sku,
      colors: p.colors || [],
    }, idx);
  }

  function addItemFromCard(el) {
    if (!el) return;
    const id = parseInt(el.getAttribute("data-id"), 10);
    const p = getProductById(id);
    if (p?.has_colors && p.colors?.length) {
      openColorPickerModal({
        id: p.id,
        name: p.name,
        price: parseInt(el.getAttribute("data-price"), 10) || p.sale_price,
        stock: parseInt(el.getAttribute("data-stock"), 10) || p.quantity,
        image_url: el.getAttribute("data-image") || p.image_url,
        sku: p.sku,
        colors: p.colors,
      });
      return;
    }
    addItem(
      id,
      el.querySelector(".pos-product-name")?.textContent || "",
      parseInt(el.getAttribute("data-price"), 10) || 0,
      parseInt(el.getAttribute("data-stock"), 10) || 0,
      el.getAttribute("data-image") || "",
      ""
    );
  }

  function addItem(id, name, price, stock, imageUrl, sku, color, colorStock) {
    const idNum = typeof id === "string" ? parseInt(id, 10) : id;
    const stockNum = typeof stock === "string" ? parseInt(stock, 10) : (stock || 0);
    const product = getProductById(idNum);
    const img = imageUrl || product?.image_url || "";
    const itemSku = sku || product?.sku || product?.barcode || "";
    const colorName = (color || "").trim();
    const lineKey = cartLineKey(idNum, colorName);
    const item = items.find((i) => cartLineKey(i.product_id, i.color) === lineKey);
    const maxStock = colorName
      ? (Number(colorStock) || (product?.colors || []).find((c) => c.name === colorName)?.qty || 0)
      : stockNum;

    if (item) {
      item.qty++;
      if (maxStock <= 0 || item.qty > maxStock) {
        toast("تمت زيادة الكمية وسيقفل الطلب بانتظار المخزون");
      } else {
        toast("تم زيادة كمية " + name + (colorName ? " — " + colorName : ""));
      }
    } else {
      items.push({
        product_id: idNum,
        name: name || "",
        price: Number(price) || 0,
        qty: 1,
        stock: stockNum,
        color: colorName,
        color_stock: maxStock,
        fulfillment_branch_id: product?.fulfillment_branch_id || null,
        image_url: img,
        sku: itemSku,
      });
      if (maxStock <= 0) {
        toast("تمت الإضافة وسيقفل الطلب بانتظار المخزون");
      } else {
        toast("تم إضافة " + (name || "منتج") + (colorName ? " — " + colorName : "") + " للسلة");
      }
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
    if (newQty <= 0) {
      if (confirm("حذف " + item.name + " من السلة؟")) {
        items.splice(i, 1);
        toast("تم حذف المنتج من السلة");
      }
    } else {
      item.qty = newQty;
      const available = effectiveItemStock(item);
      if (d > 0 && (available <= 0 || newQty > available)) {
        toast("الكمية أكبر من المخزون، سيقفل الطلب بانتظار المخزون");
      }
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
    if (editingOrderId) return;
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

  function clearFieldError(input) {
    if (!input) return;
    input.classList.remove("pos-input--error", "pos-input--shake");
  }

  function showFieldError(input) {
    if (!input) return;
    input.classList.add("pos-input--error");
    input.classList.remove("pos-input--shake");
    void input.offsetWidth;
    input.classList.add("pos-input--shake");
    input.focus();
  }

  function validatePhoneField(input, required) {
    const value = (input?.value || "").trim();
    if (!value) {
      if (required) {
        showFieldError(input);
        return false;
      }
      clearFieldError(input);
      return true;
    }
    if (!isPhone11Digits(value)) {
      showFieldError(input);
      return false;
    }
    clearFieldError(input);
    return true;
  }

  function initPhoneFieldValidation() {
    ["phone", "phone2"].forEach((id) => {
      const input = $(id);
      if (!input) return;
      input.addEventListener("input", () => clearFieldError(input));
      input.addEventListener("blur", () => {
        const value = (input.value || "").trim();
        if (value && !isPhone11Digits(value)) showFieldError(input);
      });
    });
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
    clearFieldError(phone);
    clearFieldError(phone2);
  }

  function openCustomerModal() {
    if (editingOrderId) {
      toast("لا يمكن تغيير الزبون أثناء التعديل");
      return;
    }
    resetCustomerForm();
    $("customerModal")?.classList.add("show");
    $("name")?.focus();
  }

  function closeCustomerModal() {
    $("customerModal")?.classList.remove("show");
    clearFieldError($("phone"));
    clearFieldError($("phone2"));
    closeOCR();
  }

  function isPhone11Digits(value) {
    return /^\d{11}$/.test(String(value || "").trim());
  }

  function saveCustomer() {
    const name = ($("name")?.value || "").trim();
    const phoneEl = $("phone");
    const phone2El = $("phone2");
    const phone = (phoneEl?.value || "").trim();
    const phone2 = (phone2El?.value || "").trim();
    if (!name) { toast("يرجى إدخال اسم الزبون"); return; }
    if (!validatePhoneField(phoneEl, true)) {
      toast(phone ? "رقم الهاتف يجب أن يكون 11 رقم" : "يرجى إدخال رقم الهاتف");
      return;
    }
    if (phone2 && !validatePhoneField(phone2El, false)) {
      toast("رقم الهاتف الثاني يجب أن يكون 11 رقم");
      return;
    }
    const addressValue = ($("address")?.value || "").trim();
    if (!addressValue) { toast("يرجى إدخال العنوان"); $("address")?.focus(); return; }
    const cityValue = ($("city")?.value || "").trim();
    if (!cityValue) { toast("يرجى اختيار المحافظة"); $("city")?.focus(); return; }

    const saveBtn = document.querySelector("#customerModal .pos-btn-primary");
    if (saveBtn?.dataset.busy === "1") return;
    if (saveBtn) saveBtn.dataset.busy = "1";

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
    const ni = $("orderNotesInput");
    if (ni && editingOrderId && initialOrderData?.note) {
      ni.value = String(initialOrderData.note);
    } else if (ni && !editingOrderId) {
      ni.value = "";
    }
    $("orderNotesModal")?.classList.add("show");
    ni?.focus();
  }

  function closeOrderNotesModal() {
    $("orderNotesModal")?.classList.remove("show");
    if (!editingOrderId) {
      const ni = $("orderNotesInput");
      if (ni) ni.value = "";
      const ps = $("pageSelect");
      if (ps) ps.value = "";
    }
  }

  function confirmOrderWithNotes() {
    if (isSubmitting) { toast("جاري إنشاء الطلب، انتظر لحظة..."); return; }
    if (!selectedCustomerId) { toast("اختر زبوناً"); return; }
    if (!items.length) { toast("لا توجد منتجات"); return; }

    const pageSelect = $("pageSelect");
    let pageId = null;
    let pageName = null;
    if (editingOrderId) {
      const locked = getLockedPagePayload();
      pageId = locked.pageId;
      pageName = locked.pageName;
    } else {
      if (pageSelect && !pageSelect.value) {
        toast("يرجى اختيار البيج أو 'لا يوجد بيج'");
        pageSelect.focus();
        return;
      }
      if (pageSelect && pageSelect.value && pageSelect.value !== "no_page") {
        pageId = pageSelect.value;
        const opt = pageSelect.options[pageSelect.selectedIndex];
        pageName = opt ? opt.getAttribute("data-name") || opt.text : null;
      }
    }

    const notes = ($("orderNotesInput")?.value || "").trim()
      || ($("invoiceNotes")?.value || "").trim();

    isSubmitting = true;
    activeSubmissionToken = createSubmissionToken();
    setSubmitBusy(true);
    updateStats();
    const btn = $("btnExecute");
    const btnM = $("btnExecuteMobile");
    if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> جاري التنفيذ...';
    if (btnM) btnM.innerHTML = '<i class="fas fa-spinner fa-spin"></i> ...';

    fetch("/pos/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_id: editingOrderId || null,
        customer_id: selectedCustomerId,
        items: serializeCartItems(),
        note: notes || null,
        scheduled_date: null,
        page_id: pageId || null,
        page_name: pageName || null,
        discount_amount: Number(discountValue) || 0,
        submission_token: activeSubmissionToken,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        isSubmitting = false;
        activeSubmissionToken = null;
        setSubmitBusy(false);
        if (btn) btn.innerHTML = editingOrderId ? '<i class="fas fa-save"></i> حفظ التعديل' : '<i class="fas fa-print"></i> تنفيذ و طباعة';
        if (btnM) btnM.innerHTML = editingOrderId ? '<i class="fas fa-save"></i> حفظ' : '<i class="fas fa-print"></i> تنفيذ';
        if (d.error) {
          toast(d.error);
          updateStats();
          return;
        }
        toast(d.stock_locked ? "تم إنشاء الطلب مقفلاً بانتظار المخزون" : (editingOrderId ? "تم حفظ التعديل" : "تم تنفيذ البيع وإنشاء الفاتورة"));
        if (!d.stock_locked) items.forEach((i) => syncLocalStock(i.product_id, i.qty));
        closeOrderNotesModal();
        printServerInvoice(d.invoice_id);
        if (!editingOrderId) {
          items = [];
          selectedCustomerId = null;
          clearCustomerDisplay();
          if (pageSelect) pageSelect.value = "";
        } else if (initialOrderData) {
          initialOrderData.note = notes || "";
        }
        renderItems();
      })
      .catch((err) => {
        isSubmitting = false;
        activeSubmissionToken = null;
        setSubmitBusy(false);
        if (btn) btn.innerHTML = editingOrderId ? '<i class="fas fa-save"></i> حفظ التعديل' : '<i class="fas fa-print"></i> تنفيذ و طباعة';
        if (btnM) btnM.innerHTML = editingOrderId ? '<i class="fas fa-save"></i> حفظ' : '<i class="fas fa-print"></i> تنفيذ';
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
    if (isSubmitting) { toast("جاري إنشاء الطلب، انتظر لحظة..."); return; }
    const scheduleDate = $("scheduleDateInput")?.value;
    if (!scheduleDate) { toast("اختر تاريخ التأجيل"); return; }
    if (!selectedCustomerId || !items.length) return;

    const notes = ($("scheduleNotesInput")?.value || "").trim();
    const pageSelect = $("pageSelect");
    let pageId = null;
    if (editingOrderId) {
      pageId = getLockedPagePayload().pageId;
    } else if (pageSelect?.value && pageSelect.value !== "no_page") {
      pageId = pageSelect.value;
    }

    isSubmitting = true;
    activeSubmissionToken = createSubmissionToken();
    setSubmitBusy(true);

    fetch("/pos/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_id: editingOrderId || null,
        customer_id: selectedCustomerId,
        items: serializeCartItems(),
        note: notes || null,
        scheduled_date: scheduleDate,
        page_id: pageId || null,
        discount_amount: Number(discountValue) || 0,
        submission_token: activeSubmissionToken,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        isSubmitting = false;
        activeSubmissionToken = null;
        setSubmitBusy(false);
        if (d.error) { toast(d.error); return; }
        if (!d.stock_locked) items.forEach((i) => syncLocalStock(i.product_id, i.qty));
        toast(d.stock_locked ? "تم تأجيل الطلب مقفلاً بانتظار المخزون" : "تم تأجيل الطلب — رقم " + d.invoice_id);
        closeScheduleModal();
        items = [];
        selectedCustomerId = null;
        clearCustomerDisplay();
        renderItems();
      })
      .catch((err) => {
        isSubmitting = false;
        activeSubmissionToken = null;
        setSubmitBusy(false);
        toast("حدث خطأ: " + err.message);
      });
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
            if (d[0].has_colors && Array.isArray(d[0].colors) && d[0].colors.length) {
              openColorPickerModal({
                id: d[0].id,
                name: d[0].name,
                price: d[0].price,
                stock: d[0].quantity,
                image_url: d[0].image_url || p?.image_url,
                sku: p?.sku,
                colors: d[0].colors,
              });
            } else {
              addItem(d[0].id, d[0].name, d[0].price, d[0].quantity, d[0].image_url || p?.image_url, p?.sku, "");
            }
            if (searchProduct) searchProduct.value = "";
            productSearchQuery = "";
            return;
          }
          productSearchQuery = val.toLowerCase();
          currentPage = 1;
          renderProductGrid();
          if (d.length > 0 && productResults) {
            productResults.innerHTML = d.map((p) => {
              const nameEsc = (p.name || "").replace(/</g, "&lt;");
              return `<div class="pos-product-item" onclick="PosWP.addItemById(${p.id})">${nameEsc} — ${fmt(p.price)} <small>(${fmt(p.quantity || 0)})</small></div>`;
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
    initPhoneFieldValidation();

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
      const discountInput = $("discountValue");
      if (discountInput) discountInput.value = String(discountValue);
      lockEditModeUi();
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
    openColorPickerModal,
    closeColorPickerModal,
    selectColor,
    changeCartColor,
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
