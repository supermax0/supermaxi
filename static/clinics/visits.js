/**
 * Finora Clinics — Clinical Visits Center
 */
(() => {
  const STATUS = {
    waiting_doctor: { label: "بانتظار الطبيب", cls: "orange" },
    in_consultation: { label: "قيد المعاينة", cls: "blue" },
    completed: { label: "مكتملة", cls: "green" },
    incomplete: { label: "غير مكتملة", cls: "red" },
    cancelled: { label: "ملغاة", cls: "gray" },
    deferred: { label: "مؤجلة", cls: "purple" },
  };

  const RECORD = {
    diag_rx: "تشخيص + وصفة",
    diag: "تشخيص",
    rx: "وصفة",
    writing: "قيد الكتابة",
    missing_diag: "ناقص تشخيص",
    none: "لا يوجد",
  };

  function statusBadge(st) {
    const s = STATUS[st] || STATUS.in_consultation;
    return `<span class="cx-vis-badge cx-vis-badge--${s.cls}">${s.label}</span>`;
  }

  function avatarHtml(name, cls = "cx-vis-avatar") {
    const ch = (name || "م").trim().charAt(0) || "م";
    return `<span class="${cls}" aria-hidden="true">${ch}</span>`;
  }

  function fmtTime(v) {
    if (!v.started_at) return "—";
    const t = v.started_at.replace("T", " ").slice(11, 16);
    const d = v.visit_date || "";
    const today = new Date().toISOString().slice(0, 10);
    if (d === today) return t;
    try {
      const dl = new Date(d + "T12:00:00").toLocaleDateString("ar-IQ", { day: "numeric", month: "short" });
      return `${dl} ${t}`;
    } catch {
      return `${d} ${t}`;
    }
  }

  function fmtDuration(v) {
    const m = v.duration_minutes;
    if (m == null) return "—";
    return `${m} دقيقة`;
  }

  function primaryAction(v, ctx) {
    const st = v.display_status;
    if (st === "waiting_doctor") return { label: "بدء الزيارة", act: "start" };
    if (st === "incomplete") return { label: "إكمال الزيارة", act: "complete" };
    return { label: "فتح الزيارة", act: "open" };
  }

  function buildQs(state) {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.date) p.set("date", state.date);
    p.set("page", String(state.page || 1));
    p.set("per_page", String(state.per_page || 25));
    if (state.sort) p.set("sort", state.sort);
    if (state.status) p.set("status", state.status);
    if (state.doctor_id) p.set("doctor_id", state.doctor_id);
    if (state.service_id) p.set("service_id", state.service_id);
    if (state.incomplete_only) p.set("incomplete_only", "1");
    if (state.has_rx) p.set("has_rx", "1");
    if (state.has_lab) p.set("has_lab", "1");
    if (state.has_radiology) p.set("has_radiology", "1");
    if (state.unpaid_only) p.set("unpaid_only", "1");
    if (state.followup_only) p.set("followup_only", "1");
    return p.toString();
  }

  function kpisHtml(data) {
    const s = data.stats || {};
    const cards = [
      { label: "زيارات اليوم", val: s.today_total || 0, theme: "teal", icon: "fa-calendar-day" },
      { label: "قيد المعاينة", val: s.in_consultation || 0, theme: "blue", icon: "fa-user-doctor" },
      { label: "مكتملة", val: s.completed || 0, theme: "green", icon: "fa-circle-check" },
      { label: "بانتظار الطبيب", val: s.waiting_doctor || 0, theme: "orange", icon: "fa-hourglass-half" },
      { label: "غير مكتملة", val: s.incomplete || 0, theme: "red", icon: "fa-triangle-exclamation" },
      {
        label: "متوسط مدة الزيارة",
        val: s.avg_duration_minutes ? `${s.avg_duration_minutes} د` : "—",
        theme: "purple",
        icon: "fa-clock",
      },
    ];
    return cards
      .map(
        (c) => `
      <article class="cx-vis-kpi cx-vis-kpi--${c.theme}">
        <i class="fa ${c.icon}"></i>
        <div><span>${c.label}</span><strong>${c.val}</strong></div>
      </article>`
      )
      .join("");
  }

  function alertHtml(ctx) {
    const n = ctx.data?.stats?.incomplete_yesterday || 0;
    if (!n) return "";
    return `
      <div class="cx-vis-alert" id="cxVisIncompleteAlert">
        <i class="fa fa-triangle-exclamation"></i>
        <span>${n} زيارات غير مكتملة من أمس</span>
        <button type="button" class="cx-btn cx-btn--sm" id="cxVisIncompleteBtn">عرض التفاصيل</button>
      </div>`;
  }

  function doctorBanner(ctx) {
    const cur = ctx.data?.current_visit;
    if (!cur) return "";
    const started = cur.started_at ? cur.started_at.replace("T", " ").slice(11, 16) : "—";
    return `
      <article class="cx-vis-current">
        <div>
          <span class="cx-vis-current__label">المريض الحالي</span>
          <strong>${ctx.esc(cur.patient_name)}</strong>
          <small>بدأت ${started} · ${fmtDuration(cur)} · ${ctx.esc(cur.chief_complaint || "—")}</small>
        </div>
        <a class="cx-btn cx-btn--primary" href="/clinics/doctor/${cur.id}">فتح الزيارة</a>
      </article>`;
  }

  function filtersHtml(ctx) {
    const doctors = ctx.data?.doctors || [];
    const services = ctx.data?.services || [];
    return `
      <div class="cx-vis-filters">
        <input type="date" class="cx-select" id="cxVisDate" value="${ctx.esc(ctx.state.date || ctx.data?.date || "")}">
        <select class="cx-select" id="cxVisDoctor">
          <option value="">كل الأطباء</option>
          ${doctors.map((d) => `<option value="${d.id}" ${String(d.id) === String(ctx.state.doctor_id || "") ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`).join("")}
        </select>
        <select class="cx-select" id="cxVisStatus">
          <option value="">كل الحالات</option>
          <option value="in_consultation" ${ctx.state.status === "in_consultation" ? "selected" : ""}>قيد المعاينة</option>
          <option value="completed" ${ctx.state.status === "completed" ? "selected" : ""}>مكتملة</option>
          <option value="waiting_doctor" ${ctx.state.status === "waiting_doctor" ? "selected" : ""}>بانتظار الطبيب</option>
          <option value="incomplete" ${ctx.state.status === "incomplete" ? "selected" : ""}>غير مكتملة</option>
        </select>
        <select class="cx-select" id="cxVisService">
          <option value="">نوع الزيارة</option>
          ${services.map((s) => `<option value="${s.id}" ${String(s.id) === String(ctx.state.service_id || "") ? "selected" : ""}>${ctx.esc(s.name)}</option>`).join("")}
        </select>
        <button type="button" class="cx-btn cx-btn--ghost" id="cxVisMoreFilters"><i class="fa fa-sliders"></i> فلاتر إضافية</button>
        <button type="button" class="cx-btn cx-btn--ghost" id="cxVisReset">إعادة ضبط</button>
      </div>
      <div class="cx-vis-extra-filters" id="cxVisExtra" ${ctx.state.extraOpen ? "" : "hidden"}>
        <label class="cx-vis-check"><input type="checkbox" id="cxVisRx" ${ctx.state.has_rx ? "checked" : ""}> فيها وصفة</label>
        <label class="cx-vis-check"><input type="checkbox" id="cxVisLab" ${ctx.state.has_lab ? "checked" : ""}> فيها تحاليل</label>
        <label class="cx-vis-check"><input type="checkbox" id="cxVisRad" ${ctx.state.has_radiology ? "checked" : ""}> فيها أشعة</label>
        <label class="cx-vis-check"><input type="checkbox" id="cxVisUnpaid" ${ctx.state.unpaid_only ? "checked" : ""}> فاتورة غير مسددة</label>
        <label class="cx-vis-check"><input type="checkbox" id="cxVisFu" ${ctx.state.followup_only ? "checked" : ""}> متابعة</label>
        <select class="cx-select" id="cxVisSort">
          <option value="time" ${ctx.state.sort === "time" ? "selected" : ""}>الوقت</option>
          <option value="patient" ${ctx.state.sort === "patient" ? "selected" : ""}>المريض</option>
          <option value="doctor" ${ctx.state.sort === "doctor" ? "selected" : ""}>الطبيب</option>
          <option value="status" ${ctx.state.sort === "status" ? "selected" : ""}>الحالة</option>
          <option value="duration" ${ctx.state.sort === "duration" ? "selected" : ""}>المدة</option>
        </select>
      </div>`;
  }

  function tableRows(ctx) {
    const rows = ctx.data?.visits || [];
    if (!rows.length) {
      return `<tr><td colspan="8"><div class="cx-empty">لا توجد زيارات لهذا اليوم.<button type="button" class="cx-btn cx-btn--primary" id="cxVisEmptyAdd">+ زيارة مباشرة</button></div></td></tr>`;
    }
    return rows
      .map((v) => {
        const act = primaryAction(v, ctx);
        const live = v.is_live_duration ? " data-live-duration" : "";
        return `
        <tr data-vid="${v.id}"${live}>
          <td><strong>${ctx.esc(fmtTime(v))}</strong></td>
          <td>
            <button type="button" class="cx-vis-name" data-open="${v.id}">
              ${avatarHtml(v.patient_name)}
              <span><strong>${ctx.esc(v.patient_name)}</strong><small>${ctx.esc(v.patient_file || "")}</small></span>
            </button>
          </td>
          <td>
            <div class="cx-vis-doc">
              ${avatarHtml(v.doctor_name, "cx-vis-avatar cx-vis-avatar--sm")}
              <span><strong>${ctx.esc(v.doctor_name || "—")}</strong><small>${ctx.esc(v.doctor_specialty || "")}</small></span>
            </div>
          </td>
          <td>${ctx.esc(v.visit_type || v.service_name || "—")}</td>
          <td>${statusBadge(v.display_status)}</td>
          <td class="cx-vis-duration" data-started="${ctx.esc(v.started_at || "")}">${ctx.esc(fmtDuration(v))}</td>
          <td><span class="cx-vis-record">${ctx.esc(RECORD[v.record_summary] || RECORD.none)}</span></td>
          <td class="cx-vis-actions">
            <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-act="${act.act}" data-id="${v.id}" data-finora-action="visit.open">${act.label}</button>
            <button type="button" class="cx-btn cx-btn--sm cx-btn--ghost" data-menu="${v.id}"><i class="fa fa-ellipsis-vertical"></i></button>
            <div class="cx-vis-menu" hidden data-for="${v.id}">
              <a href="/clinics/patients/${v.patient_id}">فتح المريض</a>
              <a href="/clinics/doctor/${v.id}">السجل السريري</a>
              <a href="/clinics/doctor/${v.id}#rx">الوصفة</a>
              <a href="/clinics/labs?patient_id=${v.patient_id}">التحاليل</a>
              <a href="/clinics/radiology?patient_id=${v.patient_id}">الأشعة</a>
              <a href="/clinics/attachments?patient_id=${v.patient_id}">المرفقات</a>
              <button type="button" data-act="followup" data-id="${v.patient_id}">موعد مراجعة</button>
              <button type="button" data-act="print" data-id="${v.id}">طباعة ملخص</button>
            </div>
          </td>
        </tr>`;
      })
      .join("");
  }

  function paginationHtml(ctx) {
    const pg = ctx.data?.pagination || {};
    return `
      <div class="cx-vis-pager">
        <span>عرض ${pg.from || 0}-${pg.to || 0} من ${pg.total || 0} زيارة</span>
        <div class="cx-vis-pager__nav">
          <button type="button" class="cx-btn cx-btn--sm" id="cxVisPrev" ${pg.page <= 1 ? "disabled" : ""}>السابق</button>
          <span>${pg.page || 1} / ${pg.pages || 1}</span>
          <button type="button" class="cx-btn cx-btn--sm" id="cxVisNext" ${pg.page >= pg.pages ? "disabled" : ""}>التالي</button>
        </div>
        <select class="cx-select" id="cxVisPerPage">
          ${[25, 50, 100].map((n) => `<option value="${n}" ${Number(ctx.state.per_page) === n ? "selected" : ""}>${n} / صفحة</option>`).join("")}
        </select>
      </div>`;
  }

  function progressHtml(detail) {
    const v = detail?.visit || {};
    const dx = (detail?.diagnoses || []).length > 0;
    const rx = (detail?.prescription?.items || []).length > 0 || detail?.prescription?.id;
    const steps = [
      { key: "cc", label: "الشكوى الرئيسية", done: !!(v.chief_complaint || "").trim() },
      { key: "exam", label: "الفحص السريري", done: !!(v.clinical_notes || "").trim() || (detail?.vitals || []).length > 0 },
      { key: "dx", label: "التشخيص", done: dx, active: !dx && v.status === "open" },
      { key: "rx", label: "الوصفة", done: rx },
      { key: "plan", label: "الخطة والمتابعة", done: !!v.follow_up_date },
    ];
    return steps
      .map((s, i) => {
        const cls = s.done ? "done" : s.active ? "active" : "";
        const icon = s.done ? "fa-circle-check" : s.active ? "fa-circle-dot" : "fa-circle";
        return `<div class="cx-vis-step cx-vis-step--${cls}"><i class="fa ${icon}"></i><span>${s.label}</span></div>`;
      })
      .join("");
  }

  function drawerHtml(v, detail, ctx) {
    if (!v) return "";
    const c = v.counts || {};
    return `
      <aside class="cx-vis-drawer" id="cxVisDrawer">
        <header class="cx-vis-drawer__head">
          <div>
            <h2>تفاصيل الزيارة</h2>
            <p>${statusBadge(v.display_status)}</p>
          </div>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxVisDrawerClose"><i class="fa fa-xmark"></i></button>
        </header>
        <div class="cx-vis-drawer__body">
          <div class="cx-vis-drawer__hero">
            ${avatarHtml(v.patient_name)}
            <div>
              <h3>${ctx.esc(v.patient_name)}</h3>
              <p>${ctx.esc(v.patient_file || "")} · ${v.patient_age != null ? v.patient_age + " سنة" : "—"} · ${ctx.esc(v.patient_gender || "—")}</p>
              <p>${ctx.esc(v.patient_phone || "—")}</p>
            </div>
          </div>
          <div class="cx-vis-drawer__field"><span>الطبيب</span><b>${ctx.esc(v.doctor_name || "—")}</b></div>
          <div class="cx-vis-drawer__field"><span>التاريخ والوقت</span><b>${ctx.esc(v.visit_date || "")} ${ctx.esc((v.started_at || "").replace("T", " ").slice(11, 16))}</b></div>
          <div class="cx-vis-drawer__field"><span>نوع الزيارة</span><b>${ctx.esc(v.visit_type || "—")}</b></div>
          <div class="cx-vis-drawer__field"><span>مدة الزيارة</span><b data-drawer-duration>${ctx.esc(fmtDuration(v))}</b></div>
          <div class="cx-vis-progress">${progressHtml(detail)}</div>
          <div class="cx-vis-mini-grid">
            <div><i class="fa fa-paperclip"></i><span>المرفقات</span><strong>${c.attachments || 0}</strong></div>
            <div><i class="fa fa-flask"></i><span>التحاليل</span><strong>${c.labs || 0}</strong></div>
            <div><i class="fa fa-x-ray"></i><span>الأشعة</span><strong>${c.radiology || 0}</strong></div>
            <div><i class="fa fa-prescription"></i><span>الوصفات</span><strong>${c.prescriptions || 0}</strong></div>
          </div>
        </div>
        <footer class="cx-vis-drawer__foot">
          <a class="cx-btn cx-btn--primary" href="/clinics/doctor/${v.id}">فتح السجل السريري</a>
          <a class="cx-btn" href="/clinics/doctor/${v.id}#rx">الوصفة</a>
          <a class="cx-btn" href="/clinics/labs?patient_id=${v.patient_id}">التحاليل</a>
          <a class="cx-btn" href="/clinics/radiology?patient_id=${v.patient_id}">الأشعة</a>
          <a class="cx-btn" href="/clinics/attachments?patient_id=${v.patient_id}">المرفقات</a>
          ${v.display_status === "in_consultation" ? `<button type="button" class="cx-btn" data-drawer-act="complete" data-id="${v.id}">إنهاء الزيارة</button>` : ""}
        </footer>
      </aside>`;
  }

  function buildHtml(ctx) {
    const v = ctx.drawerVisit;
    return `
      <div class="cx-vis ${v ? "has-drawer" : ""}">
        <header class="cx-vis-header">
          <div class="cx-vis-header__title">
            <h1>الزيارات</h1>
            <p>إدارة ومتابعة الزيارات السريرية</p>
          </div>
          <div class="cx-vis-header__search">
            <i class="fa fa-search"></i>
            <input type="search" class="cx-input" id="cxVisSearch" placeholder="ابحث عن مريض، رقم ملف أو رقم زيارة…" value="${ctx.esc(ctx.state.q || "")}">
            <div class="cx-vis-search-hint">Ctrl+K</div>
          </div>
          <button type="button" class="cx-btn cx-btn--primary" id="cxVisAdd"><i class="fa fa-plus"></i> زيارة مباشرة</button>
        </header>
        ${doctorBanner(ctx)}
        <div class="cx-vis-kpis">${kpisHtml(ctx.data)}</div>
        ${alertHtml(ctx)}
        ${filtersHtml(ctx)}
        <article class="cx-vis-table-card">
          <div class="cx-table-wrap">
            <table class="cx-table cx-vis-table">
              <thead>
                <tr>
                  <th>الوقت</th><th>المريض</th><th>الطبيب</th><th>نوع الزيارة</th>
                  <th>الحالة</th><th>المدة</th><th>السجل السريري</th><th>الإجراء</th>
                </tr>
              </thead>
              <tbody>${tableRows(ctx)}</tbody>
            </table>
          </div>
          ${paginationHtml(ctx)}
        </article>
        ${v ? drawerHtml(v, ctx.drawerDetail, ctx) : ""}
        <div class="cx-vis-drawer-backdrop" id="cxVisBackdrop" ${v ? "" : "hidden"}></div>
      </div>`;
  }

  function skeleton() {
    return `
      <div class="cx-vis">
        <div class="cx-skeleton-block" style="height:72px;border-radius:14px"></div>
        <div class="cx-vis-kpis">${Array(6).fill('<div class="cx-skeleton-block" style="height:88px;border-radius:14px"></div>').join("")}</div>
        <div class="cx-skeleton-block" style="height:420px;border-radius:16px"></div>
      </div>`;
  }

  function findVisit(ctx, id) {
    return (ctx.data?.visits || []).find((x) => String(x.id) === String(id));
  }

  async function loadDrawer(ctx, id) {
    try {
      const detail = await ctx.api(`/clinics/api/visits/${id}`);
      const row = findVisit(ctx, id) || {};
      ctx.drawerVisit = { ...row, ...(detail.visit || {}) };
      ctx.drawerDetail = detail;
      paint(ctx);
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  async function openVisit(id) {
    location.href = `/clinics/doctor/${id}`;
  }

  async function startVisit(ctx, id) {
    try {
      const row = findVisit(ctx, id);
      if (row?.appointment_id) {
        await ctx.api("/clinics/api/visits", {
          method: "POST",
          body: JSON.stringify({ appointment_id: row.appointment_id }),
        });
      }
      location.href = `/clinics/doctor/${id}`;
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  function promptComplete(ctx, id) {
    ctx.openModal(
      "إنهاء الزيارة",
      `
      <p style="margin:0 0 12px;color:var(--cx-muted)">هل يحتاج المريض مراجعة؟</p>
      <div class="cx-field-row">
        <label class="cx-vis-check"><input type="radio" name="fu" value="0" checked> لا</label>
        <label class="cx-vis-check"><input type="radio" name="fu" value="1"> نعم</label>
      </div>
      <div class="cx-field" id="cxVisFuDaysWrap" hidden>
        <label>بعد</label>
        <select class="cx-select" id="cxVisFuDays">
          <option value="7">7 أيام</option>
          <option value="14">14 يوم</option>
          <option value="30">30 يوم</option>
        </select>
      </div>`,
      async () => {
        const need = document.querySelector('input[name="fu"]:checked')?.value === "1";
        if (need) {
          const days = Number(document.getElementById("cxVisFuDays").value || 7);
          const d = new Date();
          d.setDate(d.getDate() + days);
          await ctx.api(`/clinics/api/visits/${id}`, {
            method: "PUT",
            body: JSON.stringify({ follow_up_date: d.toISOString().slice(0, 10) }),
          });
        }
        await ctx.api(`/clinics/api/visits/${id}/complete`, { method: "POST", body: JSON.stringify({}) });
        ctx.showNotice("تم إنهاء الزيارة", false);
        ctx.drawerVisit = null;
        await refresh(ctx);
      }
    );
    document.querySelectorAll('input[name="fu"]').forEach((el) => {
      el.onchange = () => {
        const wrap = document.getElementById("cxVisFuDaysWrap");
        if (wrap) wrap.hidden = el.value !== "1";
      };
    });
  }

  function promptWalkin(ctx) {
    const doctors = ctx.bootstrap?.doctors || ctx.data?.doctors || [];
    const services = ctx.bootstrap?.services || ctx.data?.services || [];
    const patientInline = window.ClinicsPatientInline;
    ctx.openModal(
      "زيارة مباشرة",
      `
      <div class="cx-field"><label>المريض *</label>
        <input class="cx-input" id="wv_patient_q" placeholder="ابحث بالاسم أو الهاتف">
        <select class="cx-select" id="wv_patient_id" style="margin-top:8px"></select>
      </div>
      ${patientInline ? patientInline.html("walkin") : ""}
      <div class="cx-field"><label>الطبيب *</label>
        <select class="cx-select" id="wv_doctor_id" required>
          <option value="">—</option>
          ${doctors.map((d) => `<option value="${d.id}">${ctx.esc(d.full_name)}</option>`).join("")}
        </select>
      </div>
      <div class="cx-field"><label>الاختصاص</label><select class="cx-select" id="wv_specialty_id"><option value="">اختر الطبيب أولاً</option></select></div>
      <div class="cx-field"><label>نوع الزيارة *</label>
        <select class="cx-select" id="wv_service_id" required>
          <option value="">—</option>
          ${services.map((s) => `<option value="${s.id}">${ctx.esc(s.name)}</option>`).join("")}
        </select>
      </div>
      <div class="cx-field"><label>سبب الزيارة</label><textarea class="cx-textarea" id="wv_cc"></textarea></div>`,
      async () => {
        const patientId = (patientInline ? await patientInline.resolve("walkin") : null) || document.getElementById("wv_patient_id").value;
        const doctorId = document.getElementById("wv_doctor_id").value;
        const serviceId = document.getElementById("wv_service_id").value;
        if (!patientId || !doctorId || !serviceId) throw new Error("المريض والطبيب ونوع الزيارة مطلوبة");
        const visit = await ctx.api("/clinics/api/visits", {
          method: "POST",
          body: JSON.stringify({
            patient_id: Number(patientId),
            doctor_id: Number(doctorId),
            specialty_id: document.getElementById('wv_specialty_id').value || null,
            service_id: Number(serviceId),
            chief_complaint: document.getElementById("wv_cc").value,
          }),
        });
        location.href = `/clinics/doctor/${visit.id || visit.visit?.id}`;
      },
      {
        extraActions: [
          {
            label: "إضافة إلى الانتظار",
            onClick: async () => {
              const patientId = (patientInline ? await patientInline.resolve("walkin") : null) || document.getElementById("wv_patient_id").value;
              const doctorId = document.getElementById("wv_doctor_id").value;
              const serviceId = document.getElementById("wv_service_id").value;
              if (!patientId || !doctorId || !serviceId) throw new Error("المريض والطبيب ونوع الزيارة مطلوبة");
              await ctx.api("/clinics/api/appointments", {
                method: "POST",
                body: JSON.stringify({
                  patient_id: Number(patientId),
                  doctor_id: Number(doctorId),
                  specialty_id: document.getElementById('wv_specialty_id').value || null,
                  service_id: Number(serviceId),
                  appointment_date: ctx.state.date || ctx.data?.date,
                  start_time: "09:00",
                  status: "waiting",
                  notes: document.getElementById("wv_cc").value,
                }),
              });
            },
            notice: "تمت الإضافة إلى الانتظار",
          },
        ],
      }
    );
    if (patientInline) patientInline.bind("walkin", "wv_patient_q", "wv_patient_id");
    const doctorSelect=document.getElementById('wv_doctor_id'),specialtySelect=document.getElementById('wv_specialty_id');
    const filterServices=()=>{
      const select=document.getElementById('wv_service_id');
      const sid=Number(specialtySelect.value||0);
      const did=Number(doctorSelect.value||0);
      const matched=services.filter((s)=>{
        const specIds=(s.specialty_ids||[]).map(Number);
        const docIds=(s.doctor_ids||[]).map(Number);
        if(sid && !specIds.includes(sid)) return false;
        if(did && docIds.length && !docIds.includes(did)) return false;
        return true;
      });
      select.innerHTML='<option value="">—</option>'+matched.map(s=>`<option value="${s.id}">${ctx.esc(s.name)}</option>`).join('');
    };
    doctorSelect.onchange=()=>{const doctor=doctors.find(d=>String(d.id)===doctorSelect.value);specialtySelect.innerHTML=(doctor?.specialties||[]).map(s=>`<option value="${s.id}" ${s.is_primary?'selected':''}>${ctx.esc(s.name_ar)}</option>`).join('')||'<option value="">عام</option>';filterServices()};
    specialtySelect.onchange=filterServices;
    const qInput = document.getElementById("wv_patient_q");
    const sel = document.getElementById("wv_patient_id");
    let t;
    qInput?.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const q = qInput.value.trim();
        if (q.length < 2) return;
        const hits = await ctx.api(`/clinics/api/patients?q=${encodeURIComponent(q)}`);
        const list = Array.isArray(hits) ? hits : [];
        sel.innerHTML = list.map((p) => `<option value="${p.id}">${ctx.esc(p.full_name)} · ${ctx.esc(p.file_number || "")}</option>`).join("");
      }, 300);
    });
  }

  function tickLiveDurations(ctx) {
    const now = Date.now();
    ctx.root.querySelectorAll("[data-live-duration] .cx-vis-duration").forEach((el) => {
      const started = el.dataset.started;
      if (!started) return;
      const ms = now - new Date(started).getTime();
      const m = Math.max(0, Math.floor(ms / 60000));
      el.textContent = `${m} دقيقة`;
    });
    const drawerDur = ctx.root.querySelector("[data-drawer-duration]");
    if (drawerDur && ctx.drawerVisit?.is_live_duration && ctx.drawerVisit.started_at) {
      const m = Math.max(0, Math.floor((now - new Date(ctx.drawerVisit.started_at).getTime()) / 60000));
      drawerDur.textContent = `${m} دقيقة`;
    }
  }

  function bindUi(ctx) {
    const root = ctx.root;
    if (ctx._liveTimer) clearInterval(ctx._liveTimer);
    if ((ctx.data?.visits || []).some((v) => v.is_live_duration)) {
      ctx._liveTimer = setInterval(() => tickLiveDurations(ctx), 30000);
      tickLiveDurations(ctx);
    }

    const search = root.querySelector("#cxVisSearch");
    if (search) {
      let t;
      search.oninput = () => {
        clearTimeout(t);
        t = setTimeout(async () => {
          ctx.state.q = search.value || "";
          ctx.state.page = 1;
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

    root.querySelector("#cxVisAdd")?.addEventListener("click", () => promptWalkin(ctx));
    root.querySelector("#cxVisEmptyAdd")?.addEventListener("click", () => promptWalkin(ctx));
    root.querySelector("#cxVisDrawerClose")?.addEventListener("click", () => {
      ctx.drawerVisit = null;
      paint(ctx);
    });
    root.querySelector("#cxVisBackdrop")?.addEventListener("click", () => {
      ctx.drawerVisit = null;
      paint(ctx);
    });
    root.querySelector("#cxVisIncompleteBtn")?.addEventListener("click", async () => {
      const y = new Date(ctx.state.date || ctx.data?.date || new Date());
      y.setDate(y.getDate() - 1);
      ctx.state.date = y.toISOString().slice(0, 10);
      ctx.state.status = "incomplete";
      ctx.state.page = 1;
      await refresh(ctx);
    });

    const applyFilters = async () => {
      ctx.state.date = root.querySelector("#cxVisDate")?.value || ctx.state.date;
      ctx.state.doctor_id = root.querySelector("#cxVisDoctor")?.value || "";
      ctx.state.status = root.querySelector("#cxVisStatus")?.value || "";
      ctx.state.service_id = root.querySelector("#cxVisService")?.value || "";
      ctx.state.has_rx = root.querySelector("#cxVisRx")?.checked || false;
      ctx.state.has_lab = root.querySelector("#cxVisLab")?.checked || false;
      ctx.state.has_radiology = root.querySelector("#cxVisRad")?.checked || false;
      ctx.state.unpaid_only = root.querySelector("#cxVisUnpaid")?.checked || false;
      ctx.state.followup_only = root.querySelector("#cxVisFu")?.checked || false;
      ctx.state.sort = root.querySelector("#cxVisSort")?.value || "time";
      ctx.state.page = 1;
      await refresh(ctx);
    };
    ["cxVisDate", "cxVisDoctor", "cxVisStatus", "cxVisService", "cxVisSort"].forEach((id) => {
      const el = root.querySelector(`#${id}`);
      if (el) el.onchange = applyFilters;
    });
    ["cxVisRx", "cxVisLab", "cxVisRad", "cxVisUnpaid", "cxVisFu"].forEach((id) => {
      const el = root.querySelector(`#${id}`);
      if (el) el.onchange = applyFilters;
    });
    root.querySelector("#cxVisMoreFilters")?.addEventListener("click", () => {
      ctx.state.extraOpen = !ctx.state.extraOpen;
      const ex = root.querySelector("#cxVisExtra");
      if (ex) ex.hidden = !ctx.state.extraOpen;
    });
    root.querySelector("#cxVisReset")?.addEventListener("click", async () => {
      ctx.state = {
        ...ctx.state,
        q: "",
        page: 1,
        per_page: 25,
        sort: "time",
        status: "",
        doctor_id: "",
        service_id: "",
        incomplete_only: false,
        has_rx: false,
        has_lab: false,
        has_radiology: false,
        unpaid_only: false,
        followup_only: false,
        extraOpen: false,
      };
      await refresh(ctx);
    });
    root.querySelector("#cxVisPrev")?.addEventListener("click", async () => {
      if (ctx.state.page > 1) {
        ctx.state.page -= 1;
        await refresh(ctx);
      }
    });
    root.querySelector("#cxVisNext")?.addEventListener("click", async () => {
      const pg = ctx.data?.pagination || {};
      if (ctx.state.page < (pg.pages || 1)) {
        ctx.state.page += 1;
        await refresh(ctx);
      }
    });
    root.querySelector("#cxVisPerPage")?.addEventListener("change", async (e) => {
      ctx.state.per_page = Number(e.target.value);
      ctx.state.page = 1;
      await refresh(ctx);
    });

    root.querySelectorAll("[data-open]").forEach((btn) => {
      btn.onclick = () => loadDrawer(ctx, btn.dataset.open);
    });
    root.querySelectorAll("tr[data-vid]").forEach((tr) => {
      tr.addEventListener("click", (e) => {
        if (e.target.closest("button,a,.cx-vis-menu")) return;
        loadDrawer(ctx, tr.dataset.vid);
      });
    });
    root.querySelectorAll("[data-act]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.act;
        if (act === "open") openVisit(id);
        else if (act === "start") await startVisit(ctx, id);
        else if (act === "complete") promptComplete(ctx, id);
        else if (act === "followup") ctx.promptNewAppointment(Number(id));
        else if (act === "print") openVisit(id);
      };
    });
    root.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = root.querySelector(`[data-for="${btn.dataset.menu}"]`);
        root.querySelectorAll(".cx-vis-menu").forEach((m) => {
          if (m !== menu) m.hidden = true;
        });
        if (menu) menu.hidden = !menu.hidden;
      };
    });
    root.querySelectorAll("[data-drawer-act]").forEach((btn) => {
      btn.onclick = () => {
        if (btn.dataset.drawerAct === "complete") promptComplete(ctx, btn.dataset.id);
      };
    });
  }

  function paint(ctx) {
    ctx.root.innerHTML = buildHtml(ctx);
    bindUi(ctx);
  }

  async function refresh(ctx) {
    const data = await ctx.api(`/clinics/api/visits/registry?${buildQs(ctx.state)}`);
    ctx.data = data;
    if (ctx.drawerVisit) {
      const fresh = (data.visits || []).find((x) => String(x.id) === String(ctx.drawerVisit.id));
      if (fresh) ctx.drawerVisit = { ...ctx.drawerVisit, ...fresh };
    }
    paint(ctx);
  }

  async function render(state, root, helpers) {
    const ctx = {
      state: {
        q: "",
        date: state.day || new Date().toISOString().slice(0, 10),
        page: 1,
        per_page: 25,
        sort: "time",
        status: "",
        doctor_id: "",
        service_id: "",
        incomplete_only: false,
        has_rx: false,
        has_lab: false,
        has_radiology: false,
        unpaid_only: false,
        followup_only: false,
        extraOpen: false,
      },
      data: null,
      drawerVisit: null,
      drawerDetail: null,
      root,
      api: helpers.api,
      esc: helpers.esc,
      showNotice: helpers.showNotice,
      openModal: helpers.openModal,
      promptNewAppointment: helpers.promptNewAppointment,
    };
    root.innerHTML = skeleton();
    try {
      await refresh(ctx);
    } catch (err) {
      root.innerHTML = `
        <div class="cx-vis"><div class="cx-empty">تعذر تحميل الزيارات.
        <button type="button" class="cx-btn cx-btn--primary" id="cxVisRetry">إعادة المحاولة</button></div></div>`;
      root.querySelector("#cxVisRetry")?.addEventListener("click", () => render(state, root, helpers));
      ctx.showNotice(err.message || String(err));
    }
  }

  window.ClinicsVisits = { render };
})();
