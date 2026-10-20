(() => {
  "use strict";
  const root = document.getElementById("foodPartiesRoot");
  if (!root) return;

  const kind = root.dataset.partyKind === "suppliers" ? "suppliers" : "customers";
  const isCustomer = kind === "customers";
  const endpoint = isCustomer ? "/customers" : "/suppliers";
  const label = isCustomer ? "عميل" : "مورد";

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
    tab: "all",
    rows: [],
    summary: null,
    detail: null,
    loading: false,
    searchTimer: null,
  };

  function formatWhen(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return window.FinoraTime.format(d, { dateStyle: "short", timeStyle: "short" });
  }

  function openDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function queryParams() {
    const q = new URLSearchParams({
      summary: "1",
      tab: state.tab,
      q: ($("#partySearch")?.value || "").trim(),
    });
    return q;
  }

  function renderKpis(summary) {
    const cards = [
      [`إجمالي ${isCustomer ? "العملاء" : "الموردين"}`, summary.total, "fa-address-book", true],
      ["حسابات بذمم", summary.with_debt, "fa-scale-balanced", true],
      ["إجمالي الذمم", summary.debt_total, "fa-coins"],
      ["متأخر", summary.overdue_total, "fa-clock"],
      ["متوقف", summary.inactive, "fa-ban", true],
    ];
    $("#partyKpis").innerHTML = cards.map(([title, value, icon, count]) => `
      <article class="fi-kpi">
        <span class="fi-kpi__icon"><i class="fa ${icon}"></i></span>
        <div>
          <span class="fi-kpi__title">${title}</span>
          <strong class="fi-kpi__value">${count ? num(value) : money(value)}</strong>
        </div>
      </article>`).join("");
  }

  function updateTabCounts(summary) {
    const set = (id, value) => { const el = $(id); if (el) el.textContent = num(value || 0); };
    set("#partyTabAll", summary?.total);
    set("#partyTabDebt", summary?.with_debt);
    set("#partyTabOverdue", summary?.overdue_count);
    set("#partyTabClear", summary?.clear_count);
    set("#partyTabInactive", summary?.inactive);
    set("#partyTabCredit", summary?.credit_count);
  }

  function debtBadge(row) {
    if (Number(row.overdue) > 0) return `<span class="food-badge warn">${money(row.debt)}</span>`;
    if (Number(row.debt) > 0) return `<span class="food-badge">${money(row.debt)}</span>`;
    return `<span class="food-badge parties-badge-ok">${money(0)}</span>`;
  }

  function statusBits(row) {
    const bits = [];
    if (row.active === false) bits.push('<span class="parties-chip parties-chip--mute">متوقف</span>');
    if (row.is_over_credit) bits.push('<span class="parties-chip parties-chip--danger">تجاوز الائتمان</span>');
    else if (row.credit_usage != null && row.credit_usage >= 80) bits.push('<span class="parties-chip parties-chip--warn">قرب حد الائتمان</span>');
    if (Number(row.overdue) > 0) bits.push('<span class="parties-chip parties-chip--danger">متأخر</span>');
    return bits.join(" ");
  }

  function renderTable(rows) {
    const body = $("#partyTableBody");
    const empty = $("#partyEmpty");
    if (!rows.length) {
      body.innerHTML = "";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    body.innerHTML = rows.map((row) => {
      const subtitle = [
        row.company_name,
        row.customer_code ? `كود ${row.customer_code}` : null,
        row.city,
      ].filter(Boolean).map(esc).join(" · ");
      const terms = row.payment_term_days != null ? `${num(row.payment_term_days)} يوم` : "—";
      const credit = isCustomer
        ? (row.credit_limit != null
          ? `${money(row.credit_limit)}${row.credit_usage != null ? `<small class="parties-usage">${row.credit_usage}٪ مستخدم</small>` : ""}`
          : "—")
        : "";
      return `<tr data-id="${row.id}" class="${row.active === false ? "parties-row--inactive" : ""}">
        <td>
          <button type="button" class="parties-name-btn" data-open="${row.id}">
            <b>${esc(row.name)}</b>
            ${subtitle ? `<small>${subtitle}</small>` : ""}
            ${statusBits(row)}
          </button>
        </td>
        <td>${esc(row.phone || "—")}</td>
        ${isCustomer ? `<td>${credit}</td><td>${terms}</td>` : `<td>${terms}</td>`}
        <td>${money(row.total_purchases)}</td>
        <td>${money(row.paid)}</td>
        <td>${debtBadge(row)}</td>
        <td>${Number(row.overdue) > 0 ? `<span class="food-badge warn">${money(row.overdue)}</span>` : "—"}</td>
        <td class="parties-row-actions">
          <button type="button" class="food-ghost" data-open="${row.id}" title="عرض"><i class="fa fa-eye"></i></button>
          <button type="button" class="food-ghost" data-edit="${row.id}" title="تعديل"><i class="fa fa-pen"></i></button>
          ${Number(row.debt) > 0 ? `<button type="button" class="food-ghost" data-pay="${row.id}" title="${isCustomer ? "قبض" : "تسديد"}"><i class="fa fa-${isCustomer ? "arrow-down" : "arrow-up"}"></i></button>` : ""}
        </td>
      </tr>`;
    }).join("");

    $$("[data-open]", body).forEach((btn) => btn.addEventListener("click", () => openDrawer(Number(btn.dataset.open))));
    $$("[data-edit]", body).forEach((btn) => btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openEditForm(Number(btn.dataset.edit));
    }));
    $$("[data-pay]", body).forEach((btn) => btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openPay(Number(btn.dataset.pay));
    }));
  }

  async function loadList() {
    state.loading = true;
    $("#partySkeleton").hidden = false;
    try {
      const data = await api(`${endpoint}?${queryParams()}`);
      state.rows = data.rows || [];
      state.summary = data.summary || null;
      if (state.summary) {
        renderKpis(state.summary);
        updateTabCounts(state.summary);
      }
      renderTable(state.rows);
    } catch (error) {
      notice(error.message, true);
    } finally {
      state.loading = false;
      $("#partySkeleton").hidden = true;
    }
  }

  function fillForm(detail = null) {
    $("#partyId").value = detail?.id || "";
    $("#partyName").value = detail?.name || "";
    $("#partyPhone").value = detail?.phone || "";
    $("#partyPhone2").value = detail?.phone2 || "";
    $("#partyAddress").value = detail?.address || "";
    $("#partyTerms").value = detail?.payment_term_days ?? "";
    $("#partyActive").checked = detail ? detail.active !== false : true;
    if (isCustomer) {
      if ($("#partyCode")) $("#partyCode").value = detail?.customer_code || "";
      if ($("#partyCompany")) $("#partyCompany").value = detail?.company_name || "";
      if ($("#partyCity")) $("#partyCity").value = detail?.city || "";
      if ($("#partyCredit")) $("#partyCredit").value = detail?.credit_limit ?? "";
      if ($("#partyNotes")) $("#partyNotes").value = detail?.notes || "";
    }
    $("#partyFormTitle").textContent = detail ? `تعديل ${label}` : `إضافة ${label}`;
    $("#partyFormSubtitle").textContent = detail
      ? `تحديث بيانات ${esc(detail.name)}`
      : (isCustomer ? "بيانات الاتصال وحد الائتمان وأجل التحصيل." : "بيانات الاتصال وأجل التسديد.");
  }

  function openCreateForm() {
    fillForm(null);
    openDialog($("#partyFormDialog"));
    $("#partyName").focus();
  }

  async function openEditForm(id) {
    try {
      const detail = await api(`${endpoint}/${id}`);
      fillForm(detail);
      openDialog($("#partyFormDialog"));
      $("#partyName").focus();
    } catch (error) {
      notice(error.message, true);
    }
  }

  function formPayload() {
    const payload = {
      name: $("#partyName").value.trim(),
      phone: $("#partyPhone").value.trim(),
      phone2: $("#partyPhone2").value.trim(),
      address: $("#partyAddress").value.trim(),
      payment_term_days: $("#partyTerms").value === "" ? null : $("#partyTerms").value,
      active: $("#partyActive").checked,
    };
    if (isCustomer) {
      payload.customer_code = $("#partyCode")?.value.trim() || "";
      payload.company_name = $("#partyCompany")?.value.trim() || "";
      payload.city = $("#partyCity")?.value.trim() || "";
      payload.credit_limit = $("#partyCredit")?.value === "" ? null : $("#partyCredit").value;
      payload.notes = $("#partyNotes")?.value.trim() || "";
    }
    return payload;
  }

  async function openDrawer(id) {
    const drawer = $("#partyDrawer");
    drawer.hidden = false;
    $("#partyDrawerBody").innerHTML = '<div class="fi-drawer-loading">جاري التحميل...</div>';
    try {
      const detail = await api(`${endpoint}/${id}`);
      state.detail = detail;
      $("#partyDrawerTitle").textContent = detail.name;
      const meta = [
        detail.phone || null,
        detail.company_name || null,
        detail.customer_code ? `كود ${detail.customer_code}` : null,
        detail.active === false ? "متوقف" : "نشط",
      ].filter(Boolean);
      $("#partyDrawerMeta").innerHTML = meta.map((x) => `<span>${esc(x)}</span>`).join("");
      renderDrawer(detail);
    } catch (error) {
      $("#partyDrawerBody").innerHTML = `<div class="food-inline-error">${esc(error.message)}</div>`;
    }
  }

  function closeDrawer() {
    $("#partyDrawer").hidden = true;
    state.detail = null;
  }

  function renderDrawer(d) {
    const docs = isCustomer ? (d.invoices || []) : (d.purchases || []);
    const moves = isCustomer ? (d.receipts || []) : (d.payments || []);
    const docsTitle = isCustomer ? "الفواتير الأخيرة" : "فواتير الشراء الأخيرة";
    const movesTitle = isCustomer ? "سندات القبض" : "تسديدات المورد";
    const creditBlock = isCustomer ? `
      <div class="fi-card parties-stat-grid">
        <div><span>حد الائتمان</span><strong>${d.credit_limit != null ? money(d.credit_limit) : "بدون حد"}</strong></div>
        <div><span>المتاح</span><strong>${d.available_credit != null ? money(d.available_credit) : "—"}</strong></div>
        <div><span>أجل التحصيل</span><strong>${d.payment_term_days != null ? `${num(d.payment_term_days)} يوم` : `${num(d.default_payment_term_days)} يوم (افتراضي)`}</strong></div>
        <div><span>فواتير مفتوحة</span><strong>${num(d.open_invoices || 0)}</strong></div>
      </div>` : `
      <div class="fi-card parties-stat-grid">
        <div><span>أجل التسديد</span><strong>${d.payment_term_days != null ? `${num(d.payment_term_days)} يوم` : `${num(d.default_payment_term_days)} يوم (افتراضي)`}</strong></div>
        <div><span>مشتريات مفتوحة</span><strong>${num(d.open_purchases || 0)}</strong></div>
        <div><span>رصيد افتتاحي</span><strong>${money(d.opening_balance || 0)}</strong></div>
        <div><span>عدد الفواتير</span><strong>${num(d.purchase_count || 0)}</strong></div>
      </div>`;

    $("#partyDrawerBody").innerHTML = `
      <div class="fi-drawer-actions">
        <button type="button" class="food-primary" data-drawer-edit><i class="fa fa-pen"></i> تعديل</button>
        ${Number(d.debt) > 0 ? `<button type="button" class="food-ghost" data-drawer-pay><i class="fa fa-${isCustomer ? "arrow-down" : "arrow-up"}"></i> ${isCustomer ? "قبض" : "تسديد"}</button>` : ""}
        <a class="food-ghost" href="${isCustomer ? "/food/orders" : "/food/purchases"}"><i class="fa fa-receipt"></i> ${isCustomer ? "الفواتير" : "المشتريات"}</a>
      </div>
      <div class="fi-card parties-balance-card">
        <div><span>إجمالي التعامل</span><strong>${money(d.total_purchases)}</strong></div>
        <div><span>المدفوع</span><strong>${money(d.paid)}</strong></div>
        <div><span>الذمة</span><strong class="${Number(d.debt) > 0 ? "parties-debt" : ""}">${money(d.debt)}</strong></div>
        <div><span>متأخر</span><strong class="${Number(d.overdue) > 0 ? "parties-debt" : ""}">${money(d.overdue)}</strong></div>
      </div>
      ${creditBlock}
      ${(d.address || d.notes || d.phone2) ? `<div class="fi-card"><h3>بيانات التواصل</h3>
        ${d.phone2 ? `<p><b>هاتف إضافي:</b> ${esc(d.phone2)}</p>` : ""}
        ${d.address ? `<p><b>العنوان:</b> ${esc(d.address)}</p>` : ""}
        ${d.city ? `<p><b>المدينة:</b> ${esc(d.city)}</p>` : ""}
        ${d.notes ? `<p><b>ملاحظات:</b> ${esc(d.notes)}</p>` : ""}
      </div>` : ""}
      <div class="fi-card">
        <h3>${docsTitle}</h3>
        ${docs.length ? `<div class="food-table-wrap"><table class="food-table"><thead><tr>
          <th>الرقم</th><th>الإجمالي</th><th>المتبقي</th><th>التاريخ</th>
        </tr></thead><tbody>
          ${docs.map((row) => `<tr>
            <td>${row.href ? `<a href="${esc(row.href)}">${esc(row.invoice_no)}</a>` : esc(row.invoice_no)}
              ${row.supplier_invoice_no ? `<small>${esc(row.supplier_invoice_no)}</small>` : ""}</td>
            <td>${money(row.total)}</td>
            <td>${Number(row.remaining) > 0 ? `<span class="food-badge warn">${money(row.remaining)}</span>` : money(0)}</td>
            <td>${formatWhen(row.created_at)}</td>
          </tr>`).join("")}
        </tbody></table></div>` : '<p class="parties-empty-note">لا توجد حركات بعد.</p>'}
      </div>
      <div class="fi-card">
        <h3>${movesTitle}</h3>
        ${moves.length ? `<div class="food-table-wrap"><table class="food-table"><thead><tr>
          <th>المبلغ</th><th>ملاحظة</th><th>التاريخ</th>
        </tr></thead><tbody>
          ${moves.map((row) => `<tr>
            <td>${money(row.amount)}</td>
            <td>${esc(row.note || row.payment_method || "—")}</td>
            <td>${formatWhen(row.recorded_at || row.created_at)}</td>
          </tr>`).join("")}
        </tbody></table></div>` : '<p class="parties-empty-note">لا توجد سندات بعد.</p>'}
      </div>`;

    $("[data-drawer-edit]")?.addEventListener("click", () => {
      closeDrawer();
      openEditForm(d.id);
    });
    $("[data-drawer-pay]")?.addEventListener("click", () => openPay(d.id, d));
  }

  async function openPay(id, detail = null) {
    try {
      const d = detail || await api(`${endpoint}/${id}`);
      if (!Number(d.debt)) return notice("لا توجد ذمة مستحقة", true);
      $("#partyPayId").value = d.id;
      $("#partyPayAmount").value = d.debt;
      $("#partyPaySubtitle").textContent = `${d.name} · الذمة ${money(d.debt)}`;
      $("#partyPayHint").textContent = `الحد الأقصى ${money(d.debt)}`;
      $("#partyPayTitle").textContent = isCustomer ? "سند قبض" : "تسديد مورد";
      openDialog($("#partyPayDialog"));
      $("#partyPayAmount").focus();
      $("#partyPayAmount").select();
    } catch (error) {
      notice(error.message, true);
    }
  }

  function bindUi() {
    $("#partyAddBtn")?.addEventListener("click", openCreateForm);
    $("#partyEmptyAdd")?.addEventListener("click", openCreateForm);
    $("#partyApplyFilter")?.addEventListener("click", loadList);
    $("#partyResetFilter")?.addEventListener("click", () => {
      $("#partySearch").value = "";
      state.tab = "all";
      $$("#partyTabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === "all"));
      loadList();
    });
    $("#partySearch")?.addEventListener("input", () => {
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(loadList, 280);
    });
    $$("#partyTabs button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.tab = btn.dataset.tab || "all";
        $$("#partyTabs button").forEach((b) => b.classList.toggle("active", b === btn));
        loadList();
      });
    });

    $$("#partyFormDialog [data-close], #partyPayDialog [data-close]").forEach((btn) => {
      btn.addEventListener("click", () => closeDialog(btn.closest("dialog")));
    });
    $$("[data-party-close]").forEach((el) => el.addEventListener("click", closeDrawer));

    $("#partyForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const id = $("#partyId").value;
      const payload = formPayload();
      const saveBtn = $("#partySaveBtn");
      saveBtn.disabled = true;
      try {
        if (id) {
          await api(`${endpoint}/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
          notice(`تم تحديث ${label}`);
        } else {
          await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
          notice(`تم إضافة ${label}`);
        }
        closeDialog($("#partyFormDialog"));
        await loadList();
      } catch (error) {
        notice(error.message, true);
      } finally {
        saveBtn.disabled = false;
      }
    });

    $("#partyPayForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const id = Number($("#partyPayId").value);
      const amount = $("#partyPayAmount").value;
      const saveBtn = $("#partyPaySave");
      saveBtn.disabled = true;
      try {
        const path = isCustomer ? "/finance/customer-receipt" : "/finance/supplier-payment";
        const body = isCustomer
          ? { customer_id: id, amount }
          : { supplier_id: id, amount };
        const result = await api(path, { method: "POST", body: JSON.stringify(body) });
        notice(`تم تسجيل ${money(result.applied)}`);
        closeDialog($("#partyPayDialog"));
        await loadList();
        if (!$("#partyDrawer").hidden) await openDrawer(id);
      } catch (error) {
        notice(error.message, true);
      } finally {
        saveBtn.disabled = false;
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !$("#partyDrawer").hidden) closeDrawer();
    });
  }

  bindUi();
  loadList();
})();
