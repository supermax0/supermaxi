/* Gynecology & Obstetrics clinical pack — no risk scoring / percentiles. */
(() => {
  const esc = (v) =>
    String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function gaLabel(ga) {
    if (!ga) return "—";
    return ga.label || "—";
  }

  async function mount(el, opts) {
    const { patientId, visitId, doctorId, api, showNotice, openModal, readonly } = opts;
    const endpoint = visitId
      ? `/clinics/api/visits/${visitId}/gynecology-context`
      : `/clinics/api/patients/${patientId}/gynecology-context`;
    let ctx = await api(endpoint);
    const canEdit = !readonly && ctx.permissions?.can_edit !== false;

    async function reload() {
      ctx = await api(endpoint);
      paint();
    }

    function paint() {
      const summary = ctx.summary || {};
      const active = ctx.active_pregnancy;
      const profile = ctx.profile || {};
      const pregCtx = ctx.pregnancy_context || {};
      const alerts = summary.alerts || pregCtx.alerts || [];
      const timeline = (pregCtx.timeline && pregCtx.timeline.events) || [];
      const vitalsW = (pregCtx.vital_trends && pregCtx.vital_trends.weight) || [];
      const vitalsBp = (pregCtx.vital_trends && pregCtx.vital_trends.blood_pressure) || [];
      const multi = ctx.selection_required
        ? `<div class="cx-gyn__alert">يوجد أكثر من حمل نشط — أنهِ السجلات الزائدة قبل المتابعة.</div>
           <div class="cx-feed">${(ctx.active_pregnancies || [])
             .map(
               (p) =>
                 `<article class="cx-feed__item"><strong>#${esc(p.id)} · ${esc(p.gpa_label)}</strong>
                 <small>LMP ${esc(p.lmp_date || "—")} · EDD ${esc(p.edd_date || "—")}</small>
                 ${canEdit ? `<button type="button" class="cx-btn cx-btn--sm" data-close-id="${p.id}">إنهاء</button>` : ""}</article>`
             )
             .join("")}</div>`
        : "";

      el.innerHTML = `
        <div class="cx-gyn" dir="rtl">
          <section class="cx-gyn__summary">
            <div><span>LMP</span><strong>${esc(summary.lmp || "—")}</strong></div>
            <div><span>EDD</span><strong>${esc(summary.edd || "—")}</strong></div>
            <div><span>عمر الحمل</span><strong>${esc(gaLabel(summary.gestational_age))}</strong></div>
            <div><span>G / P / A</span><strong>${esc(summary.gpa || "—")}</strong></div>
            <div><span>المتابعة التالية</span><strong>${esc(summary.next_followup?.due_date || "—")}</strong></div>
          </section>
          ${alerts.map((a) => `<p class="cx-gyn__alert">${esc(a.message)}</p>`).join("")}
          ${multi}
          <p class="cx-gyn__note">لا يوجد تقييم تلقائي لمخاطر الحمل أو نسب نمو الجنين في هذه المرحلة.</p>

          <details class="cx-gyn__block" open>
            <summary>ملخص الحمل / الحالة</summary>
            ${
              active
                ? `<div class="cx-gyn__grid">
                    <div><span>الحالة</span><strong>${esc(active.status_label_ar)}</strong></div>
                    <div><span>طريقة التأريخ</span><strong>${esc(active.dating_method_label_ar || "—")}</strong></div>
                    <div><span>EDD مقترح من LMP</span><strong>${esc(active.edd_suggested_from_lmp || "—")}</strong></div>
                  </div>
                  ${
                    canEdit
                      ? `<div class="cx-actions" style="margin-top:10px">
                    <button type="button" class="cx-btn cx-btn--sm" data-edit-preg>تعديل التأريخ / G-P-A</button>
                    <button type="button" class="cx-btn cx-btn--sm" data-close-preg>إنهاء سجل الحمل</button>
                  </div>`
                      : ""
                  }`
                : `<div class="cx-empty">لا يوجد حمل نشط — أدوات النسائية العامة متاحة بدون إجبار تسجيل حمل.</div>
                   ${canEdit ? '<button type="button" class="cx-btn cx-btn--primary cx-btn--sm" data-new-preg>+ تسجيل حمل</button>' : ""}`
            }
          </details>

          <details class="cx-gyn__block">
            <summary>الدورة والتاريخ النسائي</summary>
            <div class="cx-gyn__grid">
              <div><span>عمر الحيض</span><strong>${esc(profile.menarche_age ?? "—")}</strong></div>
              <div><span>دورة منتظمة</span><strong>${profile.cycle_regular == null ? "—" : profile.cycle_regular ? "نعم" : "لا"}</strong></div>
              <div><span>طول الدورة</span><strong>${esc(profile.cycle_length_days ?? "—")}</strong></div>
              <div><span>آخر دورة (عامة)</span><strong>${esc(profile.last_menstrual_period || "—")}</strong></div>
            </div>
            <p><small>${esc(profile.gynecologic_history || "بدون تاريخ نسائي مسجّل")}</small></p>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm" data-edit-profile>تعديل الملف النسائي</button>' : ""}
          </details>

          ${
            active
              ? `<details class="cx-gyn__block" open>
            <summary>متابعة الحمل</summary>
            ${
              ctx.current_observation
                ? `<div class="cx-feed__item"><strong>${esc(ctx.current_observation.gestational_age_label || "")}</strong>
                   <small>FHR ${esc(ctx.current_observation.fetal_heart_rate ?? "—")} · ارتفاع رحمي ${esc(ctx.current_observation.fundal_height_cm ?? "—")}</small>
                   <p>${esc(ctx.current_observation.clinical_notes || "")}</p></div>`
                : '<div class="cx-empty">لا ملاحظة مسجّلة لهذه الزيارة بعد</div>'
            }
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm" data-add-obs>تسجيل ملاحظة حمل</button>' : ""}
            <h4 style="margin:14px 0 8px">ملاحظات سابقة</h4>
            <div class="cx-feed">${(pregCtx.observations || [])
              .slice(0, 12)
              .map(
                (o) =>
                  `<article class="cx-feed__item"><strong>${esc((o.created_at || "").slice(0, 10))} · ${esc(o.gestational_age_label || "")}</strong>
                  <small>FHR ${esc(o.fetal_heart_rate ?? "—")} · ${esc(o.presentation || "")}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا ملاحظات</div>'}</div>
          </details>

          <details class="cx-gyn__block">
            <summary>اتجاهات الوزن والضغط (من العلامات الحيوية)</summary>
            <div class="cx-feed">${vitalsW
              .slice(-15)
              .reverse()
              .map(
                (r) =>
                  `<article class="cx-feed__item"><strong>${esc((r.recorded_at || "").slice(0, 10))} · ${esc(gaLabel(r.gestational_age))}</strong>
                  <small>وزن ${esc(r.weight_kg)} كغ</small></article>`
              )
              .join("") || '<div class="cx-empty">لا أوزان ضمن نافذة الحمل</div>'}</div>
            <div class="cx-feed">${vitalsBp
              .slice(-15)
              .reverse()
              .map(
                (r) =>
                  `<article class="cx-feed__item"><strong>${esc((r.recorded_at || "").slice(0, 10))}</strong>
                  <small>ضغط ${esc(r.blood_pressure)}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا قياسات ضغط ضمن نافذة الحمل</div>'}</div>
          </details>

          <details class="cx-gyn__block">
            <summary>الفحوصات (تحاليل / أشعة)</summary>
            <h4>تحاليل</h4>
            <div class="cx-feed">${(pregCtx.labs || [])
              .slice(0, 10)
              .map(
                (l) =>
                  `<article class="cx-feed__item"><strong>${esc((l.ordered_at || "").slice(0, 10))}</strong>
                  <small>${esc(l.status)} · ${(l.items || []).map((i) => esc(i.test)).join("، ")}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا تحاليل في نافذة الحمل</div>'}</div>
            <h4>موجات / أشعة</h4>
            <div class="cx-feed">${(pregCtx.radiology || [])
              .slice(0, 10)
              .map(
                (r) =>
                  `<article class="cx-feed__item"><strong>${esc((r.ordered_at || "").slice(0, 10))} · ${esc(r.modality)}</strong>
                  <small>${esc(r.body_part)} ${r.is_ultrasound ? "· موجات" : ""}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا فحوصات أشعة في نافذة الحمل</div>'}</div>
          </details>

          <details class="cx-gyn__block">
            <summary>الجدول الزمني للحمل</summary>
            <div class="cx-feed">${timeline
              .slice()
              .reverse()
              .slice(0, 40)
              .map(
                (e) =>
                  `<article class="cx-feed__item"><strong>${esc((e.at || "").slice(0, 10))} ${e.week != null ? "· أسبوع " + esc(e.week) : ""}</strong>
                  <small>${esc(e.title)} · ${esc(e.detail || "")}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا أحداث بعد</div>'}</div>
          </details>`
              : ""
          }

          <details class="cx-gyn__block">
            <summary>الأحمال السابقة</summary>
            <div class="cx-feed">${(ctx.previous_pregnancies || [])
              .map(
                (p) =>
                  `<article class="cx-feed__item"><strong>${esc(p.started_at || (p.created_at || "").slice(0, 10))} · ${esc(p.status_label_ar)}</strong>
                  <small>${esc(p.gpa_label)} · ${esc(p.outcome_label_ar || "")} · ${esc(p.delivery_type_label_ar || "")}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا أحمال سابقة مسجّلة</div>'}</div>
          </details>
        </div>`;

      bind();
    }

    function closePregnancyForm(pregnancyId) {
      openModal(
        "إنهاء سجل الحمل",
        `<div class="cx-field"><label>تاريخ الإنهاء</label><input class="cx-input" id="pr_end" type="date"></div>
         <div class="cx-field"><label>النتيجة</label><select class="cx-select" id="pr_out"><option value="">—</option>${(ctx.catalog?.outcomes || [])
           .map((o) => `<option value="${esc(o.code)}">${esc(o.label_ar)}</option>`)
           .join("")}</select></div>
         <div class="cx-field"><label>نوع الولادة</label><select class="cx-select" id="pr_del"><option value="">—</option>${(ctx.catalog?.delivery_types || [])
           .map((o) => `<option value="${esc(o.code)}">${esc(o.label_ar)}</option>`)
           .join("")}</select></div>
         <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="pr_notes"></textarea></div>`,
        async () => {
          await api(`/clinics/api/pregnancies/${pregnancyId}`, {
            method: "PATCH",
            body: JSON.stringify({
              close: true,
              status: "completed",
              ended_at: document.getElementById("pr_end").value || null,
              outcome: document.getElementById("pr_out").value || null,
              delivery_type: document.getElementById("pr_del").value || null,
              notes: document.getElementById("pr_notes").value,
            }),
          });
          showNotice("تم إنهاء سجل الحمل", false);
          await reload();
        }
      );
    }

    function bind() {
      el.querySelectorAll("[data-close-id]").forEach((btn) => {
        btn.onclick = () => closePregnancyForm(btn.dataset.closeId);
      });

      el.querySelector("[data-edit-profile]")?.addEventListener("click", () => {
        const p = ctx.profile || {};
        openModal(
          "الملف النسائي",
          `<div class="cx-field-row">
            <div class="cx-field"><label>عمر الحيض</label><input class="cx-input" id="gyn_menarche" type="number" value="${esc(p.menarche_age ?? "")}"></div>
            <div class="cx-field"><label>دورة منتظمة</label><select class="cx-select" id="gyn_reg"><option value="">—</option><option value="1" ${p.cycle_regular === true ? "selected" : ""}>نعم</option><option value="0" ${p.cycle_regular === false ? "selected" : ""}>لا</option></select></div>
          </div>
          <div class="cx-field-row">
            <div class="cx-field"><label>طول الدورة (يوم)</label><input class="cx-input" id="gyn_len" type="number" value="${esc(p.cycle_length_days ?? "")}"></div>
            <div class="cx-field"><label>مدة النزف</label><input class="cx-input" id="gyn_bleed" type="number" value="${esc(p.bleeding_duration_days ?? "")}"></div>
          </div>
          <div class="cx-field"><label>آخر دورة (عامة)</label><input class="cx-input" id="gyn_lmp" type="date" value="${esc(p.last_menstrual_period || "")}"></div>
          <div class="cx-field"><label>التاريخ النسائي</label><textarea class="cx-textarea" id="gyn_hist">${esc(p.gynecologic_history || "")}</textarea></div>
          <div class="cx-field"><label>عمليات سابقة</label><textarea class="cx-textarea" id="gyn_surg">${esc(p.previous_gynecologic_surgeries || "")}</textarea></div>
          <div class="cx-field"><label>ملاحظات منع الحمل</label><textarea class="cx-textarea" id="gyn_contra">${esc(p.contraception_notes || "")}</textarea></div>`,
          async () => {
            const reg = document.getElementById("gyn_reg").value;
            await api(`/clinics/api/patients/${patientId}/gynecology-profile`, {
              method: "PUT",
              body: JSON.stringify({
                menarche_age: document.getElementById("gyn_menarche").value || null,
                cycle_regular: reg === "" ? null : reg === "1",
                cycle_length_days: document.getElementById("gyn_len").value || null,
                bleeding_duration_days: document.getElementById("gyn_bleed").value || null,
                last_menstrual_period: document.getElementById("gyn_lmp").value || null,
                gynecologic_history: document.getElementById("gyn_hist").value,
                previous_gynecologic_surgeries: document.getElementById("gyn_surg").value,
                contraception_notes: document.getElementById("gyn_contra").value,
              }),
            });
            showNotice("تم حفظ الملف النسائي", false);
            await reload();
          }
        );
      });

      el.querySelector("[data-new-preg]")?.addEventListener("click", () => {
        openModal(
          "تسجيل حمل",
          `<div class="cx-field"><label>آخر دورة (LMP)</label><input class="cx-input" id="pr_lmp" type="date"></div>
           <div class="cx-field"><label>موعد الولادة المتوقع (EDD)</label><input class="cx-input" id="pr_edd" type="date"><small>يمكن تركه فارغاً واستخدام الاقتراح من LMP</small></div>
           <label><input type="checkbox" id="pr_use_sug"> استخدام EDD المحسوب من LMP (يتطلب تأكيد الطبيب)</label>
           <div class="cx-field"><label>طريقة التأريخ</label><select class="cx-select" id="pr_dating">${(ctx.catalog?.dating_methods || [])
             .map((d) => `<option value="${esc(d.code)}">${esc(d.label_ar)}</option>`)
             .join("")}</select></div>
           <div class="cx-field-row">
             <div class="cx-field"><label>Gravida</label><input class="cx-input" id="pr_g" type="number" min="0"></div>
             <div class="cx-field"><label>Para</label><input class="cx-input" id="pr_p" type="number" min="0"></div>
             <div class="cx-field"><label>Abortions</label><input class="cx-input" id="pr_a" type="number" min="0"></div>
           </div>
           <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="pr_notes"></textarea></div>`,
          async () => {
            await api(`/clinics/api/patients/${patientId}/pregnancies`, {
              method: "POST",
              body: JSON.stringify({
                lmp_date: document.getElementById("pr_lmp").value || null,
                edd_date: document.getElementById("pr_edd").value || null,
                use_suggested_edd: document.getElementById("pr_use_sug").checked,
                dating_method: document.getElementById("pr_dating").value,
                gravida_at_start: document.getElementById("pr_g").value || null,
                para_at_start: document.getElementById("pr_p").value || null,
                abortions_at_start: document.getElementById("pr_a").value || null,
                notes: document.getElementById("pr_notes").value,
                doctor_id: doctorId || null,
              }),
            });
            showNotice("تم تسجيل الحمل", false);
            await reload();
          }
        );
      });

      el.querySelector("[data-edit-preg]")?.addEventListener("click", () => {
        const a = ctx.active_pregnancy;
        if (!a) return;
        openModal(
          "تعديل سجل الحمل",
          `<div class="cx-field"><label>LMP</label><input class="cx-input" id="pr_lmp" type="date" value="${esc(a.lmp_date || "")}"></div>
           <div class="cx-field"><label>EDD</label><input class="cx-input" id="pr_edd" type="date" value="${esc(a.edd_date || "")}"></div>
           <label><input type="checkbox" id="pr_use_sug"> استبدال EDD بالاقتراح من LMP</label>
           <div class="cx-field"><label>طريقة التأريخ</label><select class="cx-select" id="pr_dating">${(ctx.catalog?.dating_methods || [])
             .map(
               (d) =>
                 `<option value="${esc(d.code)}" ${d.code === a.dating_method ? "selected" : ""}>${esc(d.label_ar)}</option>`
             )
             .join("")}</select></div>
           <div class="cx-field-row">
             <div class="cx-field"><label>G</label><input class="cx-input" id="pr_g" type="number" value="${esc(a.gravida_at_start ?? "")}"></div>
             <div class="cx-field"><label>P</label><input class="cx-input" id="pr_p" type="number" value="${esc(a.para_at_start ?? "")}"></div>
             <div class="cx-field"><label>A</label><input class="cx-input" id="pr_a" type="number" value="${esc(a.abortions_at_start ?? "")}"></div>
           </div>`,
          async () => {
            await api(`/clinics/api/pregnancies/${a.id}`, {
              method: "PATCH",
              body: JSON.stringify({
                lmp_date: document.getElementById("pr_lmp").value || null,
                edd_date: document.getElementById("pr_edd").value || null,
                use_suggested_edd: document.getElementById("pr_use_sug").checked,
                dating_method: document.getElementById("pr_dating").value,
                gravida_at_start: document.getElementById("pr_g").value || null,
                para_at_start: document.getElementById("pr_p").value || null,
                abortions_at_start: document.getElementById("pr_a").value || null,
              }),
            });
            showNotice("تم تحديث سجل الحمل", false);
            await reload();
          }
        );
      });

      el.querySelector("[data-close-preg]")?.addEventListener("click", () => {
        const a = ctx.active_pregnancy;
        if (a) closePregnancyForm(a.id);
      });

      el.querySelector("[data-add-obs]")?.addEventListener("click", () => {
        const a = ctx.active_pregnancy;
        if (!a) return;
        openModal(
          "ملاحظة حمل",
          `<div class="cx-field-row">
             <div class="cx-field"><label>أسابيع</label><input class="cx-input" id="ob_w" type="number" placeholder="تلقائي من التأريخ"></div>
             <div class="cx-field"><label>أيام</label><input class="cx-input" id="ob_d" type="number" min="0" max="6"></div>
           </div>
           <div class="cx-field-row">
             <div class="cx-field"><label>ارتفاع رحمي (سم)</label><input class="cx-input" id="ob_fh" type="number" step="0.1"></div>
             <div class="cx-field"><label>نبض الجنين</label><input class="cx-input" id="ob_fhr" type="number"></div>
           </div>
           <div class="cx-field"><label>المجيء</label><input class="cx-input" id="ob_pres"></div>
           <div class="cx-field"><label>حركة الجنين</label><textarea class="cx-textarea" id="ob_fm"></textarea></div>
           <div class="cx-field"><label>وذمة</label><textarea class="cx-textarea" id="ob_ed"></textarea></div>
           <div class="cx-field"><label>ملاحظات سريرية</label><textarea class="cx-textarea" id="ob_notes"></textarea></div>`,
          async () => {
            await api(`/clinics/api/pregnancies/${a.id}/observations`, {
              method: "POST",
              body: JSON.stringify({
                visit_id: visitId || null,
                doctor_id: doctorId || null,
                gestational_age_weeks: document.getElementById("ob_w").value || null,
                gestational_age_days: document.getElementById("ob_d").value || null,
                fundal_height_cm: document.getElementById("ob_fh").value || null,
                fetal_heart_rate: document.getElementById("ob_fhr").value || null,
                presentation: document.getElementById("ob_pres").value,
                fetal_movement_notes: document.getElementById("ob_fm").value,
                edema_notes: document.getElementById("ob_ed").value,
                clinical_notes: document.getElementById("ob_notes").value,
              }),
            });
            showNotice("تم حفظ ملاحظة الحمل", false);
            await reload();
          }
        );
      });
    }

    paint();
    return { reload };
  }

  window.ClinicsGynecologyTools = { mount };
})();
