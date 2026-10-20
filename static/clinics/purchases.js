(() => {
  const ui = { q: "", supplier_id: "", invoice_status: "", receipt_status: "", payment_status: "", quick: "", page: 1, perPage: 25, timer: null };
  let floatingDismiss = null;

  const invoiceLabels = { draft: "مسودة", approved: "معتمدة", cancelled: "ملغاة" };
  const receiptLabels = { pending: "لم تستلم", partial: "مستلمة جزئياً", complete: "مستلمة بالكامل" };
  const paymentLabels = { unpaid: "غير مدفوعة", partial: "مدفوعة جزئياً", paid: "مدفوعة بالكامل", overdue: "متأخرة", cancelled: "ملغاة" };
  const paymentMethods = { cash: "نقدي", treasury: "صندوق", transfer: "تحويل بنكي", card: "بطاقة", zaincash: "زين كاش", electronic: "دفع إلكتروني", other: "أخرى" };
  const purchaseTypes = { cash: "نقدي", credit: "آجل", partial: "جزئي" };
  const returnReasons = { expiring: "منتهي أو قريب الانتهاء", damaged: "تالف", mismatch: "غير مطابق", excess: "كمية زائدة", order_error: "خطأ في الطلب", batch_issue: "مشكلة في Batch", other: "أخرى" };
  const requestStatuses = { draft: "مسودة", pending: "بانتظار الموافقة", approved: "معتمد", rejected: "مرفوض", converted: "تم التحويل" };
  const priorities = { low: "منخفضة", normal: "عادية", high: "عالية", urgent: "عاجلة" };
  let perms = { view: true, create: true, edit: true, approve: true, cancel: true, receive: true, return: true, pay: true, payment_view: true, cost_view: true, export: true, request_create: true, request_approve: true };

  async function loadPerms(ctx) {
    try { perms = { ...perms, ...((await ctx.api("/clinics/api/purchases/meta")).permissions || {}) }; } catch (_) {}
  }
  function can(p) { return perms[p] !== false; }
  function costMoney(ctx, v) { return can("cost_view") ? ctx.money(v) : "—"; }

  function qty(v) { return Number(v || 0).toLocaleString("ar-IQ", { maximumFractionDigits: 3 }); }
  function today() { return new Date().toISOString().slice(0, 10); }

  function badge(cls, text) { return `<span class="cxp-badge cxp-badge--${cls}">${text}</span>`; }
  function invoiceBadge(s) { return badge(s === "cancelled" ? "danger" : s === "draft" ? "muted" : "teal", invoiceLabels[s] || s); }
  function receiptBadge(s) { return badge(s === "complete" ? "success" : s === "partial" ? "info" : "warning", receiptLabels[s] || s); }
  function paymentBadge(s) { return badge(s === "paid" ? "success" : s === "overdue" ? "danger" : s === "partial" ? "info" : "warning", paymentLabels[s] || s); }

  function header(title, desc, actions = "") {
    return `<section class="cxi-header">
      <div><div class="cxi-breadcrumb">الرئيسية <i class="fa fa-angle-left"></i> المخزون والمشتريات <i class="fa fa-angle-left"></i> ${title}</div>
      <h1>${title}</h1><p>${desc}</p></div>
      <div class="cxi-header__actions">${actions}</div>
    </section>`;
  }

  function closeMenu() {
    document.querySelector(".cxi-floating-menu")?.remove();
    if (floatingDismiss) document.removeEventListener("click", floatingDismiss);
    floatingDismiss = null;
  }

  function openMenu(trigger, items) {
    closeMenu();
    const menu = document.createElement("div");
    menu.className = "cxi-floating-menu";
    menu.innerHTML = items.map(i => i.href
      ? `<a href="${i.href}"><i class="fa fa-${i.icon}"></i><span>${i.label}</span></a>`
      : `<button type="button" data-act="${i.id}"><i class="fa fa-${i.icon}"></i><span>${i.label}</span></button>`
    ).join("");
    document.body.appendChild(menu);
    const rect = trigger.getBoundingClientRect();
    const w = 210, h = menu.offsetHeight || 200;
    menu.style.top = `${Math.min(window.innerHeight - h - 8, rect.bottom + 6)}px`;
    menu.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, rect.right - w))}px`;
    menu.querySelectorAll("[data-act]").forEach(btn => {
      btn.onclick = () => { closeMenu(); items.find(x => x.id === btn.dataset.act)?.onClick?.(); };
    });
    window.setTimeout(() => {
      floatingDismiss = e => { if (!menu.contains(e.target) && !trigger.contains(e.target)) closeMenu(); };
      document.addEventListener("click", floatingDismiss);
    }, 0);
  }

  function buildQuery() {
    const p = new URLSearchParams({ page: ui.page, per_page: ui.perPage });
    ["q", "supplier_id", "invoice_status", "receipt_status", "payment_status", "quick"].forEach(k => { if (ui[k]) p.set(k, ui[k]); });
    return p.toString();
  }

  async function renderList(root, ctx) {
    await loadPerms(ctx);
    const [data, suppliers, report] = await Promise.all([
      ctx.api(`/clinics/api/purchases?${buildQuery()}`),
      ctx.api("/clinics/api/suppliers"),
      ctx.api("/clinics/api/purchases/reports/summary").catch(() => null),
    ]);
    const k = data.kpis || {};
    const rows = data.items || [];
    const pag = data.pagination || { page: 1, pages: 1, total: 0, per_page: 25 };

    root.innerHTML = `<div class="cxi-page cxp-page">
      ${header("المشتريات", "إدارة مشتريات العيادة واستلام المواد ومتابعة الموردين والمدفوعات.",
        `${can("create") ? `<button class="cx-btn" id="cxpQuick"><i class="fa fa-bolt"></i> شراء سريع</button>` : ""}
         ${can("request_create") ? `<button class="cx-btn" id="cxpRequest"><i class="fa fa-clipboard-list"></i> طلب شراء</button>` : ""}
         ${can("receive") ? `<button class="cx-btn" id="cxpReceive"><i class="fa fa-truck-ramp-box"></i> استلام مواد</button>` : ""}
         ${can("export") ? `<button class="cx-btn" id="cxpExport"><i class="fa fa-file-export"></i> تقارير</button><a class="cx-btn" href="/clinics/purchases/reports"><i class="fa fa-chart-column"></i> تحليل</a>` : ""}
         ${can("create") ? `<a class="cx-btn cx-btn--primary" href="/clinics/purchases/new"><i class="fa fa-plus"></i> فاتورة شراء</a>` : ""}`)}
      <div class="cxi-kpis">
        ${[["calendar-day","مشتريات اليوم",ctx.money(k.purchases_today),"",""],["calendar","مشتريات الشهر",ctx.money(k.purchases_month),"",""],["hand-holding-dollar","المستحق للموردين",ctx.money(k.supplier_payable),"رصيد مفتوح","payable"],["file-circle-xmark","فواتير غير مدفوعة",k.unpaid_count,"فاتورة","unpaid"],["hourglass-half","بانتظار الاستلام",k.pending_receipt,"فاتورة","pending"],["boxes-packing","مستلمة جزئياً",k.partial_receipt,"فاتورة","partial"]]
          .map(x => `<button class="cxi-kpi cxi-kpi--${x[4] || "total"}" data-kpi="${x[4]}"><i class="fa fa-${x[0]}"></i><span>${x[1]}</span><strong>${x[2]}</strong><small>${x[3]}</small></button>`).join("")}
      </div>
      ${report ? `<section class="cxi-panel cxp-report"><div class="cxi-panel-title"><h2>تحليل سريع</h2></div><div class="cxp-report-grid">
        <article><span>أكثر مورد</span><strong>${ctx.esc(report.top_supplier?.name || "—")}</strong><small>${report.top_supplier ? ctx.money(report.top_supplier.total) : ""}</small></article>
        <article><span>أكثر صنف شراءً</span><strong>${ctx.esc(report.top_item?.name || "—")}</strong><small>${report.top_item ? ctx.money(report.top_item.total) : ""}</small></article>
        <article><span>مقارنة الشهر</span><strong>${report.month_change_pct != null ? `${report.month_change_pct > 0 ? "+" : ""}${report.month_change_pct}%` : "—"}</strong><small>مقابل الشهر السابق</small></article>
        <article><span>فواتير الشهر</span><strong>${report.purchase_count_month || 0}</strong><small>إجمالي ${ctx.money(report.month_total || 0)}</small></article>
      </div></section>` : ""}
      <section class="cxi-panel">
        <div class="cxi-filters cxp-filters">
          <label class="cxi-search"><i class="fa fa-magnifying-glass"></i><input id="cxpSearch" value="${ctx.esc(ui.q)}" placeholder="بحث برقم الفاتورة / المورد / الصنف"></label>
          <select class="cx-select" id="cxpSupplier"><option value="">كل الموردين</option>${suppliers.map(s => `<option value="${s.id}" ${String(s.id) === ui.supplier_id ? "selected" : ""}>${ctx.esc(s.name)}</option>`).join("")}</select>
          <select class="cx-select" id="cxpInvoiceStatus"><option value="">حالة الفاتورة</option>${Object.entries(invoiceLabels).map(([v,l]) => `<option value="${v}" ${v === ui.invoice_status ? "selected" : ""}>${l}</option>`).join("")}</select>
          <select class="cx-select" id="cxpReceiptStatus"><option value="">حالة الاستلام</option>${Object.entries(receiptLabels).map(([v,l]) => `<option value="${v}" ${v === ui.receipt_status ? "selected" : ""}>${l}</option>`).join("")}</select>
          <select class="cx-select" id="cxpPaymentStatus"><option value="">حالة الدفع</option>${Object.entries(paymentLabels).filter(([v]) => v !== "cancelled").map(([v,l]) => `<option value="${v}" ${v === ui.payment_status ? "selected" : ""}>${l}</option>`).join("")}</select>
          <button class="cx-btn cx-btn--ghost" id="cxpRefresh" title="تحديث"><i class="fa fa-rotate"></i></button>
          <button class="cx-btn cx-btn--ghost" id="cxpClear">مسح</button>
        </div>
        <div class="cxi-quick">
          ${[["","الكل"],["today","اليوم"],["yesterday","أمس"],["week","آخر 7 أيام"],["month","هذا الشهر"],["last_month","الشهر الماضي"]]
            .map(([v,l]) => `<button class="${ui.quick === v ? "active" : ""}" data-quick="${v}">${l}</button>`).join("")}
        </div>
        <div class="cx-table-wrap"><table class="cx-table cxi-table cxp-table"><thead><tr>
          <th>رقم الفاتورة</th><th>فاتورة المورد</th><th>المورد</th><th>التاريخ</th><th>البنود</th>
          <th>الإجمالي</th><th>المدفوع</th><th>المتبقي</th><th>الدفع</th><th>الاستلام</th><th>الفاتورة</th><th>الموظف</th><th></th>
        </tr></thead><tbody>
          ${rows.map(p => `<tr>
            <td><a class="cxi-item-link" href="/clinics/purchases/${p.id}"><b>${ctx.esc(p.purchase_number)}</b></a></td>
            <td dir="ltr">${ctx.esc(p.supplier_invoice_no || "—")}</td>
            <td>${ctx.esc(p.supplier_name)}</td>
            <td>${ctx.esc(p.purchase_date)}</td>
            <td>${p.items_count || p.items?.length || 0}</td>
            <td class="cx-money">${costMoney(ctx, p.total)}</td>
            <td class="cx-money">${costMoney(ctx, p.paid)}</td>
            <td class="cx-money">${costMoney(ctx, p.balance)}</td>
            <td>${paymentBadge(p.payment_status)}</td>
            <td>${receiptBadge(p.receipt_status)}</td>
            <td>${invoiceBadge(p.invoice_status)}</td>
            <td>${ctx.esc(p.created_by_name || "—")}</td>
            <td><button type="button" class="cxi-menu-trigger" data-menu="${p.id}"><i class="fa fa-ellipsis"></i></button></td>
          </tr>`).join("") || `<tr><td colspan="13"><div class="cx-empty"><i class="fa fa-cart-shopping"></i><b>لا توجد فواتير شراء</b><span>ابدأ بإنشاء فاتورة شراء جديدة.</span></div></td></tr>`}
        </tbody></table></div>
        <footer class="cxi-pagination"><span>${pag.total ? `${(pag.page-1)*pag.per_page+1}-${Math.min(pag.page*pag.per_page,pag.total)} من ${pag.total}` : "0 نتيجة"}</span>
          <div><button class="cx-btn cx-btn--sm" id="cxpPrev" ${pag.page <= 1 ? "disabled" : ""}>السابق</button><button class="cx-btn cx-btn--sm" id="cxpNext" ${pag.page >= pag.pages ? "disabled" : ""}>التالي</button></div>
        </footer>
      </section>
    </div>`;

    const byId = id => rows.find(r => r.id === Number(id));
    const apply = () => renderList(root, ctx);
    const setFilter = (patch) => { Object.assign(ui, patch, { page: 1 }); apply(); };

    document.getElementById("cxpSearch").oninput = e => { clearTimeout(ui.timer); ui.timer = setTimeout(() => setFilter({ q: e.target.value }), 350); };
    document.getElementById("cxpSupplier").onchange = e => setFilter({ supplier_id: e.target.value });
    document.getElementById("cxpInvoiceStatus").onchange = e => setFilter({ invoice_status: e.target.value });
    document.getElementById("cxpReceiptStatus").onchange = e => setFilter({ receipt_status: e.target.value });
    document.getElementById("cxpPaymentStatus").onchange = e => setFilter({ payment_status: e.target.value });
    document.getElementById("cxpRefresh").onclick = apply;
    document.getElementById("cxpClear").onclick = () => { Object.assign(ui, { q: "", supplier_id: "", invoice_status: "", receipt_status: "", payment_status: "", quick: "", page: 1 }); apply(); };
    root.querySelectorAll("[data-quick]").forEach(b => b.onclick = () => setFilter({ quick: b.dataset.quick }));
    document.getElementById("cxpPrev").onclick = () => { ui.page--; apply(); };
    document.getElementById("cxpNext").onclick = () => { ui.page++; apply(); };
    root.querySelectorAll("[data-kpi]").forEach(b => {
      b.onclick = () => {
        const k = b.dataset.kpi;
        if (k === "unpaid") setFilter({ payment_status: "unpaid" });
        else if (k === "pending") setFilter({ receipt_status: "pending" });
        else if (k === "partial") setFilter({ receipt_status: "partial" });
        else if (k === "payable") setFilter({ payment_status: "" });
      };
    });

    root.querySelectorAll("[data-menu]").forEach(btn => {
      btn.onclick = () => {
        const p = byId(btn.dataset.menu);
        if (!p) return;
        openMenu(btn, [
          { href: `/clinics/purchases/${p.id}`, icon: "eye", label: "عرض الفاتورة" },
          ...(can("create") ? [{ id: "copy", icon: "copy", label: "نسخ الفاتورة", onClick: async () => {
            const r = await ctx.api(`/clinics/api/purchases/${p.id}/copy`, { method: "POST", body: "{}" });
            ctx.showNotice("تم نسخ الفاتورة", false);
            location.href = `/clinics/purchases/${r.id}`;
          }}] : []),
          ...(can("edit") && p.receipt_status === "pending" && !p.paid ? [{ href: `/clinics/purchases/${p.id}/edit`, icon: "pen", label: "تعديل" }] : []),
          ...(can("approve") && p.invoice_status === "draft" ? [{ id: "approve", icon: "check", label: "اعتماد الفاتورة", onClick: async () => {
            await ctx.api(`/clinics/api/purchases/${p.id}/approve`, { method: "POST", body: "{}" });
            ctx.showNotice("تم اعتماد الفاتورة", false); apply();
          }}] : []),
          ...(can("receive") && p.receipt_status !== "complete" && p.invoice_status !== "draft" ? [{ id: "recv", icon: "truck-ramp-box", label: "استلام مواد", onClick: () => openReceiveModal(p, ctx, apply) }] : []),
          ...(can("return") && p.receipt_status !== "pending" ? [{ id: "ret", icon: "rotate-left", label: "مرتجع للمورد", onClick: () => openReturnModal(p, ctx, apply) }] : []),
          ...(can("pay") && p.balance > 0 && p.invoice_status !== "draft" ? [{ id: "pay", icon: "money-bill-wave", label: "تسجيل دفعة", onClick: () => openPaymentModal(p, ctx, apply) }] : []),
          { id: "stmt", icon: "file-invoice", label: "كشف المورد", onClick: async () => {
            const d = await ctx.api(`/clinics/api/suppliers/${p.supplier_id}/statement`);
            ctx.openModal(`كشف ${d.supplier.name}`, `<div class="cxi-statement"><div class="cxi-balance"><span>الرصيد المستحق</span><strong>${costMoney(ctx, d.outstanding_balance)}</strong></div>${(d.lines||[]).map(l => `<div><span>${ctx.esc(l.date)} · ${ctx.esc(l.reference)}</span><b>${costMoney(ctx, l.balance)}</b></div>`).join("") || "لا حركات"}<div style="margin-top:12px"><a class="cx-btn cx-btn--sm" href="/clinics/suppliers/${p.supplier_id}/statement/print" target="_blank"><i class="fa fa-print"></i> طباعة</a></div></div>`, async () => {}, { saveLabel: "إغلاق" });
          }},
          ...(can("cancel") && p.invoice_status !== "cancelled" && p.receipt_status === "pending" ? [{ id: "cancel", icon: "ban", label: "إلغاء الفاتورة", onClick: async () => {
            if (!confirm("إلغاء هذه الفاتورة؟")) return;
            await ctx.api(`/clinics/api/purchases/${p.id}/cancel`, { method: "POST", body: "{}" });
            ctx.showNotice("تم إلغاء الفاتورة", false); apply();
          }}] : []),
        ].filter(Boolean));
      };
    });

    document.getElementById("cxpQuick")?.addEventListener("click", () => openQuickPurchase(ctx, apply));
    document.getElementById("cxpReceive")?.addEventListener("click", () => {
      const pending = rows.filter(r => r.receipt_status !== "complete");
      if (!pending.length) return ctx.showNotice("لا توجد فواتير بانتظار الاستلام");
      ctx.openModal("اختر فاتورة للاستلام", `<label><span>الفاتورة</span><select class="cx-select" id="cxpPick">${pending.map(p => `<option value="${p.id}">${ctx.esc(p.purchase_number)} — ${ctx.esc(p.supplier_name)}</option>`).join("")}</select></label>`, async () => {
        openReceiveModal(byId(document.getElementById("cxpPick").value), ctx, apply);
      }, { saveLabel: "متابعة", skipRender: true });
    });
    document.getElementById("cxpRequest")?.addEventListener("click", () => openPurchaseRequests(ctx, apply));
    document.getElementById("cxpExport")?.addEventListener("click", () => openReportsModal(ctx));
  }

  function exportCsv(rows, ctx) {
    if (!rows.length) return ctx.showNotice("لا بيانات للتصدير");
    const header = ["رقم الفاتورة","فاتورة المورد","المورد","التاريخ","الإجمالي","المدفوع","المتبقي","حالة الدفع","حالة الاستلام"];
    const lines = rows.map(p => [p.purchase_number, p.supplier_invoice_no, p.supplier_name, p.purchase_date, p.total, p.paid, p.balance, paymentLabels[p.payment_status], receiptLabels[p.receipt_status]]);
    const csv = "\uFEFF" + [header, ...lines].map(r => r.map(c => `"${String(c||"").replace(/"/g,'""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `purchases-${today()}.csv`;
    a.click();
  }

  async function openReportsModal(ctx) {
    const [summary, unpaid, bySupplier] = await Promise.all([
      ctx.api("/clinics/api/purchases/reports/summary").catch(() => ({})),
      ctx.api("/clinics/api/purchases/reports/unpaid").catch(() => []),
      ctx.api("/clinics/api/purchases/reports/by-supplier").catch(() => []),
    ]);
    ctx.openModal("تقارير المشتريات", `<div class="cxp-reports">
      <section class="cxp-summary">
        <article><span>مشتريات الشهر</span><strong>${ctx.money(summary.month_total || 0)}</strong>${summary.month_change_pct != null ? `<small>${summary.month_change_pct > 0 ? "+" : ""}${summary.month_change_pct}% عن الشهر السابق</small>` : ""}</article>
        <article><span>ذمم الموردين</span><strong>${ctx.money(summary.supplier_payable || 0)}</strong></article>
        <article><span>بانتظار الاستلام</span><strong>${summary.pending_receipt_count || 0}</strong></article>
        <article><span>أعلى مورد</span><strong>${ctx.esc(summary.top_supplier?.name || "—")}</strong><small>${summary.top_supplier ? ctx.money(summary.top_supplier.total) : ""}</small></article>
      </section>
      <section class="cxi-panel"><div class="cxi-panel-title"><h2>فواتير غير مدفوعة (${unpaid.length})</h2></div>
        ${unpaid.length ? `<div class="cx-table-wrap" style="max-height:180px;overflow:auto"><table class="cx-table"><thead><tr><th>الفاتورة</th><th>المورد</th><th>المتبقي</th><th>الاستحقاق</th></tr></thead><tbody>
          ${unpaid.slice(0, 15).map(r => `<tr><td><a href="/clinics/purchases/${r.id}">${ctx.esc(r.purchase_number)}</a></td><td>${ctx.esc(r.supplier_name)}</td><td class="cx-money">${ctx.money(r.balance)}</td><td>${ctx.esc(r.due_date || "—")}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="cx-empty">لا فواتير مستحقة</div>`}
      </section>
      <section class="cxi-panel"><div class="cxi-panel-title"><h2>المشتريات حسب المورد</h2></div>
        ${bySupplier.length ? `<div class="cx-table-wrap" style="max-height:180px;overflow:auto"><table class="cx-table"><thead><tr><th>المورد</th><th>عدد الفواتير</th><th>الإجمالي</th><th>المتبقي</th></tr></thead><tbody>
          ${bySupplier.slice(0, 15).map(r => `<tr><td>${ctx.esc(r.supplier_name)}</td><td>${r.count}</td><td class="cx-money">${ctx.money(r.total)}</td><td class="cx-money">${ctx.money(r.balance)}</td></tr>`).join("")}
        </tbody></table></div>` : `<div class="cx-empty">لا بيانات</div>`}
      </section>
      <div class="cxi-form-actions"><button type="button" class="cx-btn" id="cxpExportCsv"><i class="fa fa-file-csv"></i> تصدير القائمة الحالية CSV</button></div>
    </div>`, async () => {}, { saveLabel: "إغلاق", skipRender: true });
    document.getElementById("cxpExportCsv")?.addEventListener("click", async () => {
      const data = await ctx.api(`/clinics/api/purchases?${buildQuery()}&per_page=5000`);
      exportCsv(data.items || [], ctx);
    });
  }

  function receiveForm(p, esc) {
    return `<div class="cxi-form"><div class="cxi-receipt-head"><span>${esc(p.purchase_number)}</span><b>${esc(p.supplier_name)}</b></div>
      <div class="cxi-receive-lines">${(p.items||[]).map(line => `<article data-receive-line="${line.id}">
        <header><div><b>${esc(line.item_name)}</b><small>المطلوب ${qty(line.quantity)}${line.free_quantity ? ` + ${qty(line.free_quantity)} مجاني` : ""} · مستلم ${qty(line.received_quantity)} · متبقي ${qty(line.remaining_quantity)}</small></div></header>
        <div class="cxi-form-grid cxi-form-grid--4">
          <label><span>يستلم الآن</span><input class="cx-input cxi-r-qty" type="number" min="0" max="${line.remaining_quantity}" step="0.001" value="${line.remaining_quantity}"></label>
          ${line.batch_tracking ? `<label><span>رقم الدفعة *</span><input class="cx-input cxi-r-batch" value="${esc(line.batch_number||"")}"></label>` : ""}
          ${line.expiry_tracking ? `<label><span>الصلاحية</span><input class="cx-input cxi-r-expiry" type="date" value="${esc(line.expiry_date||"")}"></label>` : ""}
          <label><span>تكلفة الوحدة</span><input class="cx-input cxi-r-cost" type="number" min="0" value="${line.unit_cost}"></label>
        </div></article>`).join("")}</div>
      <label><span>ملاحظات</span><textarea class="cx-textarea" id="cxiReceiptNotes"></textarea></label></div>`;
  }

  async function checkPriceWarnings(ctx, lines) {
    const r = await ctx.api("/clinics/api/purchases/price-check", { method: "POST", body: JSON.stringify({ items: lines }) });
    return r.warnings || [];
  }

  async function openReceiveModal(p, ctx, onDone) {
    if (!p) return;
    const full = await ctx.api(`/clinics/api/purchases/${p.id}`);
    ctx.openModal(`استلام ${full.purchase_number}`, receiveForm(full, ctx.esc), async () => {
      const receiptItems = [...document.querySelectorAll("[data-receive-line]")].map(el => ({
        purchase_item_id: Number(el.dataset.receiveLine),
        quantity: el.querySelector(".cxi-r-qty")?.value,
        batch_number: el.querySelector(".cxi-r-batch")?.value,
        expiry_date: el.querySelector(".cxi-r-expiry")?.value,
        unit_cost: el.querySelector(".cxi-r-cost")?.value,
      })).filter(x => Number(x.quantity) > 0);
      const validation = await ctx.api(`/clinics/api/purchases/${full.id}/validate-receive`, { method: "POST", body: JSON.stringify({ items: receiptItems }) });
      if (validation.blocked?.length) throw new Error(validation.blocked.map(x => x.message).join("\n"));
      if (validation.warnings?.length && !confirm(`${validation.warnings.map(w => w.message).join("\n")}\n\nمتابعة الاستلام؟`)) return;
      await ctx.api(`/clinics/api/purchases/${full.id}/receive`, { method: "POST", body: JSON.stringify({ items: receiptItems, notes: document.getElementById("cxiReceiptNotes")?.value }) });
      if (onDone) await onDone();
    }, { saveLabel: "تأكيد الاستلام", successMessage: "تم الاستلام وتحديث المخزون", skipRender: !!onDone });
  }

  function paymentForm(p, esc, balance) {
    return `<div class="cxi-form"><div class="cxi-balance"><span>المتبقي للمورد</span><strong>${esc(String(balance))}</strong></div>
      <div class="cxi-form-grid">
        <label><span>المبلغ *</span><input class="cx-input" id="cxpPayAmt" type="number" min="1" max="${balance}" value="${balance}"></label>
        <label><span>التاريخ</span><input class="cx-input" id="cxpPayDate" type="date" value="${today()}"></label>
        <label><span>طريقة الدفع</span><select class="cx-select" id="cxpPayMethod">${Object.entries(paymentMethods).map(([v,l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
        <label><span>الحساب / الصندوق</span><input class="cx-input" id="cxpPayAccount"></label>
        <label><span>رقم العملية</span><input class="cx-input" id="cxpPayRef"></label>
        <label class="cxi-span-2"><span>ملاحظات</span><textarea class="cx-textarea" id="cxpPayNotes"></textarea></label>
      </div></div>`;
  }

  function openPaymentModal(p, ctx, onDone) {
    ctx.openModal(`دفعة — ${p.purchase_number}`, paymentForm(p, ctx.money, p.balance), async () => {
      await ctx.api(`/clinics/api/purchases/${p.id}/payments`, { method: "POST", body: JSON.stringify({
        amount: document.getElementById("cxpPayAmt").value,
        payment_date: document.getElementById("cxpPayDate").value,
        payment_method: document.getElementById("cxpPayMethod").value,
        account_name: document.getElementById("cxpPayAccount").value,
        reference_no: document.getElementById("cxpPayRef").value,
        notes: document.getElementById("cxpPayNotes").value,
      })});
      if (onDone) await onDone();
    }, { saveLabel: "تسجيل الدفعة", successMessage: "تم تسجيل الدفعة", skipRender: !!onDone });
  }

  async function openQuickPurchase(ctx, onDone) {
    const [suppliers, items] = await Promise.all([ctx.api("/clinics/api/suppliers"), ctx.api("/clinics/api/inventory")]);
    ctx.openModal("شراء سريع", `<div class="cxi-form"><div class="cxi-form-grid">
      <label><span>المورد *</span><select class="cx-select" id="cxpQSup">${suppliers.map(s => `<option value="${s.id}">${ctx.esc(s.name)}</option>`).join("")}</select></label>
      <label><span>التاريخ</span><input class="cx-input" type="date" id="cxpQDate" value="${today()}"></label>
      <label><span>الصنف *</span><select class="cx-select" id="cxpQItem">${items.map(i => `<option value="${i.id}" data-cost="${i.last_purchase_cost||i.average_cost||0}" data-batch="${i.batch_tracking?1:0}" data-expiry="${i.expiry_tracking?1:0}">${ctx.esc(i.name)}</option>`).join("")}</select></label>
      <label><span>الكمية</span><input class="cx-input" id="cxpQQty" type="number" min="0.001" value="1"></label>
      <label><span>سعر الوحدة</span><input class="cx-input" id="cxpQCost" type="number" min="0" value="0"></label>
      <label><span>رقم الدفعة</span><input class="cx-input" id="cxpQBatch"></label>
      <label><span>الصلاحية</span><input class="cx-input" id="cxpQExpiry" type="date"></label>
    </div><div class="cxi-check-grid"><label><input type="checkbox" id="cxpQRecv" checked> استلام الآن</label><label><input type="checkbox" id="cxpQPay"> دفع الآن</label></div></div>`, async () => {
      const sel = document.getElementById("cxpQItem");
      const opt = sel.options[sel.selectedIndex];
      const payload = {
        supplier_id: Number(document.getElementById("cxpQSup").value),
        purchase_date: document.getElementById("cxpQDate").value,
        receive_now: document.getElementById("cxpQRecv").checked,
        pay_now: document.getElementById("cxpQPay").checked,
        paid: document.getElementById("cxpQPay").checked ? document.getElementById("cxpQCost").value * document.getElementById("cxpQQty").value : 0,
        items: [{ item_id: Number(sel.value), quantity: document.getElementById("cxpQQty").value, unit_cost: document.getElementById("cxpQCost").value, batch_number: document.getElementById("cxpQBatch").value, expiry_date: document.getElementById("cxpQExpiry").value }],
      };
      const r = await ctx.api("/clinics/api/purchases", { method: "POST", body: JSON.stringify(payload) });
      if (r?.id) location.href = `/clinics/purchases/${r.id}`;
    }, { saveLabel: "حفظ", successMessage: "تم إنشاء الشراء", skipRender: true });
    const itemSel = document.getElementById("cxpQItem");
    const syncCost = () => { const o = itemSel.options[itemSel.selectedIndex]; document.getElementById("cxpQCost").value = o?.dataset.cost || 0; };
    itemSel.onchange = syncCost; syncCost();
  }

  function lineRow(items, esc, idx = 0, line = {}) {
    const selectedId = Number(line.item_id || items[0]?.id || 0);
    const i = items.find(x => x.id === selectedId) || items[0];
    return `<tr class="cxp-line" data-idx="${idx}">
      <td><select class="cx-select cxp-item">${items.map(x => `<option value="${x.id}" ${x.id === selectedId ? "selected" : ""} data-unit="${esc(x.unit)}" data-batch="${x.batch_tracking?1:0}" data-expiry="${x.expiry_tracking?1:0}" data-cost="${x.last_purchase_cost||x.average_cost||0}">${esc(x.name)}</option>`).join("")}</select></td>
      <td class="cxp-unit">${esc(i?.unit||"")}</td>
      <td><input class="cx-input cxp-qty" type="number" min="0.001" step="0.001" value="${line.quantity ?? 1}"></td>
      <td><input class="cx-input cxp-free" type="number" min="0" step="0.001" value="${line.free_quantity ?? 0}"></td>
      <td><input class="cx-input cxp-cost" type="number" min="0" value="${line.unit_cost ?? i?.last_purchase_cost ?? i?.average_cost ?? 0}"></td>
      <td><input class="cx-input cxp-disc" type="number" min="0" max="100" value="${line.line_discount_percent ?? 0}" placeholder="%"></td>
      <td class="cx-money cxp-total">0</td>
      <td><input class="cx-input cxp-batch" placeholder="دفعة" value="${esc(line.batch_number||"")}"></td>
      <td><input class="cx-input cxp-expiry" type="date" value="${esc(line.expiry_date||"")}"></td>
      <td><button type="button" class="cxi-remove-line cxp-rm" title="حذف البند"><i class="fa fa-xmark"></i></button></td>
    </tr>`;
  }

  function cxpPanelHead(icon, title, extra = "") {
    return `<div class="cxp-panel-head">
      <div class="cxp-panel-head__title"><span class="cxp-panel-head__icon"><i class="fa fa-${icon}"></i></span><h2>${title}</h2></div>
      ${extra ? `<div class="cxp-panel-head__extra">${extra}</div>` : ""}
    </div>`;
  }

  function purchaseInfoSection(suppliers, ctx, p = {}) {
    const sel = (id, val) => Number(id) === Number(val) ? "selected" : "";
    return `<section class="cxi-panel cxp-info-panel">
      ${cxpPanelHead("file-invoice", "معلومات الفاتورة")}
      <div class="cxi-form-grid cxp-form-grid">
        <label class="cxp-field"><span>المورد <em class="cxp-req">*</em></span><select class="cx-select" id="cxpSupplier">${suppliers.map(s => `<option value="${s.id}" ${sel(s.id, p.supplier_id)}>${ctx.esc(s.name)}</option>`).join("")}</select></label>
        <label class="cxp-field"><span>رقم فاتورة المورد</span><input class="cx-input" id="cxpSupInv" dir="ltr" value="${ctx.esc(p.supplier_invoice_no || "")}" placeholder="INV-0000"></label>
        <label class="cxp-field"><span>تاريخ الفاتورة <em class="cxp-req">*</em></span><input class="cx-input" id="cxpDate" type="date" value="${p.purchase_date || today()}"></label>
        <label class="cxp-field"><span>تاريخ الاستحقاق</span><input class="cx-input" id="cxpDue" type="date" value="${p.due_date || ""}"></label>
        <label class="cxp-field"><span>المخزن المستلم</span><input class="cx-input" id="cxpWarehouse" value="${ctx.esc(p.warehouse_name || "المخزن الرئيسي")}"></label>
        <label class="cxp-field"><span>نوع الشراء</span><select class="cx-select" id="cxpType">${Object.entries(purchaseTypes).map(([v, l]) => `<option value="${v}" ${v === (p.purchase_type || "cash") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label class="cxp-field cxi-span-2"><span>ملاحظات</span><textarea class="cx-textarea" id="cxpNotes" rows="3" placeholder="ملاحظات إضافية على الفاتورة...">${ctx.esc(p.notes || "")}</textarea></label>
      </div>
    </section>`;
  }

  function purchaseLinesSection(linesHtml) {
    return `<section class="cxi-panel cxp-lines-panel">
      ${cxpPanelHead("list", "بنود الفاتورة", `<button class="cx-btn cx-btn--sm cxp-add-btn" type="button" id="cxpAddLine"><i class="fa fa-plus"></i> إضافة بند</button>`)}
      <div class="cx-table-wrap cxp-table-wrap">
        <table class="cx-table cxp-lines-table"><thead><tr>
          <th>الصنف</th><th>الوحدة</th><th>الكمية</th><th>مجاني</th><th>سعر الوحدة</th><th>خصم %</th><th>الإجمالي</th><th>دفعة</th><th>صلاحية</th><th></th>
        </tr></thead><tbody id="cxpLines">${linesHtml}</tbody></table>
      </div>
      <p class="cxp-lines-hint"><i class="fa fa-circle-info"></i> اختر الصنف ثم أدخل الكمية والسعر — يُحسب الإجمالي تلقائياً</p>
    </section>`;
  }

  function purchaseTotalsSection(p = {}, saveOptionsHtml = "") {
    return `<aside class="cxp-side">
      <section class="cxi-panel cxp-totals-card">
        ${cxpPanelHead("calculator", "ملخص الفاتورة")}
        <div class="cxp-totals">
          <div class="cxp-totals-row"><span>المجموع الفرعي</span><b class="cx-money" id="cxpSub">0</b></div>
          <label class="cxp-field"><span>خصم الفاتورة (مبلغ)</span><input class="cx-input" id="cxpDiscAmt" type="number" min="0" value="${p.discount || 0}"></label>
          <label class="cxp-field"><span>أو خصم %</span><input class="cx-input" id="cxpDiscPct" type="number" min="0" max="100" value="${p.discount_percent || 0}"></label>
          <label class="cxp-field"><span>شحن / توصيل</span><input class="cx-input" id="cxpShip" type="number" min="0" value="${p.shipping_extra || 0}"></label>
          <label class="cxp-field"><span>ضريبة</span><input class="cx-input" id="cxpTax" type="number" min="0" value="${p.tax_amount || 0}"></label>
          <div class="cxp-grand"><span>الإجمالي النهائي</span><strong class="cx-money" id="cxpGrand">0</strong></div>
        </div>
      </section>
      ${saveOptionsHtml}
    </aside>`;
  }

  function purchaseSaveOptionsSection() {
    return `<section class="cxi-panel cxp-options-card">
      ${cxpPanelHead("sliders", "خيارات الحفظ")}
      <label class="cxp-toggle"><input type="checkbox" id="cxpRecvNow"> <span><i class="fa fa-box-open"></i> استلام المواد الآن</span></label>
      <label class="cxp-toggle"><input type="checkbox" id="cxpPayNow"> <span><i class="fa fa-money-bill-wave"></i> تسجيل دفعة الآن</span></label>
      <div id="cxpPayBlock" hidden class="cxp-pay-block">
        <label class="cxp-field"><span>المبلغ</span><input class="cx-input" id="cxpPayAmt2" type="number" min="0"></label>
        <label class="cxp-field"><span>طريقة الدفع</span><select class="cx-select" id="cxpPayMethod2">${Object.entries(paymentMethods).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
      </div>
    </section>`;
  }

  function purchaseFormShell(infoHtml, linesHtml, sideHtml) {
    return `<div class="cxp-form-layout">
      <div class="cxp-form-main">${infoHtml}${linesHtml}</div>
      ${sideHtml}
    </div>`;
  }

  async function renderNew(root, ctx) {
    await loadPerms(ctx);
    const [suppliers, items] = await Promise.all([ctx.api("/clinics/api/suppliers"), ctx.api("/clinics/api/inventory")]);
    root.innerHTML = `<div class="cxi-page cxp-page">
      ${header("فاتورة شراء جديدة", "أدخل بيانات الفاتورة والبنود ثم احفظ أو فعّل الاستلام والدفع الفوري.",
        `<a class="cx-btn" href="/clinics/purchases"><i class="fa fa-arrow-right"></i> رجوع</a>
         <button class="cx-btn cx-btn--primary" id="cxpSave"><i class="fa fa-check"></i> حفظ واعتماد</button>`)}
      ${purchaseFormShell(
        purchaseInfoSection(suppliers, ctx),
        purchaseLinesSection(lineRow(items, ctx.esc)),
        purchaseTotalsSection({}, purchaseSaveOptionsSection())
      )}
    </div>`;

    const recalc = () => {
      let sub = 0;
      document.querySelectorAll(".cxp-line").forEach(row => {
        const q = Number(row.querySelector(".cxp-qty")?.value || 0);
        const c = Number(row.querySelector(".cxp-cost")?.value || 0);
        const d = Number(row.querySelector(".cxp-disc")?.value || 0);
        const gross = q * c;
        const net = Math.max(0, gross - Math.round(gross * d / 100));
        row.querySelector(".cxp-total").textContent = ctx.money(net);
        sub += net;
      });
      document.getElementById("cxpSub").textContent = ctx.money(sub);
      const discPct = Number(document.getElementById("cxpDiscPct").value || 0);
      const discAmt = discPct ? Math.round(sub * discPct / 100) : Number(document.getElementById("cxpDiscAmt").value || 0);
      if (discPct) document.getElementById("cxpDiscAmt").value = discAmt;
      const ship = Number(document.getElementById("cxpShip").value || 0);
      const tax = Number(document.getElementById("cxpTax").value || 0);
      const grand = Math.max(0, sub - discAmt + ship + tax);
      document.getElementById("cxpGrand").textContent = ctx.money(grand);
      if (document.getElementById("cxpPayNow").checked) document.getElementById("cxpPayAmt2").value = grand;
    };

    const bindLine = row => {
      row.querySelector(".cxp-item")?.addEventListener("change", async e => {
        const o = e.target.selectedOptions[0];
        row.querySelector(".cxp-unit").textContent = o?.dataset.unit || "";
        row.querySelector(".cxp-cost").value = o?.dataset.cost || 0;
        recalc();
        try {
          const hist = await ctx.api(`/clinics/api/purchases/price-history?item_id=${o.value}`);
          if (hist[0]) row.querySelector(".cxp-cost").title = `آخر سعر: ${hist[0].unit_cost}`;
        } catch (_) {}
      });
      row.querySelectorAll("input").forEach(i => i.addEventListener("input", recalc));
      row.querySelector(".cxp-rm")?.addEventListener("click", () => {
        if (document.querySelectorAll(".cxp-line").length > 1) { row.remove(); recalc(); }
      });
    };
    document.querySelectorAll(".cxp-line").forEach(bindLine);
    recalc();

    document.getElementById("cxpAddLine").onclick = () => {
      const tbody = document.getElementById("cxpLines");
      tbody.insertAdjacentHTML("beforeend", lineRow(items, ctx.esc, Date.now()));
      bindLine(tbody.lastElementChild);
      recalc();
    };
    document.getElementById("cxpPayNow").onchange = e => { document.getElementById("cxpPayBlock").hidden = !e.target.checked; recalc(); };
    ["cxpDiscAmt","cxpDiscPct","cxpShip","cxpTax"].forEach(id => document.getElementById(id).oninput = recalc);

    document.getElementById("cxpSave").onclick = async () => {
      try {
        const supInv = document.getElementById("cxpSupInv").value.trim();
        if (supInv) {
          const dup = await ctx.api(`/clinics/api/purchases/check-duplicate?supplier_id=${document.getElementById("cxpSupplier").value}&supplier_invoice_no=${encodeURIComponent(supInv)}`);
          if (dup.duplicate && !confirm(`فاتورة المورد مسجلة مسبقاً (${dup.purchase_number}). متابعة؟`)) return;
        }
        const lines = [...document.querySelectorAll(".cxp-line")].map(row => ({
          item_id: Number(row.querySelector(".cxp-item").value),
          quantity: row.querySelector(".cxp-qty").value,
          free_quantity: row.querySelector(".cxp-free").value,
          unit_cost: row.querySelector(".cxp-cost").value,
          line_discount_percent: row.querySelector(".cxp-disc").value,
          batch_number: row.querySelector(".cxp-batch").value,
          expiry_date: row.querySelector(".cxp-expiry").value,
        }));
        const warnings = await checkPriceWarnings(ctx, lines);
        if (warnings.length && !confirm(`${warnings.map(w => w.message).join("\n")}\n\nمتابعة الحفظ؟`)) return;
        const payload = {
          supplier_id: Number(document.getElementById("cxpSupplier").value),
          supplier_invoice_no: supInv,
          purchase_date: document.getElementById("cxpDate").value,
          due_date: document.getElementById("cxpDue").value,
          warehouse_name: document.getElementById("cxpWarehouse").value,
          purchase_type: document.getElementById("cxpType").value,
          notes: document.getElementById("cxpNotes").value,
          discount: document.getElementById("cxpDiscAmt").value,
          discount_percent: document.getElementById("cxpDiscPct").value,
          shipping_extra: document.getElementById("cxpShip").value,
          tax_amount: document.getElementById("cxpTax").value,
          receive_now: document.getElementById("cxpRecvNow").checked,
          pay_now: document.getElementById("cxpPayNow").checked,
          paid: document.getElementById("cxpPayNow").checked ? document.getElementById("cxpPayAmt2").value : 0,
          payment_method: document.getElementById("cxpPayMethod2").value,
          items: lines,
        };
        const r = await ctx.api("/clinics/api/purchases", { method: "POST", body: JSON.stringify(payload) });
        ctx.showNotice("تم حفظ الفاتورة", false);
        location.href = `/clinics/purchases/${r.id}`;
      } catch (err) { ctx.showNotice(err.message || String(err)); }
    };
  }

  async function renderEdit(root, ctx, purchaseId) {
    await loadPerms(ctx);
    const [p, suppliers, items] = await Promise.all([
      ctx.api(`/clinics/api/purchases/${purchaseId}`),
      ctx.api("/clinics/api/suppliers"),
      ctx.api("/clinics/api/inventory"),
    ]);
    if (p.receipt_status !== "pending" || Number(p.paid) > 0) {
      root.innerHTML = `<div class="cxi-page cxp-page"><div class="cx-empty">لا يمكن تعديل هذه الفاتورة — تم الاستلام أو تسجيل مدفوعات.<br><a class="cx-btn" style="margin-top:12px" href="/clinics/purchases/${purchaseId}">عودة للفاتورة</a></div></div>`;
      return;
    }
    const linesHtml = (p.items || []).map((line, idx) => lineRow(items, ctx.esc, idx, line)).join("") || lineRow(items, ctx.esc);
    root.innerHTML = `<div class="cxi-page cxp-page">
      ${header(`تعديل ${ctx.esc(p.purchase_number)}`, "تعديل الفاتورة قبل الاستلام أو الدفع.",
        `<a class="cx-btn" href="/clinics/purchases/${purchaseId}"><i class="fa fa-arrow-right"></i> رجوع</a>
         <button class="cx-btn cx-btn--primary" id="cxpSave"><i class="fa fa-check"></i> حفظ التعديلات</button>`)}
      ${purchaseFormShell(
        purchaseInfoSection(suppliers, ctx, p),
        purchaseLinesSection(linesHtml),
        purchaseTotalsSection(p)
      )}
    </div>`;

    const recalc = () => {
      let sub = 0;
      document.querySelectorAll(".cxp-line").forEach(row => {
        const q = Number(row.querySelector(".cxp-qty")?.value || 0);
        const c = Number(row.querySelector(".cxp-cost")?.value || 0);
        const d = Number(row.querySelector(".cxp-disc")?.value || 0);
        const gross = q * c;
        const net = Math.max(0, gross - Math.round(gross * d / 100));
        row.querySelector(".cxp-total").textContent = ctx.money(net);
        sub += net;
      });
      document.getElementById("cxpSub").textContent = ctx.money(sub);
      const discPct = Number(document.getElementById("cxpDiscPct").value || 0);
      const discAmt = discPct ? Math.round(sub * discPct / 100) : Number(document.getElementById("cxpDiscAmt").value || 0);
      if (discPct) document.getElementById("cxpDiscAmt").value = discAmt;
      const ship = Number(document.getElementById("cxpShip").value || 0);
      const tax = Number(document.getElementById("cxpTax").value || 0);
      document.getElementById("cxpGrand").textContent = ctx.money(Math.max(0, sub - discAmt + ship + tax));
    };
    const bindLine = row => {
      row.querySelector(".cxp-item")?.addEventListener("change", async e => {
        const o = e.target.selectedOptions[0];
        row.querySelector(".cxp-unit").textContent = o?.dataset.unit || "";
        row.querySelector(".cxp-cost").value = o?.dataset.cost || 0;
        recalc();
        try {
          const hist = await ctx.api(`/clinics/api/purchases/price-history?item_id=${o.value}`);
          if (hist[0]) row.querySelector(".cxp-cost").title = `آخر سعر: ${hist[0].unit_cost}`;
        } catch (_) {}
      });
      row.querySelectorAll("input").forEach(i => i.addEventListener("input", recalc));
      row.querySelector(".cxp-rm")?.addEventListener("click", () => {
        if (document.querySelectorAll(".cxp-line").length > 1) { row.remove(); recalc(); }
      });
    };
    document.querySelectorAll(".cxp-line").forEach(bindLine);
    recalc();
    document.getElementById("cxpAddLine").onclick = () => {
      const tbody = document.getElementById("cxpLines");
      tbody.insertAdjacentHTML("beforeend", lineRow(items, ctx.esc, Date.now()));
      bindLine(tbody.lastElementChild);
      recalc();
    };
    ["cxpDiscAmt","cxpDiscPct","cxpShip","cxpTax"].forEach(id => document.getElementById(id).oninput = recalc);
    document.getElementById("cxpSave").onclick = async () => {
      try {
        const supInv = document.getElementById("cxpSupInv").value.trim();
        if (supInv) {
          const dup = await ctx.api(`/clinics/api/purchases/check-duplicate?supplier_id=${document.getElementById("cxpSupplier").value}&supplier_invoice_no=${encodeURIComponent(supInv)}&exclude_id=${purchaseId}`);
          if (dup.duplicate && !confirm(`فاتورة المورد مسجلة مسبقاً (${dup.purchase_number}). متابعة؟`)) return;
        }
        const lines = [...document.querySelectorAll(".cxp-line")].map(row => ({
          item_id: Number(row.querySelector(".cxp-item").value),
          quantity: row.querySelector(".cxp-qty").value,
          free_quantity: row.querySelector(".cxp-free").value,
          unit_cost: row.querySelector(".cxp-cost").value,
          line_discount_percent: row.querySelector(".cxp-disc").value,
          batch_number: row.querySelector(".cxp-batch").value,
          expiry_date: row.querySelector(".cxp-expiry").value,
        }));
        const warnings = await checkPriceWarnings(ctx, lines);
        if (warnings.length && !confirm(`${warnings.map(w => w.message).join("\n")}\n\nمتابعة الحفظ؟`)) return;
        await ctx.api(`/clinics/api/purchases/${purchaseId}`, { method: "PUT", body: JSON.stringify({
          supplier_id: Number(document.getElementById("cxpSupplier").value),
          supplier_invoice_no: supInv,
          purchase_date: document.getElementById("cxpDate").value,
          due_date: document.getElementById("cxpDue").value,
          warehouse_name: document.getElementById("cxpWarehouse").value,
          purchase_type: document.getElementById("cxpType").value,
          notes: document.getElementById("cxpNotes").value,
          discount: document.getElementById("cxpDiscAmt").value,
          discount_percent: document.getElementById("cxpDiscPct").value,
          shipping_extra: document.getElementById("cxpShip").value,
          tax_amount: document.getElementById("cxpTax").value,
          items: lines,
        })});
        ctx.showNotice("تم حفظ التعديلات", false);
        location.href = `/clinics/purchases/${purchaseId}`;
      } catch (err) { ctx.showNotice(err.message || String(err)); }
    };
  }

  async function openPurchaseRequests(ctx, onDone, prefillItems = null) {
    const [requests, items, suggestions] = await Promise.all([
      ctx.api("/clinics/api/purchase-requests"),
      ctx.api("/clinics/api/inventory"),
      ctx.api("/clinics/api/purchases/reorder-suggestions").catch(() => []),
    ]);
    const lines = (prefillItems || suggestions || []).map(s => ({
      item_id: s.item_id,
      quantity: s.suggested_qty || s.quantity || 1,
      reason: s.reason || "مخزون منخفض",
    }));
    const lineHtml = (list) => list.map((l, i) => {
      const item = items.find(x => x.id === l.item_id) || items[0];
      return `<div class="cxp-req-line" data-idx="${i}"><select class="cx-select cxp-req-item">${items.map(x => `<option value="${x.id}" ${x.id === (l.item_id || item?.id) ? "selected" : ""}>${ctx.esc(x.name)}</option>`).join("")}</select><input class="cx-input cxp-req-qty" type="number" min="0.001" value="${l.quantity || 1}"><input class="cx-input cxp-req-reason" placeholder="السبب" value="${ctx.esc(l.reason || "")}"><button type="button" class="cxi-remove-line cxp-req-rm"><i class="fa fa-xmark"></i></button></div>`;
    }).join("") || `<div class="cxp-req-line"><select class="cx-select cxp-req-item">${items.map(x => `<option value="${x.id}">${ctx.esc(x.name)}</option>`).join("")}</select><input class="cx-input cxp-req-qty" type="number" min="0.001" value="1"><input class="cx-input cxp-req-reason" placeholder="السبب"><button type="button" class="cxi-remove-line cxp-req-rm"><i class="fa fa-xmark"></i></button></div>`;

    ctx.openModal("طلبات الشراء", `<div class="cxp-requests">
      <section class="cxi-panel"><div class="cxi-panel-title"><h2>طلبات حالية</h2></div>
        ${requests.length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>الرقم</th><th>الحالة</th><th>الأولوية</th><th>البنود</th><th></th></tr></thead><tbody>
          ${requests.map(r => `<tr><td>${ctx.esc(r.request_number)}</td><td>${ctx.esc(requestStatuses[r.status] || r.status)}</td><td>${ctx.esc(priorities[r.priority] || r.priority)}</td><td>${r.items.length}</td><td class="cxi-row-actions">
            ${r.status === "pending" ? `<button class="cx-btn cx-btn--sm" data-approve="${r.id}">اعتماد</button><button class="cx-btn cx-btn--sm" data-reject="${r.id}">رفض</button>` : ""}
            ${["approved","pending"].includes(r.status) && !r.purchase_id ? `<button class="cx-btn cx-btn--sm cx-btn--primary" data-convert="${r.id}">تحويل لفاتورة</button>` : ""}
            ${r.purchase_id ? `<a class="cx-btn cx-btn--sm" href="/clinics/purchases/${r.purchase_id}">عرض الفاتورة</a>` : ""}
          </td></tr>`).join("")}
        </tbody></table></div>` : `<div class="cx-empty">لا توجد طلبات شراء</div>`}
      </section>
      <section class="cxi-panel"><div class="cxi-panel-title"><h2>طلب شراء جديد</h2><button type="button" class="cx-btn cx-btn--sm" id="cxpReqAdd"><i class="fa fa-plus"></i> بند</button></div>
        <div class="cxi-form-grid"><label><span>الأولوية</span><select class="cx-select" id="cxpReqPriority">${Object.entries(priorities).map(([v,l]) => `<option value="${v}">${l}</option>`).join("")}</select></label><label class="cxi-span-2"><span>ملاحظات</span><input class="cx-input" id="cxpReqNotes"></label></div>
        <div id="cxpReqLines" class="cxp-req-lines">${lineHtml(lines)}</div>
      </section>
    </div>`, async () => {
      const reqItems = [...document.querySelectorAll(".cxp-req-line")].map(el => ({
        item_id: Number(el.querySelector(".cxp-req-item").value),
        quantity: el.querySelector(".cxp-req-qty").value,
        reason: el.querySelector(".cxp-req-reason").value,
      }));
      await ctx.api("/clinics/api/purchase-requests", { method: "POST", body: JSON.stringify({
        priority: document.getElementById("cxpReqPriority").value,
        notes: document.getElementById("cxpReqNotes").value,
        status: "pending",
        items: reqItems,
      })});
      if (onDone) await onDone();
    }, { saveLabel: "إرسال الطلب", successMessage: "تم إنشاء طلب الشراء", skipRender: true, extraActions: [{ label: "إغلاق", onClick: async () => {}, skipRender: true }] });

    document.getElementById("cxpReqAdd")?.addEventListener("click", () => {
      document.getElementById("cxpReqLines").insertAdjacentHTML("beforeend", lineHtml([{}]));
    });
    document.getElementById("cxpReqLines")?.addEventListener("click", e => {
      if (e.target.closest(".cxp-req-rm") && document.querySelectorAll(".cxp-req-line").length > 1) e.target.closest(".cxp-req-line").remove();
    });
    document.querySelectorAll("[data-approve]").forEach(b => b.onclick = async () => {
      await ctx.api(`/clinics/api/purchase-requests/${b.dataset.approve}/status`, { method: "POST", body: JSON.stringify({ status: "approved" }) });
      ctx.showNotice("تم اعتماد الطلب", false); openPurchaseRequests(ctx, onDone, prefillItems);
    });
    document.querySelectorAll("[data-reject]").forEach(b => b.onclick = async () => {
      const reason = prompt("سبب الرفض (اختياري)") || "";
      await ctx.api(`/clinics/api/purchase-requests/${b.dataset.reject}/status`, { method: "POST", body: JSON.stringify({ status: "rejected", reason }) });
      ctx.showNotice("تم رفض الطلب", false); openPurchaseRequests(ctx, onDone, prefillItems);
    });
    document.querySelectorAll("[data-convert]").forEach(b => b.onclick = async () => {
      const suppliers = await ctx.api("/clinics/api/suppliers");
      ctx.openModal("تحويل الطلب لفاتورة", `<label><span>المورد *</span><select class="cx-select" id="cxpConvSup">${suppliers.map(s => `<option value="${s.id}">${ctx.esc(s.name)}</option>`).join("")}</select></label>`, async () => {
        const r = await ctx.api(`/clinics/api/purchase-requests/${b.dataset.convert}/convert`, { method: "POST", body: JSON.stringify({ supplier_id: Number(document.getElementById("cxpConvSup").value) }) });
        ctx.showNotice("تم تحويل الطلب لفاتورة", false);
        location.href = `/clinics/purchases/${r.purchase.id}`;
      }, { saveLabel: "تحويل", skipRender: true });
    });
  }

  async function renderReports(root, ctx) {
    await loadPerms(ctx);
    if (!can("export")) {
      root.innerHTML = `<div class="cxi-page"><div class="cx-empty">ليس لديك صلاحية عرض تقارير المشتريات</div></div>`;
      return;
    }
    const filters = { date_from: document.getElementById("cxpRepFrom")?.value || "", date_to: document.getElementById("cxpRepTo")?.value || "" };
    const q = new URLSearchParams(Object.fromEntries(Object.entries(filters).filter(([, v]) => v)));
    const [summary, bySupplier, byItem, byCategory, unpaid, pending, returns, priceChanges] = await Promise.all([
      ctx.api("/clinics/api/purchases/reports/summary"),
      ctx.api(`/clinics/api/purchases/reports/by-supplier?${q}`),
      ctx.api(`/clinics/api/purchases/reports/by-item?${q}`),
      ctx.api(`/clinics/api/purchases/reports/by-category?${q}`),
      ctx.api("/clinics/api/purchases/reports/unpaid"),
      ctx.api("/clinics/api/purchases/reports/pending-receipt"),
      ctx.api(`/clinics/api/purchases/reports/returns?${q}`),
      ctx.api("/clinics/api/purchases/reports/price-changes"),
    ]);
    const reload = () => renderReports(root, ctx);
    function table(headers, rows) {
      if (!rows.length) return `<div class="cx-empty">لا بيانات</div>`;
      return `<div class="cx-table-wrap"><table class="cx-table"><thead><tr>${headers.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.map(cols => `<tr>${cols.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    root.innerHTML = `<div class="cxi-page cxp-page">
      ${header("تقارير المشتريات", "تحليل شامل للمشتريات والموردين والاستلامات والمرتجعات.",
        `<a class="cx-btn" href="/clinics/purchases"><i class="fa fa-arrow-right"></i> المشتريات</a>
         <button class="cx-btn" id="cxpRepCsv"><i class="fa fa-file-csv"></i> تصدير CSV</button>`)}
      <section class="cxi-panel"><div class="cxi-form-grid">
        <label><span>من تاريخ</span><input class="cx-input" type="date" id="cxpRepFrom" value="${filters.date_from}"></label>
        <label><span>إلى تاريخ</span><input class="cx-input" type="date" id="cxpRepTo" value="${filters.date_to}"></label>
        <label><span>&nbsp;</span><button class="cx-btn cx-btn--primary" id="cxpRepApply">تطبيق</button></label>
      </div></section>
      <div class="cxp-summary">
        <article><span>مشتريات الشهر</span><strong>${costMoney(ctx, summary.month_total)}</strong></article>
        <article><span>ذمم الموردين</span><strong>${costMoney(ctx, summary.supplier_payable)}</strong></article>
        <article><span>بانتظار الاستلام</span><strong>${summary.pending_receipt_count || 0}</strong></article>
        <article><span>فواتير غير مدفوعة</span><strong>${unpaid.length}</strong></article>
      </div>
      <div class="cxp-report-grid" style="margin-top:12px">
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>حسب المورد</h2></div>${table(["المورد","الفواتير","الإجمالي","المتبقي"], bySupplier.slice(0, 20).map(r => [r.supplier_name, r.count, costMoney(ctx, r.total), costMoney(ctx, r.balance)]))}</section>
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>حسب الصنف</h2></div>${table(["الصنف","الكمية","الإجمالي"], byItem.slice(0, 20).map(r => [r.item_name, qty(r.quantity), costMoney(ctx, r.total)]))}</section>
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>حسب التصنيف</h2></div>${table(["التصنيف","الأصناف","الإجمالي"], byCategory.map(r => [r.category, r.items, costMoney(ctx, r.total)]))}</section>
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>تغير الأسعار</h2></div>${table(["الصنف","السابق","الجديد","التغير"], priceChanges.slice(0, 15).map(r => [r.item_name, costMoney(ctx, r.old_cost), costMoney(ctx, r.new_cost), `${r.change_pct || 0}%`]))}</section>
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>غير مدفوعة</h2></div>${table(["الفاتورة","المورد","المتبقي"], unpaid.slice(0, 15).map(r => [r.purchase_number, r.supplier_name, costMoney(ctx, r.balance)]))}</section>
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>استلامات معلقة</h2></div>${table(["الفاتورة","المورد","الحالة"], pending.slice(0, 15).map(r => [r.purchase_number, r.supplier_name, receiptLabels[r.receipt_status] || r.receipt_status]))}</section>
        <section class="cxi-panel"><div class="cxi-panel-title"><h2>المرتجعات</h2></div>${table(["المرتجع","المورد","القيمة"], returns.slice(0, 15).map(r => [r.return_number, r.supplier_name, costMoney(ctx, r.total_value)]))}</section>
      </div>
    </div>`;
    document.getElementById("cxpRepApply").onclick = reload;
    document.getElementById("cxpRepCsv").onclick = async () => {
      const data = await ctx.api(`/clinics/api/purchases?per_page=5000&${q}`);
      exportCsv(data.items || [], ctx);
    };
  }

  function returnForm(p, esc) {
    const lines = (p.items || []).filter(i => (i.returnable_quantity || 0) > 0);
    return `<div class="cxi-form"><div class="cxi-receipt-head"><span>${esc(p.purchase_number)}</span><b>${esc(p.supplier_name)}</b></div>
      <div class="cxi-receive-lines">${lines.map(line => `<article data-return-line="${line.id}">
        <header><div><b>${esc(line.item_name)}</b><small>مستلم ${qty(line.received_quantity)} · مرتجع سابقاً ${qty(line.returned_quantity || 0)} · قابل للإرجاع ${qty(line.returnable_quantity)}</small></div></header>
        <div class="cxi-form-grid cxi-form-grid--4">
          <label><span>الكمية</span><input class="cx-input cxp-ret-qty" type="number" min="0" max="${line.returnable_quantity}" step="0.001" value="0"></label>
          <label><span>السبب</span><select class="cx-select cxp-ret-reason">${Object.entries(returnReasons).map(([v,l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
          <label><span>رقم الدفعة</span><input class="cx-input cxp-ret-batch" value="${esc(line.batch_number||"")}"></label>
          <label><span>تكلفة</span><input class="cx-input cxp-ret-cost" type="number" min="0" value="${line.unit_cost}"></label>
        </div></article>`).join("") || `<div class="cx-empty">لا أصناف قابلة للإرجاع</div>`}
      </div><label><span>ملاحظات</span><textarea class="cx-textarea" id="cxpRetNotes"></textarea></label></div>`;
  }

  async function openReturnModal(p, ctx, onDone) {
    const full = await ctx.api(`/clinics/api/purchases/${p.id}`);
    if (!(full.items || []).some(i => (i.returnable_quantity || 0) > 0)) return ctx.showNotice("لا توجد كميات قابلة للإرجاع");
    ctx.openModal(`مرتجع — ${full.purchase_number}`, returnForm(full, ctx.esc), async () => {
      const items = [...document.querySelectorAll("[data-return-line]")].map(el => ({
        purchase_item_id: Number(el.dataset.returnLine),
        quantity: el.querySelector(".cxp-ret-qty")?.value,
        reason: el.querySelector(".cxp-ret-reason")?.value,
        batch_number: el.querySelector(".cxp-ret-batch")?.value,
        unit_cost: el.querySelector(".cxp-ret-cost")?.value,
      })).filter(x => Number(x.quantity) > 0);
      await ctx.api(`/clinics/api/purchases/${full.id}/returns`, { method: "POST", body: JSON.stringify({ items, notes: document.getElementById("cxpRetNotes")?.value }) });
      if (onDone) await onDone();
    }, { saveLabel: "تأكيد المرتجع", successMessage: "تم تسجيل المرتجع وخصم المخزون", skipRender: !!onDone });
  }

  async function uploadPurchaseAttachment(purchaseId, ctx, onDone) {
    ctx.openModal("رفع مرفق", `<div class="cxi-form"><div class="cxi-form-grid">
      <label><span>النوع</span><select class="cx-select" id="cxpAttCat"><option value="invoice">فاتورة المورد</option><option value="delivery_note">وصل التسليم</option><option value="credit_note">إشعار دائن</option><option value="receipt">سند</option><option value="other">أخرى</option></select></label>
      <label class="cxi-span-2"><span>الملف (PDF / صورة)</span><input class="cx-input" id="cxpAttFile" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp"></label>
      <label class="cxi-span-2"><span>ملاحظات</span><input class="cx-input" id="cxpAttNotes"></label>
    </div></div>`, async () => {
      const file = document.getElementById("cxpAttFile").files[0];
      if (!file) throw new Error("اختر ملفاً");
      const fd = new FormData();
      fd.append("file", file);
      fd.append("category", document.getElementById("cxpAttCat").value);
      fd.append("notes", document.getElementById("cxpAttNotes").value);
      const res = await fetch(`/clinics/api/purchases/${purchaseId}/attachments`, { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok || data.ok === false) throw new Error(data.error || "فشل الرفع");
      if (onDone) await onDone();
    }, { saveLabel: "رفع", successMessage: "تم رفع المرفق", skipRender: !!onDone });
  }

  async function renderDetail(root, ctx, purchaseId) {
    await loadPerms(ctx);
    const p = await ctx.api(`/clinics/api/purchases/${purchaseId}`);
    let tab = "overview";
    const render = () => renderDetail(root, ctx, purchaseId);

    const tabs = { overview: "نظرة عامة", items: "الأصناف", receipts: "الاستلامات", payments: "المدفوعات", returns: "المرتجعات", movements: "الحركة", attachments: "المرفقات", timeline: "السجل" };
    const summaryCards = [
      ["الإجمالي", costMoney(ctx, p.total)], ["المدفوع", costMoney(ctx, p.paid)], ["المتبقي", costMoney(ctx, p.balance)],
      ["المرتجعات", costMoney(ctx, p.return_total || 0)],
      ["المستلم", qty(p.items.reduce((s,i) => s + i.received_quantity, 0))],
      ["متبقي استلام", qty(p.items.reduce((s,i) => s + i.remaining_quantity, 0))],
    ];

    const tabContent = () => {
      if (tab === "items") return `<div class="cx-table-wrap"><table class="cx-table cxi-table"><thead><tr>
        <th>الصنف</th><th>مطلوب</th><th>مجاني</th><th>مستلم</th><th>متبقي</th><th>سعر</th><th>خصم</th><th>إجمالي</th>
      </tr></thead><tbody>${p.items.map(i => `<tr><td><b>${ctx.esc(i.item_name)}</b></td><td>${qty(i.quantity)}</td><td>${qty(i.free_quantity)}</td><td>${qty(i.received_quantity)}</td><td>${qty(i.remaining_quantity)}</td><td class="cx-money">${ctx.money(i.unit_cost)}</td><td>${i.line_discount_percent || 0}%</td><td class="cx-money">${ctx.money(i.line_total)}</td></tr>`).join("")}</tbody></table></div>`;
      if (tab === "receipts") return (p.receipts||[]).length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>رقم الاستلام</th><th>التاريخ</th><th>البنود</th><th>بواسطة</th><th></th></tr></thead><tbody>${p.receipts.map(r => `<tr><td>${ctx.esc(r.receipt_number)}</td><td>${ctx.esc(window.FinoraTime.dateTime(r.received_at)||"")}</td><td>${r.items_count}</td><td>${ctx.esc(r.received_by_name||"—")}</td><td><a class="cx-btn cx-btn--sm" href="/clinics/purchases/${purchaseId}/receipts/${r.id}/print" target="_blank"><i class="fa fa-print"></i></a></td></tr>`).join("")}</tbody></table></div>` : `<div class="cx-empty">لا استلامات بعد</div>`;
      if (tab === "payments") return (p.payments||[]).length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>رقم</th><th>التاريخ</th><th>المبلغ</th><th>الطريقة</th><th>الحساب</th><th></th></tr></thead><tbody>${p.payments.map(x => `<tr><td>${ctx.esc(x.payment_number)}</td><td>${ctx.esc(x.payment_date)}</td><td class="cx-money">${costMoney(ctx, x.amount)}</td><td>${paymentMethods[x.payment_method]||x.payment_method}</td><td>${ctx.esc(x.account_name||"—")}</td><td>${can("payment_view") ? `<a class="cx-btn cx-btn--sm" href="/clinics/purchases/${purchaseId}/payments/${x.id}/print" target="_blank"><i class="fa fa-print"></i></a>` : ""}</td></tr>`).join("")}</tbody></table></div>` : `<div class="cx-empty">لا مدفوعات بعد</div>`;
      if (tab === "returns") return (p.returns||[]).length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>رقم المرتجع</th><th>التاريخ</th><th>القيمة</th><th>البنود</th><th></th></tr></thead><tbody>${p.returns.map(r => `<tr><td>${ctx.esc(r.return_number)}</td><td>${ctx.esc(r.return_date)}</td><td class="cx-money">${costMoney(ctx, r.total_value)}</td><td>${r.items.length}</td><td><a class="cx-btn cx-btn--sm" href="/clinics/purchases/${purchaseId}/returns/${r.id}/print" target="_blank"><i class="fa fa-print"></i></a></td></tr>`).join("")}</tbody></table></div>` : `<div class="cx-empty">لا مرتجعات بعد</div>`;
      if (tab === "movements") return (p.movements||[]).length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>الصنف</th><th>النوع</th><th>الكمية</th><th>التكلفة</th><th>التاريخ</th></tr></thead><tbody>${p.movements.map(m => `<tr><td>${ctx.esc(m.item_name)}</td><td>${m.movement_type === "in" ? "إدخال" : "صرف"}</td><td>${qty(m.quantity)}</td><td class="cx-money">${ctx.money(m.unit_cost)}</td><td>${ctx.esc(window.FinoraTime.dateTime(m.created_at)||"")}</td></tr>`).join("")}</tbody></table></div>` : `<div class="cx-empty">لا حركات مرتبطة</div>`;
      if (tab === "attachments") return `<div class="cxp-attachments"><div class="cxi-panel-title"><button class="cx-btn cx-btn--sm cx-btn--primary" id="cxpUploadAtt"><i class="fa fa-upload"></i> رفع مرفق</button></div>
        ${(p.attachments||[]).length ? `<div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>الملف</th><th>النوع</th><th>التاريخ</th><th></th></tr></thead><tbody>${p.attachments.map(a => `<tr><td>${ctx.esc(a.file_name)}</td><td>${ctx.esc(a.category)}</td><td>${ctx.esc(window.FinoraTime.dateTime(a.uploaded_at)||"")}</td><td><a class="cx-btn cx-btn--sm" href="/clinics/api/purchases/attachments/${a.id}/download" target="_blank">تحميل</a></td></tr>`).join("")}</tbody></table></div>` : `<div class="cx-empty">لا مرفقات بعد</div>`}</div>`;
      if (tab === "timeline") return `<div class="cxp-timeline">${(p.timeline||[]).map(t => `<article><time>${ctx.esc(window.FinoraTime.dateTime(t.at)||"")}</time><p>${ctx.esc(t.summary)}</p><small>${ctx.esc(t.actor_name||"النظام")}</small></article>`).join("") || `<div class="cx-empty">لا سجل</div>`}</div>`;
      return `<dl class="cxp-overview">
        <div><dt>المورد</dt><dd>${ctx.esc(p.supplier_name)}</dd></div>
        <div><dt>فاتورة المورد</dt><dd dir="ltr">${ctx.esc(p.supplier_invoice_no||"—")}</dd></div>
        <div><dt>التاريخ</dt><dd>${ctx.esc(p.purchase_date)}</dd></div>
        <div><dt>الاستحقاق</dt><dd>${ctx.esc(p.due_date||"—")}</dd></div>
        <div><dt>المخزن</dt><dd>${ctx.esc(p.warehouse_name||"—")}</dd></div>
        <div><dt>نوع الشراء</dt><dd>${purchaseTypes[p.purchase_type]||p.purchase_type}</dd></div>
        <div><dt>الموظف</dt><dd>${ctx.esc(p.created_by_name||"—")}</dd></div>
        <div class="cxi-span-2"><dt>ملاحظات</dt><dd>${ctx.esc(p.notes||"—")}</dd></div>
      </dl>`;
    };

    root.innerHTML = `<div class="cxi-page cxp-page">
      <section class="cxp-detail-head">
        <div><a class="cxp-back" href="/clinics/purchases"><i class="fa fa-arrow-right"></i> المشتريات</a>
          <h1>فاتورة ${ctx.esc(p.purchase_number)}</h1>
          <div class="cxp-badges">${invoiceBadge(p.invoice_status)} ${receiptBadge(p.receipt_status)} ${paymentBadge(p.payment_status)}</div>
          ${p.invoice_status === "draft" ? `<p class="cxp-draft-note"><i class="fa fa-circle-info"></i> هذه الفاتورة مسودة وتنتظر الاعتماد قبل الاستلام أو الدفع.</p>` : ""}
        </div>
        <div class="cxi-header__actions">
          ${can("approve") && p.invoice_status === "draft" ? `<button class="cx-btn cx-btn--primary" id="cxpDetApprove"><i class="fa fa-check"></i> اعتماد</button>` : ""}
          ${can("edit") && p.receipt_status === "pending" && !Number(p.paid) ? `<a class="cx-btn" href="/clinics/purchases/${purchaseId}/edit"><i class="fa fa-pen"></i> تعديل</a>` : ""}
          ${can("create") ? `<button class="cx-btn" id="cxpDetCopy"><i class="fa fa-copy"></i> نسخ</button>` : ""}
          ${can("receive") && p.receipt_status !== "complete" && p.invoice_status !== "draft" ? `<button class="cx-btn cx-btn--primary" id="cxpDetRecv"><i class="fa fa-truck-ramp-box"></i> استلام</button>` : ""}
          ${can("pay") && p.balance > 0 && p.invoice_status !== "draft" ? `<button class="cx-btn" id="cxpDetPay"><i class="fa fa-money-bill-wave"></i> دفعة</button>` : ""}
          ${can("return") && (p.items||[]).some(i => (i.returnable_quantity||0) > 0) ? `<button class="cx-btn" id="cxpDetReturn"><i class="fa fa-rotate-left"></i> مرتجع</button>` : ""}
          <button class="cx-btn" id="cxpDetPrint"><i class="fa fa-print"></i> طباعة</button>
        </div>
      </section>
      <div class="cxp-summary">${summaryCards.map(([l,v]) => `<article><span>${l}</span><strong>${v}</strong></article>`).join("")}</div>
      <section class="cxi-panel">
        <nav class="cxp-tabs">${Object.entries(tabs).map(([k,l]) => `<button class="${tab===k?"active":""}" data-tab="${k}">${l}</button>`).join("")}</nav>
        <div class="cxp-tab-body">${tabContent()}</div>
      </section>
    </div>`;

    root.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { tab = b.dataset.tab; render(); });
    document.getElementById("cxpDetApprove")?.addEventListener("click", async () => {
      await ctx.api(`/clinics/api/purchases/${purchaseId}/approve`, { method: "POST", body: "{}" });
      ctx.showNotice("تم اعتماد الفاتورة", false);
      render();
    });
    document.getElementById("cxpDetCopy")?.addEventListener("click", async () => {
      const r = await ctx.api(`/clinics/api/purchases/${purchaseId}/copy`, { method: "POST", body: "{}" });
      ctx.showNotice("تم نسخ الفاتورة", false);
      location.href = `/clinics/purchases/${r.id}`;
    });
    document.getElementById("cxpDetRecv")?.addEventListener("click", () => openReceiveModal(p, ctx, render));
    document.getElementById("cxpDetPay")?.addEventListener("click", () => openPaymentModal(p, ctx, render));
    document.getElementById("cxpDetReturn")?.addEventListener("click", () => openReturnModal(p, ctx, render));
    document.getElementById("cxpDetPrint")?.addEventListener("click", () => window.open(`/clinics/purchases/${purchaseId}/print`, "_blank"));
    document.getElementById("cxpUploadAtt")?.addEventListener("click", () => uploadPurchaseAttachment(purchaseId, ctx, render));
  }

  async function render(state, root, ctx) {
    const shell = document.querySelector(".cx-shell");
    const view = shell?.dataset.purchasesView || "";
    const purchaseId = Number(shell?.dataset.purchaseId || 0);
    if (view === "reports") return renderReports(root, ctx);
    if (view === "new") return renderNew(root, ctx);
    if (view === "edit" && purchaseId) return renderEdit(root, ctx, purchaseId);
    if (purchaseId) return renderDetail(root, ctx, purchaseId);
    return renderList(root, ctx);
  }

  window.ClinicsPurchases = { render, openPurchaseRequests };
})();
