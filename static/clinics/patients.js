/**
 * Finora Clinics — Patient Registry
 */
(() => {
  const STATUS = {
    active: { label: "نشط", cls: "green" },
    new: { label: "جديد", cls: "teal" },
    upcoming: { label: "موعد قادم", cls: "blue" },
    followup: { label: "متابعة", cls: "purple" },
    balance_due: { label: "عليه رصيد", cls: "orange" },
    archived: { label: "مؤرشف", cls: "gray" },
  };

  function can(ctx, perm) {
    const u = ctx.bootstrap?.user || ctx.data?.user || {};
    if (u.role === "admin") return true;
    return (u.permissions || []).includes(perm);
  }

  function statusBadge(op) {
    const s = STATUS[op] || STATUS.active;
    return `<span class="cx-pat-badge cx-pat-badge--${s.cls}">${s.label}</span>`;
  }

  function genderLabel(g) {
    const n = String(g || "").toLowerCase();
    return { male: "ذكر", female: "أنثى", m: "ذكر", f: "أنثى" }[n] || g || "—";
  }

  function avatarHtml(name) {
    const ch = (name || "م").trim().charAt(0) || "م";
    return `<span class="cx-pat-avatar" aria-hidden="true">${ch}</span>`;
  }

  function fmtVisit(lv) {
    if (!lv || !lv.visit_date) return { main: "—", sub: "" };
    const today = new Date().toISOString().slice(0, 10);
    const d = lv.visit_date;
    let main = d;
    if (d === today && lv.started_at) {
      main = `اليوم ${window.FinoraTime.time(lv.started_at)}`;
    } else {
      try {
        main = new Date(d + "T12:00:00").toLocaleDateString("ar-IQ", {
          day: "numeric",
          month: "short",
          year: "numeric",
        });
      } catch {
        main = d;
      }
    }
    const sub = [lv.doctor_name, lv.chief_complaint].filter(Boolean).join(" · ");
    return { main, sub };
  }

  function fmtAppt(na) {
    if (!na || !na.appointment_date) return "—";
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const t0 = today.toISOString().slice(0, 10);
    const t1 = tomorrow.toISOString().slice(0, 10);
    const d = na.appointment_date;
    let dayLabel = d;
    if (d === t0) dayLabel = "اليوم";
    else if (d === t1) dayLabel = "غداً";
    else {
      try {
        dayLabel = new Date(d + "T12:00:00").toLocaleDateString("ar-IQ", {
          day: "numeric",
          month: "short",
        });
      } catch {
        dayLabel = d;
      }
    }
    return `${dayLabel} ${window.FinoraTime.clock(na.start_time || "")}`.trim();
  }

  function allergyIcon(p, ctx) {
    if (!p.has_allergy || !ctx.data?.can_clinical) return "";
    const tip = ctx.esc(p.allergy_preview || "حساسية");
    return `<span class="cx-pat-allergy" title="${tip}"><i class="fa fa-triangle-exclamation"></i></span>`;
  }

  function buildQs(state) {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    p.set("page", String(state.page || 1));
    p.set("per_page", String(state.per_page || 25));
    if (state.sort) p.set("sort", state.sort);
    if (state.status_group) p.set("status_group", state.status_group);
    if (state.doctor_id) p.set("doctor_id", state.doctor_id);
    if (state.gender) p.set("gender", state.gender);
    if (state.upcoming_only) p.set("upcoming_only", "1");
    if (state.balance_only) p.set("balance_only", "1");
    if (state.followup_only) p.set("followup_only", "1");
    if (state.new_only) p.set("new_only", "1");
    if (state.last_visit) p.set("last_visit", state.last_visit);
    if (state.no_visit_days) p.set("no_visit_days", state.no_visit_days);
    return p.toString();
  }

  function kpisHtml(data) {
    const s = data.stats || {};
    const cards = [
      { label: "إجمالي المرضى", val: s.total || 0, theme: "teal", icon: "fa-users" },
      { label: "جديد هذا الشهر", val: s.new_this_month || 0, theme: "green", icon: "fa-user-plus" },
      { label: "زاروا اليوم", val: s.visited_today || 0, theme: "cyan", icon: "fa-door-open" },
      { label: "لديهم موعد قادم", val: s.upcoming || 0, theme: "sky", icon: "fa-calendar-check" },
      { label: "عليهم رصيد (مستحقات)", val: s.with_balance || 0, theme: "amber", icon: "fa-coins", wide: true },
    ];
    return cards
      .map(
        (c) => `
      <article class="cx-pat-kpi cx-pat-kpi--${c.theme}${c.wide ? " cx-pat-kpi--wide" : ""}">
        <div><span>${c.label}</span><strong>${c.val}</strong></div>
        <i class="fa ${c.icon}"></i>
      </article>`
      )
      .join("");
  }

  function filtersHtml(ctx) {
    const doctors = ctx.data?.doctors || [];
    return `
      <section class="cx-pat-filters-wrap">
        <div class="cx-pat-filters">
          <select class="cx-select" id="cxPatStatus" aria-label="حالة المريض">
            <option value="active" ${ctx.state.status_group === "active" ? "selected" : ""}>كافة المرضى النشطين</option>
            <option value="all" ${ctx.state.status_group === "all" ? "selected" : ""}>كل السجلات</option>
            <option value="archived" ${ctx.state.status_group === "archived" ? "selected" : ""}>المرضى المؤرشفون</option>
          </select>
          <select class="cx-select" id="cxPatUpcoming" aria-label="المواعيد">
            <option value="">موعد قادم</option>
            <option value="1" ${ctx.state.upcoming_only ? "selected" : ""}>لديه موعد</option>
          </select>
          <select class="cx-select" id="cxPatDoctor" aria-label="الطبيب المعالج">
            <option value="">الطبيب المعالج</option>
            ${doctors.map((d) => `<option value="${d.id}" ${String(d.id) === String(ctx.state.doctor_id || "") ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`).join("")}
          </select>
          <select class="cx-select" id="cxPatLastVisit" aria-label="آخر زيارة">
            <option value="">آخر زيارة</option>
            <option value="7" ${ctx.state.last_visit === "7" ? "selected" : ""}>آخر 7 أيام</option>
            <option value="30" ${ctx.state.last_visit === "30" ? "selected" : ""}>آخر 30 يوم</option>
            <option value="90" ${ctx.state.last_visit === "90" ? "selected" : ""}>آخر 90 يوم</option>
            <option value="none" ${ctx.state.last_visit === "none" ? "selected" : ""}>بدون زيارة</option>
          </select>
        </div>
        <div class="cx-pat-filter-tools">
          <button type="button" class="cx-btn cx-btn--ghost" id="cxPatMoreFilters"><i class="fa fa-sliders"></i> فلاتر إضافية</button>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxPatReset">إعادة ضبط</button>
          ${ctx.data?.can_export ? `<button type="button" class="cx-btn cx-btn--ghost" id="cxPatExport"><i class="fa fa-download"></i> تصدير</button>` : ""}
        </div>
        <div class="cx-pat-extra-filters" id="cxPatExtra" ${ctx.state.extraOpen ? "" : "hidden"}>
          <select class="cx-select" id="cxPatGender">
            <option value="">الجنس</option>
            <option value="male" ${ctx.state.gender === "male" ? "selected" : ""}>ذكر</option>
            <option value="female" ${ctx.state.gender === "female" ? "selected" : ""}>أنثى</option>
          </select>
          <label class="cx-pat-check"><input type="checkbox" id="cxPatNew" ${ctx.state.new_only ? "checked" : ""}> مريض جديد</label>
          <label class="cx-pat-check"><input type="checkbox" id="cxPatBal" ${ctx.state.balance_only ? "checked" : ""}> عليه رصيد</label>
          <label class="cx-pat-check"><input type="checkbox" id="cxPatFu" ${ctx.state.followup_only ? "checked" : ""}> متابعة</label>
          <select class="cx-select" id="cxPatNoVisit">
            <option value="">بدون زيارة منذ</option>
            <option value="90" ${ctx.state.no_visit_days === "90" ? "selected" : ""}>90+ يوم</option>
            <option value="180" ${ctx.state.no_visit_days === "180" ? "selected" : ""}>180+ يوم</option>
          </select>
          <select class="cx-select" id="cxPatSort">
            <option value="created_at" ${ctx.state.sort === "created_at" ? "selected" : ""}>ترتيب: التسجيل</option>
            <option value="name" ${ctx.state.sort === "name" ? "selected" : ""}>الاسم</option>
            <option value="last_visit" ${ctx.state.sort === "last_visit" ? "selected" : ""}>آخر زيارة</option>
            <option value="next_appointment" ${ctx.state.sort === "next_appointment" ? "selected" : ""}>الموعد القادم</option>
            <option value="balance" ${ctx.state.sort === "balance" ? "selected" : ""}>الرصيد</option>
          </select>
        </div>
      </section>`;
  }

  function emptyStateHtml() {
    return `
      <div class="cx-pat-empty">
        <div class="cx-pat-empty__panel">
          <div class="cx-pat-empty__icon"><i class="fa fa-folder-open"></i></div>
          <h3>لا توجد سجلات مرضى حالياً</h3>
          <p>يمكنك إضافة مريض جديد للبدء في إدارة الملفات الطبية والمواعيد</p>
          <button type="button" class="cx-btn cx-btn--primary" id="cxPatEmptyAdd"><i class="fa fa-plus"></i> إضافة أول مريض</button>
        </div>
      </div>`;
  }

  function tableRows(ctx) {
    const rows = ctx.data?.patients || [];
    if (!rows.length) return "";
    return rows
      .map((p) => {
        const lv = fmtVisit(p.last_visit);
        const ap = fmtAppt(p.next_appointment);
        const bal =
          p.balance != null
            ? `<span class="cx-pat-bal${p.balance > 0 ? " is-due" : ""}">${ctx.money(p.balance)}</span>`
            : "—";
        return `
        <tr data-pid="${p.id}">
          <td><code>${ctx.esc(p.file_number || "")}</code></td>
          <td>
            <button type="button" class="cx-pat-name" data-open="${p.id}">
              ${avatarHtml(p.full_name)}
              <span><strong>${ctx.esc(p.full_name)}</strong><small>${ctx.esc(p.file_number || "")}</small></span>
              ${allergyIcon(p, ctx)}
            </button>
          </td>
          <td>${ctx.esc(p.phone || "—")}</td>
          <td>${p.age != null ? `${p.age} سنة` : "—"}</td>
          <td class="cx-pat-hint" title="${ctx.esc(lv.sub)}">${ctx.esc(lv.main)}</td>
          <td>${p.next_appointment ? `<button type="button" class="cx-pat-link" data-appt="${p.next_appointment.appointment_id}">${ctx.esc(ap)}</button>` : "—"}</td>
          <td>${bal}</td>
          <td>${statusBadge(p.operational_status)}</td>
          <td class="cx-pat-actions">
            <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-open="${p.id}">فتح الملف</button>
            <button type="button" class="cx-btn cx-btn--sm cx-btn--ghost" data-menu="${p.id}"><i class="fa fa-ellipsis-vertical"></i></button>
            <div class="cx-pat-menu" hidden data-for="${p.id}">
              <button type="button" data-act="appt" data-id="${p.id}">موعد جديد</button>
              <button type="button" data-act="visit" data-id="${p.id}">زيارة مباشرة</button>
              ${p.phone ? `<a href="tel:${ctx.esc(p.phone)}">اتصال</a>` : ""}
              <button type="button" data-act="edit" data-id="${p.id}">تعديل</button>
              <button type="button" data-act="print" data-id="${p.id}">طباعة بطاقة</button>
              <button type="button" data-act="archive" data-id="${p.id}">أرشفة</button>
              <button type="button" data-act="merge" data-id="${p.id}">دمج سجل مكرر</button>
            </div>
          </td>
        </tr>`;
      })
      .join("");
  }

  function paginationHtml(ctx) {
    const pg = ctx.data?.pagination || {};
    return `
      <div class="cx-pat-pager">
        <span>عرض ${pg.from || 0}-${pg.to || 0} من ${pg.total || 0} مريض</span>
        <div class="cx-pat-pager__nav">
          <span class="cx-pat-pager__page">${pg.page || 1} / ${pg.pages || 1}</span>
          <button type="button" class="cx-btn cx-btn--sm" id="cxPatPrev" ${pg.page <= 1 ? "disabled" : ""}>السابق</button>
          <button type="button" class="cx-btn cx-btn--sm" id="cxPatNext" ${pg.page >= pg.pages ? "disabled" : ""}>التالي</button>
        </div>
        <select class="cx-select cx-input--compact" id="cxPatPerPage">
          ${[25, 50, 100].map((n) => `<option value="${n}" ${Number(ctx.state.per_page) === n ? "selected" : ""}>${n} / صفحة</option>`).join("")}
        </select>
      </div>`;
  }

  function apptStatusLabel(st) {
    const map = {
      pending: "قيد الانتظار",
      confirmed: "مؤكد",
      scheduled: "مجدول",
      arrived: "وصل",
      waiting: "بالانتظار",
      in_progress: "جارية",
      done: "منتهية",
      cancelled: "ملغاة",
    };
    return map[st] || st || "—";
  }

  function printPatientCard(p, ctx) {
    const w = window.open("", "_blank", "width=480,height=640");
    if (!w) {
      ctx.showNotice("تعذر فتح نافذة الطباعة");
      return;
    }
    const clinic = ctx.bootstrap?.tenant?.name || ctx.bootstrap?.clinic_name || "Finora Clinics";
    w.document.write(`
      <!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
      <title>بطاقة مريض — ${ctx.esc(p.full_name || "")}</title>
      <style>
        body{font-family:system-ui,sans-serif;padding:24px;color:#0f172a}
        .card{border:2px solid #0d9488;border-radius:16px;padding:20px;max-width:360px}
        h1{margin:0 0 4px;font-size:1.25rem}
        .meta{color:#64748b;font-size:13px;margin-bottom:16px}
        .row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid #e2e8f0;font-size:14px}
        .row span{color:#64748b}
        .foot{margin-top:16px;font-size:11px;color:#94a3b8;text-align:center}
      </style></head><body>
      <div class="card">
        <h1>${ctx.esc(p.full_name || "")}</h1>
        <div class="meta">${ctx.esc(p.file_number || "")} · ${p.age != null ? p.age + " سنة" : "—"} · ${genderLabel(p.gender)}</div>
        <div class="row"><span>الهاتف</span><b>${ctx.esc(p.phone || "—")}</b></div>
        <div class="row"><span>العنوان</span><b>${ctx.esc(p.address || "—")}</b></div>
        ${p.blood_type ? `<div class="row"><span>فصيلة الدم</span><b>${ctx.esc(p.blood_type)}</b></div>` : ""}
        <div class="foot">${ctx.esc(clinic)}</div>
      </div>
      <script>window.onload=function(){window.print();}<\/script>
      </body></html>`);
    w.document.close();
  }

  function apptDrawerHtml(appt, ctx) {
    if (!appt) return "";
    return `
      <aside class="cx-pat-appt-drawer" id="cxPatApptDrawer">
        <header class="cx-pat-drawer__head">
          <div>
            <h2>الموعد القادم</h2>
            <p>${ctx.esc(appt.patient_name || "")}</p>
          </div>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxPatApptClose"><i class="fa fa-xmark"></i></button>
        </header>
        <div class="cx-pat-drawer__body">
          <div class="cx-pat-drawer__field"><span>التاريخ</span><b>${ctx.esc(appt.appointment_date || "—")}</b></div>
          <div class="cx-pat-drawer__field"><span>الوقت</span><b>${ctx.esc(window.FinoraTime.clock(appt.start_time || "—"))}</b></div>
          <div class="cx-pat-drawer__field"><span>الطبيب</span><b>${ctx.esc(appt.doctor_name || "—")}</b></div>
          <div class="cx-pat-drawer__field"><span>الخدمة</span><b>${ctx.esc(appt.service_name || "—")}</b></div>
          <div class="cx-pat-drawer__field"><span>الحالة</span><b>${ctx.esc(apptStatusLabel(appt.status))}</b></div>
          ${appt.notes ? `<div class="cx-pat-drawer__field"><span>ملاحظات</span><b>${ctx.esc(appt.notes)}</b></div>` : ""}
        </div>
        <footer class="cx-pat-drawer__foot">
          <a class="cx-btn cx-btn--primary" href="/clinics/appointments?date=${ctx.esc(appt.appointment_date || "")}">فتح في المواعيد</a>
          ${appt.patient_id ? `<a class="cx-btn" href="/clinics/patients/${appt.patient_id}">ملف المريض</a>` : ""}
        </footer>
      </aside>`;
  }

  function drawerHtml(p, ctx) {
    if (!p) return "";
    const lv = p.last_visit || {};
    const na = p.next_appointment || {};
    return `
      <aside class="cx-pat-drawer" id="cxPatDrawer">
        <header class="cx-pat-drawer__head">
          <div class="cx-pat-drawer__hero">
            ${avatarHtml(p.full_name)}
            <div>
              <h2>${ctx.esc(p.full_name)}</h2>
              <p>${ctx.esc(p.file_number || "")} · ${p.age != null ? p.age + " سنة" : "—"} · ${genderLabel(p.gender)}</p>
            </div>
          </div>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxPatDrawerClose"><i class="fa fa-xmark"></i></button>
        </header>
        <div class="cx-pat-drawer__body">
          <div class="cx-pat-drawer__field"><span>الهاتف</span><b>${ctx.esc(p.phone || "—")}</b></div>
          <div class="cx-pat-drawer__field"><span>العنوان</span><b>${ctx.esc(p.address || "—")}</b></div>
          <div class="cx-pat-drawer__field"><span>آخر زيارة</span><b>${ctx.esc(fmtVisit(lv).main)} ${lv.doctor_name ? `· ${ctx.esc(lv.doctor_name)}` : ""}</b></div>
          <div class="cx-pat-drawer__field"><span>الموعد القادم</span><b>${ctx.esc(fmtAppt(na))}</b></div>
          ${ctx.data?.can_finance ? `<div class="cx-pat-drawer__field"><span>الرصيد</span><b>${ctx.money(p.balance || 0)}</b></div>` : ""}
          ${ctx.data?.can_clinical && p.has_allergy ? `<div class="cx-pat-drawer__alert"><i class="fa fa-triangle-exclamation"></i> ${ctx.esc(p.allergies || p.allergy_preview || "حساسية")}</div>` : ""}
          ${p.notes ? `<div class="cx-pat-drawer__field"><span>ملاحظات</span><b>${ctx.esc(p.notes)}</b></div>` : ""}
        </div>
        <footer class="cx-pat-drawer__foot">
          <a class="cx-btn cx-btn--primary" href="/clinics/patients/${p.id}">فتح الملف الطبي</a>
          <button type="button" class="cx-btn" data-drawer-act="appt" data-id="${p.id}">+ موعد</button>
          <button type="button" class="cx-btn" data-drawer-act="visit" data-id="${p.id}">+ زيارة</button>
          ${p.phone ? `<a class="cx-btn" href="tel:${ctx.esc(p.phone)}">اتصال</a>` : ""}
          ${ctx.data?.can_finance ? `<button type="button" class="cx-btn" data-drawer-act="pay" data-id="${p.id}">تحصيل</button>` : ""}
          <button type="button" class="cx-btn" data-drawer-act="print" data-id="${p.id}">طباعة بطاقة</button>
          <button type="button" class="cx-btn" data-drawer-act="more" data-id="${p.id}">المزيد</button>
        </footer>
      </aside>`;
  }

  function buildHtml(ctx) {
    const p = ctx.drawerPatient;
    const ap = ctx.apptDrawer;
    const rows = ctx.data?.patients || [];
    const listBody = rows.length
      ? `<div class="cx-table-wrap">
            <table class="cx-table cx-pat-table">
              <thead>
                <tr>
                  <th>الملف</th><th>المريض</th><th>الهاتف</th><th>العمر</th>
                  <th>آخر زيارة</th><th>الموعد القادم</th><th>الرصيد</th><th>الحالة</th><th>الإجراء</th>
                </tr>
              </thead>
              <tbody>${tableRows(ctx)}</tbody>
            </table>
          </div>`
      : emptyStateHtml();
    return `
      <div class="cx-pat ${p ? "has-drawer" : ""} ${ap ? "has-appt-drawer" : ""}">
        <header class="cx-pat-header">
          <div class="cx-pat-header__title">
            <span class="cx-pat-kicker">FINORA CLINICS</span>
            <h1>المرضى</h1>
            <p>سجل جميع المرضى في العيادة</p>
          </div>
        </header>
        <div class="cx-pat-header__search">
          <i class="fa fa-search"></i>
          <input type="search" class="cx-input" id="cxPatSearch" data-finora-field="patients.search" placeholder="بحث بالاسم، الهاتف، رقم الملف أو رقم الهوية..." value="${ctx.esc(ctx.state.q || "")}">
          <div class="cx-pat-search-hint">Ctrl+K</div>
          <div class="cx-pat-search-drop" id="cxPatSearchDrop" hidden></div>
        </div>
        <button type="button" class="cx-btn cx-btn--primary cx-pat-add" id="cxPatAdd" data-finora-action="patient.create"><i class="fa fa-plus"></i> مريض جديد</button>
        <div class="cx-pat-kpis">${kpisHtml(ctx.data)}</div>
        ${filtersHtml(ctx)}
        <article class="cx-pat-table-card${rows.length ? "" : " cx-pat-table-card--empty"}" data-finora-section="patients.list">
          ${listBody}
          ${paginationHtml(ctx)}
        </article>
        ${p ? drawerHtml(p, ctx) : ""}
        ${ap ? apptDrawerHtml(ap, ctx) : ""}
        <div class="cx-pat-drawer-backdrop" id="cxPatBackdrop" ${p || ap ? "" : "hidden"}></div>
      </div>`;
  }

  function skeleton() {
    return `
      <div class="cx-pat">
        <div class="cx-skeleton-block" style="height:72px;border-radius:14px"></div>
        <div class="cx-pat-kpis">${Array(5).fill('<div class="cx-skeleton-block" style="height:88px;border-radius:14px"></div>').join("")}</div>
        <div class="cx-skeleton-block" style="height:420px;border-radius:16px"></div>
      </div>`;
  }

  function findPatient(ctx, id) {
    return (ctx.data?.patients || []).find((x) => String(x.id) === String(id));
  }

  async function openApptDrawer(ctx, apptId, hint) {
    try {
      let appt = hint;
      if (!appt || !appt.patient_name) {
        appt = await ctx.api(`/clinics/api/appointments/${apptId}`);
      }
      if (appt && !appt.id) appt = { ...appt, id: apptId };
      ctx.apptDrawer = appt;
      paint(ctx);
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  async function loadDrawerPatient(ctx, id) {
    try {
      const detail = await ctx.api(`/clinics/api/patients/${id}`);
      const p = detail.patient || detail;
      const row = findPatient(ctx, id) || {};
      ctx.drawerPatient = { ...row, ...p };
      if (ctx.data?.can_finance && row.balance != null) ctx.drawerPatient.balance = row.balance;
      if (row.last_visit) ctx.drawerPatient.last_visit = row.last_visit;
      if (row.next_appointment) ctx.drawerPatient.next_appointment = row.next_appointment;
      paint(ctx);
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  function promptAddPatient(ctx) {
    ctx.openModal(
      "مريض جديد",
      `
      <div data-finora-section="patient.form">
      <div class="cx-field"><label>الاسم الكامل *</label><input class="cx-input" id="f_full_name" data-finora-field="patient.name" required></div>
      <div class="cx-field"><label>رقم الهاتف *</label><input class="cx-input" id="f_phone" data-finora-field="patient.phone" required></div>
      <div class="cx-field-row">
        <div class="cx-field"><label>الجنس</label><select class="cx-select" id="f_gender" data-finora-field="patient.gender"><option value="">—</option><option value="male">ذكر</option><option value="female">أنثى</option></select></div>
        <div class="cx-field"><label>تاريخ الميلاد</label><input class="cx-input" type="date" id="f_dob" data-finora-field="patient.birthdate"></div>
      </div>
      <div class="cx-field"><label>العنوان</label><input class="cx-input" id="f_address" data-finora-field="patient.address"></div>
      <div class="cx-field-row">
        <div class="cx-field"><label>فصيلة الدم</label><input class="cx-input" id="f_blood" data-finora-field="patient.blood_type"></div>
        <div class="cx-field"><label>طوارئ</label><input class="cx-input" id="f_emergency_phone" data-finora-field="patient.emergency_phone"></div>
      </div>
      <div class="cx-field"><label>الحساسية</label><textarea class="cx-textarea" id="f_allergies" data-finora-field="patient.allergies"></textarea></div>
      <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="f_notes" data-finora-field="patient.notes"></textarea></div>
      <div id="cxPhoneDupWarn" class="cx-phone-warn" hidden></div>
      <div id="cxSimilarWarn" class="cx-phone-warn" hidden></div>
      </div>`,
      async () => {
        const phone = document.getElementById("f_phone").value.trim();
        const check = await ctx.api(`/clinics/api/patients/check-phone?phone=${encodeURIComponent(phone)}`);
        if (check.exists && check.patient) {
          throw new Error(`يوجد مريض مسجل بهذا الرقم: ${check.patient.full_name}`);
        }
        await ctx.api("/clinics/api/patients", {
          method: "POST",
          body: JSON.stringify({
            full_name: document.getElementById("f_full_name").value,
            phone,
            gender: document.getElementById("f_gender").value,
            date_of_birth: document.getElementById("f_dob").value,
            address: document.getElementById("f_address").value,
            blood_type: document.getElementById("f_blood").value,
            emergency_phone: document.getElementById("f_emergency_phone").value,
            allergies: document.getElementById("f_allergies").value,
            notes: document.getElementById("f_notes").value,
          }),
        });
        ctx.showNotice("تم تسجيل المريض", false);
        await refresh(ctx);
      },
      { finoraAction: "patient.save" }
    );
    const phoneInput = document.getElementById("f_phone");
    const nameInput = document.getElementById("f_full_name");
    const dobInput = document.getElementById("f_dob");
    const warn = document.getElementById("cxPhoneDupWarn");
    const similarWarn = document.getElementById("cxSimilarWarn");

    const checkSimilar = () => {
      clearTimeout(nameInput?._simT);
      nameInput._simT = setTimeout(async () => {
        const name = nameInput?.value.trim() || "";
        const dob = dobInput?.value || "";
        if (name.length < 3) {
          similarWarn.hidden = true;
          return;
        }
        try {
          const qs = new URLSearchParams({ full_name: name });
          if (dob) qs.set("date_of_birth", dob);
          const res = await ctx.api(`/clinics/api/patients/check-similar?${qs}`);
          const list = res.matches || [];
          if (list.length) {
            similarWarn.hidden = false;
            similarWarn.innerHTML = `⚠ قد يكون هناك سجل مشابه: ${list
              .map((x) => `<strong>${ctx.esc(x.full_name)}</strong> (${ctx.esc(x.file_number || "")})`)
              .join(" · ")}`;
          } else similarWarn.hidden = true;
        } catch {
          similarWarn.hidden = true;
        }
      }, 450);
    };
    nameInput?.addEventListener("input", checkSimilar);
    dobInput?.addEventListener("change", checkSimilar);

    phoneInput?.addEventListener("input", () => {
      clearTimeout(phoneInput._t);
      phoneInput._t = setTimeout(async () => {
        const phone = phoneInput.value.trim();
        if (phone.length < 7) {
          warn.hidden = true;
          return;
        }
        try {
          const check = await ctx.api(`/clinics/api/patients/check-phone?phone=${encodeURIComponent(phone)}`);
          if (check.exists && check.patient) {
            const pat = check.patient;
            warn.hidden = false;
            warn.innerHTML = `⚠ يوجد مريض مسجل بهذا الرقم: <strong>${ctx.esc(pat.full_name)}</strong> ${ctx.esc(pat.file_number || "")}
              <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
                <button type="button" class="cx-btn cx-btn--sm" id="dupOpen">فتح الملف</button>
                <button type="button" class="cx-btn cx-btn--sm" id="dupAppt">إنشاء موعد</button>
              </div>`;
            document.getElementById("dupOpen")?.addEventListener("click", () => {
              document.getElementById("cxModalCancel")?.click();
              loadDrawerPatient(ctx, pat.id);
            });
            document.getElementById("dupAppt")?.addEventListener("click", () => {
              document.getElementById("cxModalCancel")?.click();
              ctx.promptNewAppointment(pat.id);
            });
          } else warn.hidden = true;
        } catch {
          warn.hidden = true;
        }
      }, 400);
    });
  }

  async function startVisit(ctx, id) {
    try {
      const visit = await ctx.api("/clinics/api/visits", {
        method: "POST",
        body: JSON.stringify({ patient_id: Number(id) }),
      });
      if (visit?.id) location.href = `/clinics/doctor/${visit.id}`;
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  async function archivePatient(ctx, id) {
    if (!window.confirm("أرشفة هذا المريض؟ يمكن استعادته لاحقاً من الفلاتر.")) return;
    try {
      await ctx.api(`/clinics/api/patients/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: "archived" }),
      });
      ctx.drawerPatient = null;
      await refresh(ctx);
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  function bindUi(ctx) {
    const root = ctx.root;
    const search = root.querySelector("#cxPatSearch");
    const drop = root.querySelector("#cxPatSearchDrop");
    if (search) {
      let t;
      search.oninput = () => {
        clearTimeout(t);
        t = setTimeout(async () => {
          ctx.state.q = search.value || "";
          ctx.state.page = 1;
          if (ctx.state.q.length >= 2) {
            try {
              const qs = new URLSearchParams({
                q: ctx.state.q,
                page: "1",
                per_page: "6",
                status_group: "all",
              });
              const reg = await ctx.api(`/clinics/api/patients/registry?${qs}`);
              const list = reg.patients || [];
              if (list.length) {
                drop.hidden = false;
                drop.innerHTML = list
                  .map((p) => {
                    const lv = fmtVisit(p.last_visit);
                    const ap = fmtAppt(p.next_appointment);
                    return `
                  <div class="cx-pat-hit-rich">
                    <div class="cx-pat-hit-rich__main">
                      <strong>${ctx.esc(p.full_name)}</strong>
                      <span>${ctx.esc(p.file_number || "")} · ${ctx.esc(p.phone || "")}</span>
                      <small>آخر زيارة: ${ctx.esc(lv.main)} · موعد: ${ctx.esc(ap)}</small>
                    </div>
                    <div class="cx-pat-hit-rich__acts">
                      <button type="button" class="cx-btn cx-btn--sm" data-hit-open="${p.id}">فتح الملف</button>
                      <button type="button" class="cx-btn cx-btn--sm cx-btn--ghost" data-hit-appt="${p.id}">موعد جديد</button>
                    </div>
                  </div>`;
                  })
                  .join("");
                drop.querySelectorAll("[data-hit-open]").forEach((btn) => {
                  btn.onclick = () => {
                    drop.hidden = true;
                    loadDrawerPatient(ctx, btn.dataset.hitOpen);
                  };
                });
                drop.querySelectorAll("[data-hit-appt]").forEach((btn) => {
                  btn.onclick = () => {
                    drop.hidden = true;
                    ctx.promptNewAppointment(Number(btn.dataset.hitAppt));
                  };
                });
              } else drop.hidden = true;
            } catch {
              drop.hidden = true;
            }
          } else drop.hidden = true;
          await refresh(ctx);
        }, 280);
      };
    }
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        search?.focus();
      }
    }, { once: true });

    root.querySelector("#cxPatAdd")?.addEventListener("click", () => promptAddPatient(ctx));
    root.querySelector("#cxPatEmptyAdd")?.addEventListener("click", () => promptAddPatient(ctx));
    root.querySelector("#cxPatDrawerClose")?.addEventListener("click", () => {
      ctx.drawerPatient = null;
      paint(ctx);
    });
    root.querySelector("#cxPatApptClose")?.addEventListener("click", () => {
      ctx.apptDrawer = null;
      paint(ctx);
    });
    root.querySelector("#cxPatBackdrop")?.addEventListener("click", () => {
      ctx.drawerPatient = null;
      ctx.apptDrawer = null;
      paint(ctx);
    });

    const applyFilters = async () => {
      ctx.state.status_group = root.querySelector("#cxPatStatus")?.value || "active";
      ctx.state.upcoming_only = root.querySelector("#cxPatUpcoming")?.value === "1";
      ctx.state.doctor_id = root.querySelector("#cxPatDoctor")?.value || "";
      ctx.state.last_visit = root.querySelector("#cxPatLastVisit")?.value || "";
      ctx.state.gender = root.querySelector("#cxPatGender")?.value || "";
      ctx.state.new_only = root.querySelector("#cxPatNew")?.checked || false;
      ctx.state.balance_only = root.querySelector("#cxPatBal")?.checked || false;
      ctx.state.followup_only = root.querySelector("#cxPatFu")?.checked || false;
      ctx.state.no_visit_days = root.querySelector("#cxPatNoVisit")?.value || "";
      ctx.state.sort = root.querySelector("#cxPatSort")?.value || "created_at";
      ctx.state.page = 1;
      await refresh(ctx);
    };

    ["cxPatStatus", "cxPatUpcoming", "cxPatDoctor", "cxPatLastVisit", "cxPatGender", "cxPatNoVisit", "cxPatSort"].forEach((id) => {
      const el = root.querySelector(`#${id}`);
      if (el) el.onchange = applyFilters;
    });
    ["cxPatNew", "cxPatBal", "cxPatFu"].forEach((id) => {
      const el = root.querySelector(`#${id}`);
      if (el) el.onchange = applyFilters;
    });

    root.querySelector("#cxPatMoreFilters")?.addEventListener("click", () => {
      ctx.state.extraOpen = !ctx.state.extraOpen;
      const ex = root.querySelector("#cxPatExtra");
      if (ex) ex.hidden = !ctx.state.extraOpen;
    });
    root.querySelector("#cxPatReset")?.addEventListener("click", async () => {
      ctx.state = {
        ...ctx.state,
        q: "",
        page: 1,
        per_page: 25,
        sort: "created_at",
        status_group: "active",
        doctor_id: "",
        gender: "",
        upcoming_only: false,
        balance_only: false,
        followup_only: false,
        new_only: false,
        last_visit: "",
        no_visit_days: "",
        extraOpen: false,
      };
      await refresh(ctx);
    });

    root.querySelector("#cxPatExport")?.addEventListener("click", () => {
      ctx.openModal(
        "تصدير المرضى",
        `
        <p style="margin:0 0 12px;color:var(--cx-muted);font-size:13px">يُصدَّر حسب الفلاتر الحالية.</p>
        <div class="cx-field-row" style="gap:8px">
          <button type="button" class="cx-btn" id="cxPatExportCsv"><i class="fa fa-file-csv"></i> CSV</button>
          <button type="button" class="cx-btn" id="cxPatExportXlsx"><i class="fa fa-file-excel"></i> Excel</button>
        </div>`,
        async () => {}
      );
      const saveBtn = document.getElementById("cxModalSave");
      if (saveBtn) saveBtn.style.display = "none";
      const qs = buildQs(ctx.state);
      document.getElementById("cxPatExportCsv")?.addEventListener("click", () => {
        window.open(`/clinics/api/patients/export?${qs}&format=csv`, "_blank");
        document.getElementById("cxModalCancel")?.click();
      });
      document.getElementById("cxPatExportXlsx")?.addEventListener("click", () => {
        window.open(`/clinics/api/patients/export?${qs}&format=xlsx`, "_blank");
        document.getElementById("cxModalCancel")?.click();
      });
    });

    root.querySelector("#cxPatPrev")?.addEventListener("click", async () => {
      if (ctx.state.page > 1) {
        ctx.state.page -= 1;
        await refresh(ctx);
      }
    });
    root.querySelector("#cxPatNext")?.addEventListener("click", async () => {
      const pg = ctx.data?.pagination || {};
      if (ctx.state.page < (pg.pages || 1)) {
        ctx.state.page += 1;
        await refresh(ctx);
      }
    });
    root.querySelector("#cxPatPerPage")?.addEventListener("change", async (e) => {
      ctx.state.per_page = Number(e.target.value);
      ctx.state.page = 1;
      await refresh(ctx);
    });

    root.querySelectorAll("[data-appt]").forEach((btn) => {
      btn.onclick = async () => {
        const apptId = btn.dataset.appt;
        const row = btn.closest("tr");
        const pid = row?.dataset?.pid;
        const p = pid ? findPatient(ctx, pid) : null;
        const hint = p?.next_appointment
          ? {
              id: apptId,
              patient_id: p.id,
              patient_name: p.full_name,
              appointment_date: p.next_appointment.appointment_date,
              start_time: p.next_appointment.start_time,
              doctor_name: p.next_appointment.doctor_name,
              status: p.next_appointment.status,
            }
          : null;
        await openApptDrawer(ctx, apptId, hint);
      };
    });
    root.querySelectorAll("[data-open]").forEach((btn) => {
      btn.onclick = () => loadDrawerPatient(ctx, btn.dataset.open);
    });
    root.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = root.querySelector(`[data-for="${btn.dataset.menu}"]`);
        root.querySelectorAll(".cx-pat-menu").forEach((m) => {
          if (m !== menu) m.hidden = true;
        });
        if (menu) menu.hidden = !menu.hidden;
      };
    });
    root.querySelectorAll("[data-act]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        if (act === "appt") ctx.promptNewAppointment(Number(id));
        else if (act === "visit") await startVisit(ctx, id);
        else if (act === "edit") {
          const detail = await ctx.api(`/clinics/api/patients/${id}`);
          const p = detail.patient || detail;
          ctx.openModal("تعديل مريض", ctx.patientFormFields(p), async () => {
            await ctx.api(`/clinics/api/patients/${id}`, {
              method: "PUT",
              body: JSON.stringify(ctx.readPatientForm()),
            });
            await refresh(ctx);
          });
        } else if (act === "print") {
          const p = findPatient(ctx, id) || (await ctx.api(`/clinics/api/patients/${id}`)).patient;
          printPatientCard(p, ctx);
        } else if (act === "merge") {
          ctx.showNotice("دمج السجلات يتطلب صلاحية إدارية — راجع الدعم أو الإعدادات.");
        } else if (act === "archive") await archivePatient(ctx, id);
      };
    });
    root.querySelectorAll("[data-drawer-act]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.drawerAct;
        if (act === "appt") ctx.promptNewAppointment(Number(id));
        else if (act === "visit") await startVisit(ctx, id);
        else if (act === "pay") location.href = `/clinics/billing?patient_id=${id}`;
        else if (act === "print") {
          const p = ctx.drawerPatient || findPatient(ctx, id);
          if (p) printPatientCard(p, ctx);
        } else if (act === "more") {
          const menu = root.querySelector(`[data-for="${id}"]`);
          if (menu) menu.hidden = false;
        }
      };
    });
  }

  function paint(ctx) {
    ctx.root.innerHTML = buildHtml(ctx);
    bindUi(ctx);
  }

  async function refresh(ctx) {
    const data = await ctx.api(`/clinics/api/patients/registry?${buildQs(ctx.state)}`);
    ctx.data = data;
    paint(ctx);
  }

  async function render(state, root, helpers) {
    const ctx = {
      state: {
        q: state.patientQ || "",
        page: 1,
        per_page: 25,
        sort: "created_at",
        status_group: "active",
        doctor_id: "",
        gender: "",
        upcoming_only: false,
        balance_only: false,
        followup_only: false,
        new_only: false,
        last_visit: "",
        no_visit_days: "",
        extraOpen: false,
      },
      data: null,
      drawerPatient: null,
      apptDrawer: null,
      root,
      bootstrap: helpers.bootstrap,
      api: helpers.api,
      esc: helpers.esc,
      money: helpers.money,
      showNotice: helpers.showNotice,
      openModal: helpers.openModal,
      promptNewAppointment: helpers.promptNewAppointment,
      patientFormFields: helpers.patientFormFields,
      readPatientForm: helpers.readPatientForm,
    };
    root.innerHTML = skeleton();
    try {
      await refresh(ctx);
    } catch (err) {
      ctx.root.innerHTML = `
        <div class="cx-pat"><div class="cx-empty">تعذر تحميل المرضى.
        <button type="button" class="cx-btn cx-btn--primary" id="cxPatRetry">إعادة المحاولة</button></div></div>`;
      ctx.root.querySelector("#cxPatRetry")?.addEventListener("click", () => render(state, root, helpers));
      ctx.showNotice(err.message || String(err));
    }
  }

  window.ClinicsPatients = { render };
})();
