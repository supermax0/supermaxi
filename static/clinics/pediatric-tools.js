/* Pediatric clinical pack — growth history, vaccinations, development (no percentiles). */
(() => {
  const esc = (v) =>
    String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function sparkline(series, key) {
    const pts = (series || []).filter((r) => r[key] != null);
    if (pts.length < 2) return '<div class="cx-ped-chart__empty">لا نقاط كافية للرسم</div>';
    const values = pts.map((p) => Number(p[key]));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const w = 280;
    const h = 80;
    const path = pts
      .map((p, i) => {
        const x = (i / (pts.length - 1)) * (w - 8) + 4;
        const y = h - 4 - ((Number(p[key]) - min) / span) * (h - 8);
        return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
    return `<svg class="cx-ped-chart__svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(key)} trend" dir="ltr"><path d="${path}" fill="none" stroke="#0f766e" stroke-width="2"/></svg>`;
  }

  async function mount(el, opts) {
    const { patientId, visitId, doctorId, api, showNotice, openModal, readonly } = opts;
    let ctx = await api(`/clinics/api/patients/${patientId}/pediatric-context`);
    const canEdit = !readonly && ctx.permissions?.can_edit !== false;

    async function reload() {
      ctx = await api(`/clinics/api/patients/${patientId}/pediatric-context`);
      paint();
    }

    function paint() {
      const p = ctx.pediatric_profile || {};
      const latest = ctx.latest_growth || {};
      const age = p.current_age || {};
      el.innerHTML = `
        <div class="cx-ped" dir="rtl">
          <section class="cx-ped__summary">
            <div><span>العمر الحالي</span><strong>${esc(age.age_label || "—")}</strong></div>
            <div><span>آخر وزن</span><strong>${latest.weight_kg != null ? esc(latest.weight_kg) + " كغ" : "—"}</strong></div>
            <div><span>آخر طول</span><strong>${latest.height_cm != null ? esc(latest.height_cm) + " سم" : "—"}</strong></div>
            <div><span>آخر BMI</span><strong>${latest.bmi != null ? esc(latest.bmi) : "—"}</strong></div>
            <div><span>آخر محيط رأس</span><strong>${latest.head_circumference_cm != null ? esc(latest.head_circumference_cm) + " سم" : "—"}</strong></div>
          </section>
          <p class="cx-ped__note">اتجاهات النمو خام فقط — لا توجد نسب مئوية WHO/CDC في هذه المرحلة.</p>

          <details class="cx-ped__block" open>
            <summary>تاريخ الولادة والتغذية</summary>
            <div class="cx-ped__grid">
              <div><span>عمر الحمل</span><strong>${esc(p.gestational_age_weeks ?? "—")}</strong></div>
              <div><span>نوع الولادة</span><strong>${esc(p.delivery_label_ar || "—")}</strong></div>
              <div><span>وزن الولادة</span><strong>${p.birth_weight != null ? esc(p.birth_weight) + " كغ" : "—"}</strong></div>
              <div><span>التغذية</span><strong>${esc(p.feeding_label_ar || "—")}</strong></div>
            </div>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm" data-edit-profile>تعديل الملف</button>' : ""}
          </details>

          <details class="cx-ped__block" open>
            <summary>تاريخ قياسات النمو</summary>
            <div class="cx-ped-charts">
              <div><small>الوزن</small>${sparkline(ctx.growth_series, "weight_kg")}</div>
              <div><small>الطول</small>${sparkline(ctx.growth_series, "height_cm")}</div>
              <div><small>محيط الرأس</small>${sparkline(ctx.growth_series, "head_circumference_cm")}</div>
            </div>
            <div class="cx-feed">
              ${(ctx.growth_history || [])
                .slice(0, 20)
                .map(
                  (r) =>
                    `<article class="cx-feed__item"><strong>${esc((r.recorded_at || "").slice(0, 10))} · ${esc(r.age_label || "")}</strong>
                    <small>وزن ${esc(r.weight_kg ?? "—")} · طول ${esc(r.height_cm ?? "—")} · BMI ${esc(r.bmi ?? "—")} · رأس ${esc(r.head_circumference_cm ?? "—")}</small></article>`
                )
                .join("") || '<div class="cx-empty">لا قياسات نمو بعد</div>'}
            </div>
          </details>

          <details class="cx-ped__block" open>
            <summary>التطعيمات</summary>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-add-vax>+ إضافة تطعيم</button>' : ""}
            <div class="cx-ped-cards">
              ${(ctx.vaccinations || [])
                .map(
                  (v) =>
                    `<article class="cx-ped-card"><strong>${esc(v.vaccine_name)}</strong>
                    <small>${esc(v.dose_label || "")} · ${esc(v.administered_date || "—")} · ${esc(v.source_label_ar)} · ${esc(v.status_label_ar)}</small>
                    ${canEdit ? `<button type="button" class="cx-btn cx-btn--sm" data-edit-vax="${v.id}">تعديل</button>` : ""}</article>`
                )
                .join("") || '<div class="cx-empty">لا تطعيمات مسجّلة</div>'}
            </div>
          </details>

          <details class="cx-ped__block" open>
            <summary>التطور</summary>
            ${canEdit && visitId ? '<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-add-dev>+ ملاحظة تطور</button>' : ""}
            <div class="cx-feed">
              ${(ctx.development_history || [])
                .map((d) => {
                  const domains = Object.values(d.domains || {})
                    .map((x) => `${esc(x.label_ar)}: ${esc(x.status_label_ar)}`)
                    .join(" · ");
                  return `<article class="cx-feed__item"><strong>${esc((d.recorded_at || "").slice(0, 10))} · ${esc(d.doctor_name || "")}</strong>
                    <small>${domains}</small>${d.notes ? `<small>${esc(d.notes)}</small>` : ""}</article>`;
                })
                .join("") || '<div class="cx-empty">لا سجلات تطور</div>'}
            </div>
          </details>
        </div>`;

      el.querySelector("[data-edit-profile]")?.addEventListener("click", () => {
        const cat = ctx.catalog || {};
        openModal(
          "الملف الطبي للأطفال",
          `<div class="cx-field-row">
            <div class="cx-field"><label>عمر الحمل (أسابيع)</label><input class="cx-input" id="ppGa" type="number" step="0.1" value="${esc(p.gestational_age_weeks ?? "")}"></div>
            <div class="cx-field"><label>نوع الولادة</label><select class="cx-select" id="ppDel"><option value="">—</option>${(cat.delivery_types || [])
              .map((x) => `<option value="${x.code}" ${p.delivery_type === x.code ? "selected" : ""}>${esc(x.label_ar)}</option>`)
              .join("")}</select></div>
          </div>
          <div class="cx-field-row">
            <div class="cx-field"><label>وزن الولادة (كغ)</label><input class="cx-input" id="ppBw" type="number" step="0.01" value="${esc(p.birth_weight ?? "")}"></div>
            <div class="cx-field"><label>طول الولادة (سم)</label><input class="cx-input" id="ppBl" type="number" step="0.1" value="${esc(p.birth_length ?? "")}"></div>
            <div class="cx-field"><label>محيط رأس الولادة (سم)</label><input class="cx-input" id="ppBhc" type="number" step="0.1" value="${esc(p.birth_head_circumference ?? "")}"></div>
          </div>
          <div class="cx-field"><label><input type="checkbox" id="ppNicu" ${p.nicu_admission ? "checked" : ""}> قبول NICU</label></div>
          <div class="cx-field"><label>أيام NICU</label><input class="cx-input" id="ppNicuDays" type="number" value="${esc(p.nicu_days ?? "")}"></div>
          <div class="cx-field"><label>مضاعفات الوليد</label><textarea class="cx-textarea" id="ppNeo">${esc(p.neonatal_complications || "")}</textarea></div>
          <div class="cx-field"><label>التغذية</label><select class="cx-select" id="ppFeed"><option value="">—</option>${(cat.feeding_types || [])
            .map((x) => `<option value="${x.code}" ${p.feeding_type === x.code ? "selected" : ""}>${esc(x.label_ar)}</option>`)
            .join("")}</select></div>
          <div class="cx-field"><label>ملاحظات التغذية</label><textarea class="cx-textarea" id="ppFeedNotes">${esc(p.feeding_notes || "")}</textarea></div>
          <div class="cx-field"><label>الفطام</label><input class="cx-input" id="ppWean" value="${esc(p.weaning_status || "")}"></div>`,
          async () => {
            await api(`/clinics/api/patients/${patientId}/pediatric-profile`, {
              method: "PUT",
              body: JSON.stringify({
                gestational_age_weeks: document.getElementById("ppGa").value,
                delivery_type: document.getElementById("ppDel").value,
                birth_weight: document.getElementById("ppBw").value,
                birth_length: document.getElementById("ppBl").value,
                birth_head_circumference: document.getElementById("ppBhc").value,
                nicu_admission: document.getElementById("ppNicu").checked,
                nicu_days: document.getElementById("ppNicuDays").value,
                neonatal_complications: document.getElementById("ppNeo").value,
                feeding_type: document.getElementById("ppFeed").value,
                feeding_notes: document.getElementById("ppFeedNotes").value,
                weaning_status: document.getElementById("ppWean").value,
              }),
            });
            await reload();
          }
        );
      });

      el.querySelector("[data-add-vax]")?.addEventListener("click", () => openVaxForm(null));
      el.querySelectorAll("[data-edit-vax]").forEach((btn) => {
        const item = (ctx.vaccinations || []).find((v) => String(v.id) === btn.dataset.editVax);
        btn.onclick = () => openVaxForm(item);
      });
      el.querySelector("[data-add-dev]")?.addEventListener("click", () => openDevForm());
    }

    function openVaxForm(item) {
      const cat = ctx.catalog || {};
      openModal(
        item ? "تعديل تطعيم" : "إضافة تطعيم",
        `<div class="cx-field"><label>اللقاح</label><input class="cx-input" id="vaxName" value="${esc(item?.vaccine_name || "")}"></div>
         <div class="cx-field"><label>الجرعة</label><input class="cx-input" id="vaxDose" value="${esc(item?.dose_label || "")}"></div>
         <div class="cx-field"><label>تاريخ الإعطاء</label><input class="cx-input" type="date" id="vaxDate" value="${esc(item?.administered_date || "")}"></div>
         <div class="cx-field"><label>المصدر</label><select class="cx-select" id="vaxSource">${(cat.vax_sources || [])
           .map((x) => `<option value="${x.code}" ${(item?.source || "clinic") === x.code ? "selected" : ""}>${esc(x.label_ar)}</option>`)
           .join("")}</select></div>
         <div class="cx-field"><label>الحالة</label><select class="cx-select" id="vaxStatus">${(cat.vax_statuses || [])
           .map((x) => `<option value="${x.code}" ${(item?.status || "recorded") === x.code ? "selected" : ""}>${esc(x.label_ar)}</option>`)
           .join("")}</select></div>
         <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="vaxNotes">${esc(item?.notes || "")}</textarea></div>
         ${item ? '<label><input type="checkbox" id="vaxArchive"> أرشفة</label>' : ""}`,
        async () => {
          const payload = {
            vaccine_name: document.getElementById("vaxName").value,
            dose_label: document.getElementById("vaxDose").value,
            administered_date: document.getElementById("vaxDate").value,
            source: document.getElementById("vaxSource").value,
            status: document.getElementById("vaxStatus").value,
            notes: document.getElementById("vaxNotes").value,
            archive: !!document.getElementById("vaxArchive")?.checked,
          };
          if (item) {
            await api(`/clinics/api/pediatric-vaccinations/${item.id}`, { method: "PATCH", body: JSON.stringify(payload) });
          } else {
            await api(`/clinics/api/patients/${patientId}/vaccinations`, { method: "POST", body: JSON.stringify(payload) });
          }
          await reload();
        }
      );
    }

    function openDevForm() {
      const cat = ctx.catalog || {};
      const domainsHtml = (cat.dev_domains || [])
        .map(
          (d) => `
          <fieldset class="cx-ped-domain"><legend>${esc(d.label_ar)}</legend>
            <select class="cx-select" data-dev-status="${d.code}">${(cat.dev_statuses || [])
              .map((s) => `<option value="${s.code}">${esc(s.label_ar)}</option>`)
              .join("")}</select>
            <textarea class="cx-textarea" data-dev-notes="${d.code}" rows="2" placeholder="ملاحظات"></textarea>
          </fieldset>`
        )
        .join("");
      openModal(
        "ملاحظة تطور",
        `${domainsHtml}<div class="cx-field"><label>ملاحظات عامة</label><textarea class="cx-textarea" id="devNotes"></textarea></div>`,
        async () => {
          const domains = {};
          (cat.dev_domains || []).forEach((d) => {
            domains[d.code] = {
              status: el.ownerDocument.querySelector(`[data-dev-status="${d.code}"]`)?.value || "not_assessed",
              notes: el.ownerDocument.querySelector(`[data-dev-notes="${d.code}"]`)?.value || "",
            };
          });
          // modal is in document
          document.querySelectorAll("[data-dev-status]").forEach((sel) => {
            domains[sel.dataset.devStatus] = {
              status: sel.value,
              notes: document.querySelector(`[data-dev-notes="${sel.dataset.devStatus}"]`)?.value || "",
            };
          });
          await api(`/clinics/api/patients/${patientId}/development`, {
            method: "POST",
            body: JSON.stringify({
              visit_id: visitId,
              doctor_id: doctorId,
              domains,
              notes: document.getElementById("devNotes").value,
            }),
          });
          await reload();
          showNotice?.("تم حفظ ملاحظة التطور");
        }
      );
    }

    paint();
    return { reload };
  }

  window.ClinicsPediatricTools = { mount };
})();
