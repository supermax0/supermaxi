/* Cardiology clinical pack — reuses Phase F longitudinal engines; no auto scoring. */
(() => {
  const esc = (v) =>
    String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  async function mount(el, opts) {
    const { patientId, visitId, doctorId, api, showNotice, openModal, readonly } = opts;
    const endpoint = visitId
      ? `/clinics/api/visits/${visitId}/cardiology-context`
      : `/clinics/api/patients/${patientId}/cardiology-context`;
    let ctx = await api(endpoint);
    let vitalFull = null;
    let labFull = null;
    const canEdit = !readonly && ctx.permissions?.can_edit !== false;
    const pid = patientId || ctx.patient_id;

    async function reload() {
      ctx = await api(endpoint);
      paint();
    }

    function paint() {
      const summary = ctx.summary || {};
      const profile = ctx.profile || {};
      const factors = ctx.risk_factors || [];
      const conditions = (ctx.conditions && ctx.conditions.items) || summary.cardiac_conditions || [];
      const meds = (ctx.medications && ctx.medications.active) || summary.current_medications || [];
      const ecgs = ctx.recent_ecgs || [];
      const echos = ctx.recent_echos || [];
      const labs = ctx.relevant_labs || {};
      const latest = (ctx.vital_trends_summary && ctx.vital_trends_summary.latest) || {};
      const catalog = ctx.catalog || {};

      el.innerHTML = `
        <div class="cx-cardio" dir="rtl">
          <section class="cx-cardio__summary">
            <div><span>حالات قلبية</span><strong>${esc(conditions.length)}</strong></div>
            <div><span>ضغط</span><strong>${esc(summary.latest_bp || latest.blood_pressure || "—")}</strong></div>
            <div><span>نبض</span><strong>${esc(summary.latest_pulse ?? latest.heart_rate ?? "—")}</strong></div>
            <div><span>وزن / SpO2</span><strong>${esc(summary.latest_weight ?? latest.weight_kg ?? "—")} / ${esc(summary.latest_spo2 ?? latest.oxygen_sat ?? "—")}</strong></div>
            <div><span>آخر ECG</span><strong>${esc(summary.latest_ecg?.rhythm || (summary.latest_ecg ? "مسجّل" : "—"))}</strong></div>
            <div><span>EF</span><strong>${esc(summary.latest_echo?.lvef_percent ?? "—")}</strong></div>
          </section>
          <p class="cx-cardio__note">بدون تفسير تلقائي لـ ECG/Echo أو حساب مخاطر قلبية أو توصيات دوائية.</p>
          ${summary.allergies ? `<p class="cx-cardio__note" style="color:var(--cx-danger);font-weight:700">⚠ حساسية: ${esc(summary.allergies)}</p>` : ""}

          <details class="cx-cardio__block" open>
            <summary>التاريخ القلبي والجهاز</summary>
            <div class="cx-cardio__grid">
              <div><span>التدخين</span><strong>${esc(profile.smoking_status_label_ar || "—")}</strong></div>
              <div><span>جهاز</span><strong>${esc(profile.device_type_label_ar || "—")}</strong></div>
              <div><span>احتشاء سابق</span><strong>${esc(profile.previous_mi_date || "—")}</strong></div>
            </div>
            <p><small>${esc(profile.family_cardiac_history || "بدون تاريخ عائلي مسجّل")}</small></p>
            <p><small>${esc(profile.other_cardiac_history || "")}</small></p>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm" data-edit-profile>تعديل التاريخ القلبي</button>' : ""}
          </details>

          <details class="cx-cardio__block" open>
            <summary>عوامل الخطورة (من السجل — بدون حساب نقاط)</summary>
            <div class="cx-cardio__chips">${factors
              .map(
                (f) =>
                  `<span class="${f.present ? "is-on" : ""}">${esc(f.label_ar)}${f.present ? " ✓" : ""}</span>`
              )
              .join("")}</div>
            <h4 style="margin:12px 0 8px">أمراض مزمنة قلبية (ClinicChronicCondition)</h4>
            <div class="cx-feed">${conditions
              .map(
                (c) =>
                  `<article class="cx-feed__item"><strong>${esc(c.condition_name || c.condition_label_ar)}</strong>
                  <small>${esc(c.status_label_ar)} · ${esc(c.diagnosis_date || "—")}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا حالات قلبية نشطة في السجل المزمن</div>'}</div>
            ${
              canEdit
                ? '<button type="button" class="cx-btn cx-btn--sm" data-add-cond>+ مرض قلبي مزمن</button>'
                : ""
            }
          </details>

          <details class="cx-cardio__block" open>
            <summary>ECG</summary>
            <div class="cx-feed">${ecgs
              .map(
                (e) =>
                  `<article class="cx-feed__item"><strong>${esc((e.recorded_at || "").slice(0, 16))}</strong>
                  <small>معدل ${esc(e.heart_rate ?? "—")} · نظم ${esc(e.rhythm || "—")}</small>
                  <p>${esc(e.interpretation || "")}</p>
                  ${
                    canEdit
                      ? `<button type="button" class="cx-btn cx-btn--sm" data-archive-ecg="${e.id}">أرشفة</button>`
                      : ""
                  }</article>`
              )
              .join("") || '<div class="cx-empty">لا تخطيطات مسجّلة</div>'}</div>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--primary cx-btn--sm" data-add-ecg>+ تسجيل ECG</button>' : ""}
          </details>

          <details class="cx-cardio__block" open>
            <summary>Echo</summary>
            <div class="cx-feed">${echos
              .map(
                (e) =>
                  `<article class="cx-feed__item"><strong>${esc((e.recorded_at || "").slice(0, 16))} · EF ${esc(e.lvef_percent ?? "—")}</strong>
                  <p>${esc(e.impression || "")}</p>
                  ${
                    canEdit
                      ? `<button type="button" class="cx-btn cx-btn--sm" data-archive-echo="${e.id}">أرشفة</button>`
                      : ""
                  }</article>`
              )
              .join("") || '<div class="cx-empty">لا سجلات إيكو</div>'}</div>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--primary cx-btn--sm" data-add-echo>+ تسجيل Echo</button>' : ""}
          </details>

          <details class="cx-cardio__block">
            <summary>المؤشرات والاتجاهات (محرك Phase F)</summary>
            <div class="cx-actions" style="margin-bottom:8px">
              <button type="button" class="cx-btn cx-btn--sm" data-load-vitals>تحميل اتجاهات حيوية</button>
              <button type="button" class="cx-btn cx-btn--sm" data-load-labs>تحميل تحاليل قلبية</button>
            </div>
            <div id="cardioTrends">
              ${
                vitalFull
                  ? `<div class="cx-cardio__grid">
                      <div><span>انقباضي</span><strong>${esc((vitalFull.series?.systolic || []).slice(-1)[0]?.value ?? "—")}</strong></div>
                      <div><span>نبض نقاط</span><strong>${esc((vitalFull.series?.heart_rate || []).length)}</strong></div>
                      <div><span>وزن نقاط</span><strong>${esc((vitalFull.series?.weight_kg || []).length)}</strong></div>
                    </div>`
                  : `<div class="cx-cardio__grid">
                      <div><span>آخر ضغط</span><strong>${esc(latest.blood_pressure || "—")}</strong></div>
                      <div><span>آخر نبض</span><strong>${esc(latest.heart_rate ?? "—")}</strong></div>
                    </div>`
              }
              ${
                labFull || Object.keys(labs).length
                  ? `<div class="cx-feed">${Object.entries(labFull?.latest || labs)
                      .map(
                        ([k, v]) =>
                          `<article class="cx-feed__item"><strong>${esc(k)}</strong>
                          <small>${esc(v.value)} ${esc(v.unit || "")} · ${esc((v.at || "").slice(0, 10))}</small></article>`
                      )
                      .join("")}</div>`
                  : '<div class="cx-empty">لا تحاليل رقمية مطابقة بعد</div>'
              }
            </div>
          </details>

          <details class="cx-cardio__block">
            <summary>الأدوية الحالية (ClinicPatientMedication)</summary>
            <div class="cx-feed">${meds
              .map(
                (m) =>
                  `<article class="cx-feed__item"><strong>${esc(m.drug_name)}</strong>
                  <small>${esc(m.dose_text)} · ${esc(m.frequency)}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا أدوية حالية مؤكدة</div>'}</div>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm" data-add-med>+ دواء حالي</button>' : ""}
            <p class="cx-cardio__note">متابعة: ${esc(summary.next_followup?.due_date || ctx.next_followup?.due_date || "—")}</p>
          </details>
        </div>`;

      wire(catalog);
    }

    function wire(catalog) {
      el.querySelector("[data-edit-profile]")?.addEventListener("click", () => {
        const p = ctx.profile || {};
        openModal(
          "التاريخ القلبي",
          `<div class="cx-field"><label>التدخين</label><select class="cx-select" id="cSmoke">${(catalog.smoking || [])
            .map((s) => `<option value="${esc(s.code)}" ${s.code === p.smoking_status ? "selected" : ""}>${esc(s.label_ar)}</option>`)
            .join("")}</select></div>
           <div class="cx-field"><label>ملاحظات التدخين</label><input class="cx-input" id="cSmokeNotes" value="${esc(p.smoking_notes || "")}"></div>
           <div class="cx-field"><label>تاريخ عائلي</label><textarea class="cx-input" id="cFamily">${esc(p.family_cardiac_history || "")}</textarea></div>
           <div class="cx-field"><label>احتشاء سابق</label><input class="cx-input" type="date" id="cMi" value="${esc(p.previous_mi_date || "")}"></div>
           <div class="cx-field"><label>PCI</label><textarea class="cx-input" id="cPci">${esc(p.previous_pci_notes || "")}</textarea></div>
           <div class="cx-field"><label>CABG</label><textarea class="cx-input" id="cCabg">${esc(p.previous_cabg_notes || "")}</textarea></div>
           <div class="cx-field"><label>جهاز</label><select class="cx-select" id="cDevice">${(catalog.devices || [])
             .map((d) => `<option value="${esc(d.code)}" ${d.code === p.device_type ? "selected" : ""}>${esc(d.label_ar)}</option>`)
             .join("")}</select></div>
           <div class="cx-field"><label>تاريخ الزرع</label><input class="cx-input" type="date" id="cDeviceDate" value="${esc(p.device_implant_date || "")}"></div>
           <div class="cx-field"><label>ملاحظات الجهاز</label><textarea class="cx-input" id="cDeviceNotes">${esc(p.device_history || "")}</textarea></div>
           <div class="cx-field"><label>تاريخ قلبي آخر</label><textarea class="cx-input" id="cOther">${esc(p.other_cardiac_history || "")}</textarea></div>`,
          async () => {
            await api(`/clinics/api/patients/${pid}/cardiology-profile`, {
              method: "PUT",
              body: JSON.stringify({
                smoking_status: document.getElementById("cSmoke").value,
                smoking_notes: document.getElementById("cSmokeNotes").value,
                family_cardiac_history: document.getElementById("cFamily").value,
                previous_mi_date: document.getElementById("cMi").value || null,
                previous_pci_notes: document.getElementById("cPci").value,
                previous_cabg_notes: document.getElementById("cCabg").value,
                device_type: document.getElementById("cDevice").value,
                device_implant_date: document.getElementById("cDeviceDate").value || null,
                device_history: document.getElementById("cDeviceNotes").value,
                other_cardiac_history: document.getElementById("cOther").value,
              }),
            });
            showNotice("تم حفظ التاريخ القلبي", false);
            await reload();
          }
        );
      });

      el.querySelector("[data-add-cond]")?.addEventListener("click", () => {
        openModal(
          "مرض قلبي مزمن",
          `<div class="cx-field"><label>النوع</label><select class="cx-select" id="cCond">${(catalog.cardiac_conditions || [])
            .map((c) => `<option value="${esc(c.code)}">${esc(c.label_ar)}</option>`)
            .join("")}</select></div>
           <div class="cx-field"><label>الحالة</label><select class="cx-select" id="cStatus">
             <option value="active">نشط</option><option value="controlled">متحكم به</option>
           </select></div>
           <div class="cx-field"><label>تاريخ التشخيص</label><input class="cx-input" type="date" id="cDate"></div>`,
          async () => {
            const code = document.getElementById("cCond").value;
            const label = (catalog.cardiac_conditions || []).find((c) => c.code === code)?.label_ar || code;
            await api(`/clinics/api/patients/${pid}/chronic-conditions`, {
              method: "POST",
              body: JSON.stringify({
                condition_code: code,
                condition_name: label,
                status: document.getElementById("cStatus").value,
                diagnosis_date: document.getElementById("cDate").value || null,
                doctor_id: doctorId || null,
              }),
            });
            showNotice("تمت الإضافة للسجل المزمن", false);
            await reload();
          }
        );
      });

      el.querySelector("[data-add-ecg]")?.addEventListener("click", () => {
        openModal(
          "تسجيل ECG",
          `<div class="cx-field"><label>معدل القلب</label><input class="cx-input" id="ecgHr" type="number"></div>
           <div class="cx-field"><label>النظم</label><input class="cx-input" id="ecgRhythm"></div>
           <div class="cx-field"><label>المحور</label><input class="cx-input" id="ecgAxis"></div>
           <div class="cx-field"><label>PR / QRS / QTc (ms)</label>
             <div style="display:flex;gap:6px"><input class="cx-input" id="ecgPr" type="number" placeholder="PR">
             <input class="cx-input" id="ecgQrs" type="number" placeholder="QRS">
             <input class="cx-input" id="ecgQtc" type="number" placeholder="QTc"></div></div>
           <div class="cx-field"><label>ST-T</label><textarea class="cx-input" id="ecgSt"></textarea></div>
           <div class="cx-field"><label>التفسير (يدوي)</label><textarea class="cx-input" id="ecgInterp"></textarea></div>
           <div class="cx-field"><label>ملاحظات</label><textarea class="cx-input" id="ecgNotes"></textarea></div>`,
          async () => {
            await api(`/clinics/api/patients/${pid}/cardiology/ecgs`, {
              method: "POST",
              body: JSON.stringify({
                visit_id: visitId || null,
                doctor_id: doctorId || null,
                heart_rate: document.getElementById("ecgHr").value,
                rhythm: document.getElementById("ecgRhythm").value,
                axis: document.getElementById("ecgAxis").value,
                pr_interval_ms: document.getElementById("ecgPr").value,
                qrs_duration_ms: document.getElementById("ecgQrs").value,
                qtc_ms: document.getElementById("ecgQtc").value,
                st_t_notes: document.getElementById("ecgSt").value,
                interpretation: document.getElementById("ecgInterp").value,
                notes: document.getElementById("ecgNotes").value,
              }),
            });
            showNotice("تم تسجيل ECG", false);
            await reload();
          }
        );
      });

      el.querySelectorAll("[data-archive-ecg]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api(`/clinics/api/cardiology/ecgs/${btn.getAttribute("data-archive-ecg")}`, {
            method: "PATCH",
            body: JSON.stringify({ archive: true }),
          });
          showNotice("تمت الأرشفة", false);
          await reload();
        });
      });

      el.querySelector("[data-add-echo]")?.addEventListener("click", () => {
        openModal(
          "تسجيل Echo",
          `<div class="cx-field"><label>LVEF %</label><input class="cx-input" id="echoEf" type="number" step="0.1"></div>
           <div class="cx-field"><label>البطين الأيسر</label><textarea class="cx-input" id="echoLv"></textarea></div>
           <div class="cx-field"><label>الصمامات</label><textarea class="cx-input" id="echoValve"></textarea></div>
           <div class="cx-field"><label>الانطباع</label><textarea class="cx-input" id="echoImp"></textarea></div>
           <div class="cx-field"><label>ملاحظات</label><textarea class="cx-input" id="echoNotes"></textarea></div>`,
          async () => {
            await api(`/clinics/api/patients/${pid}/cardiology/echos`, {
              method: "POST",
              body: JSON.stringify({
                visit_id: visitId || null,
                doctor_id: doctorId || null,
                lvef_percent: document.getElementById("echoEf").value,
                lv_notes: document.getElementById("echoLv").value,
                valve_notes: document.getElementById("echoValve").value,
                impression: document.getElementById("echoImp").value,
                notes: document.getElementById("echoNotes").value,
              }),
            });
            showNotice("تم تسجيل Echo", false);
            await reload();
          }
        );
      });

      el.querySelectorAll("[data-archive-echo]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api(`/clinics/api/cardiology/echos/${btn.getAttribute("data-archive-echo")}`, {
            method: "PATCH",
            body: JSON.stringify({ archive: true }),
          });
          showNotice("تمت الأرشفة", false);
          await reload();
        });
      });

      el.querySelector("[data-load-vitals]")?.addEventListener("click", async () => {
        vitalFull = await api(`/clinics/api/patients/${pid}/vital-trends?range=6m`);
        paint();
      });
      el.querySelector("[data-load-labs]")?.addEventListener("click", async () => {
        labFull = await api(
          `/clinics/api/patients/${pid}/lab-trends?range=1y&analytes=${encodeURIComponent(
            "troponin,bnp,ldl,hdl,creatinine,potassium,sodium,hemoglobin,hba1c"
          )}`
        );
        paint();
      });

      el.querySelector("[data-add-med]")?.addEventListener("click", () => {
        openModal(
          "دواء حالي",
          `<div class="cx-field"><label>اسم الدواء</label><input class="cx-input" id="medName"></div>
           <div class="cx-field"><label>الجرعة</label><input class="cx-input" id="medDose"></div>
           <div class="cx-field"><label>التكرار</label><input class="cx-input" id="medFreq"></div>`,
          async () => {
            await api(`/clinics/api/patients/${pid}/medications`, {
              method: "POST",
              body: JSON.stringify({
                drug_name: document.getElementById("medName").value,
                dose_text: document.getElementById("medDose").value,
                frequency: document.getElementById("medFreq").value,
                status: "active",
                doctor_id: doctorId || null,
              }),
            });
            showNotice("تم تسجيل الدواء", false);
            await reload();
          }
        );
      });
    }

    paint();
    return { reload };
  }

  window.ClinicsCardiologyTools = { mount };
})();
