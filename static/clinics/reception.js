/**
 * Finora Clinics — Reception Operations Center
 */
(() => {
  const COLS = [
    { key: "upcoming", title: "قادم", listKey: "upcoming" },
    { key: "waiting", title: "وصل / ينتظر", listKey: "waiting" },
    { key: "in_consultation", title: "عند الطبيب", listKey: "in_consultation" },
    { key: "checkout", title: "جاهز للخروج", listKey: "checkout" },
  ];

  function can(ctx, perm) {
    const u = ctx.bootstrap?.user || ctx.data?.user || {};
    if (u.role === "admin") return true;
    return (u.permissions || []).includes(perm);
  }

  function waitLabel(mins, level) {
    const cls = level || "ok";
    const text = mins <= 0 ? "الآن" : `${mins} دقيقة`;
    return `<span class="cx-rec-wait cx-rec-wait--${cls}">${text}</span>`;
  }

  function genderLabel(g) {
    if (g === "male" || g === "m") return "ذكر";
    if (g === "female" || g === "f") return "أنثى";
    return g || "—";
  }

  function findAppt(ctx, id) {
    for (const key of ["upcoming", "waiting", "in_consultation", "checkout"]) {
      const row = (ctx.data?.[key] || []).find((x) => String(x.id) === String(id));
      if (row) return row;
    }
    return null;
  }

  function doctorStatus(ctx, doctorId) {
    return (ctx.data?.doctors_status || []).find((d) => String(d.doctor_id) === String(doctorId));
  }

  function lateBadge(mins) {
    if (!mins || mins <= 0) return "";
    const cls = mins >= 30 ? "alert" : "warn";
    return `<span class="cx-rec-late cx-rec-late--${cls}">متأخر ${mins} دقيقة</span>`;
  }

  function lateActions(a, ctx) {
    if ((a.late_minutes || 0) < 30) return "";
    const id = a.id;
    return `
      <div class="cx-rec-late-actions">
        <span>لم يحضر؟</span>
        <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-rec-act="arrived" data-id="${id}">تسجيل وصول</button>
        ${a.patient_phone ? `<a class="cx-btn cx-btn--sm" href="tel:${ctx.esc(a.patient_phone)}">اتصال</a>` : ""}
        <button type="button" class="cx-btn cx-btn--sm" data-rec-menu-act="no_show" data-id="${id}">لم يحضر</button>
        <button type="button" class="cx-btn cx-btn--sm" data-rec-menu-act="reschedule" data-id="${id}" data-date="${ctx.esc(a.appointment_date)}" data-time="${ctx.esc(a.start_time)}">إعادة جدولة</button>
      </div>`;
  }

  function primaryBtn(a, col, ctx) {
    const id = a.id;
    if (col === "upcoming") {
      return `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-rec-act="arrived" data-id="${id}">تسجيل وصول</button>`;
    }
    if (col === "waiting") {
      return `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-rec-act="start" data-id="${id}">إدخال للطبيب</button>`;
    }
    if (col === "in_consultation") {
      if (a.visit_id) {
        return `<a class="cx-btn cx-btn--sm cx-btn--primary" href="/clinics/doctor/${a.visit_id}">فتح الزيارة</a>`;
      }
      return `<button type="button" class="cx-btn cx-btn--sm" data-rec-act="start" data-id="${id}">بدء زيارة</button>`;
    }
    if (col === "checkout") {
      const bal = a.invoice_balance || 0;
      if (can(ctx, "clinics_billing") && a.invoice_id && bal > 0) {
        return `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-rec-pay="${a.invoice_id}" data-appt="${id}">تحصيل ${ctx.money(bal)}</button>`;
      }
      if (a.payment_status === "paid" || bal <= 0) {
        return `<a class="cx-btn cx-btn--sm" href="/clinics/billing">فاتورة</a>`;
      }
      return `<a class="cx-btn cx-btn--sm cx-btn--primary" href="/clinics/patients/${a.patient_id}">إنهاء</a>`;
    }
    return "";
  }

  function cardMenuHtml(a, col, ctx, isEmerg, menuId) {
    const id = a.id;
    const item = (act, label, icon, extra = "", danger = false) =>
      `<button type="button" class="cx-rec-menu__item ${danger ? "is-danger" : ""}" role="menuitem"
        data-rec-menu-act="${act}" data-id="${id}" ${extra}>
        <span class="cx-rec-menu__icon"><i class="fa ${icon}"></i></span>
        <span class="cx-rec-menu__label">${label}</span>
      </button>`;
    const main = [
      item("reschedule", "إعادة جدولة", "fa-calendar-days", `data-date="${ctx.esc(a.appointment_date)}" data-time="${ctx.esc(a.start_time)}"`),
      item("note", "إضافة ملاحظة", "fa-note-sticky"),
    ];
    if (col === "waiting") {
      main.push(item("emergency", isEmerg ? "إلغاء طوارئ" : "تحديد طوارئ", "fa-bolt"));
    }
    const danger = [
      item("no_show", "لم يحضر", "fa-user-slash", "", true),
      item("cancel", "إلغاء الموعد", "fa-ban", "", true),
    ];
    return `
      <div class="cx-rec-menu-wrap">
        <button type="button" class="cx-icon-btn cx-icon-btn--more" data-rec-menu="${menuId}" title="المزيد" aria-haspopup="menu" aria-expanded="false">
          <i class="fa fa-ellipsis-vertical"></i>
        </button>
        <div class="cx-rec-menu" id="${menuId}" role="menu" aria-label="إجراءات الموعد">
          <div class="cx-rec-menu__head">إجراءات</div>
          <div class="cx-rec-menu__group">${main.join("")}</div>
          <div class="cx-rec-menu__divider" role="separator"></div>
          <div class="cx-rec-menu__group cx-rec-menu__group--danger">${danger.join("")}</div>
        </div>
      </div>`;
  }

  function cardHtml(a, col, ctx) {
    const menuId = `m-${col}-${a.id}`;
    const isEmerg = a.is_emergency || (a.queue_priority || 0) > 0;
    const drag = col === "waiting" && can(ctx, "clinics_reception");
    return `
      <article class="cx-rec-card ${isEmerg ? "is-emergency" : ""}" data-appt-id="${a.id}" data-col="${col}"
        data-arrived="${a.arrived_at || a.checked_in_at || ""}"
        data-visit-started="${a.visit_started_at || ""}"
        data-wait-mins="${a.wait_minutes || 0}" data-wait-level="${a.wait_level || "ok"}"
        ${drag ? `draggable="true" data-wait-id="${a.id}"` : ""}>
        <div class="cx-rec-card__top">
          <div class="cx-rec-card__time">
            ${col === "upcoming" ? `<strong>${ctx.esc(a.start_time || "—")}</strong> ${ctx.badge(a.status)}` : ""}
            ${col === "waiting" ? `<span>وصل ${ctx.esc((a.arrived_at || a.checked_in_at || "").slice(11, 16) || "—")}</span>` : ""}
            ${col === "in_consultation" ? `<span>بدأ ${ctx.esc((a.visit_started_at || "").slice(11, 16) || "—")}</span>` : ""}
            ${col === "checkout" ? `<span>انتهت ${ctx.esc((a.visit_completed_at || "").slice(11, 16) || "—")}</span>` : ""}
          </div>
          <div class="cx-rec-card__badges">
            ${isEmerg ? '<span class="cx-rec-tag cx-rec-tag--em">طوارئ</span>' : ""}
            ${a.queue_number ? `<span class="cx-rec-tag">#${a.queue_number}</span>` : ""}
            ${lateBadge(a.late_minutes)}
          </div>
        </div>
        <button type="button" class="cx-rec-card__name" data-rec-drawer="${a.patient_id}" data-appt="${a.id}">${ctx.esc(a.patient_name)}</button>
        <div class="cx-rec-card__meta">
          <span><i class="fa fa-user-doctor"></i> ${ctx.esc(a.doctor_name || "—")}</span>
          ${a.patient_phone ? `<span><i class="fa fa-phone"></i> ${ctx.esc(a.patient_phone)}</span>` : ""}
          ${a.service_name || a.notes ? `<span><i class="fa fa-notes-medical"></i> ${ctx.esc(a.service_name || a.notes)}</span>` : ""}
        </div>
        ${col === "waiting" ? `<div class="cx-rec-card__wait" data-live-wait>${waitLabel(a.wait_minutes, a.wait_level)}</div>` : ""}
        ${col === "in_consultation" ? `<div class="cx-rec-card__wait" data-live-consult>${waitLabel(a.consultation_minutes || 0, (a.consultation_minutes || 0) > 60 ? "alert" : "ok")}</div>` : ""}
        ${col === "checkout" && can(ctx, "clinics_billing") ? `
        <div class="cx-rec-checkout">
          <span>المبلغ: <b class="cx-money">${ctx.money(a.invoice_total || 0)}</b></span>
          <span>المقبوض: <b class="cx-money">${ctx.money(a.invoice_paid || 0)}</b></span>
          <span class="cx-rec-pay-status ${a.payment_status === "paid" ? "is-paid" : ""}">${a.payment_status === "paid" ? "مدفوع ✓" : "بانتظار التحصيل"}</span>
        </div>` : ""}
        ${col === "upcoming" ? lateActions(a, ctx) : ""}
        <div class="cx-rec-card__foot">
          ${primaryBtn(a, col, ctx)}
          <div class="cx-rec-card__icons">
            <a class="cx-icon-btn" href="/clinics/patients/${a.patient_id}" title="الملف"><i class="fa fa-folder-open"></i></a>
            ${a.patient_phone ? `<a class="cx-icon-btn" href="tel:${ctx.esc(a.patient_phone)}" title="اتصال"><i class="fa fa-phone"></i></a>` : ""}
            ${cardMenuHtml(a, col, ctx, isEmerg, menuId)}
          </div>
        </div>
      </article>`;
  }

  function kpiRow(stats, ctx) {
    const s = stats || {};
    const cards = [
      { title: "مواعيد اليوم", value: s.appointments || 0, theme: "violet" },
      { title: "حضروا", value: s.arrived || 0, theme: "blue" },
      { title: "ينتظر", value: s.waiting || 0, theme: "amber", alert: (s.overdue_wait_count || 0) > 0 },
      { title: "عند الطبيب", value: s.in_consultation || 0, theme: "green" },
      { title: "مكتمل", value: s.completed || 0, theme: "teal" },
    ];
    if (ctx.data?.can_finance) {
      const rev = Number(s.revenue || 0);
      cards.push({
        title: "إيراد اليوم",
        value: new Intl.NumberFormat("ar-IQ").format(rev),
        unit: "د.ع",
        theme: "sky",
      });
    } else {
      cards.push({ title: "لم يحضر", value: s.no_show || 0, theme: "slate" });
    }
    return cards
      .map(
        (c) => `
      <article class="cx-rec-kpi cx-rec-kpi--${c.theme}${c.alert ? " is-alert" : ""}">
        <span>${c.title}</span>
        <strong>${c.value}${c.unit ? `<small>${c.unit}</small>` : ""}</strong>
      </article>`
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
        <div class="cx-notif-panel__list" id="cxNotifList">
          ${alertsListHtml(rows, ctx)}
        </div>
      </div>`;
  }

  function alertsListHtml(rows, ctx) {
    if (!rows.length) {
      return `<div class="cx-empty cx-empty--ok"><i class="fa fa-circle-check"></i> لا توجد تنبيهات حالياً</div>`;
    }
    return rows
      .map((a) => {
        const inner = `
          <i class="fa ${a.icon || "fa-bell"}"></i>
          <div>
            <strong>${ctx.esc(a.title || "")}${a.count ? ` <span class="cx-alert__count">${a.count}</span>` : ""}</strong>
            <span>${ctx.esc(a.description || "")}</span>
          </div>`;
        return a.href
          ? `<a class="cx-notif-item cx-notif-item--${a.severity || "info"}" href="${ctx.esc(a.href)}">${inner}</a>`
          : `<div class="cx-notif-item cx-notif-item--${a.severity || "info"}">${inner}</div>`;
      })
      .join("");
  }

  function syncNotif(root, alerts, ctx) {
    const btn = root.querySelector("#cxRecNotif");
    const list = root.querySelector("#cxNotifList");
    const head = root.querySelector(".cx-notif-panel__head span");
    const rows = alerts || [];
    if (list && ctx) list.innerHTML = alertsListHtml(rows, ctx);
    if (head) head.textContent = rows.length ? `${rows.length} عنصر` : "لا يوجد";
    if (!btn) return;
    const badge = btn.querySelector(".cx-badge-count");
    if (rows.length) {
      if (badge) badge.textContent = rows.length;
      else btn.insertAdjacentHTML("beforeend", `<span class="cx-badge-count">${rows.length}</span>`);
    } else if (badge) badge.remove();
  }

  function bindNotifPanel(root) {
    const btn = root.querySelector("#cxRecNotif");
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
        const b = root.querySelector("#cxRecNotif");
        if (!p || p.hidden) return;
        if (!p.contains(e.target) && !(b && b.contains(e.target))) {
          p.hidden = true;
          b?.setAttribute("aria-expanded", "false");
        }
      });
    }
  }

  function skeleton() {
    return `
      <div class="cx-rec">
        <div class="cx-skeleton-block" style="height:140px;border-radius:16px"></div>
        <div class="cx-rec-kpis">${Array(6).fill('<div class="cx-skeleton-block" style="height:92px;border-radius:16px"></div>').join("")}</div>
        <div class="cx-rec-board">${Array(4).fill('<div class="cx-skeleton-block" style="height:180px;border-radius:16px"></div>').join("")}</div>
      </div>`;
  }

  function buildHtml(data, state, ctx) {
    const clinic = data.clinic_status || {};
    const branches = data.branches || [];
    const doctors = data.doctors || [];
    const next = data.next_patient;
    const statusLabel = clinic.is_open ? "مفتوحة" : "مغلقة";
    const hours = clinic.hours_label ? ` • ${ctx.esc(clinic.hours_label)}` : "";

    return `
      <div class="cx-rec">
        <section class="cx-rec-panel">
          <div class="cx-rec-panel__head">
            <div>
              <span class="cx-rec-kicker">FINORA CLINICS</span>
              <h1>لوحة الاستقبال</h1>
            </div>
            <span class="cx-rec-status-pill ${clinic.is_open ? "is-open" : "is-closed"}">
              ${statusLabel}${hours}
              <i class="cx-rec-status-dot" aria-hidden="true"></i>
            </span>
          </div>
          <div class="cx-rec-header__search">
            <i class="fa fa-search"></i>
            <input type="search" class="cx-input" id="cxRecSearch" placeholder="بحث مريض، موعد، هاتف... (Ctrl+K)">
            <div class="cx-search-results" id="cxRecSearchResults" hidden></div>
          </div>
          <div class="cx-rec-panel__tools">
            <label class="cx-rec-day">
              <i class="fa fa-calendar"></i>
              <input type="date" class="cx-input" id="cxRecDay" value="${ctx.esc(state.day)}" aria-label="تاريخ الاستقبال">
            </label>
            <select class="cx-select" id="cxRecDoctor" aria-label="الطبيب">
              <option value="">كل الأطباء</option>
              ${doctors.map((d) => `<option value="${d.id}" ${String(d.id) === String(state.doctorFilter) ? "selected" : ""}>${ctx.esc(d.full_name)}</option>`).join("")}
            </select>
            ${branches.length > 1 ? `
            <select class="cx-select" id="cxRecBranch" aria-label="الفرع">
              <option value="">كل الفروع</option>
              ${branches.map((b) => `<option value="${b.id}" ${String(b.id) === String(state.branchFilter) ? "selected" : ""}>${ctx.esc(b.name)}</option>`).join("")}
            </select>` : ""}
            <button type="button" class="cx-btn cx-rec-add-btn" id="cxRecNewPatient" aria-label="مريض جديد" title="مريض جديد"><i class="fa fa-plus"></i><span>م</span></button>
            <button type="button" class="cx-btn cx-btn--primary" id="cxRecNewAppt"><i class="fa fa-calendar-plus"></i><span>موعد</span></button>
            <div class="cx-notif-wrap">
              <button type="button" class="cx-btn cx-btn--ghost" id="cxRecNotif" title="تنبيهات" aria-haspopup="dialog" aria-expanded="false">
                <i class="fa fa-bell"></i>
                ${(data.alerts || []).length ? `<span class="cx-badge-count">${(data.alerts || []).length}</span>` : ""}
              </button>
              ${alertsPanelHtml(data.alerts || [], ctx)}
            </div>
          </div>
        </section>

        <div class="cx-rec-kpis">${kpiRow(data.stats, ctx)}</div>

        ${(data.doctors_status || []).length ? `
        <section class="cx-rec-doctors">
          ${(data.doctors_status || []).map((d) => `
            <div class="cx-rec-doc ${d.available ? "is-free" : "is-busy"}">
              <div class="cx-rec-doc__name">
                <span class="cx-rec-doc__dot" aria-hidden="true"></span>
                <strong>${ctx.esc(d.doctor_name)}</strong>
              </div>
              ${d.available
              ? `<span class="cx-rec-doc__state">متاح • ${d.waiting_count || 0} ينتظر</span>`
              : `<span class="cx-rec-doc__state">مع ${ctx.esc(d.current_patient || "مريض")}</span>`}
            </div>`).join("")}
        </section>` : ""}

        <div class="cx-rec-layout">
          <div class="cx-rec-main">
            <section class="cx-rec-board">
              ${COLS.map((col) => {
                const items = data[col.listKey] || [];
                return `
                <div class="cx-rec-col" data-col="${col.key}">
                  <div class="cx-rec-col__head">
                    <h3>${col.title}</h3>
                    <span class="cx-col__count" data-col-count="${col.key}">${items.length}</span>
                  </div>
                  ${col.key === "waiting" ? '<div class="cx-rec-col__hint"><span>اسحب لإعادة الترتيب</span><i class="fa fa-grip"></i></div>' : ""}
                  <div class="cx-rec-col__body" data-col-body="${col.key}">
                    ${items.map((a) => cardHtml(a, col.key, ctx)).join("") || '<div class="cx-rec-empty">لا يوجد</div>'}
                  </div>
                </div>`;
              }).join("")}
            </section>

            <section class="cx-rec-bottom">
              <article class="cx-rec-next">
                <header class="cx-rec-next__head">
                  <h2>المريض التالي</h2>
                  <span class="cx-rec-next__badge">جاهز</span>
                </header>
                <div class="cx-rec-next__body" id="cxRecNext">
                  ${next ? `
                    <strong>${ctx.esc(next.patient_name)}</strong>
                    <p>${ctx.esc(next.doctor_name)} · انتظار ${next.wait_minutes || 0} د</p>
                    <p class="cx-muted">${ctx.esc(next.service_name || "")}</p>
                    <button type="button" class="cx-btn cx-btn--primary" data-rec-act="start" data-id="${next.appointment_id}">إدخال للطبيب</button>
                  ` : '<div class="cx-rec-empty">لا يوجد مرضى بانتظار النداء</div>'}
                </div>
              </article>
            </section>
          </div>

          <aside class="cx-rec-drawer" id="cxRecDrawer" hidden aria-label="تفاصيل المريض">
            <div class="cx-rec-drawer__head">
              <h3 id="cxRecDrawerTitle">المريض</h3>
              <button type="button" class="cx-icon-btn" id="cxRecDrawerClose"><i class="fa fa-xmark"></i></button>
            </div>
            <div class="cx-rec-drawer__body" id="cxRecDrawerBody"></div>
          </aside>
        </div>
      </div>`;
  }

  async function setStatus(ctx, id, status, toast) {
    await ctx.api(`/clinics/api/appointments/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    if (toast) ctx.showNotice(toast, false);
    await ctx.refresh({ silent: true });
  }

  async function confirmStartVisit(ctx, id, patientName) {
    const appt = findAppt(ctx, id);
    const doc = appt ? doctorStatus(ctx, appt.doctor_id) : null;
    const doctorName = appt?.doctor_name || "الطبيب";

    if (doc && !doc.available && doc.current_patient) {
      ctx.openModal(
        "الطبيب مشغول",
        `<p><strong>${ctx.esc(doctorName)}</strong> لديه مريض حالياً:</p>
         <p>${ctx.esc(doc.current_patient)}</p>
         <p class="cx-muted">يمكنك إدخال ${ctx.esc(patientName)} على أي حال.</p>`,
        async () => {
          await doStartVisit(ctx, id, patientName);
        },
        { saveLabel: "إدخال على أي حال", skipRender: true, successMessage: `تم إدخال ${patientName} للطبيب` }
      );
      return;
    }
    ctx.openModal(
      "إدخال للطبيب",
      `<p>إدخال <strong>${ctx.esc(patientName)}</strong> إلى <strong>${ctx.esc(doctorName)}</strong>؟</p>`,
      async () => {
        await doStartVisit(ctx, id, patientName);
      },
      { saveLabel: "إدخال", skipRender: true, successMessage: `تم إدخال ${patientName} للطبيب` }
    );
  }

  async function doStartVisit(ctx, id, patientName) {
    const visit = await ctx.api("/clinics/api/visits", {
      method: "POST",
      body: JSON.stringify({ appointment_id: Number(id) }),
    });
    const visitId = visit?.id || visit?.visit?.id;
    if (visitId) {
      location.href = `/clinics/doctor/${visitId}`;
      return;
    }
    await ctx.refresh({ silent: true });
  }

  async function startVisit(ctx, id, patientName) {
    await confirmStartVisit(ctx, id, patientName);
  }

  function closeAllMenus(root) {
    root.querySelectorAll(".cx-rec-menu").forEach((m) => {
      m.classList.remove("is-open");
    });
    root.querySelectorAll("[data-rec-menu]").forEach((b) => {
      b.setAttribute("aria-expanded", "false");
      b.classList.remove("is-open");
    });
  }

  function openMenu(btn, menu) {
    menu.classList.add("is-open");
    btn.setAttribute("aria-expanded", "true");
    btn.classList.add("is-open");
  }

  function bindMenuDismiss(root) {
    if (root._recMenuDismissBound) return;
    root._recMenuDismissBound = true;
    document.addEventListener("click", (e) => {
      if (e.target.closest(".cx-rec-menu-wrap")) return;
      closeAllMenus(root);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeAllMenus(root);
    });
    root.querySelectorAll(".cx-rec-col__body").forEach((el) => {
      el.addEventListener("scroll", () => closeAllMenus(root), { passive: true });
    });
  }

  function bindCardActions(root, ctx) {
    root.querySelectorAll("[data-rec-act]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const id = btn.dataset.id;
          const act = btn.dataset.recAct;
          const card = root.querySelector(`[data-appt-id="${id}"]`);
          const name = card?.querySelector(".cx-rec-card__name")?.textContent?.trim() || "المريض";
          if (act === "arrived") {
            await setStatus(ctx, id, "arrived", `تم تسجيل وصول ${name}`);
            return;
          }
          if (act === "start") await startVisit(ctx, id, name);
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      };
    });

    root.querySelectorAll("[data-rec-pay]").forEach((btn) => {
      btn.onclick = () => {
        const invId = btn.dataset.recPay;
        const apptId = btn.dataset.appt;
        const card = root.querySelector(`[data-appt-id="${apptId}"]`);
        const name = card?.querySelector(".cx-rec-card__name")?.textContent?.trim() || "";
        const appt = (ctx.data?.checkout || []).find((x) => String(x.id) === String(apptId));
        openPaymentModal(ctx, appt, name, invId);
      };
    });

    root.querySelectorAll("[data-rec-menu]").forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const menu = document.getElementById(btn.dataset.recMenu);
        if (!menu) return;
        const isOpen = menu.classList.contains("is-open");
        closeAllMenus(root);
        if (!isOpen) openMenu(btn, menu);
      };
    });

    root.querySelectorAll("[data-rec-menu-act]").forEach((btn) => {
      btn.onclick = async () => {
        const menu = btn.closest(".cx-rec-menu");
        if (menu) closeAllMenus(root);
        try {
          const id = btn.dataset.id;
          const act = btn.dataset.recMenuAct;
          if (act === "reschedule") {
            ctx.openModal(
              "إعادة جدولة الموعد",
              `<div class="cx-field"><label>التاريخ</label><input class="cx-input" type="date" id="rs_date" value="${ctx.esc(btn.dataset.date)}"></div>
               <div class="cx-field"><label>الوقت</label><input class="cx-input" type="time" id="rs_time" value="${ctx.esc(btn.dataset.time)}"></div>`,
              async () => {
                await ctx.api(`/clinics/api/appointments/${id}/reschedule`, {
                  method: "POST",
                  body: JSON.stringify({
                    appointment_date: document.getElementById("rs_date").value,
                    start_time: document.getElementById("rs_time").value,
                  }),
                });
                ctx.showNotice("تمت إعادة الجدولة", false);
                await ctx.refresh({ silent: true });
              }
            );
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
          if (act === "emergency") {
            const row = (ctx.data?.waiting || []).find((x) => String(x.id) === String(id));
            await ctx.api(`/clinics/api/appointments/${id}/emergency`, {
              method: "POST",
              body: JSON.stringify({ emergency: !row?.is_emergency }),
            });
            ctx.showNotice(row?.is_emergency ? "تم إلغاء الطوارئ" : "تم تعيين طوارئ", false);
            await ctx.refresh({ silent: true });
            return;
          }
          if (act === "note") {
            ctx.openModal("ملاحظة على الموعد", `<textarea class="cx-input" id="appt_note" rows="4" placeholder="ملاحظة…"></textarea>`, async () => {
              await ctx.api(`/clinics/api/appointments/${id}`, {
                method: "PATCH",
                body: JSON.stringify({ notes: document.getElementById("appt_note").value }),
              });
              ctx.showNotice("تم حفظ الملاحظة", false);
              await ctx.refresh({ silent: true });
            });
          }
        } catch (err) {
          ctx.showNotice(err.message || String(err));
        }
      };
    });
  }

  function openPaymentModal(ctx, appt, name, invoiceId) {
    const balance = appt?.invoice_balance || 0;
    const total = appt?.invoice_total || balance;
    const paid = appt?.invoice_paid || 0;
    ctx.openModal(
      `تحصيل — ${name}`,
      `<div class="cx-rec-pay-modal">
         <p><strong>${ctx.esc(name)}</strong></p>
         <div class="cx-rec-pay-lines">
           <span>المبلغ: <b class="cx-money">${ctx.money(total)}</b></span>
           <span>المقبوض: <b class="cx-money">${ctx.money(paid)}</b></span>
           <span>المستحق: <b class="cx-money">${ctx.money(balance)}</b></span>
         </div>
         <div class="cx-field"><label>المبلغ المقبوض</label><input class="cx-input cx-money" id="pay_amt" type="number" value="${balance}" min="1"></div>
         <div class="cx-field"><label>طريقة الدفع</label>
           <select class="cx-select" id="pay_method">
             <option value="cash">نقدي</option><option value="card">بطاقة</option>
             <option value="transfer">تحويل</option><option value="other">أخرى</option>
           </select>
         </div>
         <div class="cx-field"><label>ملاحظة</label><input class="cx-input" id="pay_note" placeholder="اختياري"></div>
       </div>`,
      async () => {
        await ctx.api(`/clinics/api/invoices/${invoiceId}/pay`, {
          method: "POST",
          body: JSON.stringify({
            amount: Number(document.getElementById("pay_amt").value),
            method: document.getElementById("pay_method").value,
            notes: document.getElementById("pay_note").value,
          }),
        });
        await ctx.refresh({ silent: true });
      },
      {
        saveLabel: "تحصيل",
        skipRender: true,
        successMessage: "✓ تم التحصيل",
        extraActions: [
          {
            label: "تحصيل وطباعة",
            primary: true,
            skipRender: true,
            notice: "✓ تم التحصيل",
            onClick: async () => {
              await ctx.api(`/clinics/api/invoices/${invoiceId}/pay`, {
                method: "POST",
                body: JSON.stringify({
                  amount: Number(document.getElementById("pay_amt").value),
                  method: document.getElementById("pay_method").value,
                  notes: document.getElementById("pay_note").value,
                }),
              });
              await ctx.refresh({ silent: true });
              window.open(`/clinics/billing?invoice=${invoiceId}`, "_blank");
            },
          },
        ],
      }
    );
  }

  async function openDrawer(ctx, patientId, apptId) {
    const drawer = document.getElementById("cxRecDrawer");
    const body = document.getElementById("cxRecDrawerBody");
    const title = document.getElementById("cxRecDrawerTitle");
    if (!drawer || !body) return;
    drawer.hidden = false;
    body.innerHTML = '<div class="cx-empty">جاري التحميل…</div>';
    try {
      const appt = apptId ? findAppt(ctx, apptId) : null;
      const data = await ctx.api(`/clinics/api/patients/${patientId}`);
      const p = data.patient || {};
      let balanceHtml = "";
      if (ctx.data?.can_finance && can(ctx, "clinics_billing")) {
        try {
          const stmt = await ctx.api(`/clinics/api/patients/${patientId}/statement`);
          if (stmt.outstanding_balance) {
            balanceHtml = `<div class="cx-rec-drawer__section"><h4>الرصيد</h4><p class="cx-money">${ctx.money(stmt.outstanding_balance)}</p></div>`;
          }
        } catch {
          /* ignore */
        }
      }
      title.textContent = p.full_name || "المريض";
      const lastVisit = (data.visits || [])[0];
      body.innerHTML = `
        <div class="cx-rec-drawer__profile">
          <div class="cx-rec-avatar"><i class="fa fa-user"></i></div>
          <div>
            <strong>${ctx.esc(p.full_name)}</strong>
            <p>${ctx.esc(p.file_number || "")}${p.age ? ` · ${p.age} سنة` : ""} · ${genderLabel(p.gender)}</p>
            <p>${ctx.esc(p.phone || "")}</p>
            ${p.address ? `<p class="cx-muted">${ctx.esc(p.address)}${p.city ? ` · ${ctx.esc(p.city)}` : ""}</p>` : ""}
          </div>
        </div>
        ${appt ? `
        <div class="cx-rec-drawer__section">
          <h4>موعد اليوم</h4>
          <p>${ctx.esc(appt.start_time || "")} · ${ctx.esc(appt.doctor_name || "")}</p>
          <p>${ctx.esc(appt.service_name || appt.notes || "")}</p>
          <p>${ctx.badge(appt.status)}${appt.wait_minutes ? ` · انتظار ${appt.wait_minutes} د` : ""}</p>
        </div>` : ""}
        ${lastVisit ? `<div class="cx-rec-drawer__section"><h4>آخر زيارة</h4><p>${ctx.esc(lastVisit.visit_date || "")} · ${ctx.esc(lastVisit.doctor_name || "")}</p></div>` : ""}
        ${balanceHtml}
        ${p.notes ? `<div class="cx-rec-drawer__section"><h4>ملاحظات</h4><p>${ctx.esc(p.notes)}</p></div>` : ""}
        <div class="cx-rec-drawer__actions">
          <a class="cx-btn cx-btn--primary" href="/clinics/patients/${patientId}">الملف الطبي</a>
          <button type="button" class="cx-btn" id="cxDrawerAppt">موعد جديد</button>
          ${appt?.invoice_id && can(ctx, "clinics_billing") && (appt.invoice_balance || 0) > 0
            ? `<button type="button" class="cx-btn cx-btn--primary" id="cxDrawerPay">تحصيل</button>`
            : ""}
          ${p.phone ? `<a class="cx-btn" href="tel:${ctx.esc(p.phone)}">اتصال</a>` : ""}
        </div>`;
      document.getElementById("cxDrawerAppt")?.addEventListener("click", () => ctx.promptNewAppointment());
      document.getElementById("cxDrawerPay")?.addEventListener("click", () => {
        openPaymentModal(ctx, appt, p.full_name, appt.invoice_id);
      });
    } catch (err) {
      body.innerHTML = `<div class="cx-empty">${ctx.esc(err.message || String(err))}</div>`;
    }
  }

  function patchBoard(root, data, ctx, state) {
    closeAllMenus(root);
    COLS.forEach((col) => {
      const body = root.querySelector(`[data-col-body="${col.key}"]`);
      const count = root.querySelector(`[data-col-count="${col.key}"]`);
      const items = data[col.listKey] || [];
      if (count) count.textContent = items.length;
      if (body) {
        body.innerHTML = items.map((a) => cardHtml(a, col.key, ctx)).join("") || '<div class="cx-rec-empty">لا يوجد</div>';
      }
    });
    const kpis = root.querySelector(".cx-rec-kpis");
    if (kpis) kpis.innerHTML = kpiRow(data.stats, ctx);
    const nextEl = document.getElementById("cxRecNext");
    const next = data.next_patient;
    if (nextEl) {
      nextEl.innerHTML = next
        ? `<strong>${ctx.esc(next.patient_name)}</strong>
           <p>${ctx.esc(next.doctor_name)} · انتظار ${next.wait_minutes || 0} د</p>
           <p class="cx-muted">${ctx.esc(next.service_name || "")}</p>
           <button type="button" class="cx-btn cx-btn--primary" data-rec-act="start" data-id="${next.appointment_id}">إدخال للطبيب</button>`
        : '<div class="cx-rec-empty">لا يوجد مرضى بانتظار النداء</div>';
    }
    const st = state || { day: root.querySelector("#cxRecDay")?.value || "" };
    bindCardActions(root, ctx);
    bindDrawer(root, ctx);
    bindQueueDragDrop(root, st, ctx);
    syncNotif(root, data.alerts || [], ctx);
  }

  function bindQueueDragDrop(root, state, ctx) {
    const list = root.querySelector('[data-col-body="waiting"]');
    if (!list || !can(ctx, "clinics_reception")) return;
    const touchDevice = window.matchMedia("(pointer: coarse)").matches;
    if (touchDevice) {
      list.querySelectorAll(".cx-rec-card[draggable=true]").forEach((item) => {
        item.removeAttribute("draggable");
      });
      return;
    }
    let dragId = null;
    list.querySelectorAll(".cx-rec-card[draggable=true]").forEach((item) => {
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
        const ids = [...list.querySelectorAll(".cx-rec-card[data-wait-id]")].map((el) => el.dataset.waitId);
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
  }

  function bindDrawer(root, ctx) {
    root.querySelectorAll("[data-rec-drawer]").forEach((btn) => {
      btn.onclick = () => openDrawer(ctx, btn.dataset.recDrawer, btn.dataset.appt);
    });
    document.getElementById("cxRecDrawerClose")?.addEventListener("click", () => {
      const drawer = document.getElementById("cxRecDrawer");
      if (drawer) drawer.hidden = true;
    });
  }

  function bindSearch(root, ctx) {
    const search = root.querySelector("#cxRecSearch");
    const results = root.querySelector("#cxRecSearchResults");
    if (!search || !results) return;
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

  function startLiveTimers(root) {
    if (root._liveTimer) clearInterval(root._liveTimer);
    root._liveTimer = setInterval(() => {
      root.querySelectorAll("[data-live-wait]").forEach((el) => {
        const card = el.closest(".cx-rec-card");
        if (!card) return;
        const arrived = card.dataset.arrived;
        if (!arrived) return;
        const mins = Math.max(0, Math.floor((Date.now() - new Date(arrived).getTime()) / 60000));
        let level = "ok";
        if (mins > 30) level = "critical";
        else if (mins > 20) level = "alert";
        else if (mins > 10) level = "warn";
        el.innerHTML = waitLabel(mins, level);
      });
      root.querySelectorAll("[data-live-consult]").forEach((el) => {
        const card = el.closest(".cx-rec-card");
        if (!card) return;
        const started = card.dataset.visitStarted;
        if (!started) return;
        const mins = Math.max(0, Math.floor((Date.now() - new Date(started).getTime()) / 60000));
        const level = mins > 60 ? "alert" : "ok";
        el.innerHTML = waitLabel(mins, level);
      });
    }, 30000);
  }

  function bindUI(root, state, ctx) {
    document.getElementById("cxRecDay")?.addEventListener("change", (e) => {
      state.day = e.target.value;
      ctx.refresh();
    });
    document.getElementById("cxRecDoctor")?.addEventListener("change", (e) => {
      state.doctorFilter = e.target.value;
      ctx.refresh();
    });
    document.getElementById("cxRecBranch")?.addEventListener("change", (e) => {
      state.branchFilter = e.target.value;
      ctx.refresh();
    });
    document.getElementById("cxRecNewPatient")?.addEventListener("click", () => ctx.promptNewPatient());
    document.getElementById("cxRecNewAppt")?.addEventListener("click", () => ctx.promptNewAppointment());
    bindNotifPanel(root);
    bindMenuDismiss(root);
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        root.querySelector("#cxRecSearch")?.focus();
      }
    });
    bindCardActions(root, ctx);
    bindDrawer(root, ctx);
    bindSearch(root, ctx);
    bindQueueDragDrop(root, state, ctx);
    startLiveTimers(root);
  }

  let pollTimer = null;
  let lastPulse = null;

  function startPulse(state, root, helpers, ctxRef) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (document.hidden) return;
      try {
        const qs = new URLSearchParams({ date: state.day });
        if (state.doctorFilter) qs.set("doctor_id", state.doctorFilter);
        if (state.branchFilter) qs.set("branch_id", state.branchFilter);
        const data = await helpers.api(`/clinics/api/reception?${qs}`);
        if (lastPulse && data.pulse_version === lastPulse) return;
        lastPulse = data.pulse_version;
        ctxRef.data = data;
        patchBoard(root, data, ctxRef, state);
      } catch {
        /* ignore */
      }
    }, 12000);
  }

  async function render(state, root, helpers, opts = {}) {
    if (!opts.silent) root.innerHTML = skeleton();
    try {
      const qs = new URLSearchParams({ date: state.day });
      if (state.doctorFilter) qs.set("doctor_id", state.doctorFilter);
      if (state.branchFilter) qs.set("branch_id", state.branchFilter);
      const data = await helpers.api(`/clinics/api/reception?${qs}`);
      if (data.user) helpers.bootstrap.user = data.user;
      lastPulse = data.pulse_version || lastPulse;
      const ctx = {
        ...helpers,
        data,
        bootstrap: helpers.bootstrap,
        refresh: (o) => render(state, root, helpers, o),
      };
      if (opts.silent && root.querySelector(".cx-rec")) {
        patchBoard(root, data, ctx, state);
      } else {
        root.innerHTML = buildHtml(data, state, ctx);
        bindUI(root, state, ctx);
        startPulse(state, root, helpers, ctx);
      }
      return ctx;
    } catch (err) {
      if (!opts.silent) {
        root.innerHTML = `<div class="cx-empty">تعذر تحميل الاستقبال: ${helpers.esc(err.message || String(err))}</div>`;
      }
      throw err;
    }
  }

  window.ClinicsReception = { render };
})();
