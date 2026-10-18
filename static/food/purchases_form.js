(() => {
  "use strict";
  const root = document.querySelector('[data-food-page="purchases_new"]');
  if (!root || !document.getElementById("purchaseFormRoot")) return;

  const $ = (sel, within = document) => within.querySelector(sel);
  const $$ = (sel, within = document) => [...within.querySelectorAll(sel)];
  const money = (v) => `${Number(v || 0).toLocaleString("en-IQ")} د.ع`;
  const num = (v) => Number(v || 0).toLocaleString("en-IQ");
  const esc = (v) => String(v ?? "").replace(/[&<>'"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[c]));
  const notice = (message, error = false) => {
    const box = $("#foodNotice");
    if (!box) return alert(message);
    box.textContent = message;
    box.className = `food-notice${error ? " error" : ""}`;
    box.hidden = false;
    clearTimeout(box._timer);
    box._timer = setTimeout(() => { box.hidden = true; }, 4200);
  };

  async function api(path, options = {}) {
    const { headers: optionHeaders, ...rest } = options;
    const response = await fetch(`/food/api${path}`, {
      ...rest,
      headers: { "Content-Type": "application/json", ...(optionHeaders || {}) },
    });
    const payload = await response.json().catch(() => ({ ok: false, error: "استجابة غير صالحة" }));
    if (!response.ok || !payload.ok) throw new Error(payload.error || "تعذر إكمال العملية");
    return payload.data;
  }

  const state = {
    products: [],
    suppliers: [],
    warehouses: [],
    warehouseId: null,
    lines: [],
    supplier: null,
    expanded: new Set(),
  };

  function productLabel(p) {
    return `${p.product_name} — ${p.variant_name}${p.size ? ` / ${p.size}` : ""}`;
  }

  function lineTotal(line) {
    return Math.max(0, Number(line.quantity || 0) * Number(line.price || 0) - Number(line.discount || 0));
  }

  function totals() {
    const lineDiscounts = state.lines.reduce((s, l) => s + Number(l.discount || 0), 0);
    const sub = state.lines.reduce((s, l) => s + Number(l.quantity || 0) * Number(l.price || 0), 0);
    const afterLines = state.lines.reduce((s, l) => s + lineTotal(l), 0);
    const headerDiscount = Number($("#purchaseDiscount")?.value || 0);
    const shipping = Number($("#purchaseShipping")?.value || 0);
    const customs = Number($("#purchaseCustoms")?.value || 0);
    const other = Number($("#purchaseOther")?.value || 0);
    const extras = shipping + customs + other;
    const grand = Math.max(0, afterLines - headerDiscount + extras);
    const mode = $("#purchasePayment")?.value || "cash";
    let paid = Number($("#purchasePaid")?.value || 0);
    if (mode === "cash") {
      paid = grand;
      if ($("#purchasePaid") && document.activeElement !== $("#purchasePaid")) {
        $("#purchasePaid").value = String(grand);
      }
    }
    if (mode === "credit") paid = 0;
    paid = Math.min(grand, Math.max(0, paid));
    const remaining = Math.max(0, grand - paid);
    let baseUnits = 0;
    state.lines.forEach((line) => {
      const p = state.products.find((x) => x.id === line.variantId);
      const u = p?.units?.find((x) => x.id === line.unitId);
      baseUnits += (Number(line.quantity || 0) + Number(line.bonus || 0)) * Number(u?.factor || 1);
    });
    return { sub, lineDiscounts, afterLines, headerDiscount, extras, grand, paid, remaining, baseUnits };
  }

  function renderSummary() {
    const t = totals();
    const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
    set("#pnSubtotal", money(t.sub));
    set("#pnLineDiscounts", money(t.lineDiscounts));
    set("#pnHeaderDiscount", money(t.headerDiscount));
    set("#pnExtras", money(t.extras));
    set("#purchaseTotal", money(t.grand));
    set("#pnPaidNow", money(t.paid));
    set("#pnRemainSide", money(t.remaining));
    set("#pnRemaining", money(t.remaining));
    set("#pnItemsFoot", `${num(state.lines.length)} مادة · ${num(t.baseUnits)} وحدة أساسية`);
    set("#pnBaseHint", `${num(t.baseUnits)} وحدة أساسية`);
    const wh = state.warehouses.find((w) => String(w.id) === String(state.warehouseId));
    set("#pnWhHint", wh ? `تحديث مخزون: ${wh.name}` : "مخزن الاستلام");
    if (state.supplier) {
      set("#pnSupThis", money(t.grand));
      set("#pnSupPaid", money(t.paid));
      const expect = Number(state.supplier.debt || 0) + t.grand - t.paid;
      set("#pnSupExpect", money(expect));
    }
    const empty = $("#pnItemsEmpty");
    if (empty) empty.hidden = state.lines.length > 0;
  }

  function addLine(seed = {}) {
    if (!state.products.length) return notice("لا توجد منتجات للشراء", true);
    const product = seed.variantId
      ? state.products.find((p) => p.id === seed.variantId)
      : state.products[0];
    if (!product) return;
    const unit = product.units.find((u) => u.id === (seed.unitId || product.default_purchase_unit_id) && u.can_purchase !== false)
      || product.units.find((u) => u.can_purchase !== false);
    if (!unit) return notice("لا توجد وحدة مفعلة للشراء لهذا المنتج", true);
    const idx = state.lines.length;
    state.lines.push({
      variantId: product.id,
      unitId: unit.id,
      quantity: seed.quantity || 1,
      bonus: 0,
      price: seed.price ?? (unit.purchase_price || 0),
      discount: 0,
      batch: "",
      production: "",
      expiry: "",
      note: "",
    });
    state.expanded.add(idx);
    renderLines();
  }

  function renderLines() {
    const body = $("#purchaseLines");
    if (!body) return;
    body.innerHTML = state.lines.map((line, index) => {
      const product = state.products.find((p) => p.id === line.variantId) || state.products[0];
      if (!product) return "";
      const unit = product.units.find((u) => u.id === line.unitId) || product.units[0];
      line.variantId = product.id;
      line.unitId = unit.id;
      const open = state.expanded.has(index);
      const img = product.image_url
        ? `<img src="${esc(product.image_url)}" alt="">`
        : `<span class="pn-thumb-fallback"><i class="fa fa-box"></i></span>`;
      return `
        <tr class="pn-row" data-i="${index}">
          <td>
            <div class="pn-item-cell">
              <button type="button" class="pn-expand" data-expand="${index}" aria-expanded="${open}"><i class="fa fa-chevron-${open ? "up" : "down"}"></i></button>
              <div class="pn-thumb">${img}</div>
              <div>
                <select data-f="variant">${state.products.map((p) => `<option value="${p.id}" ${p.id === line.variantId ? "selected" : ""}>${esc(productLabel(p))}</option>`).join("")}</select>
                <small>${esc(product.sku || product.barcode || "")}</small>
              </div>
            </div>
          </td>
          <td><select data-f="unit">${product.units.filter((u) => u.can_purchase !== false).map((u) => `<option value="${u.id}" ${u.id === line.unitId ? "selected" : ""}>${esc(u.name)} × ${u.factor}</option>`).join("")}</select></td>
          <td><input data-f="quantity" type="number" min="1" value="${line.quantity}"></td>
          <td><input data-f="bonus" type="number" min="0" value="${line.bonus}"></td>
          <td><input data-f="price" type="number" min="0" value="${line.price}"></td>
          <td><input data-f="discount" type="number" min="0" value="${line.discount}"></td>
          <td><b>${money(lineTotal(line))}</b></td>
          <td><button type="button" class="pn-trash" data-remove="${index}" title="حذف"><i class="fa fa-trash"></i></button></td>
        </tr>
        <tr class="pn-detail ${open ? "is-open" : ""}" data-detail="${index}" ${open ? "" : "hidden"}>
          <td colspan="8">
            <div class="pn-detail__grid">
              <label>Batch / Lot<input data-f="batch" value="${esc(line.batch || "")}" placeholder="LOT-..."></label>
              <label>تاريخ الإنتاج<input data-f="production" type="date" value="${line.production || ""}"></label>
              <label>تاريخ الانتهاء<input data-f="expiry" type="date" value="${line.expiry || ""}" ${product.track_expiry ? "required" : ""}></label>
              <label>ملاحظة السطر<input data-f="note" value="${esc(line.note || "")}" placeholder="اختياري"></label>
              <div class="pn-detail__meta">أساسي: ${num((Number(line.quantity || 0) + Number(line.bonus || 0)) * Number(unit.factor || 1))} · البونص يدخل المخزون ولا يدخل قيمة الفاتورة</div>
            </div>
          </td>
        </tr>`;
    }).join("");

    $$("#purchaseLines [data-expand]").forEach((btn) => {
      btn.onclick = () => {
        const i = Number(btn.dataset.expand);
        if (state.expanded.has(i)) state.expanded.delete(i);
        else state.expanded.add(i);
        renderLines();
      };
    });
    $$("#purchaseLines [data-remove]").forEach((btn) => {
      btn.onclick = () => {
        const i = Number(btn.dataset.remove);
        state.lines.splice(i, 1);
        state.expanded = new Set([...state.expanded].filter((x) => x !== i).map((x) => (x > i ? x - 1 : x)));
        renderLines();
      };
    });
    $$("#purchaseLines tr.pn-row").forEach((row) => {
      const i = Number(row.dataset.i);
      $$("[data-f]", row).forEach((input) => {
        input.onchange = () => {
          const line = state.lines[i];
          const key = input.dataset.f;
          if (key === "variant") {
            line.variantId = Number(input.value);
            const p = state.products.find((x) => x.id === line.variantId);
            line.unitId = p.default_purchase_unit_id || p.units[0].id;
            line.price = p.units.find((u) => u.id === line.unitId)?.purchase_price || 0;
            renderLines();
            return;
          }
          if (key === "unit") {
            line.unitId = Number(input.value);
            const p = state.products.find((x) => x.id === line.variantId);
            line.price = p.units.find((u) => u.id === line.unitId)?.purchase_price || 0;
            renderLines();
            return;
          }
          line[key] = ["batch", "production", "expiry", "note"].includes(key) ? input.value : Number(input.value || 0);
          renderLines();
        };
      });
    });
    $$("#purchaseLines tr.pn-detail").forEach((row) => {
      const i = Number(row.dataset.detail);
      $$("[data-f]", row).forEach((input) => {
        input.onchange = () => {
          const line = state.lines[i];
          const key = input.dataset.f;
          line[key] = ["batch", "production", "expiry", "note"].includes(key) ? input.value : Number(input.value || 0);
          renderSummary();
        };
      });
    });
    renderSummary();
  }

  async function refreshSupplier() {
    const id = $("#purchaseSupplier")?.value;
    const empty = $("#pnSupplierEmpty");
    const body = $("#pnSupplierBody");
    if (!id) {
      state.supplier = null;
      if (empty) empty.hidden = false;
      if (body) body.hidden = true;
      renderSummary();
      return;
    }
    try {
      const data = await api(`/purchases/supplier-summary/${id}`);
      state.supplier = data;
      if (empty) empty.hidden = true;
      if (body) body.hidden = false;
      $("#pnSupName").textContent = data.name || "—";
      $("#pnSupMeta").textContent = [data.phone, data.last_invoice_no].filter(Boolean).join(" · ") || "—";
      $("#pnSupDebt").textContent = money(data.debt);
      renderSummary();
    } catch {
      state.supplier = null;
      if (empty) empty.hidden = false;
      if (body) body.hidden = true;
    }
  }

  async function checkDuplicate() {
    const warn = $("#purchaseDupWarn");
    if (!warn) return;
    const supplierId = $("#purchaseSupplier")?.value;
    const inv = $("#supplierInvoiceNo")?.value?.trim();
    if (!supplierId || !inv) { warn.hidden = true; return; }
    try {
      const data = await api(`/purchases/check-duplicate?supplier_id=${supplierId}&supplier_invoice_no=${encodeURIComponent(inv)}`);
      if (data.duplicate) {
        warn.hidden = false;
        warn.textContent = `هذه الفاتورة مسجلة مسبقاً لهذا المورد (${data.duplicate.invoice_no || data.duplicate.id}).`;
      } else warn.hidden = true;
    } catch { warn.hidden = true; }
  }

  function payload(draft = false) {
    const internal = ($("#purchaseInternalNotes")?.value || "").trim();
    const notes = [($("#purchaseNotes")?.value || "").trim(), internal ? `داخلي: ${internal}` : ""].filter(Boolean).join("\n");
    return {
      supplier_id: $("#purchaseSupplier").value,
      warehouse_id: state.warehouseId,
      supplier_invoice_no: $("#supplierInvoiceNo").value,
      purchase_date: $("#purchaseDate").value,
      payment_type: $("#purchasePayment").value,
      paid_amount: $("#purchasePaid").value,
      currency: $("#purchaseCurrency")?.value || "IQD",
      notes,
      discount: $("#purchaseDiscount")?.value || 0,
      shipping_extra: $("#purchaseShipping")?.value || 0,
      customs_extra: $("#purchaseCustoms")?.value || 0,
      other_extra: $("#purchaseOther")?.value || 0,
      draft: !!draft,
      items: state.lines.map((l) => ({
        variant_id: l.variantId,
        unit_id: l.unitId,
        warehouse_id: state.warehouseId,
        quantity: l.quantity,
        bonus: l.bonus,
        purchase_price: l.price,
        discount: l.discount,
        batch_number: l.batch || null,
        production_date: l.production || null,
        expiry_date: l.expiry || null,
      })),
    };
  }

  async function save(draft = false) {
    if (!$("#purchaseSupplier")?.value) return notice("اختر المورد", true);
    if (!state.lines.length) return notice("أضف مادة واحدةً على الأقل", true);
    const buttons = [$("#savePurchase"), $("#savePurchaseBar"), $("#savePurchaseDraft"), $("#savePurchaseDraftBar")].filter(Boolean);
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const result = await api("/purchases", { method: "POST", body: JSON.stringify(payload(draft)) });
      notice(draft ? `تم حفظ المسودة ${result.invoice_no}` : `تم اعتماد ${result.invoice_no} وتحديث المخزون`);
      location.href = "/food/purchases";
    } catch (e) {
      notice(e.message, true);
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  async function scanBarcode(code) {
    code = String(code || "").trim();
    if (!code) return;
    let found = state.products.find((p) => (p.units || []).some((u) => (u.barcodes || []).some((b) => String(b.value || b.barcode || "") === code) || String(u.barcode || "") === code));
    if (!found) {
      const data = await api(`/products?q=${encodeURIComponent(code)}`);
      if (data.products?.length) {
        state.products = [...data.products, ...state.products.filter((p) => !data.products.some((x) => x.id === p.id))];
        found = data.products.find((p) => (p.units || []).some((u) => (u.barcodes || []).some((b) => String(b.value || b.barcode || "") === code))) || data.products[0];
      }
    }
    if (!found) return notice("المنتج غير موجود", true);
    const unit = found.units.find((u) => (u.barcodes || []).some((b) => String(b.value || b.barcode || "") === code) && u.can_purchase !== false)
      || found.units.find((u) => u.can_purchase !== false);
    addLine({ variantId: found.id, unitId: unit?.id, price: unit?.purchase_price || 0 });
    notice(`تمت إضافة ${productLabel(found)}`);
  }

  async function init() {
    const options = await api("/product-form-options");
    state.warehouses = options.warehouses || [];
    state.warehouseId = state.warehouses.find((w) => w.is_default)?.id || state.warehouses[0]?.id || null;
    const [productsData, suppliers] = await Promise.all([
      api("/products"),
      api("/suppliers"),
    ]);
    state.products = productsData.products || [];
    state.suppliers = suppliers || [];

    $("#purchaseDate").value = new Date().toISOString().slice(0, 10);
    $("#purchaseSupplier").innerHTML = '<option value="">اختر المورد</option>' + state.suppliers.map((s) => `<option value="${s.id}">${esc(s.name)} · ${money(s.debt)}</option>`).join("");
    $("#purchaseWarehouse").innerHTML = state.warehouses.map((w) => `<option value="${w.id}" ${String(w.id) === String(state.warehouseId) ? "selected" : ""}>${esc(w.name)}${w.is_default ? " · افتراضي" : ""}</option>`).join("") || '<option value="">المخزون العام</option>';

    $("#purchaseSupplier").onchange = () => { refreshSupplier(); checkDuplicate(); };
    $("#supplierInvoiceNo").onchange = checkDuplicate;
    $("#purchaseWarehouse").onchange = () => { state.warehouseId = Number($("#purchaseWarehouse").value) || null; renderSummary(); };
    ["purchaseDiscount", "purchaseShipping", "purchaseCustoms", "purchaseOther", "purchasePayment", "purchasePaid"].forEach((id) => {
      $(`#${id}`)?.addEventListener("input", renderSummary);
      $(`#${id}`)?.addEventListener("change", renderSummary);
    });
    $("#purchasePayment").onchange = () => {
      const mode = $("#purchasePayment").value;
      if (mode === "cash") $("#purchasePaid").value = totals().grand;
      if (mode === "credit") $("#purchasePaid").value = 0;
      renderSummary();
    };
    $("#addPurchaseLine").onclick = () => addLine();
    $("#savePurchase").onclick = () => save(false);
    $("#savePurchaseBar").onclick = () => save(false);
    $("#savePurchaseDraft").onclick = () => save(true);
    $("#savePurchaseDraftBar").onclick = () => save(true);
    $("#pnRefreshSummary").onclick = renderSummary;
    $("#purchaseBarcode").onkeydown = async (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const code = $("#purchaseBarcode").value;
      $("#purchaseBarcode").value = "";
      try { await scanBarcode(code); } catch (err) { notice(err.message, true); }
    };

    addLine();
    renderSummary();
  }

  init().catch((e) => notice(e.message, true));
})();
