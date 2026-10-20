/* Finora Clinics — unified dental sessions and image metadata UI. */
(() => {
  const IMAGE_TYPES = {
    xray: "أشعة سنية",
    panoramic: "بانوراما",
    opg: "OPG",
    periapical: "حول ذروية",
    bitewing: "Bitewing",
    cbct: "CBCT",
    cephalometric: "سيفالومتري",
    intraoral: "داخل الفم",
    before: "قبل العلاج",
    after: "بعد العلاج",
    photo: "صورة",
    scan: "مسح رقمي",
    other: "أخرى",
  };
  const STATUS = {
    planned: "مخططة",
    scheduled: "مجدولة",
    in_progress: "جارية",
    completed: "مكتملة",
    cancelled: "ملغاة",
    no_show: "لم يحضر",
  };
  const esc = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function localDateTime(iso) {
    if (!iso) return "غير محدد";
    try {
      return window.FinoraTime.format(iso, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return iso;
    }
  }

  function tomorrowValue() {
    const date = new Date();
    date.setDate(date.getDate() + 7);
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  async function loadPlanAndSessions(api, patientId) {
    const plans = await api(`/clinics/api/patients/${patientId}/dental-treatment-plans`);
    const active = plans.active_plan;
    const items = active?.items || [];
    const results = await Promise.all(
      items.map((item) =>
        api(`/clinics/api/dental-treatment-plan-items/${item.id}/sessions`)
          .then((data) => ({ item, data }))
          .catch(() => ({ item, data: { items: [], next_session: null } }))
      )
    );
    const sessions = results.flatMap(({ item, data }) =>
      (data.items || []).map((session) => ({ ...session, item }))
    );
    const next = sessions
      .filter((session) => ["planned", "scheduled"].includes(session.status))
      .sort((a, b) => String(a.scheduled_for || "9999").localeCompare(String(b.scheduled_for || "9999")))[0];
    return { plans, active, items, sessions, next };
  }

  function sessionsMarkup(model, readonly) {
    const next = model.next;
    return `
      <section class="cx-dplat" aria-label="جلسات علاج الأسنان">
        <header class="cx-dplat__head">
          <div><h3>جلسات خطة العلاج</h3><small>تنفيذ بنود الخطة وربطها بالزيارة الحالية</small></div>
        </header>
        ${
          next
            ? `<article class="cx-dplat-next">
                <span>الجلسة القادمة</span>
                <strong>${esc(next.item.tooth_number || "عام")} · ${esc(next.item.title)} · الجلسة ${next.session_number}</strong>
                <small>${esc(localDateTime(next.scheduled_for))}</small>
              </article>`
            : '<div class="cx-dplat-next is-empty"><strong>لا توجد جلسة قادمة</strong><small>أنشئ جلسة من أحد بنود العلاج المفتوحة.</small></div>'
        }
        <div class="cx-dplat__items">
          ${
            model.items
              .map((item) => {
                const rows = model.sessions.filter((session) => String(session.treatment_plan_item_id) === String(item.id));
                const closed = ["completed", "cancelled"].includes(item.status);
                return `<article class="cx-dplat-item" data-session-item="${item.id}">
                  <header>
                    <div><strong>${esc(item.tooth_number || "عام")} · ${esc(item.title)}</strong>
                    <small>${esc(item.status_label_ar || item.status)} · ${esc(item.sessions_label || "")}</small></div>
                    ${!readonly && !closed ? `<button type="button" class="cx-btn cx-btn--sm" data-new-session="${item.id}"><i class="fa fa-plus"></i> جلسة</button>` : ""}
                  </header>
                  <div class="cx-dplat-sessions">
                    ${
                      rows
                        .map(
                          (session) => `<div class="cx-dplat-session is-${esc(session.status)}">
                            <div><b>الجلسة ${session.session_number}</b><span>${esc(STATUS[session.status] || session.status)} · ${esc(localDateTime(session.scheduled_for))}</span>${session.notes ? `<small>${esc(session.notes)}</small>` : ""}</div>
                            <div class="cx-dplat-session__actions">
                              ${
                                !readonly && ["planned", "scheduled"].includes(session.status)
                                  ? `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-start-session="${session.id}">بدء</button>`
                                  : ""
                              }
                              ${
                                !readonly && ["planned", "scheduled", "in_progress"].includes(session.status)
                                  ? `<button type="button" class="cx-btn cx-btn--sm" data-complete-session="${session.id}">إكمال</button>
                                     <button type="button" class="cx-btn cx-btn--sm cx-btn--danger" data-cancel-session="${session.id}">إلغاء</button>`
                                  : ""
                              }
                            </div>
                          </div>`
                        )
                        .join("") || '<p class="cx-muted">لا جلسات لهذا البند.</p>'
                    }
                  </div>
                </article>`;
              })
              .join("") || '<div class="cx-empty">أنشئ خطة علاج وبنوداً أولاً.</div>'
          }
        </div>
        <div id="cxDentalNextBooking"></div>
      </section>`;
  }

  async function mountSessions(el, opts) {
    const { api, patientId, visitId, doctorId, specialtyId, showNotice, openModal, readonly = false } = opts;
    let model = await loadPlanAndSessions(api, patientId);

    const reload = async () => {
      model = await loadPlanAndSessions(api, patientId);
      paint();
    };

    function openSessionForm(itemId) {
      openModal(
        "إنشاء جلسة علاج",
        `<div class="cx-field"><label>موعد الجلسة</label><input class="cx-input" type="datetime-local" id="dpSessionAt" value="${tomorrowValue()}"></div>
         <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="dpSessionNotes"></textarea></div>
         ${visitId ? '<label class="cx-check"><input type="checkbox" id="dpLinkVisit" checked> ربط بالزيارة الحالية</label>' : ""}`,
        async () => {
          const scheduledFor = document.getElementById("dpSessionAt").value;
          await api(`/clinics/api/dental-treatment-plan-items/${itemId}/sessions`, {
            method: "POST",
            body: JSON.stringify({
              scheduled_for: scheduledFor || null,
              status: scheduledFor ? "scheduled" : "planned",
              visit_id: visitId && document.getElementById("dpLinkVisit")?.checked ? Number(visitId) : null,
              notes: document.getElementById("dpSessionNotes").value,
            }),
          });
          await reload();
        },
        { skipRender: true, successMessage: "تم إنشاء جلسة العلاج" }
      );
    }

    function showNextBooking(item, nextSession) {
      const host = el.querySelector("#cxDentalNextBooking");
      if (!host) return;
      host.innerHTML = `<article class="cx-dplat-book">
        <div><strong>هل تريد حجز الجلسة القادمة؟</strong><small>سيُنشأ موعد عام ثم تُربط به جلسة العلاج الجديدة فعلياً.</small></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>التاريخ والوقت</label><input class="cx-input" type="datetime-local" data-next-at value="${tomorrowValue()}"></div>
          <div class="cx-field"><label>ملاحظات الموعد</label><input class="cx-input" data-next-notes value="${esc(`الجلسة القادمة: ${item.title}${item.tooth_number ? ` — السن ${item.tooth_number}` : ""}`)}"></div>
        </div>
        <div class="cx-actions"><button type="button" class="cx-btn cx-btn--primary" data-book-next>حجز وربط الجلسة</button><button type="button" class="cx-btn" data-dismiss-next>لاحقاً</button></div>
      </article>`;
      host.querySelector("[data-dismiss-next]").onclick = () => (host.innerHTML = "");
      host.querySelector("[data-book-next]").onclick = async () => {
        const at = host.querySelector("[data-next-at]").value;
        if (!at) return showNotice?.("حدد موعد الجلسة القادمة");
        const [appointment_date, start_time] = at.split("T");
        try {
          const appointment = await api("/clinics/api/appointments", {
            method: "POST",
            body: JSON.stringify({
              patient_id: Number(patientId),
              doctor_id: doctorId || null,
              specialty_id: specialtyId || null,
              service_id: item.service_id || null,
              appointment_date,
              start_time,
              notes: host.querySelector("[data-next-notes]").value,
              status: "confirmed",
              treatment_plan_id: item.treatment_plan_id || model.active?.plan?.id || null,
              treatment_plan_item_id: item.id,
              dental_session_id: nextSession?.id || null,
              tooth_number: item.tooth_number || null,
              tooth_numbers: item.tooth_numbers || [],
            }),
          });
          const sessionUrl = nextSession
            ? `/clinics/api/dental-sessions/${nextSession.id}`
            : `/clinics/api/dental-treatment-plan-items/${item.id}/sessions`;
          await api(sessionUrl, {
            method: nextSession ? "PATCH" : "POST",
            body: JSON.stringify({
              appointment_id: appointment.id,
              scheduled_for: at,
              status: "scheduled",
              notes: host.querySelector("[data-next-notes]").value,
            }),
          });
          showNotice?.("تم حجز الموعد وربط جلسة العلاج", false);
          await reload();
        } catch (error) {
          showNotice?.(error.message || String(error));
        }
      };
      host.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function paint() {
      el.innerHTML = sessionsMarkup(model, readonly);
      el.querySelectorAll("[data-new-session]").forEach((button) => {
        button.onclick = () => openSessionForm(Number(button.dataset.newSession));
      });
      el.querySelectorAll("[data-start-session]").forEach((button) => {
        button.onclick = async () => {
          try {
            await api(`/clinics/api/dental-sessions/${button.dataset.startSession}`, {
              method: "PATCH",
              body: JSON.stringify({ status: "in_progress", visit_id: visitId ? Number(visitId) : null }),
            });
            showNotice?.("بدأت جلسة العلاج", false);
            await reload();
          } catch (error) {
            showNotice?.(error.message || String(error));
          }
        };
      });
      el.querySelectorAll("[data-cancel-session]").forEach((button) => {
        button.onclick = async () => {
          const reason = prompt("اكتب سبب إلغاء جلسة العلاج:");
          if (!reason?.trim()) return;
          try {
            await api(`/clinics/api/dental-sessions/${button.dataset.cancelSession}/cancel`, {
              method: "POST",
              body: JSON.stringify({ cancellation_reason: reason.trim() }),
            });
            await reload();
          } catch (error) {
            showNotice?.(error.message || String(error));
          }
        };
      });
      el.querySelectorAll("[data-complete-session]").forEach((button) => {
        button.onclick = () => {
          const session = model.sessions.find((row) => String(row.id) === String(button.dataset.completeSession));
          if (!visitId) return showNotice?.("افتح الجلسة من زيارة حالية لإكمالها");
          openModal(
            "إكمال جلسة العلاج",
            `<p><strong>${esc(session.item.title)}</strong> · الجلسة ${session.session_number}</p>
             <div class="cx-field"><label>تفاصيل ما تم في الجلسة</label><textarea class="cx-textarea" id="dpSessionCompleteNotes">${esc(session.notes || "")}</textarea></div>
             <div class="cx-field"><label>توصية الجلسة القادمة</label><textarea class="cx-textarea" id="dpSessionRecommendation"></textarea></div>
             <label class="cx-check"><input type="checkbox" id="dpSessionFinal"> هذه آخر جلسة للبند</label>
             <p class="cx-muted">سيُربط التنفيذ بالزيارة الحالية. إذا كان البند بلا إجراء، اربط إجراء زيارة من تفاصيل بند الخطة أولاً.</p>`,
            async () => {
              const isFinal = !!document.getElementById("dpSessionFinal")?.checked;
              const completed = await api(`/clinics/api/dental-sessions/${session.id}/complete`, {
                method: "POST",
                body: JSON.stringify({
                  visit_id: Number(visitId),
                  is_final: isFinal,
                  notes: document.getElementById("dpSessionCompleteNotes").value,
                  next_recommendation: document.getElementById("dpSessionRecommendation").value,
                }),
              });
              await reload();
              if (!isFinal) showNextBooking(session.item, completed.next_session);
            },
            { skipRender: true, successMessage: "تم إكمال جلسة العلاج" }
          );
        };
      });
    }

    paint();
    return { reload };
  }

  function imageUrl(image, preview = true) {
    return `/clinics/api/attachments/${image.attachment_id}/${preview ? "preview" : "download"}`;
  }

  function attachmentIdFromUpload(payload) {
    const data = payload?.data;
    const item = Array.isArray(data?.items) ? data.items[0] : data;
    return Number(item?.id || 0);
  }

  function imageCards(images, readonly) {
    return images
      .map(
        (image) => `<article class="cx-dplat-image" data-image-id="${image.id}">
          <button type="button" class="cx-dplat-image__preview" data-open-image="${image.id}" aria-label="معاينة ${esc(image.file_name)}">
            <img src="${imageUrl(image)}" alt="${esc(`${IMAGE_TYPES[image.image_type] || image.image_type}${image.tooth_number ? ` للسن ${image.tooth_number}` : ""}`)}" loading="lazy">
          </button>
          <div><strong>${esc(IMAGE_TYPES[image.image_type] || image.image_type)}</strong>
          <small>${image.tooth_number ? `السن ${esc(image.tooth_number)} · ` : ""}${esc(localDateTime(image.captured_at))}</small>
          ${image.notes ? `<p>${esc(image.notes)}</p>` : ""}</div>
          <div class="cx-dplat-image__actions">
            <a class="cx-btn cx-btn--sm" href="${imageUrl(image, false)}"><i class="fa fa-download"></i> تنزيل</a>
            ${readonly ? "" : `<button type="button" class="cx-btn cx-btn--sm cx-btn--danger" data-delete-image="${image.id}">حذف البيانات</button>`}
          </div>
        </article>`
      )
      .join("");
  }

  async function mountImages(el, opts) {
    const { api, patientId, visitId, showNotice, readonly = false } = opts;
    let tooth = "";
    let imageType = "";

    async function load() {
      const query = new URLSearchParams({ patient_id: patientId });
      if (tooth) query.set("tooth_number", tooth);
      if (imageType) query.set("image_type", imageType);
      return api(`/clinics/api/dental-images?${query}`);
    }

    async function paint() {
      const images = await load();
      el.innerHTML = `<section class="cx-dplat" aria-label="صور الأسنان">
        <header class="cx-dplat__head"><div><h3>صور الأسنان</h3><small>المرفق يُرفع أولاً ثم تحفظ بيانات الصورة السنية.</small></div></header>
        <div class="cx-dplat-filters">
          <label>السن <input class="cx-input" data-image-filter-tooth value="${esc(tooth)}" placeholder="مثال 16"></label>
          <label>النوع <select class="cx-select" data-image-filter-type><option value="">كل الأنواع</option>${Object.entries(IMAGE_TYPES)
            .map(([key, label]) => `<option value="${key}" ${key === imageType ? "selected" : ""}>${label}</option>`)
            .join("")}</select></label>
          <button type="button" class="cx-btn" data-apply-image-filter><i class="fa fa-filter"></i> تطبيق</button>
        </div>
        ${
          readonly
            ? ""
            : `<form class="cx-dplat-upload" data-dental-upload>
                <div class="cx-field"><label>الصورة</label><input type="file" accept="image/*" data-image-file required></div>
                <div class="cx-field"><label>النوع</label><select class="cx-select" data-image-type>${Object.entries(IMAGE_TYPES)
                  .map(([key, label]) => `<option value="${key}">${label}</option>`)
                  .join("")}</select></div>
                <div class="cx-field"><label>السن (اختياري)</label><input class="cx-input" data-image-tooth placeholder="16"></div>
                <div class="cx-field"><label>ملاحظات</label><input class="cx-input" data-image-notes></div>
                <button class="cx-btn cx-btn--primary" type="submit"><i class="fa fa-upload"></i> رفع وحفظ البيانات</button>
                <span class="cx-muted" data-upload-state aria-live="polite"></span>
              </form>`
        }
        <div class="cx-dplat-images">${imageCards(images, readonly) || '<div class="cx-empty">لا توجد صور مطابقة.</div>'}</div>
      </section>`;

      el.querySelector("[data-apply-image-filter]").onclick = () => {
        tooth = el.querySelector("[data-image-filter-tooth]").value.trim();
        imageType = el.querySelector("[data-image-filter-type]").value;
        paint().catch((error) => showNotice?.(error.message || String(error)));
      };
      const form = el.querySelector("[data-dental-upload]");
      if (form) {
        form.onsubmit = async (event) => {
          event.preventDefault();
          const file = form.querySelector("[data-image-file]").files[0];
          if (!file) return;
          const state = form.querySelector("[data-upload-state]");
          const button = form.querySelector("button");
          button.disabled = true;
          state.textContent = "جاري رفع المرفق…";
          try {
            const body = new FormData();
            body.append("file", file);
            body.append("patient_id", String(patientId));
            if (visitId) body.append("visit_id", String(visitId));
            body.append("category", "radiology");
            const response = await fetch("/clinics/api/attachments", {
              method: "POST",
              headers: { "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "" },
              body,
            });
            const uploaded = await response.json();
            if (!response.ok || uploaded.ok === false) throw new Error(uploaded.error || "فشل رفع المرفق");
            const attachmentId = attachmentIdFromUpload(uploaded);
            if (!attachmentId) throw new Error("تم الرفع لكن المرفق بلا معرّف صالح");
            state.textContent = "تم الرفع، جاري حفظ البيانات…";
            await api("/clinics/api/dental-images", {
              method: "POST",
              body: JSON.stringify({
                attachment_id: attachmentId,
                patient_id: Number(patientId),
                visit_id: visitId ? Number(visitId) : null,
                tooth_number: form.querySelector("[data-image-tooth]").value.trim() || null,
                image_type: form.querySelector("[data-image-type]").value,
                captured_at: new Date().toISOString(),
                notes: form.querySelector("[data-image-notes]").value,
              }),
            });
            showNotice?.("تم رفع الصورة وحفظ بياناتها", false);
            await paint();
          } catch (error) {
            state.textContent = "فشل الحفظ";
            showNotice?.(error.message || String(error));
          } finally {
            button.disabled = false;
          }
        };
      }
      el.querySelectorAll("[data-delete-image]").forEach((button) => {
        button.onclick = async () => {
          if (!confirm("حذف بيانات صورة الأسنان؟ سيبقى المرفق الأصلي محفوظاً.")) return;
          try {
            await api(`/clinics/api/dental-images/${button.dataset.deleteImage}`, { method: "DELETE" });
            showNotice?.("تم حذف بيانات الصورة مع إبقاء المرفق", false);
            await paint();
          } catch (error) {
            showNotice?.(error.message || String(error));
          }
        };
      });
      el.querySelectorAll("[data-open-image]").forEach((button) => {
        button.onclick = () => {
          const image = images.find((row) => String(row.id) === String(button.dataset.openImage));
          openViewer(image);
        };
      });
    }

    function openViewer(image) {
      let rotation = 0;
      let zoom = 1;
      const viewer = document.createElement("div");
      viewer.className = "cx-dplat-viewer";
      viewer.setAttribute("role", "dialog");
      viewer.setAttribute("aria-modal", "true");
      viewer.setAttribute("aria-label", "معاينة صورة الأسنان");
      viewer.innerHTML = `<div class="cx-dplat-viewer__toolbar">
          <button type="button" class="cx-btn" data-view-zoom-in aria-label="تكبير"><i class="fa fa-magnifying-glass-plus"></i></button>
          <button type="button" class="cx-btn" data-view-zoom-out aria-label="تصغير"><i class="fa fa-magnifying-glass-minus"></i></button>
          <button type="button" class="cx-btn" data-view-rotate aria-label="تدوير"><i class="fa fa-rotate-right"></i></button>
          <button type="button" class="cx-btn" data-view-full aria-label="ملء الشاشة"><i class="fa fa-expand"></i></button>
          <a class="cx-btn" href="${imageUrl(image, false)}"><i class="fa fa-download"></i> تنزيل</a>
          <button type="button" class="cx-btn" data-view-close aria-label="إغلاق"><i class="fa fa-xmark"></i></button>
        </div><div class="cx-dplat-viewer__stage"><img src="${imageUrl(image)}" alt="${esc(image.file_name)}"></div>`;
      document.body.appendChild(viewer);
      const img = viewer.querySelector("img");
      const transform = () => (img.style.transform = `scale(${zoom}) rotate(${rotation}deg)`);
      const close = () => {
        document.removeEventListener("keydown", onKey);
        viewer.remove();
      };
      const onKey = (event) => event.key === "Escape" && close();
      document.addEventListener("keydown", onKey);
      viewer.querySelector("[data-view-close]").onclick = close;
      viewer.querySelector("[data-view-zoom-in]").onclick = () => {
        zoom = Math.min(3, zoom + 0.25);
        transform();
      };
      viewer.querySelector("[data-view-zoom-out]").onclick = () => {
        zoom = Math.max(0.5, zoom - 0.25);
        transform();
      };
      viewer.querySelector("[data-view-rotate]").onclick = () => {
        rotation = (rotation + 90) % 360;
        transform();
      };
      viewer.querySelector("[data-view-full]").onclick = () => viewer.requestFullscreen?.();
      viewer.onclick = (event) => event.target === viewer && close();
    }

    await paint();
    return { reload: paint };
  }

  async function mount(el, opts = {}) {
    const view = opts.view || "all";
    if (view === "sessions") return mountSessions(el, opts);
    if (view === "images") return mountImages(el, opts);
    el.innerHTML = `<div class="cx-dplat-tabs" role="tablist">
      <button type="button" class="is-active" data-dp-tab="plan">خطة العلاج</button>
      <button type="button" data-dp-tab="sessions">الجلسات</button>
      <button type="button" data-dp-tab="images">الصور</button>
    </div>
    <div class="cx-dplat-panel is-active" data-dp-panel="plan"><div data-plan-root></div></div>
    <div class="cx-dplat-panel" data-dp-panel="sessions"><div data-sessions-root></div></div>
    <div class="cx-dplat-panel" data-dp-panel="images"><div data-images-root></div></div>`;
    if (window.ClinicsDentalTreatmentPlan) {
      await window.ClinicsDentalTreatmentPlan.mount(el.querySelector("[data-plan-root]"), opts);
    }
    await Promise.all([
      mountSessions(el.querySelector("[data-sessions-root]"), opts),
      mountImages(el.querySelector("[data-images-root]"), opts),
    ]);
    el.querySelectorAll("[data-dp-tab]").forEach((button) => {
      button.onclick = () => {
        el.querySelectorAll("[data-dp-tab]").forEach((item) => item.classList.toggle("is-active", item === button));
        el.querySelectorAll("[data-dp-panel]").forEach((panel) =>
          panel.classList.toggle("is-active", panel.dataset.dpPanel === button.dataset.dpTab)
        );
      };
    });
  }

  window.ClinicsDentalPlatform = { mount, mountSessions, mountImages, loadPlanAndSessions };
})();
