(() => {
  "use strict";
  const root = document.querySelector('[data-food-page="orders"]');
  if (!root || !document.getElementById("foodInvoicesRoot")) return;

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
    page: 1,
    pageSize: 20,
    tab: "all",
    meta: null,
    selected: new Set(),
    detail: null,
    payInvoiceId: null,
    returnInvoice: null,
    manualLines: [],
    productsCache: [],
    loading: false,
  };

  function params() {
    const q = new URLSearchParams({
      range: $("#fiRange").value || "today",
      page: String(state.page),
      page_size: String(state.pageSize),
      status_tab: state.tab,
      q: ($("#fiSearch").value || "").trim(),
    });
    if ($("#fiRange").value === "custom") {
      q.set("start", $("#fiStart").value);
      q.set("end", $("#fiEnd").value);
    }
    if ($("#fiBranch").value) q.set("branch_id", $("#fiBranch").value);
    if ($("#fiCashier").value) q.set("cashier_id", $("#fiCashier").value);
    if ($("#fiSaleType").value) q.set("sale_type", $("#fiSaleType").value);
    if ($("#fiPayMethod").value) q.set("payment_method", $("#fiPayMethod").value);
    if ($("#fiStatus").value) q.set("invoice_status", $("#fiStatus").value);
    return q;
  }

  function trendHtml(change) {
    if (change == null) return "";
    const up = Number(change) >= 0;
    return `<small class="fi-trend ${up ? "up" : "down"}">${up ? "↑" : "↓"} ${Math.abs(Number(change))}٪</small>`;
  }

  function statusBadge(row) {
    return `<span class="fi-badge fi-badge--${esc(row.status)}">${esc(row.status_label)}</span>`;
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return window.FinoraTime.format(d, { dateStyle: "short", timeStyle: "short" });
  }

  function renderKpis(kpis) {
    const cards = [
      ["إجمالي المبيعات", kpis.sales, "fa-coins"],
      ["عدد الفواتير", kpis.invoices, "fa-receipt", true],
      ["المقبوض", kpis.collected, "fa-hand-holding-dollar"],
      ["المتبقي / الآجل", kpis.remaining, "fa-scale-balanced"],
      ["المرتجعات", kpis.returns, "fa-rotate-left"],
      ["متوسط الفاتورة", kpis.average, "fa-chart-simple"],
    ];
    $("#fiKpis").innerHTML = cards.map(([title, card, icon, count]) => `
      <article class="fi-kpi">
        <span class="fi-kpi__icon"><i class="fa ${icon}"></i></span>
        <div>
          <span class="fi-kpi__title">${title}</span>
          <strong class="fi-kpi__value">${count || !card.money ? num(card.value) : money(card.value)}</strong>
          ${trendHtml(card.change)}
        </div>
      </article>`).join("");
  }

  function renderTabs(tabs) {
    $("#fiTabAll").textContent = num(tabs.all);
    $("#fiTabCompleted").textContent = num(tabs.completed);
    $("#fiTabDue").textContent = num(tabs.due);
    $("#fiTabReturns").textContent = num(tabs.returns);
    $("#fiTabVoid").textContent = num(tabs.void);
  }

  function remainHtml(value) {
    const amount = Number(value || 0);
    if (amount <= 0) return `<span class="fi-muted">—</span>`;
    return `<span class="fi-remain">${money(amount)}</span>`;
  }

  function renderRows(rows) {
    const body = $("#fiTableBody");
    const mobile = $("#fiMobileList");
    const empty = $("#fiEmpty");
    const wrap = $("#fiTableWrap");
    const pager = $("#fiPager");
    const openId = state.detail?.id;
    if (!rows.length) {
      body.innerHTML = "";
      mobile.innerHTML = "";
      mobile.hidden = true;
      empty.hidden = false;
      wrap.hidden = true;
      if (pager) pager.hidden = true;
      if ($("#fiSelectAll")) $("#fiSelectAll").checked = false;
      return;
    }
    empty.hidden = true;
    wrap.hidden = false;
    if (pager) pager.hidden = false;
    mobile.hidden = false;
    body.innerHTML = rows.map((row) => {
      const checked = state.selected.has(row.id) ? "checked" : "";
      const openCls = openId === row.id ? "is-open" : "";
      const selCls = state.selected.has(row.id) ? "is-selected" : "";
      return `<tr data-id="${row.id}" class="${openCls} ${selCls}">
        <td class="fi-check-col" onclick="event.stopPropagation()"><input type="checkbox" data-select="${row.id}" ${checked}></td>
        <td><div class="fi-inv-no"><b title="${esc(row.invoice_no)}">${esc(row.invoice_no)}</b><small>${formatWhen(row.created_at)}</small></div></td>
        <td><div class="fi-cust"><b title="${esc(row.customer_name)}">${esc(row.customer_name || "عميل نقدي")}</b>${row.customer_phone ? `<small>${esc(row.customer_phone)}</small>` : ""}</div></td>
        <td><span class="fi-pill">${esc(row.sale_type_label)}</span></td>
        <td><span class="fi-pill">${esc(row.payment_method)}</span></td>
        <td>${num(row.item_count)} مادة</td>
        <td><b>${money(row.net_total || row.total)}</b></td>
        <td>${remainHtml(row.remaining)}</td>
        <td>${statusBadge(row)}</td>
        <td class="fi-actions" onclick="event.stopPropagation()">
          <button type="button" class="food-ghost" data-view="${row.id}" title="عرض"><i class="fa fa-eye"></i></button>
          <a class="food-ghost" href="${esc(row.print_url)}" target="_blank" rel="noopener" title="طباعة"><i class="fa fa-print"></i></a>
        </td>
      </tr>`;
    }).join("");

    mobile.innerHTML = rows.map((row) => `
      <article class="fi-card ${openId === row.id ? "is-open" : ""}" data-id="${row.id}">
        <header><b title="${esc(row.invoice_no)}">${esc(row.invoice_no)}</b>${statusBadge(row)}</header>
        <p>${esc(row.customer_name || "عميل نقدي")} · ${formatWhen(row.created_at)}</p>
        <p>${esc(row.sale_type_label)} · ${esc(row.payment_method)} · ${num(row.item_count)} مادة</p>
        <div class="fi-card__money"><strong>${money(row.net_total || row.total)}</strong>
          ${Number(row.remaining || 0) > 0 ? `<span class="fi-remain">متبقي ${money(row.remaining)}</span>` : `<span class="fi-muted">مدفوعة</span>`}
        </div>
      </article>`).join("");

    $$("#fiTableBody tr[data-id], #fiMobileList [data-id]").forEach((el) => {
      el.addEventListener("click", () => openDrawer(Number(el.dataset.id)));
    });
    $$("[data-view]").forEach((btn) => btn.addEventListener("click", () => openDrawer(Number(btn.dataset.view))));
    $$("[data-select]").forEach((box) => box.addEventListener("change", () => {
      const id = Number(box.dataset.select);
      if (box.checked) state.selected.add(id); else state.selected.delete(id);
      updateBulk();
    }));
    updateBulk();
  }

  function updateBulk() {
    const bar = $("#fiBulkBar");
    const n = state.selected.size;
    bar.hidden = n === 0;
    $("#fiBulkCount").textContent = n === 1 ? "تم تحديد فاتورة واحدة" : `تم تحديد ${num(n)} فواتير`;
    const boxes = $$("[data-select]");
    const all = $("#fiSelectAll");
    if (all && boxes.length) {
      all.checked = boxes.every((box) => box.checked);
      all.indeterminate = !all.checked && boxes.some((box) => box.checked);
    }
  }

  function renderPager(data) {
    const pages = data.pages || 1;
    const total = Number(data.total || 0);
    const buttons = [];
    const start = Math.max(1, state.page - 2);
    const end = Math.min(pages, start + 4);
    for (let p = start; p <= end; p += 1) {
      buttons.push(`<button type="button" class="${p === state.page ? "active" : ""}" data-page="${p}">${p}</button>`);
    }
    $("#fiPagerButtons").innerHTML = buttons.join("");
    $("#fiPagerMeta").textContent = total === 1 ? "فاتورة واحدة" : `${num(total)} فاتورة`;
    const pager = $("#fiPager");
    if (pager) pager.hidden = total === 0;
    $$("#fiPagerButtons [data-page]").forEach((btn) => {
      btn.onclick = () => { state.page = Number(btn.dataset.page); loadList(); };
    });
  }

  async function loadList() {
    if (state.loading) return;
    state.loading = true;
    $("#fiSkeleton").hidden = false;
    try {
      const data = await api(`/invoices?${params()}`);
      renderKpis(data.kpis || {});
      renderTabs(data.tabs || {});
      renderRows(data.rows || []);
      renderPager(data);
    } catch (error) {
      notice(error.message || "تعذر تحميل الفواتير", true);
    } finally {
      $("#fiSkeleton").hidden = true;
      state.loading = false;
    }
  }

  function closeDrawer() {
    const drawer = $("#fiDrawer");
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    state.detail = null;
    const copyBtn = $("#fiCopyInvoice");
    if (copyBtn) copyBtn.hidden = true;
    $$("#fiTableBody tr.is-open, #fiMobileList .is-open").forEach((el) => el.classList.remove("is-open"));
  }

  async function openDrawer(id) {
    const drawer = $("#fiDrawer");
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    $("#fiDrawerBody").innerHTML = '<div class="fi-drawer-loading">جاري التحميل...</div>';
    try {
      const detail = await api(`/invoices/${id}`);
      state.detail = detail;
      renderDrawer(detail);
      $$("#fiTableBody tr").forEach((tr) => tr.classList.toggle("is-selected", Number(tr.dataset.id) === id));
    } catch (error) {
      $("#fiDrawerBody").innerHTML = `<div class="food-inline-error">${esc(error.message)}</div>`;
    }
  }

  function renderDrawer(d) {
    const title = d.invoice_no || `#${d.id}`;
    const titleEl = $("#fiDrawerTitle");
    titleEl.textContent = title;
    titleEl.title = title;
    const copyBtn = $("#fiCopyInvoice");
    if (copyBtn) {
      copyBtn.hidden = false;
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(title);
          notice("تم نسخ رقم الفاتورة");
        } catch (_) {
          notice("تعذر النسخ", true);
        }
      };
    }
    $("#fiDrawerMeta").innerHTML = `${statusBadge(d)}<span>${formatWhen(d.created_at)}</span>${d.barcode ? `<span>${esc(d.barcode)}</span>` : ""}`;
    const perms = state.meta?.permissions || {};
    const customerBlock = d.customer
      ? `<div class="fi-block"><h3>العميل</h3><b>${esc(d.customer.name)}</b>
          <p>${esc(d.customer.phone || "—")}${d.customer.company_name ? ` · ${esc(d.customer.company_name)}` : ""}</p>
          <p>الرصيد الحالي: <b class="${Number(d.customer.balance) > 0 ? "fi-remain" : ""}">${money(d.customer.balance)}</b></p></div>`
      : `<div class="fi-block"><h3>العميل</h3><b>عميل نقدي</b><p>بيع بدون حساب عميل</p></div>`;

    const items = (d.items || []).map((item) => `
      <tr>
        <td><b>${esc(item.product_name)}</b>${item.variant_name ? `<br><small>${esc(item.variant_name)}</small>` : ""}
          ${item.sale_mode_label ? `<span class="fi-mini-badge">${esc(item.sale_mode_label)}</span>` : ""}</td>
        <td>${esc(item.unit_name)}</td>
        <td>${esc(item.quantity)}</td>
        <td>${money(item.unit_price)}</td>
        <td>${Number(item.discount || 0) ? money(item.discount) : '<span class="fi-muted">—</span>'}</td>
        <td><b>${money(item.line_total)}</b></td>
      </tr>`).join("");

    const payments = Object.entries(d.payment_breakdown || {}).map(([k, v]) =>
      `<div class="fi-pay-row"><span>${esc(k)}</span><b>${money(v)}</b></div>`).join("") || '<div class="food-empty">لا توجد مدفوعات</div>';

    const history = (d.payments || []).map((p) => `
      <div class="fi-timeline-item">
        <time>${formatWhen(p.recorded_at)}</time>
        <div><b>${p.amount >= 0 ? "قبض" : "عكس"} ${esc(p.method_label)}</b>
          <span>${money(Math.abs(p.amount))}</span>
          ${p.note ? `<small>${esc(p.note)}</small>` : ""}
        </div>
      </div>`).join("");

    const timeline = (d.timeline || []).map((t) => `
      <div class="fi-timeline-item">
        <time>${formatWhen(t.at)}</time>
        <div><b>${esc(t.label)}</b><small>${esc(t.employee || "")}</small></div>
      </div>`).join("");

    const profit = d.profit ? `
      <div class="fi-block"><h3>الربحية</h3>
        <div class="fi-summary">
          <div><span>الإيراد</span><b>${money(d.profit.revenue)}</b></div>
          ${d.profit.cost != null ? `<div><span>التكلفة</span><b>${money(d.profit.cost)}</b></div>` : ""}
          ${d.profit.profit != null ? `<div><span>الربح</span><b>${money(d.profit.profit)}</b></div>` : ""}
          ${d.profit.margin != null ? `<div><span>الهامش</span><b>${d.profit.margin}٪</b></div>` : ""}
        </div>
      </div>` : "";

    $("#fiDrawerBody").innerHTML = `
      <div class="fi-drawer-actions">
        ${d.can_receive_payment && perms.receive_payment !== false
          ? `<button type="button" class="food-primary" id="fiActPay"><i class="fa fa-hand-holding-dollar"></i> تسجيل قبض</button>` : ""}
        ${d.can_return && perms.return
          ? `<button type="button" class="food-ghost" id="fiActReturn"><i class="fa fa-rotate-left"></i> مرتجع</button>` : ""}
        ${perms.reprint !== false
          ? `<a class="food-ghost" id="fiActPrint" href="${esc(d.print_url)}" target="_blank" rel="noopener"><i class="fa fa-print"></i> إعادة طباعة</a>` : ""}
        <div class="fi-more">
          <button type="button" class="food-ghost" id="fiMoreBtn" aria-label="المزيد"><i class="fa fa-ellipsis-vertical"></i></button>
          <div id="fiMoreMenu" class="fi-more-menu" hidden>
            ${d.can_void && perms.void
              ? `<button type="button" id="fiActVoid"><i class="fa fa-ban"></i> إلغاء الفاتورة</button>` : ""}
            <a href="${esc(d.print_url)}" target="_blank" rel="noopener"><i class="fa fa-external-link"></i> فتح صفحة الطباعة</a>
          </div>
        </div>
      </div>
      ${customerBlock}
      <div class="fi-block"><h3>معلومات العملية</h3>
        <div class="fi-meta-grid">
          <div><span>نوع البيع</span><b>${esc(d.sale_type_label || "—")}</b></div>
          <div><span>الفرع / المخزن</span><b>${esc(d.branch_name || d.warehouse_name || "—")}</b></div>
          <div><span>الكاشير</span><b>${esc(d.cashier_name || "—")}</b></div>
          <div><span>طريقة الدفع</span><b>${esc(d.payment_method || "—")}</b></div>
        </div>
      </div>
      <div class="fi-block"><h3>المواد <small style="color:#66777c;font-weight:700">(${num((d.items || []).length)})</small></h3>
        <div class="fi-items-wrap"><table class="food-table">
          <thead><tr><th>المنتج</th><th>الوحدة</th><th>الكمية</th><th>السعر</th><th>الخصم</th><th>الإجمالي</th></tr></thead>
          <tbody>${items || '<tr><td colspan="6" class="food-empty">لا توجد مواد</td></tr>'}</tbody>
        </table></div>
      </div>
      <div class="fi-block"><h3>ملخص الفاتورة</h3>
        <div class="fi-summary">
          <div><span>المجموع الفرعي</span><b>${money(d.subtotal)}</b></div>
          <div><span>الخصم</span><b>${money(d.discount)}</b></div>
          <div><span>الإجمالي</span><b>${money(d.total)}</b></div>
          ${d.return_total ? `<div><span>المرتجع</span><b>${money(d.return_total)}</b></div><div><span>صافي الفاتورة</span><b>${money(d.net_total)}</b></div>` : ""}
          <div class="ok"><span>المدفوع</span><b>${money(d.paid)}</b></div>
          <div class="${Number(d.remaining) > 0 ? "warn" : ""}"><span>المتبقي</span><b>${Number(d.remaining) > 0 ? money(d.remaining) : "—"}</b></div>
        </div>
      </div>
      <div class="fi-block"><h3>تفاصيل الدفع</h3>${payments}</div>
      <div class="fi-block"><h3>سجل الدفعات</h3><div class="fi-timeline">${history || '<div class="food-empty">لا يوجد سجل</div>'}</div></div>
      ${profit}
      <div class="fi-block"><h3>سجل النشاط</h3><div class="fi-timeline">${timeline || '<div class="food-empty">لا يوجد نشاط</div>'}</div></div>
    `;

    $$("#fiTableBody tr").forEach((tr) => tr.classList.toggle("is-open", Number(tr.dataset.id) === d.id));
    $$("#fiMobileList [data-id]").forEach((card) => card.classList.toggle("is-open", Number(card.dataset.id) === d.id));

    $("#fiActPay")?.addEventListener("click", () => openPayDialog(d));
    $("#fiActReturn")?.addEventListener("click", () => openReturnDialog(d));
    $("#fiActPrint")?.addEventListener("click", () => {
      api(`/invoices/${d.id}/reprint`, { method: "POST", body: "{}" }).catch(() => {});
    });
    $("#fiMoreBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = $("#fiMoreMenu");
      menu.hidden = !menu.hidden;
    });
    document.addEventListener("click", function hideMore(event) {
      const menu = $("#fiMoreMenu");
      if (!menu || menu.hidden) return;
      if (!event.target.closest(".fi-more")) menu.hidden = true;
    }, { once: true });
    $("#fiActVoid")?.addEventListener("click", async () => {
      if (!confirm("إلغاء الفاتورة وإرجاع المخزون؟ لا يمكن التراجع.")) return;
      try {
        await api(`/invoices/${d.id}/void`, { method: "POST", body: JSON.stringify({ reason: "إلغاء من صفحة الفواتير" }) });
        notice("تم إلغاء الفاتورة");
        closeDrawer();
        loadList();
      } catch (error) {
        notice(error.message, true);
      }
    });
  }

  function openPayDialog(d) {
    state.payInvoiceId = d.id;
    $("#fiPayRemainingHint").textContent = `المتبقي: ${money(d.remaining)}`;
    $("#fiPayAmount").value = d.remaining;
    $("#fiPayNote").value = "";
    $("#fiPayError").hidden = true;
    $("#fiPayDialog").showModal();
  }

  async function confirmPay() {
    const err = $("#fiPayError");
    err.hidden = true;
    try {
      await api(`/invoices/${state.payInvoiceId}/payments`, {
        method: "POST",
        body: JSON.stringify({
          amount: $("#fiPayAmount").value,
          method: $("#fiPayMethodDialog").value,
          note: $("#fiPayNote").value,
        }),
      });
      $("#fiPayDialog").close();
      notice("تم تسجيل القبض");
      await openDrawer(state.payInvoiceId);
      loadList();
    } catch (error) {
      err.textContent = error.message;
      err.hidden = false;
    }
  }

  function openReturnDialog(d) {
    state.returnInvoice = d;
    $("#fiReturnError").hidden = true;
    $("#fiReturnItems").innerHTML = (d.items || []).map((item) => {
      const max = Number(item.returnable_quantity || 0);
      if (max <= 0) return "";
      return `<label class="fi-return-line">
        <div><b>${esc(item.product_name)}</b><small>تم البيع: ${esc(item.quantity)} ${esc(item.unit_name)} · المتبقي للإرجاع: ${esc(item.returnable_quantity)}</small></div>
        <input type="number" min="0" max="${max}" step="0.001" value="0" data-snapshot="${item.snapshot_id}" data-max="${max}">
      </label>`;
    }).join("") || '<div class="food-empty">لا توجد مواد قابلة للإرجاع</div>';
    $("#fiReturnDialog").showModal();
  }

  async function confirmReturn() {
    const err = $("#fiReturnError");
    err.hidden = true;
    const items = $$("#fiReturnItems [data-snapshot]").map((input) => ({
      snapshot_id: Number(input.dataset.snapshot),
      quantity: Number(input.value || 0),
    })).filter((row) => row.quantity > 0);
    if (!items.length) {
      err.textContent = "حدد كمية مرتجعة واحدة على الأقل";
      err.hidden = false;
      return;
    }
    let reason = $("#fiReturnReason").value;
    if (reason === "سبب آخر") reason = ($("#fiReturnNote").value || "").trim() || "سبب آخر";
    try {
      await api("/cashier/returns", {
        method: "POST",
        body: JSON.stringify({
          invoice_id: state.returnInvoice.id,
          idempotency_key: `inv-ret-${state.returnInvoice.id}-${Date.now()}`,
          items,
          refund_method: $("#fiReturnRefund").value,
          reason,
          warehouse_id: state.returnInvoice.warehouse_id,
        }),
      });
      $("#fiReturnDialog").close();
      notice("تم تسجيل المرتجع");
      await openDrawer(state.returnInvoice.id);
      loadList();
    } catch (error) {
      err.textContent = error.message;
      err.hidden = false;
    }
  }

  /* -------- Manual wholesale invoice -------- */
  function openManual() {
    const dialog = $("#fiManualDialog");
    state.manualLines = [];
    addManualLine();
    $("#fiManualError").hidden = true;
    $("#fiManualPay").dispatchEvent(new Event("change"));
    dialog.showModal();
    setTimeout(() => $$("#fiManualLines [data-m=search]")[0]?.focus(), 50);
  }

  function addManualLine(seed = {}) {
    state.manualLines.push({
      query: seed.query || "",
      product: seed.product || null,
      unitId: seed.unitId || null,
      quantity: seed.quantity || 1,
      price: seed.price || 0,
      discount: seed.discount || 0,
      saleMode: $("#fiManualMode").value || "WHOLESALE",
    });
    renderManualLines();
  }

  function renderManualLines() {
    $("#fiManualLines").innerHTML = state.manualLines.map((line, index) => {
      const units = line.product?.units?.filter((u) => u.can_sell !== false) || [];
      const unit = units.find((u) => u.id === line.unitId) || units[0];
      if (unit && !line.unitId) line.unitId = unit.id;
      const mode = line.saleMode || "WHOLESALE";
      const price = line.price || (mode === "WHOLESALE" ? unit?.wholesale_price : unit?.retail_price) || 0;
      line.price = price;
      const total = Math.max(0, price * Number(line.quantity || 0) - Number(line.discount || 0));
      return `<tr data-mline="${index}">
        <td><input data-m="search" value="${esc(line.product ? line.product.product_name : line.query)}" placeholder="باركود / اسم / SKU"></td>
        <td><select data-m="unit">${units.map((u) => `<option value="${u.id}" ${u.id === line.unitId ? "selected" : ""}>${esc(u.name)}</option>`).join("") || "<option value=\"\">—</option>"}</select></td>
        <td><input data-m="qty" type="number" min="0.001" step="0.001" value="${line.quantity}"></td>
        <td><input data-m="price" type="number" min="0" value="${price}"></td>
        <td><input data-m="discount" type="number" min="0" value="${line.discount || 0}"></td>
        <td><b>${money(total)}</b></td>
        <td><button type="button" class="food-remove" data-m-remove="${index}"><i class="fa fa-trash"></i></button></td>
      </tr>`;
    }).join("");
    const grand = state.manualLines.reduce((sum, line) => {
      const units = line.product?.units || [];
      const unit = units.find((u) => u.id === line.unitId) || units[0];
      const price = line.price || 0;
      return sum + Math.max(0, price * Number(line.quantity || 0) - Number(line.discount || 0));
    }, 0);
    $("#fiManualTotal").textContent = money(grand);

    $$("#fiManualLines [data-mline]").forEach((row) => {
      const index = Number(row.dataset.mline);
      const line = state.manualLines[index];
      const search = $('[data-m="search"]', row);
      search.onkeydown = async (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          await resolveManualProduct(index, search.value.trim());
          $('[data-m="qty"]', row)?.focus();
          $('[data-m="qty"]', row)?.select();
        }
      };
      search.onchange = () => { line.query = search.value; };
      $('[data-m="unit"]', row).onchange = (e) => {
        line.unitId = Number(e.target.value);
        const unit = line.product?.units?.find((u) => u.id === line.unitId);
        line.price = (line.saleMode === "WHOLESALE" ? unit?.wholesale_price : unit?.retail_price) || 0;
        renderManualLines();
      };
      $('[data-m="qty"]', row).onchange = (e) => { line.quantity = Number(e.target.value || 1); renderManualLines(); };
      $('[data-m="qty"]', row).onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); $('[data-m="price"]', row)?.focus(); }
      };
      $('[data-m="price"]', row).onchange = (e) => { line.price = Number(e.target.value || 0); renderManualLines(); };
      $('[data-m="price"]', row).onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          if (index === state.manualLines.length - 1) addManualLine();
          else $$("#fiManualLines [data-m=search]")[index + 1]?.focus();
        }
      };
      $('[data-m="discount"]', row).onchange = (e) => { line.discount = Number(e.target.value || 0); renderManualLines(); };
      $(`[data-m-remove="${index}"]`, row).onclick = () => {
        state.manualLines.splice(index, 1);
        if (!state.manualLines.length) addManualLine();
        else renderManualLines();
      };
    });
  }

  async function resolveManualProduct(index, term) {
    if (!term) return;
    const line = state.manualLines[index];
    try {
      const warehouseId = $("#fiManualWarehouse").value;
      const qs = new URLSearchParams();
      if (warehouseId) qs.set("warehouse_id", warehouseId);
      let found = null;
      try {
        found = await api(`/barcode/${encodeURIComponent(term)}?${qs}`);
      } catch (_) {
        found = null;
      }
      if (!found) {
        const catalog = await api(`/cashier/products?${new URLSearchParams({ q: term, per_page: 8, warehouse_id: warehouseId || "" })}`);
        found = (catalog.products || [])[0] || null;
      }
      if (!found) throw new Error("لم يتم العثور على المنتج");
      line.product = found;
      line.unitId = found.selected_unit_id || found.default_sale_unit_id || found.units?.[0]?.id;
      const unit = found.units?.find((u) => u.id === line.unitId) || found.units?.[0];
      line.saleMode = $("#fiManualMode").value || "WHOLESALE";
      line.price = (line.saleMode === "WHOLESALE" ? unit?.wholesale_price : unit?.retail_price) || 0;
      line.query = found.product_name;
      renderManualLines();
    } catch (error) {
      notice(error.message, true);
    }
  }

  async function saveManual() {
    const err = $("#fiManualError");
    err.hidden = true;
    const items = state.manualLines.filter((l) => l.product).map((l) => ({
      variant_id: l.product.id || l.product.variant_id,
      unit_id: l.unitId,
      quantity: l.quantity,
      sale_mode: l.saleMode || $("#fiManualMode").value,
      price: l.price,
      discount: l.discount || 0,
      warehouse_id: $("#fiManualWarehouse").value || null,
    }));
    if (!items.length) {
      err.textContent = "أضف مادة واحدة على الأقل";
      err.hidden = false;
      return;
    }
    const payment = $("#fiManualPay").value;
    const payload = {
      customer_id: $("#fiManualCustomer").value || null,
      warehouse_id: $("#fiManualWarehouse").value || null,
      payment_type: payment,
      paid_amount: payment === "partial" ? $("#fiManualPaid").value : undefined,
      note: $("#fiManualNote").value || null,
      items,
      idempotency_key: `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    };
    if (payment === "credit") payload.payments = [{ method: "credit", amount: 0 }];
    try {
      const result = await api("/sales", { method: "POST", body: JSON.stringify(payload) });
      $("#fiManualDialog").close();
      notice(`تم حفظ الفاتورة ${result.invoice_no}`);
      await loadList();
      openDrawer(result.id);
    } catch (error) {
      err.textContent = error.message;
      err.hidden = false;
    }
  }

  async function exportCsv() {
    try {
      const data = await api(`/invoices/export?${params()}`);
      const rows = data.rows || [];
      const header = ["invoice_no", "created_at", "customer_name", "sale_type", "payment_method", "total", "remaining", "status"];
      const lines = [header.join(",")].concat(rows.map((r) => [
        r.invoice_no, `"${window.FinoraTime.dateTime(r.created_at)}"`, `"${(r.customer_name || "").replace(/"/g, '""')}"`,
        r.sale_type_label, r.payment_method, r.net_total || r.total, r.remaining, r.status_label,
      ].join(",")));
      const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `food-invoices-${Date.now()}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      notice(error.message, true);
    }
  }

  function bindDialogs() {
    $$("dialog [data-close]").forEach((btn) => btn.addEventListener("click", () => btn.closest("dialog")?.close()));
    $$("[data-fi-close]").forEach((el) => el.addEventListener("click", closeDrawer));
    $("#fiPayConfirm").onclick = confirmPay;
    $("#fiReturnConfirm").onclick = confirmReturn;
    $("#fiReturnReason").onchange = () => {
      $("#fiReturnNoteWrap").hidden = $("#fiReturnReason").value !== "سبب آخر";
    };
    $("#fiManualAddLine").onclick = () => addManualLine();
    $("#fiManualSave").onclick = saveManual;
    $("#fiManualPay").onchange = () => {
      $("#fiManualPaidWrap").hidden = $("#fiManualPay").value !== "partial";
    };
  }

  async function init() {
    bindDialogs();
    const today = new Date().toISOString().slice(0, 10);
    $("#fiStart").value = today;
    $("#fiEnd").value = today;

    try {
      state.meta = await api("/invoices/meta");
      $("#fiBranch").innerHTML = '<option value="">كل الفروع</option>' +
        (state.meta.branches || []).map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("");
      $("#fiCashier").innerHTML = '<option value="">كل الكاشيرين</option>' +
        (state.meta.cashiers || []).map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    } catch (error) {
      notice(error.message, true);
    }

    try {
      const [customers, config] = await Promise.all([
        api("/customers").catch(() => []),
        api("/cashier-config").catch(() => ({ warehouses: [] })),
      ]);
      $("#fiManualCustomer").innerHTML = '<option value="">عميل نقدي</option>' +
        (customers || []).filter((c) => c.phone !== "FOOD-WALK-IN").map((c) =>
          `<option value="${c.id}">${esc(c.name)}${c.debt ? ` · دين ${money(c.debt)}` : ""}</option>`).join("");
      const warehouses = config.warehouses || [];
      $("#fiManualWarehouse").innerHTML = warehouses.map((w) =>
        `<option value="${w.id}" ${w.id === config.default_warehouse_id ? "selected" : ""}>${esc(w.name)}</option>`).join("")
        || '<option value="">المخزون العام</option>';
    } catch (_) { /* optional */ }

    let searchTimer;
    $("#fiSearch").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.page = 1; loadList(); }, 320);
    };
    ["fiRange", "fiBranch", "fiCashier", "fiSaleType", "fiPayMethod", "fiStatus", "fiPageSize"].forEach((id) => {
      $(`#${id}`).onchange = () => {
        if (id === "fiRange") $("#fiCustomRange").hidden = $("#fiRange").value !== "custom";
        if (id === "fiPageSize") state.pageSize = Number($("#fiPageSize").value) || 20;
        state.page = 1;
        if (id !== "fiRange" || $("#fiRange").value !== "custom") loadList();
      };
    });
    $("#fiApplyCustom").onclick = () => { state.page = 1; loadList(); };
    $$("#fiTabs [data-tab]").forEach((btn) => {
      btn.onclick = () => {
        $$("#fiTabs [data-tab]").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        state.tab = btn.dataset.tab;
        state.page = 1;
        loadList();
      };
    });
    $("#fiSelectAll").onchange = () => {
      const on = $("#fiSelectAll").checked;
      $$("[data-select]").forEach((box) => {
        box.checked = on;
        const id = Number(box.dataset.select);
        if (on) state.selected.add(id); else state.selected.delete(id);
      });
      updateBulk();
    };
    $("#fiNewInvoiceBtn").onclick = openManual;
    $("#fiEmptyNew").onclick = openManual;
    $("#fiExportBtn").onclick = exportCsv;
    $("#fiBulkExport").onclick = exportCsv;
    $("#fiBulkPrint").onclick = () => {
      [...state.selected].forEach((id) => window.open(`/orders/invoice/${id}`, "_blank", "noopener"));
    };

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("dialog[open]")) closeDrawer();
    });

    const url = new URL(window.location.href);
    if (url.searchParams.get("sale_type")) {
      $("#fiSaleType").value = url.searchParams.get("sale_type").toUpperCase();
    }
    if (url.searchParams.get("new") === "1") openManual();
    const openId = url.searchParams.get("open");
    await loadList();
    if (openId) openDrawer(Number(openId));
  }

  init().catch((error) => notice(error.message, true));
})();
