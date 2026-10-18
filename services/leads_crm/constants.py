"""Leads CRM constants and status definitions."""

LEAD_STATUSES = [
    ("NEW", "جديد", 1, "#6366f1"),
    ("CONTACTED", "تم التواصل", 2, "#3b82f6"),
    ("NO_ANSWER", "لا يرد", 3, "#94a3b8"),
    ("REPLIED", "رد علينا", 4, "#06b6d4"),
    ("INTERESTED", "مهتم", 5, "#8b5cf6"),
    ("DEMO_SCHEDULED", "موعد Demo", 6, "#a855f7"),
    ("TRIAL", "تحت التجربة", 7, "#f59e0b"),
    ("FOLLOW_UP", "متابعة لاحقة", 8, "#eab308"),
    ("SUBSCRIBED", "مشترك", 9, "#22c55e"),
    ("NOT_INTERESTED", "غير مهتم", 10, "#64748b"),
    ("INVALID", "بيانات غير صحيحة", 11, "#ef4444"),
    ("DO_NOT_CONTACT", "عدم التواصل", 12, "#dc2626"),
    ("LOST", "فرصة ضائعة", 13, "#78716c"),
]

PIPELINE_STATUSES = [
    "NEW", "CONTACTED", "REPLIED", "INTERESTED",
    "DEMO_SCHEDULED", "TRIAL", "SUBSCRIBED", "NOT_INTERESTED",
]

INTERACTION_TYPES = [
    ("CALL", "اتصال"),
    ("WHATSAPP", "واتساب"),
    ("SMS", "رسالة"),
    ("EMAIL", "بريد"),
    ("MEETING", "اجتماع"),
    ("DEMO", "Demo"),
    ("NOTE", "ملاحظة"),
    ("SYSTEM", "نظام"),
]

PRIORITIES = [
    ("LOW", "منخفض"),
    ("MEDIUM", "متوسط"),
    ("HIGH", "عالي"),
    ("URGENT", "عاجل"),
]

DUPLICATE_LEVELS = [
    ("NONE", "لا يوجد"),
    ("EXACT", "تطابق تام"),
    ("STRONG", "تكرار قوي"),
    ("POSSIBLE", "تكرار محتمل"),
]

IMPORT_FIELD_LABELS = {
    "business_name": "اسم الشركة",
    "phone": "الهاتف",
    "owner_name": "اسم المالك",
    "governorate": "المحافظة",
    "city": "المدينة",
    "district": "المنطقة",
    "area": "الحي",
    "full_address": "العنوان الكامل",
    "instagram_url": "Instagram",
    "facebook_url": "Facebook",
    "website": "الموقع",
    "source_primary": "المصدر",
}

IMPORT_STATUS_LABELS = {
    "preview": "معاينة",
    "mapped": "ربط الأعمدة",
    "validated": "تم التحقق",
    "deduped": "فحص التكرار",
    "committed": "تم الاستيراد",
    "failed": "فشل",
}

DEFAULT_ACTIVITIES = [
    ("clothing", "Clothing", "محلات الملابس", "fa-shirt", "#6366f1"),
    ("grocery", "Grocery", "المواد الغذائية", "fa-shopping-basket", "#22c55e"),
    ("cosmetics", "Cosmetics", "كوزمتك", "fa-spa", "#ec4899"),
    ("electronics", "Electronics", "إلكترونيات", "fa-laptop", "#3b82f6"),
    ("medical-supplies", "Medical Supplies", "مستلزمات طبية", "fa-kit-medical", "#14b8a6"),
    ("construction", "Construction Materials", "مواد بناء", "fa-hard-hat", "#f97316"),
    ("wholesale", "Wholesale", "تجارة الجملة", "fa-boxes-stacked", "#8b5cf6"),
    ("restaurants", "Restaurants", "مطاعم", "fa-utensils", "#ef4444"),
    ("pharmacy", "Pharmacy", "صيدليات", "fa-pills", "#06b6d4"),
    ("other", "Other", "أخرى", "fa-store", "#64748b"),
]

IRAQ_GOVERNORATES = [
    "بغداد", "البصرة", "نينوى", "أربيل", "السليمانية", "دهوك",
    "كركوك", "الأنبار", "ديالى", "صلاح الدين", "بابل", "كربلاء",
    "النجف", "ذي قار", "ميسان", "القادسية", "واسط", "المثنى",
]
