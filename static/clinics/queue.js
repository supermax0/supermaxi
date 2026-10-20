/**
 * Finora Clinics — Queue Operations Center
 */
(() => {
  const POLL_MS = 12000;

  function can(ctx, perm) {
    const u = ctx.bootstrap?.user || ctx.data?.user || {};
    if (u.role === "admin") return true;
    return (u.permissions || []).includes(perm);
  }

  function fmtDay(iso) {
    if (!iso) return "";
    try {
      return new Date(iso + "T12:00:00").toLocaleDateString("ar-IQ", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch {
      return iso;
    }
  }

  function genderLabel(g) {
    const n = String(g || "").toLowerCase();
    return { male: "ذكر", female: "أنثى", m: "ذكر", f: "أنثى" }[n] || g || "—";
  }

  function waitLevel(mins) {
    if (mins <= 10) return "ok";
    if (mins <= 20) return "warn";
    if (mins <= 30) return "alert";
    return "critical";
  }

  function liveWaitMins(arrivedAt, fallback) {
    if (!arrivedAt) return fallback || 0;
    const t = new Date(arrivedAt).getTime();
    if (Number.isNaN(t)) return fallback || 0;
    return Math.max(0, Math.floor((Date.now() - t) / 60000));
  }

  function waitHtml(mins) {
    const level = waitLevel(mins);
    const text = mins <= 0 ? "الآن" : `${mins} دقيقة`;
    return `<span class="cx-q-wait cx-q-wait--${level}"><i class="fa fa-circle"></i> ${text}</span>`;
  }

  function timeOf(iso) {
    if (!iso) return "—";
    const s = String(iso);
    if (s.length >= 16) return window.FinoraTime.time(s);
    return window.FinoraTime.clock(s);
  }

  function ticketLabel(n) {
    if (n == null || n === "") return "—";
    return `A-${String(n).padStart(3, "0")}`;
  }

  function priorityBadge(p) {
    const v = Number(p || 0);
    if (v >= 2) return '<span class="cx-q-prio cx-q-prio--emergency">طارئ</span>';
    if (v >= 1) return '<span class="cx-q-prio cx-q-prio--priority">أولوية</span>';
    return "";
  }

  function statusLabel(s) {
    return (
      {
        arrived: "حضر",
        waiting: "ينتظر",
        in_consultation: "عند الطبيب",
        called: "تم النداء",
      }[s] || s || "—"
    );
  }

  function findAppt(ctx, id) {
    const pools = [ctx.data?.waiting, ctx.data?.in_consultation, ctx.data?.upcoming, ctx.data?.checkout];
    for (const list of pools) {
      const row = (list || []).find((x) => String(x.id) === String(id));
      if (row) return row;
    }
    return null;
  }

  function filteredWaiting(ctx) {
    let rows = [...(ctx.data?.waiting || [])];
    const doc = ctx.state.doctorFilter;
    if (doc) rows = rows.filter((r) => String(r.doctor_id) === String(doc));
    const q = (ctx.state.search || "").trim().toLowerCase();
    if (q) {
      rows = rows.filter((r) => {
        const hay = [
          r.patient_name,
          r.patient_phone,
          r.patient_file,
          r.queue_number,
          r.doctor_name,
          ticketLabel(r.queue_number),
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      });
    }
    return rows;
  }

  function filteredDoctors(ctx) {
    let docs = [...(ctx.data?.doctors_status || [])];
    if (ctx.state.doctorFilter) {
      docs = docs.filter((d) => String(d.doctor_id) === String(ctx.state.doctorFilter));
    }
    return docs;
  }

  function kpisHtml(data, waiting) {
    const s = data.stats || {};
    const waitMins = waiting.map((w) => liveWaitMins(w.arrived_at || w.checked_in_at, w.wait_minutes));
    const avg = waitMins.length ? Math.round(waitMins.reduce((a, b) => a + b, 0) / waitMins.length) : s.average_waiting_minutes || 0;
    const maxW = waitMins.length ? Math.max(...waitMins) : s.max_waiting_minutes || 0;
    const cards = [
      { label: "في الانتظار", val: waiting.length, icon: "fa-users", theme: "blue" },
      { label: "عند الطبيب", val: s.in_consultation || 0, icon: "fa-user-doctor", theme: "teal" },
      { label: "متوسط الانتظار", val: `${avg} د`, icon: "fa-clock", theme: "orange" },
      { label: "أطول انتظار", val: `${maxW} د`, icon: "fa-hourglass-half", theme: "red" },
      { label: "أطباء متاحون", val: data.available_doctors || 0, icon: "fa-stethoscope", theme: "green" },
      { label: "مكتمل اليوم", val: s.completed || 0, icon: "fa-circle-check", theme: "purple" },
    ];
    return cards
      .map(
        (c) => `
      <article class="cx-q-kpi cx-q-kpi--${c.theme}">
        <div class="cx-q-kpi__icon"><i class="fa ${c.icon}"></i></div>
        <div>
          <span>${c.label}</span>
          <strong>${c.val}</strong>
        </div>
      </article>`
      )
      .join("");
  }

  function doctorCardsHtml(ctx) {
    const docs = filteredDoctors(ctx);
    if (!docs.length) {
      return '<div class="cx-empty">لا أطباء نشطون لهذا اليوم</div>';
    }
    return docs
      .map((d) => {
        const busy = !d.available;
        const nextName = d.next_patient || "—";
        const nextWait = d.next_wait_minutes || 0;
        const started = timeOf(d.consultation_started_at);
        return `
        <article class="cx-q-doc ${busy ? "is-busy" : "is-free"}" style="--doc-color:${ctx.esc(d.color || "#0d9488")}">
          <div class="cx-q-doc__head">
            <div class="cx-q-doc__avatar"><i class="fa fa-user-doctor"></i></div>
            <div>
              <strong>${ctx.esc(d.doctor_name || "")}</strong>
              <span>${ctx.esc(d.specialty || "—")}</span>
            </div>
            <em class="cx-q-doc__status">${busy ? "مشغول" : "متاح"}</em>
          </div>
          <div class="cx-q-doc__body">
            ${
              busy
                ? `<div class="cx-q-doc__stats">
                     <div class="cx-q-doc__row"><span>المريض الحالي</span><b>${ctx.esc(d.current_patient || "—")}</b></div>
                     <div class="cx-q-doc__row"><span>بدأت المعاينة</span><b>${ctx.esc(started)}</b></div>
                     <div class="cx-q-doc__row"><span>مدة الزيارة</span><b>${d.consultation_minutes || 0} دقيقة</b></div>
                   </div>`
                : `<div class="cx-q-doc__idle">لا يوجد مريض حالياً</div>`
            }
            <div class="cx-q-doc__next">
              <span>التالي</span>
              <b>${ctx.esc(nextName)}</b>
              ${d.next_patient ? `<small>ينتظر منذ ${nextWait} دقائق</small>` : ""}
            </div>
          </div>
          ${
            !busy && d.next_appointment_id
              ? `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-q-start="${d.next_appointment_id}">إدخال المريض</button>`
              : ""
          }
        </article>`;
      })
      .join("");
  }

  function menuHtml(a, ctx) {
    const id = a.id;
    const item = (act, label, icon, danger = false) =>
      `<button type="button" class="cx-q-menu__item${danger ? " is-danger" : ""}" data-q-menu="${act}" data-id="${id}"><i class="fa ${icon}"></i> ${label}</button>`;
    return `
      <div class="cx-q-menu" hidden data-menu-for="${id}">
        ${item("open", "فتح الملف", "fa-folder-open")}
        ${a.patient_phone ? `<a class="cx-q-menu__item" href="tel:${ctx.esc(a.patient_phone)}"><i class="fa fa-phone"></i> اتصال</a>` : ""}
        ${item("change_doctor", "تغيير الطبيب", "fa-user-doctor")}
        ${item("note", "إضافة ملاحظة", "fa-note-sticky")}
        ${item("priority", "تحديد أولوية", "fa-flag")}
        ${item("recall", "إعادة نداء", "fa-bullhorn")}
        ${item("reorder_up", "رفع للأعلى", "fa-arrow-up")}
        ${item("reorder_down", "إنزال للأسفل", "fa-arrow-down")}
        ${item("remove", "إزالة من الانتظار", "fa-right-from-bracket")}
        ${item("cancel", "إلغاء", "fa-ban", true)}
        ${item("no_show", "لم يحضر", "fa-user-xmark", true)}
      </div>`;
  }

  function tableHtml(ctx) {
    const rows = filteredWaiting(ctx);
    if (!rows.length) {
      return `<tr><td colspan="8"><div class="cx-empty">الطابور فارغ</div></td></tr>`;
    }
    return rows
      .map((a, idx) => {
        const mins = liveWaitMins(a.arrived_at || a.checked_in_at, a.wait_minutes);
        const prio = Number(a.queue_priority || 0);
        return `
        <tr class="cx-q-row${prio >= 2 ? " is-emergency" : prio >= 1 ? " is-priority" : ""}" data-appt-id="${a.id}" draggable="true">
          <td class="cx-q-drag"><i class="fa fa-grip-vertical"></i> ${idx + 1}</td>
          <td><strong>${ticketLabel(a.queue_number)}</strong></td>
          <td>
            <button type="button" class="cx-q-name" data-q-open="${a.id}">${ctx.esc(a.patient_name || "—")}</button>
            ${priorityBadge(prio)}
          </td>
          <td>${ctx.esc(a.doctor_name || "—")}</td>
          <td>${ctx.esc(timeOf(a.arrived_at || a.checked_in_at))}</td>
          <td data-live-wait="${ctx.esc(a.arrived_at || a.checked_in_at || "")}" data-fallback="${mins}">${waitHtml(mins)}</td>
          <td><span class="cx-badge cx-badge--waiting">${statusLabel(a.status)}${prio >= 1 && a.status === "waiting" ? "" : ""}</span></td>
          <td class="cx-q-actions">
            <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-q-start="${a.id}">إدخال للطبيب</button>
            <button type="button" class="cx-btn cx-btn--sm cx-btn--ghost" data-q-more="${a.id}" aria-label="المزيد"><i class="fa fa-ellipsis-vertical"></i></button>
            ${menuHtml(a, ctx)}
          </td>
        </tr>`;
      })
      .join("");
  }

  function alertsHtml(data) {
    const alerts = data.alerts || [];
    if (!alerts.length) return "";
    return `<div class="cx-q-alerts">${alerts
      .slice(0, 4)
      .map(
        (a) => `
      <div class="cx-q-alert">
        <i class="fa fa-triangle-exclamation"></i>
        <span>${a.count ? `${a.count} · ` : ""}${escSafe(a.description || a.title || "")}</span>
      </div>`
      )
      .join("")}</div>`;
  }

  function escSafe(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function drawerHtml(a, ctx) {
    if (!a) return "";
    const mins = liveWaitMins(a.arrived_at || a.checked_in_at, a.wait_minutes);
    const finance =
      can(ctx, "clinics_billing") && a.invoice_balance != null
        ? `<div class="cx-q-drawer__field"><span>الرصيد</span><b>${ctx.money(a.invoice_balance || 0)}</b></div>`
        : "";
    const reason = can(ctx, "clinics_clinical")
      ? `<div class="cx-q-drawer__field"><span>سبب الزيارة</span><b>${ctx.esc(a.notes || a.service_name || "—")}</b></div>`
      : "";
    return `
      <aside class="cx-q-drawer" id="cxQDrawer">
        <header class="cx-q-drawer__head">
          <div>
            <div class="cx-kicker">تفاصيل الانتظار</div>
            <h2>${ctx.esc(a.patient_name || "")}</h2>
            <p>${ticketLabel(a.queue_number)} · ${ctx.esc(a.patient_file || "")}</p>
          </div>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxQDrawerClose" aria-label="إغلاق"><i class="fa fa-xmark"></i></button>
        </header>
        <div class="cx-q-drawer__body">
          <div class="cx-q-drawer__field"><span>الهاتف</span><b>${ctx.esc(a.patient_phone || "—")}</b></div>
          <div class="cx-q-drawer__field"><span>العمر / الجنس</span><b>${a.patient_age != null ? a.patient_age + " سنة" : "—"} · ${genderLabel(a.patient_gender)}</b></div>
          <div class="cx-q-drawer__field"><span>الطبيب</span><b>${ctx.esc(a.doctor_name || "—")}</b></div>
          <div class="cx-q-drawer__field"><span>وقت الوصول</span><b>${ctx.esc(timeOf(a.arrived_at || a.checked_in_at))}</b></div>
          <div class="cx-q-drawer__field"><span>مدة الانتظار</span><b>${waitHtml(mins)}</b></div>
          ${reason}
          ${finance}
        </div>
        <footer class="cx-q-drawer__foot">
          <button type="button" class="cx-btn cx-btn--primary" data-q-start="${a.id}">إدخال للطبيب</button>
          <a class="cx-btn" href="/clinics/patients/${a.patient_id}">فتح الملف</a>
          ${a.patient_phone ? `<a class="cx-btn" href="tel:${ctx.esc(a.patient_phone)}">اتصال</a>` : ""}
          <button type="button" class="cx-btn" data-q-menu="recall" data-id="${a.id}">إعادة نداء</button>
          <button type="button" class="cx-btn" data-q-menu="change_doctor" data-id="${a.id}">تغيير الطبيب</button>
          <button type="button" class="cx-btn" data-q-menu="note" data-id="${a.id}">ملاحظة</button>
          <button type="button" class="cx-btn" data-q-menu="remove" data-id="${a.id}">إزالة</button>
        </footer>
      </aside>`;
  }

  function buildHtml(ctx) {
    const data = ctx.data;
    const waiting = filteredWaiting(ctx);
    const doctors = data.doctors || [];
    return `
      <div class="cx-q ${ctx.state.drawerId ? "has-drawer" : ""}">
        <header class="cx-q-header">
          <div class="cx-q-header__title">
            <h1>قائمة الانتظار</h1>
            <p>إدارة حركة المرضى والطابور داخل العيادة · ${fmtDay(ctx.state.day)}</p>
          </div>
          <div class="cx-q-header__tools">
            <div class="cx-q-search">
              <i class="fa fa-search"></i>
              <input type="search" class="cx-input" id="cxQSearch" placeholder="ابحث عن مريض..." value="${ctx.esc(ctx.state.search || "")}">
            </div>
            <div class="cx-q-filters">
              <input type="date" class="cx-input cx-input--compact" id="cxQDay" value="${ctx.esc(ctx.state.day)}">
              <select class="cx-select cx-input--compact" id="cxQDoctor">
                <option value="">كل الأطباء</option>
                ${doctors
                  .map(
                    (d) =>
                      `<option value="${d.id}" ${String(d.id) === String(ctx.state.doctorFilter || "") ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <div class="cx-q-toolbar">
              <button type="button" class="cx-btn cx-btn--primary" id="cxQAdd"><i class="fa fa-plus"></i> إضافة مريض</button>
              <a class="cx-btn" href="/clinics/display" target="_blank" rel="noopener"><i class="fa fa-tv"></i> فتح شاشة العرض</a>
            </div>
          </div>
        </header>

        <div class="cx-q-kpis">${kpisHtml(data, waiting)}</div>
        ${alertsHtml(data)}

        <div class="cx-q-body">
          <section class="cx-q-table-card">
            <div class="cx-q-section-head">
              <h2>المنتظرون</h2>
              <p>${waiting.length} مريض</p>
            </div>
            <div class="cx-table-wrap">
              <table class="cx-table cx-q-table">
                <thead>
                  <tr>
                    <th>#</th><th>الدور</th><th>المريض</th><th>الطبيب</th>
                    <th>وقت الوصول</th><th>مدة الانتظار</th><th>الحالة</th><th>الإجراء</th>
                  </tr>
                </thead>
                <tbody id="cxQTbody">${tableHtml(ctx)}</tbody>
              </table>
            </div>
          </section>
          <section class="cx-q-now">
            <div class="cx-q-section-head"><h2>الآن عند الأطباء</h2></div>
            <div class="cx-q-docs">${doctorCardsHtml(ctx)}</div>
          </section>
        </div>

        ${ctx.state.drawerId ? drawerHtml(findAppt(ctx, ctx.state.drawerId), ctx) : ""}
        <div class="cx-q-drawer-backdrop" id="cxQBackdrop" ${ctx.state.drawerId ? "" : "hidden"}></div>
      </div>`;
  }

  async function setStatus(ctx, id, status, note) {
    await ctx.api(`/clinics/api/appointments/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status, note: note || "" }),
    });
  }

  async function startVisit(ctx, id) {
    const appt = findAppt(ctx, id);
    if (!appt) return;
    const doc = (ctx.data.doctors_status || []).find((d) => String(d.doctor_id) === String(appt.doctor_id));
    if (doc && !doc.available && doc.current_patient) {
      const ok = window.confirm(
        `${doc.doctor_name || "الطبيب"} لديه مريض حالياً:\n${doc.current_patient}\nمدة الزيارة: ${doc.consultation_minutes || 0} دقيقة\n\nموافق = إدخال كالتالي / بدء الزيارة\nإلغاء = تراجع`
      );
      if (!ok) return;
    }
    try {
      const visit = await ctx.api("/clinics/api/visits", {
        method: "POST",
        body: JSON.stringify({ appointment_id: Number(id) }),
      });
      await ctx.api("/clinics/api/queue/recall", {
        method: "POST",
        body: JSON.stringify({ appointment_id: Number(id) }),
      }).catch(() => null);
      ctx.showNotice(`تم إدخال ${appt.patient_name || "المريض"} للطبيب`);
      if (visit?.id && window.confirm("فتح صفحة الزيارة؟")) {
        location.href = `/clinics/doctor/${visit.id}`;
        return;
      }
      await refresh(ctx, true);
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  async function reorder(ctx, orderedIds) {
    await ctx.api("/clinics/api/queue/reorder", {
      method: "POST",
      body: JSON.stringify({ date: ctx.state.day, order: orderedIds }),
    });
    await refresh(ctx, true);
  }

  function bindDragReorder(ctx) {
    const tbody = document.getElementById("cxQTbody");
    if (!tbody) return;
    let dragId = null;
    tbody.querySelectorAll("tr[data-appt-id]").forEach((tr) => {
      tr.addEventListener("dragstart", () => {
        dragId = tr.dataset.apptId;
        tr.classList.add("is-dragging");
      });
      tr.addEventListener("dragend", () => tr.classList.remove("is-dragging"));
      tr.addEventListener("dragover", (e) => {
        e.preventDefault();
        tr.classList.add("is-drop");
      });
      tr.addEventListener("dragleave", () => tr.classList.remove("is-drop"));
      tr.addEventListener("drop", async (e) => {
        e.preventDefault();
        tr.classList.remove("is-drop");
        if (!dragId || dragId === tr.dataset.apptId) return;
        const ids = [...tbody.querySelectorAll("tr[data-appt-id]")].map((r) => r.dataset.apptId);
        const from = ids.indexOf(dragId);
        const to = ids.indexOf(tr.dataset.apptId);
        if (from < 0 || to < 0) return;
        ids.splice(to, 0, ids.splice(from, 1)[0]);
        try {
          await reorder(ctx, ids.map(Number));
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      });
    });
  }

  function tickLiveWaits() {
    document.querySelectorAll("[data-live-wait]").forEach((el) => {
      const mins = liveWaitMins(el.dataset.liveWait, Number(el.dataset.fallback || 0));
      el.innerHTML = waitHtml(mins);
    });
  }

  function promptAddPatient(ctx) {
    const doctors = ctx.data.doctors || [];
    ctx.openModal(
      "إضافة مريض للانتظار",
      `
      <div class="cx-field">
        <label>بحث عن مريض</label>
        <input class="cx-input" id="q_patient_q" placeholder="اسم / هاتف / رقم ملف">
        <div id="q_patient_results" class="cx-q-patient-results"></div>
        <input type="hidden" id="q_patient_id">
        <div id="q_patient_picked" class="cx-muted" style="margin-top:6px"></div>
      </div>
      <div class="cx-field"><button type="button" class="cx-btn" id="q_new_patient"><i class="fa fa-user-plus"></i> إنشاء مريض جديد</button></div>
      <div class="cx-field">
        <label>الطبيب</label>
        <select class="cx-select" id="q_doctor">
          <option value="">اختر الطبيب</option>
          ${doctors.map((d) => `<option value="${d.id}">${ctx.esc(d.full_name)}</option>`).join("")}
        </select>
      </div>
      <div class="cx-field"><label>سبب الزيارة</label><input class="cx-input" id="q_notes"></div>
      <div class="cx-field">
        <label>الأولوية</label>
        <select class="cx-select" id="q_priority">
          <option value="0">عادي</option>
          <option value="1">أولوية</option>
          <option value="2">طارئ</option>
        </select>
      </div>`,
      async () => {
        const patientId = Number(document.getElementById("q_patient_id").value || 0);
        const doctorId = Number(document.getElementById("q_doctor").value || 0);
        if (!patientId) throw new Error("اختر المريض أولاً");
        if (!doctorId) throw new Error("اختر الطبيب");
        await ctx.api("/clinics/api/queue/enqueue", {
          method: "POST",
          body: JSON.stringify({
            patient_id: patientId,
            doctor_id: doctorId,
            notes: document.getElementById("q_notes").value || "",
            queue_priority: Number(document.getElementById("q_priority").value || 0),
            appointment_date: ctx.state.day,
          }),
        });
        ctx.showNotice("تمت إضافة المريض للانتظار");
        await refresh(ctx, true);
      }
    );

    const qInput = document.getElementById("q_patient_q");
    const results = document.getElementById("q_patient_results");
    let timer;
    qInput?.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = qInput.value.trim();
        if (q.length < 2) {
          results.innerHTML = "";
          return;
        }
        try {
          const rows = await ctx.api(`/clinics/api/patients?q=${encodeURIComponent(q)}`);
          const list = Array.isArray(rows) ? rows : rows?.items || rows?.patients || [];
          results.innerHTML = list
            .slice(0, 8)
            .map(
              (p) => `
            <button type="button" class="cx-q-patient-hit" data-pid="${p.id}" data-name="${ctx.esc(p.full_name || "")}">
              <strong>${ctx.esc(p.full_name || "")}</strong>
              <span>${ctx.esc(p.file_number || "")} · ${ctx.esc(p.phone || "")}</span>
            </button>`
            )
            .join("") || '<div class="cx-empty">لا نتائج</div>';
          results.querySelectorAll("[data-pid]").forEach((btn) => {
            btn.onclick = () => {
              document.getElementById("q_patient_id").value = btn.dataset.pid;
              document.getElementById("q_patient_picked").textContent = `المحدد: ${btn.dataset.name}`;
              results.innerHTML = "";
            };
          });
        } catch (err) {
          results.innerHTML = `<div class="cx-empty">${ctx.esc(err.message || String(err))}</div>`;
        }
      }, 280);
    });

    document.getElementById("q_new_patient")?.addEventListener("click", () => {
      if (typeof ctx.promptNewPatient === "function") ctx.promptNewPatient();
    });
  }

  async function handleMenu(ctx, act, id) {
    const appt = findAppt(ctx, id);
    if (!appt) return;
    try {
      if (act === "open") {
        location.href = `/clinics/patients/${appt.patient_id}`;
        return;
      }
      if (act === "recall") {
        await ctx.api("/clinics/api/queue/recall", {
          method: "POST",
          body: JSON.stringify({ appointment_id: Number(id) }),
        });
        ctx.showNotice(`تم نداء الدور ${ticketLabel(appt.queue_number)}`);
        return;
      }
      if (act === "note") {
        const note = window.prompt("ملاحظة", appt.notes || "");
        if (note == null) return;
        await ctx.api(`/clinics/api/appointments/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ notes: note }),
        });
        await refresh(ctx, true);
        return;
      }
      if (act === "change_doctor") {
        const doctors = ctx.data.doctors || [];
        const options = doctors.map((d) => `${d.id}: ${d.full_name}`).join("\n");
        const raw = window.prompt(`أدخل رقم الطبيب:\n${options}`, String(appt.doctor_id || ""));
        if (!raw) return;
        await ctx.api(`/clinics/api/appointments/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ doctor_id: Number(raw) }),
        });
        await refresh(ctx, true);
        return;
      }
      if (act === "priority") {
        const raw = window.prompt("الأولوية: 0 عادي / 1 أولوية / 2 طارئ", String(appt.queue_priority || 0));
        if (raw == null) return;
        await ctx.api(`/clinics/api/appointments/${id}/priority`, {
          method: "POST",
          body: JSON.stringify({ priority: Number(raw), reason: "manual" }),
        });
        await refresh(ctx, true);
        return;
      }
      if (act === "reorder_up" || act === "reorder_down") {
        const ids = filteredWaiting(ctx).map((r) => r.id);
        const idx = ids.indexOf(Number(id));
        if (idx < 0) return;
        const swap = act === "reorder_up" ? idx - 1 : idx + 1;
        if (swap < 0 || swap >= ids.length) return;
        const next = [...ids];
        [next[idx], next[swap]] = [next[swap], next[idx]];
        await reorder(ctx, next);
        return;
      }
      if (act === "remove") {
        await setStatus(ctx, id, "confirmed", "إزالة من الانتظار");
        await refresh(ctx, true);
        return;
      }
      if (act === "cancel") {
        await setStatus(ctx, id, "cancelled", "إلغاء من قائمة الانتظار");
        await refresh(ctx, true);
        return;
      }
      if (act === "no_show") {
        await setStatus(ctx, id, "no_show", "لم يحضر");
        await refresh(ctx, true);
        return;
      }
    } catch (err) {
      ctx.showNotice(err.message || String(err));
    }
  }

  function bindUi(ctx) {
    const root = ctx.root;
    const bindChange = (sel, fn) => {
      const el = root.querySelector(sel);
      if (el) el.onchange = fn;
    };
    const bindClick = (sel, fn) => {
      const el = root.querySelector(sel);
      if (el) el.onclick = fn;
    };

    bindChange("#cxQDay", (e) => {
      ctx.state.day = e.target.value;
      refresh(ctx, true);
    });
    bindChange("#cxQDoctor", (e) => {
      ctx.state.doctorFilter = e.target.value || "";
      paint(ctx);
    });
    const search = root.querySelector("#cxQSearch");
    if (search) {
      let t;
      search.oninput = () => {
        clearTimeout(t);
        t = setTimeout(() => {
          ctx.state.search = search.value || "";
          paint(ctx);
        }, 180);
      };
    }
    bindClick("#cxQAdd", () => promptAddPatient(ctx));
    bindClick("#cxQDrawerClose", () => {
      ctx.state.drawerId = null;
      paint(ctx);
    });
    bindClick("#cxQBackdrop", () => {
      ctx.state.drawerId = null;
      paint(ctx);
    });

    root.querySelectorAll("[data-q-start]").forEach((btn) => {
      btn.onclick = () => startVisit(ctx, btn.dataset.qStart);
    });
    root.querySelectorAll("[data-q-open]").forEach((btn) => {
      btn.onclick = () => {
        ctx.state.drawerId = btn.dataset.qOpen;
        paint(ctx);
      };
    });
    root.querySelectorAll("[data-q-more]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = root.querySelector(`[data-menu-for="${btn.dataset.qMore}"]`);
        root.querySelectorAll(".cx-q-menu").forEach((m) => {
          if (m !== menu) m.hidden = true;
        });
        if (menu) menu.hidden = !menu.hidden;
      };
    });
    root.querySelectorAll("[data-q-menu]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        handleMenu(ctx, btn.dataset.qMenu, btn.dataset.id);
      };
    });

    document.addEventListener(
      "click",
      () => {
        root.querySelectorAll(".cx-q-menu").forEach((m) => {
          m.hidden = true;
        });
      },
      { once: true }
    );

    bindDragReorder(ctx);
    tickLiveWaits();
    clearInterval(window.__cxQWaitTick);
    window.__cxQWaitTick = setInterval(tickLiveWaits, 30000);
  }

  function paint(ctx) {
    ctx.root.innerHTML = buildHtml(ctx);
    bindUi(ctx);
  }

  async function refresh(ctx, force) {
    const qs = new URLSearchParams({ date: ctx.state.day });
    const data = await ctx.api(`/clinics/api/reception?${qs}`);
    if (!force && data.pulse_version && data.pulse_version === ctx.state.pulse) {
      tickLiveWaits();
      return;
    }
    ctx.state.pulse = data.pulse_version || "";
    ctx.data = data;
    paint(ctx);
  }

  async function render(state, root, helpers) {
    clearTimeout(window.__cxQPoll);
    clearInterval(window.__cxQWaitTick);
    const ctx = {
      state: {
        day: state.day,
        doctorFilter: "",
        search: "",
        drawerId: null,
        pulse: "",
      },
      data: null,
      root,
      bootstrap: helpers.bootstrap,
      api: helpers.api,
      esc: helpers.esc,
      money: helpers.money,
      showNotice: helpers.showNotice,
      openModal: helpers.openModal,
      promptNewPatient: helpers.promptNewPatient,
    };
    root.innerHTML = `<div class="cx-q"><div class="cx-skeleton-block" style="height:88px;border-radius:16px"></div></div>`;
    await refresh(ctx, true);

    const poll = async () => {
      try {
        if (document.hidden) return;
        await refresh(ctx, false);
      } catch {
        /* keep polling */
      }
    };
    window.__cxQPoll = setInterval(poll, POLL_MS);
  }

  window.ClinicsQueue = { render };
})();
