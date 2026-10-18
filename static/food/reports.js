(() => {
  "use strict";
  const root = document.getElementById("foodReports");
  if (!root) return;

  const $ = (sel, within = root) => within.querySelector(sel);
  const $$ = (sel, within = root) => [...within.querySelectorAll(sel)];
  const money = (value) => `${Number(value || 0).toLocaleString("en-IQ")} د.ع`;
  const num = (value) => Number(value || 0).toLocaleString("en-IQ");
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
  const shortDate = (value) => value ? new Date(value).toLocaleDateString("en-IQ") : "—";
  const notice = (message, error = false) => {
    const box = document.getElementById("foodNotice");
    if (!box) return;
    box.textContent = message;
    box.className = `food-notice${error ? " error" : ""}`;
    box.hidden = false;
    clearTimeout(box._timer);
    box._timer = setTimeout(() => { box.hidden = true; }, 4200);
  };

  const state = {
    data: null,
    tab: "sales",
    chart: null,
    mixChart: null,
    topMode: "by_sales",
    sort: { key: null, dir: "desc" },
    query: "",
  };

  const TAB_LABELS = {
    sales: "المبيعات",
    cash: "الوارد اليومي",
    customers: "ديون العملاء",
    suppliers: "ديون الموردين",
    purchases: "المشتريات",
    inventory: "المخزون",
    products: "أفضل المنتجات",
  };

  const AGE_LABELS = {
    "0_30": "0–30 يوم",
    "31_60": "31–60 يوم",
    "61_90": "61–90 يوم",
    "90_plus": "أكثر من 90",
  };

  async function api(path) {
    const response = await fetch(`/food/api${path}`, {
      headers: { "Content-Type": "application/json" },
    });
    const payload = await response.json().catch(() => ({ ok: false, error: "استجابة غير صالحة" }));
    if (!response.ok || !payload.ok) throw new Error(payload.error || "تعذر تحميل التقرير");
    return payload.data;
  }

  function trendHtml(changePct, changeAbs, compareLabel, { invert = false } = {}) {
    const value = changePct != null ? changePct : changeAbs;
    if (value == null || Number.isNaN(Number(value))) {
      return `<span class="fd-trend fd-trend--flat">—</span>`;
    }
    const n = Number(value);
    const up = invert ? n < 0 : n > 0;
    const down = invert ? n > 0 : n < 0;
    const cls = up ? "up" : down ? "down" : "flat";
    const arrow = up ? "↑" : down ? "↓" : "→";
    const label = changePct != null
      ? `${arrow} ${Math.abs(n)}% ${compareLabel || ""}`
      : `${arrow} ${Math.abs(n).toLocaleString("en-IQ")} ${compareLabel || ""}`;
    return `<span class="fd-trend fd-trend--${cls}">${esc(label.trim())}</span>`;
  }

  function setLoading(on) {
    root.classList.toggle("is-loading", on);
    const err = $("#frError");
    if (on && err) err.hidden = true;
  }

  function showError(message) {
    const box = $("#frError");
    if (!box) return;
    const text = box.querySelector("p");
    if (text) text.textContent = message || "تعذر تحميل البيانات";
    box.hidden = false;
  }

  function updateMeta(data) {
    const range = data.range || {};
    $("#frRangeMeta").textContent = `${range.start || "—"} → ${range.end || "—"}`;
    $("#frCompareMeta").textContent = range.compare_label
      ? `مقارنة ${range.compare_label} (${range.compare_start || ""} → ${range.compare_end || ""})`
      : "";
    $("#frTabTitle").textContent = TAB_LABELS[state.tab] || "التقرير";
  }

  function renderKpis(data) {
    const s = data.summary || {};
    const compare = data.range?.compare_label || "";
    const viewProfit = data.permissions?.view_profit !== false && data.profit?.available !== false;
    const cards = [
      {
        key: "sales", title: "صافي المبيعات", icon: "fa-chart-column",
        value: money(s.sales), trend: trendHtml(s.sales_change_pct, null, compare),
      },
      {
        key: "invoices", title: "عدد الفواتير", icon: "fa-receipt",
        value: num(s.invoices), trend: trendHtml(null, s.invoices_change, compare),
      },
      {
        key: "avg", title: "متوسط الفاتورة", icon: "fa-calculator",
        value: money(s.avg_invoice), trend: trendHtml(s.avg_invoice_change_pct, null, compare),
      },
      viewProfit ? {
        key: "profit", title: "الربح التقديري", icon: "fa-coins",
        value: money(s.profit), trend: trendHtml(s.profit_change_pct, null, compare),
      } : null,
      {
        key: "cash", title: "صافي النقد", icon: "fa-wallet",
        value: money(s.net_cash), trend: trendHtml(s.net_cash_change_pct, null, compare),
      },
      {
        key: "purchases", title: "المشتريات", icon: "fa-cart-shopping",
        value: money(s.purchases), trend: trendHtml(s.purchases_change_pct, null, compare, { invert: true }),
      },
    ].filter(Boolean);

    $("#frKpis").innerHTML = cards.map((card) => `
      <article class="fd-kpi" data-kpi="${esc(card.key)}">
        <span class="fd-kpi__icon"><i class="fa ${card.icon}"></i></span>
        <span class="fd-kpi__body">
          <span class="fd-kpi__title">${esc(card.title)}</span>
          <strong class="fd-kpi__value">${card.value}</strong>
          ${card.trend}
        </span>
      </article>`).join("");
  }

  function destroyCharts() {
    if (state.chart) { state.chart.destroy(); state.chart = null; }
    if (state.mixChart) { state.mixChart.destroy(); state.mixChart = null; }
  }

  function renderTrendChart(data) {
    const canvas = $("#frTrendChart");
    const empty = $("#frTrendEmpty");
    if (!canvas) return;
    const points = data.chart?.current || [];
    const previous = data.chart?.previous || [];
    const hasSales = points.some((p) => Number(p.sales) > 0);
    empty.hidden = hasSales;
    canvas.hidden = !hasSales;
    $("#frChartHint").textContent = data.chart?.granularity === "hour"
      ? "حسب ساعات اليوم مقارنة بالفترة السابقة"
      : "حسب أيام الفترة";

    if (state.chart) { state.chart.destroy(); state.chart = null; }
    if (!hasSales || typeof Chart === "undefined") return;

    const datasets = [{
      label: "المبيعات",
      data: points.map((p) => Number(p.sales || 0)),
      borderColor: "#0f766e",
      backgroundColor: (ctx) => {
        const { chart } = ctx;
        const { ctx: c, chartArea } = chart;
        if (!chartArea) return "rgba(15,118,110,.12)";
        const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
        g.addColorStop(0, "rgba(15,118,110,.28)");
        g.addColorStop(1, "rgba(15,118,110,0)");
        return g;
      },
      fill: true,
      tension: 0.35,
      borderWidth: 2.5,
      pointRadius: 0,
      pointHoverRadius: 5,
    }];
    if (previous.length) {
      datasets.push({
        label: data.chart?.compare_label || "الفترة السابقة",
        data: previous.map((p) => Number(p.sales || 0)),
        borderColor: "rgba(102,122,121,.55)",
        borderDash: [6, 5],
        backgroundColor: "transparent",
        fill: false,
        tension: 0.35,
        borderWidth: 2,
        pointRadius: 0,
      });
    }

    state.chart = new Chart(canvas, {
      type: "line",
      data: { labels: points.map((p) => p.label), datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: previous.length > 0, position: "bottom", rtl: true, labels: { boxWidth: 12, font: { family: "Tajawal" } } },
          tooltip: {
            rtl: true,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${Number(ctx.raw || 0).toLocaleString("en-IQ")} د.ع`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 8, font: { family: "Tajawal", size: 11 } } },
          y: {
            beginAtZero: true,
            ticks: {
              callback: (v) => Number(v).toLocaleString("en-IQ"),
              font: { family: "Tajawal", size: 11 },
            },
            grid: { color: "rgba(15,118,110,.08)" },
          },
        },
      },
    });
  }

  function renderMixChart(data) {
    const canvas = $("#frMixChart");
    if (!canvas || typeof Chart === "undefined") return;
    if (state.mixChart) { state.mixChart.destroy(); state.mixChart = null; }
    const sales = data.sales || {};
    const values = [sales.retail || 0, sales.wholesale || 0, sales.mixed || 0];
    const total = values.reduce((a, b) => a + b, 0);
    $("#frMixEmpty").hidden = total > 0;
    canvas.hidden = total <= 0;
    if (total <= 0) return;

    state.mixChart = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: ["مفرد", "جملة", "مختلط"],
        datasets: [{
          data: values,
          backgroundColor: ["#0f766e", "#14b8a6", "#99f6e4"],
          borderWidth: 0,
          hoverOffset: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: { position: "bottom", rtl: true, labels: { boxWidth: 10, font: { family: "Tajawal", size: 12 } } },
          tooltip: {
            rtl: true,
            callbacks: {
              label: (ctx) => {
                const pct = total ? Math.round((ctx.raw / total) * 100) : 0;
                return `${ctx.label}: ${Number(ctx.raw).toLocaleString("en-IQ")} د.ع (${pct}%)`;
              },
            },
          },
        },
      },
    });
  }

  function renderBreakdown(data) {
    const sales = data.sales || {};
    const cash = data.cash || {};
    const debts = data.customer_debts || {};
    const suppliers = data.supplier_debts || {};
    const totalMix = (sales.retail || 0) + (sales.wholesale || 0) + (sales.mixed || 0) || 1;

    $("#frSalesBreakdown").innerHTML = `
      <div class="fr-stat-grid">
        <div><span>إجمالي قبل المرتجع</span><b>${money(sales.gross)}</b></div>
        <div><span>المرتجعات</span><b class="fr-neg">${money(sales.returns)}</b></div>
        <div><span>صافي المبيعات</span><b>${money(sales.total)}</b></div>
        <div><span>نقدي / آجل</span><b>${money(sales.cash)} / ${money(sales.credit)}</b></div>
      </div>
      <div class="fd-type-bars" style="padding:12px 0 0">
        ${[
          ["مفرد", sales.retail, "#0f766e"],
          ["جملة", sales.wholesale, "#14b8a6"],
          ["مختلط", sales.mixed, "#5eead4"],
        ].map(([label, value, color]) => `
          <div class="fd-type">
            <div class="fd-type__top"><span>${label}</span><strong>${money(value)}</strong></div>
            <div class="fd-type__bar"><i style="width:${Math.min(100, (Number(value) / totalMix) * 100)}%;background:${color}"></i></div>
          </div>`).join("")}
      </div>`;

    $("#frCashSnapshot").innerHTML = `
      <div class="fd-cash-list">
        <div class="fd-cash-row fd-cash-row--in"><span>مبيعات نقدية</span><b>${money(cash.cash_sales)}</b></div>
        <div class="fd-cash-row fd-cash-row--in"><span>قبض عملاء</span><b>${money(cash.customer_receipts)}</b></div>
        <div class="fd-cash-row fd-cash-row--out"><span>تسديد موردين</span><b>${money(cash.supplier_payments)}</b></div>
        <div class="fd-cash-row fd-cash-row--out"><span>مصروفات</span><b>${money(cash.expenses)}</b></div>
        <div class="fd-cash-highlight"><span>صافي حركة النقد</span><strong>${money(cash.net)}</strong>
          ${trendHtml(cash.change_pct, null, data.range?.compare_label || "")}
        </div>
      </div>`;

    const aging = debts.aging || {};
    $("#frDebtsSnapshot").innerHTML = `
      <div class="fr-debt-pair">
        <div><span>ذمم العملاء</span><strong>${money(debts.total)}</strong><small>${num(debts.count)} عميل</small></div>
        <div><span>ذمم الموردين</span><strong>${money(suppliers.total)}</strong><small>${num(suppliers.count)} مورد</small></div>
      </div>
      <div class="fr-aging">
        ${Object.entries(AGE_LABELS).map(([key, label]) => `
          <div><span>${label}</span><b>${money(aging[key] || 0)}</b></div>`).join("")}
      </div>`;
  }

  function tableWrap(headers, rowsHtml, { searchable = true } = {}) {
    const cols = headers.length;
    return `
      <div class="fr-table-tools">
        ${searchable ? `<label class="fr-search"><i class="fa fa-search"></i><input id="frTableSearch" type="search" placeholder="بحث في الجدول..." value="${esc(state.query)}"></label>` : "<span></span>"}
        <span class="fr-table-count">${num(rowsHtml.length)} صف</span>
      </div>
      <div class="food-table-wrap fr-table-wrap"><table class="food-table fr-table"><thead><tr>${headers.map((h) => {
        if (typeof h === "string") return `<th>${h}</th>`;
        return `<th data-sort="${esc(h.key)}" class="${state.sort.key === h.key ? `sorted ${state.sort.dir}` : ""}">${esc(h.label)} <i class="fa fa-sort"></i></th>`;
      }).join("")}</tr></thead><tbody>${rowsHtml.length ? rowsHtml.join("") : `<tr><td colspan="${cols}" class="food-empty">لا توجد بيانات</td></tr>`}</tbody></table></div>`;
  }

  function filterRows(rows, keys) {
    const q = state.query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) => keys.some((key) => String(row[key] ?? "").toLowerCase().includes(q)));
  }

  function sortRows(rows, key, numeric = false) {
    if (!key) return rows;
    const dir = state.sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (numeric || typeof av === "number" || typeof bv === "number") {
        return (Number(av || 0) - Number(bv || 0)) * dir;
      }
      return String(av ?? "").localeCompare(String(bv ?? ""), "ar") * dir;
    });
  }

  function bindTableTools(rawRows, rebuild) {
    const search = $("#frTableSearch");
    if (search) {
      search.oninput = () => {
        state.query = search.value;
        rebuild();
      };
    }
    $$(".fr-table th[data-sort]").forEach((th) => {
      th.onclick = () => {
        const key = th.dataset.sort;
        if (state.sort.key === key) state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
        else { state.sort.key = key; state.sort.dir = "desc"; }
        rebuild();
      };
    });
  }

  function renderSalesTab(data) {
    const build = () => {
      let rows = filterRows(data.sales.rows || [], ["invoice_no", "customer", "sale_mode", "sale_type"]);
      rows = sortRows(rows, state.sort.key || "created_at", state.sort.key && state.sort.key !== "customer" && state.sort.key !== "sale_mode" && state.sort.key !== "sale_type" && state.sort.key !== "invoice_no");
      const html = rows.map((x) => `<tr>
        <td>${shortDate(x.created_at)}</td>
        <td><a class="fr-link" href="/food/orders?q=${encodeURIComponent(x.invoice_no || x.id)}">${esc(x.invoice_no || x.id)}</a></td>
        <td>${esc(x.customer)}</td>
        <td><span class="food-badge">${esc(x.sale_mode)}</span></td>
        <td>${esc(x.sale_type || "—")}</td>
        <td>${money(x.total)}</td>
        <td>${money(x.returned)}</td>
        <td>${money(x.paid)}</td>
        <td>${money(x.debt)}</td>
      </tr>`);
      const returns = data.sales.return_rows || [];
      $("#frContent").innerHTML = `
        ${tableWrap([
          { label: "التاريخ", key: "created_at" },
          { label: "الفاتورة", key: "invoice_no" },
          { label: "العميل", key: "customer" },
          { label: "النوع", key: "sale_mode" },
          { label: "الدفع", key: "sale_type" },
          { label: "الإجمالي", key: "total" },
          { label: "مرتجع", key: "returned" },
          { label: "المدفوع", key: "paid" },
          { label: "الآجل", key: "debt" },
        ], html)}
        ${returns.length ? `<h3 class="fr-subhead">مرتجعات الفترة</h3>${tableWrap(["التاريخ", "الفاتورة", "العميل", "المبلغ"], returns.map((x) => `<tr><td>${shortDate(x.created_at)}</td><td>${esc(x.invoice_no)}</td><td>${esc(x.customer)}</td><td>${money(x.total)}</td></tr>`), { searchable: false })}` : ""}`;
      bindTableTools(data.sales.rows || [], build);
    };
    build();
  }

  function renderCashTab(data) {
    const c = data.cash || {};
    $("#frContent").innerHTML = `
      <div class="fr-cash-grid">
        <article class="fr-panel">
          <h3>الوارد</h3>
          <div class="fd-cash-list">
            <div class="fd-cash-row fd-cash-row--in"><span>مبيعات نقدية / بطاقة</span><b>${money(c.cash_sales)}</b></div>
            <div class="fd-cash-row fd-cash-row--in"><span>قبض من العملاء</span><b>${money(c.customer_receipts)}</b></div>
            <div class="fd-cash-row"><span>إجمالي الوارد</span><b>${money(c.total_in)}</b></div>
          </div>
        </article>
        <article class="fr-panel">
          <h3>الصادر</h3>
          <div class="fd-cash-list">
            <div class="fd-cash-row fd-cash-row--out"><span>تسديد موردين</span><b>${money(c.supplier_payments)}</b></div>
            <div class="fd-cash-row fd-cash-row--out"><span>مصروفات التشغيل</span><b>${money(c.expenses)}</b></div>
            <div class="fd-cash-row"><span>إجمالي الصادر</span><b>${money(c.total_out)}</b></div>
          </div>
        </article>
        <article class="fr-panel fr-panel--accent">
          <h3>صافي الصندوق</h3>
          <strong class="fr-big">${money(c.net)}</strong>
          ${trendHtml(c.change_pct, null, data.range?.compare_label || "")}
          ${c.opening_balance != null ? `<div class="fr-stat-grid" style="margin-top:14px">
            <div><span>افتتاحي</span><b>${money(c.opening_balance)}</b></div>
            <div><span>متوقع</span><b>${c.expected_balance != null ? money(c.expected_balance) : "—"}</b></div>
            <div><span>فعلي</span><b>${c.actual_balance != null ? money(c.actual_balance) : "—"}</b></div>
            <div><span>الفرق</span><b class="${c.difference ? "fr-neg" : ""}">${c.difference != null ? money(c.difference) : "—"}</b></div>
          </div>` : `<p class="fr-hint">جلسة الصندوق تظهر عند اختيار يوم واحد.</p>`}
        </article>
      </div>`;
  }

  function renderAgingBars(aging) {
    const total = Object.values(aging || {}).reduce((a, b) => a + Number(b || 0), 0) || 1;
    return `<div class="fr-aging-bars">${Object.entries(AGE_LABELS).map(([key, label]) => {
      const value = Number((aging || {})[key] || 0);
      return `<div><div class="fr-aging-bars__top"><span>${label}</span><b>${money(value)}</b></div>
        <div class="fd-type__bar"><i style="width:${Math.min(100, (value / total) * 100)}%;background:#0f766e"></i></div></div>`;
    }).join("")}</div>`;
  }

  function renderCustomersTab(data) {
    const build = () => {
      let rows = filterRows(data.customer_debts.rows || [], ["name", "phone"]);
      rows = sortRows(rows, state.sort.key || "debt", true);
      const html = rows.map((x) => `<tr>
        <td><b>${esc(x.name)}</b></td>
        <td>${esc(x.phone || "—")}</td>
        <td>${money(x.debt)}</td>
        <td>${num(x.age_days)} يوم</td>
        <td><span class="food-badge ${x.age_bucket === "90_plus" || x.age_bucket === "61_90" ? "warn" : ""}">${esc(AGE_LABELS[x.age_bucket] || x.age_bucket)}</span></td>
        <td>${shortDate(x.last_invoice)}</td>
        <td>${shortDate(x.last_receipt)}</td>
        <td>${shortDate(x.oldest_debt)}</td>
      </tr>`);
      $("#frContent").innerHTML = `
        ${renderAgingBars(data.customer_debts.aging)}
        ${tableWrap([
          { label: "العميل", key: "name" },
          { label: "الهاتف", key: "phone" },
          { label: "الرصيد", key: "debt" },
          { label: "العمر", key: "age_days" },
          { label: "الشريحة", key: "age_bucket" },
          { label: "آخر فاتورة", key: "last_invoice" },
          { label: "آخر قبض", key: "last_receipt" },
          { label: "أقدم دين", key: "oldest_debt" },
        ], html)}`;
      bindTableTools(data.customer_debts.rows || [], build);
    };
    build();
  }

  function renderSuppliersTab(data) {
    const build = () => {
      let rows = filterRows((data.supplier_debts.rows || []).filter((r) => Number(r.debt) > 0), ["name"]);
      rows = sortRows(rows, state.sort.key || "debt", true);
      const html = rows.map((x) => `<tr>
        <td><b>${esc(x.name)}</b></td>
        <td>${money(x.debt)}</td>
        <td>${num(x.age_days)} يوم</td>
        <td><span class="food-badge ${x.age_bucket === "90_plus" || x.age_bucket === "61_90" ? "warn" : ""}">${esc(AGE_LABELS[x.age_bucket] || x.age_bucket)}</span></td>
        <td>${shortDate(x.last_purchase)}</td>
        <td>${shortDate(x.last_payment)}</td>
        <td>${shortDate(x.oldest_due)}</td>
      </tr>`);
      $("#frContent").innerHTML = `
        ${renderAgingBars(data.supplier_debts.aging)}
        ${tableWrap([
          { label: "المورد", key: "name" },
          { label: "الرصيد", key: "debt" },
          { label: "العمر", key: "age_days" },
          { label: "الشريحة", key: "age_bucket" },
          { label: "آخر شراء", key: "last_purchase" },
          { label: "آخر تسديد", key: "last_payment" },
          { label: "أقدم استحقاق", key: "oldest_due" },
        ], html)}`;
      bindTableTools(data.supplier_debts.rows || [], build);
    };
    build();
  }

  function renderPurchasesTab(data) {
    const build = () => {
      let rows = filterRows(data.purchases.rows || [], ["invoice_no", "supplier"]);
      rows = sortRows(rows, state.sort.key || "created_at", state.sort.key && state.sort.key !== "supplier" && state.sort.key !== "invoice_no");
      const html = rows.map((x) => `<tr>
        <td>${shortDate(x.created_at)}</td>
        <td>${esc(x.invoice_no || x.id)}</td>
        <td>${esc(x.supplier)}</td>
        <td>${money(x.total)}</td>
        <td>${money(x.paid)}</td>
        <td>${money(x.remaining)}</td>
      </tr>`);
      $("#frContent").innerHTML = `
        <div class="fr-stat-grid fr-stat-grid--inline">
          <div><span>إجمالي المشتريات</span><b>${money(data.purchases.total)}</b></div>
          <div><span>المدفوع</span><b>${money(data.purchases.paid)}</b></div>
          <div><span>المتبقي</span><b>${money(data.purchases.remaining)}</b></div>
          <div><span>عدد الفواتير</span><b>${num(data.purchases.count)}</b></div>
        </div>
        ${tableWrap([
          { label: "التاريخ", key: "created_at" },
          { label: "الفاتورة", key: "invoice_no" },
          { label: "المورد", key: "supplier" },
          { label: "الإجمالي", key: "total" },
          { label: "المدفوع", key: "paid" },
          { label: "المتبقي", key: "remaining" },
        ], html)}`;
      bindTableTools(data.purchases.rows || [], build);
    };
    build();
  }

  function renderInventoryTab(data) {
    const inv = data.inventory || {};
    $("#frContent").innerHTML = `
      <div class="fr-stat-grid fr-stat-grid--inline">
        <div><span>قيمة المخزون</span><b>${money(inv.value)}</b></div>
        <div><span>أصناف متتبعة</span><b>${num(inv.sku_count)}</b></div>
        <div><span>ناقصة</span><b class="fr-neg">${num((inv.low_stock || []).length)}</b></div>
        <div><span>نافدة</span><b class="fr-neg">${num((inv.out_of_stock || []).length)}</b></div>
      </div>
      <div class="fr-split">
        <section>
          <h3 class="fr-subhead">المواد الناقصة</h3>
          ${tableWrap(["المنتج", "النوع", "المتوفر", "الحد"], (inv.low_stock || []).map((x) =>
            `<tr><td>${esc(x.product_name)}</td><td>${esc(x.variant_name)}</td><td><span class="food-badge warn">${x.stock_base}</span></td><td>${x.minimum_stock}</td></tr>`), { searchable: false })}
        </section>
        <section>
          <h3 class="fr-subhead">الأكثر حركة في الفترة</h3>
          ${tableWrap(["المنتج", "النوع", "حركة أساسية"], (inv.top_movement || []).map((x) =>
            `<tr><td>${esc(x.product)}</td><td>${esc(x.variant)}</td><td>${num(x.quantity_base)}</td></tr>`), { searchable: false })}
        </section>
      </div>`;
  }

  function renderProductsTab(data) {
    const viewProfit = data.permissions?.view_profit !== false && data.profit?.available !== false;
    const mode = state.topMode;
    const rows = (data.top_products?.[mode] || data.top_products?.by_sales || []);
    $("#frContent").innerHTML = `
      <div class="fd-mini-tabs fr-top-tabs" role="tablist">
        <button type="button" data-top="by_sales" class="${mode === "by_sales" ? "active" : ""}">حسب القيمة</button>
        <button type="button" data-top="by_quantity" class="${mode === "by_quantity" ? "active" : ""}">حسب الكمية</button>
        ${viewProfit ? `<button type="button" data-top="by_profit" class="${mode === "by_profit" ? "active" : ""}">حسب الربح</button>` : ""}
      </div>
      ${tableWrap(
        viewProfit && mode === "by_profit"
          ? ["#", "المنتج", "النوع", "الكمية", "المبيعات", "الربح"]
          : ["#", "المنتج", "النوع", "الكمية", "المبيعات", ...(viewProfit ? ["الربح"] : [])],
        rows.map((x, i) => `<tr>
          <td>${i + 1}</td>
          <td><b>${esc(x.product)}</b></td>
          <td>${esc(x.variant || "—")}</td>
          <td>${num(x.quantity_base)}</td>
          <td>${money(x.sales)}</td>
          ${viewProfit ? `<td>${money(x.profit)}</td>` : ""}
        </tr>`),
        { searchable: false },
      )}`;
    $$("[data-top]").forEach((btn) => {
      btn.onclick = () => {
        state.topMode = btn.dataset.top;
        renderProductsTab(data);
      };
    });
  }

  function renderTabCards(data) {
    const target = $("#frTabCards");
    if (!target) return;
    const map = {
      sales: [
        ["صافي المبيعات", data.sales.total],
        ["عدد الفواتير", data.sales.count, true],
        ["متوسط الفاتورة", data.sales.avg_invoice],
        ["المرتجعات", data.sales.returns],
        ["المفرد", data.sales.retail],
        ["الجملة", data.sales.wholesale],
        ["المختلط", data.sales.mixed],
        ["نقدي", data.sales.cash],
        ["آجل", data.sales.credit],
      ],
      cash: [
        ["مبيعات نقدية", data.cash.cash_sales],
        ["قبض عملاء", data.cash.customer_receipts],
        ["إجمالي الوارد", data.cash.total_in],
        ["تسديد موردين", data.cash.supplier_payments],
        ["مصروفات", data.cash.expenses],
        ["صافي النقد", data.cash.net],
      ],
      customers: [
        ["إجمالي ديون العملاء", data.customer_debts.total],
        ["عملاء لديهم دين", data.customer_debts.count, true],
      ],
      suppliers: [
        ["إجمالي ديون الموردين", data.supplier_debts.total],
        ["موردون لديهم دين", data.supplier_debts.count, true],
      ],
      purchases: [
        ["إجمالي المشتريات", data.purchases.total],
        ["عدد الفواتير", data.purchases.count, true],
        ["المدفوع", data.purchases.paid],
        ["المتبقي", data.purchases.remaining],
      ],
      inventory: [
        ["قيمة المخزون", data.inventory.value],
        ["أصناف", data.inventory.sku_count, true],
        ["ناقصة", (data.inventory.low_stock || []).length, true],
        ["نافدة", (data.inventory.out_of_stock || []).length, true],
      ],
      products: [
        ["أصناف مباعة", (data.top_products?.by_sales || []).length, true],
        ["صافي المبيعات", data.sales.total],
        ...(data.profit?.available ? [["الربح", data.profit.value], ["هامش %", data.profit.margin_pct, true]] : []),
      ],
    };
    const items = map[state.tab] || [];
    target.innerHTML = items.map(([label, value, count]) =>
      `<article class="food-metric"><span>${esc(label)}</span><strong>${count ? num(value) : money(value)}</strong></article>`
    ).join("");
  }

  function renderDetail() {
    const data = state.data;
    if (!data) return;
    state.query = "";
    state.sort = { key: null, dir: "desc" };
    updateMeta(data);
    renderTabCards(data);
    const overview = $("#frOverview");
    if (overview) overview.hidden = state.tab !== "sales" && state.tab !== "products";
    if (state.tab === "sales") {
      renderTrendChart(data);
      renderMixChart(data);
      renderBreakdown(data);
      renderSalesTab(data);
    } else if (state.tab === "cash") {
      destroyCharts();
      renderCashTab(data);
    } else if (state.tab === "customers") {
      destroyCharts();
      renderCustomersTab(data);
    } else if (state.tab === "suppliers") {
      destroyCharts();
      renderSuppliersTab(data);
    } else if (state.tab === "purchases") {
      destroyCharts();
      renderPurchasesTab(data);
    } else if (state.tab === "inventory") {
      destroyCharts();
      renderInventoryTab(data);
    } else if (state.tab === "products") {
      destroyCharts();
      renderTrendChart(data);
      renderMixChart(data);
      renderBreakdown(data);
      renderProductsTab(data);
    }
  }

  function currentRowsForExport() {
    const data = state.data;
    if (!data) return { headers: [], rows: [] };
    if (state.tab === "sales") {
      return {
        headers: ["التاريخ", "الفاتورة", "العميل", "النوع", "الدفع", "الإجمالي", "مرتجع", "المدفوع", "الآجل"],
        rows: (data.sales.rows || []).map((x) => [
          shortDate(x.created_at), x.invoice_no || x.id, x.customer, x.sale_mode, x.sale_type,
          x.total, x.returned, x.paid, x.debt,
        ]),
      };
    }
    if (state.tab === "customers") {
      return {
        headers: ["العميل", "الهاتف", "الرصيد", "عمر الدين", "الشريحة"],
        rows: (data.customer_debts.rows || []).map((x) => [x.name, x.phone || "", x.debt, x.age_days, AGE_LABELS[x.age_bucket] || x.age_bucket]),
      };
    }
    if (state.tab === "suppliers") {
      return {
        headers: ["المورد", "الرصيد", "عمر الدين", "الشريحة"],
        rows: (data.supplier_debts.rows || []).filter((x) => x.debt > 0).map((x) => [x.name, x.debt, x.age_days, AGE_LABELS[x.age_bucket] || x.age_bucket]),
      };
    }
    if (state.tab === "purchases") {
      return {
        headers: ["التاريخ", "الفاتورة", "المورد", "الإجمالي", "المدفوع", "المتبقي"],
        rows: (data.purchases.rows || []).map((x) => [shortDate(x.created_at), x.invoice_no || x.id, x.supplier, x.total, x.paid, x.remaining]),
      };
    }
    if (state.tab === "products") {
      const rows = data.top_products?.[state.topMode] || data.top_products?.by_sales || [];
      return {
        headers: ["المنتج", "النوع", "الكمية", "المبيعات", "الربح"],
        rows: rows.map((x) => [x.product, x.variant, x.quantity_base, x.sales, x.profit ?? ""]),
      };
    }
    if (state.tab === "cash") {
      const c = data.cash;
      return {
        headers: ["البيان", "المبلغ"],
        rows: [
          ["مبيعات نقدية", c.cash_sales],
          ["قبض عملاء", c.customer_receipts],
          ["تسديد موردين", c.supplier_payments],
          ["مصروفات", c.expenses],
          ["صافي النقد", c.net],
        ],
      };
    }
    return {
      headers: ["المنتج", "النوع", "المتوفر", "الحد"],
      rows: (data.inventory.low_stock || []).map((x) => [x.product_name, x.variant_name, x.stock_base, x.minimum_stock]),
    };
  }

  function exportCsv() {
    const { headers, rows } = currentRowsForExport();
    if (!rows.length) return notice("لا توجد بيانات للتصدير", true);
    const escapeCell = (cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`;
    const lines = [headers.map(escapeCell).join(","), ...rows.map((row) => row.map(escapeCell).join(","))];
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `finora-food-${state.tab}-${state.data?.range?.start || "report"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    notice("تم تصدير CSV");
  }

  function printReport() {
    window.print();
  }

  async function loadReport() {
    const range = $("#frRange").value;
    const params = new URLSearchParams({ range });
    if (range === "custom") {
      params.set("start", $("#frStart").value);
      params.set("end", $("#frEnd").value);
    }
    setLoading(true);
    try {
      state.data = await api(`/reports?${params}`);
      renderKpis(state.data);
      renderDetail();
    } catch (error) {
      showError(error.message);
      notice(error.message, true);
    } finally {
      setLoading(false);
    }
  }

  function syncCustomRange() {
    const custom = $("#frRange").value === "custom";
    $("#frCustomRange").hidden = !custom;
    $("#frStart").disabled = !custom;
    $("#frEnd").disabled = !custom;
  }

  function init() {
    const today = new Date().toISOString().slice(0, 10);
    $("#frStart").value = today;
    $("#frEnd").value = today;
    syncCustomRange();
    $("#frRange").onchange = () => { syncCustomRange(); if ($("#frRange").value !== "custom") loadReport().catch(() => {}); };
    $("#frApply").onclick = () => loadReport().catch((e) => notice(e.message, true));
    $("#frRefresh").onclick = () => loadReport().catch((e) => notice(e.message, true));
    $("#frExport").onclick = exportCsv;
    $("#frPrint").onclick = printReport;
    $$("[data-tabs='reports'] button").forEach((btn) => {
      btn.onclick = () => {
        $$("[data-tabs='reports'] button").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        state.tab = btn.dataset.tab;
        renderDetail();
      };
    });
    loadReport().catch((e) => notice(e.message, true));
  }

  init();
})();
