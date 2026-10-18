(() => {
  const TEAL = "#0d9488";
  const TEAL_SOFT = "#99f6e4";
  const SLATE = "#64748b";
  const AMBER = "#f59e0b";
  const ROSE = "#f43f5e";
  const INDIGO = "#6366f1";

  const state = {
    date_from: "",
    date_to: "",
    doctor_id: "",
    specialty_id: "",
    compare: "previous_period",
    quick: "month",
    charts: {},
  };

  function todayISO() {
    return new Date().toISOString().slice(0, 10);
  }

  function addDays(iso, days) {
    const d = new Date(`${iso}T12:00:00`);
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function monthStart(iso) {
    return `${iso.slice(0, 8)}01`;
  }

  function lastMonthRange(iso) {
    const d = new Date(`${iso}T12:00:00`);
    const firstThis = new Date(d.getFullYear(), d.getMonth(), 1);
    const lastPrev = new Date(firstThis.getTime() - 86400000);
    const firstPrev = new Date(lastPrev.getFullYear(), lastPrev.getMonth(), 1);
    const toISO = (x) => x.toISOString().slice(0, 10);
    return { from: toISO(firstPrev), to: toISO(lastPrev) };
  }

  function applyQuick(key) {
    const t = todayISO();
    state.quick = key;
    if (key === "today") {
      state.date_from = t;
      state.date_to = t;
    } else if (key === "yesterday") {
      const y = addDays(t, -1);
      state.date_from = y;
      state.date_to = y;
    } else if (key === "week") {
      state.date_from = addDays(t, -6);
      state.date_to = t;
    } else if (key === "month") {
      state.date_from = monthStart(t);
      state.date_to = t;
    } else if (key === "last_month") {
      const r = lastMonthRange(t);
      state.date_from = r.from;
      state.date_to = r.to;
    }
  }

  function ensureDefaults() {
    if (!state.date_from || !state.date_to) applyQuick(state.quick || "month");
  }

  function destroyCharts() {
    Object.values(state.charts).forEach((c) => {
      try {
        c.destroy();
      } catch (_) {}
    });
    state.charts = {};
  }

  function deltaHtml(value) {
    if (value == null) return `<small class="cxr-delta cxr-delta--na">—</small>`;
    const cls = value > 0 ? "up" : value < 0 ? "down" : "flat";
    const sign = value > 0 ? "+" : "";
    const icon = value > 0 ? "arrow-up" : value < 0 ? "arrow-down" : "minus";
    return `<small class="cxr-delta cxr-delta--${cls}"><i class="fa fa-${icon}"></i>${sign}${value}%</small>`;
  }

  function buildQuery() {
    const p = new URLSearchParams({
      date_from: state.date_from,
      date_to: state.date_to,
      compare: state.compare || "none",
    });
    if (state.doctor_id) p.set("doctor_id", state.doctor_id);
    if (state.specialty_id) p.set("specialty_id", state.specialty_id);
    return p.toString();
  }

  function exportUrl(fmt) {
    return `/clinics/api/reports/export?format=${fmt}&${buildQuery()}`;
  }

  function chartDefaults() {
    if (!window.Chart) return;
    Chart.defaults.font.family = '"IBM Plex Sans Arabic", Tahoma, sans-serif';
    Chart.defaults.color = getComputedStyle(document.body).getPropertyValue("--cx-muted").trim() || SLATE;
    Chart.defaults.plugins.legend.labels.boxWidth = 12;
    Chart.defaults.plugins.legend.rtl = true;
    Chart.defaults.plugins.legend.textDirection = "rtl";
  }

  function applyChartTheme(chart) {
    const style = getComputedStyle(document.body);
    const ink = style.getPropertyValue("--cx-muted").trim() || SLATE;
    const line = style.getPropertyValue("--cx-line").trim();
    chart.options.color = ink;
    chart.options.plugins.legend.labels.color = ink;
    Object.values(chart.options.scales || {}).forEach((scale) => {
      scale.ticks.color = ink;
      scale.title.color = ink;
      scale.grid.color = line;
      scale.border.color = line;
    });
  }

  window.addEventListener("finora:themechange", () => {
    chartDefaults();
    Object.values(state.charts).forEach((chart) => {
      applyChartTheme(chart);
      chart.update("none");
    });
  });

  function makeChart(id, config) {
    const canvas = document.getElementById(id);
    if (!canvas || !window.Chart) return null;
    if (state.charts[id]) {
      try {
        state.charts[id].destroy();
      } catch (_) {}
    }
    state.charts[id] = new Chart(canvas.getContext("2d"), config);
    applyChartTheme(state.charts[id]);
    state.charts[id].update("none");
    return state.charts[id];
  }

  function renderCharts(data, money) {
    chartDefaults();
    const byDay = data.series?.by_day || [];
    const byDoctor = data.series?.by_doctor || [];
    const methods = data.series?.payment_methods || [];
    const statuses = data.series?.appointment_status || [];

    makeChart("cxrChartRevenue", {
      type: "line",
      data: {
        labels: byDay.map((r) => r.date.slice(5)),
        datasets: [
          {
            label: "محصّل",
            data: byDay.map((r) => r.collected),
            borderColor: TEAL,
            backgroundColor: "rgba(13,148,136,.12)",
            fill: true,
            tension: 0.35,
            pointRadius: 2,
          },
          {
            label: "مفوتر",
            data: byDay.map((r) => r.invoiced),
            borderColor: INDIGO,
            backgroundColor: "transparent",
            borderDash: [5, 4],
            tension: 0.35,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${money(ctx.raw)}`,
            },
          },
        },
        scales: {
          y: {
            ticks: {
              callback: (v) => {
                if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)}م`;
                if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(0)}ألف`;
                return v;
              },
            },
          },
        },
      },
    });

    makeChart("cxrChartDoctors", {
      type: "bar",
      data: {
        labels: byDoctor.map((r) => r.doctor_name),
        datasets: [
          {
            label: "الإيراد",
            data: byDoctor.map((r) => r.revenue),
            backgroundColor: TEAL,
            borderRadius: 6,
          },
          {
            label: "الزيارات",
            data: byDoctor.map((r) => r.visits),
            backgroundColor: TEAL_SOFT,
            borderRadius: 6,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) =>
                ctx.dataset.label === "الإيراد"
                  ? `${ctx.dataset.label}: ${money(ctx.raw)}`
                  : `${ctx.dataset.label}: ${ctx.raw}`,
            },
          },
        },
        scales: {
          y: { position: "right", title: { display: true, text: "إيراد" } },
          y1: {
            position: "left",
            grid: { drawOnChartArea: false },
            title: { display: true, text: "زيارات" },
          },
        },
      },
    });

    makeChart("cxrChartPayments", {
      type: "doughnut",
      data: {
        labels: methods.map((r) => r.label),
        datasets: [
          {
            data: methods.map((r) => r.amount),
            backgroundColor: [TEAL, INDIGO, AMBER, ROSE, SLATE, "#14b8a6"],
            borderWidth: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.label}: ${money(ctx.raw)}`,
            },
          },
        },
      },
    });

    makeChart("cxrChartStatus", {
      type: "bar",
      data: {
        labels: statuses.map((r) => r.label),
        datasets: [
          {
            label: "العدد",
            data: statuses.map((r) => r.count),
            backgroundColor: statuses.map((r) =>
              r.status === "no_show" || r.status === "cancelled"
                ? ROSE
                : r.status === "completed"
                  ? TEAL
                  : INDIGO
            ),
            borderRadius: 6,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
      },
    });
  }

  function table(headers, rowsHtml, emptyMsg) {
    if (!rowsHtml) {
      return `<div class="cx-empty cxr-empty"><i class="fa fa-chart-column"></i><b>${emptyMsg}</b></div>`;
    }
    return `<div class="cx-table-wrap"><table class="cx-table cxr-table"><thead><tr>${headers
      .map((h) => `<th>${h}</th>`)
      .join("")}</tr></thead><tbody>${rowsHtml}</tbody></table></div>`;
  }

  async function render(appState, root, ctx) {
    ensureDefaults();
    destroyCharts();
    root.innerHTML = `<div class="cxr-page"><div class="cx-empty cxr-empty"><i class="fa fa-spinner fa-spin"></i><b>جارٍ تحميل التقارير...</b></div></div>`;

    let data;
    let dentalData = null;
    try {
      [data, dentalData] = await Promise.all([
        ctx.api(`/clinics/api/reports/hub?${buildQuery()}`),
        ctx.api("/clinics/api/reports/dental").catch(() => null),
      ]);
    } catch (err) {
      root.innerHTML = `<div class="cxr-page"><div class="cx-empty cxr-empty"><i class="fa fa-triangle-exclamation"></i><b>${ctx.esc(
        err.message || String(err)
      )}</b></div></div>`;
      return;
    }

    const k = data.kpis || {};
    const a = data.accounting || {};
    const rec = data.reconciliation || {};
    const deltas = data.compare?.deltas || {};
    const doctors = data.doctors || [];
    const byDoctor = data.series?.by_doctor || [];
    const services = data.tables?.top_services || [];
    const expenses = data.tables?.expenses_by_category || [];
    const alerts = data.tables?.inventory_alerts || {};
    const compareOn = data.filters?.compare === "previous_period";

    const kpiCards = [
      ["appointments", "المواعيد", k.appointments, "fa-calendar-check", false],
      ["completed_visits", "زيارات مكتملة", k.completed_visits, "fa-stethoscope", false],
      ["no_show_rate", "عدم الحضور", `${k.no_show_rate || 0}%`, "fa-user-xmark", false],
      ["invoiced", "مفوتر", ctx.money(k.invoiced), "fa-file-invoice", true],
      ["collected", "محصّل", ctx.money(k.collected), "fa-coins", true],
      ["outstanding", "آجل", ctx.money(k.outstanding), "fa-hand-holding-dollar", true],
      ["expenses", "مصروفات", ctx.money(k.expenses), "fa-receipt", true],
      ["net", "صافي الحركة النقدية", ctx.money(k.net_operating_cash_movement ?? k.net), "fa-money-bill-transfer", true],
    ];

    root.innerHTML = `
      <div class="cxr-page" id="cxrPrintRoot">
        <section class="cxr-head">
          <div>
            <h1>تقارير العيادة</h1>
            <p>لوحة تحليل تشغيلي ومالي مع مقارنة الفترات والرسوم البيانية والتصدير.</p>
          </div>
          <div class="cxr-head__actions">
            <a class="cx-btn" href="/clinics/purchases/reports"><i class="fa fa-cart-shopping"></i> تقارير المشتريات</a>
            <a class="cx-btn" href="${exportUrl("csv")}" id="cxrCsv"><i class="fa fa-file-csv"></i> CSV</a>
            <a class="cx-btn" href="${exportUrl("xlsx")}" id="cxrXlsx"><i class="fa fa-file-excel"></i> Excel</a>
            <button type="button" class="cx-btn cx-btn--primary" id="cxrPrint"><i class="fa fa-print"></i> طباعة / PDF</button>
          </div>
        </section>

        <section class="cxr-filters">
          <label><span>من</span><input type="date" class="cx-input" id="cxrFrom" value="${ctx.esc(state.date_from)}"></label>
          <label><span>إلى</span><input type="date" class="cx-input" id="cxrTo" value="${ctx.esc(state.date_to)}"></label>
          <label><span>الطبيب</span>
            <select class="cx-select" id="cxrDoctor">
              <option value="">كل الأطباء</option>
              ${doctors
                .map(
                  (d) =>
                    `<option value="${d.id}" ${String(d.id) === String(state.doctor_id) ? "selected" : ""}>${ctx.esc(
                      d.full_name
                    )}</option>`
                )
                .join("")}
            </select>
          </label>
          <label class="cxr-compare">
            <span>الاختصاص</span><select class="cx-select" id="cxrSpecialty"><option value="">كل الاختصاصات</option>${(data.specialties||[]).map(s=>`<option value="${s.id}" ${String(s.id)===String(state.specialty_id)?'selected':''}>${ctx.esc(s.name_ar)}</option>`).join('')}</select>
            <input type="checkbox" id="cxrCompare" ${compareOn ? "checked" : ""}>
            <span>مقارنة بالفترة السابقة</span>
          </label>
          <button type="button" class="cx-btn cx-btn--primary" id="cxrApply"><i class="fa fa-filter"></i> تطبيق</button>
        </section>

        <div class="cxr-quick">
          ${[
            ["today", "اليوم"],
            ["yesterday", "أمس"],
            ["week", "آخر 7 أيام"],
            ["month", "هذا الشهر"],
            ["last_month", "الشهر الماضي"],
          ]
            .map(
              ([v, l]) =>
                `<button type="button" class="${state.quick === v ? "is-active" : ""}" data-quick="${v}">${l}</button>`
            )
            .join("")}
        </div>

        <section class="cxr-kpis">
          ${kpiCards
            .map(
              ([key, label, value, icon]) => `
            <article class="cxr-kpi">
              <i class="fa ${icon}"></i>
              <span>${label}</span>
              <strong>${value}</strong>
              ${compareOn ? deltaHtml(deltas[key]) : ""}
            </article>`
            )
            .join("")}
        </section>

        <section class="cxr-panel cxr-panel--wide">
          <header><h2>المحاسبة</h2><span>نتائج دفتر الأستاذ العام — أساس الاستحقاق</span></header>
          ${rec.has_difference ? `<div class="cx-alert cx-alert--warning"><i class="fa fa-triangle-exclamation"></i> يوجد فرق بين دفتر العيادة والدليل المحاسبي</div>` : ""}
          <div class="cxr-kpis">
            ${[
              ["الإيرادات الطبية", a.medical_revenue, "fa-notes-medical"],
              ["تكلفة المستلزمات", a.medical_supplies_cost, "fa-boxes-stacked"],
              ["عمولات الأطباء", a.doctor_commission_expense, "fa-user-doctor"],
              ["مصاريف التشغيل", a.clinic_operating_expenses, "fa-receipt"],
              ["صافي الربح", a.net_profit, "fa-chart-line"],
              ["ذمم المرضى", a.patient_receivables, "fa-hand-holding-dollar"],
              ["ذمم الموردين", a.supplier_payables, "fa-truck"],
              ["مستحقات الأطباء", a.doctor_payables, "fa-user-doctor"],
              ["الصندوق", a.cash_balance, "fa-cash-register"],
              ["البنك", a.bank_balance, "fa-building-columns"],
            ].map(([label, value, icon]) => `<article class="cxr-kpi"><i class="fa ${icon}"></i><span>${label}</span><strong>${ctx.money(value || 0)}</strong></article>`).join("")}
          </div>
        </section>

        ${
          compareOn && data.compare?.previous
            ? `<p class="cxr-compare-note">مقارنة مع ${ctx.esc(data.compare.previous.from)} → ${ctx.esc(
                data.compare.previous.to
              )} · متوسط قيمة الزيارة: <b>${ctx.money(k.avg_visit_value)}</b></p>`
            : `<p class="cxr-compare-note">الفترة: ${ctx.esc(data.period.from)} → ${ctx.esc(
                data.period.to
              )} (${data.period.days} يوم) · متوسط قيمة الزيارة: <b>${ctx.money(k.avg_visit_value)}</b>
              · تحاليل مفتوحة ${data.tables?.lab_open || 0} · أشعة مفتوحة ${data.tables?.radiology_open || 0}
              · تنبيهات مخزون ${(alerts.low_stock_count || 0) + (alerts.expired_count || 0)}</p>`
        }

        <section class="cxr-charts">
          <article class="cxr-chart-card cxr-chart-card--wide">
            <header><h2>الإيراد عبر الأيام</h2><span>محصّل مقابل مفوتر</span></header>
            <div class="cxr-chart-wrap"><canvas id="cxrChartRevenue"></canvas></div>
          </article>
          <article class="cxr-chart-card">
            <header><h2>أداء الأطباء</h2><span>إيراد وزيارات</span></header>
            <div class="cxr-chart-wrap"><canvas id="cxrChartDoctors"></canvas></div>
          </article>
          <article class="cxr-chart-card">
            <header><h2>طرق الدفع</h2><span>توزيع التحصيل والآجل</span></header>
            <div class="cxr-chart-wrap cxr-chart-wrap--sm"><canvas id="cxrChartPayments"></canvas></div>
          </article>
          <article class="cxr-chart-card">
            <header><h2>حالات المواعيد</h2><span>قمع الحالات</span></header>
            <div class="cxr-chart-wrap"><canvas id="cxrChartStatus"></canvas></div>
          </article>
        </section>

        <section class="cxr-tables">
          ${
            dentalData
              ? `<article class="cxr-panel cxr-panel--wide">
                  <header><h2>نظرة عامة على الأسنان</h2><span>الوضع الحالي لخطط العلاج</span></header>
                  <div class="cxr-alert-grid">
                    <div><span>الخطط</span><strong>${dentalData.overview?.plan_count || 0}</strong></div>
                    <div><span>خطط نشطة</span><strong>${dentalData.overview?.active_plan_count || 0}</strong></div>
                    <div><span>علاجات معلقة</span><strong>${dentalData.overview?.pending_treatment_count || 0}</strong></div>
                    <div><span>علاجات مكتملة</span><strong>${dentalData.overview?.completed_treatment_count || 0}</strong></div>
                    <div><span>تنفيذات مرتبطة</span><strong>${dentalData.overview?.execution_count || 0}</strong></div>
                  </div>
                </article>
                <article class="cxr-panel cxr-panel--wide">
                  <header><h2>علاجات الأسنان المعلقة</h2></header>
                  ${table(
                    ["المريض", "السن", "العلاج", "الأولوية", "الحالة", "الجلسات"],
                    (dentalData.pending_treatments || [])
                      .map(
                        (item) => `<tr>
                          <td><a class="cx-link" href="/clinics/patients/${item.patient_id}">${ctx.esc(item.patient_name || "—")}</a></td>
                          <td>${ctx.esc(item.tooth_number || "عام")}</td>
                          <td>${ctx.esc(item.title)}</td>
                          <td>${ctx.esc(item.priority)}</td>
                          <td>${ctx.esc(item.status)}</td>
                          <td>${item.estimated_sessions || 1}</td>
                        </tr>`
                      )
                      .join(""),
                    "لا توجد علاجات أسنان معلقة"
                  )}
                </article>`
              : ""
          }
          <article class="cxr-panel">
            <header><h2>الأداء حسب الطبيب</h2></header>
            ${table(
              ["الطبيب", "التخصص", "المواعيد", "الزيارات", "عدم حضور", "الإيراد", "الحصة"],
              byDoctor
                .map(
                  (r) => `<tr>
                  <td><b>${ctx.esc(r.doctor_name)}</b></td>
                  <td>${ctx.esc(r.specialty || "—")}</td>
                  <td>${r.appointments}</td>
                  <td>${r.visits}</td>
                  <td>${r.no_show}</td>
                  <td class="cx-money">${ctx.money(r.revenue)}</td>
                  <td>${r.share}%</td>
                </tr>`
                )
                .join(""),
              "لا بيانات أطباء لهذه الفترة"
            )}
          </article>
          <article class="cxr-panel">
            <header><h2>أعلى الخدمات</h2></header>
            ${table(
              ["الخدمة", "الكمية", "الإجمالي"],
              services
                .map(
                  (r) => `<tr>
                  <td>${ctx.esc(r.name)}</td>
                  <td>${r.quantity}</td>
                  <td class="cx-money">${ctx.money(r.total)}</td>
                </tr>`
                )
                .join(""),
              "لا خدمات مفوترة في الفترة"
            )}
          </article>
          <article class="cxr-panel">
            <header><h2>المصروفات حسب التصنيف</h2></header>
            ${
              state.doctor_id
                ? `<div class="cx-empty cxr-empty"><b>المصروفات على مستوى العيادة</b><span>أزل فلتر الطبيب لعرضها.</span></div>`
                : table(
                    ["التصنيف", "العدد", "المبلغ"],
                    expenses
                      .map(
                        (r) => `<tr>
                        <td>${ctx.esc(r.category)}</td>
                        <td>${r.count}</td>
                        <td class="cx-money">${ctx.money(r.amount)}</td>
                      </tr>`
                      )
                      .join(""),
                    "لا مصروفات في الفترة"
                  )
            }
          </article>
          <article class="cxr-panel">
            <header><h2>تنبيهات المخزون</h2></header>
            <div class="cxr-alert-grid">
              <div><span>منخفض</span><strong>${alerts.low_stock_count || 0}</strong></div>
              <div><span>منتهٍ</span><strong>${alerts.expired_count || 0}</strong></div>
              <div><span>قرب الانتهاء</span><strong>${alerts.expiring_soon_count || 0}</strong></div>
              <div><span>تحاليل مفتوحة</span><strong>${data.tables?.lab_open || 0}</strong></div>
              <div><span>أشعة مفتوحة</span><strong>${data.tables?.radiology_open || 0}</strong></div>
            </div>
            <a class="cx-btn cx-btn--sm" href="/clinics/inventory" style="margin-top:10px">فتح المخزون</a>
          </article>
        </section>
      </div>`;

    const reload = () => render(appState, root, ctx);
    document.getElementById("cxrApply").onclick = () => {
      state.date_from = document.getElementById("cxrFrom").value;
      state.date_to = document.getElementById("cxrTo").value;
      state.doctor_id = document.getElementById("cxrDoctor").value;
      state.specialty_id = document.getElementById("cxrSpecialty").value;
      state.compare = document.getElementById("cxrCompare").checked ? "previous_period" : "none";
      state.quick = "";
      reload();
    };
    document.getElementById("cxrCompare").onchange = (e) => {
      state.compare = e.target.checked ? "previous_period" : "none";
    };
    root.querySelectorAll("[data-quick]").forEach((btn) => {
      btn.onclick = () => {
        applyQuick(btn.dataset.quick);
        reload();
      };
    });
    document.getElementById("cxrPrint").onclick = () => window.print();

    // Sync export links if filters changed in DOM without apply
    const syncExport = () => {
      state.date_from = document.getElementById("cxrFrom").value || state.date_from;
      state.date_to = document.getElementById("cxrTo").value || state.date_to;
      state.doctor_id = document.getElementById("cxrDoctor").value;
      state.specialty_id = document.getElementById("cxrSpecialty").value;
      state.compare = document.getElementById("cxrCompare").checked ? "previous_period" : "none";
      const csv = document.getElementById("cxrCsv");
      const xlsx = document.getElementById("cxrXlsx");
      if (csv) csv.href = exportUrl("csv");
      if (xlsx) xlsx.href = exportUrl("xlsx");
    };
    ["cxrFrom", "cxrTo", "cxrDoctor", "cxrCompare"].forEach((id) => {
      document.getElementById(id)?.addEventListener("change", syncExport);
    });

    requestAnimationFrame(() => renderCharts(data, ctx.money));
  }

  window.ClinicsReports = { render };
})();
