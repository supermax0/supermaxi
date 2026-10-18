/* Unified clinic staff, login accounts, and permissions. */
(() => {
  const iconFor = (row) => row.doctor ? "fa-user-doctor" : row.role_key === "clinic_reception" ? "fa-headset" : "fa-user-tie";

  async function render(state, root, ctx) {
    const { api, esc, showNotice, openModal } = ctx;
    let data = await api("/clinics/api/staff");
    let view = "all";
    let query = "";

    const roleMap = () => new Map((data.roles || []).map((row) => [row.key, row]));
    const branchOptions = (selected) => `<option value="">بدون فرع محدد</option>${(data.branches || []).map(
      (row) => `<option value="${row.id}" ${String(row.id) === String(selected || "") ? "selected" : ""}>${esc(row.name)}</option>`
    ).join("")}`;
    const roleOptions = (selected) => (data.roles || []).map(
      (row) => `<option value="${esc(row.key)}" ${row.key === selected ? "selected" : ""}>${esc(row.label)}</option>`
    ).join("");

    const permissionsHtml = (selected) => {
      const checked = new Set(selected || []);
      return `<div class="cx-staff-permissions">${(data.permission_groups || []).map((group) => `
        <fieldset data-finora-section="permissions.group.${group.key}"><legend>${esc(group.label)}</legend><div>
          ${group.permissions.map((permission) => `<label><input type="checkbox" data-staff-permission value="${esc(permission.name)}" ${checked.has(permission.name) ? "checked" : ""}><span>${esc(permission.label)}</span></label>`).join("")}
        </div></fieldset>`).join("")}</div>`;
    };

    const specialtyHtml = () => (data.specialties || []).map((row, index) => `
      <label><input type="checkbox" data-finora-field="doctor.specialty" data-staff-specialty value="${row.id}" ${index === 0 ? "checked" : ""}> ${esc(row.name)}</label>
    `).join("") || '<span class="cx-muted">أضف اختصاصاً أولاً من صفحة الاختصاصات.</span>';

    function formHtml(staffType, row = null) {
      const fp = row ? "staff" : staffType;
      const roleKey = row?.role_key && roleMap().has(row.role_key)
        ? row.role_key
        : staffType === "doctor" ? "clinic_doctor" : "clinic_reception";
      const selectedPermissions = row?.permissions || roleMap().get(roleKey)?.permissions || [];
      const doctorFields = !row && staffType === "doctor" ? `
        <section class="cx-staff-form-section">
          <h4>ربط سجل الطبيب</h4>
          <div class="cx-field"><label>طبيب موجود بدون حساب</label><select class="cx-select" id="staffDoctorId" data-finora-field="doctor.link"><option value="">إنشاء سجل طبي جديد</option>${(data.unlinked_doctors || []).map((doctor) => `<option value="${doctor.id}">${esc(doctor.name)}${doctor.specialty ? ` · ${esc(doctor.specialty)}` : ""}</option>`).join("")}</select></div>
          <div class="cx-field-row" data-new-doctor-fields>
            <div class="cx-field"><label>رقم الإجازة الطبية</label><input class="cx-input" id="staffLicense" data-finora-field="doctor.license"></div>
            <div class="cx-field"><label>اللقب العلمي</label><input class="cx-input" id="staffTitle" data-finora-field="doctor.title" placeholder="اختصاصي، استشاري..."></div>
          </div>
          <div class="cx-field" data-new-doctor-fields><label>الاختصاصات</label><div class="cx-check-grid" data-finora-section="doctor.specialties">${specialtyHtml()}</div></div>
        </section>` : "";
      return `
        <div class="cx-staff-form" data-finora-section="staff.form" data-finora-form="${fp}">
          <section class="cx-staff-form-section">
            <h4>بيانات الحساب</h4>
            <div class="cx-field-row">
              <div class="cx-field"><label>الاسم الكامل *</label><input class="cx-input" id="staffName" data-finora-field="${fp}.name" value="${esc(row?.name || "")}"></div>
              <div class="cx-field"><label>رقم الهاتف</label><input class="cx-input" id="staffPhone" data-finora-field="${fp}.phone" value="${esc(row?.phone || "")}"></div>
            </div>
            <div class="cx-field-row">
              <div class="cx-field"><label>اسم المستخدم *</label><input class="cx-input" id="staffUsername" data-finora-field="${fp}.username" autocomplete="off" value="${esc(row?.username || "")}"></div>
              <div class="cx-field"><label>${row ? "كلمة مرور جديدة (اختياري)" : "كلمة المرور *"}</label><input class="cx-input" id="staffPassword" data-finora-field="${fp}.password" type="password" autocomplete="new-password" minlength="6"></div>
            </div>
            <div class="cx-field-row">
              <div class="cx-field"><label>الدور الوظيفي</label><select class="cx-select" id="staffRole" data-finora-field="${fp}.role">${roleOptions(roleKey)}</select></div>
              <div class="cx-field"><label>الفرع</label><select class="cx-select" id="staffBranch" data-finora-field="${fp}.branch">${branchOptions(row?.branch_id)}</select></div>
            </div>
          </section>
          ${doctorFields}
          <section class="cx-staff-form-section">
            <div class="cx-staff-section-head"><div><h4>الصلاحيات</h4><small>يمكن تعديل صلاحيات الدور قبل الحفظ</small></div><button type="button" class="cx-btn cx-btn--sm" id="staffSelectPreset" data-finora-action="staff.role.apply">إعادة تطبيق الدور</button></div>
            <div id="staffPermissionBox" data-finora-section="${fp}.permissions">${permissionsHtml(selectedPermissions)}</div>
          </section>
        </div>`;
    }

    function bindForm(row = null) {
      const role = document.getElementById("staffRole");
      const applyPreset = () => {
        const selected = new Set(roleMap().get(role?.value)?.permissions || []);
        document.querySelectorAll("[data-staff-permission]").forEach((input) => {
          input.checked = selected.has(input.value);
        });
      };
      document.getElementById("staffSelectPreset")?.addEventListener("click", applyPreset);
      role?.addEventListener("change", applyPreset);
      const doctorSelect = document.getElementById("staffDoctorId");
      const toggleDoctorFields = () => document.querySelectorAll("[data-new-doctor-fields]").forEach((el) => {
        el.hidden = !!doctorSelect?.value;
      });
      doctorSelect?.addEventListener("change", toggleDoctorFields);
      toggleDoctorFields();
    }

    function readForm(staffType, row = null) {
      const password = document.getElementById("staffPassword")?.value || "";
      const specialtyIds = [...document.querySelectorAll("[data-staff-specialty]:checked")].map((input) => Number(input.value));
      return {
        staff_type: staffType,
        name: document.getElementById("staffName")?.value,
        username: document.getElementById("staffUsername")?.value,
        phone: document.getElementById("staffPhone")?.value,
        role_key: document.getElementById("staffRole")?.value,
        branch_id: document.getElementById("staffBranch")?.value || null,
        permissions: [...document.querySelectorAll("[data-staff-permission]:checked")].map((input) => input.value),
        ...(password ? { password } : {}),
        ...(!row && staffType === "doctor" ? {
          doctor_id: document.getElementById("staffDoctorId")?.value || null,
          license_number: document.getElementById("staffLicense")?.value || "",
          scientific_title: document.getElementById("staffTitle")?.value || "",
          specialty_ids: specialtyIds,
          primary_specialty_id: specialtyIds[0] || null,
        } : {}),
      };
    }

    function openCreate(staffType) {
      openModal(
        staffType === "doctor" ? "إضافة طبيب وإنشاء حساب دخول" : "إضافة موظف وإنشاء حساب دخول",
        formHtml(staffType),
        async () => {
          await api("/clinics/api/staff", { method: "POST", body: JSON.stringify(readForm(staffType)) });
        },
        { successMessage: "تم إنشاء الحساب وتطبيق الصلاحيات", finoraAction: `${staffType}.save` }
      );
      bindForm();
    }

    function openEdit(row) {
      openModal(
        `تعديل حساب — ${esc(row.name)}`,
        formHtml(row.doctor ? "doctor" : "employee", row),
        async () => {
          await api(`/clinics/api/staff/${row.id}`, { method: "PATCH", body: JSON.stringify(readForm(row.doctor ? "doctor" : "employee", row)) });
        },
        { successMessage: "تم تحديث الحساب والصلاحيات", finoraAction: "staff.save.edit" }
      );
      bindForm(row);
    }

    function filteredRows() {
      return (data.items || []).filter((row) => {
        if (view === "doctors" && !row.doctor) return false;
        if (view === "employees" && row.doctor) return false;
        const needle = query.trim().toLowerCase();
        return !needle || `${row.name} ${row.username} ${row.phone} ${row.role_label}`.toLowerCase().includes(needle);
      });
    }

    function paintRows() {
      const box = root.querySelector("#staffRows");
      const rows = filteredRows();
      box.innerHTML = rows.length ? rows.map((row) => `
        <article class="cx-staff-card ${row.active ? "" : "is-disabled"}">
          <div class="cx-staff-avatar"><i class="fa ${iconFor(row)}"></i></div>
          <div class="cx-staff-card__identity">
            <strong>${esc(row.name)}</strong>
            <small>@${esc(row.username)}${row.phone ? ` · ${esc(row.phone)}` : ""}</small>
          </div>
          <div><span class="cx-badge">${esc(row.role_label)}</span>${row.doctor ? '<span class="cx-badge cx-badge--done">طبيب مرتبط</span>' : ""}</div>
          <div class="cx-staff-card__permissions"><b>${row.permissions_count}</b><span>صلاحية</span></div>
          <span class="cx-badge cx-badge--${row.active ? "done" : "cancel"}">${row.active ? "فعال" : "معطل"}</span>
          <div class="cx-actions">
            ${row.doctor ? `<a class="cx-btn cx-btn--sm" href="/clinics/doctors/${row.doctor.id}">ملف الطبيب</a>` : ""}
            ${row.protected ? '<span class="cx-muted">حساب محمي</span>' : `<button class="cx-btn cx-btn--sm" data-edit-staff="${row.id}" data-finora-action="staff.edit">تعديل وصلاحيات</button><button class="cx-btn cx-btn--sm" data-toggle-staff="${row.id}">${row.active ? "تعطيل" : "تفعيل"}</button>`}
          </div>
        </article>`).join("") : '<div class="cx-empty">لا توجد حسابات مطابقة</div>';
      box.querySelectorAll("[data-edit-staff]").forEach((button) => {
        button.onclick = () => openEdit(data.items.find((row) => row.id === Number(button.dataset.editStaff)));
      });
      box.querySelectorAll("[data-toggle-staff]").forEach((button) => {
        button.onclick = async () => {
          const row = data.items.find((item) => item.id === Number(button.dataset.toggleStaff));
          if (!row || !window.confirm(`${row.active ? "تعطيل" : "تفعيل"} حساب ${row.name}؟`)) return;
          try {
            await api(`/clinics/api/staff/${row.id}`, { method: "PATCH", body: JSON.stringify({ active: !row.active }) });
            data = await api("/clinics/api/staff");
            paintRows();
            showNotice(`تم ${row.active ? "تعطيل" : "تفعيل"} الحساب`, false);
          } catch (error) {
            showNotice(error.message || String(error));
          }
        };
      });
    }

    root.innerHTML = `
      <section class="cx-hero"><div><div class="cx-kicker">إدارة العيادة</div><h1>الأطباء والموظفون</h1><p>حسابات الدخول، الأدوار والصلاحيات من مكان واحد.</p></div><div class="cx-actions"><button class="cx-btn cx-btn--primary" id="staffAddEmployee" data-finora-action="employee.create"><i class="fa fa-user-plus"></i> إضافة موظف</button><button class="cx-btn" id="staffAddDoctor" data-finora-action="doctor.create"><i class="fa fa-user-doctor"></i> إضافة طبيب وحساب</button></div></section>
      <section class="cx-kpi-grid">
        <article class="cx-kpi"><span>إجمالي الطاقم</span><strong>${data.stats.total}</strong></article>
        <article class="cx-kpi"><span>الحسابات الفعالة</span><strong>${data.stats.active}</strong></article>
        <article class="cx-kpi"><span>الأطباء المرتبطون</span><strong>${data.stats.doctors}</strong></article>
        <article class="cx-kpi"><span>موظفو الاستقبال</span><strong>${data.stats.reception}</strong></article>
      </section>
      <section class="cx-card" data-finora-section="staff.list">
        <div class="cx-staff-toolbar">
          <div class="cx-tabs"><button class="is-active" data-staff-view="all">الكل</button><button data-staff-view="doctors">الأطباء</button><button data-staff-view="employees">بقية الموظفين</button></div>
          <input class="cx-input" id="staffSearch" placeholder="بحث بالاسم أو اسم المستخدم أو الهاتف">
        </div>
        <div id="staffRows" class="cx-staff-list"></div>
      </section>`;

    root.querySelector("#staffAddEmployee").onclick = () => openCreate("employee");
    root.querySelector("#staffAddDoctor").onclick = () => openCreate("doctor");
    root.querySelector("#staffSearch").oninput = (event) => { query = event.target.value; paintRows(); };
    root.querySelectorAll("[data-staff-view]").forEach((button) => {
      button.onclick = () => {
        view = button.dataset.staffView;
        root.querySelectorAll("[data-staff-view]").forEach((item) => item.classList.toggle("is-active", item === button));
        paintRows();
      };
    });
    paintRows();
  }

  window.ClinicsStaff = { render };
})();
