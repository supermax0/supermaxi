/* Unified patient profile — hub tabs with clinical subsections (Phase UX). */
(() => {
  const hubLabels = {
    overview: "نظرة عامة",
    schedule: "المواعيد والزيارات",
    clinical: "السجل السريري",
    treatment: "العلاج والمتابعة",
    files: "الملفات",
    finance: "المالية",
  };
  const sectionLabels = {
    timeline: "السجل الطبي",
    prescriptions: "الوصفات",
    labs: "التحاليل",
    radiology: "الأشعة",
    dental: "الأسنان",
    pediatrics: "طب الأطفال",
    gynecology: "النسائية والتوليد",
    internal_medicine: "الباطنية والأمراض المزمنة",
    cardiology: "القلب والأوعية",
    procedures: "الإجراءات",
    followups: "المتابعات",
    appointments: "المواعيد",
    visits: "الزيارات",
    attachments: "المرفقات",
    invoices: "الفواتير",
  };
  const eventSections = new Set(["procedures", "followups"]);
  const eventNames = { procedures: "procedure", followups: "followup" };
  const valueText = (value) =>
    value == null || value === "" ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);

  function initials(name) {
    const parts = String(name || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!parts.length) return "؟";
    return ((parts[0][0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] || "" : "")).toUpperCase();
  }

  function genderLabel(gender) {
    if (gender === "male") return "ذكر";
    if (gender === "female") return "أنثى";
    return gender || "";
  }

  function flagCard(kind, title, icon, value) {
    const has = Boolean(String(value || "").trim());
    return `<article class="cx-pp-flag cx-pp-flag--${kind}${has ? " has" : ""}"><header><i class="fa ${icon}" aria-hidden="true"></i><h3>${title}</h3></header><p>${has ? value : "لا يوجد"}</p></article>`;
  }

  function buildHubs(can) {
    const hubs = [{ key: "overview", sections: [] }];
    hubs.push({
      key: "schedule",
      sections: [
        ...(can("clinics_appointments") || can("clinics_patients") ? ["appointments"] : []),
        ...(can("clinics_visits") || can("clinics_clinical") ? ["visits"] : []),
      ].filter(Boolean),
    });
    if (can("clinics_clinical")) {
      hubs.push({
        key: "clinical",
        sections: ["timeline", "prescriptions", "labs", "radiology", "dental", "pediatrics", "gynecology", "internal_medicine", "cardiology"],
      });
      hubs.push({ key: "treatment", sections: ["procedures", "followups"] });
    }
    if (can("clinics_patients")) hubs.push({ key: "files", sections: ["attachments"] });
    if (can("clinics_billing")) hubs.push({ key: "finance", sections: ["invoices"] });
    return hubs.filter((h) => h.key === "overview" || h.sections.length);
  }

  window.ClinicsPatientProfile = {
    async render(state, root, ctx) {
      const { api, esc, money, showNotice, openModal, promptNewAppointment, patientFormFields, readPatientForm, patientId } = ctx;
      const base = await api(`/clinics/api/patients/${patientId}`);
      const p = base.patient;
      const user = state.bootstrap?.user || {};
      const permissions = new Set(user.permissions || []);
      const admin = user.role === "admin";
      const can = (permission) => admin || permissions.has(permission);
      const hubs = buildHubs(can);
      let activeHub = hubs.some((h) => h.key === state.patientProfileHub)
        ? state.patientProfileHub
        : "overview";
      const hub = () => hubs.find((h) => h.key === activeHub) || hubs[0];
      let activeSection =
        hub().sections.includes(state.patientProfileTab) ? state.patientProfileTab : hub().sections[0] || null;

      const gender = genderLabel(p.gender);
      const ageText = p.age != null ? `${p.age} سنة` : "العمر غير محدد";
      root.innerHTML = `<section class="cx-hero cx-hero--patient"><div class="cx-pp-identity"><div class="cx-pp-avatar" aria-hidden="true">${esc(initials(p.full_name))}</div><div class="cx-pp-identity__text"><div class="cx-kicker">${esc(p.file_number)}</div><h1>${esc(p.full_name)}</h1><div class="cx-pp-meta"><span><i class="fa fa-phone" aria-hidden="true"></i>${esc(p.phone || "بدون هاتف")}</span><span><i class="fa fa-cake-candles" aria-hidden="true"></i>${esc(ageText)}</span>${gender ? `<span><i class="fa fa-user" aria-hidden="true"></i>${esc(gender)}</span>` : ""}${p.blood_type ? `<span><i class="fa fa-droplet" aria-hidden="true"></i>${esc(p.blood_type)}</span>` : ""}</div></div></div><div class="cx-actions"><button class="cx-btn cx-btn--primary" id="ppAppt"><i class="fa fa-calendar-plus" aria-hidden="true"></i>حجز موعد</button><button class="cx-btn" id="ppEdit"><i class="fa fa-pen" aria-hidden="true"></i>تعديل</button><a class="cx-btn cx-btn--ghost" href="/clinics/patients"><i class="fa fa-arrow-right" aria-hidden="true"></i>رجوع</a></div></section><nav class="cx-tabs" aria-label="أقسام ملف المريض">${hubs.map((h) => `<button type="button" data-profile-hub="${h.key}" class="${h.key === activeHub ? "active is-active" : ""}">${hubLabels[h.key]}</button>`).join("")}</nav><div id="ppSubnav" class="cx-subtabs" hidden></div><section id="ppContent" class="cx-card cx-card--profile"><div class="cx-empty">جاري التحميل…</div></section>`;
      root.querySelector("#ppEdit").onclick = () =>
        openModal("تعديل مريض", patientFormFields(p), async () =>
          api(`/clinics/api/patients/${p.id}`, { method: "PUT", body: JSON.stringify(readPatientForm()) })
        );
      root.querySelector("#ppAppt").onclick = () => promptNewAppointment(p.id);
      root.querySelectorAll("[data-profile-hub]").forEach((button) => {
        button.onclick = async () => {
          state.patientProfileHub = activeHub = button.dataset.profileHub;
          root.querySelectorAll("[data-profile-hub]").forEach((item) =>
            item.classList.toggle("active", item === button)
          );
          root.querySelectorAll("[data-profile-hub]").forEach((item) =>
            item.classList.toggle("is-active", item === button)
          );
          activeSection = hub().sections[0] || null;
          state.patientProfileTab = activeSection;
          await load();
        };
      });

      const cards = (rows) =>
        `<div class="cx-feed">${rows.map((row) => `<article class="cx-feed__item">${row}</article>`).join("") || '<div class="cx-empty">لا توجد بيانات</div>'}</div>`;
      const openHistorical = async (visitId) => {
        try {
          const detail = await api(`/clinics/api/visits/${visitId}`);
          const template = detail.template;
          if (!template) return showNotice("هذه زيارة قديمة بدون نموذج تخصصي");
          const fields = template.sections.flatMap((section) =>
            section.fields.map((field) => ({ section: section.title_ar, ...field }))
          );
          openModal(
            `النموذج التاريخي — ${esc(detail.specialty?.name_ar || "")}`,
            `<p><strong>${esc(template.name)}</strong> · الإصدار ${template.version}</p><div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>القسم</th><th>الحقل</th><th>القيمة المسجلة</th></tr></thead><tbody>${fields.map((field) => `<tr><td>${esc(field.section)}</td><td>${esc(field.label_ar)}</td><td>${esc(valueText(detail.values?.[String(field.id)]))}</td></tr>`).join("")}</tbody></table></div>`,
            async () => {}
          );
        } catch (error) {
          showNotice(error.message || String(error));
        }
      };

      function renderSubnav() {
        const sub = root.querySelector("#ppSubnav");
        const sections = hub().sections;
        if (!sections.length) {
          sub.hidden = true;
          sub.innerHTML = "";
          return;
        }
        sub.hidden = false;
        sub.innerHTML = sections
          .map(
            (key) =>
              `<button type="button" data-profile-section="${key}" class="${key === activeSection ? "is-active active" : ""}">${sectionLabels[key] || key}</button>`
          )
          .join("");
        sub.querySelectorAll("[data-profile-section]").forEach((button) => {
          button.onclick = async () => {
            state.patientProfileTab = activeSection = button.dataset.profileSection;
            sub.querySelectorAll("[data-profile-section]").forEach((item) =>
              item.classList.toggle("is-active", item === button)
            );
            sub.querySelectorAll("[data-profile-section]").forEach((item) =>
              item.classList.toggle("active", item === button)
            );
            await loadSection();
          };
        });
      }

      async function loadSection() {
        const content = root.querySelector("#ppContent");
        content.innerHTML = '<div class="cx-empty">جاري التحميل…</div>';
        const active = activeSection;
        if (!active) {
          content.innerHTML = '<div class="cx-empty">لا أقسام فرعية</div>';
          return;
        }
        if (active === "appointments") {
          content.innerHTML = cards(
            (base.appointments || []).map(
              (a) =>
                `<strong>${esc(a.appointment_date)} · ${esc(a.start_time)}</strong><small>${esc(a.doctor_name || "—")} · ${esc(a.status)}</small>`
            )
          );
        } else if (active === "visits") {
          content.innerHTML = cards(
            (base.visits || []).map(
              (v) =>
                `<strong>${esc(v.visit_date)} · ${esc(v.doctor_name || "—")}</strong><small>${esc(v.specialty_name || "عام")} · ${v.template_version ? "v" + v.template_version : "بدون نموذج"} · ${esc(v.status)}</small>${can("clinics_clinical") && v.visit_template_id ? `<button class="cx-btn cx-btn--sm" data-history-form="${v.id}">عرض النموذج المثبت</button>` : ""}`
            )
          );
          content.querySelectorAll("[data-history-form]").forEach(
            (button) => (button.onclick = () => openHistorical(button.dataset.historyForm))
          );
        } else if (active === "attachments") {
          const data = await api(`/clinics/api/attachments?patient_id=${encodeURIComponent(p.id)}&per_page=100`);
          content.innerHTML = cards(
            (data.items || []).map(
              (item) =>
                `<strong>${esc(item.file_name)}</strong><small>${esc(item.category)} · ${esc(item.uploaded_at)}</small><a class="cx-btn cx-btn--sm" href="${item.url}">تنزيل</a>`
            )
          );
        } else if (active === "invoices") {
          const statement = await api(`/clinics/api/patients/${p.id}/statement`);
          content.innerHTML = `<h2>الرصيد المستحق: ${money(statement.outstanding_balance)}</h2>${cards((statement.lines || []).map((line) => `<strong>${esc(line.reference)} · ${esc(line.date || "—")}</strong><small>${money(line.debit || 0)} / ${money(line.credit || 0)} · ${money(line.balance || 0)}</small>`))}`;
        } else if (active === "dental") {
          try {
            const dental = await api(`/clinics/api/patients/${p.id}/dental-history`);
            const current = dental.current_state || [];
            const history = dental.history || [];
            let planHtml =
              '<div id="ppDentalChart" class="cx-panel" style="margin-bottom:14px"><div class="cx-ws-section__head"><div><h3>مخطط الأسنان الحالي</h3><p class="cx-muted">محفوظ مع ملف المريض ويستمر بين الزيارات</p></div></div><div class="cx-dental-field" data-readonly="1"><div class="cx-dental-root"><div class="cx-empty">جاري تحميل المخطط…</div></div></div></div><div id="ppDentalActive" class="cx-panel" style="margin-bottom:14px"></div><div id="ppDentalPlatform" class="cx-panel" style="margin-bottom:14px"><div class="cx-empty">جاري تحميل منصة الأسنان…</div></div>';
            content.innerHTML = `${planHtml}<h3 style="margin-top:0">ملخص الحالة الحالية</h3>${
              !history.length
                ? '<div class="cx-empty">لا يوجد مخطط أسنان مسجّل لهذا المريض</div>'
                : `${cards(current.map((t) => `<strong>السن ${esc(t.tooth_number)}</strong><small>${esc(t.status_label_ar)} · ${esc((t.surfaces || []).join(", ") || "بدون أسطح")} · زيارة ${esc(t.visit_date || "")}</small>`))}<h3>التاريخ</h3>${cards(history.map((t) => `<strong>${esc(t.visit_date || "")} · السن ${esc(t.tooth_number)}</strong><small>${esc(t.status_label_ar)} · ${esc(t.doctor_name || "")} · ${esc(t.notes || "")}</small>`))}`
            }`;
            const chartRoot = content.querySelector("#ppDentalChart .cx-dental-root");
            if (chartRoot && window.ClinicsDentalChart) {
              try {
                await window.ClinicsDentalChart.mount(chartRoot, {
                  patientId: p.id,
                  chartUrl: `/clinics/api/patients/${p.id}/dental-chart`,
                  api,
                  showNotice,
                  openModal,
                  readonly: true,
                });
              } catch (error) {
                chartRoot.innerHTML = `<div class="cx-empty">${esc(error.message || String(error))}</div>`;
              }
            }
            const activeBox = content.querySelector("#ppDentalActive");
            if (activeBox) {
              try {
                const active = await api(`/clinics/api/patients/${p.id}/dental-active-treatments`);
                const items = active.items || [];
                const next = active.upcoming_appointment;
                activeBox.innerHTML = `<h3 style="margin-top:0">العلاجات النشطة</h3>${
                  items.length
                    ? items.map((item) => `<div class="cx-feed__item"><strong>${esc(item.tooth_number || "عام")} · ${esc(item.title)}</strong><small>${esc(item.status)}</small></div>`).join("")
                    : '<p class="cx-muted">لا توجد علاجات نشطة</p>'
                }${next ? `<p class="cx-muted">الموعد القادم: ${esc(next.date)} ${esc(next.time)}${next.tooth_number ? ` · السن ${esc(next.tooth_number)}` : ""}</p>` : ""}`;
              } catch (_) {
                activeBox.innerHTML = "";
              }
            }
            if (window.ClinicsDentalPlatform) {
              await window.ClinicsDentalPlatform.mount(content.querySelector("#ppDentalPlatform"), {
                patientId: p.id,
                api,
                showNotice,
                openModal,
                readonly: !can("clinics_clinical"),
                printClinicDoc: (title, body) => {
                  const w = window.open("", "_blank", "width=800,height=900");
                  if (!w) return showNotice("تعذر فتح نافذة الطباعة");
                  w.document.write(
                    `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>${esc(title)}</title></head><body>${body}</body></html>`
                  );
                  w.document.close();
                  w.focus();
                  w.print();
                },
              });
            } else {
              content.querySelector("#ppDentalPlatform").innerHTML = "";
            }
          } catch (error) {
            content.innerHTML = `<div class="cx-empty">${esc(error.message || String(error))}</div>`;
          }
        } else if (active === "pediatrics") {
          content.innerHTML = '<div id="ppPedRoot"><div class="cx-empty">جاري التحميل…</div></div>';
          if (window.ClinicsPediatricTools) {
            try {
              await window.ClinicsPediatricTools.mount(content.querySelector("#ppPedRoot"), {
                patientId: p.id,
                api,
                showNotice,
                openModal,
                readonly: false,
              });
            } catch (error) {
              content.innerHTML = `<div class="cx-empty">${esc(error.message || String(error))}</div>`;
            }
          } else {
            content.innerHTML = '<div class="cx-empty">تعذر تحميل أدوات طب الأطفال</div>';
          }
        } else if (active === "gynecology") {
          content.innerHTML = '<div id="ppGynRoot"><div class="cx-empty">جاري التحميل…</div></div>';
          if (window.ClinicsGynecologyTools) {
            try {
              await window.ClinicsGynecologyTools.mount(content.querySelector("#ppGynRoot"), {
                patientId: p.id,
                api,
                showNotice,
                openModal,
                readonly: false,
              });
            } catch (error) {
              content.innerHTML = `<div class="cx-empty">${esc(error.message || String(error))}</div>`;
            }
          } else {
            content.innerHTML = '<div class="cx-empty">تعذر تحميل أدوات النسائية والتوليد</div>';
          }
        } else if (active === "internal_medicine") {
          content.innerHTML = '<div id="ppImRoot"><div class="cx-empty">جاري التحميل…</div></div>';
          if (window.ClinicsInternalMedicineTools) {
            try {
              await window.ClinicsInternalMedicineTools.mount(content.querySelector("#ppImRoot"), {
                patientId: p.id,
                api,
                showNotice,
                openModal,
                readonly: false,
              });
            } catch (error) {
              content.innerHTML = `<div class="cx-empty">${esc(error.message || String(error))}</div>`;
            }
          } else {
            content.innerHTML = '<div class="cx-empty">تعذر تحميل أدوات الباطنية</div>';
          }
        } else if (active === "cardiology") {
          content.innerHTML = '<div id="ppCardioRoot"><div class="cx-empty">جاري التحميل…</div></div>';
          if (window.ClinicsCardiologyTools) {
            try {
              await window.ClinicsCardiologyTools.mount(content.querySelector("#ppCardioRoot"), {
                patientId: p.id,
                api,
                showNotice,
                openModal,
                readonly: false,
              });
            } catch (error) {
              content.innerHTML = `<div class="cx-empty">${esc(error.message || String(error))}</div>`;
            }
          } else {
            content.innerHTML = '<div class="cx-empty">تعذر تحميل أدوات القلب</div>';
          }
        } else {
          const section = eventSections.has(active) ? `timeline&event_type=${eventNames[active]}` : active;
          const data = await api(`/clinics/api/clinical/patients/${p.id}?section=${section}&per_page=100`);
          const rows = data.items || (active === "timeline" ? [] : data[active] || []);
          content.innerHTML = cards(
            rows.map((item) => {
              const value = item.data || item;
              return `<strong>${esc(value.title || value.procedure_name || value.medicine_name || value.modality || value.status || item.type || sectionLabels[active])}</strong><small>${esc(item.at || value.created_at || value.ordered_at || value.due_date || "")}</small>`;
            })
          );
        }
      }

      async function load() {
        renderSubnav();
        const content = root.querySelector("#ppContent");
        if (activeHub === "overview") {
          content.innerHTML = '<div class="cx-empty">جاري التحميل…</div>';
          const next = (base.appointments || [])
            .filter((a) => !["completed", "cancelled", "no_show"].includes(a.status))
            .sort((a, b) => (a.appointment_date + a.start_time).localeCompare(b.appointment_date + b.start_time))[0];
          const last = (base.visits || [])[0];
          let balanceTile = "";
          if (can("clinics_billing")) {
            const statement = await api(`/clinics/api/patients/${p.id}/statement`);
            const bal = Number(statement.outstanding_balance || 0);
            balanceTile = `<div class="cx-summary-tile${bal > 0 ? " cx-summary-tile--warn" : ""}"><span>الرصيد</span><strong>${money(statement.outstanding_balance)}</strong></div>`;
          }
          const nextText = next
            ? `${esc(next.appointment_date)}${next.start_time ? " · " + esc(next.start_time) : ""}`
            : "—";
          content.innerHTML = `<div class="cx-pp-overview"><div class="cx-summary-grid"><div class="cx-summary-tile"><span>رقم الملف</span><strong>${esc(p.file_number)}</strong></div><div class="cx-summary-tile"><span>الاسم</span><strong>${esc(p.full_name)}</strong></div><div class="cx-summary-tile"><span>العمر</span><strong>${p.age ?? "—"}</strong></div><div class="cx-summary-tile"><span>الهاتف</span><strong dir="ltr">${esc(p.phone || "—")}</strong></div><div class="cx-summary-tile cx-summary-tile--accent"><span>الموعد القادم</span><strong>${nextText}</strong></div><div class="cx-summary-tile"><span>آخر زيارة</span><strong>${esc(last?.visit_date || "—")}</strong></div>${balanceTile}</div><div class="cx-pp-flags">${flagCard("allergy", "الحساسية", "fa-triangle-exclamation", esc(p.allergies || ""))}${flagCard("chronic", "الأمراض المزمنة", "fa-heart-pulse", esc(p.chronic_conditions || ""))}${flagCard("alert", "تنبيهات مهمة", "fa-bell", esc(p.notes || ""))}</div></div>`;
          return;
        }
        await loadSection();
      }
      await load();
    },
  };
})();
