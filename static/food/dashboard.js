(() => {
  "use strict";
  const root = document.getElementById("foodDashboard");
  if (!root) return;

  const $ = (sel, within = root) => within.querySelector(sel);
  const $$ = (sel, within = root) => [...within.querySelectorAll(sel)];
  const money = (value) => `${Number(value || 0).toLocaleString("en-IQ")} د.ع`;
  const num = (value) => Number(value || 0).toLocaleString("en-IQ");
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);

  const state = { data: null, period: "today", topTab: "best", chart: null, timer: null };

  async function api(path) {
    const response = await fetch(`/food/api${path}`, {
      headers: { "Content-Type": "application/json" },
    });
    const payload = await response.json().catch(() => ({ ok: false, error: "استجابة غير صالحة" }));
    if (!response.ok || !payload.ok) throw new Error(payload.error || "تعذر تحميل لوحة القيادة");
    return payload.data;
  }

  function setLoading(on) {
    root.classList.toggle("is-loading", on);
    if (on) $("#fdError").hidden = true;
  }

  function showError(message) {
    const box = $("#fdError");
    const text = box.querySelector("p");
    if (text) text.textContent = message || "تعذر تحميل البيانات";
    box.hidden = false;
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

  function renderKpis(data) {
    const k = data.kpis || {};
    const compare = data.period?.compare_label || "";
    const isToday = data.period?.key === "today";
    const viewProfit = data.permissions?.view_profit !== false && k.profit?.available !== false;
    const salesTitle = isToday ? "مبيعات اليوم" : "مبيعات الفترة";
    const profitTitle = isToday ? "ربح اليوم" : "ربح الفترة";
    const purchaseTitle = isToday ? "مشتريات اليوم" : "مشتريات الفترة";
    const cards = [
      {
        key: "sales", title: salesTitle, icon: "fa-chart-column",
        value: money(k.sales?.value), trend: trendHtml(k.sales?.change_pct, null, compare),
        href: k.sales?.href || "/food/orders",
      },
      viewProfit ? {
        key: "profit", title: profitTitle, icon: "fa-coins",
        value: money(k.profit?.value), trend: trendHtml(k.profit?.change_pct, null, compare),
        href: k.profit?.href || "/food/reports",
      } : null,
      {
        key: "purchases", title: purchaseTitle, icon: "fa-cart-shopping",
        value: money(k.purchases?.value), trend: trendHtml(k.purchases?.change_pct, null, compare, { invert: true }),
        href: k.purchases?.href || "/food/purchases",
      },
      {
        key: "cash", title: "صافي النقد", icon: "fa-wallet",
        value: money(k.net_cash?.value), trend: trendHtml(k.net_cash?.change_pct, null, compare),
        href: k.net_cash?.href || "/food/finance",
      },
      {
        key: "invoices", title: "عدد الفواتير", icon: "fa-receipt",
        value: num(k.invoices?.value), trend: trendHtml(null, k.invoices?.change, compare),
        href: k.invoices?.href || "/food/orders",
      },
      {
        key: "avg", title: "متوسط الفاتورة", icon: "fa-calculator",
        value: money(k.avg_invoice?.value), trend: trendHtml(k.avg_invoice?.change_pct, null, compare),
        href: k.avg_invoice?.href || "/food/orders",
      },
    ].filter(Boolean);

    $("#fdKpis").innerHTML = cards.map((card) => `
      <a class="fd-kpi" href="${esc(card.href)}" data-kpi="${esc(card.key)}">
        <span class="fd-kpi__icon"><i class="fa ${card.icon}"></i></span>
        <span class="fd-kpi__body">
          <span class="fd-kpi__title">${esc(card.title)}</span>
          <strong class="fd-kpi__value">${card.value}</strong>
          ${card.trend}
        </span>
      </a>`).join("");
  }

  function renderChart(data) {
    const points = data.sales_chart?.current || [];
    const previous = data.sales_chart?.previous || [];
    const empty = $("#fdChartEmpty");
    const canvas = $("#fdSalesChart");
    const hasSales = points.some((p) => Number(p.sales) > 0);
    empty.hidden = hasSales;
    canvas.hidden = !hasSales;
    $("#fdChartHint").textContent = data.sales_chart?.granularity === "hour"
      ? "حسب ساعات اليوم"
      : "حسب أيام الفترة";

    if (state.chart) {
      state.chart.destroy();
      state.chart = null;
    }
    if (!hasSales || typeof Chart === "undefined") return;

    const labels = points.map((p) => p.label);
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
        label: data.sales_chart?.compare_label || "الفترة السابقة",
        data: previous.map((p) => Number(p.sales || 0)),
        borderColor: "rgba(102,122,121,.55)",
        borderDash: [6, 5],
        backgroundColor: "transparent",
        fill: false,
        tension: 0.35,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 4,
      });
    }

    state.chart = new Chart(canvas, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: previous.length > 0, position: "bottom", labels: { boxWidth: 12, font: { family: "Tajawal", size: 11 } } },
          tooltip: {
            rtl: true,
            titleFont: { family: "Tajawal" },
            bodyFont: { family: "Tajawal" },
            callbacks: {
              title: (items) => items[0]?.label || "",
              label: (item) => {
                const point = points[item.dataIndex] || {};
                if (item.datasetIndex === 0) {
                  return [
                    `${Number(item.raw || 0).toLocaleString("en-IQ")} د.ع`,
                    point.invoices != null ? `${point.invoices} فاتورة` : "",
                  ].filter(Boolean);
                }
                return `${Number(item.raw || 0).toLocaleString("en-IQ")} د.ع`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { font: { family: "Tajawal", size: 10 }, color: "#66777c", maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
          },
          y: {
            beginAtZero: true,
            grid: { color: "rgba(229,238,238,.9)" },
            ticks: {
              font: { family: "Tajawal", size: 10 },
              color: "#66777c",
              callback: (v) => Number(v).toLocaleString("en-IQ"),
            },
          },
        },
      },
    });
  }

  function renderInventory(data) {
    const inv = data.inventory || {};
    const rows = [
      { label: "مواد نافدة", value: inv.out_of_stock, tone: "danger", href: "/food/inventory" },
      { label: "مواد قليلة المخزون", value: inv.low_stock, tone: "warn", href: "/food/inventory" },
      { label: "مواد قاربت صلاحيتها", value: inv.expiry_soon, tone: "amber", href: "/food/inventory" },
      { label: "مواد منتهية الصلاحية", value: inv.expired, tone: "dark", href: "/food/inventory" },
    ];
    $("#fdInventoryStatus").innerHTML = rows.map((row) => `
      <a class="fd-status fd-status--${row.tone}" href="${row.href}">
        <span>${esc(row.label)}</span>
        <strong>${num(row.value)}</strong>
      </a>`).join("");

    const profitBlock = data.permissions?.view_profit && inv.expected_profit != null
      ? `<div><span>الربح المتوقع</span><b>${money(inv.expected_profit)}</b></div>`
      : "";
    $("#fdInventoryValue").innerHTML = `
      <div class="fd-inv-value__main">
        <span>قيمة المخزون (تكلفة)</span>
        <strong>${money(inv.cost_value)}</strong>
      </div>
      <div class="fd-inv-value__grid">
        <div><span>سعر التكلفة</span><b>${money(inv.cost_value)}</b></div>
        <div><span>قيمة البيع المتوقعة</span><b>${money(inv.sell_value)}</b></div>
        ${profitBlock}
      </div>`;
  }

  function renderSalesTypes(data) {
    const t = data.sales_by_type || {};
    const total = Number(t.total || 0) || 1;
    const rows = [
      { key: "retail", label: "مفرد", value: t.retail, href: "/food/orders?sale_type=RETAIL", color: "#0f766e" },
      { key: "wholesale", label: "جملة", value: t.wholesale, href: "/food/orders?sale_type=WHOLESALE", color: "#368AE6" },
      { key: "mixed", label: "مختلط", value: t.mixed, href: "/food/orders?sale_type=MIXED", color: "#66777C" },
    ];
    $("#fdSalesTypes").innerHTML = rows.map((row) => {
      const pct = Math.round((Number(row.value || 0) / total) * 1000) / 10;
      return `<a class="fd-type" href="${row.href}">
        <div class="fd-type__top"><span>${esc(row.label)}</span><b>${money(row.value)}</b></div>
        <div class="fd-type__bar"><i style="width:${pct}%;background:${row.color}"></i></div>
        <small>${pct}%</small>
      </a>`;
    }).join("") + `<div class="fd-type-total"><span>الإجمالي</span><strong>${money(t.total)}</strong></div>`;
  }

  function renderCash(data) {
    const c = data.cash_flow || {};
    const rows = [
      { label: "رصيد افتتاحي", value: c.opening_balance, tone: "muted", emptyHint: "سجّل الافتتاح من المالية" },
      { label: "مبيعات نقدية", value: c.cash_sales, tone: "in", prefix: "+" },
      { label: "قبض من عملاء", value: c.customer_receipts, tone: "in", prefix: "+" },
      { label: "تسديد للموردين", value: c.supplier_payments, tone: "out", prefix: "-" },
      { label: "مصروفات", value: c.expenses, tone: "out", prefix: "-" },
    ];
    const lines = rows.map((row) => {
      if (row.value == null) {
        return `<div class="fd-cash-row fd-cash-row--na"><span>${esc(row.label)}</span><em>${esc(row.emptyHint || "—")}</em></div>`;
      }
      const signed = `${row.prefix || ""}${Number(row.value || 0).toLocaleString("en-IQ")} د.ع`;
      return `<div class="fd-cash-row fd-cash-row--${row.tone}"><span>${esc(row.label)}</span><b>${signed}</b></div>`;
    }).join("");
    let highlight = "";
    if (c.expected_balance != null) {
      highlight += `<div class="fd-cash-highlight"><span>الرصيد المتوقع</span><strong>${money(c.expected_balance)}</strong></div>`;
    } else {
      highlight += `<div class="fd-cash-highlight"><span>صافي حركة النقد</span><strong>${money(c.net)}</strong><small>بدون رصيد افتتاحي — سجّله من صفحة المالية</small></div>`;
    }
    if (c.actual_balance != null) {
      highlight += `<div class="fd-cash-highlight" style="margin-top:8px"><span>الرصيد الفعلي</span><strong>${money(c.actual_balance)}</strong></div>`;
    }
    if (c.difference != null && Number(c.difference) !== 0) {
      highlight += `<div class="fd-cash-highlight" style="margin-top:8px;background:#fff1f1"><span>فرق الصندوق</span><strong style="color:#b91c1c">${money(c.difference)}</strong></div>`;
    }
    $("#fdCashFlow").innerHTML = lines + highlight;
  }

  function renderDebts(data) {
    const r = data.receivables || {};
    const p = data.payables || {};
    $("#fdDebts").innerHTML = `
      <div class="fd-debt-block">
        <h3>ديون العملاء</h3>
        <div class="fd-debt-metrics">
          <div><span>إجمالي</span><b>${money(r.total)}</b></div>
          <div><span>متأخرة</span><b class="is-danger">${money(r.overdue)}</b></div>
          <div><span>عدد العملاء</span><b>${num(r.count)}</b></div>
        </div>
        <a class="food-ghost" href="${esc(r.href || "/food/customers")}">عرض العملاء</a>
      </div>
      <div class="fd-debt-block fd-debt-block--out">
        <h3>ديون الموردين</h3>
        <div class="fd-debt-metrics">
          <div><span>إجمالي</span><b>${money(p.total)}</b></div>
          <div><span>متأخرة</span><b class="is-danger">${money(p.overdue)}</b></div>
          <div><span>عدد الموردين</span><b>${num(p.count)}</b></div>
        </div>
        <a class="food-ghost" href="${esc(p.href || "/food/suppliers")}">عرض الموردين</a>
      </div>`;
  }

  function productThumb(item) {
    if (item.image_url) {
      return `<img src="${esc(item.image_url)}" alt="" loading="lazy">`;
    }
    return `<span class="fd-thumb-fallback"><i class="fa fa-box"></i></span>`;
  }

  function renderTopProducts() {
    const data = state.data;
    if (!data) return;
    const pack = data.top_products || {};
    let rows = [];
    if (state.topTab === "profit") rows = pack.most_profitable || [];
    else if (state.topTab === "slow") rows = pack.slow || [];
    else rows = pack.best_selling || [];

    if (!rows.length) {
      $("#fdTopProducts").innerHTML = `<div class="fd-empty">لا توجد بيانات لهذه الفترة</div>`;
      return;
    }
    $("#fdTopProducts").innerHTML = rows.map((item) => {
      const meta = state.topTab === "profit"
        ? money(item.profit)
        : state.topTab === "slow"
          ? `${item.days_idle != null ? item.days_idle + " يوم" : "بدون بيع"}`
          : `${num(item.quantity_base)} · ${money(item.sales)}`;
      return `<a class="fd-product" href="/food/products">
        ${productThumb(item)}
        <div><b>${esc(item.product)}</b><small>${esc(item.variant || "")}</small></div>
        <strong>${esc(meta)}</strong>
      </a>`;
    }).join("");
  }

  function renderAlerts(data) {
    const alerts = data.alerts || [];
    if (!alerts.length) {
      $("#fdAlerts").innerHTML = `<div class="fd-empty">لا توجد تنبيهات حالياً — الوضع مستقر</div>`;
      return;
    }
    $("#fdAlerts").innerHTML = alerts.map((alert) => `
      <a class="fd-alert fd-alert--${esc(alert.level || "info")}" href="${esc(alert.href || "#")}">
        <i class="fa ${alert.level === "danger" ? "fa-circle-exclamation" : alert.level === "warning" ? "fa-triangle-exclamation" : "fa-circle-info"}"></i>
        <span>${esc(alert.text)}</span>
      </a>`).join("");
  }

  function renderActivity(data) {
    const rows = data.recent_activity || [];
    if (!rows.length) {
      $("#fdActivity").innerHTML = `<div class="fd-empty">لا توجد حركات حديثة</div>`;
      return;
    }
    $("#fdActivity").innerHTML = rows.map((row) => {
      const time = row.at ? new Date(row.at).toLocaleTimeString("ar-IQ-u-nu-latn", { hour: "numeric", minute: "2-digit", hour12: true }) : "—";
      const sign = row.direction === "out" ? "-" : "+";
      return `<a class="fd-time-item" href="${esc(row.href || "#")}">
        <time>${esc(time)}</time>
        <div><b>${esc(row.title)}</b></div>
        <strong class="is-${row.direction === "out" ? "out" : "in"}">${sign}${money(row.amount)}</strong>
      </a>`;
    }).join("");
  }

  function renderDeadStock(data) {
    const d = data.dead_stock || {};
    const items = d.items || [];
    $("#fdDeadStock").innerHTML = `
      <div class="fd-stat-strip">
        <div><span>عدد المنتجات</span><b>${num(d.count)}</b></div>
        <div><span>قيمة راكدة</span><b>${money(d.value)}</b></div>
      </div>
      ${items.length ? items.map((item) => `
        <div class="fd-mini-row">
          <div><b>${esc(item.product)}</b><small>${item.days_idle != null ? item.days_idle + " يوم بدون بيع" : "لم يُبع من قبل"}</small></div>
          <strong>${money(item.value)}</strong>
        </div>`).join("") : `<div class="fd-empty">لا توجد بضاعة راكدة بارزة</div>`}`;
  }

  function renderExpiry(data) {
    const e = data.expiry || {};
    $("#fdExpiry").innerHTML = `
      <div class="fd-expiry-grid">
        <div><span>تنتهي اليوم</span><b>${num(e.today)}</b></div>
        <div><span>خلال 3 أيام</span><b>${num(e.within_3)}</b></div>
        <div><span>خلال 7 أيام</span><b>${num(e.within_7)}</b></div>
        <div><span>خلال 30 يوم</span><b>${num(e.within_30)}</b></div>
      </div>
      <div class="fd-mini-note">قيمة معرّضة للانتهاء: <b>${money(e.at_risk_value)}</b></div>
      ${(e.critical || []).length ? (e.critical || []).map((item) => `
        <div class="fd-mini-row">
          <div>
            <b>${esc(item.product)}</b>
            <small>${num(item.quantity_base)} · ينتهي ${esc(item.expiry_date)} · متبقي ${item.days_left < 0 ? "منتهٍ" : item.days_left + " يوم"}</small>
          </div>
        </div>`).join("") : `<div class="fd-empty">لا توجد صلاحيات حرجة</div>`}`;
  }

  function renderReorder(data) {
    const items = data.reorder?.items || [];
    if (!items.length) {
      $("#fdReorder").innerHTML = `<div class="fd-empty">لا توجد مقترحات إعادة طلب حالياً</div>`;
      return;
    }
    $("#fdReorder").innerHTML = `
      <table class="fd-table">
        <thead><tr><th>المنتج</th><th>المخزون</th><th>يكفي لمدة</th><th>الكمية المقترحة</th></tr></thead>
        <tbody>
          ${items.map((item) => `<tr>
            <td><b>${esc(item.product)}</b><br><small>${esc(item.variant || "")}</small></td>
            <td>${esc(item.stock_display || num(item.stock_base))}</td>
            <td>${item.days_cover == null ? "—" : item.days_cover + " يوم"}</td>
            <td><span class="fd-badge">+${num(item.suggested_qty)}</span></td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  }

  function renderInsights(data) {
    const list = data.insights || [];
    $("#fdInsightsList").innerHTML = list.length
      ? list.map((text) => `<article><i class="fa fa-lightbulb"></i><p>${esc(text)}</p></article>`).join("")
      : `<article><i class="fa fa-lightbulb"></i><p>لا توجد ملاحظات إضافية لهذه الفترة.</p></article>`;
  }

  function updateMeta(data) {
    const period = data.period || {};
    // Arabic labels with Latin (English) digits
    const arLatn = "ar-IQ-u-nu-latn";
    const dateLabel = period.start === period.end
      ? new Date(period.start + "T12:00:00").toLocaleDateString(arLatn, {
        weekday: "long", year: "numeric", month: "long", day: "numeric",
      })
      : `${period.start} → ${period.end}`;
    $("#fdDateLabel").textContent = dateLabel;
    const stamp = period.generated_at
      ? new Date(period.generated_at).toLocaleTimeString(arLatn, { hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true })
      : "—";
    $("#fdLastUpdated").textContent = `آخر تحديث ${stamp}`;
  }

  function renderAll(data) {
    state.data = data;
    updateMeta(data);
    renderKpis(data);
    renderChart(data);
    renderInventory(data);
    renderSalesTypes(data);
    renderCash(data);
    renderDebts(data);
    renderTopProducts();
    renderAlerts(data);
    renderActivity(data);
    renderDeadStock(data);
    renderExpiry(data);
    renderReorder(data);
    renderInsights(data);
  }

  async function load() {
    setLoading(true);
    try {
      const params = new URLSearchParams({ range: state.period });
      if (state.period === "custom") {
        params.set("start", $("#fdStart").value);
        params.set("end", $("#fdEnd").value);
      }
      const data = await api(`/dashboard?${params}`);
      renderAll(data);
      $("#fdError").hidden = true;
    } catch (error) {
      console.error(error);
      showError(error.message || "تعذر تحميل البيانات");
    } finally {
      setLoading(false);
    }
  }

  function bind() {
    $("#fdPeriod").onchange = () => {
      state.period = $("#fdPeriod").value;
      $("#fdCustomRange").hidden = state.period !== "custom";
      if (state.period !== "custom") load();
    };
    $("#fdApplyCustom").onclick = () => load();
    $("#fdRefresh").onclick = () => load();
    $("#fdRetry").onclick = () => load();
    $$("#fdTopTabs button").forEach((btn) => {
      btn.onclick = () => {
        $$("#fdTopTabs button").forEach((x) => x.classList.remove("active"));
        btn.classList.add("active");
        state.topTab = btn.dataset.top;
        renderTopProducts();
      };
    });
    const today = new Date().toISOString().slice(0, 10);
    $("#fdStart").value = today;
    $("#fdEnd").value = today;
  }

  bind();
  load();
  state.timer = setInterval(() => load(), 60000);
  window.addEventListener("beforeunload", () => clearInterval(state.timer));
})();
