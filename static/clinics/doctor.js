/* Finora Clinics — Doctor Workspace Phase 1
 * Orchestration UI over existing visit / clinical APIs.
 * Phase 2 hooks: saveDraft, markDirty, sectionRegistry, getVisitVersion.
 */
(() => {
  const SECTION_IDS = [
    "complaint", "history", "vitals", "exam", "diagnosis", "plan",
    "rx", "labs", "radiology", "procedures", "followup", "attachments", "notes",
  ];

  const controller = {
    dirty: false,
    visitVersion: null,
    markDirty() {
      this.dirty = true;
    },
    getVisitVersion() {
      return this.visitVersion;
    },
    async onBeforeComplete() {
      await flushAutosave();
      if (this.dirty) {
        const proceedDirty = window.confirm("توجد تعديلات غير محفوظة. المتابعة رغم ذلك؟");
        if (!proceedDirty) return false;
      }
      if (activeVisitId && activeCtx?.api) {
        try {
          const preflight = await activeCtx.api(`/clinics/api/visits/${activeVisitId}/dental-complete-preflight`);
          if (preflight?.warnings?.length) {
            return window.confirm(`${preflight.warnings.join("\n")}\n\nإنهاء الزيارة الآن؟`);
          }
        } catch (_) {
          /* preflight is advisory */
        }
      }
      return true;
    },
  };

  const sectionRegistry = Object.fromEntries(SECTION_IDS.map((id) => [id, { id, dirty: false }]));

  let timerHandle = null;
  let clockHandle = null;
  let queuePollHandle = null;
  let activeCtx = null;
  let activeVisitId = null;
  let autosaveTimer = null;
  let autosavePromise = Promise.resolve();

  function setSaveState(state, text) {
    const hint = document.getElementById("cxWsSaveHint");
    if (!hint) return;
    hint.hidden = false;
    hint.dataset.state = state;
    hint.textContent = text;
  }

  function currentDraftPayload() {
    return {
      chief_complaint: document.getElementById("v_cc")?.value || "",
      clinical_notes: document.getElementById("v_notes")?.value || "",
      follow_up_date: document.getElementById("v_fu")?.value || "",
    };
  }

  async function persistDraft(ctx, visitId, manual = false) {
    if (!ctx || !visitId || !document.getElementById("v_cc")) return;
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
    const payload = currentDraftPayload();
    const snapshot = JSON.stringify(payload);
    setSaveState("saving", "جاري الحفظ…");
    autosavePromise = autosavePromise.catch(() => {}).then(async () => {
      await ctx.api(`/clinics/api/visits/${visitId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      controller.dirty = JSON.stringify(currentDraftPayload()) !== snapshot;
      setSaveState("saved", `تم الحفظ · ${new Date().toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" })}`);
      if (manual) ctx.showNotice("تم حفظ المسودة", false);
      return true;
    }).catch((error) => {
      controller.dirty = true;
      setSaveState("failed", "فشل الحفظ — أعد المحاولة");
      if (manual) ctx.showNotice(error.message || String(error));
      throw error;
    });
    return autosavePromise;
  }

  function scheduleAutosave(ctx, visitId) {
    controller.markDirty();
    setSaveState("saving", "جاري الحفظ…");
    if (autosaveTimer) clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => {
      autosaveTimer = null;
      persistDraft(ctx, visitId).catch(() => {});
    }, 700);
  }

  async function flushAutosave() {
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
    if (controller.dirty && activeCtx && activeVisitId) {
      await persistDraft(activeCtx, activeVisitId);
    } else {
      await autosavePromise.catch(() => {});
    }
  }

  function clearTimers() {
    if (timerHandle) {
      clearInterval(timerHandle);
      timerHandle = null;
    }
    if (clockHandle) {
      clearInterval(clockHandle);
      clockHandle = null;
    }
    if (queuePollHandle) {
      clearInterval(queuePollHandle);
      queuePollHandle = null;
    }
    if (autosaveTimer) {
      clearTimeout(autosaveTimer);
      autosaveTimer = null;
    }
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "—";
    }
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleDateString("ar-IQ", { day: "numeric", month: "short", year: "numeric" });
    } catch {
      return iso;
    }
  }

  function elapsedLabel(startedAt) {
    if (!startedAt) return "—";
    const start = new Date(startedAt).getTime();
    if (Number.isNaN(start)) return "—";
    const mins = Math.max(0, Math.floor((Date.now() - start) / 60000));
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    if (h > 0) return `${h}س ${m}د`;
    return `${m} دقيقة`;
  }

  function bindTimer(startedAt, el) {
    if (!el) return;
    const tick = () => {
      el.textContent = elapsedLabel(startedAt);
    };
    tick();
    if (timerHandle) clearInterval(timerHandle);
    timerHandle = setInterval(tick, 30000);
  }

  function genderLabel(g) {
    const s = String(g || "").toLowerCase();
    if (s === "male" || s === "m" || s === "ذكر") return "ذكر";
    if (s === "female" || s === "f" || s === "أنثى" || s === "انثى") return "أنثى";
    return g || "—";
  }

  function initials(name) {
    const parts = String(name || "م").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "م";
    return ((parts[0][0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] || "" : "")).toUpperCase();
  }

  function clockNow() {
    return new Date().toLocaleString("ar-IQ", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  async function fetchWorkspace(api) {
    return api("/clinics/api/doctor/workspace").catch(() => ({
      current_visit: null,
      next_patient: null,
      waiting_queue: [],
      doctor: null,
    }));
  }

  function queuePanelHtml(ctx, board, v, clinical, isOpen) {
    const { esc } = ctx;
    const next = board.next_patient;
    const waiting = board.waiting_queue || [];
    const patient = clinical?.patient || {};
    const age = patient.age != null ? `${patient.age} سنة` : "";
    const phone = v.patient_phone || patient.phone || "";
    const allergies = v.allergies || patient.allergies || "";
    return `
      <aside class="cx-ws-queue" aria-label="طابور الطبيب">
        <article class="cx-ws-card cx-ws-card--current">
          <div class="cx-ws-card__label">المريض الحالي</div>
          <div class="cx-ws-patient">
            <span class="cx-ws-avatar" aria-hidden="true">${esc(initials(v.patient_name))}</span>
            <div>
              <strong>${esc(v.patient_name || "—")}</strong>
              <small>${esc(v.patient_file || "")}${age ? ` · ${esc(age)}` : ""} · ${esc(genderLabel(patient.gender))}</small>
            </div>
          </div>
          ${phone ? `<a class="cx-ws-phone" href="tel:${esc(phone)}" dir="ltr"><i class="fa fa-phone"></i> ${esc(phone)}</a>` : ""}
          ${allergies ? `<div class="cx-ws-alert" role="alert"><i class="fa fa-triangle-exclamation" aria-hidden="true"></i><div><strong>حساسية دوائية</strong><span>${esc(allergies)}</span></div></div>` : ""}
          <div class="cx-ws-timer">
            <div><span>وقت الدخول</span><strong>${esc(fmtTime(v.started_at))}</strong></div>
            <div><span>مدة المعاينة</span><strong id="cxWsTimer">${esc(elapsedLabel(v.started_at))}</strong></div>
            <div><span>الزيارة</span><strong>VIS-${esc(String(v.id).padStart(5, "0"))}</strong></div>
          </div>
          ${v.patient_id ? `<a class="cx-ws-file-link" href="/clinics/patients/${v.patient_id}">فتح الملف الكامل</a>` : ""}
        </article>
        <article class="cx-ws-card cx-ws-card--next">
          <div class="cx-ws-card__label">التالي في الانتظار</div>
          ${next ? `
            <strong>${esc(next.patient_name)}</strong>
            <small>${esc(next.patient_file || "")} · ${esc(next.start_time || "—")}</small>
            <p class="cx-ws-muted">${next.wait_minutes != null ? `ينتظر ${next.wait_minutes} د` : "في الانتظار"} · ${esc(next.status === "arrived" ? "وصل" : "لم يصل بعد")}</p>
          ` : `<p class="cx-ws-muted">لا يوجد مريض تالٍ</p>`}
        </article>
        <article class="cx-ws-card cx-ws-card--queue">
          <div class="cx-ws-card__label">قائمة اليوم <em>${waiting.length}</em></div>
          <ol class="cx-ws-queue-list">
            ${waiting.slice(0, 8).map((a, i) => `
              <li>
                <span class="cx-ws-qnum">${i + 1}</span>
                <div>
                  <strong>${esc(a.patient_name)}</strong>
                  <small>${esc(a.start_time || "—")} · ${esc(a.patient_file || "")}</small>
                </div>
              </li>`).join("") || `<li class="cx-ws-muted">لا مرضى بانتظار</li>`}
          </ol>
          <a class="cx-ws-file-link" href="/clinics/queue">عرض قائمة الانتظار</a>
        </article>
      </aside>`;
  }

  function contextPanelHtml(ctx, v, clinical) {
    const { esc } = ctx;
    const patient = clinical?.patient || {};
    const allergies = v.allergies || patient.allergies || "";
    const chronic = v.chronic_conditions || patient.chronic_conditions || "";
    const rx = clinical?.prescriptions || [];
    const visits = (clinical?.section === "visits" ? clinical.items : null) || [];
    const lastLab = clinical?.last_lab;
    const lastRad = clinical?.last_radiology;
    const dx = clinical?.diagnoses || [];
    return `
      <aside class="cx-ws-context" aria-label="السجل السريري">
        <article class="cx-ws-card cx-ws-card--file">
          <div class="cx-ws-context-head">
            <strong>السجل السريري</strong>
            ${v.patient_id ? `<a class="cx-ws-file-link" href="/clinics/patients/${v.patient_id}">الملف الكامل</a>` : ""}
          </div>
          <nav class="cx-ws-context-tabs" aria-label="أقسام السجل">
            <button type="button" class="is-active" data-ctx-tab="summary">الملخص</button>
            <button type="button" data-ctx-tab="visits">الزيارات</button>
            <button type="button" data-ctx-tab="meds">الأدوية</button>
            <button type="button" data-ctx-tab="labs">تحاليل</button>
            <button type="button" data-ctx-tab="rad">أشعة</button>
          </nav>
          <div class="cx-ws-context-panel" data-ctx-panel="summary">
            ${allergies ? `<div class="cx-ws-alert cx-ws-alert--compact" role="alert"><i class="fa fa-triangle-exclamation"></i><span>${esc(allergies)}</span></div>` : ""}
            ${chronic ? `<p class="cx-ws-chip-row">${String(chronic).split(/[,،]/).filter(Boolean).map((c) => `<span class="cx-ws-chip">${esc(c.trim())}</span>`).join("")}</p>` : `<p class="cx-ws-muted">لا أمراض مزمنة مسجّلة</p>`}
            <div class="cx-ws-summary-tiles">
              <div><span>أمراض مزمنة</span><strong>${chronic ? "مسجّل" : "—"}</strong></div>
              <div><span>آخر تحليل</span><strong>${esc(lastLab?.items?.[0]?.name || lastLab?.status || "—")}</strong></div>
              <div><span>آخر أشعة</span><strong>${esc(lastRad?.modality || "—")}</strong></div>
              <div><span>تشخيصات</span><strong>${dx.length || 0}</strong></div>
            </div>
            <div id="cxWsActiveTreatments"></div>
          </div>
          <div class="cx-ws-context-panel" data-ctx-panel="visits" hidden>
            <div class="cx-ws-feed" id="cxWsPrevVisits">
              ${(visits.length ? visits : []).slice(0, 6).map((x) => `
                <button type="button" class="cx-ws-feed__item" data-prev-visit="${x.id}">
                  <strong>${esc(fmtDate(x.visit_date || x.started_at))}</strong>
                  <small>${esc(x.doctor_name || "—")} · ${esc(x.chief_complaint || "زيارة")}</small>
                </button>`).join("") || `<p class="cx-ws-muted">لا زيارات سابقة</p>`}
            </div>
          </div>
          <div class="cx-ws-context-panel" data-ctx-panel="meds" hidden>
            <div class="cx-ws-feed">
              ${rx.flatMap((p) => (p.items || []).map((i) => `
                <div class="cx-ws-feed__item"><strong>${esc(i.medicine_name)}</strong><small>${esc(i.dosage)} · ${esc(i.frequency)}</small></div>
              `)).join("") || `<p class="cx-ws-muted">لا أدوية مسجّلة</p>`}
            </div>
          </div>
          <div class="cx-ws-context-panel" data-ctx-panel="labs" hidden>
            ${lastLab ? `<div class="cx-ws-feed__item"><strong>${esc(lastLab.items?.[0]?.name || "تحليل")}</strong><small>${esc(lastLab.status || "")} · ${esc(fmtDate(lastLab.ordered_at || lastLab.created_at))}</small></div>` : `<p class="cx-ws-muted">لا تحاليل سابقة</p>`}
          </div>
          <div class="cx-ws-context-panel" data-ctx-panel="rad" hidden>
            ${lastRad ? `<div class="cx-ws-feed__item"><strong>${esc(lastRad.modality || "أشعة")}</strong><small>${esc(lastRad.status || "")} · ${esc(fmtDate(lastRad.ordered_at || lastRad.created_at))}</small></div>` : `<p class="cx-ws-muted">لا أشعة سابقة</p>`}
          </div>
        </article>
      </aside>`;
  }

  function vitalsStrip(vitals, esc) {
    const cells = [
      ["ضغط الدم", vitals.blood_pressure || "—", ""],
      ["نبض", vitals.heart_rate ?? "—", "bpm"],
      ["حرارة", vitals.temperature ?? "—", "°C"],
      ["SpO2", vitals.oxygen_sat ?? "—", "%"],
      ["وزن", vitals.weight_kg ?? "—", "كغ"],
      ["طول", vitals.height_cm ?? "—", "سم"],
      ["BMI", vitals.bmi ?? "—", ""],
    ];
    return `<div class="cx-ws-vitals">${cells.map(([l, val, u]) => `
      <div><span>${l}</span><strong>${esc(val)}${u && val !== "—" ? ` <small>${u}</small>` : ""}</strong></div>
    `).join("")}</div>`;
  }

  function specialtyPack(code) {
    return window.ClinicsSpecialtyWorkspace?.resolve?.(code) || {
      name_ar: "معاينة عامة",
      complaintPlaceholder: "اكتب الشكوى الرئيسية…",
      complaintChips: [],
      examPlaceholder: "سجّل موجودات الفحص السريري…",
      examHints: [],
      historyNote: "راجع الأمراض المزمنة والحساسيات من العمود الجانبي.",
      commonDiagnoses: [],
      suggestedLabs: [],
      suggestedRad: [],
      followupDefault: "14",
      toolTabs: [],
    };
  }

  function mainWorkspaceHtml(ctx, data, billPreview, rxTemplates, isOpen) {
    const { esc, money, specialtyFieldHtml } = ctx;
    const v = data.visit;
    const vitals = data.vitals?.[0] || {};
    const specialtyTemplate = data.template;
    const specCode = data.specialty?.code || "";
    const pack = specialtyPack(specCode);
    const isDental = specCode === "dentistry";
    const dentalFeatures = data.specialty_context?.features || {};
    const featureOn = (key) => dentalFeatures[key] !== false;
    const chipApi = window.ClinicsSpecialtyWorkspace;
    const disabledAttr = isOpen ? "" : "disabled";
    const complaintChips = chipApi?.chipRow?.(pack.complaintChips, `${disabledAttr} data-ws-append="#v_cc"`, esc) || "";
    const examChips = chipApi?.chipRow?.(pack.examHints, `${disabledAttr} data-ws-append="#v_notes"`, esc) || "";
    const diagChips = chipApi?.chipRow?.(pack.commonDiagnoses, disabledAttr, esc) || "";
    const labChips = (pack.suggestedLabs || []).map((x) => `<span class="cx-ws-chip">${esc(x)}</span>`).join("");
    const radChips = (pack.suggestedRad || []).map((x) => `<span class="cx-ws-chip">${esc(x)}</span>`).join("");
    const toolTabs = chipApi?.toolTabsHtml?.(specCode, esc) || "";
    const toolPanels = chipApi?.toolPanelsHtml?.(specCode) || "";

    return `
      <section class="cx-ws-main" data-specialty="${esc(specCode)}">
        <header class="cx-ws-visit-head">
          <div>
            <div class="cx-ws-kicker">VIS-${esc(String(v.id).padStart(5, "0"))} · ${esc(data.specialty?.name_ar || pack.name_ar)}</div>
            <h2>${esc(v.chief_complaint || data.specialty?.name_ar || "زيارة طبية")}</h2>
            <p>بدأت ${esc(fmtTime(v.started_at))} · ${isOpen ? '<span class="cx-ws-status is-live">قيد المعاينة</span>' : '<span class="cx-ws-status">مكتملة</span>'} · ${esc(v.doctor_name || "")}</p>
          </div>
          <div class="cx-ws-quick-actions">
            ${isOpen ? `
              <button type="button" class="cx-ws-action" data-ws-modal="lab"><i class="fa fa-flask"></i> تحاليل</button>
              <button type="button" class="cx-ws-action" data-ws-modal="rad"><i class="fa fa-x-ray"></i> أشعة</button>
              <button type="button" class="cx-ws-action" data-ws-modal="proc"><i class="fa fa-syringe"></i> إجراء</button>
              <button type="button" class="cx-ws-action" data-ws-modal="fu"><i class="fa fa-calendar-plus"></i> متابعة</button>
            ` : ""}
          </div>
        </header>

        <nav class="cx-tabs cx-ws-tabs" id="docTabs" role="tablist" aria-label="مساحات الزيارة">
          ${isDental && featureOn("odontogram") ? '<button type="button" class="is-active" data-tab="dental-chart">مخطط الأسنان</button>' : ""}
          <button type="button" class="${isDental && featureOn("odontogram") ? "" : "is-active"}" data-tab="clinical">الزيارة</button>
          ${specialtyTemplate ? '<button type="button" data-tab="specialty">الفحص</button>' : ""}
          ${isDental ? `${featureOn("treatment_plans") ? '<button type="button" data-tab="treatment" data-finora-action="visit.tab.treatment">العلاج</button>' : ""}${featureOn("sessions") ? '<button type="button" data-tab="dental-sessions">الجلسات</button>' : ""}${featureOn("dental_images") ? '<button type="button" data-tab="dental-images">الصور</button>' : ""}` : toolTabs}
          <button type="button" data-tab="rx">الوصفة</button>
          <button type="button" data-tab="bill">الفاتورة</button>
        </nav>

        ${isDental && featureOn("odontogram") ? `<div class="cx-tab-panel is-active cx-dental-primary" id="tab-dental-chart">
          <section class="cx-panel">
            <div class="cx-ws-section__head cx-ws-dental-head">
              <div><h3>مخطط الأسنان</h3><p class="cx-ws-muted">المساحة السريرية الأساسية — اختر السن لعرض حالته وخطة علاجه.</p></div>
              <button type="button" class="cx-btn cx-btn--sm cx-ws-focus-toggle" data-dental-focus-toggle aria-pressed="true"><i class="fa fa-compress"></i><span>إنهاء وضع التركيز</span><kbd>F</kbd></button>
            </div>
            <div class="cx-dental-field" data-dental-mount data-readonly="${isOpen ? "0" : "1"}"><div class="cx-dental-root"></div></div>
          </section>
        </div>` : ""}

        <div class="cx-tab-panel ${isDental && featureOn("odontogram") ? "" : "is-active"}" id="tab-clinical">
          <div class="cx-ws-sections">
            <section class="cx-ws-section" data-section="complaint">
              <h3>الشكوى الرئيسية</h3>
              <div class="cx-field"><textarea class="cx-textarea" id="v_cc" data-autosave-field="chief_complaint" placeholder="${esc(pack.complaintPlaceholder || "")}" ${isOpen ? "" : "disabled"}>${esc(v.chief_complaint || "")}</textarea></div>
              ${complaintChips}
            </section>
            <section class="cx-ws-section" data-section="history">
              <h3>التاريخ المرضي</h3>
              <p class="cx-ws-muted">${esc(v.chronic_conditions || pack.historyNote || "اعرض الملخص من العمود الجانبي — الأمراض المزمنة والحساسيات.")}</p>
            </section>
            <section class="cx-ws-section" data-section="vitals">
              <div class="cx-ws-section__head"><h3>العلامات الحيوية</h3>${isOpen ? '<button type="button" class="cx-btn cx-btn--sm" id="btnVitals">تحديث العلامات</button>' : ""}</div>
              ${vitalsStrip(vitals, esc)}
              ${isOpen ? `
              <div class="cx-field-row cx-ws-vitals-editor" id="cxWsVitalsEditor" hidden>
                <div class="cx-field"><label>ضغط الدم</label><input class="cx-input" id="v_bp" value="${esc(vitals.blood_pressure || "")}"></div>
                <div class="cx-field"><label>نبض</label><input class="cx-input" id="v_hr" value="${esc(vitals.heart_rate ?? "")}"></div>
                <div class="cx-field"><label>حرارة</label><input class="cx-input" id="v_temp" value="${esc(vitals.temperature ?? "")}"></div>
                <div class="cx-field"><label>SpO2</label><input class="cx-input" id="v_spo2" value="${esc(vitals.oxygen_sat ?? "")}"></div>
                <div class="cx-field"><label>وزن</label><input class="cx-input" id="v_w" value="${esc(vitals.weight_kg ?? "")}"></div>
                <div class="cx-field"><label>طول</label><input class="cx-input" id="v_h" value="${esc(vitals.height_cm ?? "")}"></div>
                <div class="cx-field"><label>محيط الرأس</label><input class="cx-input" id="v_hc" value="${esc(vitals.head_circumference_cm ?? "")}"></div>
              </div>` : ""}
            </section>
            <section class="cx-ws-section" data-section="exam">
              <h3>الفحص السريري</h3>
              <div class="cx-field"><textarea class="cx-textarea" id="v_notes" data-autosave-field="clinical_notes" placeholder="${esc(pack.examPlaceholder || "")}" style="min-height:120px" ${isOpen ? "" : "disabled"}>${esc(v.clinical_notes || "")}</textarea></div>
              ${examChips}
            </section>
            <section class="cx-ws-section" data-section="diagnosis">
              <h3>التشخيص</h3>
              <div class="cx-feed" id="diagList" style="margin-bottom:10px">
                ${(data.diagnoses || []).map((d) => `<div class="cx-feed__item"><strong>${esc(d.code || "")}</strong> ${esc(d.title)}</div>`).join("") || '<div class="cx-empty">لا تشخيص بعد</div>'}
              </div>
              ${diagChips}
              ${isOpen ? `
              <div class="cx-field-row" style="margin-top:10px">
                <div class="cx-field"><label>كود</label><input class="cx-input" id="d_code" placeholder="ICD"></div>
                <div class="cx-field"><label>التشخيص</label><input class="cx-input" id="d_title"></div>
              </div>
              <button type="button" class="cx-btn cx-btn--sm" id="btnDiag">إضافة تشخيص</button>` : ""}
            </section>
            <section class="cx-ws-section" data-section="plan">
              <h3>الخطة العلاجية</h3>
              <p class="cx-ws-muted">سجّل الخطة ضمن الملاحظات السريرية أو أضف إجراءات / وصفة من الأقسام التالية.</p>
              ${labChips || radChips ? `
              <div class="cx-ws-suggest">
                ${labChips ? `<div><span class="cx-ws-suggest__label">تحاليل شائعة</span><div class="cx-ws-chip-row">${labChips}</div></div>` : ""}
                ${radChips ? `<div><span class="cx-ws-suggest__label">أشعة شائعة</span><div class="cx-ws-chip-row">${radChips}</div></div>` : ""}
              </div>` : ""}
            </section>
            <section class="cx-ws-section" data-section="followup">
              <h3>المتابعة</h3>
              <div class="cx-field"><label>موعد متابعة</label>
                <select class="cx-select" id="v_fu_preset" data-default-fu="${esc(pack.followupDefault || "14")}" ${isOpen ? "" : "disabled"}>
                  <option value="custom">تاريخ مخصص</option>
                  <option value="none">لا يحتاج متابعة</option>
                  <option value="7">بعد أسبوع</option>
                  <option value="14">بعد أسبوعين</option>
                  <option value="m1">بعد شهر</option>
                  <option value="m3">بعد 3 أشهر</option>
                  <option value="m6">بعد 6 أشهر</option>
                </select>
                <input class="cx-input" type="date" id="v_fu" value="${esc(v.follow_up_date || "")}" ${isOpen ? "" : "disabled"}>
              </div>
              ${isOpen ? `<button type="button" class="cx-btn cx-btn--sm" data-ws-modal="fu">إنشاء متابعة رسمية</button>` : ""}
            </section>
            <section class="cx-ws-section" data-section="attachments">
              <h3>المرفقات</h3>
              ${isOpen ? `
              <div class="cx-field"><label>رفع مرفق</label><input type="file" id="wsAttachFile" accept=".pdf,image/*"></div>
              <button type="button" class="cx-btn cx-btn--sm" id="btnWsAttach">رفع المرفق</button>` : ""}
              <a class="cx-btn cx-btn--sm" href="/clinics/attachments?patient_id=${v.patient_id}">عرض كل المرفقات</a>
            </section>
            <section class="cx-ws-section" data-section="notes">
              <h3>ملاحظات نهائية</h3>
              <p class="cx-ws-muted">تُحفظ مع الملاحظات السريرية أعلاه عند حفظ المسودة أو إنهاء الزيارة.</p>
            </section>
          </div>
        </div>

        ${specialtyTemplate ? `<div class="cx-tab-panel" id="tab-specialty"><section class="cx-panel"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><div><h3 style="margin:0">${esc(specialtyTemplate.name)}</h3><small>${esc(data.specialty?.name_ar || "")} · الإصدار ${specialtyTemplate.version}</small></div>${isOpen ? '<button class="cx-btn cx-btn--primary" id="btnSaveSpecialty">حفظ النموذج</button>' : ""}</div>${specialtyTemplate.sections.map((section) => `<fieldset style="border:1px solid var(--cx-line);border-radius:14px;padding:14px;margin-top:14px"><legend style="padding:0 8px;font-weight:800">${esc(section.title_ar)}</legend><div class="cx-field-row">${section.fields.map((field) => specialtyFieldHtml(field, data.values?.[String(field.id)], !isOpen)).join("")}</div></fieldset>`).join("")}</section></div>` : ""}
        ${isDental ? `${featureOn("treatment_plans") ? '<div class="cx-tab-panel" id="tab-treatment"><section class="cx-panel" id="dentalTreatmentPlanRoot" data-finora-section="treatment_plan.panel"><div class="cx-empty">جاري التحميل…</div></section></div>' : ""}
        ${featureOn("sessions") ? '<div class="cx-tab-panel" id="tab-dental-sessions"><section class="cx-panel" id="dentalSessionsRoot"><div class="cx-empty">جاري التحميل…</div></section></div>' : ""}
        ${featureOn("dental_images") ? '<div class="cx-tab-panel" id="tab-dental-images"><section class="cx-panel" id="dentalImagesRoot"><div class="cx-empty">جاري التحميل…</div></section></div>' : ""}` : toolPanels}

        <div class="cx-tab-panel" id="tab-rx">
          <section class="cx-panel">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
              <h3 style="margin:0">الوصفة الطبية</h3>
              <div class="cx-actions">${isOpen ? `<select class="cx-select" id="rxTemplate"><option value="">استخدام قالب…</option>${rxTemplates.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select><button type="button" class="cx-btn cx-btn--sm" id="btnUseRxTemplate">نسخ إلى المحرر</button><button type="button" class="cx-btn cx-btn--sm" id="btnSaveRxTemplate">حفظ كقالب</button>` : ""}<button type="button" class="cx-btn cx-btn--sm" id="btnPrintRx">طباعة الوصفة</button></div>
            </div>
            <div class="cx-field"><label>ملاحظات الوصفة</label><textarea class="cx-textarea" id="rx_notes" ${isOpen ? "" : "disabled"}>${esc(data.prescription?.notes || "")}</textarea></div>
            <div id="rxList" class="cx-feed" style="margin-bottom:10px">
              ${(data.prescription?.items || []).map((i) => `<div class="cx-feed__item"><strong>${esc(i.medicine_name)}</strong><small>${esc(i.dosage)} · ${esc(i.frequency)} · ${esc(i.duration)}</small></div>`).join("") || '<div class="cx-empty">لا أدوية — أضف الأدوية أدناه</div>'}
            </div>
            ${isOpen ? `
            <div class="cx-field"><label>اسم الدواء</label><input class="cx-input" id="rx_name" placeholder="مثال: أموكسيسيلين 500"></div>
            <div class="cx-field-row">
              <div class="cx-field"><label>الجرعة</label><input class="cx-input" id="rx_dose" placeholder="قرص واحد"></div>
              <div class="cx-field"><label>التكرار</label><input class="cx-input" id="rx_freq" placeholder="مرتين يومياً"></div>
            </div>
            <div class="cx-field"><label>المدة</label><input class="cx-input" id="rx_dur" placeholder="5 أيام"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button type="button" class="cx-btn cx-btn--sm" id="btnAddRx">إضافة دواء</button>
              <button type="button" class="cx-btn cx-btn--primary" id="btnSaveRx">حفظ الوصفة</button>
            </div>` : ""}
          </section>
        </div>

        <div class="cx-tab-panel" id="tab-bill">
          <section class="cx-panel">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px">
              <h3 style="margin:0">فاتورة العلاج</h3>
              <button type="button" class="cx-btn cx-btn--sm" id="btnPrintBill">معاينة / طباعة</button>
            </div>
            <div class="cx-table-wrap">
              <table class="cx-table" id="billTable">
                <thead><tr><th>البند</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th><th></th></tr></thead>
                <tbody id="billRows">
                  ${(billPreview.lines || []).map((l) => `
                    <tr data-source="${esc(l.source)}" data-id="${l.id || ""}">
                      <td>${esc(l.description)}</td>
                      <td>${l.quantity || 1}</td>
                      <td class="cx-money">${money(l.unit_price)}</td>
                      <td class="cx-money">${money(l.line_total)}</td>
                      <td>${l.source === "extra" && isOpen ? `<button type="button" class="cx-btn cx-btn--sm cx-bill-del" data-id="${l.id}">حذف</button>` : ""}</td>
                    </tr>`).join("") || '<tr><td colspan="5" class="cx-empty">لا بنود بعد</td></tr>'}
                </tbody>
              </table>
            </div>
            ${isOpen ? `
            <div style="margin-top:14px;display:grid;gap:10px;max-width:520px">
              <h4 style="margin:0;font-size:13px">إضافة بند للفاتورة</h4>
              <div class="cx-field"><label>الوصف</label><input class="cx-input" id="bl_desc" placeholder="مثال: حقنة · ضماد · تحليل"></div>
              <div class="cx-field-row">
                <div class="cx-field"><label>الكمية</label><input class="cx-input" id="bl_qty" type="number" min="1" value="1"></div>
                <div class="cx-field"><label>سعر الوحدة</label><input class="cx-input" id="bl_price" type="number" min="0" placeholder="0"></div>
              </div>
              <button type="button" class="cx-btn cx-btn--sm" id="btnAddBillLine">إضافة البند</button>
            </div>
            <div class="cx-field-row" style="max-width:520px;margin-top:14px">
              <div class="cx-field"><label>خصم (د.ع)</label><input class="cx-input" id="bill_discount" type="number" min="0" value="0"></div>
            </div>` : `
            <div class="cx-bill-total"><span>الإجمالي</span><span>${money(billPreview.total)}</span></div>
            ${(data.invoices || []).map((inv) => `
              <div class="cx-feed__item" style="margin-top:10px">
                فاتورة ${esc(inv.invoice_number)} · ${money(inv.total)}
                <small>مدفوع ${money(inv.paid)} · متبقي ${money(inv.balance)}</small>
              </div>`).join("")}`}
            <hr style="border:0;border-top:1px solid var(--cx-line);margin:16px 0">
            <h4 style="margin:0 0 8px;font-size:13px">الإجراءات المسجلة</h4>
            <div class="cx-feed" id="procList">
              ${(data.procedures || []).map((p) => `<div class="cx-feed__item"><strong>${esc(p.procedure_name)}</strong><small>${money(p.price)}</small></div>`).join("") || '<div class="cx-empty">لا إجراءات</div>'}
            </div>
            ${isOpen ? `<button type="button" class="cx-btn cx-btn--sm" id="btnAddProc" style="margin-top:8px">إضافة إجراء</button>` : ""}
          </section>
        </div>
      </section>`;
  }

  function searchHtml() {
    return `
      <div class="cx-ws-search-wrap">
        <label class="cx-ws-search">
          <i class="fa fa-magnifying-glass"></i>
          <input id="cxWsPatientSearch" type="search" autocomplete="off" placeholder="ابحث عن مريض بالاسم أو الهاتف أو رقم الملف…" aria-label="البحث عن مريض">
          <kbd>Ctrl+K</kbd>
        </label>
        <button type="button" class="cx-ws-search-add" id="cxWsAddPatient" title="إضافة مريض جديد" aria-label="إضافة مريض جديد">
          <i class="fa fa-user-plus"></i>
        </button>
        <div class="cx-ws-search-drop" id="cxWsSearchDrop" hidden></div>
      </div>`;
  }

  function headerHtml(ctx, board, v, isOpen) {
    const { esc } = ctx;
    const doc = board.doctor || {};
    const name = doc.full_name || v?.doctor_name || "الطبيب";
    const specialty = doc.specialty || "";
    return `
      <header class="cx-ws-header">
        <div class="cx-ws-title">
          <span class="cx-ws-title__icon"><i class="fa fa-stethoscope"></i></span>
          <div>
            <h1>المعاينة الطبية</h1>
          </div>
        </div>
        ${searchHtml()}
        <div class="cx-ws-doctor-state">
          <div class="cx-ws-now">
            <small>${esc(clockNow().split("،").slice(0, 2).join("،"))}</small>
            <strong id="cxWsClock">${esc(new Date().toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" }))}</strong>
          </div>
          <span class="cx-ws-status ${isOpen ? "is-live" : ""}">${isOpen ? "مع مريض حالياً" : "بانتظار"}</span>
          <div class="cx-ws-doctor-name">
            <strong>${esc(name)}</strong>
            <small>${esc(specialty || "طبيب العيادة")}</small>
          </div>
          <a class="cx-btn cx-btn--sm cx-btn--ghost" href="/clinics/queue">قائمة الانتظار</a>
        </div>
      </header>`;
  }

  function footerHtml(isOpen, isDental = false) {
    if (!isOpen) {
      return `<footer class="cx-ws-footer"><a class="cx-btn" href="/clinics/doctor">العودة للمعالجة</a><button type="button" class="cx-btn" id="btnPrintRxFooter">طباعة الوصفة</button></footer>`;
    }
    return `
      <footer class="cx-ws-footer">
        <span class="cx-ws-save-hint" id="cxWsSaveHint" data-state="saved" role="status" aria-live="polite">تم الحفظ</span>
        <div class="cx-ws-footer__actions">
          <button type="button" class="cx-btn" id="btnSaveDraft" title="حفظ المسودة" aria-label="حفظ المسودة"><i class="fa fa-floppy-disk"></i><span>مسودة</span></button>
          <button type="button" class="cx-btn" id="btnPrintRxFooter" title="طباعة الوصفة" aria-label="طباعة الوصفة"><i class="fa fa-print"></i><span>وصفة</span></button>
          ${isDental ? `
          <button type="button" class="cx-btn" data-ws-tab="treatment" title="العلاج" aria-label="العلاج"><i class="fa fa-tooth"></i><span>علاج</span></button>
          <button type="button" class="cx-btn" data-ws-tab="dental-sessions" title="الجلسات" aria-label="الجلسات"><i class="fa fa-clock"></i><span>جلسة</span></button>
          <button type="button" class="cx-btn" data-ws-tab="dental-images" title="الصور" aria-label="الصور"><i class="fa fa-image"></i><span>صورة</span></button>
          <button type="button" class="cx-btn" data-ws-tab="bill" title="الفاتورة" aria-label="الفاتورة"><i class="fa fa-file-invoice"></i><span>فاتورة</span></button>` : ""}
        </div>
        <button type="button" class="cx-btn cx-btn--primary" id="btnCompleteVisit"><i class="fa fa-check"></i><span>إنهاء الزيارة</span></button>
      </footer>`;
  }

  function dentalFocusControlsHtml(isDental) {
    if (!isDental) return "";
    return `
      <div class="cx-ws-focus-scrim" data-focus-dismiss aria-hidden="true"></div>
      <div class="cx-ws-focus-docks" aria-label="لوحات المعاينة السريعة">
        <button type="button" class="cx-ws-focus-handle is-queue" data-focus-panel="queue" aria-expanded="false">
          <i class="fa fa-user"></i><span>المريض</span><i class="fa fa-chevron-right"></i>
        </button>
        <button type="button" class="cx-ws-focus-handle is-context" data-focus-panel="context" aria-expanded="false">
          <i class="fa fa-chevron-left"></i><span>السجل السريري</span><i class="fa fa-notes-medical"></i>
        </button>
        <button type="button" class="cx-ws-focus-handle is-footer" data-focus-panel="footer" aria-expanded="false">
          <i class="fa fa-chevron-up"></i><span>الإجراءات</span>
        </button>
      </div>`;
  }

  function bindDentalFocus(root, enabled) {
    if (!enabled) return;
    const workspace = root.querySelector(".cx-ws");
    const toggle = root.querySelector("[data-dental-focus-toggle]");
    if (!workspace || !toggle) return;
    let focusPreferred = true;
    const panelClasses = ["is-queue-open", "is-context-open", "is-footer-open"];

    const syncControls = () => {
      const active = workspace.classList.contains("is-dental-focus");
      toggle.setAttribute("aria-pressed", String(active));
      toggle.querySelector("span").textContent = active ? "إنهاء وضع التركيز" : "توسيع المخطط";
      const icon = toggle.querySelector("i");
      if (icon) icon.className = `fa ${active ? "fa-compress" : "fa-expand"}`;
      root.querySelectorAll("[data-focus-panel]").forEach((button) => {
        button.setAttribute("aria-expanded", String(workspace.classList.contains(`is-${button.dataset.focusPanel}-open`)));
      });
    };

    const closePanels = () => {
      workspace.classList.remove(...panelClasses);
      syncControls();
    };

    const setFocus = (active, remember = true) => {
      if (remember) focusPreferred = active;
      workspace.classList.toggle("is-dental-focus", active);
      if (!active) closePanels();
      syncControls();
    };

    root.querySelectorAll("[data-focus-panel]").forEach((button) => {
      button.onclick = () => {
        const className = `is-${button.dataset.focusPanel}-open`;
        const shouldOpen = !workspace.classList.contains(className);
        workspace.classList.remove(...panelClasses);
        if (shouldOpen) workspace.classList.add(className);
        syncControls();
      };
    });
    root.querySelector("[data-focus-dismiss]")?.addEventListener("click", closePanels);
    toggle.onclick = () => setFocus(!workspace.classList.contains("is-dental-focus"));
    root._setDentalFocus = (isDentalTab) => setFocus(Boolean(isDentalTab && focusPreferred), false);
    root._toggleDentalFocus = () => toggle.click();
    root._closeDentalPanels = closePanels;
    const dentalTabOn = !!root.querySelector("#tab-dental-chart.is-active");
    setFocus(dentalTabOn, false);
  }

  function waitingHtml(ctx, board) {
    const { esc } = ctx;
    const doc = board.doctor || {};
    const waiting = board.waiting_queue || [];
    return `
      <div class="cx-ws cx-ws--waiting">
        <header class="cx-ws-header">
          <div class="cx-ws-title">
            <span class="cx-ws-title__icon"><i class="fa fa-stethoscope"></i></span>
            <div>
              <h1>المعاينة الطبية</h1>
              <p>${esc(doc.full_name || "الطبيب")} · لا توجد زيارة جارية</p>
            </div>
          </div>
          ${searchHtml()}
          <div class="cx-ws-doctor-state">
            <span class="cx-ws-status">بانتظار</span>
            <a class="cx-btn cx-btn--sm" href="/clinics/queue">قائمة الانتظار</a>
          </div>
        </header>
        <section class="cx-ws-waiting-body">
          <div class="cx-ws-card cx-ws-card--hero-wait">
            <i class="fa fa-user-doctor" aria-hidden="true"></i>
            <h2>بانتظار المريض</h2>
            <p>عند ضغط الاستقبال على «إدخال للطبيب» ستُفتح الزيارة هنا تلقائياً.</p>
          </div>
          <article class="cx-ws-card">
            <div class="cx-ws-card__label">المرضى بانتظارك (${waiting.length})</div>
            <ol class="cx-ws-queue-list">
              ${waiting.map((a, i) => `
                <li>
                  <span class="cx-ws-qnum">${i + 1}</span>
                  <div>
                    <strong>${esc(a.patient_name)}</strong>
                    <small>${esc(a.start_time || "—")} · ${esc(a.patient_file || "")} · ينتظر ${a.wait_minutes != null ? a.wait_minutes + " د" : "—"}</small>
                  </div>
                </li>`).join("") || `<li class="cx-ws-muted">لا مرضى في الطابور حالياً</li>`}
            </ol>
          </article>
        </section>
      </div>`;
  }

  function bindContextTabs(root) {
    root.querySelectorAll("[data-ctx-tab]").forEach((btn) => {
      btn.onclick = () => {
        const tab = btn.dataset.ctxTab;
        root.querySelectorAll("[data-ctx-tab]").forEach((b) => b.classList.toggle("is-active", b === btn));
        root.querySelectorAll("[data-ctx-panel]").forEach((panel) => {
          panel.hidden = panel.dataset.ctxPanel !== tab;
        });
      };
    });
  }

  function bindWorkspaceSearch(ctx) {
    const input = document.getElementById("cxWsPatientSearch");
    const drop = document.getElementById("cxWsSearchDrop");
    const add = document.getElementById("cxWsAddPatient");
    if (add) {
      add.onclick = () => {
        if (typeof ctx.promptNewPatient === "function") ctx.promptNewPatient();
        else ctx.showNotice?.("افتح صفحة المرضى لإضافة ملف جديد");
      };
    }
    if (!input || !drop) return;
    const paint = (rows) => {
      if (!rows.length) {
        drop.hidden = false;
        drop.innerHTML = `<div class="cx-ws-search-empty">لا توجد نتائج</div>`;
        return;
      }
      drop.hidden = false;
      drop.innerHTML = rows
        .slice(0, 8)
        .map(
          (p) => `
        <a class="cx-ws-search-hit" href="/clinics/patients/${p.id}">
          <strong>${ctx.esc(p.full_name)}</strong>
          <span>${ctx.esc(p.file_number || "")} · ${ctx.esc(p.phone || "")}</span>
        </a>`
        )
        .join("");
    };
    input.oninput = () => {
      clearTimeout(input._t);
      const q = input.value.trim();
      if (q.length < 1) {
        drop.hidden = true;
        drop.innerHTML = "";
        return;
      }
      input._t = setTimeout(async () => {
        try {
          const rows = await ctx.api(`/clinics/api/patients?q=${encodeURIComponent(q)}&limit=8`);
          paint(Array.isArray(rows) ? rows : []);
        } catch {
          drop.hidden = true;
        }
      }, 180);
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") drop.hidden = true;
    });
    if (window._cxWsSearchCleanup) window._cxWsSearchCleanup();
    const onDoc = (e) => {
      if (!input.isConnected) {
        window._cxWsSearchCleanup?.();
        return;
      }
      if (!drop.contains(e.target) && e.target !== input && !input.contains(e.target) && e.target !== add) {
        drop.hidden = true;
      }
    };
    const onHotkey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onHotkey);
    window._cxWsSearchCleanup = () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onHotkey);
      window._cxWsSearchCleanup = null;
    };
  }

  async function saveDraft(ctx, visitId) {
    await persistDraft(ctx, visitId, true);
  }

  async function openLabModal(ctx, v) {
    const { api, esc, openModal } = ctx;
    const tests = await api("/clinics/api/lab-tests").catch(() => []);
    const list = Array.isArray(tests) ? tests : tests.items || [];
    const chips = list.length
      ? list.map((t) => {
          const meta = [t.code, t.category].filter(Boolean).join(" · ");
          return `<label class="cx-check-chip" data-lab-name="${esc(`${t.name} ${t.code || ""} ${t.category || ""}`)}">
            <input type="checkbox" name="lab_test" value="${t.id}">
            <span><b>${esc(t.name)}</b>${meta ? `<small>${esc(meta)}</small>` : ""}</span>
          </label>`;
        }).join("")
      : `<p class="cx-order-form__empty">لا توجد تحاليل معرفة في الكتالوج</p>`;
    openModal(
      "طلب تحاليل",
      `<div class="cx-order-form">
        <p class="cx-order-form__lead">اختر التحاليل المطلوبة لهذه الزيارة ثم أرسل الطلب للمختبر.</p>
        <section class="cx-order-form__section">
          <header class="cx-order-form__head">
            <strong>التحاليل</strong>
            <span id="lab_count">لم يُحدد بعد</span>
          </header>
          ${list.length > 4 ? `<label class="cx-order-form__search"><i class="fa fa-magnifying-glass"></i><input class="cx-input" id="lab_q" type="search" placeholder="ابحث عن تحليل..." autocomplete="off"></label>` : ""}
          <div class="cx-check-grid" id="lab_tests">${chips}</div>
        </section>
        <section class="cx-order-form__section">
          <strong class="cx-order-form__label">الأولوية</strong>
          <div class="cx-seg" role="radiogroup" aria-label="الأولوية">
            <label class="cx-seg__opt"><input type="radio" name="lab_priority" value="normal" checked><span>عادي</span></label>
            <label class="cx-seg__opt cx-seg__opt--urgent"><input type="radio" name="lab_priority" value="urgent"><span>مستعجل</span></label>
          </div>
        </section>
        <div class="cx-field cx-order-form__notes">
          <label for="lab_notes">ملاحظات سريرية</label>
          <textarea class="cx-textarea" id="lab_notes" placeholder="سبب الطلب أو ملاحظات للمختبر (اختياري)"></textarea>
        </div>
      </div>`,
      async () => {
        const test_ids = [...document.querySelectorAll('input[name="lab_test"]:checked')].map((el) => Number(el.value));
        if (!test_ids.length) throw new Error("اختر تحليلاً واحداً على الأقل");
        const priority = document.querySelector('input[name="lab_priority"]:checked')?.value || "normal";
        await api("/clinics/api/lab-orders", {
          method: "POST",
          body: JSON.stringify({
            patient_id: v.patient_id,
            doctor_id: v.doctor_id,
            visit_id: v.id,
            test_ids,
            priority,
            notes: document.getElementById("lab_notes").value,
          }),
        });
      },
      { saveLabel: "إرسال الطلب", successMessage: "تم إنشاء طلب التحاليل" }
    );
    const grid = document.getElementById("lab_tests");
    const countEl = document.getElementById("lab_count");
    const searchEl = document.getElementById("lab_q");
    const syncCount = () => {
      const n = document.querySelectorAll('input[name="lab_test"]:checked').length;
      if (!countEl) return;
      countEl.textContent = n === 0 ? "لم يُحدد بعد" : n === 1 ? "تحليل واحد" : `${n} تحاليل`;
      countEl.classList.toggle("is-on", n > 0);
    };
    grid?.addEventListener("change", syncCount);
    searchEl?.addEventListener("input", () => {
      const q = searchEl.value.trim().toLowerCase();
      grid.querySelectorAll(".cx-check-chip").forEach((el) => {
        el.hidden = Boolean(q) && !(el.dataset.labName || "").toLowerCase().includes(q);
      });
    });
  }

  async function openRadModal(ctx, v) {
    const { api, openModal, showNotice } = ctx;
    openModal(
      "طلب أشعة",
      `<div class="cx-field"><label>النوع</label>
        <select class="cx-select" id="rad_mod">
          <option value="xray">أشعة سينية</option>
          <option value="ultrasound">سونار</option>
          <option value="ct">مقطعية</option>
          <option value="mri">رنين مغناطيسي</option>
          <option value="mammography">ماموغرام</option>
          <option value="other">أخرى</option>
        </select>
      </div>
      <div class="cx-field"><label>المنطقة</label><input class="cx-input" id="rad_part" placeholder="صدر / بطن / ..."></div>
      <div class="cx-field"><label>الأولوية</label><select class="cx-select" id="rad_priority"><option value="normal">عادي</option><option value="urgent">مستعجل</option></select></div>
      <div class="cx-field"><label>السبب / ملاحظات</label><textarea class="cx-textarea" id="rad_notes"></textarea></div>`,
      async () => {
        await api("/clinics/api/radiology-orders", {
          method: "POST",
          body: JSON.stringify({
            patient_id: v.patient_id,
            doctor_id: v.doctor_id,
            visit_id: v.id,
            modality: document.getElementById("rad_mod").value,
            body_part: document.getElementById("rad_part").value,
            priority: document.getElementById("rad_priority").value,
            notes: document.getElementById("rad_notes").value,
          }),
        });
        showNotice("تم إنشاء طلب الأشعة", false);
      }
    );
  }

  async function openFollowupModal(ctx, v) {
    const { api, openModal, showNotice } = ctx;
    const defaultDue = document.getElementById("v_fu")?.value || "";
    openModal(
      "إنشاء متابعة",
      `<div class="cx-field"><label>تاريخ الاستحقاق</label><input class="cx-input" type="date" id="fu_due" value="${defaultDue}"></div>
      <div class="cx-field"><label>نوع المتابعة</label>
        <select class="cx-select" id="fu_type">
          <option value="treatment_review">مراجعة علاج</option>
          <option value="lab_result">نتيجة تحليل</option>
          <option value="radiology_result">نتيجة أشعة</option>
          <option value="post_procedure">بعد إجراء طبي</option>
          <option value="condition_check">استفسار عن الحالة</option>
          <option value="other">أخرى</option>
        </select>
      </div>
      <div class="cx-field"><label>السبب / ملاحظات</label><textarea class="cx-textarea" id="fu_notes"></textarea></div>`,
      async () => {
        const due = document.getElementById("fu_due").value;
        if (!due) throw new Error("حدد تاريخ المتابعة");
        await api("/clinics/api/followups", {
          method: "POST",
          body: JSON.stringify({
            patient_id: v.patient_id,
            doctor_id: v.doctor_id,
            visit_id: v.id,
            due_date: due,
            followup_type: document.getElementById("fu_type").value,
            notes: document.getElementById("fu_notes").value,
          }),
        });
        showNotice("تم إنشاء المتابعة", false);
      }
    );
  }

  async function openProcModal(ctx, visitId, onDone) {
    const { api, esc, openModal, showNotice } = ctx;
    const procs = await api(`/clinics/api/procedures?visit_id=${visitId}`);
    const list = Array.isArray(procs) ? procs : procs.items || [];
    openModal(
      "إضافة إجراء للزيارة",
      `<div class="cx-field"><label>الإجراء</label>
        <select class="cx-select" id="vp_id">${list.map((p) => `<option value="${p.id}">${esc(p.name)} · ${ctx.money(p.price)}</option>`).join("")}</select>
      </div>`,
      async () => {
        await api(`/clinics/api/visits/${visitId}/procedures`, {
          method: "POST",
          body: JSON.stringify({ procedure_id: Number(document.getElementById("vp_id").value) }),
        });
        showNotice("تمت إضافة الإجراء", false);
        if (onDone) await onDone();
      }
    );
  }

  function showCompletionSummary(ctx, v, board) {
    const { esc, root } = ctx;
    const next = board?.next_patient;
    root.innerHTML = `
      <div class="cx-ws cx-ws--done">
        <div class="cx-ws-card cx-ws-card--success">
          <i class="fa fa-circle-check" aria-hidden="true"></i>
          <h2>تم إنهاء زيارة ${esc(v.patient_name)}</h2>
          <p>تم حفظ السجل السريري وتحديث الطابور والفواتير حسب مسار العيادة.</p>
          <div class="cx-ws-done-actions">
            ${next ? `<a class="cx-btn cx-btn--primary" href="/clinics/doctor">المريض التالي / الطابور</a>` : `<a class="cx-btn cx-btn--primary" href="/clinics/doctor">العودة لطابور الطبيب</a>`}
            <a class="cx-btn" href="/clinics/billing">الفواتير</a>
            <a class="cx-btn" href="/clinics/queue">قائمة الانتظار</a>
          </div>
        </div>
      </div>`;
  }

  function mountSpecialtyTools(ctx, data, v, isOpen, visitId) {
    const { api, showNotice, openModal, esc, printClinicDoc } = ctx;
    const root = ctx.root;
    const mounted = new Set();

    async function mountDentalChart() {
      if (!window.ClinicsDentalChart) return;
      let mounts = [...root.querySelectorAll("[data-dental-mount]")];
      if (!mounts.length && data.specialty?.code === "dentistry") {
        const host = document.getElementById("tab-specialty") || document.getElementById("tab-clinical");
        if (host) {
          const box = document.createElement("section");
          box.className = "cx-panel";
          box.style.marginTop = "14px";
          box.innerHTML = `<h3 style="margin:0 0 8px">مخطط الأسنان</h3><div class="cx-field cx-dental-field" data-dental-mount data-readonly="${isOpen ? "0" : "1"}"><div class="cx-dental-root"></div></div>`;
          host.appendChild(box);
          mounts = [...root.querySelectorAll("[data-dental-mount]")];
        }
      }
      for (const mountEl of mounts) {
        const target = mountEl.querySelector(".cx-dental-root") || mountEl;
        if (target.dataset.cxMounted === "1") continue;
        target.dataset.cxMounted = "1";
        try {
          await window.ClinicsDentalChart.mount(target, {
            visitId,
            api,
            showNotice,
            readonly: mountEl.dataset.readonly === "1" || !isOpen,
            patientId: v.patient_id,
            doctorId: v.doctor_id,
            specialtyId: v.specialty_id,
            openModal,
          });
        } catch (err) {
          showNotice(err.message || String(err));
        }
      }
    }

    async function mountTreatmentPlan() {
      const planRoot = document.getElementById("dentalTreatmentPlanRoot");
      if (!planRoot || !window.ClinicsDentalTreatmentPlan) return;
      try {
        await window.ClinicsDentalTreatmentPlan.mount(planRoot, {
          patientId: v.patient_id,
          visitId,
          doctorId: v.doctor_id,
          specialtyId: v.specialty_id,
          api,
          showNotice,
          openModal,
          printClinicDoc,
        });
      } catch (err) {
        planRoot.innerHTML = `<div class="cx-empty">${esc(err.message || String(err))}</div>`;
      }
    }

    async function mountPlatform(view) {
      const platformRoot = document.getElementById(view === "sessions" ? "dentalSessionsRoot" : "dentalImagesRoot");
      if (!platformRoot || !window.ClinicsDentalPlatform) return;
      try {
        await window.ClinicsDentalPlatform.mount(platformRoot, {
          view,
          patientId: v.patient_id,
          visitId,
          doctorId: v.doctor_id,
          specialtyId: v.specialty_id,
          api,
          showNotice,
          openModal,
          readonly: !isOpen,
        });
      } catch (err) {
        platformRoot.innerHTML = `<div class="cx-empty">${esc(err.message || String(err))}</div>`;
      }
    }

    async function mountNamedTool(elId, winKey, reloadKey) {
      const el = document.getElementById(elId);
      if (!el || !window[winKey]) return;
      try {
        const handle = await window[winKey].mount(el, {
          patientId: v.patient_id,
          visitId,
          doctorId: v.doctor_id,
          api,
          showNotice,
          openModal,
          readonly: !isOpen,
        });
        el[reloadKey] = handle?.reload;
      } catch (err) {
        el.innerHTML = `<div class="cx-empty">${esc(err.message || String(err))}</div>`;
      }
    }

    const tabLoaders = {
      "dental-chart": () => mountDentalChart(),
      specialty: () => mountDentalChart(),
      treatment: () => mountTreatmentPlan(),
      "dental-sessions": () => mountPlatform("sessions"),
      "dental-images": () => mountPlatform("images"),
      pediatrics: () => mountNamedTool("pediatricToolsRoot", "ClinicsPediatricTools", "__pedReload"),
      gynecology: () => mountNamedTool("gynecologyToolsRoot", "ClinicsGynecologyTools", "__gynReload"),
      internal: () => mountNamedTool("internalMedicineToolsRoot", "ClinicsInternalMedicineTools", "__imReload"),
      cardiology: () => mountNamedTool("cardiologyToolsRoot", "ClinicsCardiologyTools", "__cardioReload"),
    };

    function ensureWsTab(tab) {
      const loader = tabLoaders[tab];
      if (!loader || mounted.has(tab)) return;
      mounted.add(tab);
      loader().catch((err) => showNotice(err.message || String(err)));
    }

    root._ensureWsTab = ensureWsTab;
    document.querySelectorAll("[data-ws-tab]").forEach((btn) => {
      btn.onclick = () => document.querySelector(`#docTabs [data-tab="${btn.dataset.wsTab}"]`)?.click();
    });
    (async () => {
      const holder = document.getElementById("cxWsActiveTreatments");
      if (!holder || (data.specialty?.code || "") !== "dentistry") return;
      try {
        const active = await api(`/clinics/api/patients/${v.patient_id}/dental-active-treatments`);
        const items = active.items || [];
        if (!items.length) return;
        holder.innerHTML = `<div class="cx-ws-card__label" style="margin-top:10px">متابعة العلاج</div>
          ${items.slice(0, 4).map((item) => `
            <button type="button" class="cx-ws-feed__item" data-continue-item="${item.id}">
              <strong>${esc(item.tooth_number || "عام")} · ${esc(item.title)}</strong>
              <small>${esc(item.status)} · ${item.estimated_sessions || 1} جلسات</small>
            </button>`).join("")}`;
        holder.querySelectorAll("[data-continue-item]").forEach((btn) => {
          btn.onclick = () => document.querySelector('#docTabs [data-tab="treatment"]')?.click();
        });
      } catch (_) {
        holder.innerHTML = "";
      }
    })();

    const activeTab = root.querySelector("#docTabs button.is-active")?.dataset.tab;
    ensureWsTab(activeTab || (data.specialty?.code === "dentistry" ? "dental-chart" : "clinical"));
    if (root.querySelector(".cx-tab-panel.is-active [data-dental-mount]")) ensureWsTab("dental-chart");
  }

  function bindSpecialtyForm(ctx, specialtyTemplate, visitId, isOpen) {
    const { root, api, showNotice, esc } = ctx;
    if (!specialtyTemplate) return async () => {};

    function specialtyValues() {
      const values = {};
      document.querySelectorAll("[data-specialty-field]").forEach((el) => {
        values[el.dataset.specialtyField] = ["boolean", "checkbox"].includes(el.dataset.fieldType)
          ? el.checked
          : ["file", "image"].includes(el.dataset.fieldType)
            ? el.value
              ? Number(el.value)
              : null
            : el.value;
      });
      document.querySelectorAll("[data-specialty-multi]").forEach((el) => {
        const id = el.dataset.specialtyMulti;
        values[id] ||= [];
        if (el.checked) values[id].push(el.value);
      });
      document.querySelectorAll("[data-specialty-table]").forEach((box) => {
        values[box.dataset.specialtyTable] = Array.from(box.querySelectorAll("tbody tr"), (row) =>
          Object.fromEntries(Array.from(row.querySelectorAll("[data-column]"), (input) => [input.dataset.column, input.value]))
        );
      });
      return values;
    }

    function updateSpecialtyVisibility() {
      const fields = specialtyTemplate?.sections.flatMap((s) => s.fields) || [];
      const values = specialtyValues();
      const byKey = Object.fromEntries(fields.map((f) => [f.key, values[f.id]]));
      fields.forEach((f) => {
        const r = f.visibility_rules || {};
        const el = root.querySelector(`[data-specialty-field="${f.id}"], [data-specialty-multi="${f.id}"], [data-specialty-table="${f.id}"]`);
        const box = el?.closest(".cx-field");
        if (!box) return;
        const v = byKey[r.field_key];
        const op = r.operator || "eq";
        box.hidden =
          !!r.field_key &&
          !(op === "eq"
            ? String(v ?? "") === String(r.value ?? "")
            : op === "ne"
              ? String(v ?? "") !== String(r.value ?? "")
              : op === "contains"
                ? Array.isArray(v) && v.includes(r.value)
                : v !== null && v !== undefined && v !== "" && (!Array.isArray(v) || v.length > 0));
      });
    }

    root.querySelectorAll("[data-specialty-table]").forEach((box) => {
      box.addEventListener("click", (event) => {
        if (event.target.closest("[data-delete-row]")) event.target.closest("tr").remove();
        if (event.target.closest("[data-add-row]")) {
          const columns = JSON.parse(box.dataset.columns);
          const tr = document.createElement("tr");
          tr.innerHTML =
            columns.map((c) => `<td><input class="cx-input" data-column="${esc(c)}"></td>`).join("") +
            '<td><button type="button" class="cx-btn" data-delete-row>حذف</button></td>';
          box.querySelector("tbody").append(tr);
        }
      });
    });

    root.querySelectorAll("[data-upload-field]").forEach((input) => {
      input.onchange = async () => {
        if (!input.files[0]) return;
        const form = new FormData();
        form.append("file", input.files[0]);
        form.append("field_id", input.dataset.uploadField);
        input.disabled = true;
        try {
          const response = await fetch(`/clinics/api/visits/${visitId}/specialty-attachment`, {
            method: "POST",
            headers: { "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "" },
            body: form,
          });
          const result = await response.json();
          if (!response.ok || !result.ok) throw Error(result.error || "فشل رفع الملف");
          root.querySelector(`[data-specialty-field="${input.dataset.uploadField}"]`).value = result.data.id;
          root.querySelector(`[data-upload-status="${input.dataset.uploadField}"]`).textContent = "تم حفظ المرفق";
        } catch (e) {
          showNotice(e.message);
        } finally {
          input.disabled = false;
        }
      };
    });

    root.querySelectorAll("[data-specialty-field], [data-specialty-multi]").forEach((el) => el.addEventListener("change", updateSpecialtyVisibility));
    updateSpecialtyVisibility();

    async function saveSpecialtyForm() {
      const values = specialtyValues();
      await api(`/clinics/api/visits/${visitId}/specialty-values`, { method: "PUT", body: JSON.stringify({ values }) });
    }

    const btnSaveSpecialty = document.getElementById("btnSaveSpecialty");
    if (btnSaveSpecialty) {
      btnSaveSpecialty.onclick = async () => {
        try {
          await saveSpecialtyForm();
          showNotice("تم حفظ نموذج الاختصاص", false);
        } catch (err) {
          showNotice(err.message || String(err));
        }
      };
    }

    return saveSpecialtyForm;
  }

  async function bindVisitHandlers(ctx, data, billPreview, rxTemplates, isOpen, visitId, board, clinical) {
    const { root, api, esc, money, showNotice, openModal, printClinicDoc, state } = ctx;
    const v = data.visit;
    const specialtyTemplate = data.template;
    const rxItems = [...(data.prescription?.items || [])];
    clinical = clinical || {};

    document.querySelectorAll("#docTabs button").forEach((btn) => {
      btn.onclick = () => {
        document.querySelectorAll("#docTabs button").forEach((b) => b.classList.remove("is-active"));
        document.querySelectorAll(".cx-tab-panel").forEach((p) => p.classList.remove("is-active"));
        btn.classList.add("is-active");
        document.getElementById(`tab-${btn.dataset.tab}`)?.classList.add("is-active");
        root._setDentalFocus?.(btn.dataset.tab === "dental-chart");
        root._ensureWsTab?.(btn.dataset.tab);
      };
    });

    root.querySelectorAll("[data-autosave-field]").forEach((el) => {
      el.addEventListener("input", () => scheduleAutosave(ctx, visitId));
      el.addEventListener("blur", () => {
        if (controller.dirty) flushAutosave().catch(() => {});
      });
    });

    const fuPreset = document.getElementById("v_fu_preset");
    if (fuPreset) {
      fuPreset.onchange = (event) => {
        const choice = event.target.value;
        const input = document.getElementById("v_fu");
        if (choice === "custom") return;
        if (choice === "none") {
          input.value = "";
          return;
        }
        const date = new Date();
        if (choice.startsWith("m")) {
          const day = date.getDate();
          date.setDate(1);
          date.setMonth(date.getMonth() + Number(choice.slice(1)));
          const last = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
          date.setDate(Math.min(day, last));
        } else date.setDate(date.getDate() + Number(choice));
        input.value = [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
      };
      if (isOpen && !v.follow_up_date && fuPreset.dataset.defaultFu) {
        const def = fuPreset.dataset.defaultFu;
        if ([...fuPreset.options].some((o) => o.value === def)) {
          fuPreset.value = def;
          fuPreset.dispatchEvent(new Event("change"));
        }
      }
    }

    function appendChipText(selector, text) {
      const el = root.querySelector(selector);
      if (!el || el.disabled || !text) return;
      const cur = String(el.value || "").trim();
      el.value = cur ? `${cur}، ${text}` : text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      controller.markDirty();
    }

    root.querySelectorAll(".cx-ws-chip.is-action[data-ws-append]").forEach((btn) => {
      btn.onclick = () => appendChipText(btn.dataset.wsAppend, btn.dataset.wsText || btn.textContent);
    });

    root.querySelectorAll(".cx-ws-chip.is-diag").forEach((btn) => {
      btn.onclick = () => {
        if (!isOpen) return;
        const codeEl = document.getElementById("d_code");
        const titleEl = document.getElementById("d_title");
        if (codeEl) codeEl.value = btn.dataset.wsDiagCode || "";
        if (titleEl) titleEl.value = btn.dataset.wsDiagTitle || "";
        document.getElementById("btnDiag")?.focus();
      };
    });

    const saveSpecialtyForm = bindSpecialtyForm(ctx, specialtyTemplate, visitId, isOpen);
    mountSpecialtyTools(ctx, data, v, isOpen, visitId);

    function renderRxList() {
      const el = document.getElementById("rxList");
      if (!el) return;
      el.innerHTML =
        rxItems
          .map((i) => `<div class="cx-feed__item"><strong>${esc(i.medicine_name)}</strong><small>${esc(i.dosage)} · ${esc(i.frequency)} · ${esc(i.duration)}</small></div>`)
          .join("") || '<div class="cx-empty">لا أدوية — أضف الأدوية أدناه</div>';
    }

    const btnUseRxTemplate = document.getElementById("btnUseRxTemplate");
    if (btnUseRxTemplate) {
      btnUseRxTemplate.onclick = () => {
        const selected = rxTemplates.find((item) => String(item.id) === document.getElementById("rxTemplate").value);
        if (!selected) return showNotice("اختر قالب وصفة أولاً");
        rxItems.splice(0, rxItems.length, ...selected.items.map((item) => ({ ...item })));
        if (!document.getElementById("rx_notes").value && selected.notes) document.getElementById("rx_notes").value = selected.notes;
        renderRxList();
        showNotice("تم نسخ القالب إلى المحرر؛ راجعه ثم اضغط حفظ الوصفة", false);
      };
    }

    const btnSaveRxTemplate = document.getElementById("btnSaveRxTemplate");
    if (btnSaveRxTemplate) {
      btnSaveRxTemplate.onclick = () => {
        if (!rxItems.length) return showNotice("أضف دواء واحداً على الأقل قبل حفظ القالب");
        const permissions = new Set(state.bootstrap?.user?.permissions || []);
        const canManageAll = state.bootstrap?.user?.role === "admin" || permissions.has("clinics_admin");
        const linkedDoctor = state.bootstrap?.current_doctor_id;
        openModal(
          "حفظ الوصفة كقالب",
          `<div class="cx-field"><label>اسم القالب</label><input class="cx-input" id="rxTplName"></div><div class="cx-field"><label>النطاق</label><select class="cx-select" id="rxTplScope">${linkedDoctor && !canManageAll ? '<option value="doctor">شخصي لهذا الطبيب</option>' : '<option value="clinic">كل العيادة</option><option value="specialty">هذا الاختصاص</option><option value="doctor">هذا الطبيب</option>'}</select></div><p class="cx-muted">حفظ القالب لا يحفظ أو يرسل الوصفة الحالية.</p>`,
          async () => {
            const scope = document.getElementById("rxTplScope").value;
            await api("/clinics/api/prescription-templates", {
              method: "POST",
              body: JSON.stringify({
                name: document.getElementById("rxTplName").value,
                scope_type: scope,
                specialty_id: scope === "specialty" ? v.specialty_id : null,
                doctor_id: scope === "doctor" ? v.doctor_id : null,
                notes: document.getElementById("rx_notes").value,
                items: rxItems,
              }),
            });
          }
        );
      };
    }

    async function refreshBillPreview() {
      const preview = await api(`/clinics/api/visits/${visitId}/treatment-bill`);
      const tbody = document.getElementById("billRows");
      if (!tbody) return preview;
      tbody.innerHTML =
        (preview.lines || [])
          .map(
            (l) => `
        <tr data-source="${esc(l.source)}" data-id="${l.id || ""}">
          <td>${esc(l.description)}</td>
          <td>${l.quantity || 1}</td>
          <td class="cx-money">${money(l.unit_price)}</td>
          <td class="cx-money">${money(l.line_total)}</td>
          <td>${l.source === "extra" && isOpen ? `<button type="button" class="cx-btn cx-btn--sm cx-bill-del" data-id="${l.id}">حذف</button>` : ""}</td>
        </tr>`
          )
          .join("") || '<tr><td colspan="5" class="cx-empty">لا بنود بعد</td></tr>';
      tbody.querySelectorAll(".cx-bill-del").forEach((btn) => {
        btn.onclick = async () => {
          try {
            await api(`/clinics/api/visits/${visitId}/treatment-bill/lines/${btn.dataset.id}`, { method: "DELETE" });
            await refreshBillPreview();
          } catch (err) {
            showNotice(err.message || String(err));
          }
        };
      });
      return preview;
    }

    document.querySelectorAll(".cx-bill-del").forEach((btn) => {
      btn.onclick = async () => {
        try {
          await api(`/clinics/api/visits/${visitId}/treatment-bill/lines/${btn.dataset.id}`, { method: "DELETE" });
          await refreshBillPreview();
        } catch (err) {
          showNotice(err.message || String(err));
        }
      };
    });

    const addProc = async () => {
      try {
        await openProcModal(ctx, visitId, () => refreshBillPreview());
      } catch (err) {
        showNotice(err.message || String(err));
      }
    };
    document.getElementById("btnAddProc") && (document.getElementById("btnAddProc").onclick = addProc);

    root.querySelectorAll("[data-ws-modal]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const kind = btn.dataset.wsModal;
          if (kind === "lab") await openLabModal(ctx, v);
          else if (kind === "rad") await openRadModal(ctx, v);
          else if (kind === "fu") await openFollowupModal(ctx, v);
          else if (kind === "proc") await addProc();
        } catch (err) {
          showNotice(err.message || String(err));
        }
      };
    });

    const btnVitals = document.getElementById("btnVitals");
    if (btnVitals) {
      btnVitals.onclick = async () => {
        const editor = document.getElementById("cxWsVitalsEditor");
        if (editor?.hidden) {
          editor.hidden = false;
          btnVitals.textContent = "حفظ العلامات";
          return;
        }
        try {
          await api(`/clinics/api/visits/${visitId}/vitals`, {
            method: "POST",
            body: JSON.stringify({
              blood_pressure: document.getElementById("v_bp")?.value,
              heart_rate: document.getElementById("v_hr")?.value,
              temperature: document.getElementById("v_temp")?.value,
              oxygen_sat: document.getElementById("v_spo2")?.value,
              weight_kg: document.getElementById("v_w")?.value,
              height_cm: document.getElementById("v_h")?.value,
              head_circumference_cm: document.getElementById("v_hc")?.value || "",
            }),
          });
          showNotice("تم حفظ العلامات الحيوية", false);
          if (editor) editor.hidden = true;
          btnVitals.textContent = "تحديث العلامات";
          if (window.ClinicsPediatricTools && document.getElementById("pediatricToolsRoot")?.__pedReload) {
            await document.getElementById("pediatricToolsRoot").__pedReload();
          }
          if (window.ClinicsInternalMedicineTools && document.getElementById("internalMedicineToolsRoot")?.__imReload) {
            await document.getElementById("internalMedicineToolsRoot").__imReload();
          }
          if (window.ClinicsCardiologyTools && document.getElementById("cardiologyToolsRoot")?.__cardioReload) {
            await document.getElementById("cardiologyToolsRoot").__cardioReload();
          }
        } catch (err) {
          showNotice(err.message || String(err));
        }
      };
    }

    document.getElementById("btnDiag") &&
      (document.getElementById("btnDiag").onclick = async () => {
        try {
          const code = document.getElementById("d_code").value;
          const title = document.getElementById("d_title").value;
          await api(`/clinics/api/visits/${visitId}/diagnoses`, {
            method: "POST",
            body: JSON.stringify({ code, title }),
          });
          const list = document.getElementById("diagList");
          if (list) {
            list.querySelector(".cx-empty")?.remove();
            const item = document.createElement("div");
            item.className = "cx-feed__item";
            item.innerHTML = `<strong>${esc(code)}</strong> ${esc(title)}`;
            list.appendChild(item);
          }
          document.getElementById("d_code").value = "";
          document.getElementById("d_title").value = "";
          showNotice("تم إضافة التشخيص", false);
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });

    document.getElementById("btnAddRx") &&
      (document.getElementById("btnAddRx").onclick = () => {
        const medicine_name = document.getElementById("rx_name").value.trim();
        if (!medicine_name) return;
        rxItems.push({
          medicine_name,
          dosage: document.getElementById("rx_dose").value,
          frequency: document.getElementById("rx_freq").value,
          duration: document.getElementById("rx_dur").value,
        });
        document.getElementById("rx_name").value = "";
        renderRxList();
      });

    document.getElementById("btnSaveRx") &&
      (document.getElementById("btnSaveRx").onclick = async () => {
        try {
          await api(`/clinics/api/visits/${visitId}/prescription`, {
            method: "POST",
            body: JSON.stringify({ items: rxItems, notes: document.getElementById("rx_notes").value }),
          });
          showNotice("تم حفظ الوصفة", false);
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });

    function doPrintRx() {
      const notes = document.getElementById("rx_notes")?.value || "";
      const settings = state.bootstrap?.settings || {};
      const patient = clinical?.patient || {};
      const doctor = (state.bootstrap?.doctors || []).find((row) => Number(row.id) === Number(v.doctor_id))
        || board?.doctor
        || {};
      const slug = document.querySelector(".cx-shell")?.dataset?.tenantSlug || "";
      const bookingUrl = slug ? `${location.origin}/c/${slug}` : location.origin;
      const payload = {
        clinicName: settings.clinic_name || "Finora Clinics",
        logoUrl: settings.public_logo_url || "",
        phone: settings.clinic_whatsapp_number || "",
        location: settings.public_location || "",
        website: bookingUrl.replace(/^https?:\/\//, ""),
        qrImage: `https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(bookingUrl)}`,
        patientName: v.patient_name || patient.full_name || "",
        patientFile: v.patient_file || patient.file_number || "",
        patientAge: patient.age ?? v.patient_age,
        patientGender: patient.gender || v.patient_gender || "",
        patientPhone: v.patient_phone || patient.phone || "",
        visitId: v.id,
        visitDate: v.visit_date || "",
        startedAt: v.started_at || "",
        specialtyName: v.specialty_name || doctor.specialty || "",
        visitType: (clinical?.items || []).length ? "مراجعة" : "زيارة",
        doctorName: v.doctor_name || doctor.full_name || "",
        doctorTitle: doctor.scientific_title || v.doctor_title || doctor.specialty || v.doctor_specialty || "",
        doctorLicense: doctor.license_number || v.doctor_license || "",
        items: rxItems,
        notes,
        doctorNotes: notes || v.clinical_notes || "",
      };
      if (window.ClinicsPrintPrescription?.print) {
        const opened = window.ClinicsPrintPrescription.print(payload, esc);
        if (!opened) showNotice("تعذر فتح نافذة الطباعة — اسمح بالنوافذ المنبثقة");
        return;
      }
      const rows = rxItems
        .map((i, n) => `<tr><td>${n + 1}</td><td>${esc(i.medicine_name)}</td><td>${esc(i.dosage)}</td><td>${esc(i.frequency)}</td><td>${esc(i.duration)}</td></tr>`)
        .join("");
      printClinicDoc(
        `وصفة — ${v.patient_name}`,
        `<h1>وصفة طبية</h1>
        <div class="meta">المريض: <strong>${esc(v.patient_name)}</strong> · ملف ${esc(v.patient_file)}<br>
        الطبيب: ${esc(v.doctor_name || "—")} · التاريخ: ${esc(v.visit_date || "")}</div>
        ${notes ? `<p><strong>ملاحظات:</strong> ${esc(notes)}</p>` : ""}
        <table><thead><tr><th>#</th><th>الدواء</th><th>الجرعة</th><th>التكرار</th><th>المدة</th></tr></thead><tbody>${rows || '<tr><td colspan="5">لا أدوية</td></tr>'}</tbody></table>`
      );
    }
    document.getElementById("btnPrintRx") && (document.getElementById("btnPrintRx").onclick = doPrintRx);
    document.getElementById("btnPrintRxFooter") && (document.getElementById("btnPrintRxFooter").onclick = doPrintRx);

    document.getElementById("btnPrintBill") &&
      (document.getElementById("btnPrintBill").onclick = async () => {
        const preview = await api(`/clinics/api/visits/${visitId}/treatment-bill`);
        const discount = Number(document.getElementById("bill_discount")?.value || 0);
        const total = Math.max(0, (preview.subtotal || 0) - discount);
        const rows = (preview.lines || [])
          .map((l) => `<tr><td>${esc(l.description)}</td><td>${l.quantity || 1}</td><td>${money(l.unit_price)}</td><td>${money(l.line_total)}</td></tr>`)
          .join("");
        printClinicDoc(
          `فاتورة علاج — ${v.patient_name}`,
          `<h1>فاتورة علاج</h1>
        <div class="meta">المريض: <strong>${esc(v.patient_name)}</strong> · ملف ${esc(v.patient_file)}<br>
        الطبيب: ${esc(v.doctor_name || "—")} · التاريخ: ${esc(v.visit_date || "")}</div>
        <table><thead><tr><th>البند</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr></thead><tbody>${rows}</tbody></table>
        <p style="text-align:left;font-weight:700;margin-top:12px">المجموع: ${money(preview.subtotal)}${discount ? ` · الخصم: ${money(discount)}` : ""} · الصافي: ${money(total)}</p>`
        );
      });

    document.getElementById("btnAddBillLine") &&
      (document.getElementById("btnAddBillLine").onclick = async () => {
        try {
          await api(`/clinics/api/visits/${visitId}/treatment-bill/lines`, {
            method: "POST",
            body: JSON.stringify({
              description: document.getElementById("bl_desc").value,
              quantity: document.getElementById("bl_qty").value,
              unit_price: document.getElementById("bl_price").value,
            }),
          });
          document.getElementById("bl_desc").value = "";
          document.getElementById("bl_qty").value = "1";
          document.getElementById("bl_price").value = "";
          await refreshBillPreview();
          showNotice("تمت إضافة البند", false);
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });

    document.getElementById("btnWsAttach") &&
      (document.getElementById("btnWsAttach").onclick = async () => {
        const fileInput = document.getElementById("wsAttachFile");
        if (!fileInput?.files?.[0]) return showNotice("اختر ملفاً أولاً");
        const form = new FormData();
        form.append("file", fileInput.files[0]);
        form.append("patient_id", String(v.patient_id));
        form.append("visit_id", String(visitId));
        form.append("category", "clinical");
        try {
          const response = await fetch("/clinics/api/attachments", {
            method: "POST",
            headers: { "X-CSRFToken": document.querySelector('meta[name="csrf-token"]')?.content || "" },
            body: form,
          });
          const result = await response.json();
          if (!response.ok || result.ok === false) throw Error(result.error || "فشل رفع المرفق");
          showNotice("تم رفع المرفق", false);
          fileInput.value = "";
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });

    document.getElementById("btnSaveDraft") &&
      (document.getElementById("btnSaveDraft").onclick = async () => {
        try {
          await saveDraft(ctx, visitId);
          if (specialtyTemplate) await saveSpecialtyForm();
        } catch (err) {
          showNotice(err.message || String(err));
        }
      });

    root.querySelectorAll("[data-prev-visit]").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const prev = await api(`/clinics/api/visits/${btn.dataset.prevVisit}`);
          const pv = prev.visit || {};
          openModal(
            `زيارة سابقة — ${fmtDate(pv.visit_date)}`,
            `<p><strong>${esc(pv.doctor_name || "—")}</strong></p>
             <p>${esc(pv.chief_complaint || "—")}</p>
             <p class="cx-ws-muted">${esc(pv.clinical_notes || "")}</p>
             <div class="cx-feed">${(prev.diagnoses || []).map((d) => `<div class="cx-feed__item">${esc(d.title)}</div>`).join("") || ""}</div>`,
            async () => {}
          );
        } catch (err) {
          showNotice(err.message || String(err));
        }
      };
    });

    async function completeVisitFlow() {
      try {
        if (!(await controller.onBeforeComplete())) return;
        if (specialtyTemplate) await saveSpecialtyForm();
        if (document.getElementById("v_cc")) {
          await api(`/clinics/api/visits/${visitId}`, {
            method: "PUT",
            body: JSON.stringify({
              chief_complaint: document.getElementById("v_cc").value,
              clinical_notes: document.getElementById("v_notes").value,
              follow_up_date: document.getElementById("v_fu").value,
            }),
          });
        }
        const discount = Number(document.getElementById("bill_discount")?.value || 0);
        await api(`/clinics/api/visits/${visitId}/complete`, {
          method: "POST",
          body: JSON.stringify({
            discount,
            create_followup: document.getElementById("v_fu_preset")?.value !== "none",
          }),
        });
        clearTimers();
        const freshBoard = await fetchWorkspace(api);
        showCompletionSummary(ctx, v, freshBoard);
      } catch (err) {
        showNotice(err.message || String(err));
      }
    }

    document.getElementById("btnCompleteVisit") && (document.getElementById("btnCompleteVisit").onclick = completeVisitFlow);

    if (root._cxWsKeyHandler) {
      document.removeEventListener("keydown", root._cxWsKeyHandler);
    }
    root._cxWsKeyHandler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        document.getElementById("btnSaveDraft")?.click();
        return;
      }
      const isFormField = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "") || e.target?.isContentEditable;
      if (!isFormField && !e.ctrlKey && !e.metaKey && !e.altKey && e.key.toLowerCase() === "f" && document.getElementById("tab-dental-chart")?.classList.contains("is-active")) {
        e.preventDefault();
        root._toggleDentalFocus?.();
      } else if (e.key === "Escape") {
        root._closeDentalPanels?.();
      }
    };
    document.addEventListener("keydown", root._cxWsKeyHandler);
  }

  async function renderWaiting(ctx) {
    clearTimers();
    const board = await fetchWorkspace(ctx.api);
    if (board.current_visit?.id) {
      location.href = `/clinics/doctor/${board.current_visit.id}`;
      return;
    }
    ctx.root.innerHTML = waitingHtml(ctx, board);
    bindWorkspaceSearch(ctx);
    queuePollHandle = setInterval(async () => {
      try {
        if (document.hidden) return;
        const b = await fetchWorkspace(ctx.api);
        if (b.current_visit?.id) location.href = `/clinics/doctor/${b.current_visit.id}`;
      } catch {
        /* ignore poll errors */
      }
    }, 40000);
  }

  async function render(ctx) {
    if (controller.dirty && activeCtx && activeVisitId) {
      await flushAutosave();
    }
    clearTimers();
    activeCtx = ctx;
    const visitId = ctx.visitId;
    activeVisitId = visitId || null;
    if (!visitId) {
      await renderWaiting(ctx);
      return;
    }

    const [data, billPreview, rxTemplates, board, specialtyContext] = await Promise.all([
      ctx.api(`/clinics/api/visits/${visitId}`),
      ctx.api(`/clinics/api/visits/${visitId}/treatment-bill`).catch(() => ({ lines: [], subtotal: 0, total: 0 })),
      ctx.api(`/clinics/api/visits/${visitId}/prescription-templates`).catch(() => []),
      fetchWorkspace(ctx.api),
      ctx.api(`/clinics/api/specialty-resolver?visit_id=${visitId}`).catch(() => null),
    ]);
    data.specialty_context = specialtyContext;

    const v = data.visit;
    const [clinicalOverview, clinicalVisitsData] = await Promise.all([
      ctx.api(`/clinics/api/clinical/patients/${v.patient_id}?section=overview`).catch(() => null),
      ctx.api(`/clinics/api/clinical/patients/${v.patient_id}?section=visits&per_page=5`).catch(() => ({ items: [] })),
    ]);
    const clinical = {
      ...(clinicalOverview || {}),
      section: "visits",
      items: (clinicalVisitsData.items || []).filter((x) => String(x.id) !== String(v.id)),
    };

    const isOpen = v.status === "open";
    controller.visitVersion = data.visit?.updated_at || data.visit?.id || null;

    ctx.root.innerHTML = `
      <div class="cx-ws ${isOpen ? "" : "cx-ws--readonly"}">
        ${headerHtml(ctx, board, v, isOpen)}
        <nav class="cx-doctor-quick" aria-label="انتقال سريع داخل المعاينة">
          <button type="button" class="cx-btn cx-btn--sm" data-jump-tab="clinical"><i class="fa fa-stethoscope"></i> الزيارة</button>
          <button type="button" class="cx-btn cx-btn--sm" data-jump-tab="rx"><i class="fa fa-prescription"></i> الوصفة</button>
          <button type="button" class="cx-btn cx-btn--sm" data-jump-tab="bill"><i class="fa fa-receipt"></i> الفاتورة</button>
        </nav>
        <div class="cx-ws-mobile-tabs" role="tablist">
          <button type="button" class="is-active" data-ws-pane="queue">المريض</button>
          <button type="button" data-ws-pane="main">المعاينة</button>
          <button type="button" data-ws-pane="context">السجل</button>
        </div>
        <div class="cx-ws-grid">
          ${queuePanelHtml(ctx, board, v, clinical, isOpen)}
          ${mainWorkspaceHtml(ctx, data, billPreview, rxTemplates, isOpen)}
          ${contextPanelHtml(ctx, v, clinical)}
        </div>
        ${footerHtml(isOpen, (data.specialty?.code || "") === "dentistry")}
        ${dentalFocusControlsHtml((data.specialty?.code || "") === "dentistry")}
      </div>`;

    bindDentalFocus(ctx.root, (data.specialty?.code || "") === "dentistry");

    bindTimer(v.started_at, document.getElementById("cxWsTimer"));
    const clockEl = document.getElementById("cxWsClock");
    if (clockEl) {
      if (clockHandle) clearInterval(clockHandle);
      clockHandle = setInterval(() => {
        const el = document.getElementById("cxWsClock");
        if (el) el.textContent = new Date().toLocaleTimeString("ar-IQ", { hour: "2-digit", minute: "2-digit" });
      }, 60000);
    }

    ctx.root.querySelectorAll("[data-ws-pane]").forEach((btn) => {
      btn.onclick = () => {
        ctx.root.querySelectorAll("[data-ws-pane]").forEach((b) => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        const pane = btn.dataset.wsPane;
        ctx.root.querySelector(".cx-ws-grid")?.setAttribute("data-active-pane", pane);
      };
    });

    bindContextTabs(ctx.root);
    bindWorkspaceSearch(ctx);

    ctx.root.querySelectorAll("[data-jump-tab]").forEach((button) => {
      button.onclick = () => {
        document.querySelector(`#docTabs [data-tab="${button.dataset.jumpTab}"]`)?.click();
      };
    });

    await bindVisitHandlers(ctx, data, billPreview, rxTemplates, isOpen, visitId, board, clinical);

    queuePollHandle = setInterval(async () => {
      try {
        if (document.hidden) return;
        const b = await fetchWorkspace(ctx.api);
        const list = ctx.root.querySelector(".cx-ws-queue-list");
        const nextCard = ctx.root.querySelector(".cx-ws-card--next");
        if (!list) return;
        const waiting = b.waiting_queue || [];
        list.innerHTML =
          waiting
            .slice(0, 8)
            .map(
              (a, i) => `
              <li>
                <span class="cx-ws-qnum">${i + 1}</span>
                <div>
                  <strong>${ctx.esc(a.patient_name)}</strong>
                  <small>${ctx.esc(a.start_time || "—")} · ${ctx.esc(a.patient_file || "")}</small>
                </div>
              </li>`
            )
            .join("") || `<li class="cx-ws-muted">لا مرضى بانتظار</li>`;
        if (nextCard && b.next_patient) {
          /* keep next card lightly updated via full poll text only on list */
        }
      } catch {
        /* ignore */
      }
    }, 40000);
  }

  window.ClinicsDoctorWorkspace = {
    render,
    renderWaiting,
    controller,
    sectionRegistry,
    saveDraft: (ctx, visitId) => saveDraft(ctx || activeCtx, visitId),
  };

  window.addEventListener("beforeunload", (event) => {
    if (!controller.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
