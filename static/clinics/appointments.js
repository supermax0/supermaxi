/**
 * Finora Clinics — Appointment Scheduling Center
 */
(() => {
  const VIEWS = [
    { key: "day", label: "اليوم" },
    { key: "week", label: "الأسبوع" },
    { key: "month", label: "الشهر" },
    { key: "list", label: "القائمة" },
  ];

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

  function weekStart(iso) {
    const d = new Date(iso + "T12:00:00");
    const day = (d.getDay() + 6) % 7;
    d.setDate(d.getDate() - day);
    return d.toISOString().slice(0, 10);
  }

  function addDays(iso, n) {
    const d = new Date(iso + "T12:00:00");
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function localToday() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function fmtDateShort(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso + "T12:00:00").toLocaleDateString("ar-IQ", {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } catch {
      return iso;
    }
  }

  function genderLabel(value) {
    const normalized = String(value || "").toLowerCase();
    return { male: "ذكر", female: "أنثى", m: "ذكر", f: "أنثى" }[normalized] || value || "";
  }

  function fileNumberDisplay(file) {
    if (!file) return "";
    const s = String(file).trim();
    return s.startsWith("#") ? s : `#${s}`;
  }

  function drawerField(label, valueHtml) {
    return `
      <div class="cx-appt-drawer__field">
        <span class="cx-appt-drawer__field-label">${label}</span>
        <span class="cx-appt-drawer__field-value">${valueHtml}</span>
      </div>`;
  }

  function drawerBodyHtml(appt, ctx) {
    const age = appt.patient_age ? `${appt.patient_age} سنة` : "";
    const gender = genderLabel(appt.patient_gender);
    const demo = [age, gender].filter(Boolean).join(" · ") || "—";
    const fileNo = fileNumberDisplay(appt.patient_file);
    const duration = appt.duration_minutes || 30;

    const acts = [];
    if (can(ctx, "clinics_reception")) {
      if (["pending", "confirmed", "scheduled"].includes(appt.status)) {
        acts.push(
          `<button type="button" class="cx-appt-drawer__btn cx-appt-drawer__btn--primary" data-drawer-act="arrived" data-finora-action="appointment.checkin" data-id="${appt.id}">
            <i class="fa fa-check"></i><span>تسجيل وصول</span>
          </button>`
        );
      }
      if (appt.status === "arrived") {
        acts.push(
          `<button type="button" class="cx-appt-drawer__btn" data-drawer-act="waiting" data-finora-action="queue.add" data-id="${appt.id}">
            <i class="fa fa-hourglass-half"></i><span>إضافة للانتظار</span>
          </button>`
        );
      }
      if (appt.status === "waiting") {
        acts.push(
          `<button type="button" class="cx-appt-drawer__btn cx-appt-drawer__btn--primary" data-drawer-act="start" data-finora-action="visit.start" data-id="${appt.id}">
            <i class="fa fa-user-doctor"></i><span>إدخال للطبيب</span>
          </button>`
        );
      }
    }
    acts.push(
      `<button type="button" class="cx-appt-drawer__btn" data-drawer-act="reschedule" data-id="${appt.id}" data-date="${ctx.esc(appt.appointment_date)}" data-time="${ctx.esc(appt.start_time)}">
        <i class="fa fa-calendar-days"></i><span>إعادة جدولة</span>
      </button>`
    );
    if (appt.patient_phone) {
      acts.push(
        `<a class="cx-appt-drawer__btn" href="tel:${ctx.esc(appt.patient_phone)}">
          <i class="fa fa-phone"></i><span>اتصال بالمريض</span>
        </a>`
      );
    }
    if (appt.visit_id) {
      acts.push(
        `<a class="cx-appt-drawer__btn" href="/clinics/doctor/${appt.visit_id}">
          <i class="fa fa-notes-medical"></i><span>فتح الزيارة</span>
        </a>`
      );
    }
    if (can(ctx, "clinics_reception") && !["cancelled", "completed", "no_show"].includes(appt.status)) {
      acts.push(
        `<button type="button" class="cx-appt-drawer__btn cx-appt-drawer__btn--danger" data-drawer-act="cancel" data-id="${appt.id}">
          <i class="fa fa-trash-can"></i><span>إلغاء الموعد</span>
        </button>`
      );
    }

    return `
      <div class="cx-appt-drawer__profile">
        <div class="cx-appt-drawer__avatar" aria-hidden="true"><i class="fa fa-user"></i></div>
        <div class="cx-appt-drawer__identity">
          <a class="cx-appt-drawer__name" href="/clinics/patients/${appt.patient_id}">${ctx.esc(appt.patient_name)}</a>
          ${fileNo ? `<span class="cx-appt-drawer__file">${ctx.esc(fileNo)}</span>` : ""}
          <span class="cx-appt-drawer__phone">${ctx.esc(appt.patient_phone || "—")}</span>
          <span class="cx-appt-drawer__demo">${ctx.esc(demo)}</span>
        </div>
      </div>
      <div class="cx-appt-drawer__fields">
        ${drawerField("الوقت", ctx.esc(window.FinoraTime.clock(appt.start_time || "—")))}
        ${drawerField("التاريخ", ctx.esc(fmtDateShort(appt.appointment_date)))}
        ${drawerField("الطبيب", ctx.esc(appt.doctor_name || "—"))}
        ${drawerField("الخدمة", ctx.esc(appt.service_name || "—"))}
        ${drawerField("المدة", `${duration} دقيقة`)}
        ${drawerField("الحالة", ctx.badge(appt.status))}
      </div>
      <div class="cx-appt-drawer__stack">${acts.join("")}</div>
      <div class="cx-appt-drawer__notes">
        <h4>ملاحظات</h4>
        <p>${appt.notes ? ctx.esc(appt.notes) : '<span class="cx-muted">لا توجد ملاحظات</span>'}</p>
        <button type="button" class="cx-link-btn" data-drawer-act="note" data-id="${appt.id}">تعديل الملاحظة</button>
      </div>`;
  }

  function bindDrawerActions(body, ctx) {
    body.querySelectorAll("[data-drawer-act]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.dataset.id;
        const act = btn.dataset.drawerAct;
        try {
          if (act === "arrived") {
            await setStatus(ctx, id, "arrived", "تم تسجيل الوصول");
            return;
          }
          if (act === "waiting") {
            await setStatus(ctx, id, "waiting", "تمت الإضافة للانتظار");
            return;
          }
          if (act === "start") {
            await ctx.api("/clinics/api/visits", { method: "POST", body: JSON.stringify({ appointment_id: Number(id) }) });
            ctx.showNotice("تم إدخال المريض للطبيب", false);
            await ctx.refresh({ silent: true });
            return;
          }
          if (act === "reschedule") {
            doReschedule(ctx, id, btn.dataset.date, btn.dataset.time);
            return;
          }
          if (act === "cancel") {
            if (!confirm("إلغاء الموعد؟")) return;
            await setStatus(ctx, id, "cancelled", "تم الإلغاء");
            const d = document.getElementById("cxApptDrawer");
            if (d) d.hidden = true;
            return;
          }
          if (act === "note") {
            const appt = (ctx.data?.appointments || []).find((x) => String(x.id) === String(id));
            ctx.openModal(
              "ملاحظة الموعد",
              `<textarea class="cx-input" id="appt_note" rows="4">${ctx.esc(appt?.notes || "")}</textarea>`,
              async () => {
                await ctx.api(`/clinics/api/appointments/${id}`, {
                  method: "PATCH",
                  body: JSON.stringify({ notes: document.getElementById("appt_note").value }),
                });
                await ctx.refresh({ silent: true });
              },
              { skipRender: true }
            );
          }
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      };
    });
  }

  let selectedApptId = null;
  let listPage = 1;
  const LIST_PAGE_SIZE = 10;

  function timeSlots(slotMin, startH = 8, endH = 20) {
    const out = [];
    let m = startH * 60;
    const end = endH * 60;
    while (m < end) {
      const h = Math.floor(m / 60);
      const min = m % 60;
      out.push(`${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`);
      m += slotMin;
    }
    return out;
  }

  function apptMenuHtml(a, ctx, menuId) {
    const id = a.id;
    const item = (act, label, icon, extra = "", danger = false) =>
      `<button type="button" class="cx-rec-menu__item ${danger ? "is-danger" : ""}" role="menuitem"
        data-appt-menu-act="${act}" data-id="${id}" ${extra}>
        <span class="cx-rec-menu__icon"><i class="fa ${icon}"></i></span>
        <span class="cx-rec-menu__label">${label}</span>
      </button>`;
    const main = [
      item("reschedule", "إعادة جدولة", "fa-calendar-days", `data-date="${ctx.esc(a.appointment_date)}" data-time="${ctx.esc(a.start_time)}"`),
      item("note", "إضافة ملاحظة", "fa-note-sticky"),
    ];
    if (can(ctx, "clinics_reception") && ["pending", "confirmed", "scheduled"].includes(a.status)) {
      main.unshift(item("arrived", "تسجيل وصول", "fa-door-open"));
    }
    const danger = [
      item("no_show", "لم يحضر", "fa-user-slash", "", true),
      item("cancel", "إلغاء الموعد", "fa-ban", "", true),
    ];
    return `
      <div class="cx-rec-menu-wrap">
        <button type="button" class="cx-icon-btn cx-icon-btn--more" data-appt-menu="${menuId}" title="المزيد" aria-haspopup="menu">
          <i class="fa fa-ellipsis-vertical"></i>
        </button>
        <div class="cx-rec-menu" id="${menuId}" role="menu" aria-label="إجراءات الموعد">
          <div class="cx-rec-menu__head">إجراءات</div>
          <div class="cx-rec-menu__group">${main.join("")}</div>
          <div class="cx-rec-menu__divider"></div>
          <div class="cx-rec-menu__group cx-rec-menu__group--danger">${danger.join("")}</div>
        </div>
      </div>`;
  }

  function statusClass(status) {
    const map = {
      confirmed: "confirmed",
      pending: "pending",
      scheduled: "pending",
      arrived: "arrived",
      waiting: "waiting",
      in_consultation: "in",
      completed: "done",
      cancelled: "cancel",
      no_show: "no_show",
    };
    return map[status] || "pending";
  }

  // The card to open depends on the appointment's stage, so each lesson can point at the right kind of card.
  function openAction(status) {
    if (["pending", "confirmed", "scheduled"].includes(status)) return "appointment.open.scheduled";
    if (status === "arrived") return "appointment.open.arrived";
    if (status === "waiting") return "appointment.open.waiting";
    return "appointment.open";
  }

  function apptCardHtml(a, ctx, compact = false) {
    const cls = statusClass(a.status);
    const selected = selectedApptId && String(selectedApptId) === String(a.id) ? " is-selected" : "";
    return `
      <button type="button" class="cx-appt-card cx-appt-card--${cls}${selected}" data-appt-pick="${a.id}" data-finora-action="${openAction(a.status)}"
        title="${ctx.esc(a.patient_name)} · ${ctx.esc(a.patient_phone || "")} · ${ctx.esc(a.service_name || "")} · ${ctx.esc(a.doctor_name || "")} · ${a.duration_minutes || 30} دقيقة · ${ctx.esc(ctx.statusLabel(a.status))}">
        <span class="cx-appt-card__time">${ctx.esc(window.FinoraTime.clock(a.start_time))}</span>
        <strong>${ctx.esc(a.patient_name)}</strong>
        ${!compact ? `<span>${ctx.esc(a.service_name || "")}</span>` : ""}
        <span class="cx-appt-card__badge">${ctx.badge(a.status)}</span>
      </button>`;
  }

  function listTable(data, ctx) {
    const rows = data.appointments || [];
    const total = rows.length;
    const pages = Math.max(1, Math.ceil(total / LIST_PAGE_SIZE));
    if (listPage > pages) listPage = pages;
    const start = (listPage - 1) * LIST_PAGE_SIZE;
    const slice = rows.slice(start, start + LIST_PAGE_SIZE);
    return `
      <section class="cx-appt-bottom">
        <div class="cx-appt-bottom__head">
          <h3>قائمة المواعيد</h3>
          <button type="button" class="cx-btn cx-btn--ghost" id="cxApptExport"><i class="fa fa-download"></i> تصدير</button>
        </div>
        <div class="cx-table-wrap">
          <table class="cx-table cx-appt-table">
            <thead>
              <tr><th>الوقت</th><th>المريض</th><th>الهاتف</th><th>الطبيب</th><th>الخدمة</th><th>الحالة</th><th></th></tr>
            </thead>
            <tbody>
              ${slice
                .map((a) => {
                  const menuId = `am-${a.id}`;
                  return `
                <tr data-appt-row="${a.id}" class="${selectedApptId && String(selectedApptId) === String(a.id) ? "is-selected" : ""}">
                  <td><b>${ctx.esc(window.FinoraTime.clock(a.start_time))}</b><small>${ctx.esc(a.appointment_date)}</small></td>
                  <td><button type="button" class="cx-link-btn" data-appt-pick="${a.id}">${ctx.esc(a.patient_name)}</button></td>
                  <td>${ctx.esc(a.patient_phone || "—")}</td>
                  <td>${ctx.esc(a.doctor_name || "—")}</td>
                  <td>${ctx.esc(a.service_name || "—")}</td>
                  <td>${ctx.badge(a.status)}</td>
                  <td class="cx-appt-actions">${apptMenuHtml(a, ctx, menuId)}</td>
                </tr>`;
                })
                .join("") || `<tr><td colspan="7"><div class="cx-empty">لا مواعيد</div></td></tr>`}
            </tbody>
          </table>
        </div>
        <div class="cx-appt-bottom__foot">
          <span class="cx-muted">عرض ${total ? start + 1 : 0}–${Math.min(start + LIST_PAGE_SIZE, total)} من ${total}</span>
          <div class="cx-appt-bottom__pages">
            <button type="button" class="cx-btn cx-btn--sm" id="cxApptPagePrev" ${listPage <= 1 ? "disabled" : ""}><i class="fa fa-chevron-right"></i></button>
            <span>${listPage} / ${pages}</span>
            <button type="button" class="cx-btn cx-btn--sm" id="cxApptPageNext" ${listPage >= pages ? "disabled" : ""}><i class="fa fa-chevron-left"></i></button>
          </div>
        </div>
      </section>`;
  }

  function exportCsv(rows, ctx) {
    const header = ["التاريخ", "الوقت", "المريض", "الهاتف", "الطبيب", "الخدمة", "الحالة"];
    const lines = [header.join(",")];
    rows.forEach((a) => {
      lines.push(
        [
          a.appointment_date,
          window.FinoraTime.clock(a.start_time),
          a.patient_name,
          a.patient_phone || "",
          a.doctor_name || "",
          a.service_name || "",
          ctx.statusLabel(a.status),
        ]
          .map((v) => `"${String(v).replace(/"/g, '""')}"`)
          .join(",")
      );
    });
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `appointments-${localToday()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function kpiRow(stats) {
    const s = stats || {};
    const upcoming = (s.confirmed || 0) + (s.arrived || 0) + (s.waiting || 0);
    const items = [
      { label: "مواعيد اليوم", val: s.total, sub: upcoming ? `${upcoming} قادم` : "", theme: "purple", icon: "fa-calendar-days" },
      { label: "مؤكد", val: s.confirmed, theme: "blue", icon: "fa-circle-check" },
      { label: "حضر", val: s.arrived, theme: "green", icon: "fa-user-check" },
      { label: "ينتظر", val: s.waiting, theme: "orange", icon: "fa-clock" },
      { label: "عند الطبيب", val: s.in_consultation, theme: "teal", icon: "fa-stethoscope" },
      { label: "ملغي", val: s.cancelled, theme: "gray", icon: "fa-ban" },
      { label: "لم يحضر", val: s.no_show, theme: "red", icon: "fa-user-xmark" },
    ];
    return items
      .map(
        (i) => `
      <article class="cx-appt-kpi cx-appt-kpi--${i.theme}">
        <i class="fa ${i.icon}"></i>
        <div><span>${i.label}</span><strong>${i.val || 0}</strong>${i.sub ? `<em>${i.sub}</em>` : ""}</div>
      </article>`
      )
      .join("");
  }

  const DOC_PREF_KEY = "cx-appt-doc-prefs";

  function loadDocPrefs() {
    try {
      const raw = JSON.parse(sessionStorage.getItem(DOC_PREF_KEY) || "{}");
      return {
        mode: raw.mode === "single" ? "single" : "all",
        selected: Array.isArray(raw.selected) ? raw.selected.map(String) : [],
      };
    } catch {
      return { mode: "all", selected: [] };
    }
  }

  function saveDocPrefs(prefs) {
    sessionStorage.setItem(
      DOC_PREF_KEY,
      JSON.stringify({
        mode: prefs.mode === "single" ? "single" : "all",
        selected: (prefs.selected || []).map(String),
      })
    );
  }

  function resolveVisibleDoctors(allDoctors, prefs) {
    const list = allDoctors || [];
    if (!list.length) return { visible: [], prefs, needsSelector: false };
    const ids = new Set(list.map((d) => String(d.id)));
    let selected = (prefs.selected || []).filter((id) => ids.has(String(id)));
    if (!selected.length) selected = list.slice(0, Math.min(4, list.length)).map((d) => String(d.id));

    const mode = prefs.mode === "single" ? "single" : "all";
    const needsSelector = list.length > 4 || mode === "single";

    let visible;
    if (mode === "single") {
      const one = list.find((d) => String(d.id) === String(selected[0])) || list[0];
      visible = one ? [one] : [];
      selected = one ? [String(one.id)] : [];
    } else if (list.length > 4) {
      visible = list.filter((d) => selected.includes(String(d.id)));
      if (!visible.length) {
        visible = list.slice(0, 4);
        selected = visible.map((d) => String(d.id));
      }
    } else {
      visible = list;
      selected = list.map((d) => String(d.id));
    }

    const nextPrefs = { mode, selected };
    saveDocPrefs(nextPrefs);
    return { visible, prefs: nextPrefs, needsSelector, all: list };
  }

  function doctorSelectorHtml(allDoctors, prefs, ctx) {
    if (!allDoctors.length) return "";
    const showChips = allDoctors.length > 4 || prefs.mode === "single";
    return `
      <div class="cx-appt-docbar" id="cxApptDocBar">
        <div class="cx-appt-docbar__modes" role="group" aria-label="نمط عرض الأطباء">
          <button type="button" class="cx-appt-docbar__mode ${prefs.mode === "all" ? "is-active" : ""}" data-doc-mode="all">كل الأطباء</button>
          <button type="button" class="cx-appt-docbar__mode ${prefs.mode === "single" ? "is-active" : ""}" data-doc-mode="single">طبيب واحد</button>
        </div>
        ${showChips ? `
        <div class="cx-appt-docbar__chips" role="group" aria-label="اختيار الأطباء">
          ${allDoctors
            .map((d) => {
              const active = prefs.selected.includes(String(d.id));
              return `<button type="button" class="cx-appt-docchip ${active ? "is-active" : ""}" data-doc-chip="${d.id}" style="--doc-color:${ctx.esc(d.color || "#0d9488")}" title="${ctx.esc(d.full_name)}">
                <i class="fa fa-user-doctor"></i><span>${ctx.esc(d.full_name)}</span>
              </button>`;
            })
            .join("")}
        </div>` : ""}
        <span class="cx-appt-docbar__hint">${prefs.mode === "single" ? "عرض طبيب واحد" : allDoctors.length > 4 ? `عرض ${prefs.selected.length} من ${allDoctors.length}` : `${allDoctors.length} أطباء`}</span>
      </div>`;
  }

  function dayTimeline(data, state, ctx) {
    const slot = data.slot_minutes || 30;
    const slots = timeSlots(slot);
    const allDoctors = data.doctors || [];
    const resolved = resolveVisibleDoctors(allDoctors, loadDocPrefs());
    const doctors = resolved.visible;
    const prefs = resolved.prefs;
    const appts = data.appointments || [];
    const docStatus = data.doctors_status || [];
    const isToday = state.day === localToday();
    const now = new Date();
    const nowLine =
      isToday
        ? `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
        : null;
    const single = doctors.length === 1;
    const layoutClass = single ? "is-single-doctor" : doctors.length >= 2 && doctors.length <= 4 ? "is-multi-doctor" : "is-selected-doctors";

    const visibleIds = new Set(doctors.map((d) => String(d.id)));
    const agendaAppts = appts.filter((a) => !visibleIds.size || visibleIds.has(String(a.doctor_id)));

    const head = doctors
      .map((d) => {
        const st = docStatus.find((x) => x.doctor_id === d.id);
        const stateLbl = st?.available ? "متاح" : st?.current_patient ? `مع ${st.current_patient}` : "—";
        const count = appts.filter((a) => a.doctor_id === d.id).length;
        return `
        <div class="cx-appt-dochead" style="border-color:${ctx.esc(d.color || "#0d9488")}">
          <span class="cx-appt-dochead__avatar"><i class="fa fa-user-doctor"></i></span>
          <span class="cx-appt-dochead__info">
            <strong>${ctx.esc(d.full_name)}</strong>
            <small>${ctx.esc(d.specialty || "طبيب")}</small>
            <em><i></i>${ctx.esc(stateLbl)} · ${count} موعد</em>
          </span>
        </div>`;
      })
      .join("");

    const rows = slots
      .map((slotLabel) => {
        const nextSlot = slots[slots.indexOf(slotLabel) + 1];
        const isNow = Boolean(nowLine && (slotLabel === nowLine || (slotLabel <= nowLine && nextSlot && nextSlot > nowLine)));
        return `
        <div class="cx-appt-row ${isNow ? "is-now" : ""}">
          <div class="cx-appt-row__time">${window.FinoraTime.clock(slotLabel)}</div>
          ${doctors
            .map((doc) => {
              const cell = appts.filter(
                (a) => a.doctor_id === doc.id && (a.start_time || "").slice(0, 5) === slotLabel
              );
              return `<div class="cx-appt-cell" data-empty-date="${ctx.esc(state.day)}" data-empty-time="${slotLabel}" data-empty-doctor="${doc.id}">
                ${cell.map((a) => apptCardHtml(a, ctx)).join("")}
                ${cell.length ? "" : '<button type="button" class="cx-appt-empty-add" aria-label="إضافة موعد"><i class="fa fa-plus"></i><span>إضافة موعد</span></button>'}
              </div>`;
            })
            .join("")}
        </div>`;
      })
      .join("");

    return `
      <div class="cx-appt-day-wrap">
        ${doctorSelectorHtml(allDoctors, prefs, ctx)}
        <div class="cx-appt-day ${layoutClass}" style="--cx-appt-doctors:${Math.max(doctors.length, 1)};--cx-appt-slot-height:${slot <= 15 ? 28 : 44}px">
          <div class="cx-appt-day__head">
            <div class="cx-appt-day__time-head">الوقت</div>${head || '<div class="cx-appt-dochead"><span class="cx-appt-dochead__info"><strong>لا يوجد أطباء</strong></span></div>'}
          </div>
          <div class="cx-appt-day__grid" data-slot-min="${slot}" data-slot-start="8" data-slot-end="20">
            ${isToday ? '<div class="cx-appt-now-line" id="cxApptNowLine" aria-hidden="true"></div>' : ""}
            ${doctors.length ? rows : '<div class="cx-empty" style="margin:20px">اختر طبيباً من الشريط أعلاه</div>'}
          </div>
          <div class="cx-appt-agenda">
            ${agendaAppts.length
              ? agendaAppts.map((a) => `
                <button type="button" class="cx-appt-agenda__item cx-appt-card--${statusClass(a.status)}" data-appt-pick="${a.id}" data-finora-action="${openAction(a.status)}">
                  <time>${ctx.esc(window.FinoraTime.clock(a.start_time))}</time>
                  <span><strong>${ctx.esc(a.patient_name)}</strong><small>${ctx.esc(a.doctor_name || "")} · ${ctx.esc(a.service_name || "")}</small></span>
                  ${ctx.badge(a.status)}
                </button>`).join("")
              : `<div class="cx-empty">لا توجد مواعيد <button type="button" class="cx-link-btn cx-appt-empty-mobile">+ إضافة موعد</button></div>`}
          </div>
        </div>
      </div>`;
  }

  function weekGrid(data, state, ctx) {
    const start = data.start;
    const end = data.end;
    const days = [];
    for (let cur = start; cur <= end; cur = addDays(cur, 1)) days.push(cur);
    const rows = data.appointments || [];
    const hours = Array.from({ length: 12 }, (_, i) => 8 + i);
    return `
      <article class="cx-card cx-cal">
        <div class="cx-cal__grid" style="grid-template-columns:64px repeat(${days.length},minmax(100px,1fr))">
          <div class="cx-cal__corner"></div>
          ${days.map((d) => `<div class="cx-cal__dayhead">${ctx.esc(d)}</div>`).join("")}
          ${hours
            .map((h) => {
              const label = String(h).padStart(2, "0") + ":00";
              return `<div class="cx-cal__hour">${label}</div>${days
                .map((d) => {
                  const cell = rows.filter(
                    (a) => a.appointment_date === d && (a.start_time || "").startsWith(String(h).padStart(2, "0"))
                  );
                  return `<div class="cx-cal__cell" data-drop-date="${d}" data-drop-hour="${h}">${cell
                    .map(
                      (a) =>
                        `<button type="button" class="cx-cal__event cx-appt-card--${statusClass(a.status)}" draggable="true" data-appt-drag="${a.id}" data-date="${ctx.esc(a.appointment_date)}" data-time="${ctx.esc(a.start_time)}" data-appt-pick="${a.id}" style="border-color:${ctx.esc(a.doctor_color || "#0d9488")}" title="${ctx.esc(a.patient_name)} · ${ctx.esc(a.patient_phone || "")} · ${ctx.esc(a.service_name || "")}">
                          <b>${ctx.esc(window.FinoraTime.clock(a.start_time))}</b><strong>${ctx.esc(a.patient_name)}</strong><small>${ctx.esc(a.dental_label || a.service_name || "")}${!a.dental_label && a.tooth_number ? ` · السن ${ctx.esc(a.tooth_number)}` : ""} · ${a.duration_minutes || 30}د</small>
                        </button>`
                    )
                    .join("")}</div>`;
                })
                .join("")}`;
            })
            .join("")}
        </div>
      </article>`;
  }

  function monthGrid(data, state, ctx) {
    const rows = data.appointments || [];
    const current = new Date(state.day + "T12:00:00");
    const first = new Date(current.getFullYear(), current.getMonth(), 1, 12);
    const last = new Date(current.getFullYear(), current.getMonth() + 1, 0, 12);
    const startOffset = (first.getDay() + 6) % 7;
    const cells = [];
    for (let i = 0; i < startOffset; i += 1) cells.push(null);
    for (let day = 1; day <= last.getDate(); day += 1) {
      const iso = `${first.getFullYear()}-${String(first.getMonth() + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      cells.push({ day, iso, appointments: rows.filter((a) => a.appointment_date === iso) });
    }
    while (cells.length % 7) cells.push(null);
    return `
      <article class="cx-appt-month">
        <div class="cx-appt-month__weekdays">${["الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد"].map((d) => `<span>${d}</span>`).join("")}</div>
        <div class="cx-appt-month__grid">
          ${cells.map((cell) => {
            if (!cell) return '<div class="cx-appt-month__day is-empty"></div>';
            const free = Math.max(0, (data.doctors || []).length * 8 - cell.appointments.length);
            return `<button type="button" class="cx-appt-month__day ${cell.iso === localToday() ? "is-today" : ""}" data-month-date="${cell.iso}">
              <b>${cell.day}</b>
              <strong>${cell.appointments.length} موعد</strong>
              <small>${free} متاح</small>
            </button>`;
          }).join("")}
        </div>
      </article>`;
  }

  function buildHtml(data, state, ctx) {
    const view = state.apptView || "day";
    const branches = data.branches || [];
    const doctors = data.doctors || [];
    const services = data.services || [];
    const hasFilters = state.doctorFilter || state.statusFilter || state.serviceFilter || state.branchFilter;

    return `
      <div class="cx-appt">
        <header class="cx-appt-header">
          <div class="cx-appt-header__title">
            <span class="cx-appt-header__mark"><i class="fa fa-calendar-check"></i></span>
            <div><h1>المواعيد</h1><small>إدارة وجدولة مواعيد العيادة</small></div>
          </div>
          <div class="cx-appt-header__search cx-dash-header__search">
            <i class="fa fa-search" aria-hidden="true"></i>
            <input type="search" class="cx-input" id="cxApptSearch" placeholder="ابحث عن مريض أو هاتف أو رقم ملف…">
            <kbd>Ctrl K</kbd>
            <div class="cx-search-results" id="cxApptSearchResults" hidden></div>
          </div>
          <div class="cx-appt-header__account">
            <button type="button" class="cx-icon-btn cx-appt-notifications" aria-label="الإشعارات"><i class="fa fa-bell"></i><span></span></button>
            <span class="cx-appt-user">
              ${ctx.data?.user?.avatar
                ? `<img src="${ctx.esc(ctx.data.user.avatar)}" alt="">`
                : '<i class="fa fa-user"></i>'}
              <span><b>${ctx.esc(ctx.data?.user?.name || "المستخدم")}</b><small>${ctx.esc(ctx.data?.user?.role_label || "")}</small></span>
            </span>
          </div>
        </header>

        <div class="cx-appt-toolbar">
          <div class="cx-appt-nav">
            <button type="button" class="cx-icon-btn" id="cxApptPrev" aria-label="السابق"><i class="fa fa-chevron-right"></i></button>
            <span class="cx-appt-nav__date">${fmtDay(state.day)}</span>
            <button type="button" class="cx-icon-btn" id="cxApptNext" aria-label="التالي"><i class="fa fa-chevron-left"></i></button>
            <button type="button" class="cx-btn cx-btn--ghost" id="cxApptToday">اليوم</button>
          </div>
          <div class="cx-appt-views" role="group" aria-label="طريقة العرض">
            ${VIEWS.map((v) => `
              <button type="button" class="${view === v.key ? "is-active" : ""}" data-appt-view="${v.key}">${v.label}</button>`).join("")}
          </div>
          <button type="button" class="cx-btn cx-appt-filter-toggle" id="cxApptFilterToggle">
            <i class="fa fa-filter"></i> الفلاتر
          </button>
          <div class="cx-appt-filters">
          <select class="cx-select" id="cxApptDoctor" aria-label="الطبيب">
            <option value="">كل الأطباء</option>
            ${doctors.map((d) => `<option value="${d.id}" ${String(state.doctorFilter) === String(d.id) ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`).join("")}
          </select>
          <select class="cx-select" id="cxApptStatus">
            <option value="">كل الحالات</option>
            ${(ctx.bootstrap?.statuses || []).map((s) => `<option value="${s}" ${state.statusFilter === s ? "selected" : ""}>${ctx.statusLabel(s)}</option>`).join("")}
          </select>
          <select class="cx-select" id="cxApptService">
            <option value="">كل الخدمات</option>
            ${services.map((s) => `<option value="${s.id}" ${String(state.serviceFilter) === String(s.id) ? "selected" : ""}>${ctx.esc(s.name)}</option>`).join("")}
          </select>
          ${branches.length > 1 ? `
          <select class="cx-select" id="cxApptBranch">
            <option value="">كل الفروع</option>
            ${branches.map((b) => `<option value="${b.id}" ${String(state.branchFilter) === String(b.id) ? "selected" : ""}>${ctx.esc(b.name)}</option>`).join("")}
          </select>` : ""}
          ${hasFilters ? `<button type="button" class="cx-btn cx-btn--ghost" id="cxApptClearFilters">مسح الفلاتر</button>` : ""}
          </div>
          <button type="button" class="cx-btn cx-btn--primary" id="cxApptNew" data-finora-action="appointment.create"><i class="fa fa-plus"></i> موعد جديد</button>
        </div>

        <div class="cx-appt-kpis">${kpiRow(data.stats)}</div>

        <div class="cx-appt-drawer-backdrop" id="cxApptDrawerBackdrop" hidden></div>
        <div class="cx-appt-body">
          <div class="cx-appt-main">
            ${view === "day" ? dayTimeline(data, state, ctx) : ""}
            ${view === "list" ? listTable(data, ctx) : ""}
            ${view === "week" ? weekGrid(data, state, ctx) : ""}
            ${view === "month" ? monthGrid(data, state, ctx) : ""}
          </div>
          <aside class="cx-appt-drawer" id="cxApptDrawer" data-finora-section="appointment.drawer" hidden aria-label="تفاصيل الموعد">
            <div class="cx-appt-drawer__head">
              <h3>تفاصيل الموعد</h3>
              <button type="button" class="cx-icon-btn" id="cxApptDrawerClose" aria-label="إغلاق"><i class="fa fa-xmark"></i></button>
            </div>
            <div class="cx-appt-drawer__body" id="cxApptDrawerBody"></div>
          </aside>
        </div>
      </div>`;
  }

  function closeAllMenus(root) {
    root.querySelectorAll(".cx-rec-menu").forEach((m) => m.classList.remove("is-open"));
    root.querySelectorAll("[data-appt-menu]").forEach((b) => {
      b.setAttribute("aria-expanded", "false");
      b.classList.remove("is-open");
    });
  }

  function openApptMenu(btn, menu) {
    const isOpen = menu.classList.contains("is-open");
    closeAllMenus(btn.closest("#cxRoot") || document);
    if (!isOpen) {
      menu.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      btn.classList.add("is-open");
    }
  }

  async function setStatus(ctx, id, status, toast) {
    await ctx.api(`/clinics/api/appointments/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    if (toast) ctx.showNotice(toast, false);
    await ctx.refresh({ silent: true });
  }

  function closeDrawer() {
    const drawer = document.getElementById("cxApptDrawer");
    const backdrop = document.getElementById("cxApptDrawerBackdrop");
    if (drawer) drawer.hidden = true;
    if (backdrop) backdrop.hidden = true;
    selectedApptId = null;
    (apptRoot || document).querySelectorAll(".cx-appt-card.is-selected, tr.is-selected").forEach((el) => {
      el.classList.remove("is-selected");
    });
  }

  function openDrawer(ctx, appt) {
    const drawer = document.getElementById("cxApptDrawer");
    const backdrop = document.getElementById("cxApptDrawerBackdrop");
    const body = document.getElementById("cxApptDrawerBody");
    if (!drawer || !body || !appt) return;
    selectedApptId = appt.id;
    drawer.hidden = false;
    const useOverlay = window.matchMedia("(max-width: 1100px)").matches;
    if (backdrop) backdrop.hidden = !useOverlay;
    body.innerHTML = drawerBodyHtml(appt, ctx);
    bindDrawerActions(body, ctx);
    ctx.api(`/clinics/api/patients/${appt.patient_id}`).then((data) => {
      if (String(selectedApptId) !== String(appt.id)) return;
      const patient = data.patient || {};
      const enriched = {
        ...appt,
        patient_file: patient.file_number || appt.patient_file,
        patient_phone: patient.phone || appt.patient_phone,
        patient_age: patient.age || appt.patient_age,
        patient_gender: patient.gender || "",
      };
      body.innerHTML = drawerBodyHtml(enriched, ctx);
      bindDrawerActions(body, ctx);
    }).catch(() => {});
    const host = apptRoot || document.getElementById("cxRoot") || document;
    host.querySelectorAll(".cx-appt-card.is-selected, tr.is-selected").forEach((el) => el.classList.remove("is-selected"));
    host.querySelectorAll(`[data-appt-pick="${appt.id}"], [data-appt-row="${appt.id}"]`).forEach((el) => {
      el.classList.add("is-selected");
    });
  }

  let apptRoot = null;

  function positionNowLine(root) {
    const grid = root.querySelector(".cx-appt-day__grid");
    const line = root.querySelector("#cxApptNowLine");
    if (!grid || !line) return;
    const slotMin = parseInt(grid.dataset.slotMin || "30", 10);
    const startH = parseInt(grid.dataset.slotStart || "8", 10);
    const endH = parseInt(grid.dataset.slotEnd || "20", 10);
    const now = new Date();
    const mins = now.getHours() * 60 + now.getMinutes();
    const startMins = startH * 60;
    const endMins = endH * 60;
    if (mins < startMins || mins > endMins) {
      line.style.display = "none";
      return;
    }
    const rows = grid.querySelectorAll(".cx-appt-row");
    if (!rows.length) return;
    const rowH = rows[0].offsetHeight || 52;
    const offsetMins = mins - startMins;
    const top = (offsetMins / slotMin) * rowH;
    line.style.display = "block";
    line.style.top = `${Math.round(top)}px`;
    const label = line.querySelector(".cx-appt-now-line__label");
    const timeStr = window.FinoraTime.time(now);
    if (label) label.textContent = timeStr;
    else line.innerHTML = `<span class="cx-appt-now-line__label">${timeStr}</span>`;
  }

  function startLiveNowLine(root) {
    if (root._nowLineTimer) clearInterval(root._nowLineTimer);
    positionNowLine(root);
    root._nowLineTimer = setInterval(() => positionNowLine(root), 60000);
  }

  function doReschedule(ctx, id, date, time) {
    const appt = (ctx.data?.appointments || []).find((x) => String(x.id) === String(id));
    ctx.openModal(
      "إعادة جدولة الموعد",
      `<p><strong>${ctx.esc(appt?.patient_name || "الموعد")}</strong></p>
       <p class="cx-muted">الموعد الحالي: ${ctx.esc(date)} ${ctx.esc(time)}</p>
       <div class="cx-field"><label>التاريخ الجديد</label><input class="cx-input" type="date" id="rs_date" value="${ctx.esc(date)}"></div>
       <div class="cx-field"><label>الوقت</label><input class="cx-input" type="time" id="rs_time" value="${ctx.esc(time)}"></div>
       <div class="cx-field"><label>الأوقات المتاحة</label><div class="cx-slot-chips" id="rs_slots"><span class="cx-muted">جاري التحميل…</span></div></div>
       <p class="cx-muted">سيتم التحقق من التعارض قبل الحفظ.</p>`,
      async () => {
        await ctx.api(`/clinics/api/appointments/${id}/reschedule`, {
          method: "POST",
          body: JSON.stringify({
            appointment_date: document.getElementById("rs_date").value,
            start_time: document.getElementById("rs_time").value,
          }),
        });
        await ctx.refresh({ silent: true });
      },
      { skipRender: true, successMessage: "تمت إعادة الجدولة" }
    );

    const loadSlots = async () => {
      const box = document.getElementById("rs_slots");
      const dateInput = document.getElementById("rs_date");
      if (!box || !dateInput || !appt?.doctor_id) {
        if (box) box.innerHTML = '<span class="cx-muted">اختر تاريخاً</span>';
        return;
      }
      box.innerHTML = '<span class="cx-muted">جاري التحميل…</span>';
      try {
        const qs = new URLSearchParams({
          date: dateInput.value,
          doctor_id: appt.doctor_id,
          exclude_id: id,
        });
        if (appt.service_id) qs.set("service_id", appt.service_id);
        const data = await ctx.api(`/clinics/api/appointments/slots?${qs}`);
        const slots = data.slots || [];
        if (!slots.length) {
          box.innerHTML = '<span class="cx-muted">لا أوقات متاحة</span>';
          return;
        }
        box.innerHTML = slots
          .map(
            (t) =>
              `<button type="button" class="cx-slot-chip" data-slot-time="${ctx.esc(t)}">${ctx.esc(t)}</button>`
          )
          .join("");
        box.querySelectorAll(".cx-slot-chip").forEach((chip) => {
          chip.onclick = () => {
            document.getElementById("rs_time").value = chip.dataset.slotTime;
            box.querySelectorAll(".cx-slot-chip").forEach((c) => c.classList.remove("is-active"));
            chip.classList.add("is-active");
          };
        });
      } catch (err) {
        box.innerHTML = `<span class="cx-muted">${ctx.esc(err.message || "تعذر جلب الأوقات")}</span>`;
      }
    };

    setTimeout(() => {
      const dateInput = document.getElementById("rs_date");
      if (dateInput) {
        dateInput.addEventListener("change", loadSlots);
        loadSlots();
      }
    }, 0);
  }

  function bindDocBar(root, state, ctx) {
    const bar = root.querySelector("#cxApptDocBar");
    if (!bar) return;

    const refreshDayOnly = () => {
      const main = root.querySelector(".cx-appt-main");
      if (!main || !ctx.data) return;
      const view = state.apptView || "day";
      if (view !== "day") return;
      main.innerHTML = dayTimeline(ctx.data, state, ctx);
      bindActions(root, state, ctx);
      startLiveNowLine(root);
      if (selectedApptId) {
        const appt = (ctx.data.appointments || []).find((x) => String(x.id) === String(selectedApptId));
        if (appt) openDrawer(ctx, appt);
      }
    };

    bar.querySelectorAll("[data-doc-mode]").forEach((btn) => {
      btn.onclick = () => {
        const prefs = loadDocPrefs();
        prefs.mode = btn.dataset.docMode === "single" ? "single" : "all";
        if (prefs.mode === "single" && prefs.selected.length > 1) {
          prefs.selected = [prefs.selected[0]];
        }
        saveDocPrefs(prefs);
        refreshDayOnly();
      };
    });

    bar.querySelectorAll("[data-doc-chip]").forEach((btn) => {
      btn.onclick = () => {
        const prefs = loadDocPrefs();
        const id = String(btn.dataset.docChip);
        if (prefs.mode === "single") {
          prefs.selected = [id];
        } else {
          const set = new Set(prefs.selected.map(String));
          if (set.has(id)) {
            if (set.size <= 1) return;
            set.delete(id);
          } else {
            set.add(id);
          }
          prefs.selected = Array.from(set);
        }
        saveDocPrefs(prefs);
        refreshDayOnly();
      };
    });
  }

  function bindActions(root, state, ctx) {
    root.querySelectorAll("[data-appt-pick]").forEach((el) => {
      el.onclick = () => {
        const a = (ctx.data?.appointments || []).find((x) => String(x.id) === String(el.dataset.apptPick));
        if (a) openDrawer(ctx, a);
      };
    });

    bindDocBar(root, state, ctx);
    root.querySelectorAll(".cx-appt-empty-add").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const cell = btn.closest("[data-empty-time]");
        ctx.promptNewAppointment();
        setTimeout(() => {
          const date = document.getElementById("f_date");
          const time = document.getElementById("f_time");
          const doctor = document.getElementById("f_doctor_id");
          if (date) date.value = cell?.dataset.emptyDate || state.day;
          if (time) time.value = cell?.dataset.emptyTime || "";
          if (doctor && cell?.dataset.emptyDoctor) doctor.value = cell.dataset.emptyDoctor;
        }, 0);
      };
    });
    root.querySelectorAll(".cx-appt-empty-mobile").forEach((btn) => {
      btn.onclick = () => ctx.promptNewAppointment();
    });

    root.querySelectorAll("[data-month-date]").forEach((btn) => {
      btn.onclick = () => {
        state.day = btn.dataset.monthDate;
        state.apptView = "day";
        sessionStorage.setItem("cx-appt-view", "day");
        ctx.refresh();
      };
    });

    root.querySelectorAll("[data-appt-menu]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = document.getElementById(btn.dataset.apptMenu);
        if (menu) openApptMenu(btn, menu);
      };
    });

    root.querySelectorAll("[data-appt-menu-act]").forEach((btn) => {
      btn.onclick = async () => {
        closeAllMenus(root);
        const id = btn.dataset.id;
        const act = btn.dataset.apptMenuAct;
        try {
          if (act === "reschedule") {
            doReschedule(ctx, id, btn.dataset.date, btn.dataset.time);
            return;
          }
          if (act === "arrived") {
            await setStatus(ctx, id, "arrived", "تم تسجيل الوصول");
            return;
          }
          if (act === "cancel") {
            if (!confirm("إلغاء الموعد؟")) return;
            await setStatus(ctx, id, "cancelled", "تم الإلغاء");
            return;
          }
          if (act === "no_show") {
            if (!confirm("تسجيل لم يحضر؟")) return;
            await setStatus(ctx, id, "no_show", "تم تسجيل عدم الحضور");
            return;
          }
          if (act === "note") {
            ctx.openModal("ملاحظة", `<textarea class="cx-input" id="appt_note" rows="4"></textarea>`, async () => {
              await ctx.api(`/clinics/api/appointments/${id}`, {
                method: "PATCH",
                body: JSON.stringify({ notes: document.getElementById("appt_note").value }),
              });
              await ctx.refresh({ silent: true });
            }, { skipRender: true });
          }
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      };
    });

    bindWeekDragDrop(root, ctx);
    const exportBtn = document.getElementById("cxApptExport");
    if (exportBtn) {
      exportBtn.onclick = () => exportCsv(ctx.data?.appointments || [], ctx);
    }
    const pagePrev = document.getElementById("cxApptPagePrev");
    const pageNext = document.getElementById("cxApptPageNext");
    if (pagePrev) {
      pagePrev.onclick = () => {
        if (listPage > 1) {
          listPage -= 1;
          ctx.refresh({ silent: true });
        }
      };
    }
    if (pageNext) {
      pageNext.onclick = () => {
        const total = (ctx.data?.appointments || []).length;
        const pages = Math.max(1, Math.ceil(total / LIST_PAGE_SIZE));
        if (listPage < pages) {
          listPage += 1;
          ctx.refresh({ silent: true });
        }
      };
    }
  }

  function bindWeekDragDrop(root, ctx) {
    root.querySelectorAll(".cx-cal__event[draggable=true]").forEach((el) => {
      el.addEventListener("dragstart", (e) => {
        el.classList.add("is-dragging");
        e.dataTransfer.setData(
          "text/plain",
          JSON.stringify({
            id: el.dataset.apptDrag,
            date: el.dataset.date,
            time: el.dataset.time,
          })
        );
        e.dataTransfer.effectAllowed = "move";
      });
      el.addEventListener("dragend", () => el.classList.remove("is-dragging"));
    });

    root.querySelectorAll(".cx-cal__cell[data-drop-date]").forEach((cell) => {
      cell.addEventListener("dragover", (e) => {
        e.preventDefault();
        cell.classList.add("is-over");
      });
      cell.addEventListener("dragleave", () => cell.classList.remove("is-over"));
      cell.addEventListener("drop", async (e) => {
        e.preventDefault();
        cell.classList.remove("is-over");
        try {
          const data = JSON.parse(e.dataTransfer.getData("text/plain") || "{}");
          const newDate = cell.dataset.dropDate;
          const newTime = String(cell.dataset.dropHour).padStart(2, "0") + ":00";
          if (!data.id) return;
          if (data.date === newDate && data.time === newTime) return;
          if (!confirm(`نقل الموعد إلى ${newDate} ${newTime}؟`)) return;
          await ctx.api(`/clinics/api/appointments/${data.id}/reschedule`, {
            method: "POST",
            body: JSON.stringify({ appointment_date: newDate, start_time: newTime }),
          });
          ctx.showNotice("تمت إعادة الجدولة", false);
          await ctx.refresh({ silent: true });
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      });
    });
  }

  function bindUI(root, state, ctx) {
    if (!root._apptMenuDismiss) {
      root._apptMenuDismiss = true;
      document.addEventListener("click", (e) => {
        if (!e.target.closest(".cx-rec-menu-wrap")) closeAllMenus(root);
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          closeAllMenus(root);
          closeDrawer();
        }
      });
    }

    const bindClick = (id, fn) => {
      const el = document.getElementById(id);
      if (el) el.onclick = fn;
    };
    const bindChange = (id, fn) => {
      const el = document.getElementById(id);
      if (el) el.onchange = fn;
    };

    bindClick("cxApptPrev", () => {
      const step = state.apptView === "month" ? 30 : state.apptView === "week" ? 7 : 1;
      state.day = addDays(state.day, -step);
      ctx.refresh();
    });
    bindClick("cxApptNext", () => {
      const step = state.apptView === "month" ? 30 : state.apptView === "week" ? 7 : 1;
      state.day = addDays(state.day, step);
      ctx.refresh();
    });
    bindClick("cxApptToday", () => {
      state.day = localToday();
      ctx.refresh();
    });
    bindClick("cxApptFilterToggle", () => {
      root.querySelector(".cx-appt-filters")?.classList.toggle("is-open");
    });
    root.querySelectorAll("[data-appt-view]").forEach((btn) => {
      btn.onclick = () => {
        state.apptView = btn.dataset.apptView;
        sessionStorage.setItem("cx-appt-view", state.apptView);
        ctx.refresh();
      };
    });
    bindChange("cxApptDoctor", (e) => {
      state.doctorFilter = e.target.value;
      ctx.refresh();
    });
    bindChange("cxApptStatus", (e) => {
      state.statusFilter = e.target.value;
      ctx.refresh();
    });
    bindChange("cxApptService", (e) => {
      state.serviceFilter = e.target.value;
      ctx.refresh();
    });
    bindChange("cxApptBranch", (e) => {
      state.branchFilter = e.target.value;
      ctx.refresh();
    });
    bindClick("cxApptClearFilters", () => {
      state.doctorFilter = "";
      state.statusFilter = "";
      state.serviceFilter = "";
      state.branchFilter = "";
      ctx.refresh();
    });
    bindClick("cxApptNew", () => ctx.promptNewAppointment());

    const search = document.getElementById("cxApptSearch");
    const results = document.getElementById("cxApptSearchResults");
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
            parts.push(`<a href="${a.href}" class="cx-search-item"><i class="fa fa-calendar"></i><span>${ctx.esc(a.patient_name)} · ${ctx.esc(a.date)}</span></a>`);
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

    if (!root._apptSearchShortcut) {
      root._apptSearchShortcut = true;
      document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          root.querySelector("#cxApptSearch")?.focus();
        }
      });
    }

    bindActions(root, state, ctx);
    bindClick("cxApptDrawerClose", closeDrawer);
    const backdrop = document.getElementById("cxApptDrawerBackdrop");
    if (backdrop) backdrop.onclick = closeDrawer;
    if ((state.apptView || "day") === "day") startLiveNowLine(root);
  }

  let pollTimer = null;
  let lastPulse = null;

  function startPulse(state, rootEl, helpers, ctxRef) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const qs = buildQs(state);
        const data = await helpers.api(`/clinics/api/appointments/board?${qs}`);
        if (lastPulse && data.pulse_version === lastPulse) return;
        lastPulse = data.pulse_version;
        ctxRef.data = data;
        const main = rootEl.querySelector(".cx-appt-main");
        const kpis = rootEl.querySelector(".cx-appt-kpis");
        if (kpis) kpis.innerHTML = kpiRow(data.stats);
        if (main) {
          const view = state.apptView || "day";
          if (view === "day") main.innerHTML = dayTimeline(data, state, ctxRef);
          else if (view === "week") main.innerHTML = weekGrid(data, state, ctxRef);
          else if (view === "month") main.innerHTML = monthGrid(data, state, ctxRef);
          else main.innerHTML = listTable(data, ctxRef);
          bindActions(rootEl, state, ctxRef);
          if ((state.apptView || "day") === "day") startLiveNowLine(rootEl);
          if (selectedApptId) {
            const appt = data.appointments.find((x) => String(x.id) === String(selectedApptId));
            if (appt) openDrawer(ctxRef, appt);
          }
        }
      } catch {
        /* ignore */
      }
    }, 15000);
  }

  function buildQs(state) {
    const qs = new URLSearchParams({ date: state.day, view: state.apptView || "day" });
    if (state.doctorFilter) qs.set("doctor_id", state.doctorFilter);
    if (state.statusFilter) qs.set("status", state.statusFilter);
    if (state.serviceFilter) qs.set("service_id", state.serviceFilter);
    if (state.branchFilter) qs.set("branch_id", state.branchFilter);
    return qs;
  }

  async function render(state, rootEl, helpers, opts = {}) {
    apptRoot = rootEl;
    if (!opts.silent) rootEl.innerHTML = `<div class="cx-appt"><div class="cx-skeleton-block" style="height:480px;border-radius:18px"></div></div>`;
    try {
      if (!state.apptView) {
        state.apptView = sessionStorage.getItem("cx-appt-view") || "day";
      }
      const data = await helpers.api(`/clinics/api/appointments/board?${buildQs(state)}`);
      if (data.user) helpers.bootstrap.user = data.user;
      lastPulse = data.pulse_version;
      const ctx = {
        ...helpers,
        data,
        bootstrap: helpers.bootstrap,
        refresh: (o) => render(state, rootEl, helpers, o),
      };
      if (opts.silent && rootEl.querySelector(".cx-appt")) {
        const main = rootEl.querySelector(".cx-appt-main");
        const kpis = rootEl.querySelector(".cx-appt-kpis");
        if (kpis) kpis.innerHTML = kpiRow(data.stats);
        if (main) {
          const view = state.apptView || "day";
          if (view === "day") main.innerHTML = dayTimeline(data, state, ctx);
          else if (view === "week") main.innerHTML = weekGrid(data, state, ctx);
          else if (view === "month") main.innerHTML = monthGrid(data, state, ctx);
          else main.innerHTML = listTable(data, ctx);
          bindActions(rootEl, state, ctx);
          if (view === "day") startLiveNowLine(rootEl);
          if (selectedApptId) {
            const appt = data.appointments.find((x) => String(x.id) === String(selectedApptId));
            if (appt) openDrawer(ctx, appt);
          }
        }
      } else {
        rootEl.innerHTML = buildHtml(data, state, ctx);
        bindUI(rootEl, state, ctx);
        startPulse(state, rootEl, helpers, ctx);
      }
      return ctx;
    } catch (err) {
      if (!opts.silent) {
        rootEl.innerHTML = `<div class="cx-empty">تعذر تحميل المواعيد: ${helpers.esc(err.message || String(err))}</div>`;
      }
      throw err;
    }
  }

  window.ClinicsAppointments = { render };
})();
