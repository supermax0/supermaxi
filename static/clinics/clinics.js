(() => {
  const root = document.getElementById("cxRoot");
  const notice = document.getElementById("cxNotice");
  const shell = document.querySelector(".cx-shell");
  if (!root || !shell) return;

  const page = shell.dataset.clinicsPage || "dashboard";
  const visitId = shell.dataset.visitId || "";
  const patientId = shell.dataset.patientId || "";

  // Compatibility contract for specialty tabs rendered by ClinicsDoctorWorkspace.
  // Keeping it here also lets diagnostics verify that the shell and delegated UI agree.
  window.ClinicsSpecialtyWorkspaceContract = Object.freeze({
    dentistry: { tab: 'data-tab="treatment"', label: "علاج الأسنان" },
    pediatrics: { tab: 'data-tab="pediatrics"', label: "طب الأطفال" },
    obstetrics_gynecology: { tab: 'data-tab="gynecology"', label: "النسائية والتوليد" },
    internal_medicine: { tab: 'data-tab="internal"', label: "الباطنية والأمراض المزمنة" },
    cardiology: { tab: 'data-tab="cardiology"', label: "القلب والأوعية" },
  });

  function localToday() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  const state = {
    bootstrap: null,
    day: localToday(),
    doctorFilter: "",
    branchFilter: "",
    statusFilter: "",
    serviceFilter: "",
    apptView: sessionStorage.getItem("cx-appt-view") || "day",
    calView: "week",
  };

  const STATUS_CLASS = {
    pending: "pending",
    confirmed: "pending",
    arrived: "waiting",
    waiting: "waiting",
    in_consultation: "in",
    completed: "done",
    cancelled: "cancel",
    rescheduled: "pending",
    no_show: "cancel",
  };

  function money(n) {
    return Number(n || 0).toLocaleString("en-IQ") + " د.ع";
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showNotice(msg, isError = true) {
    if (!msg) {
      notice.hidden = true;
      notice.textContent = "";
      return;
    }
    notice.hidden = false;
    notice.textContent = msg;
    notice.style.background = isError ? "#fff7ed" : "#ecfdf5";
    notice.style.borderColor = isError ? "#fdba74" : "#86efac";
    notice.style.color = isError ? "#9a3412" : "#166534";
  }

  async function api(url, options = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({ ok: false, error: "استجابة غير صالحة" }));
    if (!res.ok || data.ok === false) throw new Error(data.error || "فشلت العملية");
    if (data.data?.organization_upgrade_suggested && window.confirm('أصبح لديك أكثر من طبيب. هل تريد تفعيل وضع العيادة متعددة الأطباء الآن؟')) {
      try { await api('/clinics/api/settings', {method:'PUT',body:JSON.stringify({organization_mode:'multi_doctor_clinic'})}); }
      catch (error) { showNotice('تم حفظ الطبيب، لكن تعذر تغيير وضع المنشأة: '+error.message); }
    }
    return data.data;
  }

  function statusLabel(key) {
    return (state.bootstrap && state.bootstrap.status_labels && state.bootstrap.status_labels[key]) || key;
  }

  function badge(status) {
    const cls = STATUS_CLASS[status] || "pending";
    return `<span class="cx-badge cx-badge--${cls}">${esc(statusLabel(status))}</span>`;
  }

  function closeNotifPanels() {
    document.querySelectorAll("#cxNotifPanel").forEach((panel) => {
      panel.hidden = true;
    });
    document.querySelectorAll("#cxDashNotif, #cxRecNotif").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });
  }

  function openModal(title, bodyHtml, onSave, options = {}) {
    const modal = document.getElementById("cxModal");
    const actions = modal.querySelector(".cx-modal__actions");
    closeNotifPanels();
    document.getElementById("cxModalTitle").textContent = title;
    document.getElementById("cxModalBody").innerHTML = bodyHtml;
    modal.hidden = false;
    const saveBtn = document.getElementById("cxModalSave");
    const cancelBtn = document.getElementById("cxModalCancel");
    const closeBtn = document.getElementById("cxModalClose");
    actions.querySelectorAll(".cx-modal__extra").forEach((el) => el.remove());
    saveBtn.style.display = "";
    saveBtn.dataset.finoraAction = options.finoraAction || "modal.save";
    saveBtn.textContent = options.saveLabel || "حفظ";
    const close = () => {
      modal.hidden = true;
      saveBtn.onclick = null;
      cancelBtn.onclick = null;
      if (closeBtn) closeBtn.onclick = null;
      modal.onclick = null;
      actions.querySelectorAll(".cx-modal__extra").forEach((el) => el.remove());
      saveBtn.textContent = "حفظ";
    };
    cancelBtn.onclick = close;
    if (closeBtn) closeBtn.onclick = close;
    modal.onclick = (e) => {
      if (e.target === modal) close();
    };
    if (options.extraActions) {
      options.extraActions.forEach((act) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `cx-btn cx-modal__extra ${act.primary ? "cx-btn--primary" : ""}`;
        btn.textContent = act.label;
        btn.onclick = async () => {
          try {
            await act.onClick();
            close();
            if (!act.skipRender && page !== "doctor") await render();
            if (act.notice) showNotice(act.notice, false);
          } catch (err) {
            showNotice(err.message || String(err));
          }
        };
        actions.insertBefore(btn, saveBtn);
      });
    }
    saveBtn.onclick = async () => {
      try {
        await onSave();
        close();
        showNotice(options.successMessage || "تم الحفظ بنجاح", false);
        if (!options.skipRender && page !== "doctor") await render();
      } catch (err) {
        showNotice(err.message || String(err));
      }
    };
  }

  async function bindPhoneDuplicateCheck() {
    const phoneInput = document.getElementById("f_phone");
    const warn = document.getElementById("cxPhoneDupWarn");
    if (!phoneInput || !warn) return;
    const run = async () => {
      const phone = phoneInput.value.trim();
      if (phone.length < 7) {
        warn.hidden = true;
        return;
      }
      try {
        const check = await api(`/clinics/api/patients/check-phone?phone=${encodeURIComponent(phone)}`);
        if (check.exists && check.patient) {
          warn.hidden = false;
          warn.innerHTML = `يوجد مريض مسجل بهذا الرقم: <a class="cx-link" href="/clinics/patients/${check.patient.id}">${esc(check.patient.full_name)}</a> — <button type="button" class="cx-btn cx-btn--sm" id="cxUseExistingPatient" data-id="${check.patient.id}">فتح الملف</button>`;
          document.getElementById("cxUseExistingPatient")?.addEventListener("click", () => {
            location.href = `/clinics/patients/${check.patient.id}`;
          });
        } else {
          warn.hidden = true;
        }
      } catch {
        warn.hidden = true;
      }
    };
    phoneInput.addEventListener("blur", run);
    phoneInput.addEventListener("input", () => {
      clearTimeout(phoneInput._t);
      phoneInput._t = setTimeout(run, 400);
    });
  }

  function quickPatientFormHtml() {
    return `${patientFormFields()}<div id="cxPhoneDupWarn" class="cx-phone-warn" hidden></div>`;
  }

  function patientFormFields(p = {}) {
    return `
      <div class="cx-field"><label>الاسم الكامل</label><input class="cx-input" id="f_full_name" value="${esc(p.full_name || "")}" required></div>
      <div class="cx-field-row">
        <div class="cx-field"><label>الهاتف</label><input class="cx-input" id="f_phone" value="${esc(p.phone || "")}"></div>
        <div class="cx-field"><label>الجنس</label>
          <select class="cx-select" id="f_gender">
            <option value="">—</option>
            <option value="male" ${p.gender === "male" ? "selected" : ""}>ذكر</option>
            <option value="female" ${p.gender === "female" ? "selected" : ""}>أنثى</option>
          </select>
        </div>
      </div>
      <div class="cx-field-row">
        <div class="cx-field"><label>تاريخ الميلاد</label><input class="cx-input" type="date" id="f_dob" value="${esc(p.date_of_birth || "")}"></div>
        <div class="cx-field"><label>فصيلة الدم</label><input class="cx-input" id="f_blood" value="${esc(p.blood_type || "")}"></div>
      </div>
      <div class="cx-field"><label>الحساسية</label><textarea class="cx-textarea" id="f_allergies">${esc(p.allergies || "")}</textarea></div>
      <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="f_notes">${esc(p.notes || "")}</textarea></div>
    `;
  }

  function readPatientForm() {
    return {
      full_name: document.getElementById("f_full_name").value,
      phone: document.getElementById("f_phone").value,
      gender: document.getElementById("f_gender").value,
      date_of_birth: document.getElementById("f_dob").value,
      blood_type: document.getElementById("f_blood").value,
      allergies: document.getElementById("f_allergies").value,
      notes: document.getElementById("f_notes").value,
    };
  }

  function inlinePatientCreatorHtml(prefix, opts = {}) {
    const form = `
        <div class="cx-inline-patient__form" id="${prefix}_patient_form" hidden>
          <div class="cx-inline-patient__head"><b>بيانات المريض الجديد</b><span>سيتم اختياره تلقائياً بعد الحفظ</span></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>الاسم الكامل *</label><input class="cx-input" id="${prefix}_patient_name" autocomplete="name"></div>
            <div class="cx-field"><label>رقم الهاتف</label><input class="cx-input" id="${prefix}_patient_phone" inputmode="tel" autocomplete="tel"></div>
          </div>
          <div class="cx-field-row">
            <div class="cx-field"><label>الجنس</label><select class="cx-select" id="${prefix}_patient_gender"><option value="">—</option><option value="male">ذكر</option><option value="female">أنثى</option></select></div>
            <div class="cx-field"><label>تاريخ الميلاد</label><input class="cx-input" id="${prefix}_patient_dob" type="date"></div>
          </div>
          <div class="cx-phone-warn" id="${prefix}_patient_duplicate" hidden></div>
        </div>`;
    if (opts.formOnly) {
      return `<div class="cx-inline-patient cx-inline-patient--bare">${form}</div>`;
    }
    return `
      <div class="cx-inline-patient">
        <button type="button" class="cx-inline-patient__toggle" id="${prefix}_patient_toggle" aria-expanded="false">
          <i class="fa fa-user-plus"></i><span>إضافة مريض جديد</span><small>بدون مغادرة النافذة</small>
        </button>
        ${form}
      </div>`;
  }

  function bindInlinePatientCreator(prefix, searchId, selectId) {
    const toggle = document.getElementById(`${prefix}_patient_toggle`);
    const form = document.getElementById(`${prefix}_patient_form`);
    const search = document.getElementById(searchId);
    const select = document.getElementById(selectId);
    if (!toggle || !form) return;
    const phone = document.getElementById(`${prefix}_patient_phone`);
    const duplicate = document.getElementById(`${prefix}_patient_duplicate`);
    const checkDuplicate = async () => {
      const value = phone?.value.trim() || "";
      if (!duplicate || value.length < 7) {
        if (duplicate) duplicate.hidden = true;
        return;
      }
      try {
        const check = await api(`/clinics/api/patients/check-phone?phone=${encodeURIComponent(value)}`);
        duplicate.hidden = !check.exists;
        duplicate.innerHTML = check.exists && check.patient
          ? `<i class="fa fa-circle-info"></i> يوجد مريض بهذا الرقم: <b>${esc(check.patient.full_name)}</b> — سيُستخدم سجله الحالي بدلاً من إنشاء سجل مكرر.`
          : "";
      } catch {
        duplicate.hidden = true;
      }
    };
    phone?.addEventListener("blur", checkDuplicate);
    phone?.addEventListener("input", () => {
      clearTimeout(phone._patientCheckTimer);
      phone._patientCheckTimer = setTimeout(checkDuplicate, 400);
    });
    toggle.onclick = () => {
      const opening = form.hidden;
      form.hidden = !opening;
      toggle.classList.toggle("is-active", opening);
      toggle.setAttribute("aria-expanded", String(opening));
      const span = toggle.querySelector("span");
      if (span) span.textContent = opening ? "اختيار مريض مسجل" : "إضافة مريض جديد";
      toggle.title = opening ? "إلغاء إضافة المريض" : "إضافة مريض جديد";
      toggle.setAttribute("aria-label", opening ? "إلغاء إضافة المريض" : "إضافة مريض جديد");
      const icon = toggle.querySelector("i");
      if (icon && toggle.classList.contains("cx-patient-picker__add")) {
        icon.className = opening ? "fa fa-xmark" : "fa fa-user-plus";
      }
      const picker = search?.closest(".cx-patient-picker");
      picker?.classList.toggle("is-adding", opening);
      search?.closest(".cx-field")?.classList.toggle("is-disabled", opening);
      if (select?.tagName === "SELECT") select.closest(".cx-field")?.classList.toggle("is-disabled", opening);
      if (search) search.disabled = opening;
      if (select && select.tagName === "SELECT") select.disabled = opening;
      const hits = document.getElementById("f_patient_hits") || document.getElementById(`${prefix}_patient_hits`);
      if (hits) hits.hidden = true;
      if (opening) {
        if (select && select.tagName !== "SELECT") select.value = "";
        const picked = document.getElementById("f_patient_picked");
        if (picked) {
          picked.hidden = true;
          picked.innerHTML = "";
        }
        document.getElementById(`${prefix}_patient_name`)?.focus();
      }
    };
  }

  async function resolveInlinePatient(prefix) {
    const form = document.getElementById(`${prefix}_patient_form`);
    if (!form || form.hidden) return null;
    if (form.dataset.resolvedPatientId) return Number(form.dataset.resolvedPatientId);
    const name = document.getElementById(`${prefix}_patient_name`).value.trim();
    const phone = document.getElementById(`${prefix}_patient_phone`).value.trim();
    if (!name) throw new Error("اسم المريض الجديد مطلوب");
    if (phone) {
      const check = await api(`/clinics/api/patients/check-phone?phone=${encodeURIComponent(phone)}`);
      if (check.exists && check.patient) {
        showNotice(`تم اختيار المريض المسجل مسبقاً: ${check.patient.full_name}`, false);
        form.dataset.resolvedPatientId = String(check.patient.id);
        return Number(check.patient.id);
      }
    }
    const created = await api("/clinics/api/patients", {
      method: "POST",
      body: JSON.stringify({
        full_name: name,
        phone,
        gender: document.getElementById(`${prefix}_patient_gender`).value,
        date_of_birth: document.getElementById(`${prefix}_patient_dob`).value,
      }),
    });
    form.dataset.resolvedPatientId = String(created.id);
    return Number(created.id);
  }

  window.ClinicsPatientInline = {
    html: inlinePatientCreatorHtml,
    bind: bindInlinePatientCreator,
    resolve: resolveInlinePatient,
  };

  function appointmentSpecialtyPack(specialty) {
    const code = String(specialty?.code || "").toLowerCase();
    const name = String(specialty?.name_ar || specialty?.name_en || "");
    const packs = {
      dentistry: {
        title: "تفاصيل الأسنان",
        fields: [
          { id: "f_tooth", key: "tooth", label: "رقم السن", type: "text", placeholder: "مثال 16", bind: "tooth" },
          { id: "f_spec_priority", key: "priority", label: "أولوية الجلسة", type: "select", options: ["عادية", "ألم", "طارئة"] },
        ],
      },
      pediatrics: {
        title: "تفاصيل الأطفال",
        fields: [
          { id: "f_spec_age", key: "child_age", label: "عمر الطفل", type: "text", placeholder: "مثال: 3 سنوات" },
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "حمى، سعال، تطعيم…" },
        ],
      },
      obstetrics_gynecology: {
        title: "تفاصيل النسائية والتوليد",
        fields: [
          { id: "f_spec_preg_week", key: "pregnancy_week", label: "أسبوع الحمل (إن وجد)", type: "number", placeholder: "24" },
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "متابعة حمل، دورة…" },
        ],
      },
      gynecology: {
        title: "تفاصيل النسائية",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "نزيف، ألم حوض…" },
        ],
      },
      cardiology: {
        title: "تفاصيل القلب",
        fields: [
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مستعجلة", "طارئة"] },
          { id: "f_spec_reason", key: "reason", label: "العَرَض الرئيسي", type: "text", placeholder: "ألم صدري، خفقان…" },
        ],
      },
      urology: {
        title: "تفاصيل المسالك البولية",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "الشكوى", type: "text", placeholder: "ألم خاصرة، حرقة بول…" },
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مغص كلوي", "طارئة"] },
        ],
      },
      ophthalmology: {
        title: "تفاصيل العيون",
        fields: [
          { id: "f_spec_eye", key: "eye_side", label: "العين", type: "select", options: ["اليمنى", "اليسرى", "كلتاهما"] },
          { id: "f_spec_reason", key: "reason", label: "الشكوى", type: "text", placeholder: "احمرار، ضعف بصر…" },
        ],
      },
      ent: {
        title: "تفاصيل الأنف والأذن",
        fields: [
          { id: "f_spec_side", key: "side", label: "الجانب", type: "select", options: ["أيمن", "أيسر", "ثنائي"] },
          { id: "f_spec_reason", key: "reason", label: "الشكوى", type: "text", placeholder: "ألم أذن، انسداد أنف…" },
        ],
      },
      orthopedics: {
        title: "تفاصيل العظام",
        fields: [
          { id: "f_spec_site", key: "site", label: "موقع الألم/الإصابة", type: "text", placeholder: "ركبة، ظهر…" },
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "بعد إصابة", "طارئة"] },
        ],
      },
      dermatology: {
        title: "تفاصيل الجلدية",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "الشكوى الجلدية", type: "text", placeholder: "طفح، حكة…" },
        ],
      },
      neurology: {
        title: "تفاصيل الأعصاب",
        fields: [
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مستعجلة", "طارئة"] },
          { id: "f_spec_reason", key: "reason", label: "الشكوى", type: "text", placeholder: "صداع، تنميل…" },
        ],
      },
      general_surgery: {
        title: "تفاصيل الجراحة",
        fields: [
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مستعجلة", "بطن حاد"] },
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "فتق، جرح، ألم بطن…" },
        ],
      },
      internal_medicine: {
        title: "تفاصيل الباطنية",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "متابعة مزمن، إعياء…" },
        ],
      },
      endocrinology: {
        title: "تفاصيل الغدد والسكري",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "متابعة سكري، درقية…" },
        ],
      },
      pulmonology: {
        title: "تفاصيل الصدرية",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "الشكوى", type: "text", placeholder: "سعال، ضيق تنفس…" },
        ],
      },
      gastroenterology: {
        title: "تفاصيل الجهاز الهضمي",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "الشكوى", type: "text", placeholder: "حموضة، ألم بطن…" },
        ],
      },
      nephrology: {
        title: "تفاصيل الكلى",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "متابعة كرياتينين…" },
        ],
      },
      rheumatology: {
        title: "تفاصيل الروماتيزم",
        fields: [
          { id: "f_spec_site", key: "site", label: "المفصل/الموقع", type: "text", placeholder: "ركبة، يد…" },
        ],
      },
      psychiatry: {
        title: "تفاصيل الطب النفسي",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "قلق، أرق…" },
        ],
      },
      physiotherapy: {
        title: "تفاصيل العلاج الطبيعي",
        fields: [
          { id: "f_spec_site", key: "site", label: "المنطقة", type: "text", placeholder: "ظهر، رقبة…" },
          { id: "f_spec_session", key: "session_no", label: "رقم الجلسة", type: "number", placeholder: "1" },
        ],
      },
      nutrition: {
        title: "تفاصيل التغذية",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "الهدف", type: "text", placeholder: "إنقاص وزن، سكري…" },
        ],
      },
      family_medicine: {
        title: "تفاصيل طب الأسرة",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "متابعة مزمن، فحص دوري…" },
        ],
      },
      general_medicine: {
        title: "تفاصيل الطب العام",
        fields: [
          { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "سعال، حمى…" },
        ],
      },
      labs: {
        title: "تفاصيل التحاليل",
        fields: [
          { id: "f_spec_fasting", key: "fasting", label: "صيام", type: "select", options: ["غير مطلوب", "صائم 8 ساعات", "صائم 12 ساعة"] },
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مستعجلة", "طارئة"] },
          { id: "f_spec_reason", key: "reason", label: "نوع التحليل / ملاحظة", type: "text", placeholder: "CBC، سكر صائم…" },
        ],
      },
      radiology: {
        title: "تفاصيل الأشعة",
        fields: [
          { id: "f_spec_body", key: "body_part", label: "المنطقة", type: "text", placeholder: "صدر، بطن، ركبة…" },
          { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مستعجلة"] },
          { id: "f_spec_reason", key: "reason", label: "نوع التصوير", type: "text", placeholder: "X-ray، سونار، CT…" },
        ],
      },
    };

    if (packs[code]) return packs[code];
    if (/تحليل|مختبر|lab/i.test(`${code} ${name}`)) return packs.labs;
    if (/أشع|تصوير|rad|x-?ray|سونار/i.test(`${code} ${name}`)) return packs.radiology;
    if (/سن|أسنان|dental|tooth/i.test(`${code} ${name}`)) return packs.dentistry;
    if (/طفل|أطفال|pedia/i.test(`${code} ${name}`)) return packs.pediatrics;
    if (/نسا|توليد|gyn|obstet/i.test(`${code} ${name}`)) return packs.obstetrics_gynecology;
    if (/قلب|cardio/i.test(`${code} ${name}`)) return packs.cardiology;
    if (/مسالك|بولي|uro/i.test(`${code} ${name}`)) return packs.urology;
    return {
      title: specialty?.name_ar ? `تفاصيل ${specialty.name_ar}` : "تفاصيل الموعد",
      fields: [
        { id: "f_spec_reason", key: "reason", label: "سبب المراجعة", type: "text", placeholder: "اكتب سبب الموعد باختصار" },
        { id: "f_spec_priority", key: "priority", label: "الأولوية", type: "select", options: ["عادية", "مستعجلة"] },
      ],
    };
  }

  function renderAppointmentSpecialtyFields(specialty, dentalContext = null) {
    const pack = appointmentSpecialtyPack(specialty);
    if (!pack?.fields?.length) return "";
    const fieldsHtml = pack.fields.map((field) => {
      const prefill =
        field.bind === "tooth" && dentalContext?.toothNumber
          ? dentalContext.toothNumber
          : "";
      if (field.type === "select") {
        return `<div class="cx-field"><label>${esc(field.label)}</label>
          <select class="cx-select" id="${esc(field.id)}" data-appt-spec="${esc(field.key)}">
            ${(field.options || []).map((o, i) => `<option value="${esc(o)}" ${i === 0 ? "selected" : ""}>${esc(o)}</option>`).join("")}
          </select></div>`;
      }
      const inputType = field.type === "number" ? "number" : "text";
      return `<div class="cx-field"><label>${esc(field.label)}</label>
        <input class="cx-input" type="${inputType}" id="${esc(field.id)}" data-appt-spec="${esc(field.key)}" value="${esc(prefill)}" placeholder="${esc(field.placeholder || "")}"></div>`;
    }).join("");
    return `<div class="cx-appt-spec-panel" id="f_specialty_panel">
      <div class="cx-appt-spec-panel__head"><strong>${esc(pack.title)}</strong><span>حسب الاختصاص المختار</span></div>
      <div class="cx-field-row">${fieldsHtml}</div>
    </div>`;
  }

  function collectAppointmentSpecialtyNotes() {
    const bits = [];
    document.querySelectorAll("[data-appt-spec]").forEach((el) => {
      if (el.closest?.("[hidden]")) return;
      const val = String(el.value || "").trim();
      if (!val) return;
      const label = el.closest(".cx-field")?.querySelector("label")?.textContent || el.dataset.apptSpec;
      bits.push(`${label}: ${val}`);
    });
    return bits.join(" · ");
  }

  function appointmentFormFields(dentalContext = null) {
    const doctors = (state.bootstrap?.doctors || []).filter((d) => d.active !== false);
    const services = (state.bootstrap?.services || []).filter((s) => s.active !== false);
    const specialties = (state.bootstrap?.specialties || []).filter((s) => s.is_active !== false);
    return `
      <div class="cx-appt-form" data-finora-section="appointment.form">
        <section class="cx-appt-section">
          <div class="cx-appt-section__title">1) المريض</div>
          <div class="cx-patient-picker">
            <label class="cx-patient-picker__label" for="f_patient_q">بحث مريض / رقم ملف</label>
            <div class="cx-patient-picker__row">
              <div class="cx-patient-picker__search">
                <i class="fa fa-magnifying-glass"></i>
                <input class="cx-input" id="f_patient_q" type="search" autocomplete="off" data-finora-field="appointment.patient_search" placeholder="الاسم، الهاتف أو رقم الملف">
              </div>
              <button type="button" class="cx-patient-picker__add" id="appt_patient_toggle" title="إضافة مريض جديد" aria-label="إضافة مريض جديد" aria-expanded="false">
                <i class="fa fa-user-plus"></i>
              </button>
            </div>
            <input type="hidden" id="f_patient_id" value="">
            <div class="cx-patient-picker__picked" id="f_patient_picked" data-finora-section="appointment.patient_picked" hidden></div>
            <div class="cx-patient-picker__drop" id="f_patient_hits" hidden></div>
            ${inlinePatientCreatorHtml("appt", { formOnly: true })}
          </div>
        </section>

        <section class="cx-appt-section">
          <div class="cx-appt-section__title">2) الاختصاص والطبيب</div>
          <div class="cx-field-row">
            <div class="cx-field"><label>الاختصاص</label>
              <select class="cx-select" id="f_specialty_id" data-finora-field="appointment.specialty"><option value="">اختر الاختصاص…</option>${specialties.map((s) => `<option value="${s.id}" data-code="${esc(s.code || "")}">${esc(s.name_ar)}</option>`).join("")}</select>
            </div>
            <div class="cx-field"><label>الطبيب</label>
              <select class="cx-select" id="f_doctor_id" data-finora-field="appointment.doctor">
                <option value="">—</option>
                ${doctors.map((d) => `<option value="${d.id}">${esc(d.full_name)}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="cx-field"><label>الخدمة</label>
            <select class="cx-select" id="f_service_id" data-finora-field="appointment.service">
              <option value="">—</option>
              ${services.map((s) => `<option value="${s.id}" data-duration="${s.duration_minutes || 15}" data-requires-tooth="${s.requires_tooth ? "1" : "0"}">${esc(s.name)} · ${money(s.price)}</option>`).join("")}
            </select>
            <small id="f_service_hint" style="display:block;margin-top:4px;color:var(--cx-muted)">تظهر حسب الاختصاص والطبيب</small>
          </div>
        </section>

        <section class="cx-appt-section" id="f_specialty_fields_wrap">
          <div class="cx-appt-section__title">3) حقول الاختصاص</div>
          <div id="f_specialty_fields"><div class="cx-empty" style="padding:10px">اختر اختصاصاً لإظهار الحقول الخاصة به</div></div>
        </section>

        <section class="cx-appt-section">
          <div class="cx-appt-section__title">4) الموعد</div>
          <div class="cx-field-row">
            <div class="cx-field"><label>التاريخ</label><input class="cx-input" type="date" id="f_date" data-finora-field="appointment.date" value="${esc(state.day)}"></div>
            <div class="cx-field"><label>الوقت</label><input class="cx-input" type="time" id="f_time" data-finora-field="appointment.time" value="09:00"></div>
          </div>
          <div class="cx-field"><label>المدة (دقيقة)</label><input class="cx-input" type="number" min="5" id="f_duration" data-finora-field="appointment.duration" value="${esc(String(dentalContext?.durationMinutes || ""))}"></div>
          ${dentalContext ? `<div class="cx-dental-appt-context"><i class="fa fa-tooth"></i><div><strong>جلسة علاج أسنان</strong><small>${esc(dentalContext.title || "علاج")}${dentalContext.toothNumber ? ` · السن ${esc(dentalContext.toothNumber)}` : ""}${dentalContext.sessionNumber ? ` · الجلسة ${esc(dentalContext.sessionNumber)}` : ""}</small><span>سيتم ربط الجلسة بالموعد بعد إنشاء الموعد.</span></div></div>` : ""}
          <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="f_notes" data-finora-field="appointment.notes">${esc(dentalContext?.notes || "")}</textarea></div>
        </section>
      </div>
    `;
  }

  function idList(values) {
    return (values || []).map((v) => Number(v)).filter((n) => Number.isFinite(n) && n > 0);
  }

  function serviceMatchesSelection(service, specialtyId, doctorId) {
    const sid = Number(specialtyId || 0);
    const did = Number(doctorId || 0);
    const specIds = idList(service?.specialty_ids);
    const docIds = idList(service?.doctor_ids);

    // Specialty chosen → only services linked to that specialty.
    // Unscoped (general) services appear only when no specialty is selected.
    if (sid) {
      if (!specIds.includes(sid)) return false;
    }

    // Doctor chosen → if service is limited to doctors, doctor must be in the list.
    if (did && docIds.length && !docIds.includes(did)) return false;

    return true;
  }

  function rankPatientHits(rows, term) {
    const t = String(term || "").trim().toLowerCase();
    const score = (p) => {
      const file = String(p.file_number || "").toLowerCase();
      const phone = String(p.phone || "").replace(/\s+/g, "");
      const name = String(p.full_name || "").toLowerCase();
      const nid = String(p.national_id || "").toLowerCase();
      const tPhone = t.replace(/\s+/g, "");
      if (file === t || phone === tPhone || nid === t) return 0;
      if (file.startsWith(t) || phone.startsWith(tPhone)) return 1;
      if (name.startsWith(t)) return 2;
      if (name.includes(t) || file.includes(t) || phone.includes(tPhone)) return 3;
      return 4;
    };
    return [...(rows || [])].sort((a, b) => score(a) - score(b) || String(a.full_name || "").localeCompare(String(b.full_name || ""), "ar"));
  }

  function highlightPatientTerm(text, term) {
    const raw = String(text || "");
    const t = String(term || "").trim();
    if (!t) return esc(raw);
    const i = raw.toLowerCase().indexOf(t.toLowerCase());
    if (i < 0) return esc(raw);
    return `${esc(raw.slice(0, i))}<mark>${esc(raw.slice(i, i + t.length))}</mark>${esc(raw.slice(i + t.length))}`;
  }

  async function bindPatientSearch(opts = {}) {
    const q = document.getElementById("f_patient_q");
    const sel = document.getElementById("f_patient_id");
    const hits = document.getElementById("f_patient_hits");
    const picked = document.getElementById("f_patient_picked");
    if (!q || !sel) return;
    const comboMode = Boolean(hits) && sel.tagName !== "SELECT";
    let activeIndex = -1;
    let lastRows = [];

    const closeAddForm = () => {
      const form = document.getElementById("appt_patient_form");
      const toggle = document.getElementById("appt_patient_toggle");
      if (!form || form.hidden) return;
      form.hidden = true;
      toggle?.classList.remove("is-active");
      toggle?.setAttribute("aria-expanded", "false");
      q.closest(".cx-patient-picker")?.classList.remove("is-adding");
      q.disabled = false;
      const icon = toggle?.querySelector("i");
      if (icon && toggle?.classList.contains("cx-patient-picker__add")) icon.className = "fa fa-user-plus";
    };

    const markPicked = (p) => {
      if (!p) {
        sel.value = "";
        if (picked) {
          picked.hidden = true;
          picked.innerHTML = "";
        }
        return;
      }
      closeAddForm();
      sel.value = String(p.id);
      if (sel.tagName === "SELECT") {
        if (![...sel.options].some((o) => o.value === String(p.id))) {
          const opt = document.createElement("option");
          opt.value = String(p.id);
          opt.textContent = `${p.full_name} · ${p.file_number || ""} · ${p.phone || ""}`;
          sel.appendChild(opt);
        }
        sel.value = String(p.id);
      }
      if (picked) {
        const meta = [p.file_number, p.phone].filter(Boolean).join(" · ");
        picked.hidden = false;
        picked.innerHTML = `
          <div class="cx-patient-picker__chip">
            <i class="fa fa-user"></i>
            <div>
              <strong>${esc(p.full_name)}</strong>
              <small>${esc(meta || "تم الاختيار")}</small>
            </div>
            <button type="button" class="cx-patient-picker__clear" id="f_patient_clear" title="إلغاء الاختيار" aria-label="إلغاء الاختيار">
              <i class="fa fa-xmark"></i>
            </button>
          </div>`;
        picked.querySelector("#f_patient_clear")?.addEventListener("click", () => {
          markPicked(null);
          q.value = "";
          q.focus();
        });
      }
      if (hits) {
        hits.hidden = true;
        hits.innerHTML = "";
      }
    };

    const renderHits = (rows, term) => {
      lastRows = rows;
      activeIndex = rows.length ? 0 : -1;
      if (!comboMode) {
        sel.innerHTML =
          `<option value="">اختر المريض…</option>` +
          rows
            .slice(0, 40)
            .map((p) => `<option value="${p.id}">${esc(p.full_name)} · ${esc(p.file_number)} · ${esc(p.phone)}</option>`)
            .join("");
        return;
      }
      if (!term.trim()) {
        hits.hidden = true;
        hits.innerHTML = "";
        return;
      }
      if (!rows.length) {
        hits.hidden = false;
        hits.innerHTML = `<div class="cx-patient-picker__empty">لا توجد نتائج — أضف مريضاً من الزر المربع بجانب البحث</div>`;
        return;
      }
      hits.hidden = false;
      hits.innerHTML = rows
        .slice(0, 8)
        .map(
          (p, i) => `
        <button type="button" class="cx-patient-picker__hit${i === 0 ? " is-active" : ""}" data-idx="${i}" data-finora-action="appointment.patient_pick">
          <strong>${highlightPatientTerm(p.full_name, term)}</strong>
          <span>${highlightPatientTerm(p.file_number || "بدون رقم ملف", term)} · ${highlightPatientTerm(p.phone || "بدون هاتف", term)}</span>
        </button>`
        )
        .join("");
      hits.querySelectorAll("[data-idx]").forEach((btn) => {
        btn.onclick = () => {
          const p = lastRows[Number(btn.dataset.idx)];
          if (!p) return;
          q.value = p.full_name;
          markPicked(p);
        };
      });
    };

    const fill = async () => {
      const term = (q.value || "").trim();
      if (comboMode && !term) {
        renderHits([], "");
        return;
      }
      const qs = comboMode
        ? `q=${encodeURIComponent(term)}&limit=20`
        : `q=${encodeURIComponent(term)}`;
      try {
        const rows = await api(`/clinics/api/patients?${qs}`);
        const list = rankPatientHits(Array.isArray(rows) ? rows : [], term);
        renderHits(list, term);
        if (comboMode && list.length === 1) {
          const p = list[0];
          const t = term.toLowerCase();
          const phone = String(p.phone || "").replace(/\s+/g, "");
          if ([String(p.file_number || "").toLowerCase(), phone, String(p.national_id || "").toLowerCase()].includes(t)) {
            q.value = p.full_name;
            markPicked(p);
          }
        }
      } catch {
        if (comboMode) {
          hits.hidden = false;
          hits.innerHTML = `<div class="cx-patient-picker__empty">تعذر البحث، حاول مرة أخرى</div>`;
        }
      }
    };

    q.addEventListener("input", () => {
      if (comboMode && sel.value) markPicked(null);
      clearTimeout(q._t);
      q._t = setTimeout(fill, 180);
    });
    q.addEventListener("keydown", (e) => {
      if (!comboMode || hits.hidden) return;
      const items = [...hits.querySelectorAll("[data-idx]")];
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!items.length) return;
        activeIndex = e.key === "ArrowDown"
          ? Math.min(items.length - 1, activeIndex + 1)
          : Math.max(0, activeIndex - 1);
        items.forEach((el, i) => el.classList.toggle("is-active", i === activeIndex));
        items[activeIndex]?.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter" && activeIndex >= 0 && lastRows[activeIndex]) {
        e.preventDefault();
        const p = lastRows[activeIndex];
        q.value = p.full_name;
        markPicked(p);
      } else if (e.key === "Escape") {
        hits.hidden = true;
      }
    });
    q.addEventListener("focus", () => {
      if (comboMode && (q.value || "").trim() && hits.innerHTML && !sel.value) hits.hidden = false;
    });
    const onDocDown = (e) => {
      if (!q.isConnected) {
        document.removeEventListener("mousedown", onDocDown);
        return;
      }
      if (!comboMode) return;
      if (!hits.contains(e.target) && e.target !== q && !q.contains(e.target)) hits.hidden = true;
    };
    document.addEventListener("mousedown", onDocDown);

    if (opts.fixedPatientId) {
      try {
        const data = await api(`/clinics/api/patients/${opts.fixedPatientId}`);
        const p = data.patient || data;
        if (p?.id) {
          q.value = p.full_name || "";
          markPicked(p);
          return;
        }
      } catch {
        /* keep empty picker */
      }
    }
    if (!comboMode) await fill();
  }

  /* ── Pages ─────────────────────────────────────────────── */

  async function renderDashboard() {
    if (window.ClinicsDashboard) {
      await window.ClinicsDashboard.render(state, root, {
        api,
        esc,
        badge,
        money,
        showNotice,
        bootstrap: state.bootstrap,
        promptNewPatient,
        promptNewAppointment,
      });
      return;
    }
    const data = await api(`/clinics/api/dashboard?date=${encodeURIComponent(state.day)}`);
    const k = data.kpis || {};
    root.innerHTML = `
      <section class="cx-hero">
        <div>
          <div class="cx-kicker">Finora Clinics</div>
          <h1>نبض العيادة اليوم</h1>
          <p>${esc(data.settings?.clinic_name || "عيادتك")} · ${esc(data.settings?.organization_mode_label || data.settings?.clinic_type_label || "")} — متابعة المواعيد والطابور والإيراد من مكان واحد.</p>
        </div>
        <div class="cx-actions">
          <input type="date" class="cx-input" id="cxDay" value="${esc(state.day)}">
          <button type="button" class="cx-btn" id="btnNewPatient"><i class="fa fa-user-plus"></i> مريض</button>
          <button type="button" class="cx-btn cx-btn--primary" id="btnNewAppt"><i class="fa fa-calendar-plus"></i> موعد</button>
          <a class="cx-btn" href="/clinics/reception"><i class="fa fa-desktop"></i> الاستقبال</a>
        </div>
      </section>
      <section class="cx-kpis">
        <article class="cx-kpi"><span>مواعيد اليوم</span><strong>${k.appointments_today || 0}</strong><em>${k.arrived || 0} حضروا</em></article>
        <article class="cx-kpi"><span>في الانتظار</span><strong>${k.waiting || 0}</strong><em>${k.in_consultation || 0} عند الطبيب</em></article>
        <article class="cx-kpi"><span>زيارات مكتملة</span><strong>${k.completed_visits || 0}</strong><em>${k.cancelled || 0} ملغاة · ${k.no_show || 0} لم يحضر</em></article>
        <article class="cx-kpi"><span>إيراد اليوم</span><strong class="cx-money">${money(k.revenue_today)}</strong><em>آجل ${money(k.open_balance)}</em></article>
      </section>
    `;
    document.getElementById("cxDay").onchange = (e) => {
      state.day = e.target.value;
      render();
    };
    document.getElementById("btnNewPatient").onclick = () => promptNewPatient();
    document.getElementById("btnNewAppt").onclick = () => promptNewAppointment();
  }

  function ticketHtml(a) {
    return `
      <article class="cx-ticket" style="--ticket-color:${esc(a.doctor_color || "#0d9488")}">
        <div class="cx-ticket__time">${esc(window.FinoraTime.clock(a.start_time))}${a.queue_number ? ` · #${a.queue_number}` : ""}</div>
        <div class="cx-ticket__name">${esc(a.patient_name)}</div>
        <div class="cx-ticket__meta">
          ${esc(a.doctor_name || "بدون طبيب")}<br>
          ${esc(a.service_name || "—")} · ${esc(a.patient_phone || "")}<br>
          ${badge(a.status)}
        </div>
        <div class="cx-ticket__actions">
          ${a.status === "pending" || a.status === "confirmed" ? `<button class="cx-btn cx-btn--sm cx-btn--primary" data-act="arrived" data-id="${a.id}">Check-in</button>` : ""}
          ${a.status === "arrived" ? `<button class="cx-btn cx-btn--sm" data-act="waiting" data-id="${a.id}">انتظار</button>` : ""}
          ${["arrived", "waiting", "confirmed"].includes(a.status) ? `<button class="cx-btn cx-btn--sm" data-act="start" data-id="${a.id}">للطبيب</button>` : ""}
          ${a.status === "in_consultation" ? `<a class="cx-btn cx-btn--sm cx-btn--primary" href="/clinics/visits">الزيارات</a>` : ""}
          ${!["completed", "cancelled", "no_show"].includes(a.status) ? `<button class="cx-btn cx-btn--sm cx-btn--danger" data-act="cancel" data-id="${a.id}">إلغاء</button>` : ""}
          <a class="cx-btn cx-btn--sm cx-btn--ghost" href="/clinics/patients/${a.patient_id}">الملف</a>
        </div>
      </article>`;
  }

  async function renderReception() {
    if (window.ClinicsReception) {
      await window.ClinicsReception.render(state, root, {
        api,
        esc,
        badge,
        money,
        showNotice,
        bootstrap: state.bootstrap,
        promptNewPatient,
        promptNewAppointment,
        openModal,
      });
      return;
    }
    const qs = new URLSearchParams({ date: state.day });
    if (state.doctorFilter) qs.set("doctor_id", state.doctorFilter);
    const data = await api(`/clinics/api/reception?${qs}`);
    const cols = [
      ["confirmed", "مؤكد / قادم", [...(data.columns.pending || []), ...(data.columns.confirmed || [])]],
      ["waiting", "حضر / انتظار", [...(data.columns.arrived || []), ...(data.columns.waiting || [])]],
      ["in_consultation", "عند الطبيب", data.columns.in_consultation || []],
      ["completed", "مكتمل / أخرى", [...(data.columns.completed || []), ...(data.columns.cancelled || []), ...(data.columns.no_show || [])]],
    ];
    root.innerHTML = `
      <section class="cx-hero">
        <div>
          <div class="cx-kicker">Reception Desk</div>
          <h1>لوحة الاستقبال</h1>
          <p>سير يوم العيادة بضغطة واحدة: تسجيل حضور، طابور، وإرسال للمريض إلى الطبيب.</p>
        </div>
        <div class="cx-actions">
          <input type="date" class="cx-input" id="cxDay" value="${esc(state.day)}">
          <select class="cx-select" id="cxDoctor">
            <option value="">كل الأطباء</option>
            ${(data.doctors || []).map((d) => `<option value="${d.id}" ${String(d.id) === String(state.doctorFilter) ? "selected" : ""}>${esc(d.full_name)}</option>`).join("")}
          </select>
          <button type="button" class="cx-btn" id="btnNewPatient"><i class="fa fa-user-plus"></i> مريض</button>
          <button type="button" class="cx-btn cx-btn--primary" id="btnNewAppt"><i class="fa fa-calendar-plus"></i> موعد</button>
        </div>
      </section>
      <section class="cx-board">
        ${cols
          .map(
            ([key, title, items]) => `
          <div class="cx-col" data-col="${key}">
            <div class="cx-col__head"><h3>${title}</h3><span class="cx-col__count">${items.length}</span></div>
            ${items.map(ticketHtml).join("") || '<div class="cx-empty">فارغ</div>'}
          </div>`
          )
          .join("")}
      </section>
    `;
    document.getElementById("cxDay").onchange = (e) => {
      state.day = e.target.value;
      render();
    };
    document.getElementById("cxDoctor").onchange = (e) => {
      state.doctorFilter = e.target.value;
      render();
    };
    document.getElementById("btnNewPatient").onclick = () => promptNewPatient();
    document.getElementById("btnNewAppt").onclick = () => promptNewAppointment();
    root.querySelectorAll("[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const id = btn.dataset.id;
          const act = btn.dataset.act;
          if (act === "start") {
            const visit = await api("/clinics/api/visits", {
              method: "POST",
              body: JSON.stringify({ appointment_id: Number(id) }),
            });
            location.href = `/clinics/doctor/${visit.id}`;
            return;
          }
          const map = { arrived: "arrived", waiting: "waiting", cancel: "cancelled" };
          await api(`/clinics/api/appointments/${id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: map[act] }),
          });
          await render();
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });
    });
  }

  async function renderQueue() {
    if (window.ClinicsQueue) {
      await window.ClinicsQueue.render(state, root, {
        api,
        esc,
        money,
        showNotice,
        bootstrap: state.bootstrap,
        openModal,
        promptNewPatient,
      });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة قائمة الانتظار</div>`;
  }

  async function renderAppointments() {
    if (window.ClinicsAppointments) {
      await window.ClinicsAppointments.render(state, root, {
        api,
        esc,
        badge,
        money,
        showNotice,
        bootstrap: state.bootstrap,
        statusLabel,
        promptNewPatient,
        promptNewAppointment,
        openModal,
      });
      return;
    }
    await renderCalendar("list");
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

  async function renderCalendar(forcedView) {
    if (window.ClinicsAppointments) {
      if (forcedView) state.apptView = forcedView;
      else if (!state.apptView && state.calView) state.apptView = state.calView;
      await renderAppointments();
      return;
    }
    const view = forcedView || state.calView || "week";
    state.calView = view;
    let start = state.day;
    let end = state.day;
    if (view === "week") {
      start = weekStart(state.day);
      end = addDays(start, 6);
    } else if (view === "month") {
      const d = new Date(state.day + "T12:00:00");
      start = new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
      end = new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
    }
    const doctorQ = state.doctorFilter ? `&doctor_id=${encodeURIComponent(state.doctorFilter)}` : "";
    const rows = await api(`/clinics/api/calendar?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}${doctorQ}`);
    const doctors = (state.bootstrap && state.bootstrap.doctors) || [];
    const hours = Array.from({ length: 12 }, (_, i) => 8 + i);
    const days = [];
    for (let cur = start; cur <= end; cur = addDays(cur, 1)) days.push(cur);

    root.innerHTML = `
      <section class="cx-hero">
        <div>
          <div class="cx-kicker">Clinic Calendar</div>
          <h1>التقويم</h1>
          <p>عرض يومي/أسبوعي/شهري مع إعادة جدولة بعد التأكيد.</p>
        </div>
        <div class="cx-actions">
          <input type="date" class="cx-input" id="cxDay" value="${esc(state.day)}">
          <select class="cx-select" id="cxDoctor"><option value="">كل الأطباء</option>
            ${doctors.map((d) => `<option value="${d.id}" ${String(state.doctorFilter) === String(d.id) ? "selected" : ""}>${esc(d.full_name)}</option>`).join("")}
          </select>
          <button class="cx-btn ${view === "day" || view === "list" ? "cx-btn--primary" : ""}" data-view="day">يوم</button>
          <button class="cx-btn ${view === "week" ? "cx-btn--primary" : ""}" data-view="week">أسبوع</button>
          <button class="cx-btn ${view === "month" ? "cx-btn--primary" : ""}" data-view="month">شهر</button>
          <button class="cx-btn cx-btn--primary" id="btnNewAppt">موعد جديد</button>
        </div>
      </section>
      ${view === "list" || view === "day" ? `
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>الوقت</th><th>المريض</th><th>الطبيب</th><th>الخدمة</th><th>الحالة</th><th></th></tr></thead>
        <tbody>
          ${rows.map((a) => `
            <tr>
              <td>${esc(a.appointment_date)} ${esc(window.FinoraTime.clock(a.start_time))}</td>
              <td><a href="/clinics/patients/${a.patient_id}">${esc(a.patient_name)}</a></td>
              <td>${esc(a.doctor_name || "—")}</td>
              <td>${esc(a.service_name || "—")}</td>
              <td>${badge(a.status)}</td>
              <td><button class="cx-btn cx-btn--sm" data-reschedule="${a.id}" data-date="${esc(a.appointment_date)}" data-time="${esc(a.start_time)}">نقل</button></td>
            </tr>`).join("") || `<tr><td colspan="6"><div class="cx-empty">لا مواعيد</div></td></tr>`}
        </tbody>
      </table></div></article>` : `
      <article class="cx-card cx-cal">
        <div class="cx-cal__grid" style="grid-template-columns: 64px repeat(${days.length}, minmax(120px,1fr))">
          <div class="cx-cal__corner"></div>
          ${days.map((d) => `<div class="cx-cal__dayhead">${esc(d)}</div>`).join("")}
          ${hours.map((h) => {
            const label = String(h).padStart(2, "0") + ":00";
            return `<div class="cx-cal__hour">${label}</div>` + days.map((d) => {
              const cell = rows.filter((a) => a.appointment_date === d && (a.start_time || "").startsWith(String(h).padStart(2, "0")));
              return `<div class="cx-cal__cell" data-drop-date="${d}" data-drop-hour="${h}">
                ${cell.map((a) => `<button type="button" class="cx-cal__event" draggable="true" data-id="${a.id}" data-date="${esc(a.appointment_date)}" data-time="${esc(a.start_time)}" style="border-color:${esc(a.doctor_color || "#0d9488")}">
                  <b>${esc(window.FinoraTime.clock(a.start_time))}</b> ${esc(a.patient_name)}
                </button>`).join("")}
              </div>`;
            }).join("");
          }).join("")}
        </div>
      </article>`}
    `;
    document.getElementById("cxDay").onchange = (e) => { state.day = e.target.value; render(); };
    document.getElementById("cxDoctor").onchange = (e) => { state.doctorFilter = e.target.value; render(); };
    root.querySelectorAll("[data-view]").forEach((btn) => {
      btn.onclick = () => { state.calView = btn.dataset.view; render(); };
    });
    document.getElementById("btnNewAppt").onclick = () => promptNewAppointment();

    const doReschedule = (id, date, time) => {
      openModal("إعادة جدولة الموعد", `
        <div class="cx-field"><label>التاريخ</label><input class="cx-input" type="date" id="rs_date" value="${esc(date)}"></div>
        <div class="cx-field"><label>الوقت</label><input class="cx-input" type="time" id="rs_time" value="${esc(time)}"></div>
        <p style="color:var(--cx-muted)">سيتم التحقق من التعارض قبل الحفظ.</p>`, async () => {
        await api(`/clinics/api/appointments/${id}/reschedule`, {
          method: "POST",
          body: JSON.stringify({
            appointment_date: document.getElementById("rs_date").value,
            start_time: document.getElementById("rs_time").value,
          }),
        });
      });
    };

    root.querySelectorAll("[data-reschedule]").forEach((btn) => {
      btn.onclick = () => doReschedule(btn.dataset.reschedule, btn.dataset.date, btn.dataset.time);
    });
    root.querySelectorAll(".cx-cal__event").forEach((el) => {
      el.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/plain", JSON.stringify({ id: el.dataset.id, date: el.dataset.date, time: el.dataset.time }));
      });
      el.onclick = () => doReschedule(el.dataset.id, el.dataset.date, el.dataset.time);
    });
    root.querySelectorAll(".cx-cal__cell").forEach((cell) => {
      cell.addEventListener("dragover", (e) => e.preventDefault());
      cell.addEventListener("drop", async (e) => {
        e.preventDefault();
        try {
          const data = JSON.parse(e.dataTransfer.getData("text/plain") || "{}");
          const newDate = cell.dataset.dropDate;
          const newTime = String(cell.dataset.dropHour).padStart(2, "0") + ":00";
          if (!confirm(`نقل الموعد إلى ${newDate} ${newTime}؟`)) return;
          await api(`/clinics/api/appointments/${data.id}/reschedule`, {
            method: "POST",
            body: JSON.stringify({ appointment_date: newDate, start_time: newTime }),
          });
          showNotice("تمت إعادة الجدولة", false);
          await render();
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });
    });
  }

  async function renderPatients() {
    if (window.ClinicsPatients) {
      await window.ClinicsPatients.render(state, root, {
        api,
        esc,
        money,
        showNotice,
        bootstrap: state.bootstrap,
        openModal,
        promptNewAppointment,
        patientFormFields,
        readPatientForm,
      });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة المرضى</div>`;
  }

  async function renderPatientDetail() {
    if (window.ClinicsPatientProfile) {
      await window.ClinicsPatientProfile.render(state, root, {api, esc, money, showNotice, openModal, promptNewAppointment, patientFormFields, readPatientForm, patientId});
      return;
    }
    const data = await api(`/clinics/api/patients/${patientId}`);
    const p = data.patient;
    root.innerHTML = `
      <section class="cx-hero">
        <div>
          <div class="cx-kicker">${esc(p.file_number)}</div>
          <h1>${esc(p.full_name)}</h1>
          <p>${esc(p.phone || "بدون هاتف")} · ${p.age != null ? p.age + " سنة" : "العمر غير محدد"} · ${esc(p.blood_type || "")}</p>
        </div>
        <div class="cx-actions">
          <button type="button" class="cx-btn" id="btnEdit">تعديل</button>
          <button type="button" class="cx-btn" id="btnStmt">كشف حساب</button>
          <button type="button" class="cx-btn cx-btn--primary" id="btnAppt">حجز موعد</button>
          <a class="cx-btn" href="/clinics/patients">رجوع</a>
        </div>
      </section>
      <section class="cx-grid cx-grid--2">
        <article class="cx-card">
          <div class="cx-card__head"><div><h2>الملف الطبي المختصر</h2></div></div>
          <p><strong>الحساسية:</strong> ${esc(p.allergies || "لا يوجد")}</p>
          <p><strong>الأمراض المزمنة:</strong> ${esc(p.chronic_conditions || "لا يوجد")}</p>
          <p><strong>العنوان:</strong> ${esc(p.address || "—")}</p>
          <p><strong>ملاحظات:</strong> ${esc(p.notes || "—")}</p>
        </article>
        <article class="cx-card">
          <div class="cx-card__head"><div><h2>آخر الزيارات</h2></div></div>
          <div class="cx-feed">
            ${(data.visits || [])
              .map(
                (v) => `
              <div class="cx-feed__item">
                ${esc(v.visit_date)} · ${esc(v.doctor_name || "—")} · ${esc(v.status)}
                <small>${esc(v.chief_complaint || "بدون شكوى مسجلة")}</small>
                ${v.status === "open" ? `<div style="margin-top:8px"><a class="cx-btn cx-btn--sm cx-btn--primary" href="/clinics/doctor/${v.id}">متابعة الزيارة</a></div>` : ""}
              </div>`
              )
              .join("") || '<div class="cx-empty">لا زيارات</div>'}
          </div>
        </article>
      </section>
    `;
    document.getElementById("btnEdit").onclick = () => {
      openModal("تعديل مريض", patientFormFields(p), async () => {
        await api(`/clinics/api/patients/${p.id}`, {
          method: "PUT",
          body: JSON.stringify(readPatientForm()),
        });
      });
    };
    document.getElementById("btnAppt").onclick = () => promptNewAppointment(p.id);
    document.getElementById("btnStmt").onclick = async () => {
      try {
        const stmt = await api(`/clinics/api/patients/${p.id}/statement`);
        openModal(`كشف حساب — ${esc(p.full_name)}`, `
          <p><strong>الرصيد المستحق:</strong> ${money(stmt.outstanding_balance)}</p>
          <p style="color:var(--cx-muted);margin:0 0 12px">فواتير: ${money(stmt.total_invoices)} · مدفوعات: ${money(stmt.total_payments)}</p>
          <div class="cx-feed">
            ${(stmt.lines || []).map((l) => `
              <div class="cx-feed__item">
                <strong>${esc(l.reference)}</strong> · ${esc(l.date || "—")}
                <span>${money(l.debit || 0)} / ${money(l.credit || 0)} · رصيد ${money(l.balance)}</span>
              </div>`).join("") || '<div class="cx-empty">لا حركات</div>'}
          </div>`, async () => {});
      } catch (err) {
        showNotice(err.message || String(err));
      }
    };
  }

  async function renderVisits() {
    if (window.ClinicsVisits) {
      await window.ClinicsVisits.render(state, root, {
        api,
        esc,
        showNotice,
        openModal,
        promptNewAppointment,
      });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة الزيارات</div>`;
  }

  function printClinicDoc(title, bodyHtml) {
    const w = window.open("", "_blank", "width=800,height=900");
    if (!w) {
      showNotice("تعذر فتح نافذة الطباعة — اسمح بالنوافذ المنبثقة");
      return;
    }
    w.document.write(`<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>${esc(title)}</title>
      <style>body{font-family:"IBM Plex Sans Arabic",Tahoma,sans-serif;padding:24px;color:#111}
      h1{margin:0 0 4px;font-size:1.4rem} h2{margin:18px 0 8px;font-size:1rem}
      table{width:100%;border-collapse:collapse;margin-top:8px} th,td{padding:8px;border-bottom:1px solid #ddd;text-align:right;font-size:13px}
      .meta{color:#555;font-size:13px;margin-bottom:16px} .foot{margin-top:24px;font-size:12px;color:#666}</style></head><body>
      ${bodyHtml}<div class="foot">طباعة من Finora Clinics · ${window.FinoraTime.dateTime(Date.now())}</div></body></html>`);
    w.document.close();
    w.focus();
    w.print();
  }

  function specialtyFieldHtml(field, value, disabled) {
    const attrs = `data-specialty-field="${field.id}" data-field-type="${esc(field.field_type)}" ${disabled ? "disabled" : ""}`;
    const label = `<label>${esc(field.label_ar)}${field.required ? " *" : ""}${field.unit ? ` (${esc(field.unit)})` : ""}</label>`;
    const options = field.options || [];
    if (field.field_type === 'table') return `<div class="cx-field" data-specialty-table="${field.id}" data-columns="${esc(JSON.stringify(options))}">${label}<div style="overflow:auto"><table class="cx-table"><thead><tr>${options.map(o=>`<th>${esc(o)}</th>`).join('')}<th></th></tr></thead><tbody>${(Array.isArray(value)?value:[]).map(row=>`<tr>${options.map(o=>`<td><input class="cx-input" data-column="${esc(o)}" value="${esc(row[o]||'')}" ${disabled?'disabled':''}></td>`).join('')}<td>${disabled?'':'<button type="button" class="cx-btn" data-delete-row>حذف</button>'}</td></tr>`).join('')}</tbody></table></div>${disabled?'':'<button type="button" class="cx-btn" data-add-row>إضافة صف</button>'}</div>`;
    if (['file','image'].includes(field.field_type)) return `<div class="cx-field">${label}<input type="hidden" ${attrs} value="${esc(value || '')}">${value?`<a href="/clinics/attachments?patient_id=${patientId||''}">المرفق المحفوظ #${esc(value)}</a>`:''}${disabled?'':`<input type="file" data-upload-field="${field.id}" ${field.field_type==='image'?'accept="image/png,image/jpeg,image/webp"':''}><small data-upload-status="${field.id}"></small>`}</div>`;
    if (field.field_type === "dental_chart") {
      return `<div class="cx-field cx-dental-field" data-dental-mount data-visit-id="${esc(visitId || "")}" data-readonly="${disabled ? "1" : "0"}">${label}<div class="cx-dental-root"></div></div>`;
    }
    if (["pediatric_growth_history", "vaccination_history", "development_tracker"].includes(field.field_type)) {
      return `<div class="cx-field" data-pediatric-field="${esc(field.field_type)}">${label}<div class="cx-ped-field-note" style="font-size:12px;color:var(--cx-muted)">يُدار من لوحة طب الأطفال في مساحة الطبيب</div></div>`;
    }
    if (field.field_type === "textarea" || ["drawing", "body_map", "growth_chart", "pregnancy_tracker"].includes(field.field_type)) return `<div class="cx-field">${label}<textarea class="cx-textarea" ${attrs} placeholder="${esc(field.placeholder || "")}">${esc(typeof value === "string" ? value : (value == null ? "" : JSON.stringify(value)))}</textarea></div>`;
    if (["select", "radio"].includes(field.field_type)) return `<div class="cx-field">${label}<select class="cx-select" ${attrs}><option value="">—</option>${options.map((o) => `<option value="${esc(o)}" ${String(value ?? "") === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></div>`;
    if (field.field_type === "multi_select") { const selected = new Set(Array.isArray(value) ? value.map(String) : []); return `<div class="cx-field">${label}<div style="display:flex;gap:10px;flex-wrap:wrap">${options.map((o) => `<label><input type="checkbox" data-specialty-multi="${field.id}" value="${esc(o)}" ${selected.has(String(o)) ? "checked" : ""} ${disabled ? "disabled" : ""}> ${esc(o)}</label>`).join("")}</div></div>`; }
    if (["boolean", "checkbox"].includes(field.field_type)) return `<div class="cx-field"><label><input type="checkbox" ${attrs} ${value === true || value === "true" ? "checked" : ""}> ${esc(field.label_ar)}</label></div>`;
    const type = field.field_type === 'measurement' ? 'number' : ["number", "date", "time"].includes(field.field_type) ? field.field_type : "text";
    return `<div class="cx-field">${label}<input class="cx-input" type="${type}" ${attrs} value="${esc(value ?? "")}" placeholder="${esc(field.placeholder || "")}"></div>`;
  }

  async function renderDoctor() {
    if (!window.ClinicsDoctorWorkspace) {
      root.innerHTML = `<div class="cx-empty">تعذر تحميل مساحة الطبيب</div>`;
      return;
    }
    await window.ClinicsDoctorWorkspace.render({
      root,
      visitId,
      state,
      api,
      esc,
      money,
      showNotice,
      openModal,
      printClinicDoc,
      badge,
      specialtyFieldHtml,
      promptNewPatient,
      render: () => render(),
    });
  }

  async function renderBilling() {
    if (window.ClinicsFinance) {
      await window.ClinicsFinance.renderBilling(state, root, { api, esc, money, showNotice, openModal });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة الفواتير</div>`;
  }

  async function renderDoctors() {
    root.innerHTML = `
      <section class="cx-doc-head">
        <div><h1>الأطباء</h1><p>إدارة الأطباء والجداول والخدمات والاستحقاقات والارتباط بالموارد البشرية</p></div>
        <button class="cx-btn cx-btn--primary" id="btnAdd"><i class="fa fa-plus"></i> إضافة طبيب</button>
      </section>
      <div class="cx-doc-search"><i class="fa fa-magnifying-glass"></i><input id="docSearch" placeholder="ابحث باسم الطبيب، الهاتف، التخصص أو الرقم الوظيفي..." autocomplete="off"></div>
      <div class="cx-doc-filters" id="docFilters">
        <select id="docSpecialty"><option value="">كل التخصصات</option></select>
        <select id="docStatus"><option value="">كل الحالات التشغيلية</option><option value="available">متاح</option><option value="with_patient">مع مريض</option><option value="off_duty">خارج الدوام</option><option value="unavailable">غير متواجد</option><option value="disabled">غير مفعل</option></select>
        <select id="docBranch"><option value="">كل الفروع</option></select>
        <select id="docAvailability"><option value="">التوفر</option><option value="today">متاح اليوم</option></select>
        <select id="docEmployment"><option value="">الحالة الوظيفية</option><option value="active">فعال</option><option value="on_leave">في إجازة</option><option value="suspended">موقوف</option><option value="terminated">منتهي الخدمة</option><option value="probation">تحت التجربة</option><option value="unlinked">غير مرتبط</option></select>
        <select id="docExtra"><option value="">فلاتر إضافية</option><option value="with_patient">مع مريض الآن</option><option value="waiting">لديه مرضى انتظار</option><option value="appointments">لديه مواعيد اليوم</option><option value="on_leave">في إجازة HR</option><option value="off_duty">خارج الدوام</option><option value="disabled">غير مفعل</option><option value="unlinked">لا يوجد Employee Record مرتبط</option><option value="no_schedule">لا يوجد جدول استقبال</option></select>
      </div>
      <div class="cx-doc-kpis" id="docKpis"></div>
      <article class="cx-card cx-doc-table-card"><div class="cx-table-wrap"><table class="cx-table cx-doc-table">
        <thead><tr><th>الطبيب</th><th>التخصص</th><th>الفرع / الغرفة</th><th>دوام اليوم</th><th>مواعيد اليوم</th><th>الانتظار</th><th>الحالة التشغيلية</th><th>الحالة الوظيفية</th><th>نظام الاستحقاق</th><th>الإجراء</th></tr></thead>
        <tbody id="docRows"><tr><td colspan="10"><div class="cx-empty cx-doc-empty"><i class="fa fa-user-doctor"></i><b>جارٍ تحميل الأطباء...</b></div></td></tr></tbody>
      </table></div><div class="cx-doc-pager" id="docPager"></div></article>
      <aside class="cx-doc-drawer" id="docDrawer" aria-hidden="true"><button class="cx-doc-drawer__close" id="docDrawerClose" aria-label="إغلاق"><i class="fa fa-xmark"></i></button><div id="docDrawerBody"></div></aside>
      <div class="cx-doc-drawer-backdrop" id="docDrawerBackdrop" hidden></div>
    `;
    const filters = { q: "", specialty: "", status: "", branch_id: "", availability: "", employment_status: "", extra: "", page: 1 };
    const opClass = { available: "ok", with_patient: "info", off_duty: "muted", unavailable: "warn", on_leave: "warn", disabled: "danger" };
    const empClass = { active: "ok", probation: "info", on_leave: "warn", suspended: "danger", terminated: "muted", inactive: "muted", unlinked: "warn" };
    let timer;
    let initializedFilters = false;
    let doctorsCache = [];
    let floatingDismiss = null;
    let drawerTab = "overview";
    let drawerDoctorId = 0;

    function closeDocMenu() {
      document.querySelector(".cxi-floating-menu")?.remove();
      if (floatingDismiss) document.removeEventListener("click", floatingDismiss);
      floatingDismiss = null;
    }

    function openDocMenu(trigger, items) {
      closeDocMenu();
      const menu = document.createElement("div");
      menu.className = "cxi-floating-menu";
      menu.innerHTML = items
        .map((item) => `<button type="button" data-act="${esc(item.id)}"><i class="fa fa-${item.icon}"></i><span>${esc(item.label)}</span></button>`)
        .join("");
      document.body.appendChild(menu);
      const rect = trigger.getBoundingClientRect();
      const w = 200;
      const h = menu.offsetHeight || 180;
      menu.style.top = `${Math.min(window.innerHeight - h - 8, rect.bottom + 6)}px`;
      menu.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, rect.right - w))}px`;
      menu.querySelectorAll("[data-act]").forEach((btn) => {
        btn.onclick = () => {
          closeDocMenu();
          items.find((x) => x.id === btn.dataset.act)?.onClick?.();
        };
      });
      window.setTimeout(() => {
        floatingDismiss = (event) => {
          if (!menu.contains(event.target) && !trigger.contains(event.target)) closeDocMenu();
        };
        document.addEventListener("click", floatingDismiss);
      }, 0);
    }

    function readCommission() {
      const raw = document.getElementById("d_commission")?.value;
      if (raw === "" || raw == null) return 0;
      const value = Number(raw);
      if (Number.isNaN(value)) throw new Error("نسبة العمولة غير صالحة");
      if (value < 0 || value > 100) throw new Error("نسبة العمولة يجب أن تكون بين 0 و 100");
      return value;
    }

    function doctorFormHtml(doctor, employeesHtml) {
      const isEdit = Boolean(doctor);
      const specialties = state.bootstrap?.specialties || [];
      const selected = new Set((doctor?.specialty_ids || []).map(String));
      return `
        <div class="cx-form-section"><h4>1. المعلومات الطبية</h4>
          <div class="cx-field"><label>الاسم *</label><input class="cx-input" id="d_name" value="${esc(doctor?.full_name || "")}" required></div>
          <div class="cx-field-row"><div class="cx-field"><label>المسمى العلمي</label><input class="cx-input" id="d_title" value="${esc(doctor?.scientific_title || "")}"></div><div class="cx-field"><label>رابط الصورة</label><input class="cx-input" id="d_photo" dir="ltr" value="${esc(doctor?.photo_url || "")}"></div></div>
          <div class="cx-field"><label>الاختصاص الرئيسي *</label><select class="cx-select" id="d_primary_spec"><option value="">اختر الاختصاص</option>${specialties.filter((s) => s.is_active).map((s) => `<option value="${s.id}" ${String(doctor?.primary_specialty_id || "") === String(s.id) ? "selected" : ""}>${esc(s.name_ar)}</option>`).join("")}</select></div>
          <div class="cx-field"><label>اختصاصات إضافية</label><div style="display:flex;gap:12px;flex-wrap:wrap">${specialties.filter((s) => s.is_active).map((s) => `<label><input type="checkbox" data-doctor-specialty="${s.id}" ${selected.has(String(s.id)) && String(doctor?.primary_specialty_id) !== String(s.id) ? "checked" : ""}> ${esc(s.name_ar)}</label>`).join("") || '<a href="/clinics/specialties">أضف الاختصاصات أولاً</a>'}</div></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>الهاتف</label><input class="cx-input" id="d_phone" dir="ltr" placeholder="07xxxxxxxxx" value="${esc(doctor?.phone || "")}"></div>
            <div class="cx-field"><label>رقم الترخيص</label><input class="cx-input" id="d_license" value="${esc(doctor?.license_number || "")}"></div>
          </div>
          <div class="cx-field-row">
            <div class="cx-field"><label>نسبة العمولة % (Legacy)</label><input class="cx-input" id="d_commission" type="number" min="0" max="100" step="0.01" value="${esc(String(doctor?.commission_pct ?? 0))}"><small class="cx-form-note">قيمة بين 0 و 100 فقط</small></div>
            ${isEdit ? `<div class="cx-field"><label>الحالة</label><select class="cx-select" id="d_active"><option value="1" ${doctor.active !== false ? "selected" : ""}>نشط</option><option value="0" ${doctor.active === false ? "selected" : ""}>غير مفعل</option></select></div>` : `<div class="cx-field"></div>`}
          </div>
        </div>
        ${isEdit ? "" : `<div class="cx-form-section"><h4>2. الربط مع الموارد البشرية</h4>
          <div class="cx-field"><label>موظف HR موجود (اختياري)</label><select class="cx-select" id="d_employee"><option value="">بدون ربط الآن</option>${employeesHtml}</select></div>
          <p class="cx-form-note">لإنشاء موظف جديد استخدم مسار إنشاء الموظف في HR ثم اربطه هنا. لا يطلب هذا النموذج راتباً أو إجازة.</p>
          <a class="cx-btn cx-btn--sm" href="/hr/employees">فتح إدارة الموظفين</a>
        </div>`}`;
    }

    async function setDoctorActive(doctorId, active) {
      const label = active ? "تفعيل" : "تعطيل";
      if (!window.confirm(`${label} هذا الطبيب؟`)) return;
      await api(`/clinics/api/doctors/${doctorId}`, {
        method: "PATCH",
        body: JSON.stringify({ active }),
      });
      showNotice(active ? "تم تفعيل الطبيب" : "تم تعطيل الطبيب", false);
      await loadDoctors();
      if (drawerDoctorId === doctorId) await openDoctor(doctorId);
    }

    async function editDoctor(doctorId) {
      let doctor = doctorsCache.find((row) => row.id === doctorId);
      if (!doctor) {
        const rows = await api("/clinics/api/doctors");
        doctor = (rows || []).find((row) => row.id === doctorId);
      } else {
        const detail = (await api("/clinics/api/doctors")).find((row) => row.id === doctorId);
        if (detail) doctor = { ...doctor, ...detail };
      }
      if (!doctor) throw new Error("الطبيب غير موجود");
      openModal(
        "تعديل طبيب",
        doctorFormHtml(doctor, ""),
        async () => {
          await api(`/clinics/api/doctors/${doctorId}`, {
            method: "PATCH",
            body: JSON.stringify({
              full_name: document.getElementById("d_name").value,
              primary_specialty_id: document.getElementById("d_primary_spec").value,
              specialty_ids: [document.getElementById("d_primary_spec").value, ...Array.from(document.querySelectorAll("[data-doctor-specialty]:checked")).map((el) => el.dataset.doctorSpecialty)].filter(Boolean),
              scientific_title: document.getElementById("d_title").value,
              photo_url: document.getElementById("d_photo").value,
              phone: document.getElementById("d_phone").value,
              license_number: document.getElementById("d_license").value,
              commission_pct: readCommission(),
              active: document.getElementById("d_active").value === "1",
            }),
          });
        },
        { successMessage: "تم تحديث بيانات الطبيب" }
      );
    }

    async function loadDoctors() {
      const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== ""));
      const data = await api(`/clinics/api/doctors/center?${query}`);
      doctorsCache = data.items || [];
      if (!initializedFilters) {
        document.getElementById("docSpecialty").innerHTML += (data.filters.specialties || []).map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
        document.getElementById("docBranch").innerHTML += (data.filters.branches || []).map((value) => `<option value="${value.id}">${esc(value.name)}</option>`).join("");
        initializedFilters = true;
      }
      const cards = [
        ["إجمالي الأطباء", data.kpis.total, "user-doctor"], ["متاحون اليوم", data.kpis.available, "circle-check"],
        ["مع مريض الآن", data.kpis.with_patient, "stethoscope"], ["في إجازة", data.kpis.on_leave, "umbrella-beach"],
        ["مواعيد اليوم", data.kpis.appointments, "calendar-check"], ["زيارات مكتملة اليوم", data.kpis.completed, "clipboard-check"],
      ];
      document.getElementById("docKpis").innerHTML = cards.map((item) => `<div><i class="fa fa-${item[2]}"></i><span>${esc(item[0])}</span><strong>${item[1]}</strong></div>`).join("");
      document.getElementById("docRows").innerHTML = (data.items || []).map((d) => `
        <tr data-doctor="${d.id}">
          <td><div class="cx-doc-person"><span class="cx-doc-avatar">${esc((d.full_name || "ط").replace(/^د\.?\s*/, "").slice(0, 1))}</span><div><strong>${esc(d.full_name)}</strong><small>${esc(d.doctor_code)}${d.employee_code ? ` · ${esc(d.employee_code)}` : ""}</small></div></div></td>
          <td>${esc(d.specialty || "—")}</td><td><strong>${esc(d.branch_name)}</strong><small>${esc(d.room_name || "—")}</small></td>
          <td class="cx-doc-schedule">${esc(d.today_schedule)}</td><td>${d.appointment_count} مواعيد</td><td>${d.waiting_count} انتظار</td>
          <td><span class="cx-doc-status cx-doc-status--${opClass[d.operational_status] || "muted"}">${esc(d.operational_status_label)}</span></td>
          <td><span class="cx-doc-status cx-doc-status--${empClass[d.employment_status] || "muted"}">${esc(d.employment_status_label)}</span></td>
          <td>${esc(d.compensation_model)}<small>${Number(d.commission_pct || 0) > 0 ? `${d.commission_pct}%` : ""}</small></td>
          <td class="cx-doc-actions-cell">
            <button type="button" class="cx-btn cx-btn--sm" data-open-doctor="${d.id}">فتح</button>
            <button type="button" class="cxi-menu-trigger" data-menu="${d.id}" title="الإجراءات" aria-label="إجراءات ${esc(d.full_name)}"><i class="fa fa-ellipsis"></i></button>
          </td>
        </tr>`).join("") || `<tr><td colspan="10"><div class="cx-empty cx-doc-empty"><i class="fa fa-user-doctor"></i><b>لا توجد نتائج مطابقة</b><span>جرّب تغيير البحث أو الفلاتر، أو أضف طبيباً جديداً.</span></div></td></tr>`;
      document.getElementById("docPager").innerHTML = `<span>${data.total} طبيب</span><div><button class="cx-btn cx-btn--sm" id="docPrev" ${data.page <= 1 ? "disabled" : ""}>السابق</button><b>${data.page} / ${data.pages}</b><button class="cx-btn cx-btn--sm" id="docNext" ${data.page >= data.pages ? "disabled" : ""}>التالي</button></div>`;
      document.getElementById("docPrev").onclick = () => { filters.page -= 1; loadDoctors(); };
      document.getElementById("docNext").onclick = () => { filters.page += 1; loadDoctors(); };
      document.querySelectorAll("[data-open-doctor]").forEach((button) => {
        button.onclick = (event) => {
          event.stopPropagation();
          openDoctor(Number(button.dataset.openDoctor));
        };
      });
      document.querySelectorAll("[data-menu]").forEach((button) => {
        button.onclick = (event) => {
          event.stopPropagation();
          const doctorId = Number(button.dataset.menu);
          const row = doctorsCache.find((item) => item.id === doctorId);
          const active = row?.active !== false;
          openDocMenu(button, [
            { id: "open", icon: "folder-open", label: "فتح الملف", onClick: () => openDoctor(doctorId) },
            { id: "edit", icon: "pen", label: "تعديل", onClick: () => editDoctor(doctorId).catch((err) => showNotice(err.message || String(err))) },
            {
              id: "toggle",
              icon: active ? "ban" : "circle-check",
              label: active ? "تعطيل" : "تفعيل",
              onClick: () => setDoctorActive(doctorId, !active).catch((err) => showNotice(err.message || String(err))),
            },
          ]);
        };
      });
      document.querySelectorAll("#docRows tr[data-doctor]").forEach((row) => {
        row.onclick = (event) => {
          if (event.target.closest("button, a, .cxi-menu-trigger")) return;
          openDoctor(Number(row.dataset.doctor));
        };
      });
    }

    function renderDrawerTab(tab, data) {
      const d = data.doctor;
      const hr = data.hr;
      const today = data.today;
      const perf = data.performance || {};
      const finance = data.clinical_finance || {};
      const attendanceRows = data.attendance || [];
      const leaveRows = data.leaves || [];
      const commission = d.commission_pct ?? finance.legacy_commission_pct ?? 0;
      const attendanceToday = hr && hr.today_attendance
        ? `${esc(hr.today_attendance.status_label)} ${esc(window.FinoraTime.clock(hr.today_attendance.check_in || ""))}`
        : "لا يوجد تسجيل";

      if (tab === "finance") {
        const settlements = finance.settlements || [];
        return `
          <section class="cx-doc-drawer__section"><h3>المالية السريرية</h3>
            <div class="cx-doc-meta">
              <span><b>نظام الاستحقاق</b>${esc(d.compensation_model || "—")}</span>
              <span><b>نسبة العمولة (Legacy)</b>${commission}%</span>
              <span><b>إيراد الشهر</b>${money(perf.service_revenue)}</span>
              <span><b>زيارات مكتملة</b>${perf.completed_visits || 0}</span>
            </div>
          </section>
          <section class="cx-doc-drawer__section"><h3>أداء الشهر</h3>
            <div class="cx-doc-summary">
              <div><span>المواعيد</span><b>${perf.appointments || 0}</b></div>
              <div><span>الزيارات</span><b>${perf.completed_visits || 0}</b></div>
              <div><span>No Show</span><b>${perf.no_show || 0}</b></div>
              <div><span>الملغاة</span><b>${perf.cancelled || 0}</b></div>
            </div>
          </section>
          <section class="cx-doc-drawer__section"><div class="cx-card__head"><h3>التسويات</h3><a href="${esc(data.links.settlements)}">عرض الكل</a></div>
            ${settlements.length ? `<div class="cx-table-wrap"><table class="cx-table cx-doc-mini-table"><thead><tr><th>الفترة</th><th>الإيراد</th><th>الحصة</th><th>المتبقي</th><th>الحالة</th></tr></thead><tbody>
              ${settlements.map((s) => `<tr><td>${esc(s.period_from)} → ${esc(s.period_to)}</td><td class="cx-money">${money(s.gross_revenue)}</td><td class="cx-money">${money(s.doctor_share)}</td><td class="cx-money">${money(s.balance)}</td><td>${esc(s.status)}</td></tr>`).join("")}
            </tbody></table></div>` : `<div class="cx-empty cx-doc-empty"><i class="fa fa-file-invoice-dollar"></i><b>لا توجد تسويات</b><span>ستظهر هنا تسويات الطبيب عند إنشائها.</span></div>`}
          </section>`;
      }

      if (tab === "attendance") {
        if (!hr) {
          return `<section class="cx-doc-drawer__section"><div class="cx-doc-unlinked"><i class="fa fa-link-slash"></i><p>اربط الطبيب بموظف HR لعرض الحضور والإجازات.</p><button class="cx-btn cx-btn--sm" id="docLinkEmployee">ربط بموظف HR</button></div></section>`;
        }
        return `
          <section class="cx-doc-drawer__section"><div class="cx-card__head"><h3>الحضور</h3><a href="${esc(data.links.hr_attendance)}">فتح الحضور</a></div>
            ${attendanceRows.length ? `<div class="cx-table-wrap"><table class="cx-table cx-doc-mini-table"><thead><tr><th>التاريخ</th><th>دخول</th><th>خروج</th><th>الحالة</th></tr></thead><tbody>
              ${attendanceRows.map((row) => `<tr><td>${esc(row.date)}</td><td dir="ltr">${esc(window.FinoraTime.clock(row.check_in || "—"))}</td><td dir="ltr">${esc(window.FinoraTime.clock(row.check_out || "—"))}</td><td>${esc(row.status_label || row.status)}</td></tr>`).join("")}
            </tbody></table></div>` : `<div class="cx-empty cx-doc-empty"><i class="fa fa-clock"></i><b>لا سجلات حضور</b></div>`}
          </section>
          <section class="cx-doc-drawer__section"><div class="cx-card__head"><h3>الإجازات</h3><a href="${esc(data.links.hr_leave)}">فتح الإجازات</a></div>
            <div class="cx-doc-meta"><span><b>الرصيد</b>${hr.leave_balance} يوم</span><span><b>المستخدم</b>${hr.leave_used} يوم</span></div>
            ${leaveRows.length ? `<div class="cx-table-wrap" style="margin-top:10px"><table class="cx-table cx-doc-mini-table"><thead><tr><th>النوع</th><th>من</th><th>إلى</th><th>أيام</th><th>الحالة</th></tr></thead><tbody>
              ${leaveRows.map((row) => `<tr><td>${esc(row.type)}</td><td>${esc(row.start_date)}</td><td>${esc(row.end_date)}</td><td>${row.days}</td><td>${esc(row.status)}</td></tr>`).join("")}
            </tbody></table></div>` : `<div class="cx-empty cx-doc-empty"><i class="fa fa-umbrella-beach"></i><b>لا طلبات إجازة</b></div>`}
          </section>`;
      }

      return `
        <div class="cx-doc-meta">
          <span><b>التخصص</b>${esc(d.specialty || "—")}</span>
          <span><b>الهاتف</b>${esc(d.phone || "—")}</span>
          <span><b>الفرع / الغرفة</b>${esc(d.branch_name || "—")} / ${esc(d.room_name || "—")}</span>
          <span><b>الترخيص</b>${esc(d.license_number || "—")}</span>
          <span><b>نظام الاستحقاق</b>${esc(d.compensation_model || "—")}</span>
          <span><b>نسبة العمولة</b>${commission}%</span>
        </div>
        <section class="cx-doc-drawer__section"><h3>ملخص اليوم</h3>
          <div class="cx-doc-summary">
            <div><span>الدوام</span><b>${esc(d.today_schedule)}</b></div>
            <div><span>المواعيد</span><b>${d.appointment_count}</b></div>
            <div><span>المكتملة</span><b>${d.completed_count}</b></div>
            <div><span>المنتظرون</span><b>${d.waiting_count}</b></div>
          </div>
          <p class="cx-doc-current"><b>المريض الحالي:</b> ${esc(today.current_patient || "لا يوجد")}${today.started_at ? ` · بدأ ${esc(window.FinoraTime.format(today.started_at, { hour: "2-digit", minute: "2-digit" }))}` : ""}<br><b>التالي:</b> ${esc(today.next_patient || "لا يوجد")}</p>
        </section>
        <section class="cx-doc-drawer__section">
          <div class="cx-card__head"><h3>الموارد البشرية</h3>${hr ? `<a href="${esc(data.links.hr_employee)}">فتح ملف HR</a>` : ""}</div>
          ${hr ? `<div class="cx-doc-meta">
            <span><b>نوع التوظيف</b>${esc(hr.employment_type_label)}</span>
            <span><b>الحالة الوظيفية</b>${esc(hr.employment_status_label)}</span>
            <span><b>الراتب الأساسي</b>${hr.salary_visible ? money(hr.salary) : "حسب الصلاحية"}</span>
            <span><b>رصيد الإجازات</b>${hr.leave_balance} يوم</span>
            <span><b>الحضور اليوم</b>${attendanceToday}</span>
            <span><b>راتب الشهر</b>${hr.month_salary_status === "paid" ? "مسدد ✓" : "غير مسدد"}</span>
          </div>
          <div class="cx-doc-drawer-actions"><button type="button" class="cx-btn cx-btn--sm" id="docUnlinkEmployee">فك ربط HR</button></div>`
          : `<div class="cx-doc-unlinked"><i class="fa fa-link-slash"></i><p>لا يوجد Employee Record مرتبط.</p><button class="cx-btn cx-btn--sm" id="docLinkEmployee">ربط بموظف HR</button></div>`}
        </section>
        <section class="cx-doc-drawer__section"><h3>أداء الشهر</h3>
          <div class="cx-doc-summary">
            <div><span>المواعيد</span><b>${perf.appointments || 0}</b></div>
            <div><span>الزيارات</span><b>${perf.completed_visits || 0}</b></div>
            <div><span>No Show</span><b>${perf.no_show || 0}</b></div>
            <div><span>الإيراد</span><b>${money(perf.service_revenue)}</b></div>
          </div>
        </section>`;
    }

    function bindDrawerActions(doctorId, data) {
      document.getElementById("docEditDoctor")?.addEventListener("click", () => {
        editDoctor(doctorId).catch((err) => showNotice(err.message || String(err)));
      });
      document.getElementById("docToggleActive")?.addEventListener("click", () => {
        const active = data.doctor.active !== false;
        setDoctorActive(doctorId, !active).catch((err) => showNotice(err.message || String(err)));
      });
      document.getElementById("docLinkEmployee")?.addEventListener("click", () => linkEmployee(doctorId));
      document.getElementById("docUnlinkEmployee")?.addEventListener("click", () => unlinkEmployee(doctorId));
      document.querySelectorAll("[data-doc-tab]").forEach((btn) => {
        btn.onclick = () => {
          drawerTab = btn.dataset.docTab;
          paintDrawer(data);
        };
      });
    }

    function paintDrawer(data) {
      const body = document.getElementById("docDrawerBody");
      const d = data.doctor;
      const hr = data.hr;
      const active = d.active !== false;
      body.innerHTML = `
        <header class="cx-doc-drawer__head">
          <span class="cx-doc-avatar cx-doc-avatar--lg">${esc((d.full_name || "ط").replace(/^د\.?\s*/, "").slice(0, 1))}</span>
          <div>
            <h2>${esc(d.full_name)}</h2>
            <p>${esc(d.doctor_code)}${d.employee_code ? ` · ${esc(d.employee_code)}` : ""}</p>
            <span class="cx-doc-status cx-doc-status--${opClass[d.operational_status] || "muted"}">${esc(d.operational_status_label)}</span>
          </div>
        </header>
        <div class="cx-doc-drawer-actions">
          <button type="button" class="cx-btn cx-btn--sm cx-btn--primary" id="docEditDoctor"><i class="fa fa-pen"></i> تعديل</button>
          <button type="button" class="cx-btn cx-btn--sm" id="docToggleActive"><i class="fa fa-${active ? "ban" : "circle-check"}"></i> ${active ? "تعطيل" : "تفعيل"}</button>
        </div>
        <nav class="cx-doc-profile-tabs" aria-label="أقسام ملف الطبيب">
          <button type="button" class="${drawerTab === "overview" ? "is-active" : ""}" data-doc-tab="overview">نظرة عامة</button>
          <button type="button" class="${drawerTab === "finance" ? "is-active" : ""}" data-doc-tab="finance">المالية السريرية</button>
          <button type="button" class="${drawerTab === "attendance" ? "is-active" : ""}" data-doc-tab="attendance">الحضور والإجازات</button>
          <a href="${esc(data.links.schedule)}">الجدول الطبي</a>
          <a href="${esc(data.links.services)}">الخدمات</a>
          <a href="/clinics/appointments?doctor_id=${d.id}">المواعيد</a>
          <a href="/clinics/visits?doctor_id=${d.id}">الزيارات</a>
          <a href="${esc(data.links.settlements)}">الاستحقاقات</a>
          ${hr ? `<a href="${esc(data.links.hr_employee)}">HR</a><a href="${esc(data.links.hr_payroll)}">الرواتب</a>` : ""}
        </nav>
        <div class="cx-doc-drawer__panels">${renderDrawerTab(drawerTab, data)}</div>
        <nav class="cx-doc-links">
          <a href="${esc(data.links.schedule)}">جدول الطبيب</a>
          <a href="${esc(data.links.services)}">الخدمات</a>
          <a href="${esc(data.links.settlements)}">الاستحقاقات</a>
          ${hr ? `<a href="${esc(data.links.hr_employee)}">HR</a><a href="${esc(data.links.hr_payroll)}">الرواتب</a>` : ""}
        </nav>`;
      bindDrawerActions(d.id, data);
    }

    async function openDoctor(doctorId) {
      const drawer = document.getElementById("docDrawer");
      const backdrop = document.getElementById("docDrawerBackdrop");
      const body = document.getElementById("docDrawerBody");
      drawerDoctorId = doctorId;
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      backdrop.hidden = false;
      body.innerHTML = `<div class="cx-empty cx-doc-empty"><i class="fa fa-spinner fa-spin"></i><b>جارٍ تحميل الملف...</b></div>`;
      try {
        const data = await api(`/clinics/api/doctors/${doctorId}/workspace`);
        paintDrawer(data);
      } catch (error) {
        body.innerHTML = `<div class="cx-empty cx-doc-empty"><i class="fa fa-triangle-exclamation"></i><b>${esc(error.message)}</b></div>`;
      }
    }

    async function linkEmployee(doctorId) {
      const employees = await api("/clinics/api/doctors/employees");
      openModal(
        "ربط الطبيب بموظف HR",
        `<div class="cx-field"><label>سجل الموظف</label><select class="cx-select" id="doctorEmployeeLink"><option value="">اختر الموظف</option>${employees.filter((e) => !e.already_linked).map((e) => `<option value="${e.id}">${esc(e.name)} · ${esc(e.employee_code)}</option>`).join("")}</select></div><p class="cx-form-note">الراتب والإجازات والحضور ستُقرأ من ملف HR نفسه ولن تُنسخ إلى ملف الطبيب.</p>`,
        async () => {
          const employeeId = Number(document.getElementById("doctorEmployeeLink").value || 0);
          if (!employeeId) throw new Error("اختر الموظف");
          await api(`/clinics/api/doctors/${doctorId}/employee-link`, {
            method: "PATCH",
            body: JSON.stringify({ employee_id: employeeId }),
          });
          await loadDoctors();
          await openDoctor(doctorId);
        },
        { successMessage: "تم ربط ملف الطبيب بالموظف", skipRender: true }
      );
    }

    async function unlinkEmployee(doctorId) {
      if (!window.confirm("فك ربط الطبيب عن سجل الموظف؟ لن يُحذف سجل HR.")) return;
      await api(`/clinics/api/doctors/${doctorId}/employee-link`, {
        method: "PATCH",
        body: JSON.stringify({ employee_id: null }),
      });
      showNotice("تم فك ربط الموظف", false);
      await loadDoctors();
      await openDoctor(doctorId);
    }

    const closeDrawer = () => {
      closeDocMenu();
      document.getElementById("docDrawer").classList.remove("open");
      document.getElementById("docDrawer").setAttribute("aria-hidden", "true");
      document.getElementById("docDrawerBackdrop").hidden = true;
      drawerDoctorId = 0;
    };
    document.getElementById("docDrawerClose").onclick = closeDrawer;
    document.getElementById("docDrawerBackdrop").onclick = closeDrawer;
    document.getElementById("docSearch").oninput = (event) => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        filters.q = event.target.value.trim();
        filters.page = 1;
        loadDoctors();
      }, 320);
    };
    [["docSpecialty", "specialty"], ["docStatus", "status"], ["docBranch", "branch_id"], ["docAvailability", "availability"], ["docEmployment", "employment_status"], ["docExtra", "extra"]].forEach(([id, key]) => {
      document.getElementById(id).onchange = (event) => {
        filters[key] = event.target.value;
        filters.page = 1;
        loadDoctors();
      };
    });
    document.getElementById("btnAdd").onclick = async () => {
      const employees = await api("/clinics/api/doctors/employees");
      const employeesHtml = employees
        .filter((e) => !e.already_linked)
        .map((e) => `<option value="${e.id}">${esc(e.name)} · ${esc(e.employee_code)}</option>`)
        .join("");
      openModal(
        "إضافة طبيب — المعلومات الطبية والربط مع HR",
        doctorFormHtml(null, employeesHtml),
        async () => {
          await api("/clinics/api/doctors", {
            method: "POST",
            body: JSON.stringify({
              full_name: document.getElementById("d_name").value,
              primary_specialty_id: document.getElementById("d_primary_spec").value,
              specialty_ids: [document.getElementById("d_primary_spec").value, ...Array.from(document.querySelectorAll("[data-doctor-specialty]:checked")).map((el) => el.dataset.doctorSpecialty)].filter(Boolean),
              scientific_title: document.getElementById("d_title").value,
              photo_url: document.getElementById("d_photo").value,
              phone: document.getElementById("d_phone").value,
              license_number: document.getElementById("d_license").value,
              commission_pct: readCommission(),
              employee_id: document.getElementById("d_employee")?.value || null,
            }),
          });
        },
        { successMessage: "تمت إضافة الطبيب" }
      );
    };
    await loadDoctors();
    const initialDoctorId = Number(root.closest(".cx-shell")?.dataset.doctorId || 0);
    if (initialDoctorId) await openDoctor(initialDoctorId);
  }

  async function renderServices() {
    if (window.ClinicsServices) {
      await window.ClinicsServices.renderServices(state, root, { api, esc, money, showNotice, openModal, render, state });
      return;
    }
    const rows = await api("/clinics/api/services");
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Service Catalog</div><h1>الخدمات</h1><p>أسعار ومدد الخدمات الطبية للعيادة.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnAdd">خدمة جديدة</button></div>
      </section>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>الخدمة</th><th>التصنيف</th><th>المدة</th><th>السعر</th></tr></thead>
        <tbody>
          ${rows
            .map(
              (s) =>
                `<tr><td>${esc(s.name)}</td><td>${esc(s.category)}</td><td>${s.duration_minutes} د</td><td class="cx-money">${money(s.price)}</td></tr>`
            )
            .join("") || `<tr><td colspan="4"><div class="cx-empty">لا خدمات بعد</div></td></tr>`}
        </tbody>
      </table></div></article>
    `;
    document.getElementById("btnAdd").onclick = () => {
      openModal(
        "خدمة جديدة",
        `
        <div class="cx-field"><label>الاسم</label><input class="cx-input" id="s_name"></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>التصنيف</label><input class="cx-input" id="s_cat"></div>
          <div class="cx-field"><label>المدة (دقيقة)</label><input class="cx-input" id="s_dur" type="number" value="15"></div>
        </div>
        <div class="cx-field"><label>السعر</label><input class="cx-input" id="s_price" type="number" value="0"></div>`,
        async () => {
          await api("/clinics/api/services", {
            method: "POST",
            body: JSON.stringify({
              name: document.getElementById("s_name").value,
              category: document.getElementById("s_cat").value,
              duration_minutes: document.getElementById("s_dur").value,
              price: document.getElementById("s_price").value,
            }),
          });
        }
      );
    };
  }

  async function renderReports() {
    if (window.ClinicsReports) {
      await window.ClinicsReports.render(state, root, { api, esc, money, showNotice, openModal });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة التقارير</div>`;
  }

  async function renderDisplay() {
    if (window.ClinicsDisplay) {
      await window.ClinicsDisplay.render(state, root, {
        api,
        esc,
        showNotice,
        bootstrap: state.bootstrap,
      });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة شاشة العرض</div>`;
  }

  async function renderInventory() {
    if (window.ClinicsInventory) {
      await window.ClinicsInventory.renderInventory(state, root, { api, esc, money, showNotice, openModal, render });
      return;
    }
    const [rows, alerts] = await Promise.all([
      api("/clinics/api/inventory"),
      api("/clinics/api/inventory/alerts"),
    ]);
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Clinic Stock</div><h1>مخزون العيادة</h1><p>مستلزمات طبية مع تنبيهات النقص والانتهاء وخصم تلقائي من الإجراءات.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnAdd">صنف جديد</button></div>
      </section>
      <div class="cx-alert-row">
        <article class="cx-kpi"><span>منخفض</span><strong>${(alerts.low_stock || []).length}</strong></article>
        <article class="cx-kpi"><span>منتهٍ</span><strong>${(alerts.expired || []).length}</strong></article>
        <article class="cx-kpi"><span>ينتهي خلال 30 يوم</span><strong>${(alerts.expiring_soon || []).length}</strong></article>
      </div>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>الصنف</th><th>SKU</th><th>الوحدة</th><th>الرصيد</th><th>الحد الأدنى</th><th></th></tr></thead>
        <tbody>
          ${rows
            .map(
              (i) => `
            <tr>
              <td>${esc(i.name)}${i.low_stock ? ' <span class="cx-badge cx-badge--waiting">منخفض</span>' : ""}</td>
              <td>${esc(i.sku)}</td><td>${esc(i.unit)}</td>
              <td>${i.current_stock}</td><td>${i.minimum_stock}</td>
              <td><button class="cx-btn cx-btn--sm" data-in="${i.id}">إدخال</button></td>
            </tr>`
            )
            .join("") || `<tr><td colspan="6"><div class="cx-empty">لا أصناف بعد</div></td></tr>`}
        </tbody>
      </table></div></article>
    `;
    document.getElementById("btnAdd").onclick = () => {
      openModal(
        "صنف مخزون",
        `
        <div class="cx-field"><label>الاسم</label><input class="cx-input" id="i_name"></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>SKU</label><input class="cx-input" id="i_sku"></div>
          <div class="cx-field"><label>الوحدة</label><input class="cx-input" id="i_unit" value="piece"></div>
        </div>
        <div class="cx-field-row">
          <div class="cx-field"><label>رصيد افتتاحي</label><input class="cx-input" id="i_stock" type="number" value="0"></div>
          <div class="cx-field"><label>الحد الأدنى</label><input class="cx-input" id="i_min" type="number" value="0"></div>
        </div>
        <label style="display:flex;gap:8px;align-items:center;font-weight:700"><input type="checkbox" id="i_batch"> تتبع دفعات / انتهاء</label>`,
        async () => {
          await api("/clinics/api/inventory", {
            method: "POST",
            body: JSON.stringify({
              name: document.getElementById("i_name").value,
              sku: document.getElementById("i_sku").value,
              unit: document.getElementById("i_unit").value,
              current_stock: document.getElementById("i_stock").value,
              minimum_stock: document.getElementById("i_min").value,
              batch_tracking: document.getElementById("i_batch").checked,
              expiry_tracking: document.getElementById("i_batch").checked,
            }),
          });
        }
      );
    };
    root.querySelectorAll("[data-in]").forEach((btn) => {
      btn.onclick = () => {
        openModal(
          "إدخال مخزون",
          `
          <div class="cx-field"><label>الكمية</label><input class="cx-input" id="q" type="number" value="1"></div>
          <div class="cx-field"><label>رقم الدفعة</label><input class="cx-input" id="b"></div>
          <div class="cx-field"><label>تاريخ الانتهاء</label><input class="cx-input" type="date" id="e"></div>`,
          async () => {
            await api(`/clinics/api/inventory/${btn.dataset.in}/stock-in`, {
              method: "POST",
              body: JSON.stringify({
                quantity: document.getElementById("q").value,
                batch_number: document.getElementById("b").value,
                expiry_date: document.getElementById("e").value,
              }),
            });
          }
        );
      };
    });
  }

  async function renderLabs() {
    const [orders, tests] = await Promise.all([
      api("/clinics/api/lab-orders"),
      api("/clinics/api/lab-tests"),
    ]);
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Laboratory</div><h1>التحاليل</h1><p>طلب نتائج وتسجيل القيم مع علامات الشذوذ.</p></div>
        <div class="cx-actions">
          <button class="cx-btn" id="btnTest">تحليل جديد</button>
          <button class="cx-btn cx-btn--primary" id="btnOrder">طلب تحاليل</button>
        </div>
      </section>
      <article class="cx-card">
        <div class="cx-card__head"><div><h2>الطلبات</h2><p>${orders.length} طلب</p></div></div>
        ${(orders || [])
          .map(
            (o) => `
          <div class="cx-feed__item" style="margin-bottom:10px">
            <strong>${esc(o.patient_name)}</strong> · ${esc(o.status)} · ${esc(o.priority)}
            <small>${esc(window.FinoraTime.dateTime((o.ordered_at || "")))}</small>
            ${(o.items || [])
              .map(
                (it) => `
              <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                <span>${esc(it.test_name)} ${it.value ? "→ " + esc(it.value) + " " + esc(it.unit) : ""} ${badge(it.status === "completed" ? "completed" : "pending")}</span>
                ${it.status !== "completed" ? `<button class="cx-btn cx-btn--sm" data-result="${it.id}">تسجيل نتيجة</button>` : ""}
              </div>`
              )
              .join("")}
          </div>`
          )
          .join("") || '<div class="cx-empty">لا طلبات</div>'}
      </article>
    `;
    document.getElementById("btnTest").onclick = () => {
      openModal(
        "تحليل مخبري",
        `
        <div class="cx-field"><label>الاسم</label><input class="cx-input" id="t_name"></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>الكود</label><input class="cx-input" id="t_code"></div>
          <div class="cx-field"><label>السعر</label><input class="cx-input" id="t_price" type="number" value="0"></div>
        </div>`,
        async () => {
          await api("/clinics/api/lab-tests", {
            method: "POST",
            body: JSON.stringify({
              name: document.getElementById("t_name").value,
              code: document.getElementById("t_code").value,
              price: document.getElementById("t_price").value,
            }),
          });
        }
      );
    };
    document.getElementById("btnOrder").onclick = () => {
      openModal(
        "طلب تحاليل",
        `
        <div class="cx-field"><label>بحث مريض</label><input class="cx-input" id="f_patient_q"></div>
        <div class="cx-field"><label>المريض</label><select class="cx-select" id="f_patient_id"><option value="">…</option></select></div>
        <div class="cx-field"><label>التحاليل</label>
          <div style="display:grid;gap:6px;max-height:180px;overflow:auto">
            ${tests.map((t) => `<label style="display:flex;gap:8px;align-items:center"><input type="checkbox" value="${t.id}" class="lab-test-cb"> ${esc(t.name)}</label>`).join("") || "أضف تحليلاً أولاً"}
          </div>
        </div>`,
        async () => {
          const test_ids = [...document.querySelectorAll(".lab-test-cb:checked")].map((el) => Number(el.value));
          await api("/clinics/api/lab-orders", {
            method: "POST",
            body: JSON.stringify({
              patient_id: Number(document.getElementById("f_patient_id").value),
              test_ids,
            }),
          });
        }
      );
      bindPatientSearch();
    };
    root.querySelectorAll("[data-result]").forEach((btn) => {
      btn.onclick = () => {
        openModal(
          "نتيجة تحليل",
          `
          <div class="cx-field"><label>القيمة</label><input class="cx-input" id="r_val"></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>الوحدة</label><input class="cx-input" id="r_unit"></div>
            <div class="cx-field"><label>المرجع</label><input class="cx-input" id="r_ref"></div>
          </div>
          <div class="cx-field"><label>العلم</label>
            <select class="cx-select" id="r_flag">
              <option value="normal">طبيعي</option>
              <option value="high">مرتفع</option>
              <option value="low">منخفض</option>
              <option value="critical">حرج</option>
            </select>
          </div>`,
          async () => {
            await api(`/clinics/api/lab-order-items/${btn.dataset.result}/result`, {
              method: "POST",
              body: JSON.stringify({
                value: document.getElementById("r_val").value,
                unit: document.getElementById("r_unit").value,
                reference_range: document.getElementById("r_ref").value,
                abnormal_flag: document.getElementById("r_flag").value,
              }),
            });
          }
        );
      };
    });
  }

  async function renderRadiology() {
    const orders = await api("/clinics/api/radiology-orders");
    const modalities = [
      ["xray", "أشعة سينية"],
      ["ultrasound", "سونار"],
      ["ct", "مقطعية"],
      ["mri", "رنين"],
      ["mammography", "ماموغرام"],
      ["other", "أخرى"],
    ];
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Imaging</div><h1>الأشعة</h1><p>طلبات التصوير والتقارير والانطباع السريري.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnOrder">طلب أشعة</button></div>
      </section>
      <article class="cx-card">
        ${(orders || [])
          .map(
            (o) => `
          <div class="cx-feed__item" style="margin-bottom:10px">
            <strong>${esc(o.patient_name)}</strong> · ${esc(o.modality_label)} · ${badge(o.status === "completed" ? "completed" : "pending")}
            <small>${esc(o.body_part || "")} · ${money(o.price)}</small>
            ${o.impression ? `<div style="margin-top:6px">${esc(o.impression)}</div>` : ""}
            ${o.status !== "completed" ? `<div style="margin-top:8px"><button class="cx-btn cx-btn--sm" data-rad="${o.id}">تسجيل تقرير</button></div>` : ""}
          </div>`
          )
          .join("") || '<div class="cx-empty">لا طلبات أشعة</div>'}
      </article>
    `;
    document.getElementById("btnOrder").onclick = () => {
      openModal(
        "طلب أشعة",
        `
        <div class="cx-field"><label>بحث مريض</label><input class="cx-input" id="f_patient_q"></div>
        <div class="cx-field"><label>المريض</label><select class="cx-select" id="f_patient_id"></select></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>النوع</label>
            <select class="cx-select" id="r_mod">${modalities.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
          </div>
          <div class="cx-field"><label>السعر</label><input class="cx-input" id="r_price" type="number" value="0"></div>
        </div>
        <div class="cx-field"><label>المنطقة</label><input class="cx-input" id="r_part"></div>`,
        async () => {
          await api("/clinics/api/radiology-orders", {
            method: "POST",
            body: JSON.stringify({
              patient_id: Number(document.getElementById("f_patient_id").value),
              modality: document.getElementById("r_mod").value,
              price: document.getElementById("r_price").value,
              body_part: document.getElementById("r_part").value,
            }),
          });
        }
      );
      bindPatientSearch();
    };
    root.querySelectorAll("[data-rad]").forEach((btn) => {
      btn.onclick = () => {
        openModal(
          "تقرير أشعة",
          `
          <div class="cx-field"><label>التقرير</label><textarea class="cx-textarea" id="r_report"></textarea></div>
          <div class="cx-field"><label>الانطباع</label><textarea class="cx-textarea" id="r_imp"></textarea></div>`,
          async () => {
            await api(`/clinics/api/radiology-orders/${btn.dataset.rad}/result`, {
              method: "POST",
              body: JSON.stringify({
                report: document.getElementById("r_report").value,
                impression: document.getElementById("r_imp").value,
                status: "completed",
              }),
            });
          }
        );
      };
    });
  }

  async function renderSchedules() {
    const [schedules, timeOff, doctors] = await Promise.all([
      api("/clinics/api/schedules"),
      api("/clinics/api/time-off"),
      api("/clinics/api/doctors?active=1"),
    ]);
    const days = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"];
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Doctor Hours</div><h1>جدول استقبال المرضى والحظر التشغيلي</h1><p>هذا الجدول للحجز الطبي فقط؛ الحضور والإجازات تُدار من HR.</p></div>
        <div class="cx-actions">
          <button class="cx-btn" id="btnOff">إجازة</button>
          <button class="cx-btn cx-btn--primary" id="btnSch" data-finora-action="schedule.create">إضافة دوام</button>
        </div>
      </section>
      <section class="cx-grid cx-grid--2">
        <article class="cx-card">
          <div class="cx-card__head"><div><h2>الدوام</h2></div></div>
          <div class="cx-table-wrap"><table class="cx-table">
            <thead><tr><th>الطبيب</th><th>اليوم</th><th>من</th><th>إلى</th><th></th></tr></thead>
            <tbody>
              ${schedules
                .map(
                  (s) => `
                <tr>
                  <td>${esc(s.doctor_name)}</td><td>${esc(s.weekday_label)}</td>
                  <td>${esc(window.FinoraTime.clock(s.start_time))}</td><td>${esc(window.FinoraTime.clock(s.end_time))}</td>
                  <td><button class="cx-btn cx-btn--sm cx-btn--danger" data-del="${s.id}">حذف</button></td>
                </tr>`
                )
                .join("") || `<tr><td colspan="5"><div class="cx-empty">لا جداول</div></td></tr>`}
            </tbody>
          </table></div>
        </article>
        <article class="cx-card">
          <div class="cx-card__head"><div><h2>الحظر التشغيلي</h2><p>اجتماع، استراحة، عملية، تدريب أو وقت إداري — وليس إجازة HR.</p></div></div>
          <div class="cx-feed">
            ${timeOff
              .map(
                (t) => `
              <div class="cx-feed__item">
                <strong>${esc(t.doctor_name)}</strong>
                <small>${esc(t.from_date)} → ${esc(t.to_date)} · ${esc(t.reason || "")}</small>
              </div>`
              )
              .join("") || '<div class="cx-empty">لا يوجد حظر تشغيلي</div>'}
          </div>
        </article>
      </section>
    `;
    const doctorOptions = doctors.map((d) => `<option value="${d.id}">${esc(d.full_name)}</option>`).join("");
    document.getElementById("btnSch").onclick = () => {
      openModal(
        "دوام طبيب",
        `
        <div data-finora-section="schedule.form"><div class="cx-field"><label>الطبيب</label><select class="cx-select" id="s_doc" data-finora-field="schedule.doctor">${doctorOptions}</select></div>
        <div class="cx-field"><label>اليوم</label><select class="cx-select" id="s_day" data-finora-field="schedule.day">${days.map((d, i) => `<option value="${i}">${d}</option>`).join("")}</select></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>من</label><input class="cx-input" type="time" id="s_from" data-finora-field="schedule.start" value="09:00"></div>
          <div class="cx-field"><label>إلى</label><input class="cx-input" type="time" id="s_to" data-finora-field="schedule.end" value="13:00"></div>
        </div><div class="cx-field-row">
          <div class="cx-field"><label>بداية الاستراحة (اختياري)</label><input class="cx-input" type="time" id="s_break_from" data-finora-field="schedule.break_start"></div>
          <div class="cx-field"><label>نهاية الاستراحة (اختياري)</label><input class="cx-input" type="time" id="s_break_to" data-finora-field="schedule.break_end"></div>
        </div></div>`,
        async () => {
          await api("/clinics/api/schedules", {
            method: "POST",
            body: JSON.stringify({
              doctor_id: document.getElementById("s_doc").value,
              weekday: document.getElementById("s_day").value,
              start_time: document.getElementById("s_from").value,
              end_time: document.getElementById("s_to").value,
              break_start: document.getElementById("s_break_from").value || null,
              break_end: document.getElementById("s_break_to").value || null,
            }),
          });
        },
        { finoraAction: "schedule.save" }
      );
    };
    document.getElementById("btnOff").onclick = () => {
      openModal(
        "حظر تشغيلي للطبيب",
        `
        <div class="cx-field"><label>الطبيب</label><select class="cx-select" id="o_doc">${doctorOptions}</select></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>من</label><input class="cx-input" type="date" id="o_from" value="${esc(state.day)}"></div>
          <div class="cx-field"><label>إلى</label><input class="cx-input" type="date" id="o_to" value="${esc(state.day)}"></div>
        </div>
        <div class="cx-field"><label>السبب</label><input class="cx-input" id="o_reason"></div>`,
        async () => {
          await api("/clinics/api/time-off", {
            method: "POST",
            body: JSON.stringify({
              doctor_id: document.getElementById("o_doc").value,
              from_date: document.getElementById("o_from").value,
              to_date: document.getElementById("o_to").value,
              reason: document.getElementById("o_reason").value,
            }),
          });
        }
      );
    };
    root.querySelectorAll("[data-del]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/clinics/api/schedules/${btn.dataset.del}`, { method: "DELETE" });
          await render();
        } catch (err) {
          showNotice(err.message || String(err));
        }
      };
    });
  }

  async function renderSettlements() {
    if (window.ClinicsFinance) {
      await window.ClinicsFinance.renderSettlements(state, root, { api, esc, money, showNotice, openModal });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة التسوية</div>`;
  }

  async function renderProcedures() {
    const rows = await api("/clinics/api/procedures");
    const items = await api("/clinics/api/inventory").catch(() => []);
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Procedures</div><h1>الإجراءات الطبية</h1><p>مع وصفة استهلاك مخزون تُخصم مرة واحدة عند إكمال الزيارة.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnAdd">إجراء جديد</button></div>
      </section>
      <article class="cx-card">
        ${(rows || [])
          .map(
            (p) => `
          <div class="cx-feed__item" style="margin-bottom:8px">
            <strong>${esc(p.name)}</strong> · ${money(p.price)}
            <small>${(p.recipe || []).map((r) => `${esc(r.item_name)} × ${r.quantity}`).join(" · ") || "بدون استهلاك مخزون"}</small>
          </div>`
          )
          .join("") || '<div class="cx-empty">لا إجراءات</div>'}
      </article>
    `;
    document.getElementById("btnAdd").onclick = () => {
      openModal(
        "إجراء طبي",
        `
        <div class="cx-field"><label>الاسم</label><input class="cx-input" id="p_name"></div>
        <div class="cx-field"><label>السعر</label><input class="cx-input" id="p_price" type="number" value="0"></div>
        <div class="cx-field"><label>مستهلك من المخزون</label>
          <select class="cx-select" id="p_item">
            <option value="">— بدون —</option>
            ${items.map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("")}
          </select>
        </div>
        <div class="cx-field"><label>الكمية المستهلكة</label><input class="cx-input" id="p_qty" type="number" value="1"></div>`,
        async () => {
          const itemId = document.getElementById("p_item").value;
          const recipe = itemId
            ? [{ item_id: Number(itemId), quantity: document.getElementById("p_qty").value }]
            : [];
          await api("/clinics/api/procedures", {
            method: "POST",
            body: JSON.stringify({
              name: document.getElementById("p_name").value,
              price: document.getElementById("p_price").value,
              consumes_inventory: !!itemId,
              recipe,
            }),
          });
        }
      );
    };
  }

  async function renderRooms() {
    const rows = await api("/clinics/api/rooms?active=0");
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Rooms</div><h1>الغرف</h1><p>غرف الكشف والإجراءات.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnAdd">غرفة جديدة</button></div>
      </section>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>الاسم</th><th>النوع</th><th>الحالة</th></tr></thead>
        <tbody>
          ${rows.map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.room_type)}</td><td>${r.active ? "نشطة" : "موقوفة"}</td></tr>`).join("") || `<tr><td colspan="3"><div class="cx-empty">لا غرف</div></td></tr>`}
        </tbody>
      </table></div></article>
    `;
    document.getElementById("btnAdd").onclick = () => {
      openModal(
        "غرفة جديدة",
        `
        <div class="cx-field"><label>الاسم</label><input class="cx-input" id="r_name"></div>
        <div class="cx-field"><label>النوع</label>
          <select class="cx-select" id="r_type">
            <option value="consultation">كشف</option>
            <option value="procedure">إجراء</option>
            <option value="lab">مختبر</option>
            <option value="imaging">أشعة</option>
          </select>
        </div>`,
        async () => {
          await api("/clinics/api/rooms", {
            method: "POST",
            body: JSON.stringify({
              name: document.getElementById("r_name").value,
              room_type: document.getElementById("r_type").value,
            }),
          });
        }
      );
    };
  }

  async function renderExpenses() {
    if (window.ClinicsFinance) {
      await window.ClinicsFinance.renderExpenses(state, root, { api, esc, money, showNotice, openModal });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة المصروفات</div>`;
  }

  async function renderCash() {
    if (window.ClinicsFinance) {
      await window.ClinicsFinance.renderCash(state, root, { api, esc, money, showNotice, openModal });
      return;
    }
    root.innerHTML = `<div class="cx-empty">تعذر تحميل وحدة الصندوق</div>`;
  }

  async function renderAttachments() {
    const qPatient = state.attachPatientId || patientId || "";
    const rows = qPatient ? await api(`/clinics/api/attachments?patient_id=${encodeURIComponent(qPatient)}`) : [];
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Files</div><h1>المرفقات</h1><p>ملفات المريض: تحاليل، أشعة، هوية، موافقات.</p></div>
        <div class="cx-actions">
          <input class="cx-input" id="attPatient" type="number" placeholder="رقم المريض" value="${esc(qPatient)}">
          <button class="cx-btn" id="btnLoad">عرض</button>
          <button class="cx-btn cx-btn--primary" id="btnUp">رفع ملف</button>
        </div>
      </section>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>الملف</th><th>التصنيف</th><th>الحجم</th><th></th></tr></thead>
        <tbody>${rows.map((a)=>`<tr>
          <td>${esc(a.file_name)}</td><td>${esc(a.category)}</td><td>${a.size_bytes}</td>
          <td><a class="cx-btn cx-btn--sm" href="${esc(a.url)}">تنزيل</a></td>
        </tr>`).join("") || `<tr><td colspan="4"><div class="cx-empty">أدخل رقم المريض لعرض المرفقات</div></td></tr>`}</tbody>
      </table></div></article>`;
    document.getElementById("btnLoad").onclick = () => {
      state.attachPatientId = document.getElementById("attPatient").value;
      render();
    };
    document.getElementById("btnUp").onclick = () => {
      openModal("رفع مرفق", `
        <div class="cx-field"><label>رقم المريض</label><input class="cx-input" id="up_pid" value="${esc(qPatient)}"></div>
        <div class="cx-field"><label>التصنيف</label>
          <select class="cx-select" id="up_cat">
            <option value="lab">تحليل</option><option value="radiology">أشعة</option>
            <option value="id">هوية</option><option value="consent">موافقة</option>
            <option value="other">أخرى</option>
          </select>
        </div>
        <div class="cx-field"><label>الملف</label><input class="cx-input" type="file" id="up_file"></div>`, async () => {
        const fd = new FormData();
        fd.append("patient_id", document.getElementById("up_pid").value);
        fd.append("category", document.getElementById("up_cat").value);
        const file = document.getElementById("up_file").files[0];
        if (!file) throw new Error("اختر ملفاً");
        fd.append("file", file);
        const res = await fetch("/clinics/api/attachments", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || "فشل الرفع");
        state.attachPatientId = document.getElementById("up_pid").value;
      });
    };
  }

  async function renderCommunications() {
    if (window.ClinicsCommunications) {
      await window.ClinicsCommunications.render(state, root, { api, esc, showNotice, openModal, render, promptNewAppointment });
      return;
    }
    const data = await api("/clinics/api/communications");
    const qr = await api("/clinics/api/booking-qr").catch(() => null);
    const bookingUrl = (qr && qr.url) || `${window.location.origin}/c/${shell.dataset.tenantSlug || ""}`;
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Patient Comms</div><h1>التواصل والتذكيرات</h1><p>واتساب، تأكيد المواعيد، وتذكيرات تلقائية بدون تكرار.</p></div>
        <div class="cx-actions">
          <button class="cx-btn" id="btnJobs">تشغيل المهام</button>
          <button class="cx-btn cx-btn--primary" id="btnProcess">تشغيل التذكيرات</button>
        </div>
      </section>
      <section class="cx-kpis">
        <article class="cx-kpi"><span>واتساب</span><strong>${data.whatsapp_enabled ? "مفعّل" : "موقوف"}</strong></article>
        <article class="cx-kpi"><span>تذكيرات معلقة</span><strong>${data.pending_reminders || 0}</strong></article>
        <article class="cx-kpi"><span>متابعات مستحقة</span><strong>${data.due_followups || 0}</strong></article>
      </section>
      <article class="cx-card">
        <p style="margin:0 0 10px;color:var(--cx-muted)">رابط الحجز وQR للمرضى:</p>
        <code style="display:block;padding:12px;background:var(--cx-soft);border-radius:12px;direction:ltr;margin-bottom:12px">${esc(bookingUrl)}</code>
        ${qr && qr.qr_image ? `<img src="${esc(qr.qr_image)}" alt="QR" width="180" height="180" style="border-radius:12px;background:#fff;padding:8px">` : ""}
      </article>
      <article class="cx-card" style="margin-top:14px">
        <div class="cx-card__head"><div><h2>سجل الرسائل</h2></div></div>
        <div class="cx-feed">
          ${(data.recent_messages || []).map((m) => `
            <div class="cx-feed__item">
              <strong>${esc(m.template_key)}</strong> → ${esc(m.recipient)} · ${esc(m.status)}
              <small>${esc(window.FinoraTime.dateTime((m.sent_at || m.created_at || "")))}</small>
            </div>`).join("") || '<div class="cx-empty">لا رسائل بعد</div>'}
        </div>
      </article>
    `;
    document.getElementById("btnProcess").onclick = async () => {
      try {
        const r = await api("/clinics/api/reminders/process", { method: "POST", body: "{}" });
        showNotice(`تمت معالجة ${r.processed} · أُرسل ${r.sent}`, false);
        await render();
      } catch (err) { showNotice(err.message || String(err)); }
    };
    document.getElementById("btnJobs").onclick = async () => {
      try {
        const r = await api("/clinics/api/jobs/run", { method: "POST", body: "{}" });
        showNotice(`مجدول: ${r.scheduled || 0} · أُرسل ${r.sent || 0}`, false);
        await render();
      } catch (err) { showNotice(err.message || String(err)); }
    };
  }

  async function renderFollowups() {
    const rows = await api("/clinics/api/followups");
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Follow-up Queue</div><h1>المتابعات</h1><p>مرضى يحتاجون مراجعة بعد الزيارة.</p></div>
      </section>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>المريض</th><th>الطبيب</th><th>الاستحقاق</th><th>الحالة</th><th></th></tr></thead>
        <tbody>
          ${rows.map((f) => `
            <tr>
              <td>${esc(f.patient_name)}<br><small>${esc(f.patient_phone)}</small></td>
              <td>${esc(f.doctor_name || "—")}</td>
              <td>${esc(f.due_date)}</td>
              <td>${esc(f.status)}</td>
              <td>
                ${f.status === "due" ? `<button class="cx-btn cx-btn--sm" data-contact="${f.id}">تم التواصل</button>` : "—"}
              </td>
            </tr>`).join("") || `<tr><td colspan="5"><div class="cx-empty">لا متابعات</div></td></tr>`}
        </tbody>
      </table></div></article>
    `;
    root.querySelectorAll("[data-contact]").forEach((btn) => {
      btn.onclick = async () => {
        await api(`/clinics/api/followups/${btn.dataset.contact}`, { method: "PUT", body: JSON.stringify({ status: "contacted" }) });
        await render();
      };
    });
  }

  async function renderSuppliers() {
    if (window.ClinicsInventory) {
      await window.ClinicsInventory.renderSuppliers(state, root, { api, esc, money, showNotice, openModal, render });
      return;
    }
    const rows = await api("/clinics/api/suppliers?active=0");
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Suppliers</div><h1>الموردون</h1><p>موردو مستلزمات العيادة.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnAdd">مورد جديد</button></div>
      </section>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>الاسم</th><th>الهاتف</th><th>جهة الاتصال</th><th></th></tr></thead>
        <tbody>
          ${rows.map((s) => `
            <tr>
              <td>${esc(s.name)}</td><td>${esc(s.phone)}</td><td>${esc(s.contact_person)}</td>
              <td><a class="cx-btn cx-btn--sm" href="#" data-stmt="${s.id}">كشف</a></td>
            </tr>`).join("") || `<tr><td colspan="4"><div class="cx-empty">لا موردين</div></td></tr>`}
        </tbody>
      </table></div></article>
    `;
    document.getElementById("btnAdd").onclick = () => {
      openModal("مورد جديد", `
        <div class="cx-field"><label>الاسم</label><input class="cx-input" id="sup_name"></div>
        <div class="cx-field-row">
          <div class="cx-field"><label>الهاتف</label><input class="cx-input" id="sup_phone"></div>
          <div class="cx-field"><label>جهة الاتصال</label><input class="cx-input" id="sup_contact"></div>
        </div>`, async () => {
        await api("/clinics/api/suppliers", { method: "POST", body: JSON.stringify({
          name: document.getElementById("sup_name").value,
          phone: document.getElementById("sup_phone").value,
          contact_person: document.getElementById("sup_contact").value,
        })});
      });
    };
    root.querySelectorAll("[data-stmt]").forEach((a) => {
      a.onclick = async (e) => {
        e.preventDefault();
        const stmt = await api(`/clinics/api/suppliers/${a.dataset.stmt}/statement`);
        openModal(`كشف ${stmt.supplier.name}`, `
          <p><strong>الرصيد:</strong> ${money(stmt.outstanding_balance)}</p>
          <div class="cx-feed">${(stmt.lines||[]).map((l)=>`<div class="cx-feed__item">${esc(l.reference)} · ${money(l.debit||0)} / ${money(l.credit||0)} · ${money(l.balance)}</div>`).join("")}</div>`, async () => {});
      };
    });
  }

  async function renderPurchases() {
    if (window.ClinicsPurchases) {
      await window.ClinicsPurchases.render(state, root, { api, esc, money, showNotice, openModal, render });
      return;
    }
    if (window.ClinicsInventory) {
      await window.ClinicsInventory.renderPurchases(state, root, { api, esc, money, showNotice, openModal, render });
      return;
    }
    const [rows, suppliers, items] = await Promise.all([
      api("/clinics/api/purchases"),
      api("/clinics/api/suppliers"),
      api("/clinics/api/inventory"),
    ]);
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Purchasing</div><h1>مشتريات المخزون</h1><p>فواتير شراء مع إدخال تلقائي للمخزون.</p></div>
        <div class="cx-actions"><button class="cx-btn cx-btn--primary" id="btnAdd">فاتورة شراء</button></div>
      </section>
      <article class="cx-card"><div class="cx-table-wrap"><table class="cx-table">
        <thead><tr><th>رقم</th><th>المورد</th><th>التاريخ</th><th>الإجمالي</th><th>المتبقي</th></tr></thead>
        <tbody>
          ${rows.map((p) => `<tr><td>${esc(p.purchase_number)}</td><td>${esc(p.supplier_name)}</td><td>${esc(p.purchase_date)}</td><td class="cx-money">${money(p.total)}</td><td class="cx-money">${money(p.balance)}</td></tr>`).join("") || `<tr><td colspan="5"><div class="cx-empty">لا مشتريات</div></td></tr>`}
        </tbody>
      </table></div></article>
    `;
    document.getElementById("btnAdd").onclick = () => {
      openModal("فاتورة شراء", `
        <div class="cx-field"><label>المورد</label>
          <select class="cx-select" id="p_sup">${suppliers.map((s)=>`<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select>
        </div>
        <div class="cx-field"><label>الصنف</label>
          <select class="cx-select" id="p_item">${items.map((i)=>`<option value="${i.id}">${esc(i.name)}</option>`).join("")}</select>
        </div>
        <div class="cx-field-row">
          <div class="cx-field"><label>الكمية</label><input class="cx-input" id="p_qty" type="number" value="1"></div>
          <div class="cx-field"><label>سعر الوحدة</label><input class="cx-input" id="p_cost" type="number" value="0"></div>
        </div>`, async () => {
        await api("/clinics/api/purchases", { method: "POST", body: JSON.stringify({
          supplier_id: Number(document.getElementById("p_sup").value),
          items: [{ item_id: Number(document.getElementById("p_item").value), quantity: document.getElementById("p_qty").value, unit_cost: document.getElementById("p_cost").value }],
        })});
      });
    };
  }

  async function renderSettings() {
    const [s, specialties, specialtyRegistry] = await Promise.all([
      api("/clinics/api/settings"),
      api("/clinics/api/specialties").catch(() => state.bootstrap?.specialties || []),
      api("/clinics/api/specialty-registry").catch(() => ({ items: [] })),
    ]);
    const activeSpecialties = (specialties || []).filter((item) => item.is_active !== false);
    const registryByCode = Object.fromEntries((specialtyRegistry.items || []).map((item) => [item.code, item]));
    const featureLabels = {
      odontogram: "مخطط الأسنان",
      treatment_plans: "خطط العلاج",
      sessions: "جلسات العلاج",
      dental_images: "صور الأسنان",
      dental_reports: "تقارير الأسنان",
      clinical_timeline: "التسلسل السريري",
      ecg: "تخطيط القلب",
      echo: "الإيكو",
      growth: "متابعة النمو",
      vaccinations: "اللقاحات",
      pregnancy: "متابعة الحمل",
    };
    const slug = shell.dataset.tenantSlug || "";
    const bookingPath = slug ? `/c/${slug}` : "/c/{tenant_slug}";
    const bookingUrl = `${window.location.origin}${bookingPath}`;
    const switchHtml = (id, checked, title, hint = "") => `
      <label class="cx-settings-switch">
        <input type="checkbox" id="${id}" ${checked ? "checked" : ""}>
        <span class="cx-settings-switch__ui" aria-hidden="true"></span>
        <span class="cx-settings-switch__copy"><b>${title}</b>${hint ? `<small>${hint}</small>` : ""}</span>
      </label>`;
    const checkHtml = (id, checked, title, hint = "") => `
      <label class="cx-settings-check">
        <input type="checkbox" id="${id}" ${checked ? "checked" : ""}>
        <span><b>${title}</b>${hint ? `<small>${hint}</small>` : ""}</span>
      </label>`;
    const specialtyFeaturesHtml = activeSpecialties.map((specialty) => {
      const registry = registryByCode[specialty.code];
      const entries = Object.entries(registry?.features || {});
      if (!entries.length) return "";
      const configured = s.specialty_features?.[specialty.code] || {};
      return `<div class="cx-settings-features__group"><strong>${esc(specialty.name_ar)}</strong>
        ${entries.map(([feature, defaultValue]) => {
          const enabled = Object.prototype.hasOwnProperty.call(configured, feature)
            ? configured[feature] !== false
            : defaultValue !== false;
          return `<label><input type="checkbox" data-spec-feature="${esc(feature)}" data-spec-code="${esc(specialty.code)}" ${enabled ? "checked" : ""}> ${esc(featureLabels[feature] || feature)}</label>`;
        }).join("")}
      </div>`;
    }).join("") || '<p class="cx-muted" style="margin:0">لا توجد ميزات قابلة للضبط للاختصاصات الحالية.</p>';

    const tabs = [
      ["general", "عام", "fa-building"],
      ["appearance", "المظهر", "fa-palette"],
      ["specialties", "الاختصاصات", "fa-stethoscope"],
      ["booking", "الحجز والمتابعة", "fa-calendar-check"],
      ["display", "شاشة العرض", "fa-tv"],
      ["guides", "الأدلة", "fa-book"],
    ];
    const hashTab = String(location.hash || "").replace(/^#/, "");
    const activeTab = tabs.some(([id]) => id === hashTab) ? hashTab : "general";

    root.innerHTML = `
      <section class="cx-hero">
        <div>
          <div class="cx-kicker">Clinic Setup</div>
          <h1>إعدادات العيادة</h1>
          <p>نظّم بيانات العيادة، المظهر، الاختصاصات، الحجز الإلكتروني، وشاشة الانتظار.</p>
        </div>
      </section>
      <div class="cx-settings">
        <nav class="cx-settings__tabs" role="tablist" aria-label="أقسام الإعدادات">
          ${tabs.map(([id, label, icon]) => `
            <button type="button" role="tab" data-settings-tab="${id}" class="${id === activeTab ? "is-active" : ""}" aria-selected="${id === activeTab ? "true" : "false"}">
              <i class="fa ${icon}" aria-hidden="true"></i>${label}
            </button>`).join("")}
        </nav>

        <div class="cx-settings__panel ${activeTab === "general" ? "is-active" : ""}" data-settings-panel="general">
          <div class="cx-settings-grid">
            <article class="cx-settings-panel cx-settings-panel--wide">
              <header>
                <div>
                  <h2><i class="fa fa-building" aria-hidden="true"></i> بيانات المنشأة</h2>
                  <p>الاسم ونوع المنشأة — منفصل عن الاختصاصات الطبية.</p>
                </div>
              </header>
              <div class="cx-settings-stack">
                <div class="cx-field"><label>اسم العيادة</label><input class="cx-input" id="set_name" value="${esc(s.clinic_name || "")}"></div>
                <div class="cx-field">
                  <label>شعار العيادة (رابط الصورة)</label>
                  <input class="cx-input" id="set_logo" dir="ltr" value="${esc(s.public_logo_url || "")}" placeholder="https://... أو /static/...">
                  <span class="cx-settings-hint">يظهر على الوصفة المطبوعة وصفحة الحجز. اتركه فارغاً لاستخدام شعار Finora.</span>
                </div>
                ${s.public_logo_url ? `<div class="cx-settings-hint" style="display:flex;align-items:center;gap:10px"><img src="${esc(s.public_logo_url)}" alt="الشعار" style="width:48px;height:48px;object-fit:contain;border-radius:10px;background:#fff;border:1px solid var(--cx-line);padding:4px" onerror="this.style.display='none'"><span>معاينة الشعار الحالي</span></div>` : ""}
                <div class="cx-field-row">
                  <div class="cx-field"><label>هاتف العيادة</label><input class="cx-input" id="set_phone" dir="ltr" value="${esc(s.clinic_whatsapp_number || "")}" placeholder="07xxxxxxxxx"></div>
                  <div class="cx-field"><label>العنوان</label><input class="cx-input" id="set_location" value="${esc(s.public_location || "")}" placeholder="المدينة — الحي"></div>
                </div>
                <span class="cx-settings-hint">الهاتف والعنوان يظهران في رأس الوصفة المطبوعة.</span>
                <div class="cx-field">
                  <label>نوع المنشأة</label>
                  <select class="cx-select" id="set_org_mode">
                    ${(s.organization_modes || []).map((t) => `<option value="${t.key}" ${t.key === s.organization_mode ? "selected" : ""}>${esc(t.label)}</option>`).join("")}
                  </select>
                  <span class="cx-settings-hint">عيادة طبيب واحد · عيادة متعددة الأطباء · مجمع طبي. لا يُخلط مع الاختصاصات الطبية.</span>
                </div>
                <div class="cx-field">
                  <label>نسبة العمولة الافتراضية (Legacy)</label>
                  <input class="cx-input" id="set_comm" type="number" value="${s.doctor_commission_default_pct || 0}">
                  <span class="cx-settings-hint">للأنظمة القديمة فقط — العمولات الحديثة تُدار من إعدادات الطبيب.</span>
                </div>
                ${switchHtml("set_attendance_gate", !!s.doctor_availability_requires_attendance, "ربط التوافر بحضور HR", "الطبيب يظهر متاحاً فقط بعد تسجيل حضوره.")}
              </div>
            </article>
          </div>
        </div>

        <div class="cx-settings__panel ${activeTab === "appearance" ? "is-active" : ""}" data-settings-panel="appearance">
          <article class="cx-settings-panel">
            <header><div>
              <h2><i class="fa fa-palette" aria-hidden="true"></i> مظهر نظام العيادات</h2>
              <p>اختر المظهر المناسب لك. يتغيّر النظام بالكامل، بما فيه القائمة الجانبية، مباشرة.</p>
            </div></header>
            <div class="cx-theme-choices" role="radiogroup" aria-label="مظهر نظام العيادات">
              ${[["light", "الوضع الفاتح", "واجهة مشرقة وواضحة للعمل اليومي", "fa-sun"], ["dark", "الوضع الداكن", "ألوان هادئة للعمل في الإضاءة المنخفضة", "fa-moon"]].map(([theme, title, hint, icon]) => `
                <label class="cx-theme-choice">
                  <input type="radio" name="clinic-theme" data-clinic-theme value="${theme}" ${window.ClinicsTheme?.current() === theme ? "checked" : ""}>
                  <span class="cx-theme-preview ${theme === "dark" ? "cx-theme-preview--dark" : ""}" aria-hidden="true">
                    <span class="cx-theme-preview__main"><span></span><span></span><span></span></span>
                    <span class="cx-theme-preview__side"><i></i><i></i><i></i><i></i></span>
                  </span>
                  <span class="cx-theme-choice__copy"><i class="fa ${icon}" aria-hidden="true"></i><span><b>${title}</b><small>${hint}</small></span><i class="fa fa-circle-check cx-theme-choice__check" aria-hidden="true"></i></span>
                </label>`).join("")}
            </div>
            <p class="cx-settings-hint" id="cxThemeStatus" role="status" style="margin:16px 0 0">يُحفظ اختيارك تلقائياً على هذا المتصفح، ويستمر عند فتح النظام مرة أخرى.</p>
          </article>
        </div>

        <div class="cx-settings__panel ${activeTab === "specialties" ? "is-active" : ""}" data-settings-panel="specialties">
          <div class="cx-settings-grid">
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-stethoscope" aria-hidden="true"></i> الاختصاصات</h2>
                  <p>الاختصاص الرئيسي ورابط إدارة القائمة.</p>
                </div>
              </header>
              <div class="cx-settings-stack">
                <a class="cx-settings-link" href="/clinics/specialties">
                  <i class="fa fa-stethoscope" aria-hidden="true"></i>
                  <span><b>إدارة الاختصاصات</b><small>أسنان، أطفال، جلدية… تُدار بصورة مستقلة</small></span>
                  <em><i class="fa fa-chevron-left" aria-hidden="true"></i></em>
                </a>
                <div class="cx-field">
                  <label>الاختصاص الرئيسي للعيادة</label>
                  <select class="cx-select" id="set_primary_specialty">
                    <option value="">طب عام / حسب الطبيب</option>
                    ${activeSpecialties.map((item) => `<option value="${item.id}" ${String(item.id) === String(s.primary_specialty_id || "") ? "selected" : ""}>${esc(item.name_ar)}</option>`).join("")}
                  </select>
                  <span class="cx-settings-hint">خيار احتياطي بعد اختصاص الزيارة أو الموعد واختصاص الطبيب الرئيسي.</span>
                </div>
                <button type="button" class="cx-btn" id="btnSeed"><i class="fa fa-seedling" aria-hidden="true"></i> إضافة الاختصاصات الافتراضية</button>
              </div>
            </article>
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-tooth" aria-hidden="true"></i> وحدة الأسنان</h2>
                  <p>الترقيم، الجلسات، والأسطح.</p>
                </div>
              </header>
              <div class="cx-settings-stack" id="cxDentalSettings">
                ${switchHtml("set_dental_enabled", s.dental_config?.enabled !== false, "تفعيل وحدة الأسنان", "مخطط الأسنان وخطط العلاج والجلسات.")}
                <div class="cx-field-row" data-dental-deps>
                  <div class="cx-field"><label>نظام ترقيم الأسنان</label>
                    <select class="cx-select" id="set_dental_numbering">
                      ${[["fdi", "FDI (افتراضي)"], ["universal", "Universal"], ["palmer", "Palmer"]].map(([key, label]) => `<option value="${key}" ${String(s.dental_config?.tooth_numbering || "fdi") === key ? "selected" : ""}>${label}</option>`).join("")}
                    </select>
                  </div>
                  <div class="cx-field"><label>الجلسات الافتراضية</label><input class="cx-input" id="set_dental_sessions" type="number" min="1" value="${s.dental_config?.default_sessions || 1}"></div>
                </div>
                <div class="cx-settings-stack" data-dental-deps>
                  ${checkHtml("set_dental_primary", s.dental_config?.enable_primary_teeth !== false, "الأسنان اللبنية")}
                  ${checkHtml("set_dental_surfaces", s.dental_config?.enable_tooth_surfaces !== false, "أسطح السن")}
                  ${checkHtml("set_dental_pay", s.dental_config?.enable_treatment_payments !== false, "دفعات خطط العلاج")}
                </div>
              </div>
            </article>
            <article class="cx-settings-panel cx-settings-panel--wide">
              <header>
                <div>
                  <h2><i class="fa fa-sliders" aria-hidden="true"></i> ميزات واجهات الاختصاص</h2>
                  <p>فعّل أو أوقف الأدوات السريرية لكل اختصاص نشط.</p>
                </div>
              </header>
              <fieldset class="cx-settings-features">${specialtyFeaturesHtml}</fieldset>
            </article>
          </div>
        </div>

        <div class="cx-settings__panel ${activeTab === "booking" ? "is-active" : ""}" data-settings-panel="booking">
          <div class="cx-settings-grid">
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-calendar-check" aria-hidden="true"></i> جدولة المواعيد</h2>
                  <p>المدة، المتابعة، والتذكير.</p>
                </div>
              </header>
              <div class="cx-settings-stack">
                <div class="cx-field-row">
                  <div class="cx-field"><label>مدة الموعد (د)</label><input class="cx-input" id="set_slot" type="number" value="${s.appointment_slot_minutes || 15}"></div>
                  <div class="cx-field"><label>أيام المتابعة الافتراضية</label><input class="cx-input" id="set_fu" type="number" value="${s.default_followup_days || 7}"></div>
                </div>
                <div class="cx-field"><label>تذكير قبل الموعد (ساعة)</label><input class="cx-input" id="set_rem" type="number" value="${s.reminder_hours_before || 24}"></div>
                <div class="cx-field"><label>نص ترحيب الحجز الإلكتروني</label><textarea class="cx-textarea" id="set_welcome" rows="4">${esc(s.booking_welcome_text || "")}</textarea></div>
              </div>
            </article>
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-globe" aria-hidden="true"></i> القنوات الإلكترونية</h2>
                  <p>الحجز العام، OTP، وواتساب.</p>
                </div>
              </header>
              <div class="cx-settings-stack">
                ${switchHtml("set_booking", !!s.allow_online_booking, "تفعيل الحجز الإلكتروني", "يفتح رابط الحجز العام للمرضى.")}
                ${switchHtml("set_otp", !!s.booking_otp_enabled, "طلب OTP عند الحجز", "تأكيد رقم الهاتف برمز لمرة واحدة.")}
                ${switchHtml("set_wa", !!s.whatsapp_notifications_enabled, "تفعيل واتساب", "إشعارات وتذكيرات عبر واتساب.")}
                ${s.allow_online_booking ? `<div class="cx-settings-booking-url"><p>رابط الحجز الإلكتروني</p><code>${esc(bookingUrl)}</code></div>` : ""}
              </div>
            </article>
          </div>
        </div>

        <div class="cx-settings__panel ${activeTab === "display" ? "is-active" : ""}" data-settings-panel="display">
          <div class="cx-settings-grid">
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-tv" aria-hidden="true"></i> شاشة الانتظار</h2>
                  <p>تفعيل الشاشة العامة للطابور.</p>
                </div>
              </header>
              <div class="cx-settings-stack">
                ${switchHtml("set_queue", !!s.queue_display_enabled, "تفعيل شاشة الانتظار", "عرض أرقام الدور على شاشة TV.")}
                <a class="cx-settings-link" href="/clinics/display" target="_blank" rel="noopener">
                  <i class="fa fa-arrow-up-right-from-square" aria-hidden="true"></i>
                  <span><b>فتح شاشة العرض</b><small>/clinics/display — بدون أزرار تحكم على الشاشة</small></span>
                  <em><i class="fa fa-chevron-left" aria-hidden="true"></i></em>
                </a>
              </div>
            </article>
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-volume-high" aria-hidden="true"></i> النداء والعرض</h2>
                  <p>الصوت، الاسم المختصر، ورسالة التذييل.</p>
                </div>
              </header>
              <div class="cx-settings-stack">
                ${switchHtml("set_disp_sound", s.display_sound_enabled !== false, "صوت النداء (Chime)")}
                ${switchHtml("set_disp_voice", !!s.display_voice_enabled, "نداء صوتي")}
                ${switchHtml("set_disp_short", !!s.display_show_short_name, "عرض اسم مختصر فقط", "مثلاً: م. حسن")}
                <div class="cx-field"><label>مستوى الصوت (0–100)</label><input class="cx-input" id="set_disp_vol" type="number" min="0" max="100" value="${s.display_volume ?? 70}"></div>
                <div class="cx-field"><label>رسالة أسفل الشاشة</label><textarea class="cx-textarea" id="set_disp_footer" rows="3" placeholder="يرجى متابعة رقم الدور على الشاشة.">${esc(s.display_footer_message || "")}</textarea></div>
              </div>
            </article>
          </div>
        </div>

        <div class="cx-settings__panel ${activeTab === "guides" ? "is-active" : ""}" data-settings-panel="guides">
          <div class="cx-settings-grid cx-settings-grid--single">
            <article class="cx-settings-panel">
              <header>
                <div>
                  <h2><i class="fa fa-book" aria-hidden="true"></i> أدلة التشغيل حسب الاختصاص</h2>
                  <p>دليل قابل للطباعة لكل اختصاص — يتخصّص باسم عيادتك ورابط الحجز.</p>
                </div>
                <a class="cx-btn cx-btn--sm" href="/clinics/specialties">إدارة الاختصاصات</a>
              </header>
              <div class="cx-guide-grid" id="cxGuideGrid"><div class="cx-empty">جاري تحميل الأدلة…</div></div>
            </article>
          </div>
        </div>

        <div class="cx-settings-save">
          <button type="button" class="cx-btn cx-btn--primary" id="btnSave"><i class="fa fa-floppy-disk" aria-hidden="true"></i> حفظ الإعدادات</button>
        </div>
      </div>
    `;

    const activateSettingsTab = (tabId) => {
      root.querySelectorAll("[data-settings-tab]").forEach((btn) => {
        const on = btn.dataset.settingsTab === tabId;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      });
      root.querySelectorAll("[data-settings-panel]").forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.settingsPanel === tabId);
      });
      if (location.hash !== `#${tabId}`) {
        history.replaceState(null, "", `#${tabId}`);
      }
    };
    root.querySelectorAll("[data-settings-tab]").forEach((btn) => {
      btn.onclick = () => activateSettingsTab(btn.dataset.settingsTab);
    });
    root.querySelectorAll("[data-clinic-theme]").forEach((input) => {
      input.addEventListener("change", () => {
        if (!input.checked) return;
        window.ClinicsTheme?.set(input.value);
        document.getElementById("cxThemeStatus").textContent = input.value === "dark"
          ? "تم تطبيق الوضع الداكن. يُحفظ اختيارك تلقائياً على هذا المتصفح."
          : "تم تطبيق الوضع الفاتح. يُحفظ اختيارك تلقائياً على هذا المتصفح.";
      });
    });

    const syncDentalDeps = () => {
      const enabled = document.getElementById("set_dental_enabled")?.checked !== false;
      root.querySelectorAll("[data-dental-deps]").forEach((el) => {
        el.style.opacity = enabled ? "1" : ".45";
        el.style.pointerEvents = enabled ? "" : "none";
      });
    };
    document.getElementById("set_dental_enabled")?.addEventListener("change", syncDentalDeps);
    syncDentalDeps();

    document.getElementById("btnSave").onclick = async () => {
      try {
        const specialtyFeatures = JSON.parse(JSON.stringify(s.specialty_features || {}));
        root.querySelectorAll("[data-spec-feature]").forEach((input) => {
          specialtyFeatures[input.dataset.specCode] ||= {};
          specialtyFeatures[input.dataset.specCode][input.dataset.specFeature] = input.checked;
        });
        await api("/clinics/api/settings", {
          method: "POST",
          body: JSON.stringify({
            clinic_name: document.getElementById("set_name").value,
            public_logo_url: document.getElementById("set_logo")?.value || "",
            clinic_whatsapp_number: document.getElementById("set_phone")?.value || "",
            public_location: document.getElementById("set_location")?.value || "",
            organization_mode: document.getElementById("set_org_mode").value,
            primary_specialty_id: document.getElementById("set_primary_specialty").value || null,
            specialty_features: specialtyFeatures,
            dental_config: {
              enabled: document.getElementById("set_dental_enabled").checked,
              tooth_numbering: document.getElementById("set_dental_numbering").value,
              default_sessions: Number(document.getElementById("set_dental_sessions").value || 1),
              enable_primary_teeth: document.getElementById("set_dental_primary").checked,
              enable_tooth_surfaces: document.getElementById("set_dental_surfaces").checked,
              enable_treatment_payments: document.getElementById("set_dental_pay").checked,
            },
            appointment_slot_minutes: document.getElementById("set_slot").value,
            doctor_commission_default_pct: document.getElementById("set_comm").value,
            booking_welcome_text: document.getElementById("set_welcome").value,
            default_followup_days: document.getElementById("set_fu").value,
            reminder_hours_before: document.getElementById("set_rem").value,
            allow_online_booking: document.getElementById("set_booking").checked,
            booking_otp_enabled: document.getElementById("set_otp").checked,
            whatsapp_notifications_enabled: document.getElementById("set_wa").checked,
            queue_display_enabled: document.getElementById("set_queue").checked,
            doctor_availability_requires_attendance: document.getElementById("set_attendance_gate").checked,
            display_sound_enabled: document.getElementById("set_disp_sound").checked,
            display_voice_enabled: document.getElementById("set_disp_voice").checked,
            display_show_short_name: document.getElementById("set_disp_short").checked,
            display_volume: document.getElementById("set_disp_vol").value,
            display_footer_message: document.getElementById("set_disp_footer").value,
          }),
        });
        state.bootstrap = await api("/clinics/api/bootstrap");
        showNotice("تم حفظ الإعدادات", false);
      } catch (err) {
        showNotice(err.message || String(err));
      }
    };
    document.getElementById("btnSeed").onclick = async () => {
      try {
        const r = await api("/clinics/api/specialty/seed", {
          method: "POST",
          body: JSON.stringify({}),
        });
        state.bootstrap = await api("/clinics/api/bootstrap");
        showNotice(`تم تجهيز ${r.specialties.length} اختصاصاً مع نماذج الزيارة`, false);
        await loadSpecialtyGuides();
      } catch (err) {
        showNotice(err.message || String(err));
      }
    };

    async function loadSpecialtyGuides() {
      const grid = document.getElementById("cxGuideGrid");
      if (!grid) return;
      try {
        const data = await api("/clinics/api/guides");
        const items = data.items || [];
        grid.innerHTML = items.map((g) => `
          <a class="cx-guide-card ${g.is_active ? "is-active" : ""}" href="${esc(g.url)}" target="_blank" rel="noopener">
            <strong>${esc(g.name_ar)}</strong>
            <small>${esc(g.name_en || g.code)}</small>
            <span>${g.is_active ? "مفعّل في العيادة" : "مرجع"}</span>
            <em>فتح الدليل / طباعة</em>
          </a>
        `).join("") || '<div class="cx-empty">لا توجد أدلة</div>';
      } catch (err) {
        grid.innerHTML = `<div class="cx-empty">${esc(err.message || String(err))}</div>`;
      }
    }
    await loadSpecialtyGuides();
  }

  async function renderSpecialties() {
    const rows = await api("/clinics/api/specialties");
    root.innerHTML = `
      <section class="cx-hero">
        <div><div class="cx-kicker">Medical Specialties</div><h1>الاختصاصات</h1><p>اختصاصات المنشأة ونماذج الزيارة المرتبطة بها.</p></div>
        <div class="cx-actions"><button class="cx-btn" id="btnSeedSpecialties">الاختصاصات الافتراضية</button><button class="cx-btn cx-btn--primary" id="btnAddSpecialty" data-finora-action="specialty.create">إضافة اختصاص</button></div>
      </section>
      <section class="cx-card"><div class="cx-table-wrap"><table class="cx-table"><thead><tr><th>الاختصاص</th><th>الأطباء</th><th>نموذج الزيارة</th><th>الحالة</th><th></th></tr></thead><tbody>
        ${rows.map((s) => `<tr><td><strong>${esc(s.name_ar)}</strong><small>${esc(s.name_en || s.code)}</small></td><td>${s.doctor_count}</td><td>${s.default_visit_template_id ? `#${s.default_visit_template_id}` : "النموذج العام"}</td><td>${s.is_active ? "مفعّل" : "معطّل"}</td><td><button class="cx-btn cx-btn--sm" data-edit-specialty="${s.id}">تعديل</button></td></tr>`).join("") || '<tr><td colspan="5" class="cx-empty">لا توجد اختصاصات بعد</td></tr>'}
      </tbody></table></div></section>`;
    const openSpecialty = (specialty) => openModal(specialty ? "تعديل اختصاص" : "اختصاص جديد", `
      <div data-finora-section="specialty.form">
      <div class="cx-field"><label>الاسم العربي *</label><input class="cx-input" id="sp_ar" data-finora-field="specialty.name" value="${esc(specialty?.name_ar || "")}"></div>
      <div class="cx-field"><label>الاسم الإنجليزي</label><input class="cx-input" id="sp_en" value="${esc(specialty?.name_en || "")}"></div>
      ${specialty ? "" : '<div class="cx-field"><label>الرمز</label><input class="cx-input" id="sp_code" data-finora-field="specialty.code" placeholder="family_medicine"></div>'}
      <div class="cx-field"><label>الوصف</label><textarea class="cx-textarea" id="sp_desc">${esc(specialty?.description || "")}</textarea></div>
      ${specialty ? `<label><input type="checkbox" id="sp_active" ${specialty.is_active ? "checked" : ""}> مفعّل</label>` : ""}
      </div>`,
      async () => {
        const payload = {name_ar: document.getElementById("sp_ar").value, name_en: document.getElementById("sp_en").value, description: document.getElementById("sp_desc").value};
        if (!specialty) payload.code = document.getElementById("sp_code").value;
        else payload.is_active = document.getElementById("sp_active").checked;
        await api(specialty ? `/clinics/api/specialties/${specialty.id}` : "/clinics/api/specialties", {method: specialty ? "PATCH" : "POST", body: JSON.stringify(payload)});
        await renderSpecialties();
      }, { finoraAction: specialty ? "specialty.save.edit" : "specialty.save" });
    document.getElementById("btnAddSpecialty").onclick = () => openSpecialty(null);
    document.querySelectorAll("[data-edit-specialty]").forEach((btn) => btn.onclick = () => openSpecialty(rows.find((s) => String(s.id) === btn.dataset.editSpecialty)));
    document.querySelectorAll("[data-edit-specialty]").forEach((btn) => {
      const manage = document.createElement('button');
      manage.className = 'cx-btn cx-btn--sm';
      manage.textContent = 'إدارة نموذج الزيارة';
      manage.onclick = async () => {
        try {
          await window.ClinicsSpecialtyBuilder(root, rows.find(s => String(s.id) === btn.dataset.editSpecialty), {api, esc, showNotice, back:renderSpecialties, fieldHtml:specialtyFieldHtml});
        } catch (err) { showNotice(err.message || String(err)); }
      };
      btn.after(manage);
    });
    document.getElementById("btnSeedSpecialties").onclick = async () => { await api("/clinics/api/specialty/seed", {method:"POST", body:"{}"}); await renderSpecialties(); };
  }

  function promptNewPatient() {
    openModal(
      "مريض جديد",
      quickPatientFormHtml(),
      async () => {
        await api("/clinics/api/patients", {
          method: "POST",
          body: JSON.stringify(readPatientForm()),
        });
      },
      {
        saveLabel: "حفظ فقط",
        extraActions: [
          {
            label: "حفظ وإنشاء موعد",
            primary: true,
            skipRender: true,
            onClick: async () => {
              const created = await api("/clinics/api/patients", {
                method: "POST",
                body: JSON.stringify(readPatientForm()),
              });
              showNotice("تم حفظ المريض", false);
              promptNewAppointment(created.id);
            },
          },
          {
            label: "حفظ وبدء زيارة",
            onClick: async () => {
              const created = await api("/clinics/api/patients", {
                method: "POST",
                body: JSON.stringify(readPatientForm()),
              });
              const visit = await api("/clinics/api/visits", {
                method: "POST",
                body: JSON.stringify({ patient_id: created.id }),
              });
              location.href = `/clinics/doctor/${visit.id}`;
            },
          },
        ],
      }
    );
    bindPhoneDuplicateCheck();
  }

  function promptNewAppointment(fixedPatientId, dentalContext = null) {
    openModal("موعد جديد", appointmentFormFields(dentalContext), async () => {
      const inlinePatientId = await resolveInlinePatient("appt");
      const specNotes = collectAppointmentSpecialtyNotes();
      const baseNotes = String(document.getElementById("f_notes")?.value || "").trim();
      const payload = {
        patient_id: Number(inlinePatientId || document.getElementById("f_patient_id").value || fixedPatientId || 0),
        appointment_date: document.getElementById("f_date").value,
        start_time: document.getElementById("f_time").value,
        doctor_id: document.getElementById("f_doctor_id").value || null,
        specialty_id: document.getElementById("f_specialty_id").value || null,
        service_id: document.getElementById("f_service_id").value || null,
        duration_minutes: document.getElementById("f_duration")?.value || null,
        tooth_number: document.getElementById("f_tooth")?.value || dentalContext?.toothNumber || null,
        treatment_plan_item_id: dentalContext?.itemId || null,
        notes: [specNotes, baseNotes].filter(Boolean).join("\n"),
        status: "confirmed",
      };
      if (!payload.patient_id) throw new Error("اختر المريض أو أضف مريضاً جديداً");
      const appointment = await api("/clinics/api/appointments", { method: "POST", body: JSON.stringify(payload) });
      if (dentalContext?.sessionId) {
        await api(`/clinics/api/dental-sessions/${dentalContext.sessionId}`, {
          method: "PATCH",
          body: JSON.stringify({ appointment_id: appointment.id, scheduled_for: `${payload.appointment_date}T${payload.start_time}`, status: "scheduled" }),
        });
      } else if (dentalContext?.itemId) {
        await api(`/clinics/api/dental-treatment-plan-items/${dentalContext.itemId}/sessions`, {
          method: "POST",
          body: JSON.stringify({ appointment_id: appointment.id, scheduled_for: `${payload.appointment_date}T${payload.start_time}`, status: "scheduled" }),
        });
      }
    }, { finoraAction: "appointment.save" });
    bindInlinePatientCreator("appt", "f_patient_q", "f_patient_id");
    const specialtySelect = document.getElementById("f_specialty_id");
    const doctorSelect = document.getElementById("f_doctor_id");
    const serviceSelect = document.getElementById("f_service_id");
    const durationInput = document.getElementById("f_duration");
    const serviceHint = document.getElementById("f_service_hint");
    const specialtyFields = document.getElementById("f_specialty_fields");
    const allServices = (state.bootstrap?.services || []).filter((s) => s.active !== false);
    const specialties = (state.bootstrap?.specialties || []).filter((s) => s.is_active !== false);

    const selectedSpecialty = () => {
      const id = Number(specialtySelect?.value || 0);
      return specialties.find((s) => Number(s.id) === id) || null;
    };

    const refreshSpecialtyFields = () => {
      if (!specialtyFields) return;
      const specialty = selectedSpecialty();
      if (!specialty) {
        specialtyFields.innerHTML = `<div class="cx-empty" style="padding:10px">اختر اختصاصاً لإظهار الحقول الخاصة به</div>`;
        return;
      }
      specialtyFields.innerHTML = renderAppointmentSpecialtyFields(specialty, dentalContext);
    };

    const filterDoctors = () => {
      const specialtyId = Number(specialtySelect?.value || 0);
      Array.from(doctorSelect?.options || []).forEach((option) => {
        if (!option.value) return;
        const doctor = (state.bootstrap?.doctors || []).find((row) => String(row.id) === option.value);
        const docsSpecs = idList(doctor?.specialty_ids);
        option.hidden = Boolean(specialtyId && docsSpecs.length && !docsSpecs.includes(specialtyId));
      });
      if (doctorSelect?.selectedOptions?.[0]?.hidden) doctorSelect.value = "";
    };

    const filterServices = () => {
      const specialtyId = Number(specialtySelect?.value || 0);
      const doctorId = Number(doctorSelect?.value || 0);
      let visible = 0;
      Array.from(serviceSelect?.options || []).forEach((option) => {
        if (!option.value) return;
        const service = allServices.find((row) => String(row.id) === option.value);
        const ok = serviceMatchesSelection(service, specialtyId, doctorId);
        option.hidden = !ok;
        if (ok) visible += 1;
      });
      if (serviceSelect?.selectedOptions?.[0]?.hidden) serviceSelect.value = "";
      if (serviceHint) {
        if (!specialtyId && !doctorId) {
          serviceHint.textContent = "اختر الاختصاص (والطبيب) لتصفية الخدمات";
        } else if (!visible) {
          serviceHint.textContent = "لا توجد خدمات مربوطة بهذا الاختصاص/الطبيب — اربطها من شاشة الخدمات";
        } else {
          serviceHint.textContent = `${visible} خدمة متاحة حسب الاختصاص والطبيب`;
        }
      }
    };

    if (specialtySelect) {
      specialtySelect.onchange = () => {
        filterDoctors();
        filterServices();
        refreshSpecialtyFields();
      };
    }
    if (doctorSelect) {
      doctorSelect.onchange = () => {
        const doctorId = Number(doctorSelect.value || 0);
        const doctor = (state.bootstrap?.doctors || []).find((row) => Number(row.id) === doctorId);
        if (doctor && specialtySelect && !specialtySelect.value) {
          const primary = doctor.primary_specialty_id || idList(doctor.specialty_ids)[0];
          if (primary) specialtySelect.value = String(primary);
          filterDoctors();
          refreshSpecialtyFields();
        }
        filterServices();
      };
    }
    if (serviceSelect && durationInput) {
      serviceSelect.onchange = () => {
        const selected = serviceSelect.selectedOptions[0];
        if (selected?.dataset.duration) durationInput.value = selected.dataset.duration;
        if (selected?.dataset.requiresTooth === "1") {
          const tooth = document.getElementById("f_tooth");
          if (tooth && !tooth.value) tooth.focus();
        }
      };
    }
    filterDoctors();
    filterServices();
    refreshSpecialtyFields();
    bindPatientSearch({ fixedPatientId });
  }

  window.ClinicsOpenAppointment = promptNewAppointment;

  function applyClinicsNav() {
    const nav = state.bootstrap?.nav;
    if (!nav) return;
    if (window.ClinicsNav?.apply) window.ClinicsNav.apply(nav);
    document.dispatchEvent(new CustomEvent("clinics:bootstrap", { detail: state.bootstrap }));
  }

  async function render() {
    showNotice("");
    root.innerHTML = `<div class="cx-empty">جاري التحميل…</div>`;
    try {
      if (!state.bootstrap) state.bootstrap = await api("/clinics/api/bootstrap");
      applyClinicsNav();
      if (page === "dashboard") await renderDashboard();
      else if (page === "activity" && window.ClinicsActivity) await window.ClinicsActivity.render(state, root, { api, esc, showNotice });
      else if (page === "reception") await renderReception();
      else if (page === "queue") await renderQueue();
      else if (page === "display") await renderDisplay();
      else if (page === "appointments" || page === "calendar") await renderAppointments();
      else if (page === "patients") await renderPatients();
      else if (page === "patient_detail") await renderPatientDetail();
      else if (page === "visits") await renderVisits();
      else if (page === "doctor") await renderDoctor();
      else if (page === "billing") await renderBilling();
      else if (page === "expenses") await renderExpenses();
      else if (page === "cash") await renderCash();
      else if (page === "attachments" && window.ClinicsAttachments) await window.ClinicsAttachments.render(state, root, { api, esc, showNotice, openModal, render });
      else if (page === "settlements") await renderSettlements();
      else if (page === "inventory") await renderInventory();
      else if (page === "labs" && window.ClinicsOps) await window.ClinicsOps.labs(state, root, { api, esc, showNotice, openModal, render, bootstrap: state.bootstrap });
      else if (page === "radiology" && window.ClinicsOps) await window.ClinicsOps.radiology(state, root, { api, esc, showNotice, openModal, render, bootstrap: state.bootstrap });
      else if (page === "schedules") await renderSchedules();
      else if (page === "procedures" && window.ClinicsOps) await window.ClinicsOps.procedures(state, root, { api, esc, showNotice, openModal, render, bootstrap: state.bootstrap });
      else if (page === "doctors") await renderDoctors();
      else if (page === "staff" && window.ClinicsStaff) await window.ClinicsStaff.render(state, root, { api, esc, showNotice, openModal, render });
      else if (page === "specialties") await renderSpecialties();
      else if (page === "services") await renderServices();
      else if (page === "rooms") await renderRooms();
      else if (page === "reports") await renderReports();
      else if (page === "clinical" && window.ClinicsClinical) await window.ClinicsClinical.render(state, root, { api, esc, showNotice, openModal, render, promptNewAppointment });
      else if (page === "communications") await renderCommunications();
      else if (page === "followups" && window.ClinicsOps) await window.ClinicsOps.followups(state, root, { api, esc, showNotice, openModal, render, bootstrap: state.bootstrap });
      else if (page === "suppliers") await renderSuppliers();
      else if (page === "purchases") await renderPurchases();
      else if (page === "settings") await renderSettings();
      else root.innerHTML = `<div class="cx-empty">الصفحة غير متاحة</div>`;
    } catch (err) {
      root.innerHTML = `<div class="cx-empty">${esc(err.message || String(err))}</div>`;
      showNotice(err.message || String(err));
    }
  }

  render();
})();
