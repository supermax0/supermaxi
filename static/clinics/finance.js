/**
 * Finora Clinics — Finance pages (billing, expenses, cash, settlements)
 */
(() => {
  const UI = window.FinoraFinanceUI;
  if (!UI) return;

  const INV_STATUS = {
    paid: { label: "مدفوعة", cls: "green" },
    partial: { label: "مدفوعة جزئياً", cls: "blue" },
    open: { label: "غير مدفوعة", cls: "orange" },
    overdue: { label: "متأخرة", cls: "red" },
    cancelled: { label: "ملغاة", cls: "gray" },
    refunded: { label: "مستردة", cls: "purple" },
    void: { label: "ملغاة محاسبياً", cls: "gray" },
  };

  const SETTLEMENT_STATUS = {
    open: { label: "غير مدفوعة", cls: "orange" },
    paid: { label: "مكتملة", cls: "green" },
    partial: { label: "مدفوعة جزئياً", cls: "blue" },
    draft: { label: "مسودة", cls: "gray" },
    cancelled: { label: "ملغاة", cls: "red" },
  };

  function badge(map, key) {
    const s = map[key] || { label: key || "—", cls: "gray" };
    return `<span class="cx-fin-badge cx-fin-badge--${s.cls}">${s.label}</span>`;
  }

  function paintBilling(ctx) {
    ctx.root.innerHTML = buildBillingHtml(ctx);
    bindBilling(ctx);
  }

  function buildBillingHtml(ctx) {
    const rows = ctx.viewRows || [];
    const p = ctx.pagination || {};
    const inv = ctx.drawerInvoice;
    const listHtml = rows.length
      ? UI.tableCard(
          `<table class="cx-table cx-fin-table">
            <thead><tr>
              <th>رقم الفاتورة</th><th>المريض</th><th>الطبيب</th><th>التاريخ</th>
              <th>الإجمالي</th><th>الخصم</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th><th></th>
            </tr></thead>
            <tbody>${billingRows(ctx, rows)}</tbody>
          </table>`,
          UI.pagerHtml(ctx, p)
        )
      : `<section class="cx-fin-table-card cx-fin-table-card--empty">${UI.emptyHtml(
          "لا توجد فواتير لهذه الفترة",
          "تسجيل دفعة",
          "cxBillPayEmpty",
          { sub: "لم يتم العثور على فواتير أو دفعات مسجلة ضمن الفلتر المختار." }
        )}</section>`;
    return `
      <div class="cx-fin cx-fin--billing ${inv ? "has-drawer" : ""}">
        ${UI.headerHtml(ctx, {
          title: "الفواتير والمدفوعات",
          desc: "إدارة فواتير المرضى والتحصيلات والأرصدة",
          icon: "fa-file-invoice",
          kicker: "FINORA CLINICS",
          actionsRow: true,
          actions: [
            { id: "cxBillPay", label: "تسجيل دفعة", icon: "fa-plus", primary: true, finoraAction: "payment.record" },
            { id: "cxBillExport", label: "تصدير", icon: "fa-download", primary: false },
          ],
        })}
        <div class="cx-fin-kpis">${UI.kpisHtml(ctx.kpis || [])}</div>
        ${billingFilters(ctx)}
        ${listHtml}
        ${inv ? billingDrawer(inv, ctx) : ""}
        <div class="cx-fin-drawer-backdrop" id="cxFinBackdrop" ${inv ? "" : "hidden"}></div>
      </div>`;
  }

  function billingFilters(ctx) {
    const doctors = ctx.doctors || [];
    return UI.filtersShell(
      ctx,
      `
      <div class="cx-fin-filters__primary">
        <input type="search" class="cx-input" id="cxFinSearch" placeholder="بحث: فاتورة، مريض، هاتف…" value="${ctx.esc(ctx.state.q || "")}">
        <select class="cx-select" id="cxFinStatus">
          <option value="">كل الحالات</option>
          <option value="paid" ${ctx.state.status === "paid" ? "selected" : ""}>مدفوعة</option>
          <option value="partial" ${ctx.state.status === "partial" ? "selected" : ""}>جزئية</option>
          <option value="open" ${ctx.state.status === "open" ? "selected" : ""}>غير مدفوعة</option>
          <option value="refunded" ${ctx.state.status === "refunded" ? "selected" : ""}>مستردة</option>
        </select>
      </div>
      <div class="cx-fin-filters__secondary">
        <select class="cx-select" id="cxFinDoctor">
          <option value="">كل الأطباء</option>
          ${doctors.map((d) => `<option value="${d.id}" ${String(d.id) === String(ctx.state.doctor_id || "") ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`).join("")}
        </select>
      </div>`,
      `
      <select class="cx-select" id="cxFinMethod">
        <option value="">طريقة الدفع</option>
        ${Object.entries(UI.PAYMENT_METHODS).map(([k, v]) => `<option value="${k}" ${ctx.state.method === k ? "selected" : ""}>${v}</option>`).join("")}
      </select>`,
      ctx.state,
      ["method", "doctor_id", "status"]
    );
  }

  function billingRows(ctx, rows) {
    if (!rows.length) return "";
    return rows
      .map((inv) => {
        const st = inv.balance > 0 && inv.invoice_date < shiftDays(-7) ? "overdue" : inv.status;
        return `
        <tr data-inv="${inv.id}">
          <td><button type="button" class="cx-fin-link" data-open-inv="${inv.id}"><code>${ctx.esc(inv.invoice_number)}</code></button></td>
          <td>${ctx.esc(inv.patient_name || "—")}</td>
          <td>${ctx.esc(inv.doctor_name || "—")}</td>
          <td>${ctx.esc(inv.invoice_date || "—")}</td>
          <td class="cx-money">${ctx.money(inv.total)}</td>
          <td class="cx-money">${ctx.money(inv.discount || 0)}</td>
          <td class="cx-money">${ctx.money(inv.paid)}</td>
          <td class="cx-money ${inv.balance > 0 ? "is-due" : ""}">${ctx.money(inv.balance)}</td>
          <td>${badge(INV_STATUS, st)}</td>
          <td class="cx-fin-actions">
            ${inv.balance > 0 ? `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-pay="${inv.id}" data-bal="${inv.balance}" data-finora-action="payment.record">تحصيل</button>` : ""}
            <button type="button" class="cx-btn cx-btn--sm cx-btn--ghost" data-menu="${inv.id}" data-finora-action="invoice.row_menu.toggle"><i class="fa fa-ellipsis-vertical"></i></button>
            <div class="cx-fin-menu" hidden data-for="${inv.id}">
              <button type="button" data-act="open" data-id="${inv.id}">عرض التفاصيل</button>
              ${inv.balance > 0 ? `<button type="button" data-act="pay" data-id="${inv.id}" data-bal="${inv.balance}" data-finora-action="payment.record">تسجيل دفعة</button>` : ""}
              <button type="button" data-act="print" data-id="${inv.id}">طباعة</button>
              ${inv.paid > 0 ? `<button type="button" data-act="refund" data-id="${inv.id}" data-paid="${inv.paid}" data-finora-action="refund.record">استرداد</button>` : ""}
            </div>
          </td>
        </tr>`;
      })
      .join("");
  }

  function billingDrawer(inv, ctx) {
    const pays = (ctx.drawerPayments || [])
      .map(
        (p) => `
      <div class="cx-fin-timeline__item">
        <strong>${ctx.money(p.amount)}</strong>
        <span>${ctx.esc(UI.PAYMENT_METHODS[p.method] || p.method)} · ${ctx.esc((p.paid_at || "").replace("T", " ").slice(0, 16))}</span>
        <small>${ctx.esc(p.notes || "")}</small>
      </div>`
      )
      .join("");
    return `
      <aside class="cx-fin-drawer" id="cxFinDrawer" data-finora-section="invoice.drawer">
        <header class="cx-fin-drawer__head">
          <div><h2>${ctx.esc(inv.invoice_number)}</h2>${badge(INV_STATUS, inv.status)}</div>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxFinDrawerClose"><i class="fa fa-xmark"></i></button>
        </header>
        <div class="cx-fin-drawer__body">
          <div class="cx-fin-drawer__field"><span>المريض</span><b>${ctx.esc(inv.patient_name || "—")}</b></div>
          <div class="cx-fin-drawer__field"><span>الطبيب</span><b>${ctx.esc(inv.doctor_name || "—")}</b></div>
          <div class="cx-fin-drawer__field"><span>الإجمالي</span><b>${ctx.money(inv.total)}</b></div>
          <div class="cx-fin-drawer__field"><span>المدفوع</span><b>${ctx.money(inv.paid)}</b></div>
          <div class="cx-fin-drawer__field" data-finora-section="invoice.balance" data-remaining="${inv.balance}" data-status="${inv.status}"><span>المتبقي</span><b class="${inv.balance > 0 ? "is-due" : ""}">${ctx.money(inv.balance)}</b></div>
          <h3 class="cx-fin-drawer__sub">سجل الدفعات</h3>
          <div class="cx-fin-timeline" data-finora-section="payment.history">${pays || "<div class='cx-fin-muted'>لا دفعات بعد</div>"}</div>
        </div>
        <footer class="cx-fin-drawer__foot">
          ${inv.balance > 0 ? `<button type="button" class="cx-btn cx-btn--primary" data-drawer-pay="${inv.id}" data-bal="${inv.balance}" data-finora-action="payment.record.drawer">تسجيل دفعة</button>` : ""}
          ${inv.paid > 0 ? `<button type="button" class="cx-btn" data-drawer-refund="${inv.id}" data-paid="${inv.paid}" data-finora-action="refund.record.drawer">استرداد</button>` : ""}
          <a class="cx-btn" href="/clinics/patients/${inv.patient_id}">ملف المريض</a>
          <button type="button" class="cx-btn" data-drawer-print="${inv.id}">طباعة</button>
        </footer>
      </aside>`;
  }

  function shiftDays(n) {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return UI.localDateStr(d);
  }

  function computeBillingKpis(rows) {
    const total = rows.reduce((s, r) => s + Number(r.total || 0), 0);
    const paid = rows.reduce((s, r) => s + Number(r.paid || 0), 0);
    const balance = rows.reduce((s, r) => s + Number(r.balance || 0), 0);
    const unpaid = rows.filter((r) => Number(r.balance || 0) > 0).length;
    const overdue = rows.filter((r) => Number(r.balance || 0) > 0 && r.invoice_date < shiftDays(-7)).length;
    return [
      { label: "إجمالي المبالغ", value: numFmt(total), unit: "د.ع", theme: "blue", icon: "fa-wallet" },
      { label: "إجمالي الفواتير", value: rows.length, unit: "فاتورة", theme: "teal", icon: "fa-file-invoice" },
      { label: "المحصل", value: numFmt(paid), unit: "د.ع", theme: "green", icon: "fa-coins" },
      { label: "المتبقي", value: numFmt(balance), unit: "د.ع", theme: "orange", icon: "fa-clock" },
      { label: "غير مسددة", value: unpaid, unit: "فاتورة", theme: "rose", icon: "fa-triangle-exclamation" },
      { label: "متأخرة", value: overdue, unit: "متأخرة", theme: "red", icon: "fa-circle-exclamation" },
    ];
  }

  function numFmt(n) {
    return new Intl.NumberFormat("ar-IQ").format(n || 0);
  }

  function moneyFmt(n) {
    return numFmt(n) + " د.ع";
  }

  async function loadBilling(ctx) {
    const range = UI.resolveDateRange(ctx.state.quickDate, ctx.state.day, ctx.state.from, ctx.state.to);
    const qs = range.fetchAll ? "" : `?date=${encodeURIComponent(range.day)}`;
    const rows = await ctx.api(`/clinics/api/invoices${qs}`);
    const doctors = ctx.doctors || (await ctx.api("/clinics/api/doctors?active=1"));
    ctx.doctors = doctors;
    const docMap = Object.fromEntries((doctors || []).map((d) => [d.id, d.full_name]));
    let list = (Array.isArray(rows) ? rows : []).map((r) => ({
      ...r,
      doctor_name: docMap[r.doctor_id] || "",
    }));
    list = list.filter((r) => UI.inRange(r.invoice_date, range.from, range.to));
    if (ctx.state.q) {
      const q = ctx.state.q.toLowerCase();
      list = list.filter(
        (r) =>
          (r.invoice_number || "").toLowerCase().includes(q) ||
          (r.patient_name || "").toLowerCase().includes(q)
      );
    }
    if (ctx.state.status) list = list.filter((r) => r.status === ctx.state.status);
    if (ctx.state.doctor_id) list = list.filter((r) => String(r.doctor_id) === String(ctx.state.doctor_id));
    ctx.kpis = computeBillingKpis(list);
    const pg = UI.paginate(list, ctx.state.page, ctx.state.per_page);
    ctx.viewRows = pg.items;
    ctx.pagination = pg.pagination;
    ctx.allRows = list;
  }

  function promptPay(ctx, id, balance) {
    ctx.openModal(
      "تسجيل دفعة",
      `
      <div data-finora-section="payment.form">
      <div class="cx-field"><label>المتبقي</label><input class="cx-input" readonly value="${ctx.money(balance)}"></div>
      <div class="cx-field"><label>المبلغ *</label><input class="cx-input" id="pay_amount" data-finora-field="payment.amount" type="number" value="${balance}" max="${balance}"></div>
      <div class="cx-field"><label>طريقة الدفع</label>
        <select class="cx-select" id="pay_method" data-finora-field="payment.method">
          ${Object.entries(UI.PAYMENT_METHODS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
        </select>
      </div>
      <div class="cx-field"><label>ملاحظة</label><input class="cx-input" id="pay_notes" data-finora-field="payment.notes"></div>
      </div>`,
      async () => {
        const amt = Number(document.getElementById("pay_amount").value);
        if (amt <= 0) throw new Error("المبلغ غير صالح");
        if (amt > balance) throw new Error("المبلغ أكبر من المتبقي");
        await ctx.api(`/clinics/api/invoices/${id}/pay`, {
          method: "POST",
          body: JSON.stringify({
            amount: amt,
            method: document.getElementById("pay_method").value,
            notes: document.getElementById("pay_notes").value,
          }),
        });
        ctx.drawerInvoice = null;
        await refreshBilling(ctx);
      },
      { finoraAction: "payment.confirm" }
    );
  }

  function promptRefund(ctx, id, paid) {
    ctx.openModal(
      "استرداد",
      `
      <div data-finora-section="refund.form">
      <div class="cx-field"><label>المبلغ</label><input class="cx-input" id="rf_amount" data-finora-field="refund.amount" type="number" value="${paid}"></div>
      <div class="cx-field"><label>السبب</label><input class="cx-input" id="rf_reason" data-finora-field="refund.reason"></div>
      </div>`,
      async () => {
        await ctx.api(`/clinics/api/invoices/${id}/refund`, {
          method: "POST",
          body: JSON.stringify({
            amount: document.getElementById("rf_amount").value,
            reason: document.getElementById("rf_reason").value,
          }),
        });
        ctx.drawerInvoice = null;
        await refreshBilling(ctx);
      },
      { finoraAction: "refund.confirm" }
    );
  }

  async function openInvoiceDrawer(ctx, id) {
    const inv = (ctx.allRows || []).find((x) => String(x.id) === String(id));
    if (!inv) return;
    ctx.drawerInvoice = inv;
    try {
      const stmt = await ctx.api(`/clinics/api/patients/${inv.patient_id}/statement`);
      ctx.drawerPayments = (stmt.lines || []).filter((l) => l.type === "payment");
    } catch {
      ctx.drawerPayments = [];
    }
    paintBilling(ctx);
  }

  function bindBilling(ctx) {
    const root = ctx.root;
    UI.bindFilterChrome(ctx, async () => {
      ctx.state.page = 1;
      await refreshBilling(ctx);
    }, paintBilling);
    root.querySelector("#cxFinSearch")?.addEventListener("input", (e) => {
      clearTimeout(ctx._searchT);
      ctx._searchT = setTimeout(async () => {
        ctx.state.q = e.target.value;
        ctx.state.page = 1;
        await refreshBilling(ctx);
      }, 280);
    });
    ["cxFinStatus", "cxFinDoctor", "cxFinMethod"].forEach((id) => {
      const el = root.querySelector(`#${id}`);
      if (el) el.onchange = async () => {
        ctx.state.status = root.querySelector("#cxFinStatus")?.value || "";
        ctx.state.doctor_id = root.querySelector("#cxFinDoctor")?.value || "";
        ctx.state.method = root.querySelector("#cxFinMethod")?.value || "";
        ctx.state.page = 1;
        await refreshBilling(ctx);
      };
    });
    root.querySelector("#cxBillPay")?.addEventListener("click", () => {
      const unpaid = (ctx.allRows || []).find((r) => r.balance > 0);
      if (!unpaid) ctx.showNotice("لا توجد فواتير بمتبقي");
      else promptPay(ctx, unpaid.id, unpaid.balance);
    });
    root.querySelector("#cxBillPayEmpty")?.addEventListener("click", () => root.querySelector("#cxBillPay")?.click());
    root.querySelector("#cxFinDrawerClose")?.addEventListener("click", () => {
      ctx.drawerInvoice = null;
      paintBilling(ctx);
    });
    root.querySelector("#cxFinBackdrop")?.addEventListener("click", () => {
      ctx.drawerInvoice = null;
      paintBilling(ctx);
    });
    root.querySelectorAll("[data-pay],[data-drawer-pay]").forEach((btn) => {
      btn.onclick = () => promptPay(ctx, btn.dataset.pay || btn.dataset.drawerPay, Number(btn.dataset.bal));
    });
    root.querySelectorAll("[data-drawer-refund]").forEach((btn) => {
      btn.onclick = () => promptRefund(ctx, btn.dataset.drawerRefund, Number(btn.dataset.paid));
    });
    root.querySelectorAll("[data-open-inv],[data-act]").forEach((btn) => {
      btn.onclick = async () => {
        const act = btn.dataset.act;
        const id = btn.dataset.id || btn.dataset.openInv;
        if (act === "pay") promptPay(ctx, id, Number(btn.dataset.bal));
        else if (act === "refund") promptRefund(ctx, id, Number(btn.dataset.paid));
        else if (act === "print" || act === "open") openInvoiceDrawer(ctx, id);
        else openInvoiceDrawer(ctx, id);
      };
    });
    root.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = root.querySelector(`[data-for="${btn.dataset.menu}"]`);
        root.querySelectorAll(".cx-fin-menu").forEach((m) => {
          if (m !== menu) m.hidden = true;
        });
        if (menu) menu.hidden = !menu.hidden;
      };
    });
    root.querySelector("#cxFinPrev")?.addEventListener("click", async () => {
      if (ctx.state.page > 1) {
        ctx.state.page -= 1;
        await refreshBilling(ctx);
      }
    });
    root.querySelector("#cxFinNext")?.addEventListener("click", async () => {
      if (ctx.state.page < (ctx.pagination?.pages || 1)) {
        ctx.state.page += 1;
        await refreshBilling(ctx);
      }
    });
  }

  async function refreshBilling(ctx) {
    await loadBilling(ctx);
    paintBilling(ctx);
  }

  async function renderBilling(state, root, helpers) {
    const ctx = {
      state: {
        day: state.day,
        quickDate: "month",
        defaultQuickDate: "month",
        q: "",
        status: "",
        doctor_id: "",
        method: "",
        page: 1,
        per_page: 25,
        extraOpen: false,
      },
      root,
      api: helpers.api,
      esc: helpers.esc,
      money: helpers.money,
      showNotice: helpers.showNotice,
      openModal: helpers.openModal,
    };
    root.innerHTML = `<div class="cx-fin cx-fin--billing">${UI.skeletonKpis(6)}<div class="cx-skeleton-block" style="height:220px;border-radius:16px;margin-top:12px"></div></div>`;
    try {
      await refreshBilling(ctx);
    } catch (err) {
      root.innerHTML = UI.emptyHtml(err.message || String(err));
    }
  }

  /* ── Expenses ── */
  const EXPENSE_CATS = ["إيجار", "رواتب", "كهرباء", "مولدة", "إنترنت", "مواد طبية", "صيانة", "تنظيف", "تسويق", "نقل", "ضيافة", "مصاريف إدارية", "أخرى"];

  async function renderExpenses(state, root, helpers) {
    const ctx = {
      state: { day: state.day, quickDate: "today", q: "", category: "", page: 1, per_page: 25, extraOpen: false },
      root,
      api: helpers.api,
      esc: helpers.esc,
      money: helpers.money,
      showNotice: helpers.showNotice,
      openModal: helpers.openModal,
    };
    root.innerHTML = `<div class="cx-fin">${UI.skeletonKpis(4)}</div>`;
    try {
      const range = UI.resolveDateRange(ctx.state.quickDate, ctx.state.day, ctx.state.from, ctx.state.to);
      const qs = range.fetchAll ? "" : `?date=${encodeURIComponent(range.day)}`;
      let rows = await ctx.api(`/clinics/api/expenses${qs}`);
      rows = (Array.isArray(rows) ? rows : []).filter((r) => UI.inRange(r.expense_date, range.from, range.to));
      if (ctx.state.q) {
        const q = ctx.state.q.toLowerCase();
        rows = rows.filter((r) => (r.title || "").toLowerCase().includes(q) || (r.category || "").toLowerCase().includes(q));
      }
      if (ctx.state.category) rows = rows.filter((r) => r.category === ctx.state.category);
      const today = UI.localDateStr(new Date());
      const monthStart = today.slice(0, 8) + "01";
      const todaySum = rows.filter((r) => r.expense_date === today).reduce((s, r) => s + Number(r.amount || 0), 0);
      const monthSum = rows.filter((r) => r.expense_date >= monthStart).reduce((s, r) => s + Number(r.amount || 0), 0);
      const kpis = [
        { label: "مصروفات اليوم", value: moneyFmt(todaySum), theme: "orange", icon: "fa-receipt" },
        { label: "هذا الشهر", value: moneyFmt(monthSum), theme: "blue", icon: "fa-calendar" },
        { label: "عدد اليوم", value: rows.filter((r) => r.expense_date === today).length, theme: "teal", icon: "fa-list" },
        { label: "إجمالي الفترة", value: moneyFmt(rows.reduce((s, r) => s + Number(r.amount || 0), 0)), theme: "purple", icon: "fa-coins" },
      ];
      const pg = UI.paginate(rows, ctx.state.page, ctx.state.per_page);
      root.innerHTML = `
        <div class="cx-fin">
          ${UI.headerHtml(ctx, {
            title: "المصروفات",
            desc: "تسجيل ومتابعة مصروفات التشغيل",
            icon: "fa-receipt",
            breadcrumb: "المالية / المصروفات",
            actions: [{ id: "cxExpAdd", label: "مصروف جديد", icon: "fa-plus", primary: true }],
          })}
          <div class="cx-fin-kpis">${UI.kpisHtml(kpis)}</div>
          ${UI.filtersShell(
            ctx,
            `<input type="search" class="cx-input" id="cxFinSearch" placeholder="بحث…" value="${ctx.esc(ctx.state.q || "")}">
             <select class="cx-select" id="cxExpCat"><option value="">كل التصنيفات</option>
             ${EXPENSE_CATS.map((c) => `<option value="${c}">${c}</option>`).join("")}</select>`,
            "",
            ctx.state,
            ["category"]
          )}
          ${UI.tableCard(
            `<table class="cx-table"><thead><tr><th>العنوان</th><th>التصنيف</th><th>المبلغ</th><th>الطريقة</th><th>التاريخ</th></tr></thead>
            <tbody>${pg.items.map((e) => `<tr><td>${ctx.esc(e.title)}</td><td>${ctx.esc(e.category)}</td><td class="cx-money">${ctx.money(e.amount)}</td><td>${ctx.esc(UI.PAYMENT_METHODS[e.payment_method] || e.payment_method)}</td><td>${ctx.esc(e.expense_date)}</td></tr>`).join("") || `<tr><td colspan="5">${UI.emptyHtml("لا مصروفات", "مصروف جديد", "cxExpAdd")}</td></tr>`}</tbody></table>`,
            UI.pagerHtml(ctx, pg.pagination)
          )}
        </div>`;
      root.querySelector("#cxExpAdd")?.addEventListener("click", () => {
        ctx.openModal(
          "مصروف جديد",
          `
          <div class="cx-field"><label>العنوان *</label><input class="cx-input" id="ex_title"></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>التصنيف</label><select class="cx-select" id="ex_cat">${EXPENSE_CATS.map((c) => `<option value="${c}">${c}</option>`).join("")}</select></div>
            <div class="cx-field"><label>المبلغ *</label><input class="cx-input" id="ex_amt" type="number"></div>
          </div>
          <div class="cx-field"><label>طريقة الدفع</label><select class="cx-select" id="ex_method">${Object.entries(UI.PAYMENT_METHODS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
          <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="ex_notes"></textarea></div>`,
          async () => {
            await ctx.api("/clinics/api/expenses", {
              method: "POST",
              body: JSON.stringify({
                title: document.getElementById("ex_title").value,
                category: document.getElementById("ex_cat").value,
                amount: document.getElementById("ex_amt").value,
                payment_method: document.getElementById("ex_method").value,
                notes: document.getElementById("ex_notes").value,
                expense_date: state.day,
              }),
            });
            await renderExpenses(state, root, helpers);
          }
        );
      });
    } catch (err) {
      root.innerHTML = UI.emptyHtml(err.message || String(err));
    }
  }

  /* ── Cash ── */
  async function renderCash(state, root, helpers) {
    const ctx = { root, api: helpers.api, esc: helpers.esc, money: helpers.money, showNotice: helpers.showNotice, openModal: helpers.openModal };
    try {
      const sessions = await ctx.api("/clinics/api/cash-sessions");
      const list = Array.isArray(sessions) ? sessions : [];
      const open = list.find((s) => s.status === "open");
      const kpis = open
        ? [
            { label: "الرصيد الافتتاحي", value: ctx.money(open.opening_cash), theme: "teal", icon: "fa-wallet" },
            { label: "المتوقع", value: open.expected_cash != null ? ctx.money(open.expected_cash) : "—", theme: "blue", icon: "fa-calculator" },
            { label: "الحالة", value: "مفتوحة", theme: "green", icon: "fa-door-open" },
          ]
        : [{ label: "لا جلسة مفتوحة", value: "—", theme: "orange", icon: "fa-lock" }];
      root.innerHTML = `
        <div class="cx-fin">
          ${UI.headerHtml(ctx, {
            title: "الصندوق",
            desc: "جلسات الصندوق والمقبوضات والمصروفات",
            icon: "fa-cash-register",
            breadcrumb: "المالية / الصندوق",
            actions: open
              ? [{ id: "cxCashClose", label: "إغلاق الجلسة", icon: "fa-lock" }]
              : [{ id: "cxCashOpen", label: "فتح جلسة", icon: "fa-unlock", primary: true }],
          })}
          <div class="cx-fin-kpis">${UI.kpisHtml(kpis)}</div>
          ${open ? `<article class="cx-fin-session"><strong>جلسة مفتوحة</strong><span>افتتاح ${ctx.esc(open.opened_at?.replace("T", " ").slice(0, 16) || "")}</span><span>افتتاحي ${ctx.money(open.opening_cash)}</span></article>` : UI.emptyHtml("لا توجد جلسة صندوق مفتوحة", "فتح جلسة", "cxCashOpen")}
          ${UI.tableCard(
            `<table class="cx-table"><thead><tr><th>التاريخ</th><th>افتتاحي</th><th>متوقع</th><th>إغلاق</th><th>الحالة</th><th></th></tr></thead>
            <tbody>${list.map((s) => `<tr><td>${ctx.esc(s.business_date)}</td><td class="cx-money">${ctx.money(s.opening_cash)}</td><td class="cx-money">${s.expected_cash == null ? "—" : ctx.money(s.expected_cash)}</td><td class="cx-money">${s.closing_cash == null ? "—" : ctx.money(s.closing_cash)}</td><td>${ctx.esc(s.status)}</td><td>${s.status === "open" ? `<button class="cx-btn cx-btn--sm" data-close="${s.id}">إغلاق</button>` : "—"}</td></tr>`).join("")}</tbody></table>`,
            ""
          )}
        </div>`;
      root.querySelector("#cxCashOpen")?.addEventListener("click", () => {
        ctx.openModal("فتح جلسة صندوق", `
          <div class="cx-field"><label>الرصيد الافتتاحي</label><input class="cx-input" id="cs_open" type="number" value="0"></div>
          <div class="cx-field"><label>ملاحظة</label><input class="cx-input" id="cs_notes"></div>`, async () => {
          await ctx.api("/clinics/api/cash-sessions", {
            method: "POST",
            body: JSON.stringify({
              opening_cash: document.getElementById("cs_open").value,
              business_date: state.day,
              notes: document.getElementById("cs_notes").value,
            }),
          });
          await renderCash(state, root, helpers);
        });
      });
      root.querySelector("#cxCashClose")?.addEventListener("click", () => {
        if (!open) return;
        ctx.openModal("إغلاق الصندوق", `
          <div class="cx-field"><label>الرصيد الفعلي</label><input class="cx-input" id="cs_close" type="number" placeholder="اتركه للمتوقع"></div>
          <div class="cx-field"><label>ملاحظة</label><input class="cx-input" id="cs_close_notes"></div>`, async () => {
          const val = document.getElementById("cs_close").value;
          await ctx.api(`/clinics/api/cash-sessions/${open.id}/close`, {
            method: "POST",
            body: JSON.stringify({
              closing_cash: val === "" ? undefined : val,
              notes: document.getElementById("cs_close_notes").value,
            }),
          });
          await renderCash(state, root, helpers);
        });
      });
      root.querySelectorAll("[data-close]").forEach((btn) => {
        btn.onclick = () => root.querySelector("#cxCashClose")?.click();
      });
    } catch (err) {
      root.innerHTML = UI.emptyHtml(err.message || String(err));
    }
  }

  /* ── Settlements ── */
  async function renderSettlements(state, root, helpers) {
    const ctx = { root, api: helpers.api, esc: helpers.esc, money: helpers.money, showNotice: helpers.showNotice, openModal: helpers.openModal };
    try {
      const [rows, doctors] = await Promise.all([ctx.api("/clinics/api/settlements"), ctx.api("/clinics/api/doctors?active=1")]);
      const list = Array.isArray(rows) ? rows : [];
      const gross = list.reduce((s, r) => s + Number(r.gross_revenue || 0), 0);
      const docShare = list.reduce((s, r) => s + Number(r.doctor_share || 0), 0);
      const paid = list.reduce((s, r) => s + Number(r.paid_amount || 0), 0);
      const bal = list.reduce((s, r) => s + Number(r.balance || 0), 0);
      const kpis = [
        { label: "إيرادات الأطباء", value: moneyFmt(gross), theme: "teal", icon: "fa-chart-line" },
        { label: "حصص الأطباء", value: moneyFmt(docShare), theme: "blue", icon: "fa-user-doctor" },
        { label: "المدفوع", value: moneyFmt(paid), theme: "green", icon: "fa-hand-holding-dollar" },
        { label: "المتبقي", value: moneyFmt(bal), theme: "orange", icon: "fa-hourglass-half" },
      ];
      root.innerHTML = `
        <div class="cx-fin">
          ${UI.headerHtml(ctx, {
            title: "تسوية الأطباء",
            desc: "حصص الأطباء والمدفوعات للفترة",
            icon: "fa-handshake",
            breadcrumb: "المالية / التسوية",
            actions: [{ id: "cxSetAdd", label: "تسوية جديدة", icon: "fa-plus", primary: true }],
          })}
          <div class="cx-fin-kpis">${UI.kpisHtml(kpis)}</div>
          ${UI.tableCard(
            `<table class="cx-table"><thead><tr><th>الطبيب</th><th>الفترة</th><th>الإيراد</th><th>حصة الطبيب</th><th>المدفوع</th><th>المتبقي</th><th>الحالة</th></tr></thead>
            <tbody>${list.map((s) => `<tr><td>${ctx.esc(s.doctor_name)}</td><td>${ctx.esc(s.period_from)} → ${ctx.esc(s.period_to)}</td><td class="cx-money">${ctx.money(s.gross_revenue)}</td><td class="cx-money">${ctx.money(s.doctor_share)}</td><td class="cx-money">${ctx.money(s.paid_amount)}</td><td class="cx-money">${ctx.money(s.balance)}</td><td>${badge(SETTLEMENT_STATUS, s.status)}</td></tr>`).join("") || `<tr><td colspan="7">${UI.emptyHtml("لا تسويات", "تسوية جديدة", "cxSetAdd")}</td></tr>`}</tbody></table>`,
            ""
          )}
        </div>`;
      root.querySelector("#cxSetAdd")?.addEventListener("click", () => {
        const end = state.day;
        const start = end.slice(0, 8) + "01";
        ctx.openModal(
          "تسوية طبيب",
          `
          <div class="cx-field"><label>الطبيب</label><select class="cx-select" id="s_doc">${(doctors || []).map((d) => `<option value="${d.id}">${ctx.esc(d.full_name)} (${d.commission_pct}%)</option>`).join("")}</select></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>من</label><input class="cx-input" type="date" id="s_from" value="${start}"></div>
            <div class="cx-field"><label>إلى</label><input class="cx-input" type="date" id="s_to" value="${end}"></div>
          </div>
          <div class="cx-field"><label>المبلغ المدفوع الآن</label><input class="cx-input" type="number" id="s_paid" value="0"></div>`,
          async () => {
            await ctx.api("/clinics/api/settlements", {
              method: "POST",
              body: JSON.stringify({
                doctor_id: document.getElementById("s_doc").value,
                period_from: document.getElementById("s_from").value,
                period_to: document.getElementById("s_to").value,
                paid_amount: document.getElementById("s_paid").value,
              }),
            });
            await renderSettlements(state, root, helpers);
          }
        );
      });
    } catch (err) {
      root.innerHTML = UI.emptyHtml(err.message || String(err));
    }
  }

  window.ClinicsFinance = {
    renderBilling,
    renderExpenses,
    renderCash,
    renderSettlements,
  };
})();
