(() => {
  "use strict";
  const root = document.querySelector('[data-food-page="purchases"]');
  if (!root || !document.getElementById("foodPurchasesRoot")) return;

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
    detail: null,
    payPurchaseId: null,
    returnPurchase: null,
    loading: false,
    perms: {},
  };

  function params() {
    const range = $("#fpRange").value || "month";
    const q = new URLSearchParams({
      range,
      page: String(state.page),
      page_size: String(state.pageSize),
      status_tab: state.tab,
      q: ($("#fpSearch").value || "").trim(),
    });
    if (range === "custom" || $("#fpStart").value || $("#fpEnd").value) {
      if ($("#fpStart").value && $("#fpEnd").value) {
        q.set("range", "custom");
        q.set("start", $("#fpStart").value);
        q.set("end", $("#fpEnd").value);
      }
    }
    if ($("#fpWarehouse").value) q.set("warehouse_id", $("#fpWarehouse").value);
    if ($("#fpSupplier").value) q.set("supplier_id", $("#fpSupplier").value);
    if ($("#fpPayMethod").value) q.set("payment_method", $("#fpPayMethod").value);
    if ($("#fpStatus").value) q.set("purchase_status", $("#fpStatus").value);
    return q;
  }

  function trendHtml(change) {
    if (change == null) return `<small class="fi-trend mute">—</small>`;
    const up = Number(change) >= 0;
    return `<small class="fi-trend ${up ? "up" : "down"}">${up ? "↑" : "↓"} ${Math.abs(Number(change))}٪ عن الفترة السابقة</small>`;
  }

  function statusBadge(row) {
    return `<span class="fi-badge fi-badge--${esc(row.status)}">${esc(row.status_label)}</span>`;
  }

  function payPill(row) {
    const mode = String(row.payment_mode || "").toLowerCase();
    const label = row.payment_method || "—";
    const cls = {
      cash: "fp-pay--cash",
      credit: "fp-pay--credit",
      partial: "fp-pay--partial",
      mixed: "fp-pay--mixed",
      transfer: "fp-pay--transfer",
      card: "fp-pay--card",
    }[mode] || "fp-pay--mute";
    return `<span class="fp-pay ${cls}">${esc(label)}</span>`;
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString("en-IQ");
  }

  function formatWhenTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("en-IQ", { dateStyle: "short", timeStyle: "short" });
  }

  function renderKpis(kpis) {
    const cards = [
      ["إجمالي المشتريات", kpis.purchases, "fa-wallet"],
      ["عدد الفواتير", kpis.invoices, "fa-file-invoice", true],
      ["المدفوع", kpis.paid, "fa-credit-card"],
      ["المتبقي للموردين", kpis.remaining, "fa-scale-balanced"],
      ["مرتجعات المشتريات", kpis.returns, "fa-rotate-left"],
      ["متوسط فاتورة الشراء", kpis.average, "fa-chart-column"],
    ];
    $("#fpKpis").innerHTML = cards.map(([title, card, icon, count]) => `
      <article class="fi-kpi fp-kpi">
        <span class="fi-kpi__icon"><i class="fa ${icon}"></i></span>
        <div>
          <span class="fi-kpi__title">${title}</span>
          <strong class="fi-kpi__value">${count || !card.money ? num(card.value) : money(card.value)}</strong>
          ${trendHtml(card.change)}
        </div>
      </article>`).join("");
  }

  function renderCounters(counters) {
    $("#fpTabAll").textContent = num(counters.all);
    $("#fpTabConfirmed").textContent = num(counters.confirmed);
    $("#fpTabDraft").textContent = num(counters.draft);
    $("#fpTabDue").textContent = num(counters.due);
    $("#fpTabPaid").textContent = num(counters.paid || 0);
    $("#fpTabReturns").textContent = num(counters.returns);
    $("#fpTabCancelled").textContent = num(counters.cancelled);
  }

  function renderPager(data) {
    const pages = data.pages || 1;
    const page = data.page || 1;
    const size = data.page_size || state.pageSize;
    const total = data.total || 0;
    const from = total ? (page - 1) * size + 1 : 0;
    const to = Math.min(page * size, total);
    const buttons = [];
    const pushBtn = (label, pageNum, disabled = false, active = false) => {
      buttons.push(`<button type="button" class="${active ? "active" : ""}" data-page="${pageNum}" ${disabled ? "disabled" : ""}>${label}</button>`);
    };
    pushBtn('<i class="fa fa-chevron-right"></i>', Math.max(1, page - 1), page <= 1);
    const windowSize = 5;
    let start = Math.max(1, page - 2);
    let end = Math.min(pages, start + windowSize - 1);
    start = Math.max(1, end - windowSize + 1);
    if (start > 1) {
      pushBtn("1", 1, false, page === 1);
      if (start > 2) buttons.push(`<span class="fp-pager-gap">…</span>`);
    }
    for (let i = start; i <= end; i += 1) pushBtn(String(i), i, false, i === page);
    if (end < pages) {
      if (end < pages - 1) buttons.push(`<span class="fp-pager-gap">…</span>`);
      pushBtn(String(pages), pages, false, page === pages);
    }
    pushBtn('<i class="fa fa-chevron-left"></i>', Math.min(pages, page + 1), page >= pages);
    $("#fpPagerButtons").innerHTML = buttons.join("");
    $("#fpPagerMeta").textContent = `عرض ${num(from)} إلى ${num(to)} من ${num(total)} فاتورة`;
    $$("#fpPagerButtons [data-page]").forEach((btn) => {
      btn.onclick = () => {
        if (btn.disabled) return;
        state.page = Number(btn.dataset.page);
        load();
      };
    });
  }

  function rowMenu(row) {
    const canPay = row.remaining > 0 && row.status !== "draft" && row.status !== "cancelled";
    const canCancel = row.status !== "cancelled";
    return `
      <div class="fp-more" data-more-wrap>
        <button type="button" class="fp-more__btn" data-more aria-label="إجراءات"><i class="fa fa-ellipsis-vertical"></i></button>
        <div class="fp-more__menu" hidden>
          <button type="button" data-open="${row.id}"><i class="fa fa-eye"></i> عرض</button>
          ${canPay ? `<button type="button" data-pay="${row.id}"><i class="fa fa-money-bill"></i> تسديد</button>` : ""}
          ${canCancel ? `<button type="button" data-cancel-row="${row.id}"><i class="fa fa-ban"></i> إلغاء</button>` : ""}
        </div>
      </div>`;
  }

  function renderRows(rows) {
    const empty = !rows.length;
    $("#fpEmpty").hidden = !empty;
    $("#fpTableWrap").hidden = empty;
    $("#fpPager").hidden = empty;
    if (empty) {
      $("#fpTableBody").innerHTML = "";
      return;
    }
    $("#fpTableBody").innerHTML = rows.map((row) => `
      <tr data-id="${row.id}" tabindex="0">
        <td><button type="button" class="fp-inv-link" data-open="${row.id}">${esc(row.invoice_no || row.id)}</button></td>
        <td>
          <div class="fp-stack">
            <b>${esc(row.supplier_invoice_no || "—")}</b>
            <small>${esc(formatWhenTime(row.created_at) || formatWhen(row.purchase_date))}</small>
          </div>
        </td>
        <td><b class="fp-supplier">${esc(row.supplier_name)}</b></td>
        <td>${esc(row.warehouse_name || "—")}</td>
        <td>${payPill(row)}</td>
        <td><b>${money(row.total)}</b></td>
        <td>${money(row.paid)}</td>
        <td class="${row.remaining > 0 ? "fi-remain" : ""}">${money(row.remaining)}</td>
        <td>${statusBadge(row)}</td>
        <td>${rowMenu(row)}</td>
      </tr>`).join("");

    $$("#fpTableBody tr[data-id]").forEach((tr) => {
      tr.onclick = (e) => {
        if (e.target.closest("button,a,.fp-more")) return;
        openDrawer(Number(tr.dataset.id));
      };
      tr.onkeydown = (e) => {
        if (e.key === "Enter") openDrawer(Number(tr.dataset.id));
      };
    });
    $$("[data-open]").forEach((btn) => {
      btn.onclick = (e) => { e.stopPropagation(); closeMenus(); openDrawer(Number(btn.dataset.open)); };
    });
    $$("[data-pay]").forEach((btn) => {
      btn.onclick = (e) => { e.stopPropagation(); closeMenus(); openPay(Number(btn.dataset.pay)); };
    });
    $$("[data-cancel-row]").forEach((btn) => {
      btn.onclick = (e) => { e.stopPropagation(); closeMenus(); cancelPurchase(Number(btn.dataset.cancelRow)); };
    });
    $$("[data-more]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = btn.parentElement.querySelector(".fp-more__menu");
        const open = !menu.hidden;
        closeMenus();
        menu.hidden = open;
      };
    });
  }

  function closeMenus() {
    $$(".fp-more__menu").forEach((m) => { m.hidden = true; });
    const ops = $("#fpOpsMenu");
    if (ops) ops.hidden = true;
    $("#fpOpsBtn")?.setAttribute("aria-expanded", "false");
  }

  function toggleOpsMenu(e) {
    e.preventDefault();
    e.stopPropagation();
    const menu = $("#fpOpsMenu");
    if (!menu) return;
    const willOpen = menu.hidden;
    closeMenus();
    if (willOpen) {
      menu.hidden = false;
      $("#fpOpsBtn")?.setAttribute("aria-expanded", "true");
    }
  }

  function closeDrawer() {
    const drawer = $("#fpDrawer");
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    state.detail = null;
  }

  async function openDrawer(id) {
    const drawer = $("#fpDrawer");
    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    $("#fpDrawerBody").innerHTML = '<div class="fi-drawer-loading">جاري التحميل...</div>';
    try {
      const detail = await api(`/purchases/${id}`);
      state.detail = detail;
      $("#fpDrawerTitle").textContent = detail.invoice_no || `#${detail.id}`;
      $("#fpDrawerMeta").innerHTML = `${statusBadge(detail)} · ${esc(detail.supplier_name)} · ${money(detail.total)}`;
      const itemsHtml = detail.items?.length
        ? `<div class="food-table-wrap"><table class="food-table"><thead><tr><th>المادة</th><th>الوحدة</th><th>الكمية</th><th>بونص</th><th>السعر</th><th>الإجمالي</th><th>Batch</th><th>الصلاحية</th></tr></thead><tbody>${
          detail.items.map((item) => `<tr>
            <td><b>${esc(item.product_name)}</b><br><small>${esc(item.variant_name || "")}</small></td>
            <td>${esc(item.unit_name || "—")}</td>
            <td>${num(item.quantity)}</td>
            <td>${num(item.bonus)}</td>
            <td>${item.unit_cost == null ? "—" : money(item.unit_cost)}</td>
            <td>${money(item.line_total)}</td>
            <td>${esc(item.batch_number || "—")}</td>
            <td>${esc(item.expiry_date || "—")}</td>
          </tr>`).join("")
        }</tbody></table></div>`
        : '<div class="food-empty">لا توجد مواد</div>';

      const paymentsHtml = detail.payments?.length
        ? detail.payments.map((p) => `<div class="fi-block"><b>${money(p.amount)}</b><span>${formatWhen(p.created_at)}</span><small>${esc(p.note || "")}</small></div>`).join("")
        : '<div class="food-empty">لا توجد دفعات مسجلة</div>';

      const returnsHtml = detail.returns?.length
        ? detail.returns.map((r) => `<div class="fi-pay-row"><div><b>${esc(r.return_no)}</b><small>${esc(r.reason || "")} · ${formatWhen(r.created_at)}</small></div><strong>${money(r.total)}</strong></div>`).join("")
        : '<div class="food-empty">لا توجد مرتجعات</div>';

      const canReturn = detail.status !== "draft" && detail.status !== "cancelled" && detail.stock_applied
        && (detail.items || []).some((i) => Number(i.returnable_quantity || 0) > 0);

      $("#fpDrawerBody").innerHTML = `
        <div class="fi-drawer-actions">
          ${detail.status === "draft" ? `<button type="button" class="food-primary" id="fpDrawerConfirm"><i class="fa fa-check"></i> اعتماد وتحديث المخزون</button>` : ""}
          ${detail.remaining > 0 && detail.status !== "draft" && detail.status !== "cancelled" ? `<button type="button" class="food-primary" id="fpDrawerPay"><i class="fa fa-money-bill"></i> تسجيل تسديد</button>` : ""}
          ${canReturn ? `<button type="button" class="food-ghost" id="fpDrawerReturn"><i class="fa fa-rotate-left"></i> مرتجع للمورد</button>` : ""}
          ${detail.status !== "cancelled" ? `<button type="button" class="food-ghost" id="fpDrawerCancel"><i class="fa fa-ban"></i> إلغاء / عكس</button>` : ""}
          <a class="food-ghost" href="/food/purchases/new"><i class="fa fa-plus"></i> فاتورة جديدة</a>
        </div>
        <section class="fi-block">
          <h3>المورد والدفع</h3>
          <div class="fi-meta-grid">
            <div><span>المورد</span><b>${esc(detail.supplier_name)}</b></div>
            <div><span>فاتورة المورد</span><b>${esc(detail.supplier_invoice_no || "—")}</b></div>
            <div><span>المخزن</span><b>${esc(detail.warehouse_name || "—")}</b></div>
            <div><span>طريقة الدفع</span><b>${esc(detail.payment_method)}</b></div>
            <div><span>المدفوع</span><b>${money(detail.paid)}</b></div>
            <div><span>المتبقي</span><b>${money(detail.remaining)}</b></div>
            <div><span>إجمالي المرتجعات</span><b>${money(detail.return_total || 0)}</b></div>
            <div><span>ذمة المورد الحالية</span><b>${money(detail.supplier_debt)}</b></div>
            <div><span>ملاحظات</span><b>${esc(detail.notes || "—")}</b></div>
          </div>
        </section>
        <section class="fi-block">
          <h3>المصاريف</h3>
          <div class="fi-meta-grid">
            <div><span>الخصم</span><b>${money(detail.discount_value)}</b></div>
            <div><span>النقل</span><b>${money(detail.extras?.shipping || 0)}</b></div>
            <div><span>الجمارك</span><b>${money(detail.extras?.customs || 0)}</b></div>
            <div><span>أخرى</span><b>${money(detail.extras?.other || 0)}</b></div>
          </div>
        </section>
        <section class="fi-block"><h3>المواد</h3>${itemsHtml}</section>
        <section class="fi-block"><h3>المدفوعات</h3>${paymentsHtml}</section>
        <section class="fi-block"><h3>مرتجعات المورد</h3>${returnsHtml}</section>
      `;
      $("#fpDrawerPay")?.addEventListener("click", () => openPay(detail.id, detail.remaining));
      $("#fpDrawerCancel")?.addEventListener("click", () => cancelPurchase(detail.id));
      $("#fpDrawerConfirm")?.addEventListener("click", () => confirmPurchase(detail.id));
      $("#fpDrawerReturn")?.addEventListener("click", () => openReturn(detail));
    } catch (error) {
      $("#fpDrawerBody").innerHTML = `<div class="food-inline-error">${esc(error.message)}</div>`;
    }
  }

  function openPay(id, remainingHint) {
    state.payPurchaseId = id;
    const dialog = $("#fpPayDialog");
    $("#fpPayError").hidden = true;
    $("#fpPayAmount").value = remainingHint || "";
    $("#fpPayRemainingHint").textContent = remainingHint != null ? `المتبقي ${money(remainingHint)}` : "تسجيل تسديد للمورد";
    $("#fpPayNote").value = "";
    dialog.showModal();
  }

  function openReturn(detail) {
    state.returnPurchase = detail;
    $("#fpReturnError").hidden = true;
    $("#fpReturnNote").value = "";
    const items = (detail.items || []).filter((i) => Number(i.returnable_quantity || 0) > 0);
    $("#fpReturnItems").innerHTML = items.map((item) => `
      <div class="fi-return-line" data-item-id="${item.id}">
        <div>
          <b>${esc(item.product_name)}</b>
          <small>${esc(item.variant_name || "")} · ${esc(item.unit_name || "")} · قابل للإرجاع ${num(item.returnable_quantity)}</small>
          ${item.batches?.length ? `<label style="display:block;margin-top:6px">الدفعة
            <select data-batch>
              ${item.batches.map((b) => `<option value="${b.id}">${esc(b.batch_number || ("#" + b.id))} · ${b.expiry_date || "—"} · ${num(b.quantity_base)}</option>`).join("")}
            </select>
          </label>` : ""}
        </div>
        <input type="number" min="0" max="${item.returnable_quantity}" value="0" data-qty>
      </div>`).join("") || '<div class="food-empty">لا توجد كميات قابلة للإرجاع</div>';
    $("#fpReturnDialog").showModal();
  }

  async function confirmPurchase(id) {
    if (!confirm("اعتماد المسودة وتحديث المخزون وذمة المورد؟")) return;
    try {
      const result = await api(`/purchases/${id}/confirm`, { method: "POST", body: "{}" });
      notice(`تم اعتماد ${result.invoice_no || id}`);
      openDrawer(id);
      load();
    } catch (error) {
      notice(error.message, true);
    }
  }

  async function cancelPurchase(id) {
    const reason = prompt("سبب الإلغاء / العكس:", "إلغاء فاتورة شراء");
    if (reason == null) return;
    if (!confirm("سيتم عكس المخزون وذمة المورد إن وُجدت. متابعة؟")) return;
    try {
      await api(`/purchases/${id}/cancel`, { method: "POST", body: JSON.stringify({ reason }) });
      notice("تم إلغاء الفاتورة");
      closeDrawer();
      load();
    } catch (error) {
      notice(error.message, true);
    }
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    $("#fpSkeleton").hidden = false;
    try {
      const data = await api(`/purchases?${params()}`);
      renderKpis(data.kpis);
      renderCounters(data.counters);
      renderRows(data.rows);
      renderPager(data);
    } catch (error) {
      notice(error.message, true);
    } finally {
      $("#fpSkeleton").hidden = true;
      state.loading = false;
    }
  }

  async function initMeta() {
    const meta = await api("/purchases/meta");
    state.perms = meta.permissions || {};
    $("#fpWarehouse").innerHTML = '<option value="">كل المخازن</option>' + (meta.warehouses || []).map(
      (w) => `<option value="${w.id}">${esc(w.name)}</option>`
    ).join("");
    $("#fpSupplier").innerHTML = '<option value="">كل الموردين</option>' + (meta.suppliers || []).map(
      (s) => `<option value="${s.id}">${esc(s.name)}</option>`
    ).join("");
  }

  function bind() {
    let searchTimer;
    $("#fpSearch").oninput = () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.page = 1; load(); }, 280);
    };
    $("#fpRange").onchange = () => {
      if ($("#fpRange").value !== "custom") {
        $("#fpStart").value = "";
        $("#fpEnd").value = "";
        state.page = 1;
        load();
      }
    };
    $("#fpApplyFilter").onclick = () => {
      if ($("#fpStart").value && $("#fpEnd").value) $("#fpRange").value = "custom";
      state.page = 1;
      load();
    };
    $("#fpResetFilter").onclick = () => {
      $("#fpSearch").value = "";
      $("#fpRange").value = "month";
      $("#fpStart").value = "";
      $("#fpEnd").value = "";
      $("#fpWarehouse").value = "";
      $("#fpSupplier").value = "";
      $("#fpPayMethod").value = "";
      $("#fpStatus").value = "";
      state.tab = "all";
      state.page = 1;
      $$("#fpTabs [data-tab]").forEach((x) => x.classList.toggle("active", x.dataset.tab === "all"));
      load();
    };
    ["fpWarehouse", "fpSupplier", "fpPayMethod", "fpStatus", "fpPageSize"].forEach((id) => {
      $(`#${id}`).onchange = () => {
        if (id === "fpPageSize") state.pageSize = Number($("#fpPageSize").value) || 20;
        state.page = 1;
        load();
      };
    });
    $$("#fpTabs [data-tab]").forEach((btn) => {
      btn.onclick = () => {
        $$("#fpTabs [data-tab]").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        state.tab = btn.dataset.tab;
        state.page = 1;
        load();
      };
    });
    $$("[data-fp-close]").forEach((el) => { el.onclick = closeDrawer; });
    $("#fpOpsBtn").onclick = toggleOpsMenu;
    document.addEventListener("click", (e) => {
      if (e.target.closest?.("#fpOpsMenu, #fpOpsBtn, .fp-more")) return;
      closeMenus();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeMenus();
    });
    $("#fpExportBtn").onclick = async () => {
      closeMenus();
      try {
        const data = await api(`/purchases/export?${params()}`);
        const header = ["invoice_no", "purchase_date", "supplier_invoice_no", "supplier", "warehouse", "total", "paid", "remaining", "payment_method", "status"];
        const lines = [header.join(",")].concat((data.rows || []).map((row) => header.map((k) => `"${String(row[k] ?? "").replace(/"/g, '""')}"`).join(",")));
        const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `food-purchases-${Date.now()}.csv`;
        a.click();
      } catch (error) {
        notice(error.message, true);
      }
    };
    $$("#fpPayDialog [data-close]").forEach((btn) => {
      btn.onclick = () => $("#fpPayDialog").close();
    });
    $$("#fpReturnDialog [data-close]").forEach((btn) => {
      btn.onclick = () => $("#fpReturnDialog").close();
    });
    $("#fpPayConfirm").onclick = async () => {
      $("#fpPayError").hidden = true;
      try {
        await api(`/purchases/${state.payPurchaseId}/payments`, {
          method: "POST",
          body: JSON.stringify({
            amount: $("#fpPayAmount").value,
            method: $("#fpPayMethodDialog").value,
            note: $("#fpPayNote").value,
          }),
        });
        $("#fpPayDialog").close();
        notice("تم تسجيل التسديد");
        if (state.detail?.id === state.payPurchaseId) openDrawer(state.payPurchaseId);
        load();
      } catch (error) {
        $("#fpPayError").hidden = false;
        $("#fpPayError").textContent = error.message;
      }
    };
    $("#fpReturnConfirm").onclick = async () => {
      $("#fpReturnError").hidden = true;
      const purchase = state.returnPurchase;
      if (!purchase) return;
      const items = $$("#fpReturnItems [data-item-id]").map((row) => {
        const qty = Number($("[data-qty]", row)?.value || 0);
        if (qty <= 0) return null;
        const batch = $("[data-batch]", row);
        return {
          purchase_item_id: Number(row.dataset.itemId),
          quantity: qty,
          batch_id: batch?.value ? Number(batch.value) : null,
        };
      }).filter(Boolean);
      if (!items.length) {
        $("#fpReturnError").hidden = false;
        $("#fpReturnError").textContent = "أدخل كمية مرتجعة واحدةً على الأقل";
        return;
      }
      try {
        const result = await api(`/purchases/${purchase.id}/returns`, {
          method: "POST",
          body: JSON.stringify({
            items,
            reason: $("#fpReturnReason").value,
            settlement: $("#fpReturnSettlement").value,
            note: $("#fpReturnNote").value,
          }),
        });
        $("#fpReturnDialog").close();
        notice(`تم تسجيل المرتجع ${result.return_no}`);
        openDrawer(purchase.id);
        load();
      } catch (error) {
        $("#fpReturnError").hidden = false;
        $("#fpReturnError").textContent = error.message;
      }
    };
  }

  (async () => {
    try {
      await initMeta();
      bind();
      await load();
    } catch (error) {
      notice(error.message, true);
    }
  })();
})();
