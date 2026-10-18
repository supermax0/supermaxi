/* Finora Clinics — adaptive doctor workspace by specialty code.
 * Keeps existing tool packs; adds complaint/exam/dx shortcuts for all specialties.
 */
(() => {
  const DEFAULT_PACK = {
    name_ar: "معاينة عامة",
    complaintPlaceholder: "اكتب الشكوى الرئيسية…",
    complaintChips: ["ألم", "حمى", "سعال", "إعياء", "متابعة"],
    examPlaceholder: "سجّل موجودات الفحص السريري…",
    examHints: ["المظهر العام طبيعي", "القلب طبيعي", "الرئتان طبيعيتان", "البطن لين", "لا وذمة"],
    historyNote: "راجع الأمراض المزمنة والحساسيات من العمود الجانبي.",
    commonDiagnoses: [],
    suggestedLabs: ["CBC", "RBS"],
    suggestedRad: [],
    followupDefault: "14",
    toolTabs: [],
  };

  const TOOL = {
    dentistry: [{ id: "treatment", label: "العلاج", rootId: "dentalTreatmentPlanRoot" }],
    pediatrics: [{ id: "pediatrics", label: "طب الأطفال", rootId: "pediatricToolsRoot" }],
    obstetrics_gynecology: [{ id: "gynecology", label: "النسائية والتوليد", rootId: "gynecologyToolsRoot" }],
    gynecology: [{ id: "gynecology", label: "النسائية والتوليد", rootId: "gynecologyToolsRoot" }],
    internal_medicine: [{ id: "internal", label: "الباطنية والأمراض المزمنة", rootId: "internalMedicineToolsRoot" }],
    cardiology: [{ id: "cardiology", label: "القلب والأوعية", rootId: "cardiologyToolsRoot" }],
  };

  const PACKS = {
    general_medicine: {
      name_ar: "الطب العام",
      complaintChips: ["التهاب حلق", "سعال", "حمى", "صداع", "ألم بطن", "إسهال", "متابعة مزمن"],
      examHints: ["حلق طبيعي", "أذنان طبيعيتان", "صدر نظيف", "بطن لين", "لا تضخم عقد"],
      commonDiagnoses: [
        { code: "J06.9", title: "التهاب تنفسي علوي" },
        { code: "A09", title: "التهاب معدي معوي" },
        { code: "R51", title: "صداع" },
      ],
      suggestedLabs: ["CBC", "RBS", "CRP"],
      followupDefault: "7",
    },
    family_medicine: {
      name_ar: "طب الأسرة",
      complaintChips: ["متابعة مزمن", "فحص دوري", "سعال", "ارتفاع ضغط", "سكري", "تطعيم"],
      examHints: ["فحص عام طبيعي", "ضغط مستقر", "لا وذمة", "صدر نظيف"],
      commonDiagnoses: [
        { code: "I10", title: "ارتفاع ضغط الدم" },
        { code: "E11", title: "سكري نمط 2" },
        { code: "Z00.0", title: "فحص طبي عام" },
      ],
      suggestedLabs: ["HbA1c", "Lipid profile", "Creatinine", "CBC"],
      followupDefault: "m1",
    },
    internal_medicine: {
      name_ar: "الباطنية",
      complaintChips: ["إعياء", "حمى", "ألم بطن", "ضيق تنفس", "فقدان وزن", "متابعة مزمن"],
      examHints: ["المظهر العام", "القلب طبيعي", "الرئتان طبيعيتان", "البطن لين", "لا وذمة"],
      commonDiagnoses: [
        { code: "E11", title: "سكري نمط 2" },
        { code: "I10", title: "ارتفاع ضغط الدم" },
        { code: "D50", title: "فقر دم بعوز الحديد" },
      ],
      suggestedLabs: ["CBC", "RFT", "LFT", "HbA1c", "TSH"],
      toolTabs: TOOL.internal_medicine,
    },
    cardiology: {
      name_ar: "القلب",
      complaintChips: ["ألم صدري", "ضيق تنفس", "خفقان", "إغماء", "تورم ساقين", "متابعة ضغط"],
      examHints: ["أصوات القلب طبيعية", "لا نفخة", "لا وذمة", "نبضات طرفية جيدة", "JVP طبيعي"],
      commonDiagnoses: [
        { code: "I20", title: "ذبحة صدرية" },
        { code: "I10", title: "ارتفاع ضغط الدم" },
        { code: "I48", title: "رجفان أذيني" },
      ],
      suggestedLabs: ["Troponin", "BNP", "Lipid profile", "ECG"],
      suggestedRad: ["Echo", "CXR"],
      followupDefault: "14",
      toolTabs: TOOL.cardiology,
    },
    pediatrics: {
      name_ar: "الأطفال",
      complaintChips: ["حمى", "سعال", "إسهال", "قيء", "طفح", "ضعف رضاعة", "مراجعة نمو"],
      examHints: ["نشاط جيد", "ترطيب جيد", "حلق طبيعي", "صدر نظيف", "بطن لين", "لا طفح"],
      commonDiagnoses: [
        { code: "J06.9", title: "التهاب تنفسي علوي" },
        { code: "A09", title: "إسهال حاد" },
        { code: "B34.9", title: "عدوى فيروسية" },
      ],
      suggestedLabs: ["CBC", "CRP", "RBS"],
      followupDefault: "7",
      toolTabs: TOOL.pediatrics,
    },
    dentistry: {
      name_ar: "الأسنان",
      complaintChips: ["ألم سن", "تورم لثة", "حساسية", "كسر سن", "رائحة فم", "متابعة علاج"],
      examHints: ["لثة ملتهبة", "نخر ظاهر", "لا خراج", "إطباق مقبول", "نظافة فموية ضعيفة"],
      commonDiagnoses: [
        { code: "K02.9", title: "نخر الأسنان" },
        { code: "K05.1", title: "التهاب لثة مزمن" },
        { code: "K04.0", title: "التهاب لب السن" },
      ],
      suggestedLabs: [],
      suggestedRad: ["X-ray سنّي"],
      followupDefault: "7",
      toolTabs: TOOL.dentistry,
    },
    dermatology: {
      name_ar: "الجلدية",
      complaintChips: ["طفح", "حكة", "حبوب", "تساقط شعر", "تغير لون", "جفاف جلد"],
      examHints: ["طفح بقعي", "حطاطات", "حويصلات", "تقشر", "لا عدوى ثانوية", "أظافر طبيعية"],
      commonDiagnoses: [
        { code: "L30.9", title: "التهاب جلد" },
        { code: "L70.0", title: "حب الشباب" },
        { code: "B35.1", title: "سعفة الأظافر" },
      ],
      suggestedLabs: ["IgE", "CBC"],
      followupDefault: "14",
    },
    obstetrics_gynecology: {
      name_ar: "النسائية والتوليد",
      complaintChips: ["تأخر دورة", "نزيف", "ألم حوض", "متابعة حمل", "إفرازات", "عقم"],
      examHints: ["بطن رخو", "رحم متناسب مع العمر الحملي", "لا نزيف نشط", "لا إيلام عنقي"],
      commonDiagnoses: [
        { code: "Z34", title: "متابعة حمل" },
        { code: "N92", title: "اضطراب دورة" },
        { code: "N94.6", title: "عسر طمث" },
      ],
      suggestedLabs: ["β-hCG", "CBC", "Blood group", "TSH"],
      suggestedRad: ["Ultrasound حوض/حمل"],
      followupDefault: "m1",
      toolTabs: TOOL.obstetrics_gynecology,
    },
    gynecology: {
      name_ar: "النسائية",
      complaintChips: ["نزيف", "ألم حوض", "إفرازات", "تأخر دورة", "متابعة"],
      examHints: ["لا نزيف نشط", "لا إيلام", "إفرازات طبيعية"],
      commonDiagnoses: [
        { code: "N92", title: "اضطراب دورة" },
        { code: "N76", title: "التهاب مهبلي" },
      ],
      suggestedLabs: ["CBC", "β-hCG"],
      suggestedRad: ["Ultrasound حوض"],
      toolTabs: TOOL.gynecology,
    },
    ent: {
      name_ar: "الأنف والأذن والحنجرة",
      complaintChips: ["ألم أذن", "انسداد أنف", "التهاب حلق", "دوار", "طنين", "بحة صوت"],
      examHints: ["طبلة طبيعية", "أنف محتقن", "حلق محمر", "لا ضخامة لوز", "لا إفراز صديدي"],
      commonDiagnoses: [
        { code: "H66.9", title: "التهاب أذن وسطى" },
        { code: "J02.9", title: "التهاب بلعوم" },
        { code: "J32.9", title: "التهاب جيوب مزمن" },
      ],
      suggestedLabs: ["CBC", "CRP"],
      suggestedRad: ["CT sinuses"],
      followupDefault: "7",
    },
    ophthalmology: {
      name_ar: "العيون",
      complaintChips: ["ضعف بصر", "احمرار عين", "ألم عين", "حكة", "إفرازات", "بقع سوداء"],
      examHints: ["حدة بصر", "حدقة متجاوبة", "ملتحمة محمرة", "لا إفراز صديدي", "قاع عين طبيعي"],
      commonDiagnoses: [
        { code: "H10.9", title: "التهاب ملتحمة" },
        { code: "H52.1", title: "قصر نظر" },
        { code: "H40.9", title: "زرق" },
      ],
      suggestedLabs: [],
      suggestedRad: [],
      followupDefault: "14",
    },
    orthopedics: {
      name_ar: "العظام",
      complaintChips: ["ألم ركبة", "ألم ظهر", "التواء", "كسر", "تيبس مفصل", "ضعف حركة"],
      examHints: ["لا تشوه", "مدى حركة محدود", "إيلام موضعي", "لا وذمة واضحة", "قوة عضلية طبيعية"],
      commonDiagnoses: [
        { code: "M54.5", title: "ألم أسفل الظهر" },
        { code: "M17.9", title: "خشونة ركبة" },
        { code: "S93.4", title: "التواء كاحل" },
      ],
      suggestedLabs: ["CBC", "ESR", "CRP", "Vit D"],
      suggestedRad: ["X-ray", "MRI"],
      followupDefault: "14",
    },
    neurology: {
      name_ar: "الأعصاب",
      complaintChips: ["صداع", "دوخة", "تنميل", "ضعف طرف", "تشنجات", "اضطراب ذاكرة"],
      examHints: ["وعي كامل", "أعصاب قحفية طبيعية", "قوة عضلية 5/5", "منعكسات طبيعية", "لا علامة سحائية"],
      commonDiagnoses: [
        { code: "G43.9", title: "شقيقة" },
        { code: "G40.9", title: "صرع" },
        { code: "R51", title: "صداع" },
      ],
      suggestedLabs: ["CBC", "Electrolytes", "B12", "TSH"],
      suggestedRad: ["CT brain", "MRI brain"],
      followupDefault: "14",
    },
    endocrinology: {
      name_ar: "الغدد والسكري",
      complaintChips: ["متابعة سكري", "خلل غدة درقية", "سمنة", "تعب", "عطش زائد", "تساقط شعر"],
      examHints: ["لا جحوظ", "درقية غير مجسوسة", "لا وذمة", "وزن مستقر"],
      commonDiagnoses: [
        { code: "E11", title: "سكري نمط 2" },
        { code: "E03.9", title: "قصور درقية" },
        { code: "E05.9", title: "فرط درقية" },
      ],
      suggestedLabs: ["HbA1c", "FBS", "TSH", "FT4", "Lipid profile"],
      followupDefault: "m1",
    },
    gastroenterology: {
      name_ar: "الجهاز الهضمي",
      complaintChips: ["حموضة", "ألم بطن", "إسهال", "إمساك", "غثيان", "يرقان", "نزف هضمي"],
      examHints: ["بطن لين", "لا إيلام ارتدادي", "كبد غير مجسوس", "طحال غير مجسوس", "لا يرقان ظاهر"],
      commonDiagnoses: [
        { code: "K21.0", title: "ارتجاع معدي مريئي" },
        { code: "K29.7", title: "التهاب معدة" },
        { code: "K58.9", title: "قولون عصبي" },
      ],
      suggestedLabs: ["LFT", "Amylase", "H. pylori Ag", "CBC"],
      suggestedRad: ["Ultrasound بطن", "Endoscopy"],
      followupDefault: "14",
    },
    nephrology: {
      name_ar: "الكلى",
      complaintChips: ["ارتفاع كرياتينين", "تورم", "زلال بول", "متابعة غسيل", "ارتفاع ضغط", "قلة بول"],
      examHints: ["لا وذمة", "ضغط مرتفع/مستقر", "بطن لين", "لا إيلام زاوية ضلعية قطنية"],
      commonDiagnoses: [
        { code: "N18.9", title: "مرض كلوي مزمن" },
        { code: "N17.9", title: "قصور كلوي حاد" },
        { code: "I12", title: "اعتلال كلوي بفرط الضغط" },
      ],
      suggestedLabs: ["Creatinine", "BUN", "Electrolytes", "Urinalysis", "ACR"],
      suggestedRad: ["Ultrasound كلى"],
      followupDefault: "m1",
    },
    pulmonology: {
      name_ar: "الصدرية",
      complaintChips: ["سعال", "ضيق تنفس", "بلغم", "أزيز", "ألم صدري", "متابعة ربو"],
      examHints: ["صدر متناظر", "أزيز مسموع", "خراخر", "لا زرقة", "SpO2 جيدة"],
      commonDiagnoses: [
        { code: "J45.9", title: "ربو" },
        { code: "J18.9", title: "ذات رئة" },
        { code: "J44.9", title: "COPD" },
      ],
      suggestedLabs: ["CBC", "CRP", "ABG"],
      suggestedRad: ["CXR", "CT chest"],
      followupDefault: "14",
    },
    rheumatology: {
      name_ar: "الروماتيزم",
      complaintChips: ["ألم مفاصل", "تيبس صباحي", "تورم مفصل", "ألم عضلات", "طفح", "إعياء"],
      examHints: ["تورم مفصل", "محدودية حركة", "لا احمرار حاد", "نقاط إيلام", "قوة عضلية طبيعية"],
      commonDiagnoses: [
        { code: "M06.9", title: "التهاب مفاصل روماتويدي" },
        { code: "M10.9", title: "نقرس" },
        { code: "M79.1", title: "ألم عضلي" },
      ],
      suggestedLabs: ["ESR", "CRP", "RF", "ANA", "Uric acid"],
      suggestedRad: ["X-ray مفاصل"],
      followupDefault: "m1",
    },
    general_surgery: {
      name_ar: "الجراحة العامة",
      complaintChips: ["ألم بطن حاد", "فتق", "خراج", "جرح", "متابعة عملية", "كتلة"],
      examHints: ["بطن لين/متوتر", "إيلام موضعي", "لا دفاع عضلي", "جرح نظيف", "لا احمرار"],
      commonDiagnoses: [
        { code: "K35.8", title: "التهاب زائدة" },
        { code: "K40.9", title: "فتق إربي" },
        { code: "L02.9", title: "خراج جلدي" },
      ],
      suggestedLabs: ["CBC", "CRP", "RFT"],
      suggestedRad: ["Ultrasound بطن", "CT abdomen"],
      followupDefault: "7",
    },
    urology: {
      name_ar: "المسالك البولية",
      complaintChips: [
        "صعوبة تبول", "حرقة بول", "تكرار تبول", "دم في البول", "ألم خاصرة",
        "مغص كلوي", "ضعف قذف", "كتلة صفن", "متابعة حصى", "متابعة بروستات",
      ],
      examHints: [
        "بطن لين", "إيلام زاوية ضلعية قطنية", "مثانة غير ممتلئة ظاهرياً",
        "لا تضخم صفن", "فحص بروستات (إن أُجري)", "لا إفراز إحليلي",
      ],
      commonDiagnoses: [
        { code: "N40", title: "تضخم البروستات الحميد" },
        { code: "N20.0", title: "حصاة كلوية" },
        { code: "N39.0", title: "التهاب مسالك بولية" },
        { code: "N30.9", title: "التهاب مثانة" },
        { code: "R31", title: "بيلة دموية" },
        { code: "N48.4", title: "ضعف انتصاب" },
      ],
      suggestedLabs: ["Urinalysis", "Urine culture", "PSA", "Creatinine", "CBC"],
      suggestedRad: ["KUB", "Ultrasound كلى/مثانة", "CT urography"],
      followupDefault: "14",
    },
    psychiatry: {
      name_ar: "الطب النفسي",
      complaintChips: ["قلق", "أرق", "اكتئاب", "توتر", "نوبات هلع", "متابعة دواء"],
      examHints: ["مظهر مرتب", "تواصل جيد", "مزاج مكتئب/قلق", "لا أفكار انتحارية حالية", "إدراك سليم"],
      commonDiagnoses: [
        { code: "F41.1", title: "اضطراب قلق عام" },
        { code: "F32.9", title: "اكتئاب" },
        { code: "F51.0", title: "أرق غير عضوي" },
      ],
      suggestedLabs: ["TSH", "CBC", "B12"],
      followupDefault: "14",
    },
    physiotherapy: {
      name_ar: "العلاج الطبيعي",
      complaintChips: ["ألم ظهر", "ضعف عضلي", "تيبس", "إعادة تأهيل", "ألم رقبة", "محدودية حركة"],
      examHints: ["مدى حركة", "قوة عضلية", "توازن", "مشية", "إيلام موضعي"],
      commonDiagnoses: [
        { code: "M54.5", title: "ألم أسفل الظهر" },
        { code: "M62.81", title: "ضعف عضلي" },
        { code: "Z50.1", title: "إعادة تأهيل طبيعي" },
      ],
      suggestedLabs: [],
      followupDefault: "7",
    },
    nutrition: {
      name_ar: "التغذية",
      complaintChips: ["إنقاص وزن", "سمنة", "سكري", "سوء تغذية", "حساسية غذائية", "متابعة نظام"],
      examHints: ["BMI", "محيط خصر", "علامات سوء تغذية", "حالة ترطيب"],
      commonDiagnoses: [
        { code: "E66.9", title: "سمنة" },
        { code: "E46", title: "سوء تغذية" },
        { code: "E11", title: "سكري — دعم غذائي" },
      ],
      suggestedLabs: ["HbA1c", "Lipid profile", "Albumin", "Vit D"],
      followupDefault: "14",
    },
  };

  function resolve(code) {
    const key = String(code || "").trim().toLowerCase();
    const pack = PACKS[key] || {};
    return {
      ...DEFAULT_PACK,
      ...pack,
      code: key || "general_medicine",
      toolTabs: pack.toolTabs || TOOL[key] || DEFAULT_PACK.toolTabs,
      complaintChips: pack.complaintChips || DEFAULT_PACK.complaintChips,
      examHints: pack.examHints || DEFAULT_PACK.examHints,
      commonDiagnoses: pack.commonDiagnoses || DEFAULT_PACK.commonDiagnoses,
      suggestedLabs: pack.suggestedLabs || DEFAULT_PACK.suggestedLabs,
      suggestedRad: pack.suggestedRad || DEFAULT_PACK.suggestedRad,
    };
  }

  function chipRow(items, attrs, esc) {
    const list = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!list.length) return "";
    return `<div class="cx-ws-chip-row">${list.map((item) => {
      if (typeof item === "string") {
        return `<button type="button" class="cx-ws-chip is-action" ${attrs} data-ws-text="${esc(item)}">${esc(item)}</button>`;
      }
      return `<button type="button" class="cx-ws-chip is-action is-diag" ${attrs} data-ws-diag-code="${esc(item.code || "")}" data-ws-diag-title="${esc(item.title || "")}">${esc(item.code || "")} · ${esc(item.title || "")}</button>`;
    }).join("")}</div>`;
  }

  function toolTabsHtml(code, esc) {
    return resolve(code).toolTabs.map((t) =>
      `<button type="button" data-tab="${esc(t.id)}">${esc(t.label)}</button>`
    ).join("");
  }

  function toolPanelsHtml(code) {
    return resolve(code).toolTabs.map((t) =>
      `<div class="cx-tab-panel" id="tab-${t.id}"><section class="cx-panel" id="${t.rootId}"><div class="cx-empty">جاري التحميل…</div></section></div>`
    ).join("");
  }

  window.ClinicsSpecialtyWorkspace = {
    DEFAULT_PACK,
    PACKS,
    resolve,
    chipRow,
    toolTabsHtml,
    toolPanelsHtml,
  };
})();
