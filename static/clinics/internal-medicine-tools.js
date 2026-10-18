/* Internal Medicine longitudinal pack — no risk scoring / dose calc / recommendations. */
(() => {
  const esc = (v) =>
    String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  const ANALYTE_AR = {
    hba1c: "HbA1c",
    fasting_glucose: "سكر صائم",
    creatinine: "كرياتينين",
    egfr: "eGFR",
    tsh: "TSH",
    free_t4: "Free T4",
    ldl: "LDL",
    hdl: "HDL",
    triglycerides: "دهون ثلاثية",
    total_cholesterol: "كوليسترول كلي",
    hemoglobin: "هيموغلوبين",
    alt: "ALT",
    ast: "AST",
    alp: "ALP",
    bilirubin: "بيليروبين",
  };

  function spark(points, limit = 8) {
    const rows = (points || []).slice(-limit);
    if (!rows.length) return '<div class="cx-empty">لا بيانات</div>';
    return `<div class="cx-im__spark">${rows
      .map((p) => `<span>${esc((p.at || "").slice(0, 10))} · ${esc(p.value)}${p.unit ? " " + esc(p.unit) : ""}</span>`)
      .join("")}</div>`;
  }

  async function mount(el, opts) {
    const { patientId, visitId, doctorId, api, showNotice, openModal, readonly } = opts;
    const endpoint = visitId
      ? `/clinics/api/visits/${visitId}/internal-medicine-context`
      : `/clinics/api/patients/${patientId}/internal-medicine-context`;
    let ctx = await api(endpoint);
    let vitalFull = null;
    let labFull = null;
    let compareData = null;
    const canEdit = !readonly && ctx.permissions?.can_edit !== false;
    const pid = patientId || ctx.patient_id;

    async function reload() {
      ctx = await api(endpoint);
      vitalFull = null;
      labFull = null;
      paint();
    }

    function catalogSelect(list, selected, emptyLabel) {
      return `<option value="">${esc(emptyLabel || "—")}</option>${(list || [])
        .map((c) => `<option value="${esc(c.code)}" ${c.code === selected ? "selected" : ""}>${esc(c.label_ar)}</option>`)
        .join("")}`;
    }

    function paint() {
      const summary = ctx.summary || {};
      const conditions = (ctx.conditions && ctx.conditions.items) || [];
      const active = (ctx.conditions && ctx.conditions.active) || summary.active_conditions || [];
      const meds = (ctx.medications && ctx.medications.active) || summary.current_medications || [];
      const packs = ctx.disease_packs || [];
      const labs = ctx.important_recent_labs || {};
      const alerts = ctx.alerts || [];
      const catalog = ctx.catalog || (ctx.conditions && ctx.conditions.catalog) || {};
      const visits = ctx.recent_visits || [];
      const vt = ctx.vital_trends_summary || {};
      const latest = vt.latest || {};

      const packHtml = packs.length
        ? packs
            .map((p) => {
              const labBits = Object.entries(p.related_labs || {})
                .map(([k, v]) => `${ANALYTE_AR[k] || k}: ${esc(v.value)}${v.unit ? " " + esc(v.unit) : ""}`)
                .join(" · ");
              return `<article class="cx-feed__item"><strong>${esc(p.label_ar)}</strong>
                <small>${labBits || "لا تحاليل مرتبطة حديثة"}</small>
                <small>ضغط ${esc(p.related_vitals?.blood_pressure || "—")} · سكر ${esc(p.related_vitals?.blood_glucose ?? "—")}</small>
                </article>`;
            })
            .join("")
        : '<div class="cx-empty">لا حزم سياقية — أضف أمراضاً مزمنة نشطة</div>';

      el.innerHTML = `
        <div class="cx-im" dir="rtl">
          <section class="cx-im__summary">
            <div><span>أمراض نشطة</span><strong>${esc(active.length)}</strong></div>
            <div><span>أدوية حالية</span><strong>${esc(meds.length)}</strong></div>
            <div><span>ضغط</span><strong>${esc(summary.latest_bp || latest.blood_pressure || "—")}</strong></div>
            <div><span>وزن / BMI</span><strong>${esc(summary.latest_weight ?? latest.weight_kg ?? "—")} / ${esc(summary.latest_bmi ?? latest.bmi ?? "—")}</strong></div>
            <div><span>سكر</span><strong>${esc(summary.latest_glucose ?? latest.blood_glucose ?? "—")}</strong></div>
            <div><span>متابعة</span><strong>${esc(summary.next_followup?.due_date || ctx.next_followup?.due_date || "—")}</strong></div>
          </section>
          ${alerts.map((a) => `<p class="cx-im__alert">${esc(a.message || a)}</p>`).join("")}
          <p class="cx-im__note">أدوات توثيق طولية فقط — بدون توصيات علاجية أو حساب جرعات أو تقييم مخاطر تلقائي.</p>

          <details class="cx-im__block" open>
            <summary>سجل الأمراض المزمنة</summary>
            <div class="cx-feed">${conditions
              .filter((c) => !c.archived_at)
              .map(
                (c) =>
                  `<article class="cx-feed__item"><strong>${esc(c.condition_name)}</strong>
                  <small>${esc(c.status_label_ar)} · ${esc(c.severity_label_ar || "")} · منذ ${esc(c.diagnosis_date || "—")}</small>
                  <p>${esc(c.notes || "")}</p>
                  ${
                    canEdit
                      ? `<div class="cx-actions"><button type="button" class="cx-btn cx-btn--sm" data-edit-cond="${c.id}">تعديل</button>
                         <button type="button" class="cx-btn cx-btn--sm" data-archive-cond="${c.id}">أرشفة</button></div>`
                      : ""
                  }</article>`
              )
              .join("") || '<div class="cx-empty">لا أمراض مزمنة مسجّلة</div>'}</div>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--primary cx-btn--sm" data-add-cond>+ مرض مزمن</button>' : ""}
          </details>

          <details class="cx-im__block" open>
            <summary>الأدوية الحالية (مؤكدة سريرياً)</summary>
            <div class="cx-feed">${meds
              .map(
                (m) =>
                  `<article class="cx-feed__item"><strong>${esc(m.drug_name)}</strong>
                  <small>${esc(m.dose_text)} · ${esc(m.frequency)} · ${esc(m.status_label_ar)}</small>
                  ${
                    canEdit
                      ? `<button type="button" class="cx-btn cx-btn--sm" data-edit-med="${m.id}">تعديل الحالة</button>`
                      : ""
                  }</article>`
              )
              .join("") || '<div class="cx-empty">لا أدوية حالية مؤكدة</div>'}</div>
            ${canEdit ? '<button type="button" class="cx-btn cx-btn--sm" data-add-med>+ دواء حالي</button>' : ""}
            <h4 style="margin:14px 0 8px">من الوصفات السابقة (مرجع فقط)</h4>
            <div class="cx-feed">${((ctx.medications && ctx.medications.prescription_history) || [])
              .slice(0, 8)
              .map(
                (h) =>
                  `<article class="cx-feed__item"><strong>${esc(h.medicine_name)}</strong>
                  <small>${esc((h.at || "").slice(0, 10))} · ${esc(h.dosage)} · ${esc(h.frequency)}</small></article>`
              )
              .join("") || '<div class="cx-empty">لا وصفات سابقة</div>'}</div>
          </details>

          <details class="cx-im__block">
            <summary>اتجاهات العلامات الحيوية</summary>
            <div class="cx-actions" style="margin-bottom:8px">
              <button type="button" class="cx-btn cx-btn--sm" data-load-vitals="6m">6 أشهر</button>
              <button type="button" class="cx-btn cx-btn--sm" data-load-vitals="1y">سنة</button>
              <button type="button" class="cx-btn cx-btn--sm" data-load-vitals="all">الكل</button>
            </div>
            <div id="imVitalTrends">
              ${
                vitalFull
                  ? `<div class="cx-im__grid">
                      <div><span>ضغط انقباضي</span>${spark(vitalFull.series?.systolic)}</div>
                      <div><span>ضغط انبساطي</span>${spark(vitalFull.series?.diastolic)}</div>
                      <div><span>وزن</span>${spark(vitalFull.series?.weight_kg)}</div>
                      <div><span>سكر</span>${spark(vitalFull.series?.blood_glucose)}</div>
                    </div>`
                  : `<div class="cx-im__grid">
                      <div><span>آخر ضغط</span><strong>${esc(latest.blood_pressure || "—")}</strong></div>
                      <div><span>آخر وزن</span><strong>${esc(latest.weight_kg ?? "—")}</strong></div>
                      <div><span>نقاط ضغط</span><strong>${esc((vt.counts && vt.counts.systolic) || 0)}</strong></div>
                    </div>
                    <p class="cx-im__note">حمّل الاتجاه الكامل عند الحاجة (تحميل كسول).</p>`
              }
            </div>
          </details>

          <details class="cx-im__block">
            <summary>اتجاهات التحاليل المهمة</summary>
            <div class="cx-actions" style="margin-bottom:8px">
              <button type="button" class="cx-btn cx-btn--sm" data-load-labs>تحميل الاتجاهات</button>
            </div>
            <div id="imLabTrends">
              ${
                labFull
                  ? Object.keys(labFull.series || {})
                      .map((k) => {
                        const byUnit = labFull.series[k] || {};
                        const unit = Object.keys(byUnit)[0];
                        return `<div><strong>${esc(ANALYTE_AR[k] || k)}</strong>${spark(unit ? byUnit[unit] : [])}</div>`;
                      })
                      .join("") || '<div class="cx-empty">لا نتائج رقمية مطابقة</div>'
                  : Object.entries(labs)
                      .map(
                        ([k, v]) =>
                          `<div class="cx-feed__item"><strong>${esc(ANALYTE_AR[k] || k)}</strong>
                          <small>${esc(v.value)} ${esc(v.unit || "")} · ${esc((v.at || "").slice(0, 10))}</small></div>`
                      )
                      .join("") || '<div class="cx-empty">لا تحاليل حديثة مرتبطة</div>'
              }
            </div>
          </details>

          <details class="cx-im__block">
            <summary>حزم سياقية حسب المرض</summary>
            <div class="cx-feed">${packHtml}</div>
          </details>

          <details class="cx-im__block">
            <summary>مقارنة زيارات</summary>
            <div class="cx-field">
              <label>اختر زيارتين أو أكثر</label>
              <select class="cx-select" id="imCompareVisits" multiple size="4" style="min-height:90px">
                ${visits
                  .map(
                    (v) =>
                      `<option value="${v.id}">${esc(v.visit_date || "")} · ${esc(v.chief_complaint || "زيارة #" + v.id)}</option>`
                  )
                  .join("")}
              </select>
            </div>
            <button type="button" class="cx-btn cx-btn--sm" data-compare>مقارنة</button>
            <div id="imCompareResult" class="cx-im__compare">
              ${(compareData && compareData.visits
                ? compareData.visits
                    .map(
                      (card) =>
                        `<article><h4>${esc(card.visit_date || "#" + card.visit_id)}</h4>
                        <small>ضغط ${esc(card.vitals?.blood_pressure || "—")} · وزن ${esc(card.vitals?.weight_kg ?? "—")}</small>
                        <p>${(card.diagnoses || []).map((d) => esc(d.title)).join("، ") || "بدون تشخيص"}</p>
                        <p>${(card.medications || []).map((m) => esc(m.medicine_name)).join("، ") || "بدون أدوية"}</p>
                        <p>${esc((card.clinical_notes || "").slice(0, 120))}</p></article>`
                    )
                    .join("")
                : "") || ""}
            </div>
          </details>
        </div>`;

      wire(catalog);
    }

    function wire(catalog) {
      el.querySelector("[data-add-cond]")?.addEventListener("click", () => {
        openModal(
          "إضافة مرض مزمن",
          `<div class="cx-field"><label>النوع</label><select class="cx-select" id="imCondCode">${catalogSelect(catalog.codes, "diabetes")}</select></div>
           <div class="cx-field"><label>الاسم</label><input class="cx-input" id="imCondName" value="السكري"></div>
           <div class="cx-field"><label>الحالة</label><select class="cx-select" id="imCondStatus">${catalogSelect(catalog.statuses, "active")}</select></div>
           <div class="cx-field"><label>الشدة</label><select class="cx-select" id="imCondSev">${catalogSelect(catalog.severities, "unspecified")}</select></div>
           <div class="cx-field"><label>تاريخ التشخيص</label><input class="cx-input" type="date" id="imCondDate"></div>
           <div class="cx-field"><label>ملاحظات</label><textarea class="cx-input" id="imCondNotes"></textarea></div>`,
          async () => {
            const code = document.getElementById("imCondCode").value || "other";
            const label = (catalog.codes || []).find((c) => c.code === code)?.label_ar || "";
            await api(`/clinics/api/patients/${pid}/chronic-conditions`, {
              method: "POST",
              body: JSON.stringify({
                condition_code: code,
                condition_name: document.getElementById("imCondName").value || label,
                status: document.getElementById("imCondStatus").value || "active",
                severity: document.getElementById("imCondSev").value || null,
                diagnosis_date: document.getElementById("imCondDate").value || null,
                notes: document.getElementById("imCondNotes").value || "",
                doctor_id: doctorId || null,
              }),
            });
            showNotice("تم إضافة المرض المزمن", false);
            await reload();
          }
        );
        const codeEl = document.getElementById("imCondCode");
        const nameEl = document.getElementById("imCondName");
        codeEl?.addEventListener("change", () => {
          const hit = (catalog.codes || []).find((c) => c.code === codeEl.value);
          if (hit && hit.code !== "other") nameEl.value = hit.label_ar;
        });
      });

      el.querySelectorAll("[data-edit-cond]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-edit-cond");
          const row = ((ctx.conditions && ctx.conditions.items) || []).find((c) => String(c.id) === String(id));
          if (!row) return;
          openModal(
            "تعديل مرض مزمن",
            `<div class="cx-field"><label>الاسم</label><input class="cx-input" id="imCondName" value="${esc(row.condition_name)}"></div>
             <div class="cx-field"><label>الحالة</label><select class="cx-select" id="imCondStatus">${catalogSelect(catalog.statuses, row.status)}</select></div>
             <div class="cx-field"><label>الشدة</label><select class="cx-select" id="imCondSev">${catalogSelect(catalog.severities, row.severity || "unspecified")}</select></div>
             <div class="cx-field"><label>تاريخ التشخيص</label><input class="cx-input" type="date" id="imCondDate" value="${esc(row.diagnosis_date || "")}"></div>
             <div class="cx-field"><label>ملاحظات</label><textarea class="cx-input" id="imCondNotes">${esc(row.notes || "")}</textarea></div>`,
            async () => {
              await api(`/clinics/api/chronic-conditions/${id}`, {
                method: "PATCH",
                body: JSON.stringify({
                  condition_name: document.getElementById("imCondName").value,
                  status: document.getElementById("imCondStatus").value,
                  severity: document.getElementById("imCondSev").value || null,
                  diagnosis_date: document.getElementById("imCondDate").value || null,
                  notes: document.getElementById("imCondNotes").value || "",
                }),
              });
              showNotice("تم التحديث", false);
              await reload();
            }
          );
        });
      });

      el.querySelectorAll("[data-archive-cond]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await api(`/clinics/api/chronic-conditions/${btn.getAttribute("data-archive-cond")}`, {
            method: "PATCH",
            body: JSON.stringify({ archive: true }),
          });
          showNotice("تمت الأرشفة", false);
          await reload();
        });
      });

      el.querySelector("[data-add-med]")?.addEventListener("click", () => {
        openModal(
          "دواء حالي",
          `<div class="cx-field"><label>اسم الدواء</label><input class="cx-input" id="imMedName"></div>
           <div class="cx-field"><label>الجرعة</label><input class="cx-input" id="imMedDose"></div>
           <div class="cx-field"><label>التكرار</label><input class="cx-input" id="imMedFreq"></div>
           <div class="cx-field"><label>تاريخ البدء</label><input class="cx-input" type="date" id="imMedStart"></div>`,
          async () => {
            await api(`/clinics/api/patients/${pid}/medications`, {
              method: "POST",
              body: JSON.stringify({
                drug_name: document.getElementById("imMedName").value,
                dose_text: document.getElementById("imMedDose").value,
                frequency: document.getElementById("imMedFreq").value,
                start_date: document.getElementById("imMedStart").value || null,
                status: "active",
                doctor_id: doctorId || null,
              }),
            });
            showNotice("تم تسجيل الدواء", false);
            await reload();
          }
        );
      });

      el.querySelectorAll("[data-edit-med]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const id = btn.getAttribute("data-edit-med");
          openModal(
            "تحديث حالة الدواء",
            `<div class="cx-field"><label>الحالة</label><select class="cx-select" id="imMedStatus">
              <option value="active">فعال</option><option value="stopped">موقوف</option><option value="historical">تاريخي</option>
            </select></div>
            <div class="cx-field"><label>تاريخ الإيقاف</label><input class="cx-input" type="date" id="imMedEnd"></div>`,
            async () => {
              await api(`/clinics/api/patient-medications/${id}`, {
                method: "PATCH",
                body: JSON.stringify({
                  status: document.getElementById("imMedStatus").value,
                  end_date: document.getElementById("imMedEnd").value || null,
                }),
              });
              showNotice("تم التحديث", false);
              await reload();
            }
          );
        });
      });

      el.querySelectorAll("[data-load-vitals]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const range = btn.getAttribute("data-load-vitals") || "6m";
          vitalFull = await api(`/clinics/api/patients/${pid}/vital-trends?range=${encodeURIComponent(range)}`);
          paint();
        });
      });

      el.querySelector("[data-load-labs]")?.addEventListener("click", async () => {
        labFull = await api(`/clinics/api/patients/${pid}/lab-trends?range=1y`);
        paint();
      });

      el.querySelector("[data-compare]")?.addEventListener("click", async () => {
        const sel = el.querySelector("#imCompareVisits");
        const ids = Array.from(sel?.selectedOptions || []).map((o) => o.value);
        if (ids.length < 2) return showNotice("اختر زيارتين على الأقل");
        compareData = await api(
          `/clinics/api/patients/${pid}/visit-comparison?visit_ids=${encodeURIComponent(ids.join(","))}`
        );
        paint();
      });
    }

    paint();
    return { reload };
  }

  window.ClinicsInternalMedicineTools = { mount };
})();
