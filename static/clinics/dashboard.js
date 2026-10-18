/**
 * Finora Clinics — Operations Dashboard UI
 */
(() => {
  const KPI_THEMES = [
    { key: "appointments", icon: "fa-calendar-check", theme: "purple" },
    { key: "waiting", icon: "fa-hourglass-half", theme: "orange" },
    { key: "doctor", icon: "fa-user-doctor", theme: "blue" },
    { key: "completed", icon: "fa-check-circle", theme: "green" },
    { key: "new_patients", icon: "fa-user-plus", theme: "violet" },
    { key: "revenue", icon: "fa-coins", theme: "teal" },
  ];

  function can(ctx, perm) {
    const u = ctx.bootstrap?.user || ctx.data?.user || {};
    if (u.role === "admin") return true;
    return (u.permissions || []).includes(perm);
  }

  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function apptActions(a, ctx) {
    const id = a.id;
    const btns = [];
    if (can(ctx, "clinics_reception")) {
      if (a.status === "pending" || a.status === "confirmed") {
        btns.push(`<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-appt-act="arrived" data-id="${id}">تسجيل وصول</button>`);
      }
      if (a.status === "arrived") {
        btns.push(`<button type="button" class="cx-btn cx-btn--sm" data-appt-act="waiting" data-id="${id}">إدخال انتظار</button>`);
      }
      if (["arrived", "waiting", "confirmed"].includes(a.status)) {
        btns.push(`<button type="button" class="cx-btn cx-btn--sm" data-appt-act="start" data-id="${id}">إدخال للطبيب</button>`);
      }
    }
    if (a.status === "in_consultation" && can(ctx, "clinics_visits")) {
      btns.push(`<a class="cx-btn cx-btn--sm cx-btn--primary" href="/clinics/visits">فتح الزيارة</a>`);
    }
    if (a.status === "completed") {
      btns.push(`<a class="cx-btn cx-btn--sm" href="/clinics/patients/${a.patient_id}">فتح الملف</a>`);
      if (can(ctx, "clinics_billing")) {
        btns.push(`<a class="cx-btn cx-btn--sm" href="/clinics/billing">الفاتورة</a>`);
      }
    }
    btns.push(`<a class="cx-btn cx-btn--sm cx-btn--ghost" href="/clinics/patients/${a.patient_id}">الملف</a>`);
    return btns.join("");
  }

  function skeletonDashboard() {
    return `
      <div class="cx-dash">
        <div class="cx-dash-header cx-skeleton-block" style="height:88px"></div>
        <div class="cx-dash-kpis">${Array(6).fill('<div class="cx-stat-card cx-skeleton-block" style="height:110px"></div>').join("")}</div>
        <div class="cx-dash-main">
          <div class="cx-skeleton-block" style="height:420px;border-radius:18px"></div>
          <div class="cx-skeleton-block" style="height:420px;border-radius:18px"></div>
        </div>
      </div>`;
  }

  function kpiCards(k, ctx) {
    const cards = [
      {
        title: "مواعيد اليوم",
        value: k.appointments_today || 0,
        sub: `${k.arrived || 0} حضروا · ${k.no_show || 0} لم يحضروا · ${k.coming || 0} قادمون`,
        theme: "purple",
        icon: "fa-calendar-check",
        show: true,
      },
      {
        title: "في الانتظار",
        value: k.waiting || 0,
        sub: `متوسط الانتظار: ${k.avg_wait_minutes || 0} دقيقة`,
        theme: "orange",
        icon: "fa-hourglass-half",
        alert: k.overdue_wait_count > 0,
        show: can(ctx, "clinics_reception"),
      },
      {
        title: "عند الطبيب",
        value: k.in_consultation || 0,
        sub: `من أصل ${k.appointments_today || 0} موعد`,
        theme: "blue",
        icon: "fa-user-doctor",
        show: true,
      },
      {
        title: "زيارات مكتملة",
        value: k.completed_visits || 0,
        sub: `${k.cancelled || 0} ملغاة`,
        theme: "green",
        icon: "fa-check-circle",
        show: true,
      },
      {
        title: "مرضى جدد",
        value: k.new_patients || 0,
        sub: `من إجمالي ${k.arrived || 0} زيارة`,
        theme: "violet",
        icon: "fa-user-plus",
        show: can(ctx, "clinics_patients"),
      },
      {
        title: "إيراد اليوم",
        value: ctx.money(k.revenue_today),
        sub: `من ${k.invoice_count || 0} فواتير`,
        theme: "teal",
        icon: "fa-coins",
        money: true,
        show: can(ctx, "clinics_billing"),
      },
    ];
    const visible = cards.filter((c) => c.show);
    return `<section class="cx-dash-kpis" style="--cx-kpi-count:${visible.length}">${visible
      .map(
        (c) => `
      <article class="cx-stat-card cx-stat-card--${c.theme} ${c.alert ? "cx-stat-card--alert" : ""}">
        <div class="cx-stat-card__icon"><i class="fa ${c.icon}"></i></div>
        <div class="cx-stat-card__body">
          <span class="cx-stat-card__label">${c.title}</span>
          <strong class="${c.money ? "cx-money" : ""}">${ctx.esc(c.value)}</strong>
          <em>${ctx.esc(c.sub)}</em>
        </div>
      </article>`
      )
      .join("")}</section>`;
  }

  function dentalWidgets(dental, ctx) {
    if (!dental || dental.enabled === false) return "";
    const cards = [
      ["جلسات اليوم", dental.sessions_today || 0, "fa-tooth"],
      ["خطط علاج نشطة", dental.active_plans || 0, "fa-clipboard-list"],
      ["علاجات غير مكتملة", dental.incomplete_treatments || 0, "fa-hourglass-half"],
      ["مواعيد أسنان قادمة", dental.upcoming_appointments || 0, "fa-calendar-plus"],
    ];
    if (dental.estimated_outstanding != null && can(ctx, "clinics_billing")) {
      cards.push(["متبقي خطط العلاج", ctx.money(dental.estimated_outstanding), "fa-coins", true]);
    }
    return `
      <section class="cx-dash-band" aria-label="مؤشرات الأسنان">
        <div class="cx-dash-band__head">
          <h2>الأسنان</h2>
          <p>الجلسات وخطط العلاج لليوم</p>
        </div>
        <div class="cx-dash-kpis cx-dash-kpis--dental" style="--cx-kpi-count:${cards.length}">
          ${cards
            .map(
              ([title, value, icon, money]) => `
            <article class="cx-stat-card cx-stat-card--quiet">
              <div class="cx-stat-card__icon"><i class="fa ${icon}"></i></div>
              <div class="cx-stat-card__body">
                <span class="cx-stat-card__label">${title}</span>
                <strong class="${money ? "cx-money" : ""}">${ctx.esc(value)}</strong>
              </div>
            </article>`
            )
            .join("")}
        </div>
      </section>`;
  }

  function appointmentsTable(rows, ctx, filterQ) {
    const q = (filterQ || "").trim().toLowerCase();
    const filtered = q
      ? rows.filter(
          (a) =>
            (a.patient_name || "").toLowerCase().includes(q) ||
            (a.patient_phone || "").includes(q) ||
            (a.patient_file || "").toLowerCase().includes(q) ||
            String(a.id).includes(q)
        )
      : rows;
    if (!filtered.length) {
      return `<div class="cx-empty">لا توجد مواعيد لهذا اليوم<button type="button" class="cx-btn cx-btn--primary cx-btn--sm" id="cxDashNewAppt">+ إضافة موعد</button></div>`;
    }
    return `
      <div class="cx-table-wrap">
        <table class="cx-table cx-table--dash">
          <thead><tr>
            <th>الوقت</th><th>المريض</th><th>الطبيب</th><th>الحالة</th><th>سبب الزيارة</th><th>إجراء</th>
          </tr></thead>
          <tbody>
            ${filtered
              .map(
                (a) => `
              <tr>
                <td><strong>${ctx.esc(a.start_time)}</strong></td>
                <td><a href="/clinics/patients/${a.patient_id}" class="cx-link">${ctx.esc(a.patient_name)}</a></td>
                <td>${ctx.esc(a.doctor_name || "—")}</td>
                <td>${ctx.badge(a.status)}</td>
                <td>${ctx.esc(a.service_name || a.notes || "—")}</td>
                <td class="cx-table__actions">${apptActions(a, ctx)}</td>
              </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`;
  }

  function paymentDonut(methods, ctx) {
    const colors = { cash: "#0d9488", card: "#6366f1", transfer: "#0ea5e9", credit: "#f59e0b" };
    const slices = (methods || []).filter((m) => m.amount > 0);
    const total = slices.reduce((s, m) => s + (m.key === "credit" ? 0 : m.amount), 0);
    if (!total) return "";
    const r = 38;
    const c = 2 * Math.PI * r;
    let offset = 0;
    const segs = slices
      .filter((m) => m.key !== "credit" && m.amount > 0)
      .map((m) => {
        const dash = (m.amount / total) * c;
        const seg = `<circle cx="50" cy="50" r="${r}" fill="none" stroke="${colors[m.key] || "#94a3b8"}" stroke-width="12" stroke-dasharray="${dash} ${c - dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 50 50)"/>`;
        offset += dash;
        return seg;
      })
      .join("");
    const legend = slices
      .map(
        (m) =>
          `<span><i style="background:${colors[m.key] || "#94a3b8"}"></i>${ctx.esc(m.label)}</span>`
      )
      .join("");
    return `
      <div class="cx-donut-block">
        <div class="cx-donut-wrap">
          <svg viewBox="0 0 100 100" class="cx-donut" aria-hidden="true">${segs}</svg>
          <div class="cx-donut__center"><small>المقبوض</small><strong class="cx-money">${ctx.money(total)}</strong></div>
        </div>
        <div class="cx-donut-legend">${legend}</div>
      </div>`;
  }

  function waitingQueue(items, ctx) {
    if (!items.length) {
      return `<div class="cx-empty">لا يوجد مرضى في قائمة الانتظار</div>`;
    }
    const dragHint = can(ctx, "clinics_reception") ? `<div class="cx-wait-hint"><i class="fa fa-grip-vertical"></i> اسحب لإعادة الترتيب</div>` : "";
    return (
      dragHint +
      items
        .map(
          (a, i) => `
      <div class="cx-wait-item cx-wait-item--${a.wait_level || "ok"} ${a.is_emergency ? "cx-wait-item--emergency" : ""}"
        draggable="${can(ctx, "clinics_reception") ? "true" : "false"}" data-wait-id="${a.id}">
        <div class="cx-wait-item__drag"><i class="fa fa-grip-vertical"></i></div>
        <div class="cx-wait-item__num">${String(a.queue_number || i + 1).padStart(2, "0")}</div>
        <div class="cx-wait-item__main">
          <strong>${ctx.esc(a.patient_name)} ${a.is_emergency ? '<span class="cx-badge cx-badge--cancel">طارئ</span>' : ""}</strong>
          <span>${ctx.esc(a.doctor_name || "")} · ${ctx.esc(a.service_name || "")}</span>
        </div>
        <div class="cx-wait-item__time">${a.wait_minutes || 0} د</div>
        <div class="cx-wait-item__acts">
          ${can(ctx, "clinics_reception") ? `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-appt-act="start" data-id="${a.id}">إدخال للطبيب</button>` : ""}
          ${can(ctx, "clinics_reception") ? `<button type="button" class="cx-btn cx-btn--sm" data-queue-emergency="${a.id}" title="طوارئ">${a.is_emergency ? "إلغاء طوارئ" : "طارئ"}</button>` : ""}
          <a class="cx-btn cx-btn--sm cx-btn--ghost" href="/clinics/patients/${a.patient_id}">الملف</a>
        </div>
      </div>`
        )
        .join("")
    );
  }

  function financeCard(finance, ctx) {
    if (!can(ctx, "clinics_billing")) return "";
    const methods = finance.payment_methods || [];
    const totalPay = methods.reduce((s, m) => s + (m.key !== "credit" ? m.amount : 0), 0);
    return `
      <article class="cx-card cx-card--compact">
        <div class="cx-card__head">
          <div><h2>ملخص اليوم المالي</h2><p>تحصيلات ومصروفات اليوم</p></div>
          <a href="/clinics/cash" class="cx-btn cx-btn--sm">عرض الحسابات</a>
        </div>
        <div class="cx-finance-grid">
          <div><span>إجمالي الفواتير</span><strong class="cx-money">${ctx.money(finance.invoiced)}</strong></div>
          <div><span>المقبوض</span><strong class="cx-money">${ctx.money(finance.collected)}</strong></div>
          <div><span>المتبقي</span><strong class="cx-money">${ctx.money(finance.outstanding)}</strong></div>
          <div><span>المصروف</span><strong class="cx-money">${ctx.money(finance.expenses)}</strong></div>
          <div class="cx-finance-grid__net"><span>صافي الحركة</span><strong class="cx-money">${ctx.money(finance.net_movement)}</strong></div>
        </div>
        ${paymentDonut(methods, ctx)}
        <div class="cx-pay-methods">
          ${methods
            .map(
              (m) => `
            <div class="cx-pay-method">
              <span>${ctx.esc(m.label)}</span>
              <strong class="cx-money">${ctx.money(m.amount)}</strong>
              <div class="cx-pay-method__bar" style="width:${totalPay ? Math.min(100, (m.amount / totalPay) * 100) : 0}%"></div>
            </div>`
            )
            .join("")}
        </div>
      </article>`;
  }

  function alertsListHtml(rows, ctx) {
    const list = rows || [];
    if (!list.length) {
      return `<div class="cx-empty cx-empty--ok"><i class="fa fa-circle-check"></i> لا توجد تنبيهات حالياً</div>`;
    }
    return list
      .map(
        (a) => `
      <a href="${ctx.esc(a.href || "#")}" class="cx-notif-item cx-notif-item--${a.severity || "info"}">
        <i class="fa ${a.icon || "fa-bell"}"></i>
        <div>
          <strong>${ctx.esc(a.title)} <span class="cx-alert__count">${a.count}</span></strong>
          <span>${ctx.esc(a.description)}</span>
        </div>
      </a>`
      )
      .join("");
  }

  function alertsPanelHtml(alerts, ctx) {
    const rows = alerts || [];
    return `
      <div class="cx-notif-panel" id="cxNotifPanel" hidden role="dialog" aria-label="التنبيهات">
        <div class="cx-notif-panel__head">
          <strong>التنبيهات</strong>
          <span>${rows.length ? `${rows.length} عنصر` : "لا يوجد"}</span>
        </div>
        <div class="cx-notif-panel__list" id="cxNotifList">${alertsListHtml(rows, ctx)}</div>
      </div>`;
  }

  function bindNotifPanel(root) {
    const btn = root.querySelector("#cxDashNotif");
    const panel = root.querySelector("#cxNotifPanel");
    if (!btn || !panel) return;
    btn.onclick = (e) => {
      e.stopPropagation();
      panel.hidden = !panel.hidden;
      btn.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
    };
    if (!root._notifDocBound) {
      root._notifDocBound = true;
      document.addEventListener("click", (e) => {
        const p = root.querySelector("#cxNotifPanel");
        const b = root.querySelector("#cxDashNotif");
        if (!p || p.hidden) return;
        if (!p.contains(e.target) && !(b && b.contains(e.target))) {
          p.hidden = true;
          b?.setAttribute("aria-expanded", "false");
        }
      });
    }
  }

  function followupBadge(status, ctx) {
    const map = {
      late: { cls: "cancel", label: "متأخر" },
      pending: { cls: "waiting", label: "قيد المتابعة" },
      scheduled: { cls: "pending", label: "مجدول" },
      completed: { cls: "done", label: "مكتمل" },
      cancelled: { cls: "cancel", label: "ملغي" },
    };
    const m = map[status] || { cls: "pending", label: status };
    return `<span class="cx-badge cx-badge--${m.cls}">${ctx.esc(m.label)}</span>`;
  }

  function followupsCard(rows, ctx) {
    if (!can(ctx, "clinics_clinical")) return "";
    if (!rows.length) {
      return `
        <article class="cx-card cx-card--compact">
          <div class="cx-card__head"><div><h2>المتابعات القادمة</h2></div><a href="/clinics/followups" class="cx-btn cx-btn--sm">عرض الكل</a></div>
          <div class="cx-empty">لا توجد متابعات مستحقة</div>
        </article>`;
    }
    return `
      <article class="cx-card cx-card--compact">
        <div class="cx-card__head">
          <div><h2>المتابعات القادمة</h2></div>
          <a href="/clinics/followups" class="cx-btn cx-btn--sm">عرض الكل</a>
        </div>
        <div class="cx-table-wrap">
          <table class="cx-table cx-table--compact">
            <thead><tr><th>المريض</th><th>النوع</th><th>الموعد</th><th>الحالة</th></tr></thead>
            <tbody>
              ${rows
                .map(
                  (f) => `
                <tr>
                  <td><a href="/clinics/patients/${f.patient_id}" class="cx-link">${ctx.esc(f.patient_name)}</a></td>
                  <td>${ctx.esc(f.type_label)}</td>
                  <td>${ctx.esc(f.due_date)}</td>
                  <td>${followupBadge(f.status, ctx)}</td>
                </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </article>`;
  }

  function doctorCard(ws, ctx) {
    if (!ws || !can(ctx, "clinics_clinical")) return "";
    const cur = ws.current_patient;
    const next = ws.next_patient;
    return `
      <article class="cx-card cx-doctor-now">
        <div class="cx-card__head"><div><h2>المريض الحالي</h2></div></div>
        ${cur
          ? `
          <div class="cx-doctor-now__patient">
            <h3>${ctx.esc(cur.patient_name)}</h3>
            <p>${ctx.esc(cur.age ? `${cur.age} سنة` : "")} ${ctx.esc(cur.gender === "male" ? "· ذكر" : cur.gender === "female" ? "· أنثى" : "")}</p>
            <p><strong>سبب الزيارة:</strong> ${ctx.esc(cur.chief_complaint || "—")}</p>
            <p><strong>مدة الزيارة:</strong> ${cur.duration_minutes || 0} دقيقة</p>
            ${cur.allergies ? `<p class="cx-doctor-now__warn"><i class="fa fa-triangle-exclamation"></i> ${ctx.esc(cur.allergies)}</p>` : ""}
            <div class="cx-actions" style="margin-top:12px">
              <a href="/clinics/doctor/${cur.visit_id}" class="cx-btn cx-btn--primary">فتح الزيارة</a>
              <a href="/clinics/patients/${cur.patient_id}" class="cx-btn">فتح الملف</a>
              <a href="/clinics/labs" class="cx-btn">التحاليل</a>
              <a href="/clinics/radiology" class="cx-btn">الأشعة</a>
            </div>
          </div>`
          : `<div class="cx-empty">لا يوجد مريض حالياً عند الطبيب</div>`}
        ${next
          ? `<div class="cx-doctor-now__next"><span>المريض التالي:</span> <strong>${ctx.esc(next.patient_name)}</strong> · ${ctx.esc(next.start_time)}</div>`
          : ""}
      </article>`;
  }

  function newActionMenu() {
    return `
      <div class="cx-dropdown" id="cxNewActionMenu" hidden>
        <button type="button" data-action="patient">مريض جديد</button>
        <button type="button" data-action="appointment">موعد جديد</button>
        <button type="button" data-action="visit">زيارة جديدة</button>
        <button type="button" data-action="invoice">فاتورة</button>
        <button type="button" data-action="payment">تحصيل</button>
        <button type="button" data-action="expense">مصروف</button>
        <button type="button" data-action="call">اتصال / متابعة</button>
      </div>`;
  }

  function buildHtml(data, state, ctx) {
    const k = data.kpis || {};
    const user = data.user || {};
    const clinic = data.settings || {};
    const status = data.clinic_status || {};
    const dateLabel = data.date;

    return `
      <div class="cx-dash">
        <header class="cx-dash-header">
          <div class="cx-dash-header__info">
            <h1>لوحة العيادة</h1>
            <p class="cx-dash-header__status">
              <span class="cx-clinic-dot ${status.is_open ? "is-open" : "is-closed"}"></span>
              ${status.is_open ? "مفتوحة" : "مغلقة"}
              ${status.hours_label ? ` · ${ctx.esc(status.hours_label)}` : ""}
            </p>
          </div>
          <div class="cx-dash-header__search">
            <div class="cx-search-wrap">
              <i class="fa fa-search"></i>
              <input type="search" class="cx-input cx-search" id="cxGlobalSearch" placeholder="ابحث عن مريض، رقم هاتف، موعد، ملف…" autocomplete="off">
              <div id="cxSearchResults" class="cx-search-results" hidden></div>
            </div>
          </div>
          <div class="cx-dash-header__actions">
            <input type="date" class="cx-input cx-input--compact" id="cxDashDay" value="${ctx.esc(state.day)}">
            ${data.branch_filter_active
              ? `<select class="cx-select cx-input--compact" id="cxDashBranch"><option value="">كل الفروع</option>${(data.branches || []).map((b) => `<option value="${b.id}" ${String(b.id) === String(state.branchFilter || "") ? "selected" : ""}>${ctx.esc(b.name)}</option>`).join("")}</select>`
              : ""}
            <select class="cx-select cx-input--compact" id="cxDashDoctor">
              <option value="">كل الأطباء</option>
              ${(data.doctors || []).map((d) => `<option value="${d.id}" ${String(d.id) === String(state.doctorFilter || "") ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`).join("")}
            </select>
            <button type="button" class="cx-btn" id="cxDashCal" title="التقويم"><i class="fa fa-calendar"></i></button>
            <div class="cx-notif-wrap">
              <button type="button" class="cx-btn" id="cxDashNotif" title="التنبيهات" aria-haspopup="dialog" aria-expanded="false">
                <i class="fa fa-bell"></i>
                ${(data.alerts || []).length ? `<span class="cx-badge-count">${(data.alerts || []).length}</span>` : ""}
              </button>
              ${alertsPanelHtml(data.alerts || [], ctx)}
            </div>
            <div class="cx-new-action-wrap">
              <button type="button" class="cx-btn cx-btn--primary" id="cxNewActionBtn"><i class="fa fa-plus"></i> إجراء جديد</button>
              ${newActionMenu()}
            </div>
          </div>
        </header>

        ${doctorCard(data.doctor_workspace, ctx)}
        ${data.dashboard_mode === 'owner_doctor_dashboard' ? `<div class="cx-actions"><button class="cx-btn" data-dashboard-view="management">إدارة العيادة</button><button class="cx-btn" data-dashboard-view="clinical">عيادتي</button></div>` : ''}

        ${kpiCards(k, ctx)}
        ${dentalWidgets(data.dental, ctx)}

        <section class="cx-dash-main">
          <article class="cx-card cx-card--main">
            <div class="cx-card__head">
              <div>
                <h2>مواعيد اليوم</h2>
                <p>${k.appointments_today || 0} موعد</p>
              </div>
              <div class="cx-toolbar__filters">
                <button type="button" class="cx-btn cx-btn--sm" data-day-shift="-1">أمس</button>
                <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-day-shift="0">اليوم</button>
                <button type="button" class="cx-btn cx-btn--sm" data-day-shift="1">غداً</button>
                <input type="search" class="cx-input cx-input--sm" id="cxApptFilter" placeholder="بحث في المواعيد…">
              </div>
            </div>
            <div id="cxApptTable">${appointmentsTable(data.appointments || [], ctx)}</div>
          </article>
          <article class="cx-card cx-card--queue">
            <div class="cx-card__head">
              <div><h2>قائمة الانتظار</h2><p>${(data.waiting_queue || []).length} مريض</p></div>
              <button type="button" class="cx-btn cx-btn--sm" id="cxQueueRefresh"><i class="fa fa-rotate"></i></button>
            </div>
            <div id="cxWaitList">${waitingQueue(data.waiting_queue || [], ctx)}</div>
          </article>
        </section>

        ${(() => {
          const row = [
            data.can_view_finance !== false ? financeCard(data.finance || {}, ctx) : "",
            followupsCard(data.followups || [], ctx),
          ].filter(Boolean);
          return row.length
            ? `<section class="cx-dash-row cx-dash-row--${row.length}">${row.join("")}</section>`
            : "";
        })()}
      </div>`;
  }

  async function bindApptActions(root, ctx) {
    root.querySelectorAll("[data-appt-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const id = btn.dataset.id;
          const act = btn.dataset.apptAct;
          if (act === "start") {
            const visit = await ctx.api("/clinics/api/visits", {
              method: "POST",
              body: JSON.stringify({ appointment_id: Number(id) }),
            });
            location.href = `/clinics/doctor/${visit.id}`;
            return;
          }
          const map = { arrived: "arrived", waiting: "waiting", cancel: "cancelled" };
          await ctx.api(`/clinics/api/appointments/${id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: map[act] || act }),
          });
          ctx.showNotice("تم تحديث حالة الموعد", false);
          await ctx.refresh();
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      });
    });
  }

  function bindUI(root, state, ctx) {
    const dayInput = root.querySelector("#cxDashDay");
    if (dayInput) {
      dayInput.onchange = (e) => {
        state.day = e.target.value;
        ctx.refresh();
      };
    }
    const doctorSel = root.querySelector("#cxDashDoctor");
    root.querySelectorAll('[data-dashboard-view]').forEach(button=>button.onclick=()=>{state.dashboardView=button.dataset.dashboardView;state.doctorFilter=state.dashboardView==='clinical'?String(ctx.data.current_doctor_id||''):'';ctx.refresh()});
    if (doctorSel) {
      doctorSel.onchange = (e) => {
        state.doctorFilter = e.target.value;
        ctx.refresh();
      };
    }
    const branchSel = root.querySelector("#cxDashBranch");
    if (branchSel) {
      branchSel.onchange = (e) => {
        state.branchFilter = e.target.value;
        ctx.refresh();
      };
    }
    root.querySelectorAll("[data-day-shift]").forEach((btn) => {
      btn.onclick = () => {
        const shift = Number(btn.dataset.dayShift || 0);
        const d = new Date(state.day + "T12:00:00");
        if (shift === 0) {
          state.day = localToday();
        } else {
          d.setDate(d.getDate() + shift);
          state.day = d.toISOString().slice(0, 10);
        }
        ctx.refresh();
      };
    });
    const apptFilter = root.querySelector("#cxApptFilter");
    if (apptFilter && ctx.data) {
      apptFilter.oninput = () => {
        const table = root.querySelector("#cxApptTable");
        if (table) {
          table.innerHTML = appointmentsTable(ctx.data.appointments || [], ctx, apptFilter.value);
          bindApptActions(root, ctx);
          root.querySelector("#cxDashNewAppt")?.addEventListener("click", () => ctx.promptNewAppointment());
        }
      };
    }
    root.querySelector("#cxQueueRefresh")?.addEventListener("click", () => ctx.refresh());
    root.querySelector("#cxDashCal")?.addEventListener("click", () => {
      location.href = "/clinics/appointments";
    });
    bindNotifPanel(root);
    root.querySelector("#cxDashNewPatient")?.addEventListener("click", () => ctx.promptNewPatient());
    root.querySelectorAll("#cxDashNewAppt, #cxDashNewPatient").forEach((el) => {
      if (el.id === "cxDashNewAppt") el.addEventListener("click", () => ctx.promptNewAppointment());
    });
    const newBtn = root.querySelector("#cxNewActionBtn");
    const menu = root.querySelector("#cxNewActionMenu");
    if (newBtn && menu) {
      newBtn.onclick = () => {
        menu.hidden = !menu.hidden;
      };
      menu.querySelectorAll("button").forEach((b) => {
        b.onclick = () => {
          menu.hidden = true;
          const a = b.dataset.action;
          if (a === "patient") ctx.promptNewPatient();
          else if (a === "appointment") ctx.promptNewAppointment();
          else if (a === "visit") location.href = "/clinics/visits";
          else if (a === "invoice" || a === "payment") location.href = "/clinics/billing";
          else if (a === "expense") location.href = "/clinics/expenses";
          else if (a === "call") location.href = "/clinics/communications";
        };
      });
      document.addEventListener(
        "click",
        (e) => {
          if (!menu.hidden && !menu.contains(e.target) && e.target !== newBtn) menu.hidden = true;
        },
        { once: true }
      );
    }

    const search = root.querySelector("#cxGlobalSearch");
    const results = root.querySelector("#cxSearchResults");
    if (search && results) {
      const run = async () => {
        const q = search.value.trim();
        if (q.length < 2) {
          results.hidden = true;
          return;
        }
        try {
          const data = await ctx.api(`/clinics/api/search?q=${encodeURIComponent(q)}`);
          const parts = [];
          (data.patients || []).forEach((p) => {
            parts.push(`<a href="${p.href}" class="cx-search-item"><i class="fa fa-user"></i><span>${ctx.esc(p.full_name)} · ${ctx.esc(p.phone)}</span></a>`);
          });
          (data.appointments || []).forEach((a) => {
            parts.push(`<a href="${a.href}" class="cx-search-item"><i class="fa fa-calendar"></i><span>${ctx.esc(a.patient_name)} · ${ctx.esc(a.date)} ${ctx.esc(a.time)}</span></a>`);
          });
          (data.invoices || []).forEach((i) => {
            parts.push(`<a href="${i.href}" class="cx-search-item"><i class="fa fa-file-invoice"></i><span>فاتورة ${ctx.esc(i.invoice_number)} · ${ctx.money(i.total)}</span></a>`);
          });
          (data.doctors || []).forEach((d) => {
            parts.push(`<a href="${d.href}" class="cx-search-item"><i class="fa fa-user-doctor"></i><span>${ctx.esc(d.full_name)} · ${ctx.esc(d.specialty || "")}</span></a>`);
          });
          (data.treatment_plans || []).forEach((p) => {
            parts.push(`<a href="${p.href}" class="cx-search-item"><i class="fa fa-clipboard-list"></i><span>خطة علاج ${ctx.esc(p.name)}</span></a>`);
          });
          (data.treatments || []).forEach((t) => {
            parts.push(`<a href="${t.href}" class="cx-search-item"><i class="fa fa-tooth"></i><span>${ctx.esc(t.title)}${t.tooth_number ? ` · السن ${ctx.esc(t.tooth_number)}` : ""}</span></a>`);
          });
          results.innerHTML = parts.join("") || '<div class="cx-empty">لا نتائج</div>';
          results.hidden = false;
        } catch {
          results.hidden = true;
        }
      };
      search.addEventListener("input", () => {
        clearTimeout(search._t);
        search._t = setTimeout(run, 280);
      });
    }

    bindApptActions(root, ctx);
    bindQueueDragDrop(root, state, ctx);
  }

  function bindQueueDragDrop(root, state, ctx) {
    const list = root.querySelector("#cxWaitList");
    if (!list || !can(ctx, "clinics_reception")) return;
    let dragId = null;
    list.querySelectorAll(".cx-wait-item[draggable=true]").forEach((item) => {
      item.addEventListener("dragstart", (e) => {
        dragId = item.dataset.waitId;
        item.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
      });
      item.addEventListener("dragend", () => {
        item.classList.remove("is-dragging");
        dragId = null;
      });
      item.addEventListener("dragover", (e) => {
        e.preventDefault();
        item.classList.add("is-over");
      });
      item.addEventListener("dragleave", () => item.classList.remove("is-over"));
      item.addEventListener("drop", async (e) => {
        e.preventDefault();
        item.classList.remove("is-over");
        if (!dragId || dragId === item.dataset.waitId) return;
        const ids = [...list.querySelectorAll(".cx-wait-item")].map((el) => el.dataset.waitId);
        const from = ids.indexOf(dragId);
        const to = ids.indexOf(item.dataset.waitId);
        if (from < 0 || to < 0) return;
        ids.splice(to, 0, ids.splice(from, 1)[0]);
        try {
          await ctx.api("/clinics/api/queue/reorder", {
            method: "POST",
            body: JSON.stringify({ date: state.day, order: ids.map(Number) }),
          });
          ctx.showNotice("تم تحديث ترتيب الانتظار", false);
          await ctx.refresh({ silent: true });
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      });
    });
    list.querySelectorAll("[data-queue-emergency]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const id = btn.dataset.queueEmergency;
          const row = (ctx.data?.waiting_queue || []).find((x) => String(x.id) === String(id));
          await ctx.api(`/clinics/api/appointments/${id}/emergency`, {
            method: "POST",
            body: JSON.stringify({ emergency: !row?.is_emergency }),
          });
          ctx.showNotice(row?.is_emergency ? "تم إلغاء وضع الطوارئ" : "تم تعيين المريض كطارئ", false);
          await ctx.refresh({ silent: true });
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      };
    });
  }

  function patchDashboard(root, data, state, ctx) {
    ctx.data = data;
    const k = data.kpis || {};
    const kpis = root.querySelector(".cx-dash-kpis:not(.cx-dash-kpis--dental)");
    if (kpis) {
      const next = document.createElement("div");
      next.innerHTML = kpiCards(k, ctx);
      const fresh = next.firstElementChild;
      if (fresh) kpis.replaceWith(fresh);
    }
    const waitHead = root.querySelector(".cx-card--queue .cx-card__head p");
    if (waitHead) waitHead.textContent = `${(data.waiting_queue || []).length} مريض`;
    const waitList = root.querySelector("#cxWaitList");
    if (waitList) {
      waitList.innerHTML = waitingQueue(data.waiting_queue || [], ctx);
      bindQueueDragDrop(root, state, ctx);
      bindApptActions(root, ctx);
    }
    const apptTable = root.querySelector("#cxApptTable");
    const apptFilter = root.querySelector("#cxApptFilter");
    if (apptTable) {
      apptTable.innerHTML = appointmentsTable(data.appointments || [], ctx, apptFilter?.value || "");
      bindApptActions(root, ctx);
    }
    const notifBtn = root.querySelector("#cxDashNotif");
    if (notifBtn) {
      const badge = notifBtn.querySelector(".cx-badge-count");
      const count = (data.alerts || []).length;
      if (count) {
        if (badge) badge.textContent = count;
        else notifBtn.insertAdjacentHTML("beforeend", `<span class="cx-badge-count">${count}</span>`);
      } else if (badge) badge.remove();
    }
    const list = root.querySelector("#cxNotifList");
    const head = root.querySelector(".cx-notif-panel__head span");
    if (list) list.innerHTML = alertsListHtml(data.alerts || [], ctx);
    if (head) head.textContent = (data.alerts || []).length ? `${(data.alerts || []).length} عنصر` : "لا يوجد";
  }

  let pollTimer = null;
  let lastPulseVersion = null;

  async function startPulse(state, root, helpers) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const qs = new URLSearchParams({ date: state.day });
        if (state.doctorFilter) qs.set("doctor_id", state.doctorFilter);
        if (state.branchFilter) qs.set("branch_id", state.branchFilter);
        const pulse = await helpers.api(`/clinics/api/dashboard/pulse?${qs}`);
        if (lastPulseVersion && pulse.version === lastPulseVersion) return;
        lastPulseVersion = pulse.version;
        await render(state, root, helpers, { silent: true });
      } catch {
        /* ignore pulse errors */
      }
    }, 12000);
  }

  async function render(state, root, helpers, opts = {}) {
    if (!opts.silent) root.innerHTML = skeletonDashboard();
    try {
      const data = await (async () => {
        const qs = new URLSearchParams({ date: state.day });
        if (state.doctorFilter) qs.set("doctor_id", state.doctorFilter);
        if (state.branchFilter) qs.set("branch_id", state.branchFilter);
        qs.set('view', state.dashboardView || 'management');
        return helpers.api(`/clinics/api/dashboard?${qs}`);
      })();
      if (data.user) helpers.bootstrap.user = data.user;
      lastPulseVersion = data.pulse_version || lastPulseVersion;
      const ctx = {
        ...helpers,
        data,
        bootstrap: helpers.bootstrap,
        refresh: (o) => render(state, root, helpers, o),
      };
      if (opts.silent && root.querySelector(".cx-dash")) {
        patchDashboard(root, data, state, ctx);
      } else {
        root.innerHTML = buildHtml(data, state, ctx);
        bindUI(root, state, ctx);
      }
      if (!opts.silent) startPulse(state, root, helpers);
      return ctx;
    } catch (err) {
      if (!opts.silent) {
        root.innerHTML = `<div class="cx-empty">تعذر تحميل لوحة التحكم: ${helpers.esc(err.message || String(err))}</div>`;
      }
      throw err;
    }
  }

  window.ClinicsDashboard = { render, skeletonDashboard };
})();
