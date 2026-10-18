/* Interactive FDI dental chart — anatomical LTR layout inside RTL workspace. */
(() => {
  const QUADRANTS = {
    permanent: {
      upper: [
        ["18", "17", "16", "15", "14", "13", "12", "11"],
        ["21", "22", "23", "24", "25", "26", "27", "28"],
      ],
      lower: [
        ["48", "47", "46", "45", "44", "43", "42", "41"],
        ["31", "32", "33", "34", "35", "36", "37", "38"],
      ],
    },
    primary: {
      upper: [
        ["55", "54", "53", "52", "51"],
        ["61", "62", "63", "64", "65"],
      ],
      lower: [
        ["85", "84", "83", "82", "81"],
        ["71", "72", "73", "74", "75"],
      ],
    },
  };

  const SURFACE_LABELS = {
    mesial: "أنسي",
    distal: "وحشي",
    occlusal: "إطباقي",
    buccal: "دهليزي",
    lingual: "لساني",
    incisal: "قاطع",
  };

  const MODE_LABELS = { permanent: "دائم", primary: "لبني", mixed: "مختلط" };

  const STATUS_META = {
    healthy: { label: "سليم", className: "is-healthy" },
    caries: { label: "تسوس", className: "is-caries" },
    filled: { label: "حشوة", className: "is-filled" },
    temporary_filling: { label: "حشوة مؤقتة", className: "is-temporary" },
    root_canal: { label: "علاج عصب", className: "is-root-canal" },
    crown: { label: "تاج", className: "is-crown" },
    implant: { label: "زرعة", className: "is-implant" },
    bridge: { label: "جسر", className: "is-bridge" },
    missing: { label: "سن مفقود", className: "is-missing" },
    extracted: { label: "مقلوع", className: "is-extracted" },
    extraction_planned: { label: "مقرر قلع", className: "is-extraction-planned" },
    fracture: { label: "كسر", className: "is-fracture" },
    inflammation: { label: "التهاب", className: "is-inflammation" },
    mobility: { label: "حركة السن", className: "is-mobility" },
    unerupted: { label: "غير بازغ", className: "is-unerupted" },
    impacted: { label: "منطمر", className: "is-impacted" },
    other: { label: "أخرى", className: "is-other" },
  };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function findingMap(teeth) {
    const map = {};
    (teeth || []).forEach((t) => {
      map[t.tooth_number] = t;
    });
    return map;
  }

  function toothAria(num, finding) {
    const label = finding?.status_label_ar || "بدون تسجيل";
    return `السن ${num}، ${toothMeta(num).name} — ${label}`;
  }

  function statusClass(status) {
    return STATUS_META[status || "healthy"]?.className || "is-other";
  }

  function toothMeta(num) {
    const value = String(num);
    const quadrant = Number(value[0]);
    const position = Number(value[1]);
    const primary = quadrant >= 5;
    const names = primary
      ? ["", "القاطع المركزي", "القاطع الجانبي", "الناب", "الضرس الأول", "الضرس الثاني"]
      : ["", "القاطع المركزي", "القاطع الجانبي", "الناب", "الضاحك الأول", "الضاحك الثاني", "الضرس الأول", "الضرس الثاني", "ضرس العقل"];
    const kinds = primary
      ? ["", "central", "lateral", "canine", "molar1", "molar2"]
      : ["", "central", "lateral", "canine", "premolar1", "premolar2", "molar1", "molar2", "molar3"];
    const shortName = names[position] || "سن";
    const lower = [3, 4, 7, 8].includes(quadrant);
    const patientLeft = [2, 3, 6, 7].includes(quadrant);
    return {
      name: `${shortName} ${lower ? "السفلي" : "العلوي"} ${patientLeft ? "الأيسر" : "الأيمن"}`,
      shortName,
      kind: kinds[position] || "central",
      primary,
      lower,
      patientLeft,
    };
  }

  function toothSurfaceMarkers(surfaces) {
    const active = surfaces?.length ? surfaces : ["occlusal"];
    const paths = {
      occlusal: "M31 19 C35 14 46 15 49 21 C51 27 44 32 37 30 C31 29 27 24 31 19Z",
      incisal: "M25 13 C34 10 47 11 54 16 L51 22 C43 19 33 20 26 23Z",
      buccal: "M22 23 C26 18 31 20 32 26 C32 32 27 36 22 33 C19 31 19 26 22 23Z",
      lingual: "M48 24 C53 20 59 23 58 29 C57 35 51 37 47 33 C44 30 45 26 48 24Z",
      mesial: "M25 34 C29 30 34 32 34 38 C34 43 29 47 24 44 C21 42 21 37 25 34Z",
      distal: "M49 34 C54 31 59 34 58 40 C57 45 51 47 47 43 C44 40 45 36 49 34Z",
    };
    return active.map((surface) => `<path class="cx-dental__condition cx-dental__condition--lesion is-${esc(surface)}" d="${paths[surface] || paths.occlusal}" />`).join("");
  }

  function toothSvg(num, status, surfaces = []) {
    const meta = toothMeta(num);
    const drawings = {
      central: {
        body: "M22 12 C31 8 49 8 58 12 C63 15 64 28 60 39 C57 47 52 50 50 58 C47 73 47 101 41 111 C39 115 36 115 34 111 C28 99 30 74 28 59 C27 51 21 47 19 39 C16 29 17 16 22 12Z",
        detail: "M25 18 C34 14 47 14 55 18 M28 45 C35 48 44 48 51 45 M39 53 C38 71 38 91 38 106",
      },
      lateral: {
        body: "M25 14 C32 10 46 10 53 14 C59 18 60 29 57 39 C55 47 49 50 48 58 C46 76 47 100 41 111 C39 115 36 115 34 111 C28 99 30 76 29 59 C28 51 23 47 21 39 C18 29 20 18 25 14Z",
        detail: "M28 19 C35 16 44 16 51 19 M29 44 C35 47 43 47 49 44 M39 53 C38 73 38 92 38 106",
      },
      canine: {
        body: "M20 28 C25 23 31 23 37 9 C39 5 42 5 44 9 C49 22 57 23 61 29 C65 36 61 48 53 53 C49 56 48 61 48 68 C47 86 47 106 41 115 C39 118 36 118 34 114 C28 102 30 82 29 66 C29 59 26 56 22 52 C15 45 14 34 20 28Z",
        detail: "M23 32 C32 28 49 28 58 32 M27 49 C34 53 47 53 54 49 M39 57 C38 77 38 98 38 111",
      },
      premolar1: {
        body: "M17 20 C22 13 30 12 39 18 C47 11 58 13 63 21 C68 30 63 45 55 50 C51 53 51 59 50 66 C49 81 53 101 47 112 C45 116 42 115 40 111 L36 89 L32 111 C30 116 26 116 24 111 C19 100 24 80 23 66 C23 58 21 54 17 50 C10 43 10 29 17 20Z",
        detail: "M20 25 C30 20 49 20 60 25 M17 39 C28 45 52 45 63 38 M38 49 C37 63 36 78 36 91",
      },
      premolar2: {
        body: "M16 21 C22 13 31 12 39 18 C48 12 59 14 64 22 C70 32 64 45 55 51 C51 54 50 60 49 69 C48 86 48 105 42 114 C40 117 37 117 35 113 C29 102 31 85 29 69 C28 59 26 55 21 51 C11 44 9 31 16 21Z",
        detail: "M19 25 C29 20 50 20 61 26 M16 39 C28 45 53 45 65 39 M39 50 C38 69 38 92 38 109",
      },
      molar1: {
        body: "M10 20 C17 11 27 12 35 17 C44 10 54 11 60 17 C69 16 74 24 71 35 C70 44 65 49 59 52 C56 55 56 62 57 69 L61 102 C62 110 58 116 54 112 L44 83 L42 108 C41 116 36 117 33 110 L28 84 L21 110 C18 116 13 112 15 104 L19 70 C20 61 18 56 13 51 C5 43 4 29 10 20Z",
        detail: "M14 25 C27 19 52 19 67 25 M10 39 C25 47 56 47 70 38 M24 52 L28 83 M40 52 L42 84 M55 52 L45 83",
      },
      molar2: {
        body: "M11 21 C17 13 27 12 36 17 C44 11 55 12 62 18 C71 19 74 29 70 39 C67 47 61 49 57 54 C53 60 55 69 56 78 L59 105 C60 113 56 117 52 111 L43 84 L41 108 C40 116 35 117 32 110 L27 84 L20 109 C17 115 12 112 14 104 L18 72 C19 63 17 58 13 53 C5 44 5 29 11 21Z",
        detail: "M14 26 C27 20 53 20 67 26 M11 39 C25 46 55 47 69 39 M24 53 L27 84 M40 53 L42 85 M55 54 L44 84",
      },
      molar3: {
        body: "M13 24 C18 15 27 14 35 19 C44 13 55 15 61 21 C69 25 70 36 66 44 C63 50 57 53 54 58 C50 66 55 80 55 94 C55 104 51 110 47 105 L39 84 L36 105 C34 112 29 111 27 104 L23 85 L18 102 C15 108 11 104 13 96 L17 68 C18 60 14 55 11 50 C6 42 7 31 13 24Z",
        detail: "M16 28 C27 22 49 22 61 27 M13 41 C25 47 52 48 65 41 M23 55 L24 84 M38 55 L39 85 M53 58 L41 84",
      },
    };
    const drawing = drawings[meta.kind] || drawings.central;
    const canalPath = meta.kind.startsWith("molar")
      ? "M24 48 C24 68 22 88 20 105 M40 48 C40 68 40 89 40 108 M56 48 C56 68 58 88 60 104"
      : meta.kind === "premolar1"
        ? "M33 48 C33 70 31 91 29 108 M47 48 C47 70 49 91 51 108"
        : "M40 48 C40 70 40 92 40 110";
    const mirror = meta.patientLeft ? 'transform="translate(80 0) scale(-1 1)"' : "";
    return `<svg class="cx-dental__tooth-svg ${meta.lower ? "is-lower" : "is-upper"} is-${meta.kind}" viewBox="0 0 80 120" aria-hidden="true">
      <g ${mirror}>
        <path class="cx-dental__tooth-shadow" d="${drawing.body}" transform="translate(1.5 2)" />
        <path class="cx-dental__tooth-body" d="${drawing.body}" />
        <path class="cx-dental__anatomy-line" d="${drawing.detail}" />
        ${toothSurfaceMarkers(surfaces)}
        <path class="cx-dental__condition cx-dental__condition--canal" d="${canalPath}" />
        <path class="cx-dental__condition cx-dental__condition--crown" d="M12 22 C22 12 31 14 39 18 C48 12 61 14 68 23 L70 38 C57 47 23 47 10 38Z" />
        <path class="cx-dental__condition cx-dental__condition--fracture" d="M50 15 L38 29 L47 37 L33 51" />
        <path class="cx-dental__condition cx-dental__condition--implant" d="M31 49 L31 101 L49 101 L49 49 M28 60 L52 60 M28 70 L52 70 M28 80 L52 80 M28 90 L52 90 M34 108 L46 108" />
        <path class="cx-dental__condition cx-dental__condition--cross" d="M13 18 L66 91 M66 18 L13 91" />
        <path class="cx-dental__condition cx-dental__condition--motion" d="M8 38 C1 44 1 53 8 59 M72 38 C79 44 79 53 72 59" />
        <path class="cx-dental__condition cx-dental__condition--inflammation" d="M22 100 C31 112 49 112 58 100" />
        <path class="cx-dental__condition cx-dental__condition--bridge" d="M3 31 H17 M63 31 H77" />
      </g>
    </svg>`;
  }

  function archVars(index, count, isLower) {
    const middle = (count - 1) / 2;
    const normalized = middle ? (index - middle) / middle : 0;
    // Wide dental horseshoe, in the same 1000 × 700 space as the gum guide.
    // Rotate along the ellipse normal so posterior crowns face into the jaw.
    const angle = normalized * 84 * Math.PI / 180;
    const x = 500 + 400 * Math.sin(angle);
    const y = 265 - 165 * Math.cos(angle);
    const tilt = Math.atan2(165 * Math.sin(angle), 400 * Math.cos(angle)) * 180 / Math.PI;
    return `--arc-x:${(x / 10).toFixed(3)}%;--arc-y:${((isLower ? 700 - y : y) / 7).toFixed(3)}%;--arc-tilt:${(isLower ? -tilt : tilt).toFixed(2)}deg`;
  }

  function statusLegend(statuses) {
    const visible = ["healthy", "caries", "filled", "temporary_filling", "root_canal", "crown", "implant", "missing", "extraction_planned", "fracture", "other"];
    const available = new Map((statuses || []).map((item) => [item.code, item.label_ar]));
    return visible
      .filter((code) => available.has(code) || code === "healthy")
      .map((code) => `<span class="cx-dental__legend-item"><i class="${statusClass(code)}"></i>${esc(available.get(code) || STATUS_META[code].label)}</span>`)
      .join("");
  }

  function rowsForMode(mode) {
    if (mode === "primary") return QUADRANTS.primary;
    if (mode === "mixed") {
      return {
        upper: [
          [...QUADRANTS.permanent.upper[0], ...QUADRANTS.primary.upper[0]],
          [...QUADRANTS.primary.upper[1], ...QUADRANTS.permanent.upper[1]],
        ],
        lower: [
          [...QUADRANTS.permanent.lower[0], ...QUADRANTS.primary.lower[0]],
          [...QUADRANTS.primary.lower[1], ...QUADRANTS.permanent.lower[1]],
        ],
      };
    }
    return QUADRANTS.permanent;
  }

  function mobileQuadrants(mode) {
    const rows = rowsForMode(mode === "mixed" ? "permanent" : mode);
    const primaryRows = mode === "mixed" || mode === "primary" ? QUADRANTS.primary : null;
    const items = [
      { key: "ur", title: "يمين علوي", teeth: rows.upper[0] },
      { key: "ul", title: "يسار علوي", teeth: rows.upper[1] },
      { key: "lr", title: "يمين سفلي", teeth: rows.lower[0] },
      { key: "ll", title: "يسار سفلي", teeth: rows.lower[1] },
    ];
    if (mode === "mixed" && primaryRows) {
      items.push(
        { key: "pur", title: "لبني يمين علوي", teeth: primaryRows.upper[0] },
        { key: "pul", title: "لبني يسار علوي", teeth: primaryRows.upper[1] },
        { key: "plr", title: "لبني يمين سفلي", teeth: primaryRows.lower[0] },
        { key: "pll", title: "لبني يسار سفلي", teeth: primaryRows.lower[1] },
      );
    }
    return items;
  }

  async function mount(el, opts) {
    const { visitId, api, showNotice, readonly, patientId, doctorId, specialtyId, openModal } = opts;
    const chartUrl = opts.chartUrl || (visitId
      ? `/clinics/api/visits/${visitId}/dental-chart`
      : `/clinics/api/patients/${patientId}/dental-chart`);
    let chart = await api(chartUrl);
    let mode = chart.dentition_mode || "permanent";
    let activeQuad = "ur";
    let visitProcedures = [];
    let dentalServices = [];
    if (visitId) {
      try {
        [visitProcedures, dentalServices] = await Promise.all([
          api(`/clinics/api/visits/${visitId}/procedures`),
          api("/clinics/api/services?active=1"),
        ]);
        dentalServices = (dentalServices || []).filter((service) =>
          service.category === "أسنان" || (specialtyId && (service.specialty_ids || []).map(String).includes(String(specialtyId)))
        );
      } catch (_) {
        visitProcedures = [];
        dentalServices = [];
      }
    }
    const canEdit = !readonly && chart.permissions?.can_edit;
    const pid = patientId || chart.patient_id;

    function paint() {
      const byTooth = findingMap(chart.teeth);
      const rows = rowsForMode(mode === "mixed" ? "permanent" : mode);
      const primaryRows = mode === "mixed" ? QUADRANTS.primary : null;
      const quads = mobileQuadrants(mode);
      const active = quads.find((q) => q.key === activeQuad) || quads[0];
      const statuses = chart.catalog?.statuses || [];
      const recordedCount = (chart.teeth || []).filter((item) => item.status !== "healthy").length;
      const previousCount = Object.keys(chart.history_summary || {}).length;
      // Tablets have enough room for the complete anatomical arch.  Keep the
      // quadrant view for phones only so 7–13 inch devices never lose context.
      const mobile = window.matchMedia("(max-width: 599px)").matches;

      const archRow = (halves, isLower, isPrimary = false) => {
        const allTeeth = [...halves[0], ...halves[1]];
        return `<div class="cx-dental__arch ${isLower ? "is-lower" : "is-upper"} ${isPrimary ? "is-primary" : ""}">
          ${allTeeth
            .map((n, index) => toothBtn(n, byTooth[n], archVars(index, allTeeth.length, isLower)))
            .join("")}
        </div>`;
      };

      el.innerHTML = `
        <div class="cx-dental" dir="ltr" lang="en" data-dental-root>
          <div class="cx-dental__toolbar" dir="rtl">
            <div class="cx-dental__toolbar-title">
              <span class="cx-dental__toolbar-icon" aria-hidden="true"><i class="fa fa-tooth"></i></span>
              <div><strong>المخطط السريري للأسنان</strong><small>${
                chart.has_chart ? "محفوظ ضمن الزيارة الحالية" : "اختر سناً لبدء التوثيق"
              }</small></div>
            </div>
            <div class="cx-dental__toolbar-actions">
              <span class="cx-dental__readonly ${canEdit ? "" : "is-visible"}"><i class="fa fa-lock"></i> للقراءة فقط</span>
              <div class="cx-dental__modes" role="group" aria-label="نوع الأسنان">
                ${["permanent", "primary", "mixed"]
                  .map(
                    (m) =>
                      `<button type="button" class="cx-dental__mode ${mode === m ? "is-active" : ""}" data-mode="${m}" aria-pressed="${mode === m}">${MODE_LABELS[m]}</button>`
                  )
                  .join("")}
              </div>
            </div>
          </div>

          <div class="cx-dental__body">
            <aside class="cx-dental__legend" dir="rtl" aria-label="دليل الحالات">
              <div class="cx-dental__legend-head"><strong>الحالات والعلاجات</strong><small>انقر على أي سن لتسجيل حالته</small></div>
              <div class="cx-dental__legend-list">${statusLegend(statuses)}</div>
              <div class="cx-dental__stats">
                <span><b>${recordedCount}</b> حالة حالية</span>
                <span><b>${previousCount}</b> في السجل السابق</span>
              </div>
            </aside>

            <div class="cx-dental__canvas">
              ${
                mobile
                  ? `<div class="cx-dental__mobile">
                <div class="cx-dental__quad-nav" dir="rtl">
                  ${quads
                    .map(
                      (q) =>
                        `<button type="button" class="cx-dental__quad ${activeQuad === q.key ? "is-active" : ""}" data-quad="${q.key}">${esc(q.title)}</button>`
                    )
                    .join("")}
                </div>
                <div class="cx-dental__quad-grid">${(active?.teeth || [])
                  .map((n) => toothBtn(n, byTooth[n]))
                  .join("")}</div>
              </div>`
                  : `<div class="cx-dental__desktop ${primaryRows ? "is-mixed" : ""}" aria-label="مخطط الأسنان التشريحي">
                <svg class="cx-dental__jaw-guide" viewBox="0 0 1000 700" aria-hidden="true">
                  <path class="cx-dental__gingiva is-upper" d="M103.9 242 A400 165 0 0 1 896.1 242" />
                  <path class="cx-dental__gingiva is-lower" d="M103.9 458 A400 165 0 0 0 896.1 458" />
                </svg>
                <div class="cx-dental__orientation is-right" dir="rtl"><b>يمين المريض</b><small>Patient right</small></div>
                <div class="cx-dental__orientation is-left" dir="rtl"><b>يسار المريض</b><small>Patient left</small></div>
                <div class="cx-dental__jaw-label is-upper" dir="rtl"><b>الفك العلوي</b><small>Maxillary</small></div>
                ${archRow(rows.upper, false)}
                ${primaryRows ? archRow(primaryRows.upper, false, true) : ""}
                <div class="cx-dental__centerline" aria-hidden="true"></div>
                <div class="cx-dental__jaw-divider" aria-hidden="true"><span></span></div>
                <div class="cx-dental__jaw-label is-lower" dir="rtl"><b>الفك السفلي</b><small>Mandibular</small></div>
                ${primaryRows ? archRow(primaryRows.lower, true, true) : ""}
                ${archRow(rows.lower, true)}
              </div>`
              }
            </div>
          </div>
        </div>`;

      el.querySelectorAll("[data-mode]").forEach((btn) => {
        btn.onclick = () => {
          mode = btn.dataset.mode;
          paint();
        };
      });
      el.querySelectorAll("[data-quad]").forEach((btn) => {
        btn.onclick = () => {
          activeQuad = btn.dataset.quad;
          paint();
        };
      });
      el.querySelectorAll("[data-tooth]").forEach((btn) => {
        btn.onclick = () => openTooth(btn.dataset.tooth, byTooth[btn.dataset.tooth]);
      });
    }

    function toothBtn(num, finding, style = "") {
      const status = finding?.status || "healthy";
      const findings = finding?.findings || [];
      const visualStatuses = finding?.visual_statuses?.length ? finding.visual_statuses : [status];
      const visualClasses = visualStatuses.map(statusClass).join(" ");
      const badge = findings.length > 1
        ? findings.map((item) => item.status_label_ar).join(" + ")
        : finding ? finding.status_label_ar : "";
      const prev = chart.history_summary?.[num];
      const meta = toothMeta(num);
      return `<button type="button" class="cx-dental__tooth ${visualClasses} ${prev ? "has-history" : ""}" data-tooth="${esc(num)}" data-finora-action="tooth.select" data-status="${esc(status)}" aria-label="${esc(toothAria(num, finding))}" title="${esc(toothAria(num, finding))}" ${style ? `style="${style}"` : ""}>
        <span class="cx-dental__identity"><b class="cx-dental__num">${esc(num)}</b><small>${esc(meta.shortName)}</small></span>
        <span class="cx-dental__anatomy">${toothSvg(num, status, finding?.surfaces || [])}</span>
        <span class="cx-dental__badge">${esc(status !== "healthy" ? badge : prev ? "سجل سابق" : "")}</span>
        ${prev ? '<span class="cx-dental__history-dot" aria-hidden="true"></span>' : ""}
      </button>`;
    }

    async function openTooth(toothNumber, finding) {
      const prev = chart.history_summary?.[toothNumber];
      const statuses = chart.catalog?.statuses || [];
      const surfaces = chart.catalog?.surfaces || Object.keys(SURFACE_LABELS);
      const selected = new Set(finding?.surfaces || []);
      const currentFindings = finding?.findings || (finding ? [{ ...finding, legacy: true }] : []);
      let planItems = [];
      let planIncludeFinancial = false;
      if (pid) {
        try {
          const ctx = await api(
            `/clinics/api/patients/${pid}/dental-treatment-plans/tooth/${toothNumber}`
          );
          planItems = ctx.items || [];
          planIncludeFinancial = !!ctx.active_plan?.permissions?.include_financial;
        } catch (_) {
          planItems = [];
        }
      }
      const modal = document.createElement("div");
      modal.className = "cx-dental-drawer";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      modal.innerHTML = `
        <div class="cx-dental-drawer__panel" dir="rtl">
          <header class="cx-dental-drawer__head">
            <div><span>تفاصيل السن</span><h3>السن ${esc(toothNumber)}</h3><small>${esc(MODE_LABELS[mode])} · ترقيم FDI</small></div>
            <button type="button" class="cx-dental-drawer__close" data-close aria-label="إغلاق"><i class="fa fa-times"></i></button>
          </header>
          <div class="cx-dental-drawer__preview ${statusClass(finding?.status || "healthy")}" data-tooth-preview>
            ${toothSvg(toothNumber, finding?.status || "healthy", finding?.surfaces || [])}
            <div><span>${esc(toothMeta(toothNumber).name)}</span><strong data-preview-label>${esc(finding?.status_label_ar || "سليم")}</strong><small>${esc(toothAria(toothNumber, finding))}</small></div>
          </div>
          ${
            prev
              ? `<div class="cx-dental-drawer__prev"><i class="fa fa-history"></i><div><span>آخر حالة مسجلة</span><strong>${esc(prev.status_label_ar)}</strong><small>${esc(prev.visit_date || "")} · ${esc(prev.doctor_name || "")}</small></div></div>`
              : `<div class="cx-dental-drawer__prev"><i class="fa fa-history"></i><div><span>السجل السابق</span><small>لا يوجد تاريخ سابق لهذا السن</small></div></div>`
          }
          ${pid ? `<button type="button" class="cx-btn cx-btn--sm" data-load-history><i class="fa fa-clock-rotate-left"></i> عرض الخط الزمني الكامل</button><div class="cx-feed" data-tooth-timeline hidden></div>` : ""}
          <div class="cx-dental-drawer__plan">
            <div class="cx-dental-drawer__section-title"><i class="fa fa-clipboard-list"></i><strong>خطة العلاج</strong></div>
            <ul>${planItems
              .map(
                (i) =>
                  `<li>${esc(i.title)} · ${esc(i.status_label_ar)} · ${esc(i.sessions_label)}</li>`
              )
              .join("") || "<li>لا بنود نشطة لهذا السن</li>"}</ul>
            ${
              canEdit && window.ClinicsDentalTreatmentPlan
                ? `<button type="button" class="cx-btn cx-btn--sm cx-btn--primary" data-add-plan>+ إضافة إلى خطة العلاج</button>`
                : ""
            }
          </div>
          <div class="cx-dental-drawer__field"><span>حالة السن</span>
            <select class="cx-select cx-dental-drawer__native-status" data-status ${canEdit ? "" : "disabled"} aria-label="حالة السن">
              ${statuses
                .map(
                  (s) =>
                    `<option value="${esc(s.code)}" ${(finding?.status || "healthy") === s.code ? "selected" : ""}>${esc(s.label_ar)}</option>`
                )
                .join("")}
            </select>
            <div class="cx-dental-drawer__status-grid" role="radiogroup" aria-label="اختيار حالة السن">
              ${statuses.map((s) => `<button type="button" role="radio" aria-checked="${(finding?.status || "healthy") === s.code}" class="cx-dental-drawer__status ${statusClass(s.code)} ${(finding?.status || "healthy") === s.code ? "is-selected" : ""}" data-status-choice="${esc(s.code)}" ${canEdit ? "" : "disabled"}><i></i><span>${esc(s.label_ar)}</span></button>`).join("")}
            </div>
          </div>
          <section class="cx-dental-drawer__findings" aria-label="الحالات الفعالة">
            <div class="cx-dental-drawer__section-title"><i class="fa fa-notes-medical"></i><strong>الحالات الفعالة (${currentFindings.length})</strong></div>
            <div class="cx-dental-drawer__finding-list">
              ${currentFindings.map((item) => `<article class="cx-dental-drawer__finding ${statusClass(item.status)}">
                <i aria-hidden="true"></i><div><strong>${esc(item.status_label_ar || item.status)}</strong><small>${esc((item.surfaces || []).map((surface) => SURFACE_LABELS[surface] || surface).join("، ") || "كامل السن")}</small>${item.notes ? `<p>${esc(item.notes)}</p>` : ""}</div>
                ${canEdit && !item.legacy ? `<button type="button" class="cx-btn cx-btn--sm" data-resolve-finding="${item.id}">إنهاء</button>` : ""}
              </article>`).join("") || '<p class="cx-muted">لا توجد حالات فعالة.</p>'}
            </div>
          </section>
          <fieldset class="cx-dental-drawer__surface-field" ${canEdit ? "" : "disabled"}>
            <legend>الأسطح المتأثرة</legend>
            <p>حدد موضع الحالة بدقة على السن</p>
            <div class="cx-dental-drawer__surfaces" dir="ltr">
              ${surfaces
                .map(
                  (s) =>
                    `<label class="is-${esc(s)}"><input type="checkbox" value="${esc(s)}" ${selected.has(s) ? "checked" : ""}><span>${esc(SURFACE_LABELS[s] || s)}</span></label>`
                )
                .join("")}
            </div>
          </fieldset>
          <label class="cx-dental-drawer__field"><span>ملاحظات سريرية</span>
            <textarea class="cx-textarea" data-notes rows="3" ${canEdit ? "" : "disabled"}>${esc(finding?.notes || "")}</textarea>
          </label>
          <div class="cx-dental-drawer__procs">
            <div class="cx-dental-drawer__section-title"><i class="fa fa-link"></i><strong>إجراءات مرتبطة بهذه الزيارة</strong></div>
            <ul>${(finding?.procedures || [])
              .map((p) => `<li>${esc(p.procedure_name || "#" + p.visit_procedure_id)}</li>`)
              .join("") || "<li>لا إجراءات مرتبطة</li>"}</ul>
            ${
              canEdit && visitProcedures.length
                ? `<label>ربط إجراء موجود
                    <select class="cx-select" data-link-proc>
                      <option value="">—</option>
                      ${visitProcedures
                        .map(
                          (p) =>
                            `<option value="${p.id}">${esc(p.procedure_name || "إجراء")} (#${p.id})</option>`
                        )
                        .join("")}
                    </select>
                  </label>`
                : ""
            }
          </div>
          <footer class="cx-dental-drawer__footer">
            ${canEdit ? `<button type="button" class="cx-btn cx-btn--primary" data-add-finding><i class="fa fa-plus"></i> إضافة Finding</button>
              <button type="button" class="cx-btn" data-save><i class="fa fa-check"></i> استبدال الحالة الحالية</button>` : ""}
            <button type="button" class="cx-btn" data-close>${canEdit ? "إلغاء" : "إغلاق"}</button>
          </footer>
        </div>`;
      document.body.appendChild(modal);
      let onKeydown = null;
      const close = () => {
        if (onKeydown) document.removeEventListener("keydown", onKeydown);
        modal.remove();
      };
      modal.querySelectorAll("[data-close]").forEach((b) => (b.onclick = close));
      modal.addEventListener("click", (e) => {
        if (e.target === modal) close();
      });
      onKeydown = (event) => {
        if (event.key === "Escape") {
          close();
        }
      };
      document.addEventListener("keydown", onKeydown);
      const historyButton = modal.querySelector("[data-load-history]");
      if (historyButton) {
        historyButton.onclick = async () => {
          const timeline = modal.querySelector("[data-tooth-timeline]");
          historyButton.disabled = true;
          try {
            const events = await api(`/clinics/api/patients/${pid}/dental-tooth-events?tooth_number=${encodeURIComponent(toothNumber)}&limit=100`);
            timeline.innerHTML = (events || []).map((event) => `<div class="cx-feed__item">
              <strong>${esc(event.condition_label_ar)}</strong>
              <small>${esc((event.event_date || "").replace("T", " ").slice(0, 16))} · زيارة #${esc(event.visit_id || "—")} · ${event.event_type === "finding_resolved" ? "تم إنهاء الحالة" : event.is_active ? "حالة فعالة" : "تغيير مسجل"}</small>
              ${event.notes ? `<p>${esc(event.notes)}</p>` : ""}
            </div>`).join("") || '<p class="cx-muted">لا توجد أحداث مسجلة لهذا السن.</p>';
            timeline.hidden = false;
            historyButton.textContent = "تم عرض التاريخ الكامل";
          } catch (err) {
            historyButton.disabled = false;
            showNotice?.(err.message || String(err));
          }
        };
      }
      const statusSelect = modal.querySelector("[data-status]");
      const refreshPreview = () => {
        const preview = modal.querySelector("[data-tooth-preview]");
        if (preview) {
          preview.className = `cx-dental-drawer__preview ${statusClass(statusSelect.value)}`;
          const svg = preview.querySelector("svg");
          if (svg) {
            const selectedSurfaces = [...modal.querySelectorAll(".cx-dental-drawer__surfaces input:checked")].map((input) => input.value);
            svg.outerHTML = toothSvg(toothNumber, statusSelect.value, selectedSurfaces);
          }
        }
        const label = modal.querySelector("[data-preview-label]");
        if (label) label.textContent = statusSelect.selectedOptions[0]?.textContent || "";
        modal.querySelectorAll("[data-status-choice]").forEach((button) => {
          const selectedStatus = button.dataset.statusChoice === statusSelect.value;
          button.classList.toggle("is-selected", selectedStatus);
          button.setAttribute("aria-checked", String(selectedStatus));
        });
      };
      statusSelect?.addEventListener("change", refreshPreview);
      modal.querySelectorAll("[data-status-choice]").forEach((button) => {
        button.onclick = () => {
          statusSelect.value = button.dataset.statusChoice;
          statusSelect.dispatchEvent(new Event("change", { bubbles: true }));
        };
      });
      modal.querySelectorAll(".cx-dental-drawer__surfaces input").forEach((input) => input.addEventListener("change", refreshPreview));
      modal.querySelectorAll("[data-resolve-finding]").forEach((button) => {
        button.onclick = async () => {
          try {
            chart = await api(`/clinics/api/visits/${visitId}/dental-chart/tooth/${toothNumber}/findings/${button.dataset.resolveFinding}/resolve`, {
              method: "POST",
              body: JSON.stringify({}),
            });
            close();
            paint();
            showNotice?.("تم إنهاء الـ finding مع بقاءه في تاريخ السن");
          } catch (err) {
            showNotice?.(err.message || String(err));
          }
        };
      });
      const addPlanBtn = modal.querySelector("[data-add-plan]");
      if (addPlanBtn) {
        addPlanBtn.onclick = () => {
          if (!openModal || !window.ClinicsDentalTreatmentPlan) return;
          openModal(
            `إضافة السن ${toothNumber} إلى الخطة`,
            `<div class="cx-field"><label>خدمة الأسنان</label><select class="cx-select" id="dcPlanService"><option value="">علاج مخصص</option>${dentalServices.map((service) => `<option value="${service.id}">${esc(service.name)} · ${service.default_sessions || 1} جلسة${planIncludeFinancial ? ` · ${Number(service.price || 0).toLocaleString("ar-IQ")}` : ""}</option>`).join("")}</select></div>
             <div class="cx-field"><label>العنوان</label><input class="cx-input" id="dcPlanTitle" value=""></div>
             <div class="cx-field-row">
               <div class="cx-field"><label>الأولوية</label><select class="cx-select" id="dcPlanPriority"><option value="urgent">عاجل</option><option value="high">مرتفع</option><option value="normal" selected>عادي</option><option value="low">منخفض</option></select></div>
               <div class="cx-field"><label>جلسات</label><input class="cx-input" type="number" min="1" id="dcPlanSessions" value="1"></div>
             </div>
             ${planIncludeFinancial ? `<div class="cx-field"><label>سعر تقديري</label><input class="cx-input" type="number" min="0" id="dcPlanPrice" value=""></div>` : ""}
             <div class="cx-field"><label>ملاحظات</label><textarea class="cx-textarea" id="dcPlanNotes">حالة السن: ${esc(finding?.status_label_ar || finding?.status || "")}</textarea></div>`,
            async () => {
              await window.ClinicsDentalTreatmentPlan.addItemFromTooth(
                api,
                pid,
                toothNumber,
                {
                  service_id: document.getElementById("dcPlanService").value || null,
                  title: document.getElementById("dcPlanTitle").value || `علاج السن ${toothNumber}`,
                  priority: document.getElementById("dcPlanPriority").value,
                  estimated_sessions: Number(document.getElementById("dcPlanSessions").value || 1),
                  ...(planIncludeFinancial ? { estimated_price: document.getElementById("dcPlanPrice").value } : {}),
                  notes: document.getElementById("dcPlanNotes").value,
                },
                { doctorId, specialtyId, visitId }
              );
              showNotice?.("تمت الإضافة إلى خطة العلاج");
              close();
            }
          );
          const serviceSelect = document.getElementById("dcPlanService");
          if (serviceSelect) {
            serviceSelect.onchange = () => {
              const service = dentalServices.find((row) => String(row.id) === serviceSelect.value);
              if (!service) return;
              document.getElementById("dcPlanTitle").value = service.name;
              document.getElementById("dcPlanSessions").value = service.default_sessions || 1;
              const price = document.getElementById("dcPlanPrice");
              if (price) price.value = service.price || 0;
            };
          }
        };
      }
      const saveBtn = modal.querySelector("[data-save]");
      const payloadFromForm = () => ({
        status: modal.querySelector("[data-status]").value,
        surfaces: [...modal.querySelectorAll(".cx-dental-drawer__surfaces input:checked")].map((i) => i.value),
        notes: modal.querySelector("[data-notes]").value,
        dentition_mode: mode,
      });
      const addFindingBtn = modal.querySelector("[data-add-finding]");
      if (addFindingBtn) {
        addFindingBtn.onclick = async () => {
          try {
            chart = await api(`/clinics/api/visits/${visitId}/dental-chart/tooth/${toothNumber}/findings`, {
              method: "POST",
              body: JSON.stringify(payloadFromForm()),
            });
            mode = chart.dentition_mode || mode;
            close();
            paint();
            showNotice?.("تمت إضافة الحالة مع الحفاظ على الحالات الأخرى");
          } catch (err) {
            showNotice?.(err.message || String(err));
          }
        };
      }
      if (saveBtn) {
        saveBtn.onclick = async () => {
          const payload = payloadFromForm();
          const link = modal.querySelector("[data-link-proc]");
          if (link && link.value) payload.link_visit_procedure_id = Number(link.value);
          try {
            chart = await api(`/clinics/api/visits/${visitId}/dental-chart/tooth/${toothNumber}`, {
              method: "PUT",
              body: JSON.stringify(payload),
            });
            mode = chart.dentition_mode || mode;
            close();
            paint();
            showNotice?.("تم حفظ حالة السن");
          } catch (err) {
            showNotice?.(err.message || String(err));
          }
        };
      }
    }

    paint();
    const mq = window.matchMedia("(max-width: 599px)");
    const onViewport = () => paint();
    if (mq.addEventListener) mq.addEventListener("change", onViewport);
    else mq.addListener(onViewport);
    return {
      refresh: async () => {
        chart = await api(chartUrl);
        mode = chart.dentition_mode || mode;
        paint();
      },
    };
  }

  window.ClinicsDentalChart = { mount };
})();
