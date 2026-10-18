(() => {
  const ui = { q: "", category: "", status: "", sort: "name", direction: "asc", page: 1, perPage: 25, timer: null };
  let cache = { items: [], filters: { categories: [], presets: [] }, kpis: {} };
  let floatingDismiss = null;

  function durationLabel(minutes) {
    const value = Number(minutes || 0);
    if (value >= 60 && value % 60 === 0) return `${value / 60} س`;
    return `${value} د`;
  }

  function closeMenu() {
    document.querySelector(".cxi-floating-menu")?.remove();
    if (floatingDismiss) document.removeEventListener("click", floatingDismiss);
    floatingDismiss = null;
  }

  function openMenu(trigger, items) {
    closeMenu();
    const menu = document.createElement("div");
    menu.className = "cxi-floating-menu";
    menu.innerHTML = items
      .map((item) => `<button type="button" data-act="${item.id}"><i class="fa fa-${item.icon}"></i><span>${item.label}</span></button>`)
      .join("");
    document.body.appendChild(menu);
    const rect = trigger.getBoundingClientRect();
    const w = 200;
    const h = menu.offsetHeight || 160;
    menu.style.top = `${Math.min(window.innerHeight - h - 8, rect.bottom + 6)}px`;
    menu.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, rect.right - w))}px`;
    menu.querySelectorAll("[data-act]").forEach((btn) => {
      btn.onclick = () => {
        closeMenu();
        items.find((x) => x.id === btn.dataset.act)?.onClick?.();
      };
    });
    window.setTimeout(() => {
      floatingDismiss = (event) => {
        if (!menu.contains(event.target) && !trigger.contains(event.target)) closeMenu();
      };
      document.addEventListener("click", floatingDismiss);
    }, 0);
  }

  function categoryOptions(esc, categories, presets, selected = "") {
    const merged = [...new Set([...(presets || []), ...(categories || [])])];
    return `<option value="">كل التصنيفات</option>${merged
      .map((value) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`)
      .join("")}`;
  }

  function serviceFormHtml(esc, service = {}, presets = [], bootstrap = {}) {
    const isEdit = Boolean(service.id);
    const categoryList = [...new Set([...(presets || []), service.category].filter(Boolean))];
    const selectedSpecs = new Set((service.specialty_ids || []).map(String));
    const selectedDocs = new Set((service.doctor_ids || []).map(String));
    const specialties = (bootstrap.specialties || []).filter((s) => s.is_active !== false);
    const doctors = (bootstrap.doctors || []).filter((d) => d.active !== false);

    const specialtyChips = specialties.length
      ? specialties
          .map(
            (s) => `<label class="cx-svc-chip">
              <input type="checkbox" data-svc-specialty="${s.id}" data-finora-field="service.specialty" ${selectedSpecs.has(String(s.id)) ? "checked" : ""}>
              <span>${esc(s.name_ar)}</span>
            </label>`
          )
          .join("")
      : `<div class="cx-empty" style="padding:8px">لا توجد اختصاصات — أضفها من شاشة الاختصاصات</div>`;

    const doctorChips = doctors.length
      ? doctors
          .map(
            (d) => `<label class="cx-svc-chip" data-doctor-chip data-specialty-ids="${esc((d.specialty_ids || []).join(","))}">
              <input type="checkbox" data-svc-doctor="${d.id}" ${selectedDocs.has(String(d.id)) ? "checked" : ""}>
              <span>${esc(d.full_name)}</span>
            </label>`
          )
          .join("")
      : `<div class="cx-empty" style="padding:8px">لا يوجد أطباء بعد</div>`;

    return `
      <div class="cx-svc-form" data-finora-section="service.form">
        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head">
            <strong>1) بيانات الخدمة</strong>
            <span>الاسم والسعر والمدة</span>
          </div>
          <div class="cx-field"><label>اسم الخدمة *</label><input class="cx-input" id="svc_name" data-finora-field="service.name" value="${esc(service.name || "")}" required placeholder="مثال: كشف عام، CBC، تنظيف أسنان"></div>
          <div class="cx-field-row">
            <div class="cx-field"><label>التصنيف</label>
              <input class="cx-input" id="svc_cat" data-finora-field="service.category" list="svc_cat_list" value="${esc(service.category || "")}" placeholder="كشف · إجراء · متابعة · تحليل">
              <datalist id="svc_cat_list">${categoryList.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
            </div>
            <div class="cx-field"><label>المدة (دقيقة) *</label><input class="cx-input" id="svc_dur" data-finora-field="service.duration" type="number" min="5" step="5" value="${service.duration_minutes || 15}"></div>
          </div>
          <div class="cx-field-row">
            <div class="cx-field"><label>السعر (د.ع) *</label><input class="cx-input" id="svc_price" data-finora-field="service.price" type="number" min="0" step="1000" value="${service.price ?? 0}"></div>
            <div class="cx-field"><label>عمولة الطبيب %</label><input class="cx-input" id="svc_comm" data-finora-field="service.commission" type="number" min="0" max="100" step="0.5" value="${service.doctor_commission_pct ?? ""}" placeholder="اختياري"></div>
          </div>
          <div class="cx-field"><label>الوصف</label><textarea class="cx-textarea" id="svc_desc" data-finora-field="service.description" rows="2" placeholder="ملاحظات داخلية أو وصف للحجز الإلكتروني">${esc(service.description || "")}</textarea></div>
        </section>

        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head">
            <strong>2) النطاق</strong>
            <span>لمن تظهر هذه الخدمة؟</span>
          </div>
          <div class="cx-field">
            <label>الاختصاصات <small class="cx-svc-req">مطلوب للظهور في الموعد</small></label>
            <div class="cx-svc-chip-grid" id="svc_specialties_grid" data-finora-section="service.specialties">${specialtyChips}</div>
            <small class="cx-svc-hint">اختر اختصاصاً واحداً أو أكثر. بدون ربط لن تظهر الخدمة عند حجز ذلك الاختصاص.</small>
          </div>
          <div class="cx-field">
            <label>الأطباء <small>(اختياري — بدون اختيار = كل أطباء الاختصاص)</small></label>
            <div class="cx-svc-chip-grid" id="svc_doctors_grid" data-finora-section="service.doctors">${doctorChips}</div>
          </div>
        </section>

        <section class="cx-svc-form__section">
          <div class="cx-svc-form__head">
            <strong>3) خيارات إضافية</strong>
            <span>الغرفة · الأسنان · الجلسات</span>
          </div>
          <div class="cx-svc-option-grid" data-finora-section="service.options">
            <label class="cx-svc-option"><input type="checkbox" id="svc_room" ${service.requires_room ? "checked" : ""}><span><b>تتطلب غرفة</b><small>حجز غرفة معاينة</small></span></label>
            <label class="cx-svc-option"><input type="checkbox" id="svc_tooth" ${service.requires_tooth ? "checked" : ""}><span><b>تتطلب سناً</b><small>للخدمات السنية</small></span></label>
            <label class="cx-svc-option"><input type="checkbox" id="svc_multi_tooth" ${service.allows_multiple_teeth ? "checked" : ""}><span><b>عدة أسنان</b><small>أكثر من سن في الجلسة</small></span></label>
            <label class="cx-svc-option"><input type="checkbox" id="svc_sessions" ${service.requires_sessions ? "checked" : ""}><span><b>تتطلب جلسات</b><small>خطة علاج متعددة</small></span></label>
            ${isEdit ? `<label class="cx-svc-option"><input type="checkbox" id="svc_active" ${service.active !== false ? "checked" : ""}><span><b>نشطة</b><small>متاحة للحجز والاستخدام</small></span></label>` : ""}
          </div>
          <div class="cx-field" id="svc_sessions_wrap" ${service.requires_sessions ? "" : "hidden"}>
            <label>عدد الجلسات الافتراضي</label>
            <input class="cx-input" id="svc_default_sessions" type="number" min="1" value="${service.default_sessions || 1}">
          </div>
        </section>
      </div>`;
  }

  function readServicePayload(isEdit) {
    const name = document.getElementById("svc_name").value.trim();
    if (!name) throw new Error("اسم الخدمة مطلوب");
    const duration = Number(document.getElementById("svc_dur").value || 15);
    if (Number.isNaN(duration) || duration < 5) throw new Error("المدة يجب أن تكون 5 دقائق على الأقل");
    const price = Number(document.getElementById("svc_price").value || 0);
    if (Number.isNaN(price) || price < 0) throw new Error("السعر غير صالح");
    const commRaw = document.getElementById("svc_comm").value;
    let doctor_commission_pct = null;
    if (commRaw !== "") {
      doctor_commission_pct = Number(commRaw);
      if (Number.isNaN(doctor_commission_pct) || doctor_commission_pct < 0 || doctor_commission_pct > 100) {
        throw new Error("نسبة العمولة يجب أن تكون بين 0 و 100");
      }
    }
    const specialty_ids = Array.from(document.querySelectorAll("[data-svc-specialty]:checked"), (el) => Number(el.dataset.svcSpecialty));
    const doctor_ids = Array.from(document.querySelectorAll("[data-svc-doctor]:checked"), (el) => Number(el.dataset.svcDoctor));
    if (!specialty_ids.length) {
      throw new Error("اربط الخدمة باختصاص واحد على الأقل حتى تظهر في الموعد");
    }
    const payload = {
      specialty_ids,
      doctor_ids,
      name,
      category: document.getElementById("svc_cat").value.trim(),
      duration_minutes: duration,
      price,
      doctor_commission_pct,
      requires_room: document.getElementById("svc_room").checked,
      requires_tooth: document.getElementById("svc_tooth").checked,
      allows_multiple_teeth: document.getElementById("svc_multi_tooth").checked,
      requires_sessions: document.getElementById("svc_sessions").checked,
      default_sessions: Number(document.getElementById("svc_default_sessions").value || 1),
      description: document.getElementById("svc_desc").value.trim(),
    };
    if (isEdit) payload.active = document.getElementById("svc_active").checked;
    return payload;
  }

  function bindServiceFormUi() {
    const sessions = document.getElementById("svc_sessions");
    const sessionsWrap = document.getElementById("svc_sessions_wrap");
    if (sessions && sessionsWrap) {
      sessions.onchange = () => {
        sessionsWrap.hidden = !sessions.checked;
      };
    }
    const tooth = document.getElementById("svc_tooth");
    const multi = document.getElementById("svc_multi_tooth");
    if (tooth && multi) {
      const syncTooth = () => {
        if (!tooth.checked) multi.checked = false;
        multi.disabled = !tooth.checked;
      };
      tooth.onchange = syncTooth;
      syncTooth();
    }

    const filterDoctorsBySpecialty = () => {
      const selected = new Set(
        Array.from(document.querySelectorAll("[data-svc-specialty]:checked"), (el) => String(el.dataset.svcSpecialty))
      );
      document.querySelectorAll("[data-doctor-chip]").forEach((chip) => {
        const ids = String(chip.dataset.specialtyIds || "")
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
        const match = !selected.size || !ids.length || ids.some((id) => selected.has(id));
        chip.hidden = !match;
        if (!match) {
          const input = chip.querySelector("input");
          if (input) input.checked = false;
        }
      });
    };
    document.querySelectorAll("[data-svc-specialty]").forEach((el) => {
      el.addEventListener("change", filterDoctorsBySpecialty);
    });
    filterDoctorsBySpecialty();
  }

  function openServiceModal(service, ctx, options = {}) {
    const isEdit = Boolean(service?.id);
    ctx.openModal(
      isEdit ? "تعديل خدمة" : "خدمة جديدة",
      serviceFormHtml(ctx.esc, service || {}, cache.filters.presets, ctx.state?.bootstrap || {}),
      async () => {
        const payload = readServicePayload(isEdit);
        if (isEdit) {
          await ctx.api(`/clinics/api/services/${service.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        } else {
          await ctx.api("/clinics/api/services", { method: "POST", body: JSON.stringify(payload) });
        }
      },
      { successMessage: isEdit ? "تم تحديث الخدمة" : "تمت إضافة الخدمة", finoraAction: isEdit ? "service.save.edit" : "service.save", ...options }
    );
    bindServiceFormUi();
  }

  async function toggleServiceActive(service, ctx) {
    const next = service.active === false;
    const label = next ? "تفعيل" : "إيقاف";
    if (!window.confirm(`${label} خدمة «${service.name}»؟`)) return;
    await ctx.api(`/clinics/api/services/${service.id}`, {
      method: "PATCH",
      body: JSON.stringify({ active: next }),
    });
    ctx.showNotice(next ? "تم تفعيل الخدمة" : "تم إيقاف الخدمة", false);
    await loadServices(ctx);
  }

  async function duplicateService(service, ctx) {
    openServiceModal(
      {
        ...service,
        id: null,
        name: `${service.name} (نسخة)`,
        active: true,
      },
      ctx
    );
  }

  async function seedTemplate(ctx) {
    const result = await ctx.api("/clinics/api/specialty/seed", {
      method: "POST",
      body: JSON.stringify({}),
    });
    ctx.showNotice(
      `تم تجهيز الاختصاصات: ${(result.specialties || []).length} اختصاص`,
      false
    );
    if (ctx.state) ctx.state.bootstrap = await ctx.api("/clinics/api/bootstrap");
    await loadServices(ctx);
  }

  function renderShell(ctx) {
    ctx.root.innerHTML = `
      <section class="cx-doc-head cx-svc-head">
        <div>
          <div class="cx-kicker">Service Catalog</div>
          <h1>الخدمات</h1>
          <p>أسعار ومدد الخدمات الطبية — تُستخدم في المواعيد والزيارات والفواتير والحجز الإلكتروني.</p>
        </div>
        <div class="cx-actions cx-svc-head__actions">
          <button type="button" class="cx-btn" id="svcSeed"><i class="fa fa-wand-magic-sparkles"></i> قالب تخصص</button>
          <button type="button" class="cx-btn cx-btn--primary" id="svcAdd" data-finora-action="service.create"><i class="fa fa-plus"></i> خدمة جديدة</button>
        </div>
      </section>
      <div class="cx-doc-search cx-svc-search"><i class="fa fa-magnifying-glass"></i><input id="svcSearch" placeholder="ابحث بالاسم، التصنيف، أو الوصف..." autocomplete="off"></div>
      <div class="cx-doc-filters cx-svc-filters">
        <select id="svcCategory"><option value="">كل التصنيفات</option></select>
        <select id="svcStatus">
          <option value="">كل الحالات</option>
          <option value="active">نشطة</option>
          <option value="inactive">موقوفة</option>
        </select>
        <select id="svcSort">
          <option value="name">ترتيب: الاسم</option>
          <option value="price">ترتيب: السعر</option>
          <option value="duration">ترتيب: المدة</option>
          <option value="usage">ترتيب: الاستخدام</option>
          <option value="category">ترتيب: التصنيف</option>
        </select>
        <button type="button" class="cx-btn cx-btn--sm" id="svcSortDir" title="عكس الترتيب"><i class="fa fa-arrow-down-wide-short"></i></button>
      </div>
      <div class="cx-doc-kpis cx-svc-kpis" id="svcKpis"></div>
      <article class="cx-card cx-doc-table-card cx-svc-table-card">
        <div class="cx-table-wrap"><table class="cx-table cx-svc-table">
          <thead><tr>
            <th>الخدمة</th><th>التصنيف</th><th>المدة</th><th>السعر</th><th>عمولة</th><th>غرفة</th><th>الاستخدام</th><th>الحالة</th><th></th>
          </tr></thead>
          <tbody id="svcRows"><tr><td colspan="9"><div class="cx-empty cx-doc-empty"><i class="fa fa-hand-holding-medical"></i><b>جارٍ التحميل...</b></div></td></tr></tbody>
        </table></div>
        <div class="cx-doc-pager" id="svcPager"></div>
      </article>`;
  }

  function renderKpis(kpis, money) {
    const cards = [
      ["إجمالي الخدمات", kpis.total, "list"],
      ["نشطة", kpis.active, "circle-check"],
      ["موقوفة", kpis.inactive, "ban"],
      ["تصنيفات", kpis.categories, "tags"],
      ["متوسط السعر", money(kpis.avg_price), "coins"],
      ["متوسط المدة", `${kpis.avg_duration || 0} د`, "clock"],
    ];
    document.getElementById("svcKpis").innerHTML = cards
      .map(([label, value, icon]) => `<div><i class="fa fa-${icon}"></i><span>${label}</span><strong>${value}</strong></div>`)
      .join("");
  }

  function renderRows(data, ctx) {
    const { esc, money } = ctx;
    const statusClass = (active) => (active !== false ? "ok" : "muted");
    document.getElementById("svcRows").innerHTML = (data.items || [])
      .map(
        (s) => `
      <tr data-service="${s.id}" class="${s.active === false ? "cx-svc-row--inactive" : ""}">
        <td>
          <div class="cx-svc-name">
            <strong>${esc(s.name)}</strong>
            ${s.description ? `<small>${esc(s.description)}</small>` : ""}
          </div>
        </td>
        <td>${s.category ? `<span class="cx-svc-cat">${esc(s.category)}</span>` : "—"}</td>
        <td class="cx-svc-duration">${durationLabel(s.duration_minutes)}</td>
        <td class="cx-money">${money(s.price)}</td>
        <td>${s.doctor_commission_pct != null ? `${s.doctor_commission_pct}%` : "—"}</td>
        <td>${s.requires_room ? '<span class="cx-badge cx-badge--in">نعم</span>' : "—"}</td>
        <td><span class="cx-svc-usage" title="مواعيد / زيارات">${s.total_usage || 0}<small>${s.appointments || 0} · ${s.visits || 0}</small></span></td>
        <td><span class="cx-doc-status cx-doc-status--${statusClass(s.active)}">${s.active !== false ? "نشطة" : "موقوفة"}</span></td>
        <td class="cx-doc-actions-cell">
          <button type="button" class="cx-btn cx-btn--sm" data-edit="${s.id}">تعديل</button>
          <button type="button" class="cxi-menu-trigger" data-menu="${s.id}" aria-label="إجراءات"><i class="fa fa-ellipsis"></i></button>
        </td>
      </tr>`
      )
      .join("") ||
      `<tr><td colspan="9"><div class="cx-empty cx-doc-empty"><i class="fa fa-hand-holding-medical"></i><b>لا توجد خدمات مطابقة</b><span>أضف خدمة جديدة أو غيّر معايير البحث.</span></div></td></tr>`;

    const pager = data.pagination || { page: 1, pages: 1, total: 0 };
    document.getElementById("svcPager").innerHTML = `<span>${pager.total} خدمة</span><div>
      <button class="cx-btn cx-btn--sm" id="svcPrev" ${pager.page <= 1 ? "disabled" : ""}>السابق</button>
      <b>${pager.page} / ${pager.pages}</b>
      <button class="cx-btn cx-btn--sm" id="svcNext" ${pager.page >= pager.pages ? "disabled" : ""}>التالي</button>
    </div>`;

    document.getElementById("svcPrev").onclick = () => {
      ui.page -= 1;
      loadServices(ctx);
    };
    document.getElementById("svcNext").onclick = () => {
      ui.page += 1;
      loadServices(ctx);
    };

    document.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.onclick = (event) => {
        event.stopPropagation();
        const service = cache.items.find((row) => row.id === Number(btn.dataset.edit));
        if (service) openServiceModal(service, ctx);
      };
    });

    document.querySelectorAll("[data-menu]").forEach((btn) => {
      btn.onclick = (event) => {
        event.stopPropagation();
        const service = cache.items.find((row) => row.id === Number(btn.dataset.menu));
        if (!service) return;
        openMenu(btn, [
          { id: "edit", icon: "pen", label: "تعديل", onClick: () => openServiceModal(service, ctx) },
          { id: "dup", icon: "copy", label: "نسخ", onClick: () => duplicateService(service, ctx) },
          {
            id: "toggle",
            icon: service.active === false ? "circle-check" : "ban",
            label: service.active === false ? "تفعيل" : "إيقاف",
            onClick: () => toggleServiceActive(service, ctx),
          },
        ]);
      };
    });
  }

  async function loadServices(ctx) {
    const query = new URLSearchParams(
      Object.entries({
        center: "1",
        q: ui.q,
        category: ui.category,
        status: ui.status,
        sort: ui.sort,
        direction: ui.direction,
        page: ui.page,
        per_page: ui.perPage,
      }).filter(([, value]) => value !== "")
    );
    const data = await ctx.api(`/clinics/api/services?${query}`);
    cache = data;
    renderKpis(data.kpis || {}, ctx.money);
    renderRows(data, ctx);

    const categorySelect = document.getElementById("svcCategory");
    if (categorySelect && categorySelect.options.length <= 1) {
      categorySelect.innerHTML = categoryOptions(ctx.esc, data.filters?.categories, data.filters?.presets, ui.category);
    }
  }

  function bindEvents(ctx) {
    document.getElementById("svcAdd").onclick = () => openServiceModal(null, ctx);
    document.getElementById("svcSeed").onclick = () => {
      if (window.confirm("تجهيز الاختصاصات الافتراضية ونماذج الزيارة؟\nلن تُكرَّر الاختصاصات الموجودة.")) {
        seedTemplate(ctx).catch((err) => ctx.showNotice(err.message || String(err)));
      }
    };

    const searchInput = document.getElementById("svcSearch");
    searchInput.value = ui.q;
    searchInput.oninput = (event) => {
      clearTimeout(ui.timer);
      ui.timer = setTimeout(() => {
        ui.q = event.target.value.trim();
        ui.page = 1;
        loadServices(ctx).catch((err) => ctx.showNotice(err.message || String(err)));
      }, 350);
    };

    document.getElementById("svcCategory").onchange = (event) => {
      ui.category = event.target.value;
      ui.page = 1;
      loadServices(ctx).catch((err) => ctx.showNotice(err.message || String(err)));
    };
    document.getElementById("svcStatus").value = ui.status;
    document.getElementById("svcStatus").onchange = (event) => {
      ui.status = event.target.value;
      ui.page = 1;
      loadServices(ctx).catch((err) => ctx.showNotice(err.message || String(err)));
    };
    document.getElementById("svcSort").value = ui.sort;
    document.getElementById("svcSort").onchange = (event) => {
      ui.sort = event.target.value;
      ui.page = 1;
      loadServices(ctx).catch((err) => ctx.showNotice(err.message || String(err)));
    };
    document.getElementById("svcSortDir").onclick = () => {
      ui.direction = ui.direction === "asc" ? "desc" : "asc";
      ui.page = 1;
      loadServices(ctx).catch((err) => ctx.showNotice(err.message || String(err)));
    };
  }

  async function renderServices(state, root, ctx) {
    if (state) state.bootstrap = await ctx.api("/clinics/api/bootstrap");
    renderShell({ ...ctx, root, state });
    bindEvents({ ...ctx, root, state });
    await loadServices({ ...ctx, root, state });
  }

  window.ClinicsServices = { renderServices };
})();
