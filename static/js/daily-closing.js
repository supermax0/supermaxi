(function () {
  "use strict";
  const configNode = document.getElementById("dcConfig");
  const config = configNode ? JSON.parse(configNode.textContent || "{}") : {};
  const base = config.sessionId ? `/reports/daily-closing/${config.sessionId}` : "/reports/daily-closing";
  const selectedProducts = new Set();
  let loadedProducts = [];

  function toast(message, type = "success") {
    if (typeof window.showToast === "function") return window.showToast(message, type);
    const node = document.createElement("div");
    node.className = `dc-toast ${type}`;
    node.textContent = message;
    Object.assign(node.style, { position: "fixed", left: "22px", bottom: "22px", zIndex: 12000, padding: "12px 16px", borderRadius: "10px", color: "#fff", background: type === "error" ? "#dc2626" : "#059669", boxShadow: "0 12px 35px #0003" });
    document.body.appendChild(node); setTimeout(() => node.remove(), 3200);
  }

  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", headers: { "Content-Type": "application/json", "Accept": "application/json", ...(options.headers || {}) }, ...options });
    const data = await response.json().catch(() => ({ success: false, error: "استجابة غير صالحة من الخادم" }));
    if (!response.ok || data.success === false) {
      const error = new Error(data.error || `تعذر إكمال العملية (${response.status})`);
      error.responseData = data;
      throw error;
    }
    return data;
  }

  function reload(message) { if (message) sessionStorage.setItem("dcToast", message); location.reload(); }
  const queuedToast = sessionStorage.getItem("dcToast"); if (queuedToast) { sessionStorage.removeItem("dcToast"); setTimeout(() => toast(queuedToast), 150); }

  function localTimes() {
    document.querySelectorAll(".js-local-time").forEach(node => {
      const raw = node.dataset.time; if (!raw) return;
      const value = new Date(raw.endsWith("Z") ? raw : `${raw}Z`);
      if (!Number.isNaN(value.getTime())) node.textContent = value.toLocaleString("ar-IQ", { dateStyle: "short", timeStyle: "short" });
    });
  }
  localTimes();
  document.querySelectorAll("[data-open]").forEach(button => button.addEventListener("click", () => {
    const modal = document.getElementById(button.dataset.open); if (modal) { modal.classList.add("open"); modal.setAttribute("aria-hidden", "false"); }
    if (button.dataset.open === "productModal") loadProducts();
  }));
  document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => closeModal(button.closest(".dc-modal"))));
  document.querySelectorAll(".dc-modal").forEach(modal => modal.addEventListener("click", event => { if (event.target === modal) closeModal(modal); }));
  function closeModal(modal) { if (modal) { modal.classList.remove("open"); modal.setAttribute("aria-hidden", "true"); } }

  document.querySelectorAll("[data-toggle]").forEach(button => button.addEventListener("click", () => document.getElementById(button.dataset.toggle)?.classList.toggle("open")));
  document.querySelectorAll("[data-table-search]").forEach(input => input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase(); document.querySelectorAll(`#${input.dataset.tableSearch} tbody tr`).forEach(row => row.hidden = q && !row.textContent.toLowerCase().includes(q));
  }));

  document.getElementById("saveDaily")?.addEventListener("click", async () => {
    const payload = { notes: document.getElementById("dailyNotes")?.value };
    if (config.permissions?.can_edit_actual_cash) payload.actual_closing_cash = document.getElementById("actualCash")?.value;
    try { await api(`${base}/save`, { method: "POST", body: JSON.stringify(payload) }); reload("تم حفظ التقرير الحالي وحساب فرق الصندوق"); }
    catch (error) { toast(error.message, "error"); }
  });
  document.getElementById("refreshDaily")?.addEventListener("click", async () => {
    try { await api(`${base}/refresh`); reload("تم تحديث البيانات من السجلات الأصلية"); } catch (error) { toast(error.message, "error"); }
  });
  document.getElementById("saveCashAdjustment")?.addEventListener("click", async () => {
    try {
      await api(`${base}/cash-adjustments`, { method: "POST", body: JSON.stringify({
        direction: document.getElementById("cashAdjustmentDirection").value,
        category: document.getElementById("cashAdjustmentCategory").value,
        amount: document.getElementById("cashAdjustmentAmount").value,
        reference: document.getElementById("cashAdjustmentReference").value,
        description: document.getElementById("cashAdjustmentDescription").value,
      }) });
      reload("تمت إضافة حركة الصندوق اليدوية إلى اليومية");
    } catch (error) { toast(error.message, "error"); }
  });

  document.querySelectorAll(".dc-count-input").forEach(input => input.addEventListener("change", async () => {
    if (input.value === "") return;
    input.disabled = true;
    try { await api(`${base}/inventory/items/${input.dataset.countId}`, { method: "PATCH", body: JSON.stringify({ actual_quantity: input.value }) }); reload("تم حفظ الجرد الفعلي"); }
    catch (error) { input.disabled = false; toast(error.message, "error"); }
  }));
  document.querySelectorAll("[data-remove-count]").forEach(button => button.addEventListener("click", async () => {
    try { await api(`${base}/inventory/items/${button.dataset.removeCount}`, { method: "DELETE" }); reload("تم حذف المادة من الجرد"); } catch (error) { toast(error.message, "error"); }
  }));

  let productTimer;
  document.getElementById("productSearch")?.addEventListener("input", event => { clearTimeout(productTimer); productTimer = setTimeout(() => loadProducts(event.target.value), 250); });
  document.getElementById("categoryFilter")?.addEventListener("change", renderProducts);
  document.getElementById("brandFilter")?.addEventListener("change", renderProducts);
  document.getElementById("availabilityFilter")?.addEventListener("change", renderProducts);
  async function loadProducts(q = "") {
    const picker = document.getElementById("productPicker"); if (!picker) return;
    picker.innerHTML = '<div class="dc-empty">جاري تحميل المواد...</div>';
    try {
      const result = await api(`/reports/daily-closing/products?branch_id=${encodeURIComponent(config.branchId || "")}&q=${encodeURIComponent(q)}`);
      loadedProducts = result.products || [];
      const categories = [...new Set(loadedProducts.map(row => row.category).filter(Boolean))].sort();
      const filter = document.getElementById("categoryFilter"); const current = filter.value;
      filter.innerHTML = '<option value="">كل التصنيفات</option>' + categories.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join(""); filter.value = current;
      const brands = [...new Set(loadedProducts.map(row => row.brand).filter(Boolean))].sort();
      const brandFilter = document.getElementById("brandFilter"); const currentBrand = brandFilter?.value || "";
      if (brandFilter) { brandFilter.innerHTML = '<option value="">كل الماركات</option>' + brands.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join(""); brandFilter.value = currentBrand; }
      renderProducts();
    } catch (error) { picker.innerHTML = `<div class="dc-empty">${escapeHtml(error.message)}</div>`; }
  }
  function escapeHtml(value) { const span = document.createElement("span"); span.textContent = String(value ?? ""); return span.innerHTML; }
  function renderProducts() {
    const picker = document.getElementById("productPicker"); if (!picker) return;
    const category = document.getElementById("categoryFilter")?.value || "";
    const brand = document.getElementById("brandFilter")?.value || "";
    const availability = document.getElementById("availabilityFilter")?.value || "";
    const rows = loadedProducts
      .filter(row => !category || row.category === category)
      .filter(row => !brand || row.brand === brand)
      .filter(row => !availability || (availability === "available" ? Number(row.available_quantity || 0) > 0 : Number(row.available_quantity || 0) <= 0))
      .sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "ar"));
    picker.innerHTML = rows.map(row => {
      const quantity = Number(row.available_quantity || 0);
      return `<label class="dc-product-option ${quantity <= 0 ? "out-of-stock" : ""}"><input type="checkbox" value="${row.id}" ${selectedProducts.has(row.id) ? "checked" : ""}><span class="dc-product-copy"><strong>${escapeHtml(row.name)}</strong><small>${escapeHtml(row.category)} · ${escapeHtml(row.brand)}${row.sku ? ` · ${escapeHtml(row.sku)}` : ""}</small></span><span class="dc-stock-qty"><small>الكمية الموجودة</small><strong>${quantity.toLocaleString("ar-IQ")}</strong></span></label>`;
    }).join("") || '<div class="dc-empty">لا توجد مواد مطابقة.</div>';
    picker.querySelectorAll('input[type="checkbox"]').forEach(box => box.addEventListener("change", () => { const id = Number(box.value); box.checked ? selectedProducts.add(id) : selectedProducts.delete(id); updateSelectedCount(); })); updateSelectedCount();
  }
  function updateSelectedCount() { const node = document.getElementById("selectedProductCount"); if (node) node.textContent = `${selectedProducts.size} مادة محددة`; }
  document.getElementById("selectAllProducts")?.addEventListener("click", () => { document.querySelectorAll('#productPicker input[type="checkbox"]').forEach(box => selectedProducts.add(Number(box.value))); renderProducts(); });
  document.getElementById("clearAllProducts")?.addEventListener("click", () => { selectedProducts.clear(); renderProducts(); });
  document.getElementById("addSelectedProducts")?.addEventListener("click", async () => {
    try {
      const endpoint = config.allBranches ? "/reports/daily-closing/shared-inventory/items" : `${base}/inventory/items`;
      await api(endpoint, { method: "POST", body: JSON.stringify({ product_ids: [...selectedProducts] }) });
      reload(config.allBranches ? "تم حفظ مواد الجرد لكل الفروع" : "تمت إضافة المواد إلى الجرد");
    } catch (error) { toast(error.message, "error"); }
  });
  document.getElementById("saveTemplate")?.addEventListener("click", async () => {
    const name = prompt("اسم قائمة الجرد المحفوظة:"); if (!name) return;
    try { await api(`${base}/templates`, { method: "POST", body: JSON.stringify({ name }) }); reload("تم حفظ قائمة الجرد"); } catch (error) { toast(error.message, "error"); }
  });
  document.getElementById("templateSelect")?.addEventListener("change", async event => {
    if (!event.target.value) return;
    try { await api(`${base}/templates/${event.target.value}/apply`, { method: "POST", body: "{}" }); reload("تم تحميل قائمة الجرد"); } catch (error) { toast(error.message, "error"); }
  });

  let stockDetailState = null;
  async function loadStockDetails(page = 1) {
    if (!stockDetailState) return;
    const body = document.getElementById("stockDetailBody");
    body.innerHTML = '<tr><td colspan="5" class="dc-empty">جاري تحميل المراجع...</td></tr>';
    try {
      const result = await api(`${base}/stock-details?product_id=${stockDetailState.productId}&category=${encodeURIComponent(stockDetailState.category)}&page=${page}&per_page=30`);
      stockDetailState.page = result.page; stockDetailState.pages = result.pages;
      body.innerHTML = result.rows.map(row => `<tr><td>${new Date(`${row.time}Z`).toLocaleString("ar-IQ")}</td><td>${escapeHtml(row.movement_type)}</td><td>${row.quantity}</td><td>${escapeHtml(row.reference_type)}</td><td>#${escapeHtml(row.reference_id)}</td></tr>`).join("") || '<tr><td colspan="5" class="dc-empty">لا توجد تفاصيل.</td></tr>';
      document.getElementById("stockDetailPageInfo").textContent = `${result.total} حركة · صفحة ${result.page} من ${result.pages}`;
      document.getElementById("stockDetailPrev").disabled = result.page <= 1;
      document.getElementById("stockDetailNext").disabled = result.page >= result.pages;
    } catch (error) { body.innerHTML = `<tr><td colspan="5" class="dc-empty">${escapeHtml(error.message)}</td></tr>`; }
  }
  document.querySelectorAll("[data-stock-detail]").forEach(button => button.addEventListener("click", () => {
    const [productId, category] = button.dataset.stockDetail.split(":");
    stockDetailState = { productId, category, page: 1, pages: 1 };
    document.getElementById("stockDetailTitle").textContent = `${button.closest("tr").children[0].textContent.trim()} — تفاصيل الحركات`;
    const modal = document.getElementById("stockDetailModal"); modal.classList.add("open"); modal.setAttribute("aria-hidden", "false");
    loadStockDetails(1);
  }));
  document.getElementById("stockDetailPrev")?.addEventListener("click", () => loadStockDetails(Math.max(1, stockDetailState.page - 1)));
  document.getElementById("stockDetailNext")?.addEventListener("click", () => loadStockDetails(Math.min(stockDetailState.pages, stockDetailState.page + 1)));

  const defaultSections = ["sales", "cash", "expenses", "stock_out", "stock_in", "inventory", "audit", "notes", "signatures"];
  document.getElementById("printSelectAll")?.addEventListener("click", () => document.querySelectorAll('[name="printSection"]').forEach(box => { box.checked = true; }));
  document.getElementById("printDefaults")?.addEventListener("click", () => document.querySelectorAll('[name="printSection"]').forEach(box => { box.checked = defaultSections.includes(box.value); }));
  document.querySelectorAll("[data-print-action]").forEach(button => button.addEventListener("click", () => {
    const params = new URLSearchParams(); params.set("mode", document.querySelector('[name="printMode"]:checked')?.value || "detailed");
    document.querySelectorAll('[name="printSection"]:checked').forEach(box => params.append("section", box.value));
    if (button.dataset.printAction !== "preview") params.set("auto_print", "1");
    if (button.dataset.printAction === "pdf") params.set("download", "1");
    window.open(`${base}/print?${params.toString()}`, "_blank", "noopener");
  }));
})();
