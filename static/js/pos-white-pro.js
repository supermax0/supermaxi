/* Finora POS White Pro — client logic */
(function () {
  "use strict";

  const bootstrapEl = document.getElementById("posBootstrapData");
  const bootstrap = bootstrapEl ? JSON.parse(bootstrapEl.textContent || "{}") : {};
  const canEditPrice = !!bootstrap.canEditPrice;
  const canPrintInvoice = !!bootstrap.canPrintInvoice;
  const isAdmin = !!bootstrap.isAdmin;
  const independentBranches = bootstrap.independentBranches !== false;
  const allProducts = Array.isArray(bootstrap.products) ? bootstrap.products : [];
  const PRIMARY_PROVINCE = String(bootstrap.primaryProvince || "بغداد").trim() || "بغداد";

  let items = [];
  let selectedCustomerId = null;
  let selectedCustomerName = "";
  let selectedCustomerCity = "";
  let selectedCustomerPhone = "";
  let customerSearchCache = Object.create(null);
  let editingOrderId = null;
  let currentPriceEditIndex = -1;
  let pendingColorCtx = null;
  let pendingSaleCtx = null;
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
  let orderInstallmentUi = Object.assign({}, bootstrap.orderInstallmentUi || {});
  let selectedBranchId = Number(initialOrderData?.branch_id || bootstrap.currentBranchId) || null;
  if (initialOrderData) {
    editingOrderId = initialOrderData.id ?? null;
    selectedCustomerId = initialOrderData.customer_id ?? null;
    selectedCustomerName = initialOrderData.customer_name || "";
    selectedCustomerCity = initialOrderData.customer_city || "";
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
          sale_mode: it.sale_mode || "normal",
          trade_in_source_product_id: it.trade_in_source_product_id || null,
          trade_in_source_product_name: it.trade_in_source_product_name || "",
          fulfillment_branch_id: it.fulfillment_branch_id || null,
          image_url: it.image_url || "",
          sku: it.sku || "",
        }))
      : [];
  }

  const $ = (id) => document.getElementById(id);

  function currentPosBranchId() {
    const value = $("posBranchSelect")?.value || selectedBranchId;
    return Number(value) || null;
  }

  function productsForCurrentBranch() {
    if (!independentBranches) return allProducts;
    const branchId = currentPosBranchId();
    if (!branchId) return [];
    return allProducts.filter((product) => Number(product.branch_id) === branchId);
  }

  function debounce(fn, ms) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  let orderSuccessTimer = null;

  function toast(msg, type, options) {
    options = options || {};
    const t = $("posToast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 3000);

    if (options.silent || options.sound === false) return;

    if (typeof window.playNotificationSound === "function") {
      var soundType = options.soundType;
      if (!soundType && typeof window.finoraInferNotificationSound === "function") {
        soundType = window.finoraInferNotificationSound(msg);
      }
      if (soundType) {
        window.playNotificationSound(soundType, { soundType: soundType, message: msg });
      }
    }
  }

  function showOrderCreatedNotification(invoiceId, stockLocked) {
    const el = $("posOrderSuccess");
    const detail = $("posOrderSuccessDetail");
    const parts = [];
    if (invoiceId) parts.push("رقم الفاتورة: " + invoiceId);
    if (stockLocked) parts.push("مقفل بانتظار المخزون");

    if (detail) detail.textContent = parts.join(" — ");

    if (typeof window.playNotificationSound === "function") {
      window.playNotificationSound("buzz", { soundType: "buzz" });
    }

    if (!el) {
      toast(stockLocked ? "تم إنشاء الطلب مقفلاً بانتظار المخزون" : "تم إنشاء الطلب", "success", { silent: true });
      return;
    }

    el.hidden = false;
    el.classList.add("show");
    clearTimeout(orderSuccessTimer);
    orderSuccessTimer = setTimeout(function () {
      el.classList.remove("show");
      setTimeout(function () { el.hidden = true; }, 320);
    }, 4500);
  }

  function fmt(n) {
    return (Number(n) || 0).toLocaleString("en-US");
  }

  function colorSwatchCss(colorName) {
    const raw = String(colorName || "").trim();
    if (/^#[0-9a-f]{3,8}$/i.test(raw) || /^rgba?\(/i.test(raw) || /^hsla?\(/i.test(raw)) {
      return raw;
    }
    const normalized = raw
      .toLowerCase()
      .replace(/[أإآ]/g, "ا")
      .replace(/ة/g, "ه")
      .replace(/\s+/g, "");
    const known = [
      [["ابيض", "white"], "#ffffff"],
      [["اسود", "black"], "#111827"],
      [["احمر", "red"], "#ef4444"],
      [["اخضر", "green"], "#22c55e"],
      [["ازرق", "blue"], "#3b82f6"],
      [["سماوي", "cyan"], "#22d3ee"],
      [["كحلي", "navy"], "#172554"],
      [["اصفر", "yellow"], "#facc15"],
      [["برتقالي", "orange"], "#f97316"],
      [["بنفسجي", "purple"], "#8b5cf6"],
      [["وردي", "pink"], "#ec4899"],
      [["بني", "brown"], "#92400e"],
      [["بيج", "beige"], "#d6c6a5"],
      [["رمادي", "gray", "grey"], "#94a3b8"],
      [["فضي", "silver"], "linear-gradient(135deg,#f8fafc,#94a3b8)"],
      [["ذهبي", "gold"], "linear-gradient(135deg,#fde68a,#d97706)"],
    ];
    const match = known.find(([aliases]) => aliases.some((alias) => normalized.includes(alias)));
    if (match) return match[1];
    let hash = 0;
    for (let index = 0; index < raw.length; index += 1) {
      hash = ((hash << 5) - hash + raw.charCodeAt(index)) | 0;
    }
    return `hsl(${Math.abs(hash) % 360} 68% 52%)`;
  }

  function getProductById(id) {
    // Shared mode already receives one merged card per catalog family.
    // Do not reject it merely because its representative record belongs to
    // a different physical branch; the server resolves that branch copy at
    // checkout before it deducts stock.
    if (!independentBranches) {
      return allProducts.find((p) => Number(p.id) === Number(id));
    }
    const branchId = currentPosBranchId();
    return allProducts.find((p) => Number(p.id) === Number(id) && Number(p.branch_id) === branchId);
  }

  function cartLineKey(productId, color, saleMode, sourceProductId) {
    return [
      String(productId),
      ((color || "").trim() || ""),
      saleMode || "normal",
      "",
    ].join("::");
  }

  function isPrimaryCustomerCity(city) {
    const value = String(city || "").trim();
    if (!value) return true;
    return value === PRIMARY_PROVINCE;
  }

  function regionSalePriceForProduct(product, colorRow) {
    const bagdad = colorRow && colorRow.sale_price != null && colorRow.sale_price !== ""
      ? Number(colorRow.sale_price)
      : Number(product?.price ?? product?.sale_price ?? 0);
    if (!product?.dual_region_pricing) return bagdad || 0;
    if (isPrimaryCustomerCity(selectedCustomerCity)) return bagdad || 0;
    const govRaw = colorRow && colorRow.governorate_sale_price != null && colorRow.governorate_sale_price !== ""
      ? Number(colorRow.governorate_sale_price)
      : Number(product?.governorate_sale_price ?? 0);
    return (govRaw > 0 ? govRaw : bagdad) || 0;
  }

  function repriceCartForCustomerCity() {
    let changed = false;
    items.forEach((item) => {
      if (String(item.sale_mode || "normal") !== "normal") return;
      const product = getProductById(item.product_id);
      if (!product?.dual_region_pricing) return;
      const colorRow = item.color
        ? (product.colors || []).find((c) => (c.name || c) === item.color)
        : null;
      const next = regionSalePriceForProduct(product, colorRow);
      if (next > 0 && Number(item.price) !== next) {
        item.price = next;
        changed = true;
      }
    });
    if (changed) renderItems();
  }

  function serializeCartItems() {
    const branchId = currentPosBranchId();
    return items.map(({ product_id, qty, price, color, sale_mode }) => ({
      product_id,
      qty,
      price,
      color: (color || "").trim() || null,
      sale_mode: sale_mode || "normal",
      fulfillment_branch_id: branchId,
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
    const branchSelect = $("posBranchSelect");
    if (branchSelect && isAdmin && !editingOrderId) branchSelect.disabled = !!busy;
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
        badge.textContent = "الزبون المختار: لم يتم اختيار زبون (نقدي عام)";
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
      badge.textContent = "الزبون المختار: لم يتم اختيار زبون (نقدي عام)";
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
    const countLabel = count + " أصناف";
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

  function cartSaleBadgeHtml(item) {
    return item?.sale_mode === "exchange"
      ? '<span class="pos-color-badge">استبدال</span>'
      : '<span class="pos-color-badge">بيع</span>';
  }

  function renderItems() {
    const tbody = $("orderItems");
    const mobileList = $("cartMobileList");
    const itemCountEl = $("itemCount");
    const count = items.reduce((s, i) => s + (i.qty || 0), 0);
    if (itemCountEl) itemCountEl.textContent = count + " أصناف";

    const rowHtml = items.map((i, idx) => {
      const t = (i.price || 0) * (i.qty || 0);
      const sku = i.sku || "";
      const color = (i.color || "").trim();
      const colorBadge = color
        ? `<button type="button" class="pos-color-badge" onclick="PosWP.changeCartColor(${idx})" title="تغيير اللون">${color}</button>`
        : "";
      const saleBadge = cartSaleBadgeHtml(i);
      const priceLabel = cartPriceHtml(i.price, idx);
      return `<tr>
        <td>
          <div class="pos-cart-product-cell">
            ${cartThumbHtml(i)}
            <div>
              <strong>${i.name}</strong>
              ${colorBadge}
              ${saleBadge}
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

    const cartEmpty = $("cartEmptyState");
    const cartTable = tbody ? tbody.closest(".pos-cart-table") : null;
    if (cartEmpty) cartEmpty.hidden = items.length > 0;
    if (cartTable) cartTable.hidden = items.length === 0;

    const mobileHtml = items.map((i, idx) => {
      const t = (i.price || 0) * (i.qty || 0);
      const color = (i.color || "").trim();
      const saleBadge = cartSaleBadgeHtml(i);
      return `<div class="pos-cart-mobile-item">
        <div class="pos-cart-mobile-thumb-wrap">${cartThumbHtml(i)}</div>
        <div class="pos-cart-mobile-main">
          <div class="pos-cart-mobile-item-name">${i.name}</div>
          <div class="pos-cart-mobile-meta">
            ${color ? `<span class="pos-color-badge pos-color-badge--sm" onclick="PosWP.changeCartColor(${idx})">${color}</span>` : ""}
            ${saleBadge}
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
    let list = productsForCurrentBranch();
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
          onclick="PosWP.addItemById(${p.id})"><i class="fas fa-plus"></i> إضافة</button>
      </article>`;
    }).join("");
  }

  async function refreshCatalogStock() {
    try {
      const response = await fetch("/pos/all-products");
      if (!response.ok) throw new Error("catalog request failed");
      const data = await response.json();
      if (!Array.isArray(data.products)) throw new Error("invalid catalog response");
      allProducts.splice(0, allProducts.length, ...data.products);
      filterInventory();
      buildCategoryTabs();
      renderProductGrid();
    } catch (error) {
      toast("تم حفظ الطلب، لكن تعذّر تحديث المخزون. حدّث الصفحة قبل البيع التالي.", "warning");
    }
  }

  function addItemById(id) {
    const p = getProductById(id);
    if (!p) return;
    if (p.has_colors && Array.isArray(p.colors) && p.colors.length) {
      openColorPickerModal({
        id: p.id,
        name: p.name,
        price: regionSalePriceForProduct(p, null),
        stock: p.quantity,
        image_url: p.image_url,
        sku: p.sku,
        colors: p.colors,
        dual_region_pricing: p.dual_region_pricing,
        governorate_sale_price: p.governorate_sale_price,
        sale_price: p.sale_price,
      });
      return;
    }
    chooseSaleMode({ ...p, sale_price: regionSalePriceForProduct(p, null), price: regionSalePriceForProduct(p, null) }, "", 0);
  }

  function chooseSaleMode(product, color, colorStock) {
    const normalPrice = Number(product.sale_price ?? product.price) || 0;
    if (!product?.has_exchange_sale) {
      addItem(
        product.id, product.name, normalPrice, product.quantity,
        product.image_url, product.sku, color || "", colorStock,
        "normal", null, ""
      );
      return;
    }
    pendingSaleCtx = { product, color: color || "", colorStock: Number(colorStock) || 0 };
    const modal = $("saleModePickerModal");
    const title = $("saleModeProductName");
    if (title) title.textContent = product.name;
    const normalPriceEl = $("normalSaleModePrice");
    const exchangePrice = $("exchangeSaleModePrice");
    if (normalPriceEl) normalPriceEl.textContent = fmt(normalPrice) + " د.ع";
    if (exchangePrice) exchangePrice.textContent = fmt(product.exchange_sale_price) + " د.ع";
    modal?.classList.add("show");
  }

  function closeSaleModePickerModal() {
    $("saleModePickerModal")?.classList.remove("show");
    pendingSaleCtx = null;
  }

  function selectSaleMode(mode) {
    if (!pendingSaleCtx) return;
    if (mode === "exchange") {
      const { product, color, colorStock } = pendingSaleCtx;
      addItem(
        product.id, product.name, product.exchange_sale_price, product.quantity,
        product.image_url, product.sku, color, colorStock, "exchange", null, ""
      );
      closeSaleModePickerModal();
      return;
    }
    const { product, color, colorStock } = pendingSaleCtx;
    addItem(
      product.id, product.name, Number(product.sale_price ?? product.price) || 0, product.quantity,
      product.image_url, product.sku, color, colorStock, "normal", null, ""
    );
    closeSaleModePickerModal();
  }

  function confirmExchangeSale() {
    if (!pendingSaleCtx) return;
    const { product, color, colorStock } = pendingSaleCtx;
    addItem(
      product.id, product.name, product.exchange_sale_price, product.quantity,
      product.image_url, product.sku, color, colorStock,
      "exchange", null, ""
    );
    closeSaleModePickerModal();
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
      list.innerHTML = colors.map((c, index) => {
        const rawName = (c.name || c).toString();
        const name = escapeHtml(rawName);
        const qty = Number(c.qty ?? c.quantity) || 0;
        const salePrice = regionSalePriceForProduct(product, c);
        const stateClass = qty > 0 ? "is-available" : "is-unavailable";
        return `<button type="button" class="pos-color-option pos-color-choice-card ${stateClass}" onclick="PosWP.selectColorByIndex(${index})">
          <span class="pos-color-swatch" style="--pos-choice-color:${colorSwatchCss(rawName)}">
            <i class="fas fa-check"></i>
          </span>
          <span class="pos-color-choice-copy">
            <strong>${name}</strong>
            <small>${qty > 0 ? "جاهز للبيع · " + fmt(salePrice) + " د.ع" : "يمكن إضافته بانتظار المخزون"}</small>
          </span>
          <span class="pos-color-stock">${qty > 0 ? fmt(qty) + " قطعة" : "نفد"}</span>
          <i class="fas fa-chevron-left pos-color-choice-arrow"></i>
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
    const p = getProductById(pendingColorCtx.id) || pendingColorCtx;
    const colorRow = (p.colors || []).find((c) => (c.name || c) === color);
    const colorStock = colorRow ? Number(colorRow.qty ?? colorRow.quantity) || 0 : 0;
    const colorSalePrice = regionSalePriceForProduct(p, colorRow);
    if (colorEditCartIndex >= 0) {
      const item = items[colorEditCartIndex];
      if (item) {
        item.color = color;
        item.color_stock = colorStock + (item.qty || 0);
        if (String(item.sale_mode || "normal") === "normal") {
          item.price = colorSalePrice;
        }
        const dup = items.find((it, idx) =>
          idx !== colorEditCartIndex &&
          cartLineKey(it.product_id, it.color, it.sale_mode, it.trade_in_source_product_id) ===
            cartLineKey(item.product_id, color, item.sale_mode, item.trade_in_source_product_id)
        );
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
    chooseSaleMode(
      { ...p, sale_price: colorSalePrice, price: colorSalePrice, quantity: p.stock ?? p.quantity },
      color,
      colorStock
    );
    closeColorPickerModal();
  }

  function selectColorByIndex(index) {
    if (!pendingColorCtx) return;
    const product = getProductById(pendingColorCtx.id) || pendingColorCtx;
    const row = (product.colors || [])[Number(index)];
    if (!row) return;
    selectColor((row.name || row).toString());
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
        price: regionSalePriceForProduct(p, null),
        stock: parseInt(el.getAttribute("data-stock"), 10) || p.quantity,
        image_url: el.getAttribute("data-image") || p.image_url,
        sku: p.sku,
        colors: p.colors,
        dual_region_pricing: p.dual_region_pricing,
        governorate_sale_price: p.governorate_sale_price,
        sale_price: p.sale_price,
      });
      return;
    }
    const priced = p
      ? { ...p, sale_price: regionSalePriceForProduct(p, null), price: regionSalePriceForProduct(p, null) }
      : p;
    chooseSaleMode(priced, "", 0);
  }

  function addItem(id, name, price, stock, imageUrl, sku, color, colorStock, saleMode, sourceProductId, sourceProductName) {
    const idNum = typeof id === "string" ? parseInt(id, 10) : id;
    const stockNum = typeof stock === "string" ? parseInt(stock, 10) : (stock || 0);
    const product = getProductById(idNum);
    const img = imageUrl || product?.image_url || "";
    const itemSku = sku || product?.sku || product?.barcode || "";
    const colorName = (color || "").trim();
    const mode = saleMode || "normal";
    const lineKey = cartLineKey(idNum, colorName, mode, sourceProductId);
    const item = items.find((i) =>
      cartLineKey(i.product_id, i.color, i.sale_mode, i.trade_in_source_product_id) === lineKey
    );
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
        sale_mode: mode,
        trade_in_source_product_id: null,
        trade_in_source_product_name: "",
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
    repriceCartForCustomerCity();
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
    const branchId = currentPosBranchId();
    if (!branchId) { toast("اختر فرع خصم المخزون"); return; }

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
        branch_id: branchId,
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
          repriceCartForCustomerCity();
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
    if (!currentPosBranchId()) { toast("اختر فرع خصم المخزون"); return; }
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

  async function toggleInstallmentOrderMode() {
    if (!orderInstallmentUi.can_toggle) return;
    const enabling = !orderInstallmentUi.mode_on;
    try {
      const res = await fetch(enabling ? "/api/order-installment/mode/enable" : "/api/order-installment/mode/disable", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        toast(data.error || "تعذر تبديل وضع الأقساط");
        return;
      }
      orderInstallmentUi.mode_on = !!data.mode_on;
      const btn = $("installmentModeToggleBtn");
      const label = $("installmentModeToggleLabel");
      const banner = $("installmentModeBanner");
      if (btn) {
        btn.classList.toggle("is-on", orderInstallmentUi.mode_on);
        btn.classList.toggle("is-off", !orderInstallmentUi.mode_on);
        btn.setAttribute("aria-pressed", orderInstallmentUi.mode_on ? "true" : "false");
      }
      if (label) label.textContent = orderInstallmentUi.mode_on ? "ON" : "OFF";
      if (btn) btn.classList.toggle("is-off", !orderInstallmentUi.mode_on);
      if (banner) banner.style.display = orderInstallmentUi.mode_on ? "block" : "none";
      toast(data.message || (orderInstallmentUi.mode_on ? "تم تفعيل وضع الأقساط" : "تم إيقاف وضع الأقساط"));
    } catch (e) {
      toast("تعذر تبديل وضع الأقساط");
    }
  }

  function confirmOrderWithNotes() {
    if (isSubmitting) { toast("جاري إنشاء الطلب، انتظر لحظة..."); return; }
    if (!selectedCustomerId) { toast("اختر زبوناً"); return; }
    if (!items.length) { toast("لا توجد منتجات"); return; }
    const branchId = currentPosBranchId();
    if (!branchId) { toast("اختر فرع خصم المخزون"); return; }

    const oilUi = orderInstallmentUi || {};
    if (!editingOrderId && oilUi.mode_on && oilUi.settings && oilUi.settings.confirm_on_create !== false) {
      const days = (oilUi.settings && oilUi.settings.duration_value) || 7;
      const unit = (oilUi.settings && oilUi.settings.duration_unit) === "hours" ? "ساعات" : "أيام";
      const due = new Date();
      if ((oilUi.settings && oilUi.settings.duration_unit) === "hours") {
        due.setHours(due.getHours() + Number(days));
      } else {
        due.setDate(due.getDate() + Number(days));
      }
      const dueLabel = due.toLocaleDateString("en-GB");
      if (!window.confirm(
        "إنشاء طلب أقساط؟\n\nسيتم تسجيل هذا الطلب ضمن دورة أقساط مدتها " +
        days + " " + unit + ".\n\nإذا لم يتم ترجيعه قبل " + dueLabel +
        "\nسيتم تسديده تلقائياً."
      )) {
        return;
      }
    }

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
        branch_id: branchId,
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
        if (btn) btn.innerHTML = editingOrderId
          ? '<i class="fas fa-save"></i> حفظ التعديل'
          : canPrintInvoice
            ? '<i class="fas fa-print"></i> تنفيذ و طباعة'
            : '<i class="fas fa-check"></i> تنفيذ';
        if (btnM) btnM.innerHTML = editingOrderId
          ? '<i class="fas fa-save"></i> حفظ'
          : canPrintInvoice
            ? '<i class="fas fa-print"></i> تنفيذ و طباعة'
            : '<i class="fas fa-check"></i> تنفيذ';
        if (d.error) {
          toast(d.error);
          updateStats();
          return;
        }
        showSavedInvoice(d.invoice_id);
        if (editingOrderId) {
          toast("تم حفظ التعديل", "success");
        } else {
          showOrderCreatedNotification(d.invoice_id, d.stock_locked);
        }
        refreshCatalogStock();
        closeOrderNotesModal();
        if (!editingOrderId) {
          items = [];
          selectedCustomerId = null;
          clearCustomerDisplay();
          if (pageSelect) pageSelect.value = "";
        } else if (initialOrderData) {
          initialOrderData.note = notes || "";
        }
        renderItems();
        if (canPrintInvoice) {
          try {
            printServerInvoice(d.invoice_id);
          } catch (error) {
            toast("تم حفظ الطلب. افتح الفاتورة من الرابط لإعادة الطباعة.", "warning");
          }
        }
      })
      .catch((err) => {
        isSubmitting = false;
        activeSubmissionToken = null;
        setSubmitBusy(false);
        if (btn) btn.innerHTML = editingOrderId
          ? '<i class="fas fa-save"></i> حفظ التعديل'
          : canPrintInvoice
            ? '<i class="fas fa-print"></i> تنفيذ و طباعة'
            : '<i class="fas fa-check"></i> تنفيذ';
        if (btnM) btnM.innerHTML = editingOrderId
          ? '<i class="fas fa-save"></i> حفظ'
          : canPrintInvoice
            ? '<i class="fas fa-print"></i> تنفيذ و طباعة'
            : '<i class="fas fa-check"></i> تنفيذ';
        toast("حدث خطأ: " + err.message);
        updateStats();
      });
  }

  function printServerInvoice(invoiceId) {
    if (!canPrintInvoice) return;
    finoraPrintUrl("/orders/invoice/" + encodeURIComponent(invoiceId));
  }

  function showSavedInvoice(invoiceId) {
    const panel = $("posSavedInvoice");
    const link = $("posSavedInvoiceLink");
    const label = $("posSavedInvoiceLabel");
    if (!panel || !link || !label || !invoiceId || !canPrintInvoice) return;
    link.href = "/orders/invoice/" + encodeURIComponent(invoiceId);
    label.textContent = "تم حفظ الفاتورة #" + invoiceId;
    panel.hidden = false;
  }

  function openScheduleModal() {
    if (!currentPosBranchId()) { toast("اختر فرع خصم المخزون"); return; }
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
    const branchId = currentPosBranchId();
    if (!branchId) { toast("اختر فرع خصم المخزون"); return; }

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
        branch_id: branchId,
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
        refreshCatalogStock();
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
    const branchId = currentPosBranchId();
    document.querySelectorAll("#inventoryModalList .inventory-card").forEach((card) => {
      const name = (card.getAttribute("data-name") || "").toLowerCase();
      const sameBranch = Number(card.getAttribute("data-branch-id")) === branchId;
      card.style.display = sameBranch && name.includes(q) ? "" : "none";
    });
  }

  function buildCategoryTabs() {
    const container = $("categoryPills");
    if (!container) return;

    const cats = new Set();
    let hasOffers = false;
    productsForCurrentBranch().forEach((p) => {
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
        const branchId = currentPosBranchId();
        if (!branchId) { toast("اختر فرع خصم المخزون"); return; }
        fetch("/pos/search-customer?q=" + encodeURIComponent(val) + "&branch_id=" + encodeURIComponent(branchId))
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
      const branchId = currentPosBranchId();
      if (!branchId) { toast("اختر فرع خصم المخزون"); return; }
      fetch("/pos/search-product?q=" + encodeURIComponent(val) + "&branch_id=" + encodeURIComponent(branchId))
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
              chooseSaleMode(p || d[0], "", 0);
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
              return `<div class="pos-product-item" onclick="PosWP.addItemById(${p.id})">${nameEsc} — ${fmt(p.price)} <small>المخزون: ${fmt(p.quantity || 0)}</small></div>`;
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

  function initBranchSelector() {
    const select = $("posBranchSelect");
    if (!select) return;
    if (selectedBranchId) select.value = String(selectedBranchId);
    selectedBranchId = Number(select.value) || selectedBranchId;
    select.addEventListener("change", () => {
      const nextBranchId = Number(select.value) || null;
      if (!nextBranchId || nextBranchId === selectedBranchId) return;
      selectedBranchId = nextBranchId;
      items = [];
      selectedCustomerId = null;
      selectedCustomerName = "";
      selectedCustomerCity = "";
      selectedCustomerPhone = "";
      customerSearchCache = Object.create(null);
      discountValue = 0;
      activeCategory = "all";
      productSearchQuery = "";
      currentPage = 1;
      const customerInput = $("searchCustomer");
      if (customerInput) customerInput.value = "";
      const productInput = $("searchProduct");
      if (productInput) productInput.value = "";
      clearCustomerDisplay();
      buildCategoryTabs();
      filterInventory();
      renderProductGrid();
      renderItems();
      toast("تم تغيير فرع الخصم وإفراغ السلة والزبون السابقين");
    });
  }

  function init() {
    initBranchSelector();
    filterInventory();
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
    selectColorByIndex,
    changeCartColor,
    closeSaleModePickerModal,
    selectSaleMode,
    confirmExchangeSale,
    pickCustomerFromSearch,
    openCustomerModal,
    closeCustomerModal,
    saveCustomer,
    openOrderNotesModal,
    closeOrderNotesModal,
    confirmOrderWithNotes,
    toggleInstallmentOrderMode,
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
