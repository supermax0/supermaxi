/* Finora POS White Pro — client logic (same APIs as stable POS) */
(function () {
  "use strict";

  const bootstrapEl = document.getElementById("posBootstrapData");
  const bootstrap = bootstrapEl ? JSON.parse(bootstrapEl.textContent || "{}") : {};
  const canEditPrice = !!bootstrap.canEditPrice;
  const allProducts = Array.isArray(bootstrap.products) ? bootstrap.products : [];
  const cashBalanceBase = Number(bootstrap.cashBalance) || 0;

  let items = [];
  let selectedCustomerId = null;
  let editingOrderId = null;
  let currentPriceEditIndex = -1;
  let activeCategory = "all";
  let productSearchQuery = "";
  let discountType = "amount";
  let discountValue = 0;
  let shippingValue = 0;
  let lastOrderLabel = "—";
  let isSubmitting = false;

  const initialOrderData = bootstrap.orderData ?? null;
  if (initialOrderData) {
    editingOrderId = initialOrderData.id ?? null;
    selectedCustomerId = initialOrderData.customer_id ?? null;
    items = Array.isArray(initialOrderData.items) ? initialOrderData.items.slice() : [];
  }

  const $ = (id) => document.getElementById(id);

  function toast(msg) {
    const t = $("posToast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 3000);
  }

  function fmt(n) {
    return (Number(n) || 0).toLocaleString("ar-IQ");
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

  function stockBadge(qty) {
    if (qty <= 0) return { cls: "out", text: "نفد" };
    if (qty <= 5) return { cls: "low", text: "مخزون منخفض" };
    return { cls: "ok", text: "متوفر" };
  }

  function updateStats() {
    const total = calcTotal();
    const count = items.reduce((s, i) => s + (i.qty || 0), 0);
    const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
    set("statCartTotal", fmt(total) + " د.ع");
    set("statItemCount", String(count));
    set("statCashBalance", fmt(cashBalanceBase) + " د.ع");
    set("statLastSale", lastOrderLabel);
    const mcb = $("mobileCartBtn");
    if (mcb) mcb.textContent = `السلة: ${count} منتجات — ${fmt(total)} د.ع`;
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
    const set = (id, val) => { const el = $(id); if (el) el.textContent = val; };
    set("summarySubtotal", fmt(sub) + " د.ع");
    set("summaryDiscount", disc > 0 ? "−" + fmt(disc) + " د.ع" : "0 د.ع");
    set("summaryShipping", fmt(ship) + " د.ع");
    set("summaryTotal", fmt(total) + " د.ع");
    set("summaryTotalMobile", fmt(total) + " د.ع");
    const tp = $("totalPrice");
    if (tp) tp.textContent = fmt(total);
    updateOperationImpact(total);
    updateStats();
  }

  function updateOperationImpact(total) {
    const box = $("operationImpactList");
    if (!box) return;
    if (!items.length) {
      box.innerHTML = "<li>أضف منتجات لمعاينة أثر العملية</li>";
      return;
    }
    const lines = items.map((i) => {
      return `<li>${i.name}: −${i.qty} من المخزون</li>`;
    });
    lines.push(`<li>الصندوق: +${fmt(total)} د.ع عند الدفع النقدي</li>`);
    lines.push("<li>فاتورة جديدة سيتم إنشاؤها</li>");
    lines.push("<li>حالة الدفع: غير مسدد (حسب المنطق الحالي)</li>");
    box.innerHTML = lines.join("");
  }

  function renderItems() {
    const tbody = $("orderItems");
    const mobileList = $("cartMobileList");
    const itemCountEl = $("itemCount");
    const count = items.reduce((s, i) => s + (i.qty || 0), 0);
    if (itemCountEl) itemCountEl.textContent = count + " منتج";

    const rowHtml = items.map((i, idx) => {
      const t = (i.price || 0) * (i.qty || 0);
      const priceEdit = canEditPrice
        ? `<button type="button" class="pos-qty-btn" onclick="PosWP.changePrice(${idx})" title="تعديل السعر"><i class="fas fa-pen"></i></button>`
        : "";
      return `<tr>
        <td><strong>${i.name}</strong></td>
        <td>${fmt(i.price)} د.ع ${priceEdit}</td>
        <td>
          <div class="pos-qty-stepper">
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},-1)">−</button>
            <span style="min-width:24px;text-align:center;font-weight:700">${i.qty}</span>
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},1)">+</button>
          </div>
        </td>
        <td style="font-weight:700">${fmt(t)} د.ع</td>
        <td><button type="button" class="pos-btn-remove" onclick="PosWP.removeItem(${idx})" title="حذف">×</button></td>
      </tr>`;
    }).join("");

    if (tbody) tbody.innerHTML = rowHtml;

    const mobileHtml = items.map((i, idx) => {
      const t = (i.price || 0) * (i.qty || 0);
      return `<div class="pos-cart-mobile-item">
        <div class="pos-cart-mobile-item-head">
          <div class="pos-cart-mobile-item-name">${i.name}</div>
          <button type="button" class="pos-btn-remove" onclick="PosWP.removeItem(${idx})">×</button>
        </div>
        <div class="pos-product-row">
          <span>${fmt(i.price)} د.ع</span>
          <div class="pos-qty-stepper">
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},-1)">−</button>
            <span style="min-width:24px;text-align:center;font-weight:700">${i.qty}</span>
            <button type="button" class="pos-qty-btn" onclick="PosWP.updateQty(${idx},1)">+</button>
          </div>
        </div>
        <div style="margin-top:6px;font-weight:700;color:var(--primary)">${fmt(t)} د.ع</div>
      </div>`;
    }).join("");

    if (mobileList) {
      mobileList.innerHTML = items.length
        ? mobileHtml
        : '<div class="pos-empty"><i class="fas fa-shopping-basket"></i><p>لم يتم إضافة منتجات بعد</p></div>';
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
    if (activeCategory === "low") list = list.filter((p) => (p.quantity || 0) > 0 && (p.quantity || 0) <= 5);
    else if (activeCategory === "out") list = list.filter((p) => (p.quantity || 0) <= 0);
    else if (activeCategory === "available") list = list.filter((p) => (p.quantity || 0) > 5);
    return list;
  }

  function renderProductGrid() {
    const grid = $("productGrid");
    const empty = $("productEmpty");
    if (!grid) return;
    const list = filteredProducts();
    if (!list.length) {
      grid.innerHTML = "";
      if (empty) empty.style.display = "block";
      return;
    }
    if (empty) empty.style.display = "none";

    grid.innerHTML = list.map((p) => {
      const qty = p.quantity || 0;
      const badge = stockBadge(qty);
      const img = p.image_url
        ? `<img src="${p.image_url}" alt="" loading="lazy">`
        : '<i class="fas fa-box"></i>';
      const sku = p.sku || p.barcode || ("#" + p.id);
      const nameEsc = (p.name || "").replace(/'/g, "\\'");
      return `<article class="pos-product-card" data-id="${p.id}">
        <div class="pos-product-img">${img}</div>
        <div class="pos-product-name">${p.name}</div>
        <div class="pos-product-sku">${sku}</div>
        <div class="pos-product-row">
          <span class="pos-product-price">${fmt(p.sale_price)} د.ع</span>
          <span class="pos-stock-badge ${badge.cls}">${badge.text}</span>
        </div>
        <div class="pos-product-row" style="font-size:12px;color:var(--text-muted)">المخزون: ${qty}</div>
        <button type="button" class="pos-btn-add" ${qty <= 0 ? "disabled" : ""}
          onclick="PosWP.addItem(${p.id},'${nameEsc}',${p.sale_price || 0},${qty})">إضافة</button>
      </article>`;
    }).join("");
  }

  function addItem(id, name, price, stock) {
    const idNum = typeof id === "string" ? parseInt(id, 10) : id;
    const stockNum = typeof stock === "string" ? parseInt(stock, 10) : (stock || 0);
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
      items.push({ product_id: idNum, name: name || "", price: Number(price) || 0, qty: 1, stock: stockNum });
      toast("تم إضافة " + (name || "منتج") + " للسلة");
    }
    const sp = $("searchProduct");
    if (sp) sp.value = "";
    const pr = $("productResults");
    if (pr) pr.classList.remove("open");
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
    if (input) { input.value = item.price; }
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
    if (c && c.blacklisted) {
      toast(c.blacklist_message || "هذا الزبون في القائمة السوداء");
      return;
    }
    selectedCustomerId = c.id;
    const el = $("selectedCustomer");
    if (el) el.textContent = c.name + " — " + (c.phone || "");
    $("customerResults")?.classList.remove("open");
    const sc = $("searchCustomer");
    if (sc) sc.value = "";
  }

  function pickCustomerFromSearch(enc) {
    try {
      selectCustomer(JSON.parse(decodeURIComponent(enc)));
    } catch (e) { /* ignore */ }
  }

  function openCustomerModal() {
    $("customerModal")?.classList.add("show");
    $("name")?.focus();
  }

  function closeCustomerModal() {
    $("customerModal")?.classList.remove("show");
    closeOCR();
  }

  function saveCustomer() {
    const name = ($("name")?.value || "").trim();
    const phone = ($("phone")?.value || "").trim();
    if (!name) { toast("يرجى إدخال اسم الزبون"); return; }
    if (!phone) { toast("يرجى إدخال رقم الهاتف"); return; }

    fetch("/pos/add-customer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        phone,
        phone2: ($("phone2")?.value || "").trim(),
        city: $("city")?.value || "",
        address: ($("address")?.value || "").trim(),
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.blacklisted || (d.status === "fail" && d.msg)) {
          toast(d.msg || "لا يُسمح بهذا الرقم");
          return;
        }
        if (d.status === "success" && d.id) {
          selectedCustomerId = d.id;
          const el = $("selectedCustomer");
          if (el) el.textContent = d.name + " — " + d.phone;
          toast("تم حفظ الزبون بنجاح");
          closeCustomerModal();
        } else {
          toast(d.msg || "فشل حفظ الزبون");
        }
      })
      .catch(() => toast("حدث خطأ في الاتصال"));
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

    const notes = ($("orderNotesInput")?.value || "").trim();
    isSubmitting = true;
    updateStats();
    const btn = $("btnExecute");
    if (btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> جاري التنفيذ...';

    fetch("/pos/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_id: selectedCustomerId,
        items: items,
        note: notes || null,
        scheduled_date: null,
        page_id: pageId || null,
        page_name: pageName || null,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        isSubmitting = false;
        if (btn) btn.innerHTML = '<i class="fas fa-print"></i> تنفيذ و طباعة';
        if (d.error) {
          toast(d.error);
          updateStats();
          return;
        }
        toast("تم تنفيذ البيع وإنشاء الفاتورة");
        lastOrderLabel = "INV-" + d.invoice_id;
        closeOrderNotesModal();
        printServerInvoice(d.invoice_id);
        items = [];
        selectedCustomerId = null;
        const el = $("selectedCustomer");
        if (el) el.textContent = "زبون سريع — اختر أو أضف زبون";
        if (pageSelect) pageSelect.value = "";
        renderItems();
        fetchLastOrders();
      })
      .catch((err) => {
        isSubmitting = false;
        if (btn) btn.innerHTML = '<i class="fas fa-print"></i> تنفيذ و طباعة';
        toast("حدث خطأ: " + err.message);
        updateStats();
      });
  }

  function printServerInvoice(invoiceId) {
    const url = "/orders/invoice/" + encodeURIComponent(invoiceId);
    const printWin = window.open(url, "_blank");
    if (!printWin) {
      toast("اسمح بالنوافذ المنبثقة لطباعة الفاتورة");
      return;
    }
    const tryPrint = () => {
      try { printWin.focus(); printWin.print(); } catch (e) { /* */ }
    };
    printWin.addEventListener("load", function onLoad() {
      printWin.removeEventListener("load", onLoad);
      setTimeout(tryPrint, 500);
    });
    setTimeout(tryPrint, 2500);
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
        items: items,
        note: notes || null,
        scheduled_date: scheduleDate,
        page_id: pageSelect?.value && pageSelect.value !== "no_page" ? pageSelect.value : null,
      }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.error) { toast(d.error); return; }
        toast("تم تأجيل الطلب — رقم " + d.invoice_id);
        closeScheduleModal();
        items = [];
        selectedCustomerId = null;
        $("selectedCustomer").textContent = "زبون سريع — اختر أو أضف زبون";
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

  function openMobileCart() {
    $("mobileSheetBackdrop")?.classList.add("open");
    $("mobileCartSheet")?.classList.add("open");
    document.body.style.overflow = "hidden";
  }

  function closeMobileCart() {
    $("mobileSheetBackdrop")?.classList.remove("open");
    $("mobileCartSheet")?.classList.remove("open");
    document.body.style.overflow = "";
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

  function fetchLastOrders() {
    fetch("/pos/last-orders")
      .then((r) => r.json())
      .then((orders) => {
        if (orders && orders.length) {
          const o = orders[0];
          lastOrderLabel = "INV-" + o.id + " / " + (o.date || "").split(" ")[1] || o.date;
          updateStats();
        }
      })
      .catch(() => { /* */ });
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
          $("selectedCustomer").textContent = d.name + " — " + d.phone;
          closeOCR();
          toast("تم حفظ بيانات OCR");
        }
      });
  }

  function clearProductSearch() {
    const sp = $("searchProduct");
    if (sp) sp.value = "";
    productSearchQuery = "";
    activeCategory = "all";
    document.querySelectorAll(".pos-pill").forEach((b, i) => b.classList.toggle("active", i === 0));
    const pr = $("productResults");
    if (pr) pr.classList.remove("open");
    renderProductGrid();
  }
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  function initSearch() {
    const searchCustomer = $("searchCustomer");
    const customerResults = $("customerResults");
    if (searchCustomer) {
      searchCustomer.addEventListener("input", debounce(() => {
        const val = searchCustomer.value.trim();
        if (val.length < 2) {
          customerResults?.classList.remove("open");
          return;
        }
        fetch("/pos/search-customer?q=" + encodeURIComponent(val))
          .then((r) => r.json())
          .then((d) => {
            if (!customerResults) return;
            customerResults.innerHTML = d.map((c) => {
              const enc = encodeURIComponent(JSON.stringify(c));
              const bl = c.blacklisted ? ' class="pos-cust-bl"' : "";
              return `<div${bl} onclick="PosWP.pickCustomerFromSearch('${enc}')">${c.name} — ${c.phone}</div>`;
            }).join("");
            customerResults.classList.add("open");
          });
      }, 250));
    }

    const searchProduct = $("searchProduct");
    const productResults = $("productResults");
    const runProductSearch = (val) => {
      if (!val) {
        productSearchQuery = "";
        renderProductGrid();
        productResults?.classList.remove("open");
        return;
      }
      fetch("/pos/search-product?q=" + encodeURIComponent(val))
        .then((r) => r.json())
        .then((d) => {
          if (d.length === 1 && d[0].is_barcode) {
            addItem(d[0].id, d[0].name, d[0].price, d[0].quantity);
            if (searchProduct) searchProduct.value = "";
            return;
          }
          productSearchQuery = val.toLowerCase();
          renderProductGrid();
          if (d.length > 0 && productResults) {
            productResults.innerHTML = d.map((p) => {
              const name = (p.name || "").replace(/"/g, "&quot;");
              return `<div class="pos-product-item" onclick="PosWP.addItem(${p.id},'${name.replace(/'/g, "\\'")}',${p.price},${p.quantity || 0})">${p.name} — ${fmt(p.price)} <small>(${p.quantity || 0})</small></div>`;
            }).join("");
            productResults.classList.add("open");
          } else {
            if (productResults) {
              productResults.innerHTML = '<div style="padding:12px;color:var(--text-muted)">لا توجد نتائج</div>';
              productResults.classList.add("open");
            }
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

  function initPills() {
    document.querySelectorAll(".pos-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".pos-pill").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        activeCategory = btn.getAttribute("data-cat") || "all";
        renderProductGrid();
      });
    });
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
        closeMobileCart();
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
        if (window.innerWidth < 768) openMobileCart();
      }
      if (e.ctrlKey && e.key === "Enter" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
        openOrderNotesModal();
      }
    });
  }

  function init() {
    initSearch();
    initPills();
    initDiscountShipping();
    initKeyboard();
    fetchLastOrders();

    $("cameraInput")?.addEventListener("change", (e) => {
      if (e.target.files?.[0]) sendToOCR(e.target.files[0]);
    });
    $("imageInput")?.addEventListener("change", (e) => {
      if (e.target.files?.[0]) sendToOCR(e.target.files[0]);
    });

    if (initialOrderData) {
      const el = $("selectedCustomer");
      if (el && initialOrderData.customer_name) {
        el.textContent = initialOrderData.customer_name;
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
    openMobileCart,
    closeMobileCart,
    openInventoryModal,
    closeInventoryModal,
    filterInventory,
    openCamera,
    uploadImage,
    confirmOCR,
    closeOCR,
    clearProductSearch,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
