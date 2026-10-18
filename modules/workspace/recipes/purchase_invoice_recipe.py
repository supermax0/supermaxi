PURCHASE_INVOICE_RECIPE = {
    "workflow_type": "purchase_invoice",
    "title": "فاتورة شراء ذكية",
    "description": "تحليل فاتورة الشراء ومطابقة المورد والمنتجات ثم التنفيذ بعد موافقة صريحة",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "بداية",
            "report_messages": ["تم اختيار تحليل فاتورة الشراء الذكي."],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة فاتورة الشراء", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.62, "y": 0.5},
                "speech": "أقرأ بيانات فاتورة المورد بدقة...",
                "progress": 5,
            },
            "next_step_id": "read_purchase_foundation",
        },
        "read_purchase_foundation": {
            "id": "read_purchase_foundation",
            "title": "قراءة فاتورة الشراء",
            "handler": "document_intelligence.run_active_document",
            "report_messages": ["تم استخراج المورد ورقم الفاتورة والأصناف والكميات والأسعار."],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.58, "y": 0.5},
                "speech": "أحلل بنية الفاتورة وأتحقق من المجاميع...",
                "progress": 20,
            },
            "next_step_id": "match_purchase_entities",
        },
        "match_purchase_entities": {
            "id": "match_purchase_entities",
            "title": "مطابقة المورد والمنتجات",
            "handler": "purchase_analysis.run",
            "report_messages": ["تمت مطابقة بيانات الفاتورة مع الموردين والمنتجات وتجهيز نافذة المراجعة."],
            "avatar": {
                "mode": "matching",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "أطابق الباركود والرموز والأسماء وأحدد المنتجات الجديدة.",
                "progress": 78,
            },
            "next_step_id": "complete",
        },
        "complete": {
            "id": "complete",
            "title": "جاهز للمراجعة",
            "report_messages": ["اكتمل التحليل والمطابقة. راجع النتائج ثم اضغط اعتماد لإضافة المخزون."],
            "avatar": {
                "mode": "awaiting_approval",
                "position": {"x": 0.5, "y": 0.42},
                "speech": "التحليل جاهز. راجع المطابقات والمنتجات الجديدة قبل التنفيذ.",
                "progress": 100,
            },
            "status_after_step": "completed",
        },
    },
}
