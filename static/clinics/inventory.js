(() => {
  const initialQuery = new URLSearchParams(window.location.search).get("q") || "";
  const ui = { q: initialQuery, category: "", status: "", page: 1, perPage: 25, timer: null };
  let globalShortcutBound = false;
  let floatingDismiss = null;
  const statusLabels = { available: "متوفر", low: "منخفض", critical: "حرج", out: "نافد", expiring: "قريب الانتهاء", expired: "منتهي", inactive: "موقوف" };
  const movementLabels = { in: "إدخال", out: "صرف", adjust: "تسوية", procedure: "استهلاك إجراء" };
  const receiptLabels = { pending: "بانتظار الاستلام", partial: "مستلمة جزئياً", complete: "مستلمة بالكامل" };
  const units = ["حبة", "علبة", "كرتون", "قارورة", "أمبولة", "سرنجة", "كيس", "رول", "مل", "لتر", "غرام", "كيلوغرام", "قطعة"];
  const categories = ["الأدوية", "المستهلكات", "التعقيم", "الأسنان", "المختبر", "المعدات", "الطوارئ", "أخرى"];

  function qty(value) {
    return Number(value || 0).toLocaleString("ar-IQ", { maximumFractionDigits: 3 });
  }

  function bindGlobalSearch(onSearch) {
    const input = document.getElementById("cxiGlobalSearch");
    if (!input) return;
    input.value = ui.q;
    input.oninput = event => {
      clearTimeout(ui.timer);
      ui.timer = setTimeout(() => onSearch(event.target.value), 350);
    };
    if (!globalShortcutBound) {
      document.addEventListener("keydown", event => {
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
          event.preventDefault();
          document.getElementById("cxiGlobalSearch")?.focus();
        }
      });
      globalShortcutBound = true;
    }
  }

  function statusBadge(status) {
    return `<span class="cxi-status cxi-status--${status || "available"}">${statusLabels[status] || status}</span>`;
  }

  function closeFloatingMenu() {
    document.querySelector(".cxi-floating-menu")?.remove();
    if (floatingDismiss) document.removeEventListener("click", floatingDismiss);
    floatingDismiss = null;
  }

  function openFloatingMenu(trigger, item, ctx) {
    closeFloatingMenu();
    const menu = document.createElement("div");
    menu.className = "cxi-floating-menu";
    menu.innerHTML = `<a href="/clinics/inventory/items/${item.id}"><i class="fa fa-eye"></i><span>عرض التفاصيل</span></a>
      <button type="button" data-action="in"><i class="fa fa-arrow-down"></i><span>إدخال مخزون</span></button>
      <button type="button" data-action="out"><i class="fa fa-arrow-up"></i><span>صرف مخزون</span></button>
      <button type="button" data-action="edit"><i class="fa fa-pen"></i><span>تعديل الصنف</span></button>`;
    document.body.appendChild(menu);
    const rect = trigger.getBoundingClientRect();
    const menuWidth = 190;
    const menuHeight = menu.offsetHeight || 170;
    const top = window.innerHeight - rect.bottom >= menuHeight + 12
      ? rect.bottom + 6
      : Math.max(8, rect.top - menuHeight - 6);
    const left = Math.max(8, Math.min(window.innerWidth - menuWidth - 8, rect.right - menuWidth));
    menu.style.top = `${top}px`;
    menu.style.left = `${left}px`;
    menu.querySelector('[data-action="in"]').onclick = () => { closeFloatingMenu(); openStockModal(item, "in", ctx); };
    menu.querySelector('[data-action="out"]').onclick = () => { closeFloatingMenu(); openStockModal(item, "out", ctx); };
    menu.querySelector('[data-action="edit"]').onclick = () => { closeFloatingMenu(); openItemModal(item, ctx); };
    window.setTimeout(() => {
      floatingDismiss = event => {
        if (!menu.contains(event.target) && !trigger.contains(event.target)) {
          closeFloatingMenu();
        }
      };
      document.addEventListener("click", floatingDismiss);
    }, 0);
  }

  function subnav(active = "inventory") {
    return `<nav class="cxi-subnav" aria-label="صفحات المخزون">
      <a class="${active === "inventory" ? "active" : ""}" href="/clinics/inventory">الأصناف</a>
      <a class="${active === "movements" ? "active" : ""}" href="/clinics/inventory/movements">الحركات</a>
      <a class="${["batches", "expiry"].includes(active) ? "active" : ""}" href="/clinics/inventory/batches">الدفعات والصلاحية</a>
      <a href="/clinics/purchases">المشتريات</a>
      <a href="/clinics/suppliers">الموردون</a>
    </nav>`;
  }

  function header(title, description, actions = "", active = "inventory") {
    return `<section class="cxi-header">
      <div><div class="cxi-breadcrumb">الرئيسية <i class="fa fa-angle-left"></i> المخزون والمشتريات <i class="fa fa-angle-left"></i> ${title}</div><h1>${title}</h1><p>${description}</p></div>
      <div class="cxi-header__actions">${actions}</div>
    </section>${subnav(active)}`;
  }

  function itemForm(esc, suppliers, item = {}) {
    const selected = (value, current) => value === current ? "selected" : "";
    const checked = (value) => value ? "checked" : "";
    return `<div class="cxi-form">
      <section><h4>المعلومات الأساسية</h4><div class="cxi-form-grid">
        <label><span>اسم الصنف *</span><input class="cx-input" id="cxiName" value="${esc(item.name || "")}"></label>
        <label><span>الاسم العلمي</span><input class="cx-input" id="cxiScientific" value="${esc(item.scientific_name || "")}"></label>
        <label><span>التصنيف *</span><select class="cx-select" id="cxiCategory"><option value="">اختر التصنيف</option>${categories.map(v => `<option ${selected(v, item.category)}>${v}</option>`).join("")}</select></label>
        <label><span>الوحدة الأساسية *</span><select class="cx-select" id="cxiUnit">${units.map(v => `<option ${selected(v, item.unit)}>${v}</option>`).join("")}</select></label>
        <label><span>SKU</span><input class="cx-input" id="cxiSku" value="${esc(item.sku || "")}"></label>
        <label><span>Barcode</span><input class="cx-input" id="cxiBarcode" value="${esc(item.barcode || "")}"></label>
        <label class="cxi-span-2"><span>الوصف</span><textarea class="cx-textarea" id="cxiDescription">${esc(item.description || "")}</textarea></label>
      </div></section>
      <section><h4>إعدادات المخزون</h4><div class="cxi-form-grid cxi-form-grid--4">
        ${item.id ? "" : `<label><span>الرصيد الافتتاحي</span><input class="cx-input" id="cxiOpening" type="number" min="0" step="0.001" value="0"></label>`}
        <label><span>الحد الأدنى</span><input class="cx-input" id="cxiMin" type="number" min="0" step="0.001" value="${item.minimum_stock || 0}"></label>
        <label><span>الحد الأعلى</span><input class="cx-input" id="cxiMax" type="number" min="0" step="0.001" value="${item.maximum_stock || 0}"></label>
        <label><span>نقطة إعادة الطلب</span><input class="cx-input" id="cxiReorder" type="number" min="0" step="0.001" value="${item.reorder_point || 0}"></label>
        <label><span>كمية الطلب المقترحة</span><input class="cx-input" id="cxiSuggested" type="number" min="0" step="0.001" value="${item.suggested_reorder_qty || 0}"></label>
        ${item.id ? "" : `<label><span>تكلفة الافتتاح</span><input class="cx-input" id="cxiCost" type="number" min="0" value="0"></label>`}
        <label><span>المورد الافتراضي</span><select class="cx-select" id="cxiSupplier"><option value="">بدون</option>${suppliers.map(s => `<option value="${s.id}" ${String(s.id) === String(item.default_supplier_id || "") ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
      </div></section>
      <section><h4>التتبع والسلامة</h4><div class="cxi-check-grid">
        <label><input type="checkbox" id="cxiBatch" ${checked(item.batch_tracking)}> تتبع رقم الدفعة</label>
        <label><input type="checkbox" id="cxiExpiry" ${checked(item.expiry_tracking)}> تتبع الصلاحية</label>
        <label><input type="checkbox" id="cxiSerial" ${checked(item.serial_tracking)}> تتبع Serial Number</label>
        <label><input type="checkbox" id="cxiCooling" ${checked(item.requires_cooling)}> يتطلب تبريداً</label>
        <label><input type="checkbox" id="cxiSensitive" ${checked(item.sensitive_item)}> مادة حساسة</label>
        <label><input type="checkbox" id="cxiPrevent" ${checked(item.prevent_expired_usage !== false)}> منع الاستخدام بعد الانتهاء</label>
      </div></section>
    </div>`;
  }

  function readItemForm() {
    const value = id => document.getElementById(id)?.value || "";
    const on = id => !!document.getElementById(id)?.checked;
    return {
      name: value("cxiName"), scientific_name: value("cxiScientific"), category: value("cxiCategory"), unit: value("cxiUnit"),
      sku: value("cxiSku"), barcode: value("cxiBarcode"), description: value("cxiDescription"),
      current_stock: value("cxiOpening"), opening_cost: value("cxiCost"), minimum_stock: value("cxiMin"),
      maximum_stock: value("cxiMax"), reorder_point: value("cxiReorder"), suggested_reorder_qty: value("cxiSuggested"),
      default_supplier_id: Number(value("cxiSupplier")) || null, batch_tracking: on("cxiBatch"), expiry_tracking: on("cxiExpiry"),
      serial_tracking: on("cxiSerial"), requires_cooling: on("cxiCooling"), sensitive_item: on("cxiSensitive"), prevent_expired_usage: on("cxiPrevent"),
    };
  }

  function stockForm(item, mode, suppliers, esc) {
    const incoming = mode === "in";
    return `<div class="cxi-form cxi-stock-form">
      <div class="cxi-balance"><span>${esc(item.name)}</span><strong>${qty(item.available_stock)} ${esc(item.unit)}</strong><small>الرصيد المتاح حالياً</small></div>
      <div class="cxi-form-grid">
        <label><span>الكمية *</span><input class="cx-input" id="cxiQty" type="number" min="0.001" step="0.001" value="1"></label>
        ${incoming ? `<label><span>نوع الإدخال</span><select class="cx-select" id="cxiReason"><option value="manual">إدخال يدوي</option><option value="opening">رصيد افتتاحي</option><option value="return">مرتجع</option><option value="count">تصحيح جرد</option></select></label>` : `<label><span>سبب الصرف</span><select class="cx-select" id="cxiReason"><option value="internal_use">استخدام داخلي</option><option value="procedure">إجراء طبي</option><option value="damage">تلف</option><option value="sample">عينة</option><option value="adjustment">تصحيح</option><option value="other">أخرى</option></select></label>`}
        ${incoming && item.batch_tracking ? `<label><span>رقم الدفعة *</span><input class="cx-input" id="cxiBatchNo"></label>` : ""}
        ${incoming && item.expiry_tracking ? `<label><span>تاريخ الانتهاء *</span><input class="cx-input" id="cxiExpiryDate" type="date"></label>` : ""}
        ${incoming ? `<label><span>تكلفة الوحدة</span><input class="cx-input" id="cxiUnitCost" type="number" min="0" value="${item.last_purchase_cost || item.average_cost || 0}"></label>
        <label><span>المورد</span><select class="cx-select" id="cxiStockSupplier"><option value="">بدون</option>${suppliers.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></label>` : ""}
        <label class="cxi-span-2"><span>ملاحظات</span><textarea class="cx-textarea" id="cxiNotes"></textarea></label>
      </div><div class="cxi-preview"><span>قبل العملية <b>${qty(item.current_stock)}</b></span><span>${incoming ? "الكمية الداخلة" : "الكمية المصروفة"} <b id="cxiDelta">${incoming ? "+" : "-"}1</b></span><span>الرصيد المتوقع <b id="cxiExpected">${qty(Number(item.current_stock) + (incoming ? 1 : -1))}</b></span></div>
    </div>`;
  }

  function bindStockPreview(item, incoming) {
    const input = document.getElementById("cxiQty");
    input?.addEventListener("input", () => {
      const amount = Number(input.value || 0);
      document.getElementById("cxiDelta").textContent = `${incoming ? "+" : "-"}${qty(amount)}`;
      document.getElementById("cxiExpected").textContent = qty(Number(item.current_stock) + (incoming ? amount : -amount));
    });
  }

  async function openItemModal(item, ctx) {
    const suppliers = await ctx.api("/clinics/api/suppliers");
    ctx.openModal(item ? "تعديل الصنف" : "إضافة صنف جديد", itemForm(ctx.esc, suppliers, item || {}), async () => {
      await ctx.api(item ? `/clinics/api/inventory/${item.id}` : "/clinics/api/inventory", { method: item ? "PUT" : "POST", body: JSON.stringify(readItemForm()) });
    }, { successMessage: item ? "تم تحديث الصنف" : "تم إنشاء الصنف" });
  }

  async function openStockModal(item, mode, ctx) {
    const suppliers = mode === "in" ? await ctx.api("/clinics/api/suppliers") : [];
    ctx.openModal(mode === "in" ? "إدخال مخزون" : "صرف مخزون", stockForm(item, mode, suppliers, ctx.esc), async () => {
      const value = id => document.getElementById(id)?.value || "";
      const payload = { quantity: value("cxiQty"), reason: value("cxiReason"), notes: value("cxiNotes") };
      if (mode === "in") Object.assign(payload, { batch_number: value("cxiBatchNo"), expiry_date: value("cxiExpiryDate"), unit_cost: value("cxiUnitCost"), supplier_id: Number(value("cxiStockSupplier")) || null, reference_type: value("cxiReason") });
      await ctx.api(`/clinics/api/inventory/${item.id}/stock-${mode}`, { method: "POST", body: JSON.stringify(payload) });
    }, { successMessage: mode === "in" ? "تم إدخال المخزون وتسجيل الحركة" : "تم صرف المخزون وتسجيل الحركة" });
    bindStockPreview(item, mode === "in");
  }

  async function renderMain(root, ctx) {
    const query = new URLSearchParams({ center: "1", q: ui.q, category: ui.category, status: ui.status, page: ui.page, per_page: ui.perPage });
    const data = await ctx.api(`/clinics/api/inventory?${query}`);
    const k = data.kpis;
    root.innerHTML = `<div class="cxi-page">
      ${header("مخزون العيادة", "إدارة المواد الطبية والمستهلكات والدفعات وتواريخ الصلاحية وحركة المخزون.", `<button class="cx-btn" id="cxiIssue"><i class="fa fa-arrow-up-from-bracket"></i> صرف مخزون</button><button class="cx-btn" id="cxiReceive"><i class="fa fa-arrow-down"></i> إدخال مخزون</button><button class="cx-btn cx-btn--primary" id="cxiAdd"><i class="fa fa-plus"></i> صنف جديد</button>`)}
      <div class="cxi-kpis">
        ${[["calendar-xmark","منتهي الصلاحية",k.expired,"محظور الاستخدام","expired"],["clock","ينتهي خلال 30 يوم",k.expiring_soon,"دفعات قريبة","expiring"],["briefcase-medical","نفد المخزون",k.out_of_stock,"يحتاج إعادة طلب","out"],["chart-line","منخفض المخزون",k.low_stock,"يحتاج إعادة طلب","low"],["circle-dollar-to-slot","قيمة المخزون",ctx.money(k.inventory_value),"حسب متوسط التكلفة","value"],["boxes-stacked","إجمالي الأصناف",k.total_items,"صنف نشط",""]].map(x => `<button class="cxi-kpi cxi-kpi--${x[4] || "total"}" data-kpi="${x[4] === "value" ? "" : x[4]}"><i class="fa fa-${x[0]}"></i><span>${x[1]}</span><strong>${x[2]}</strong><small>${x[3]}</small></button>`).join("")}
      </div>
      ${(k.expired || k.expiring_soon) ? `<div class="cxi-alert"><i class="fa fa-triangle-exclamation"></i><span>توجد <b>${k.expired}</b> دفعات منتهية و<b>${k.expiring_soon}</b> دفعات ستنتهي خلال 30 يوماً.</span><a href="/clinics/inventory/batches">عرض الدفعات</a></div>` : ""}
      ${(k.low_stock || k.out_of_stock) ? `<div class="cxi-alert"><i class="fa fa-cart-shopping"></i><span><b>${k.low_stock}</b> أصناف منخفضة و<b>${k.out_of_stock}</b> نافدة — حدّد الأصناف وأنشئ طلب شراء.</span><button type="button" class="cx-btn cx-btn--sm" id="cxiReorder">طلب شراء (الكل)</button><button type="button" class="cx-btn cx-btn--sm cx-btn--primary" id="cxiReorderSel">طلب للمحدد</button></div>` : ""}
      <section class="cxi-panel">
        <div class="cxi-filters"><label class="cxi-search"><i class="fa fa-magnifying-glass"></i><input id="cxiSearch" value="${ctx.esc(ui.q)}" placeholder="بحث باسم الصنف / الاسم العلمي / SKU / Barcode"></label>
          <select class="cx-select" id="cxiCategoryFilter"><option value="">كل التصنيفات</option>${data.categories.map(v => `<option ${v === ui.category ? "selected" : ""}>${ctx.esc(v)}</option>`).join("")}</select>
          <select class="cx-select" id="cxiStatusFilter"><option value="">كل الحالات</option>${Object.entries(statusLabels).slice(0,5).map(([v,l]) => `<option value="${v}" ${v === ui.status ? "selected" : ""}>${l}</option>`).join("")}</select>
          <button class="cx-btn cx-btn--ghost" id="cxiRefresh" title="تحديث"><i class="fa fa-rotate"></i></button>
        </div>
        <div class="cxi-quick">${[["","الكل",k.total_items],["low","منخفض",k.low_stock],["out","نافد",k.out_of_stock],["expiring","قريب الانتهاء",k.expiring_soon]].map(v => `<button class="${ui.status === v[0] ? "active" : ""}" data-quick="${v[0]}">${v[1]} <b>${v[2]}</b></button>`).join("")}</div>
        <div class="cx-table-wrap"><table class="cx-table cxi-table"><thead><tr><th><input type="checkbox" id="cxiSelectAll" title="تحديد الكل"></th><th>اسم الصنف</th><th>التصنيف</th><th>SKU</th><th>الوحدة</th><th>الرصيد</th><th>المتاح</th><th>الحد الأدنى</th><th>أقرب انتهاء</th><th>متوسط التكلفة</th><th>القيمة</th><th>الحالة</th><th></th></tr></thead><tbody>
          ${data.items.map(i => `<tr><td><input type="checkbox" class="cxi-pick" data-id="${i.id}" data-min="${i.minimum_stock}" data-stock="${i.current_stock}" ${["low","out"].includes(i.status) ? "checked" : ""}></td><td><a class="cxi-item-link" href="/clinics/inventory/items/${i.id}"><b>${ctx.esc(i.name)}</b><small>${ctx.esc(i.scientific_name || i.barcode)}</small></a></td><td>${ctx.esc(i.category || "—")}</td><td dir="ltr">${ctx.esc(i.sku || "—")}</td><td>${ctx.esc(i.unit)}</td><td><b>${qty(i.current_stock)}</b></td><td>${qty(i.available_stock)}</td><td>${qty(i.minimum_stock)}</td><td>${ctx.esc(i.nearest_expiry || "—")}</td><td class="cx-money">${ctx.money(i.average_cost)}</td><td class="cx-money">${ctx.money(i.inventory_value)}</td><td>${statusBadge(i.status)}</td><td><button type="button" class="cxi-menu-trigger" data-menu="${i.id}" title="الإجراءات" aria-label="إجراءات ${ctx.esc(i.name)}"><i class="fa fa-ellipsis"></i></button></td></tr>`).join("") || `<tr><td colspan="13"><div class="cx-empty"><i class="fa fa-box-open"></i><b>لا توجد أصناف مطابقة</b><span>جرّب تغيير البحث أو أضف أول صنف طبي.</span></div></td></tr>`}
        </tbody></table></div>
        <footer class="cxi-pagination"><span>${data.pagination.total ? `${(data.pagination.page-1)*data.pagination.per_page+1}-${Math.min(data.pagination.page*data.pagination.per_page,data.pagination.total)} من ${data.pagination.total}` : "0 نتيجة"}</span><div><button class="cx-btn cx-btn--sm" id="cxiPrev" ${data.pagination.page <= 1 ? "disabled" : ""}>السابق</button><button class="cx-btn cx-btn--sm" id="cxiNext" ${data.pagination.page >= data.pagination.pages ? "disabled" : ""}>التالي</button></div></footer>
      </section>
      <section class="cxi-panel cxi-recent"><div class="cxi-panel-title"><h2>آخر حركات المخزون</h2><a href="/clinics/inventory/movements">عرض الكل</a></div>${movementTable(data.recent_movements, ctx)}</section>
    </div>`;
    const byId = id => data.items.find(i => i.id === Number(id));
    document.getElementById("cxiAdd").onclick = () => openItemModal(null, ctx);
    const chooseItem = (mode) => {
      if (!data.items.length) return ctx.showNotice("أضف صنفاً أولاً");
      ctx.openModal(mode === "in" ? "اختر صنفاً للإدخال" : "اختر صنفاً للصرف", `<div class="cxi-form"><label><span>الصنف</span><select class="cx-select" id="cxiChoose">${data.items.map(i=>`<option value="${i.id}">${ctx.esc(i.name)} — ${qty(i.available_stock)} ${ctx.esc(i.unit)}</option>`).join("")}</select></label></div>`, async () => {
        const selected = byId(document.getElementById("cxiChoose").value);
        window.setTimeout(() => openStockModal(selected, mode, ctx), 0);
      }, { saveLabel: "متابعة", skipRender: true });
    };
    document.getElementById("cxiReceive").onclick = () => chooseItem("in");
    document.getElementById("cxiIssue").onclick = () => chooseItem("out");
    const openPurchaseRequest = async (prefill) => {
      if (window.ClinicsPurchases?.openPurchaseRequests) {
        await window.ClinicsPurchases.openPurchaseRequests(ctx, reload, prefill);
      } else location.href = "/clinics/purchases";
    };
    const selectedLines = () => [...document.querySelectorAll(".cxi-pick:checked")].map(el => ({
      item_id: Number(el.dataset.id),
      quantity: Math.max(1, Number(el.dataset.min || 0) - Number(el.dataset.stock || 0) + 1),
      reason: "مخزون منخفض",
    }));
    document.getElementById("cxiReorder")?.addEventListener("click", () => openPurchaseRequest(null));
    document.getElementById("cxiReorderSel")?.addEventListener("click", () => {
      const lines = selectedLines();
      if (!lines.length) return ctx.showNotice("حدّد صنفاً واحداً على الأقل");
      openPurchaseRequest(lines);
    });
    document.getElementById("cxiSelectAll")?.addEventListener("change", e => {
      document.querySelectorAll(".cxi-pick").forEach(cb => { cb.checked = e.target.checked; });
    });
    root.querySelectorAll("[data-in]").forEach(b => b.onclick = () => openStockModal(byId(b.dataset.in), "in", ctx));
    root.querySelectorAll("[data-out]").forEach(b => b.onclick = () => openStockModal(byId(b.dataset.out), "out", ctx));
    root.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => openItemModal(byId(b.dataset.edit), ctx));
    root.querySelectorAll("[data-menu]").forEach(b => b.onclick = event => {
      event.stopPropagation();
      openFloatingMenu(b, byId(b.dataset.menu), ctx);
    });
    const reload = async () => renderMain(root, ctx);
    document.getElementById("cxiSearch").oninput = e => { clearTimeout(ui.timer); ui.timer = setTimeout(() => { ui.q=e.target.value; ui.page=1; reload(); }, 350); };
    document.getElementById("cxiCategoryFilter").onchange = e => { ui.category=e.target.value; ui.page=1; reload(); };
    document.getElementById("cxiStatusFilter").onchange = e => { ui.status=e.target.value; ui.page=1; reload(); };
    document.getElementById("cxiRefresh").onclick = reload;
    root.querySelectorAll("[data-quick],[data-kpi]").forEach(b => b.onclick = () => { ui.status=b.dataset.quick ?? b.dataset.kpi; ui.page=1; reload(); });
    document.getElementById("cxiPrev").onclick = () => { ui.page--; reload(); };
    document.getElementById("cxiNext").onclick = () => { ui.page++; reload(); };
    bindGlobalSearch(value => { ui.q=value; ui.page=1; reload(); });
  }

  function movementTable(rows, ctx) {
    return `<div class="cx-table-wrap"><table class="cx-table cxi-table"><thead><tr><th>الحركة</th><th>الصنف</th><th>الكمية</th><th>الرصيد قبل</th><th>الرصيد بعد</th><th>المرجع</th><th>التاريخ</th></tr></thead><tbody>${rows.map(m => `<tr><td><span class="cxi-movement cxi-movement--${m.movement_type}">${movementLabels[m.movement_type] || ctx.esc(m.movement_type)}</span></td><td><a class="cxi-item-link" href="/clinics/inventory/items/${m.item_id}"><b>${ctx.esc(m.item_name)}</b></a></td><td><b>${m.movement_type === "out" ? "−" : "+"}${qty(m.quantity)}</b></td><td>${qty(m.stock_before)}</td><td>${qty(m.stock_after)}</td><td>${ctx.esc(m.reference_type || "—")}${m.reference_id ? ` #${m.reference_id}` : ""}</td><td>${ctx.esc(window.FinoraTime.dateTime((m.created_at || "")))}</td></tr>`).join("") || `<tr><td colspan="7"><div class="cx-empty">لا توجد حركات بعد</div></td></tr>`}</tbody></table></div>`;
  }

  async function renderMovements(root, ctx) {
    const rows = await ctx.api("/clinics/api/inventory/movements");
    root.innerHTML = `<div class="cxi-page">${header("حركة المخزون", "سجل غير قابل للحذف لكل مادة دخلت أو خرجت من العيادة.", `<a class="cx-btn cx-btn--primary" href="/clinics/inventory">إدارة الأصناف</a>`, "movements")}<section class="cxi-panel">${movementTable(rows, ctx)}</section></div>`;
  }

  async function renderBatches(root, ctx) {
    const rows = await ctx.api("/clinics/api/inventory/batches");
    root.innerHTML = `<div class="cxi-page">${header("الدفعات والصلاحية", "تتبّع الدفعات المتاحة والقيمة المعرضة للخطر وتطبيق FEFO عند الصرف.", `<a class="cx-btn cx-btn--primary" href="/clinics/inventory">إدخال مخزون</a>`, "batches")}<section class="cxi-panel"><div class="cx-table-wrap"><table class="cx-table cxi-table"><thead><tr><th>الصنف</th><th>رقم الدفعة</th><th>تاريخ الانتهاء</th><th>الكمية المستلمة</th><th>المتبقي</th><th>تكلفة الوحدة</th><th>القيمة المعرضة</th><th>الحالة</th></tr></thead><tbody>${rows.map(b => `<tr><td><a class="cxi-item-link" href="/clinics/inventory/items/${b.item_id}"><b>${ctx.esc(b.item_name)}</b></a></td><td dir="ltr">${ctx.esc(b.batch_number)}</td><td>${ctx.esc(b.expiry_date || "بدون تاريخ")}</td><td>${qty(b.quantity_received)}</td><td><b>${qty(b.quantity_available)}</b></td><td class="cx-money">${ctx.money(b.unit_cost)}</td><td class="cx-money">${ctx.money(b.quantity_available*b.unit_cost)}</td><td>${statusBadge(b.status)}</td></tr>`).join("") || `<tr><td colspan="8"><div class="cx-empty">لا توجد دفعات مسجلة</div></td></tr>`}</tbody></table></div></section></div>`;
  }

  async function renderDetail(root, ctx, itemId) {
    const [data, priceHistory] = await Promise.all([
      ctx.api(`/clinics/api/inventory/${itemId}`),
      ctx.api(`/clinics/api/purchases/price-history?item_id=${itemId}`).catch(() => []),
    ]);
    const i = data.item;
    let tab = "overview";
    const render = () => renderDetail(root, ctx, itemId);
    const tabBody = () => {
      if (tab === "batches") return data.batches.length ? `<div class="cxi-batch-cards">${data.batches.map(b=>`<article><div>${statusBadge(b.status)}<b>${ctx.esc(b.batch_number)}</b></div><strong>${qty(b.quantity_available)} ${ctx.esc(i.unit)}</strong><small>انتهاء: ${ctx.esc(b.expiry_date || "غير محدد")}</small></article>`).join("")}</div>` : `<div class="cx-empty">لا توجد دفعات لهذا الصنف</div>`;
      if (tab === "movements") return movementTable(data.movements, ctx);
      if (tab === "prices") return priceHistory.length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>التاريخ</th><th>المورد</th><th>الفاتورة</th><th>الكمية</th><th>سعر الوحدة</th><th>الإجمالي</th></tr></thead><tbody>${priceHistory.map(r => `<tr><td>${ctx.esc(r.purchase_date)}</td><td>${ctx.esc(r.supplier_name)}</td><td><a href="/clinics/purchases/${r.purchase_id}">${ctx.esc(r.purchase_number)}</a></td><td>${qty(r.quantity)}</td><td class="cx-money">${ctx.money(r.unit_cost)}</td><td class="cx-money">${ctx.money(r.line_total)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="cx-empty">لا سجل شراء لهذا الصنف</div>`;
      return `<div class="cxi-detail-grid"><section class="cxi-panel cxi-item-summary"><div class="cxi-item-summary__top"><div class="cxi-item-icon"><i class="fa fa-pills"></i></div><div><h2>${ctx.esc(i.name)}</h2><p>${ctx.esc(i.scientific_name || "لا يوجد اسم علمي")}</p>${statusBadge(i.status)}</div></div><dl><div><dt>الرصيد</dt><dd>${qty(i.current_stock)} ${ctx.esc(i.unit)}</dd></div><div><dt>المتاح للصرف</dt><dd>${qty(i.available_stock)}</dd></div><div><dt>متوسط التكلفة</dt><dd>${ctx.money(i.average_cost)}</dd></div><div><dt>قيمة المخزون</dt><dd>${ctx.money(i.inventory_value)}</dd></div><div><dt>الحد الأدنى</dt><dd>${qty(i.minimum_stock)}</dd></div><div><dt>أقرب انتهاء</dt><dd>${ctx.esc(i.nearest_expiry || "—")}</dd></div></dl></section>
      <section class="cxi-panel"><div class="cxi-panel-title"><h2>معلومات التتبع</h2></div><div class="cxi-flags"><span class="${i.batch_tracking ? "on":""}"><i class="fa fa-layer-group"></i> تتبع الدفعات</span><span class="${i.expiry_tracking ? "on":""}"><i class="fa fa-calendar-xmark"></i> تتبع الصلاحية</span><span class="${i.requires_cooling ? "on":""}"><i class="fa fa-snowflake"></i> تبريد</span><span class="${i.sensitive_item ? "on":""}"><i class="fa fa-shield-halved"></i> مادة حساسة</span></div><p class="cxi-description">${ctx.esc(i.description || "لا يوجد وصف لهذا الصنف.")}</p></section></div>`;
    };
    root.innerHTML = `<div class="cxi-page">${header(i.name, `${i.sku || "بدون SKU"} · ${i.category || "غير مصنف"}`, `<button class="cx-btn" id="cxiDetailReq">طلب شراء</button><button class="cx-btn" id="cxiDetailOut">صرف</button><button class="cx-btn" id="cxiDetailIn">إدخال</button><button class="cx-btn cx-btn--primary" id="cxiDetailEdit">تعديل</button>`)}
      <section class="cxi-panel"><nav class="cxp-tabs"><button class="${tab==="overview"?"active":""}" data-tab="overview">نظرة عامة</button><button class="${tab==="batches"?"active":""}" data-tab="batches">الدفعات</button><button class="${tab==="movements"?"active":""}" data-tab="movements">الحركة</button><button class="${tab==="prices"?"active":""}" data-tab="prices">سجل الشراء</button></nav><div class="cxp-tab-body">${tabBody()}</div></section></div>`;
    root.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { tab = b.dataset.tab; render(); });
    document.getElementById("cxiDetailIn").onclick = () => openStockModal(i,"in",ctx);
    document.getElementById("cxiDetailOut").onclick = () => openStockModal(i,"out",ctx);
    document.getElementById("cxiDetailEdit").onclick = () => openItemModal(i,ctx);
    document.getElementById("cxiDetailReq").onclick = async () => {
      if (window.ClinicsPurchases?.openPurchaseRequests) {
        await window.ClinicsPurchases.openPurchaseRequests(ctx, render, [{ item_id: i.id, quantity: Math.max(1, (i.minimum_stock || 0) - (i.current_stock || 0) + 1), reason: "مخزون منخفض" }]);
      } else location.href = "/clinics/purchases";
    };
  }

  async function renderInventory(state, root, ctx) {
    const shell = document.querySelector(".cx-shell");
    const view = shell?.dataset.inventoryView || "";
    const itemId = Number(shell?.dataset.inventoryItemId || 0);
    if (itemId) return renderDetail(root,ctx,itemId);
    if (view === "movements") return renderMovements(root,ctx);
    if (["batches","expiry"].includes(view)) return renderBatches(root,ctx);
    return renderMain(root,ctx);
  }

  async function renderSuppliers(state, root, ctx) {
    const rows = await ctx.api("/clinics/api/suppliers?active=0");
    root.innerHTML = `<div class="cxi-page">${header("الموردون", "إدارة موردي المواد الطبية وربطهم بالمشتريات وحساباتهم.", `<button class="cx-btn cx-btn--primary" id="cxiAddSupplier"><i class="fa fa-plus"></i> مورد جديد</button>`, "suppliers")}<section class="cxi-panel"><div class="cx-table-wrap"><table class="cx-table cxi-table"><thead><tr><th>المورد</th><th>الهاتف</th><th>جهة الاتصال</th><th>البريد</th><th>الحالة</th><th></th></tr></thead><tbody>${rows.map(s=>`<tr><td><b>${ctx.esc(s.name)}</b></td><td dir="ltr">${ctx.esc(s.phone||"—")}</td><td>${ctx.esc(s.contact_person||"—")}</td><td>${ctx.esc(s.email||"—")}</td><td>${s.active?statusBadge("available"):statusBadge("inactive")}</td><td><button class="cx-btn cx-btn--sm" data-statement="${s.id}">كشف الحساب</button></td></tr>`).join("")||`<tr><td colspan="6"><div class="cx-empty">لا يوجد موردون بعد</div></td></tr>`}</tbody></table></div></section></div>`;
    document.getElementById("cxiAddSupplier").onclick=()=>ctx.openModal("مورد جديد",`<div class="cxi-form"><div class="cxi-form-grid"><label><span>اسم المورد *</span><input class="cx-input" id="supName"></label><label><span>الهاتف</span><input class="cx-input" id="supPhone"></label><label><span>جهة الاتصال</span><input class="cx-input" id="supContact"></label><label><span>البريد الإلكتروني</span><input class="cx-input" id="supEmail" type="email"></label><label class="cxi-span-2"><span>العنوان</span><textarea class="cx-textarea" id="supAddress"></textarea></label></div></div>`,async()=>ctx.api("/clinics/api/suppliers",{method:"POST",body:JSON.stringify({name:document.getElementById("supName").value,phone:document.getElementById("supPhone").value,contact_person:document.getElementById("supContact").value,email:document.getElementById("supEmail").value,address:document.getElementById("supAddress").value})}));
    root.querySelectorAll("[data-statement]").forEach(b=>b.onclick=async()=>{const d=await ctx.api(`/clinics/api/suppliers/${b.dataset.statement}/statement`);ctx.openModal(`كشف حساب ${d.supplier.name}`,`<div class="cxi-statement"><div class="cxi-balance"><span>الرصيد المستحق</span><strong>${ctx.money(d.outstanding_balance)}</strong></div>${d.lines.map(l=>`<div><span>${ctx.esc(l.date||"")} · ${ctx.esc(l.reference)}</span><b>${ctx.money(l.balance)}</b></div>`).join("")||"لا توجد حركات"}<div style="margin-top:12px"><a class="cx-btn cx-btn--sm" href="/clinics/suppliers/${b.dataset.statement}/statement/print" target="_blank"><i class="fa fa-print"></i> طباعة</a></div></div>`,async()=>{},{saveLabel:"إغلاق"});});
    bindGlobalSearch(value => { window.location.href = `/clinics/inventory?q=${encodeURIComponent(value)}`; });
  }

  function purchaseLines(items, esc) {
    return `<div id="cxiPurchaseLines">${purchaseLine(items,esc,0)}</div><button type="button" class="cx-btn cx-btn--sm" id="cxiAddLine"><i class="fa fa-plus"></i> إضافة بند</button>`;
  }
  function purchaseLine(items,esc,index){return `<div class="cxi-purchase-line"><label><span>الصنف</span><select class="cx-select cxi-p-item">${items.map(i=>`<option value="${i.id}">${esc(i.name)}</option>`).join("")}</select></label><label><span>الكمية</span><input class="cx-input cxi-p-qty" type="number" min="0.001" step="0.001" value="1"></label><label><span>سعر الوحدة</span><input class="cx-input cxi-p-cost" type="number" min="0" value="0"></label><button type="button" class="cxi-remove-line" title="حذف البند"><i class="fa fa-xmark"></i></button></div>`;}

  function receiveForm(p, esc) {
    return `<div class="cxi-form"><div class="cxi-receipt-head"><span>${esc(p.purchase_number)}</span><b>${esc(p.supplier_name)}</b></div><div class="cxi-receive-lines">${p.items.map(line=>`<article data-receive-line="${line.id}"><header><div><b>${esc(line.item_name)}</b><small>المطلوب ${qty(line.quantity)} · مستلم سابقاً ${qty(line.received_quantity)} · المتبقي ${qty(line.remaining_quantity)}</small></div></header><div class="cxi-form-grid cxi-form-grid--4"><label><span>يستلم الآن</span><input class="cx-input cxi-r-qty" type="number" min="0" max="${line.remaining_quantity}" step="0.001" value="${line.remaining_quantity}"></label><label><span>رقم الدفعة</span><input class="cx-input cxi-r-batch" value="${esc(line.batch_number||"")}"></label><label><span>الصلاحية</span><input class="cx-input cxi-r-expiry" type="date" value="${esc(line.expiry_date||"")}"></label><label><span>تكلفة الوحدة</span><input class="cx-input cxi-r-cost" type="number" min="0" value="${line.unit_cost}"></label></div></article>`).join("")}</div><label><span>ملاحظات الاستلام</span><textarea class="cx-textarea" id="cxiReceiptNotes"></textarea></label></div>`;
  }

  async function renderPurchases(state, root, ctx) {
    const [rows,suppliers,items]=await Promise.all([ctx.api("/clinics/api/purchases"),ctx.api("/clinics/api/suppliers"),ctx.api("/clinics/api/inventory")]);
    root.innerHTML=`<div class="cxi-page">${header("المشتريات", "الفاتورة تثبت الالتزام المالي، والمخزون يتغير فقط عند استلام المواد.",`<button class="cx-btn cx-btn--primary" id="cxiAddPurchase"><i class="fa fa-plus"></i> فاتورة شراء</button>`,"purchases")}<section class="cxi-panel"><div class="cx-table-wrap"><table class="cx-table cxi-table"><thead><tr><th>رقم الفاتورة</th><th>المورد</th><th>التاريخ</th><th>البنود</th><th>الإجمالي</th><th>المتبقي المالي</th><th>الاستلام</th><th></th></tr></thead><tbody>${rows.map(p=>`<tr><td><b>${ctx.esc(p.purchase_number)}</b></td><td>${ctx.esc(p.supplier_name)}</td><td>${ctx.esc(p.purchase_date)}</td><td>${p.items.length}</td><td class="cx-money">${ctx.money(p.total)}</td><td class="cx-money">${ctx.money(p.balance)}</td><td><span class="cxi-receipt cxi-receipt--${p.receipt_status}">${receiptLabels[p.receipt_status]||p.receipt_status}</span></td><td>${p.receipt_status!=="complete"?`<button class="cx-btn cx-btn--sm cx-btn--primary" data-receive-purchase="${p.id}">استلام المواد</button>`:"—"}</td></tr>`).join("")||`<tr><td colspan="8"><div class="cx-empty">لا توجد مشتريات بعد</div></td></tr>`}</tbody></table></div></section></div>`;
    document.getElementById("cxiAddPurchase").onclick=()=>{ctx.openModal("فاتورة شراء",`<div class="cxi-form"><div class="cxi-form-grid"><label><span>المورد *</span><select class="cx-select" id="cxiPSupplier">${suppliers.map(s=>`<option value="${s.id}">${ctx.esc(s.name)}</option>`).join("")}</select></label><label><span>تاريخ الشراء</span><input class="cx-input" type="date" id="cxiPDate" value="${new Date().toISOString().slice(0,10)}"></label></div><section><h4>بنود الفاتورة</h4>${purchaseLines(items,ctx.esc)}</section></div>`,async()=>{const lines=[...document.querySelectorAll(".cxi-purchase-line")].map(el=>({item_id:Number(el.querySelector(".cxi-p-item").value),quantity:el.querySelector(".cxi-p-qty").value,unit_cost:el.querySelector(".cxi-p-cost").value}));await ctx.api("/clinics/api/purchases",{method:"POST",body:JSON.stringify({supplier_id:Number(document.getElementById("cxiPSupplier").value),purchase_date:document.getElementById("cxiPDate").value,items:lines})});},{successMessage:"تم إنشاء الفاتورة وهي بانتظار الاستلام"});document.getElementById("cxiAddLine").onclick=()=>document.getElementById("cxiPurchaseLines").insertAdjacentHTML("beforeend",purchaseLine(items,ctx.esc,Date.now()));document.getElementById("cxiPurchaseLines").onclick=e=>{const b=e.target.closest(".cxi-remove-line");if(b&&document.querySelectorAll(".cxi-purchase-line").length>1)b.closest(".cxi-purchase-line").remove();};};
    root.querySelectorAll("[data-receive-purchase]").forEach(b=>b.onclick=()=>{const p=rows.find(x=>x.id===Number(b.dataset.receivePurchase));ctx.openModal("استلام مواد الشراء",receiveForm(p,ctx.esc),async()=>{const receiptItems=[...document.querySelectorAll("[data-receive-line]")].map(el=>({purchase_item_id:Number(el.dataset.receiveLine),quantity:el.querySelector(".cxi-r-qty").value,batch_number:el.querySelector(".cxi-r-batch").value,expiry_date:el.querySelector(".cxi-r-expiry").value,unit_cost:el.querySelector(".cxi-r-cost").value})).filter(x=>Number(x.quantity)>0);await ctx.api(`/clinics/api/purchases/${p.id}/receive`,{method:"POST",body:JSON.stringify({items:receiptItems,notes:document.getElementById("cxiReceiptNotes").value})});},{saveLabel:"تأكيد الاستلام",successMessage:"تم الاستلام وإنشاء الدفعات وحركات المخزون"});});
    bindGlobalSearch(value => { window.location.href = `/clinics/inventory?q=${encodeURIComponent(value)}`; });
  }

  window.ClinicsInventory={renderInventory,renderSuppliers,renderPurchases};
})();
