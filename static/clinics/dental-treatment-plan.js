/* Dental treatment plan panel — patient-level clinical intent. */
(() => {
  const money = (n) => Number(n || 0).toLocaleString("ar-IQ");
  const esc = (v) =>
    String(v ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  async function ensureActivePlan(api, patientId, meta = {}) {
    const listed = await api(`/clinics/api/patients/${patientId}/dental-treatment-plans`);
    if (listed.active_plan) return listed;
    await api(`/clinics/api/patients/${patientId}/dental-treatment-plans`, {
      method: "POST",
      body: JSON.stringify({
        name: "خطة علاج الأسنان",
        status: "active",
        created_by_doctor_id: meta.doctorId || null,
        specialty_id: meta.specialtyId || null,
        source_visit_id: meta.visitId || null,
      }),
    });
    return api(`/clinics/api/patients/${patientId}/dental-treatment-plans`);
  }

  async function addItemFromTooth(api, patientId, toothNumber, defaults = {}, meta = {}) {
    const listed = await ensureActivePlan(api, patientId, meta);
    const planId = listed.active_plan.plan.id;
    return api(`/clinics/api/dental-treatment-plans/${planId}/items`, {
      method: "POST",
      body: JSON.stringify({
        tooth_number: toothNumber,
        service_id: defaults.service_id || null,
        procedure_id: defaults.procedure_id || null,
        title: defaults.title || "",
        priority: defaults.priority || "normal",
        estimated_sessions: defaults.estimated_sessions || 1,
        estimated_price: defaults.estimated_price,
        notes: defaults.notes || "",
        activate_plan: true,
      }),
    });
  }

  function summaryHtml(summary, includeFinancial) {
    const cards = [
      ["البنود", summary.item_count],
      ["مكتمل", summary.completed_count],
      ["قيد التنفيذ", summary.in_progress_count],
      ["متبقي", summary.remaining_count],
    ];
    if (includeFinancial) {
      cards.push(
        ["تقديري", money(summary.estimated_total)],
        ["منفّذ", money(summary.actual_billed)],
        ["مدفوع", money(summary.paid)]
      );
    }
    return `<div class="cx-dtp__summary">${cards
      .map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`)
      .join("")}</div>`;
  }

  function itemsHtml(items, includeFinancial) {
    if (!items.length) return '<div class="cx-empty">لا بنود في الخطة</div>';
    return `<div class="cx-dtp__items">${items
      .map(
        (item) => `
      <article class="cx-dtp__item" data-item-id="${item.id}">
        <div class="cx-dtp__item-main">
          <strong>${esc(item.whole_mouth ? "الفم بالكامل" : (item.tooth_numbers?.join("، ") || item.tooth_number || "عام"))} · ${esc(item.title)}</strong>
          <small>${esc(item.priority_label_ar)} · ${esc(item.status_label_ar)} · جلسات ${esc(item.sessions_label)}</small>
          ${includeFinancial ? `<small>تقديري ${money(item.estimated_price)} · منفّذ ${money(item.actual_billed || 0)}</small>` : ""}
        </div>
        <div class="cx-dtp__item-actions">
          <button type="button" class="cx-btn cx-btn--sm" data-edit-item="${item.id}">تفاصيل</button>
        </div>
      </article>`
      )
      .join("")}</div>`;
  }

  async function mount(el, opts) {
    const { patientId, api, showNotice, openModal, doctorId, specialtyId, visitId, printClinicDoc } = opts;
    let data = await api(`/clinics/api/patients/${patientId}/dental-treatment-plans`);
    let procedures = [];
    let services = [];
    try {
      [procedures, services] = await Promise.all([
        api(`/clinics/api/procedures${visitId ? `?visit_id=${visitId}` : ""}`),
        api("/clinics/api/services?active=1"),
      ]);
      services = (services || []).filter((service) =>
        service.category === "أسنان" || (specialtyId && (service.specialty_ids || []).map(String).includes(String(specialtyId)))
      );
    } catch (_) {
      procedures = [];
      services = [];
    }

    async function reload() {
      data = await api(`/clinics/api/patients/${patientId}/dental-treatment-plans`);
      paint();
    }

    function paint() {
      const active = data.active_plan;
      const includeFinancial = !!active?.permissions?.include_financial;
      el.innerHTML = `
        <div class="cx-dtp" dir="rtl">
          <div class="cx-dtp__head">
            <div>
              <h3 style="margin:0">خطة العلاج</h3>
              <small>${active ? esc(active.plan.name) + " · " + esc(active.plan.status_label_ar) : "لا توجد خطة علاج حالية"}</small>
            </div>
            <div class="cx-dtp__actions">
              ${active ? `<button type="button" class="cx-btn cx-btn--sm" data-print>طباعة</button>` : ""}
              ${active && !active.plan.accepted_at ? `<button type="button" class="cx-btn cx-btn--sm" data-accept-plan>موافقة المريض</button>` : ""}
              ${active ? `<button type="button" class="cx-btn cx-btn--sm" data-add-option>+ خيار علاجي</button>` : ""}
              ${active && includeFinancial ? `<button type="button" class="cx-btn cx-btn--sm" data-invoice data-finora-action="invoice.create">إنشاء فاتورة</button>` : ""}
              ${active ? `<button type="button" class="cx-btn cx-btn--sm" data-add-general data-finora-action="treatment_plan.add_item">+ علاج عام</button>` : ""}
              <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-create-plan data-finora-action="treatment_plan.create">${active ? "خطة جديدة" : "+ إنشاء خطة علاج"}</button>
            </div>
          </div>
          ${
            active
              ? `${summaryHtml(active.summary, includeFinancial)}
                 ${(active.options || []).length ? `<div class="cx-dtp__options">${active.options.map((option) => `<span class="cx-chip ${option.status === "selected" ? "is-active" : ""}">${esc(option.title)}${option.is_recommended ? " · موصى به" : ""}</span>`).join("")}</div>` : ""}
                 ${itemsHtml(active.items, includeFinancial)}`
              : `<div class="cx-empty">لا توجد خطة علاج حالية<button type="button" class="cx-btn cx-btn--primary" data-create-plan data-finora-action="treatment_plan.create" style="margin-top:10px">+ إنشاء خطة علاج</button></div>`
          }
          ${
            data.plans?.length > 1
              ? `<details class="cx-dtp__history"><summary>الخطط التاريخية (${data.plans.length})</summary>
                <ul>${data.plans
                  .map(
                    (p) =>
                      `<li><button type="button" class="cx-btn cx-btn--sm" data-open-plan="${p.plan.id}">${esc(p.plan.name)} · ${esc(p.plan.status_label_ar)}</button></li>`
                  )
                  .join("")}</ul></details>`
              : ""
          }
        </div>`;

      el.querySelectorAll("[data-create-plan]").forEach((btn) => {
        btn.onclick = () => {
          openModal(
            "إنشاء خطة علاج",
            `<div data-finora-section="treatment_plan.form"><div class="cx-field"><label>اسم الخطة</label><input class="cx-input" id="dtpName" data-finora-field="treatment_plan.name" value="خطة علاج الأسنان"></div>
             <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="dtpNotes" data-finora-field="treatment_plan.notes"></textarea></div></div>`,
            async () => {
              await api(`/clinics/api/patients/${patientId}/dental-treatment-plans`, {
                method: "POST",
                body: JSON.stringify({
                  name: document.getElementById("dtpName").value,
                  notes: document.getElementById("dtpNotes").value,
                  status: "active",
                  created_by_doctor_id: doctorId || null,
                  specialty_id: specialtyId || null,
                  source_visit_id: visitId || null,
                }),
              });
              await reload();
            },
            { finoraAction: "treatment_plan.save" }
          );
        };
      });

      const addGeneral = el.querySelector("[data-add-general]");
      if (addGeneral) {
        addGeneral.onclick = () => openItemForm(null);
      }
      const addOption = el.querySelector("[data-add-option]");
      if (addOption && active) {
        addOption.onclick = () => openModal(
          "إضافة خيار علاجي",
          `<div class="cx-field"><label>عنوان الخيار</label><input class="cx-input" id="dtpOptionTitle" placeholder="مثال: الخطة المحافظة"></div>
           <div class="cx-field"><label>الوصف</label><textarea class="cx-textarea" id="dtpOptionDescription"></textarea></div>
           <label class="cx-check"><input type="checkbox" id="dtpOptionRecommended"> الخيار الموصى به</label>`,
          async () => {
            await api(`/clinics/api/dental-treatment-plans/${active.plan.id}/options`, {
              method: "POST",
              body: JSON.stringify({
                title: document.getElementById("dtpOptionTitle").value,
                description: document.getElementById("dtpOptionDescription").value,
                is_recommended: document.getElementById("dtpOptionRecommended").checked,
              }),
            });
            await reload();
          },
          { successMessage: "تمت إضافة الخيار العلاجي" }
        );
      }
      const acceptPlan = el.querySelector("[data-accept-plan]");
      if (acceptPlan && active) {
        acceptPlan.onclick = () => openModal(
          "تسجيل موافقة المريض",
          `<div class="cx-field"><label>الخيار المقبول</label><select class="cx-select" id="dtpAcceptedOption"><option value="">الخطة الحالية بدون خيار محدد</option>${(active.options || []).map((option) => `<option value="${option.id}" ${option.is_recommended ? "selected" : ""}>${esc(option.title)}</option>`).join("")}</select></div>
           <div class="cx-field"><label>طريقة الموافقة</label><select class="cx-select" id="dtpAcceptanceMethod"><option value="verbal">شفهية</option><option value="written">خطية</option><option value="digital">رقمية</option><option value="signature">توقيع مرفق</option></select></div>
           <label class="cx-check"><input type="checkbox" id="dtpActivateAccepted" checked> تفعيل الخطة مباشرة</label>`,
          async () => {
            await api(`/clinics/api/dental-treatment-plans/${active.plan.id}/accept`, {
              method: "POST",
              body: JSON.stringify({
                selected_option_id: document.getElementById("dtpAcceptedOption").value || null,
                acceptance_method: document.getElementById("dtpAcceptanceMethod").value,
                activate: document.getElementById("dtpActivateAccepted").checked,
              }),
            });
            await reload();
          },
          { successMessage: "تم تسجيل موافقة المريض" }
        );
      }
      const invoiceBtn = el.querySelector("[data-invoice]");
      if (invoiceBtn && active) {
        invoiceBtn.onclick = () => {
          openModal(
            "إنشاء فاتورة من خطة العلاج",
            `<div data-finora-section="invoice.form"><div class="cx-field"><label>نوع الفاتورة</label>
              <select class="cx-select" id="dtpInvMode" data-finora-field="invoice.mode">
                <option value="full">الخطة كاملة</option>
                <option value="selected">بنود محددة</option>
                <option value="custom">مبلغ مخصص</option>
              </select></div>
             <div class="cx-field" data-finora-section="invoice.items"><label>البنود</label>
               ${(active.items || []).map((item) => `<label class="cx-check"><input type="checkbox" data-inv-item="${item.id}" checked> ${esc(item.tooth_number || "عام")} · ${esc(item.title)}</label>`).join("")}
             </div>
             <div class="cx-field"><label>مبلغ مخصص</label><input class="cx-input" id="dtpInvAmount" data-finora-field="invoice.custom_amount" type="number" min="0"></div></div>`,
            async () => {
              const mode = document.getElementById("dtpInvMode").value;
              await api(`/clinics/api/dental-treatment-plans/${active.plan.id}/invoice`, {
                method: "POST",
                body: JSON.stringify({
                  mode,
                  visit_id: visitId || null,
                  item_ids: Array.from(el.ownerDocument.querySelectorAll("[data-inv-item]:checked")).map((input) => Number(input.dataset.invItem)),
                  custom_amount: Number(document.getElementById("dtpInvAmount").value || 0),
                }),
              });
            },
            { successMessage: "تم إنشاء الفاتورة من خطة العلاج", finoraAction: "invoice.save" }
          );
        };
      }
      const printBtn = el.querySelector("[data-print]");
      if (printBtn) {
        printBtn.onclick = async () => {
          try {
            const payload = await api(`/clinics/api/dental-treatment-plans/${active.plan.id}/print`);
            const showMoney = payload.include_financial !== false;
            const rows = (payload.items || [])
              .map(
                (i) =>
                  `<tr><td>${esc(i.tooth_numbers?.join("، ") || i.tooth_number || "عام")}</td><td>${esc(i.title)}</td><td>${esc(i.estimated_sessions)}</td>${showMoney ? `<td>${money(i.estimated_price)}</td>` : ""}<td>${esc(i.notes)}</td></tr>`
              )
              .join("");
            (printClinicDoc || window.print)(
              `خطة علاج — ${payload.patient_name}`,
              `<h1>${esc(payload.clinic_name)}</h1>
               <h2>${esc(payload.plan_name)}</h2>
               <p class="meta">${esc(payload.patient_name)} · ${esc(payload.patient_file)} · ${esc(payload.doctor_name)} · ${esc(payload.plan_date)}</p>
               <table><thead><tr><th>السن</th><th>العلاج</th><th>الجلسات</th>${showMoney ? "<th>التقديري</th>" : ""}<th>ملاحظات</th></tr></thead><tbody>${rows}</tbody></table>
               ${showMoney ? `<p><strong>الإجمالي التقديري:</strong> ${money(payload.estimated_total)}</p>` : ""}`
            );
          } catch (err) {
            showNotice?.(err.message || String(err));
          }
        };
      }
      el.querySelectorAll("[data-edit-item]").forEach((btn) => {
        btn.onclick = () => {
          const item = active.items.find((i) => String(i.id) === String(btn.dataset.editItem));
          if (item) openItemForm(item);
        };
      });
      el.querySelectorAll("[data-open-plan]").forEach((btn) => {
        btn.onclick = async () => {
          try {
            const detail = await api(`/clinics/api/dental-treatment-plans/${btn.dataset.openPlan}`);
            data.active_plan = detail;
            paint();
          } catch (err) {
            showNotice?.(err.message || String(err));
          }
        };
      });
    }

    function openItemForm(item) {
      const active = data.active_plan;
      if (!active) return showNotice?.("أنشئ خطة أولاً");
      const isEdit = !!item;
      const includeFinancial = !!active.permissions?.include_financial;
      openModal(
        isEdit ? "تفاصيل العلاج" : "إضافة علاج",
        `<div data-finora-section="treatment_plan.item_form"><div class="cx-field"><label>الأسنان (اختياري)</label><input class="cx-input" id="dtpTooth" data-finora-field="treatment_plan.tooth" value="${esc(item?.tooth_numbers?.join(", ") || item?.tooth_number || "")}" placeholder="مثال 16, 15, 14"><small>يمكن تحديد أكثر من سن مفصولة بفاصلة</small></div>
         <label class="cx-check"><input type="checkbox" id="dtpWholeMouth" ${item?.whole_mouth ? "checked" : ""}> العلاج يشمل الفم بالكامل</label>
         ${(active.options || []).length ? `<div class="cx-field"><label>الخيار العلاجي</label><select class="cx-select" id="dtpTreatmentOption"><option value="">الخطة الرئيسية</option>${active.options.map((option) => `<option value="${option.id}" ${String(item?.treatment_option_id || "") === String(option.id) ? "selected" : ""}>${esc(option.title)}</option>`).join("")}</select></div>` : ""}
         <div class="cx-field"><label>خدمة الأسنان</label><select class="cx-select" id="dtpService" data-finora-field="treatment_plan.service"><option value="">بدون خدمة حجز</option>${services.map((service) => `<option value="${service.id}" ${String(item?.service_id || "") === String(service.id) ? "selected" : ""}>${esc(service.name)} · ${service.default_sessions || 1} جلسة${includeFinancial ? ` · ${money(service.price)}` : ""}</option>`).join("")}</select></div>
         <div class="cx-field"><label>الإجراء</label><select class="cx-select" id="dtpProc"><option value="">مخصص</option>${(procedures || [])
           .map(
             (p) =>
               `<option value="${p.id}" ${String(item?.procedure_id || "") === String(p.id) ? "selected" : ""}>${esc(p.name)}${includeFinancial ? ` · ${money(p.price)}` : ""}</option>`
           )
           .join("")}</select></div>
         <div class="cx-field"><label>العنوان</label><input class="cx-input" id="dtpTitle" data-finora-field="treatment_plan.title" value="${esc(item?.title || "")}"></div>
         <div class="cx-field-row">
           <div class="cx-field"><label>الأولوية</label><select class="cx-select" id="dtpPriority">
             ${["urgent", "high", "normal", "low"]
               .map(
                 (p) =>
                   `<option value="${p}" ${(item?.priority || "normal") === p ? "selected" : ""}>${
                     { urgent: "عاجل", high: "مرتفع", normal: "عادي", low: "منخفض" }[p]
                   }</option>`
               )
               .join("")}
           </select></div>
           <div class="cx-field"><label>الحالة</label><select class="cx-select" id="dtpStatus">
             ${["planned", "scheduled", "in_progress", "completed", "cancelled", "deferred"]
               .map(
                 (s) =>
                   `<option value="${s}" ${(item?.status || "planned") === s ? "selected" : ""}>${
                     {
                       planned: "مخطط",
                       scheduled: "مجدول",
                       in_progress: "قيد التنفيذ",
                       completed: "مكتمل",
                       cancelled: "ملغى",
                       deferred: "مؤجل",
                     }[s]
                   }</option>`
               )
               .join("")}
           </select></div>
         </div>
         <div class="cx-field-row">
           <div class="cx-field"><label>جلسات تقديرية</label><input class="cx-input" type="number" min="1" id="dtpSessions" data-finora-field="treatment_plan.sessions" value="${esc(item?.estimated_sessions || 1)}"></div>
           ${includeFinancial ? `<div class="cx-field"><label>السعر التقديري</label><input class="cx-input" type="number" min="0" id="dtpPrice" value="${esc(item?.estimated_price ?? "")}"></div>` : ""}
         </div>
         ${includeFinancial ? `<div class="cx-field-row"><div class="cx-field"><label>الكمية</label><input class="cx-input" type="number" min="0.01" step="0.01" id="dtpQuantity" value="${esc(item?.quantity || 1)}"></div><div class="cx-field"><label>الخصم</label><input class="cx-input" type="number" min="0" id="dtpDiscount" value="${esc(item?.discount || 0)}"></div></div>` : ""}
         ${isEdit ? `<div class="cx-field"><label>سبب الإلغاء (يُطلب عند اختيار ملغى)</label><input class="cx-input" id="dtpCancelReason" value="${esc(item?.cancellation_reason || "")}"></div>` : ""}
         <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="dtpItemNotes">${esc(item?.notes || "")}</textarea></div>
         ${
           isEdit && item.executions?.length
             ? `<div class="cx-feed"><strong>التنفيذ المرتبط</strong>${item.executions
                 .map(
                   (ex) =>
                     `<div class="cx-feed__item">${esc(ex.visit_date || "")} · ${esc(ex.procedure_name)} · #${ex.visit_procedure_id}</div>`
                 )
                 .join("")}</div>`
             : ""
         }
         ${
           isEdit && visitId
             ? `<div class="cx-field"><label>ربط إجراء من الزيارة الحالية</label><select class="cx-select" id="dtpLinkVp"><option value="">—</option></select></div>`
             : ""
         }</div>`,
        async () => {
          const selectedTeeth = document.getElementById("dtpTooth").value.split(/[,،\s]+/).filter(Boolean);
          const payload = {
            tooth_number: selectedTeeth[0] || null,
            tooth_numbers: selectedTeeth,
            whole_mouth: document.getElementById("dtpWholeMouth").checked,
            treatment_option_id: document.getElementById("dtpTreatmentOption")?.value || null,
            service_id: document.getElementById("dtpService").value || null,
            procedure_id: document.getElementById("dtpProc").value || null,
            title: document.getElementById("dtpTitle").value,
            priority: document.getElementById("dtpPriority").value,
            status: document.getElementById("dtpStatus").value,
            estimated_sessions: Number(document.getElementById("dtpSessions").value || 1),
            notes: document.getElementById("dtpItemNotes").value,
          };
          if (includeFinancial) {
            payload.estimated_price = document.getElementById("dtpPrice").value;
            payload.quantity = Number(document.getElementById("dtpQuantity").value || 1);
            payload.discount = Number(document.getElementById("dtpDiscount").value || 0);
          }
          if (isEdit) payload.cancellation_reason = document.getElementById("dtpCancelReason").value;
          if (isEdit) {
            await api(`/clinics/api/dental-treatment-plan-items/${item.id}`, {
              method: "PATCH",
              body: JSON.stringify(payload),
            });
            const linkSel = document.getElementById("dtpLinkVp");
            if (linkSel?.value) {
              await api(`/clinics/api/dental-treatment-plan-items/${item.id}/procedure-links`, {
                method: "POST",
                body: JSON.stringify({ visit_procedure_id: Number(linkSel.value) }),
              });
            }
          } else {
            await api(`/clinics/api/dental-treatment-plans/${active.plan.id}/items`, {
              method: "POST",
              body: JSON.stringify(payload),
            });
          }
          await reload();
        },
        { finoraAction: isEdit ? "treatment_plan.item.save.edit" : "treatment_plan.item.save" }
      );
      const procSel = document.getElementById("dtpProc");
      const serviceSel = document.getElementById("dtpService");
      const titleInput = document.getElementById("dtpTitle");
      const priceInput = document.getElementById("dtpPrice");
      if (serviceSel) {
        serviceSel.onchange = () => {
          const service = services.find((row) => String(row.id) === serviceSel.value);
          if (!service) return;
          titleInput.value = service.name;
          document.getElementById("dtpSessions").value = service.default_sessions || 1;
          if (priceInput) priceInput.value = service.price || 0;
          if (service.default_procedure_id) procSel.value = String(service.default_procedure_id);
        };
      }
      if (procSel) {
        procSel.onchange = () => {
          const proc = (procedures || []).find((p) => String(p.id) === procSel.value);
          if (proc) {
            if (!titleInput.value) titleInput.value = proc.name;
            if (priceInput && (priceInput.value === "" || priceInput.value === "0")) priceInput.value = proc.price || 0;
          }
        };
      }
      if (isEdit && visitId) {
        api(`/clinics/api/visits/${visitId}/procedures`)
          .then((rows) => {
            const sel = document.getElementById("dtpLinkVp");
            if (!sel) return;
            sel.innerHTML =
              '<option value="">—</option>' +
              (rows || [])
                .map((p) => `<option value="${p.id}">${esc(p.procedure_name)} (#${p.id})</option>`)
                .join("");
          })
          .catch(() => {});
      }
    }

    paint();
    return { reload, addItemFromTooth: (tooth, defaults) => addItemFromTooth(api, patientId, tooth, defaults, { doctorId, specialtyId, visitId }).then(reload) };
  }

  window.ClinicsDentalTreatmentPlan = { mount, ensureActivePlan, addItemFromTooth };
})();
