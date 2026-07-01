PURCHASE_INVOICE_RECIPE = {
    "workflow_type": "purchase_invoice",
    "title": "مستند شراء",
    "description": "قراءة أولية لفاتورة الشراء — بدون مطابقة منتجات",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "بداية",
            "report_messages": ["تم اختيار سير مستند الشراء."],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.62, "y": 0.5},
                "speech": "أراجع فاتورة المورد...",
            },
            "next_step_id": "read_purchase_foundation",
        },
        "read_purchase_foundation": {
            "id": "read_purchase_foundation",
            "title": "قراءة أساس فاتورة الشراء",
            "handler": "document_intelligence.run_active_document",
            "report_messages": [
                "تم تجهيز أساس قراءة فاتورة الشراء. مطابقة المنتجات ستُبنى في المرحلة التالية.",
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.58, "y": 0.5},
                "speech": "أحلل بنية فاتورة الشراء...",
            },
            "next_step_id": "placeholder_mapping",
        },
        "placeholder_mapping": {
            "id": "placeholder_mapping",
            "title": "مطابقة المنتجات",
            "report_messages": ["سيتم إضافة مطابقة المنتجات في مرحلة لاحقة."],
            "open_windows": [
                {
                    "type": "assistant_notes",
                    "title": "ملاحظات LEON",
                    "placement": "bottom",
                    "position": {"x": 260, "y": 420, "width": 360, "height": 200},
                    "props": {"notes": ["مطابقة المنتجات — Phase 6", "لا إنشاء مشتريات"]},
                }
            ],
            "avatar": {
                "mode": "matching",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "المطابقة قريباً...",
            },
            "next_step_id": "complete",
        },
        "complete": {
            "id": "complete",
            "title": "اكتمال",
            "report_messages": ["اكتمل الهيكل التجريبي لمستند الشراء."],
            "avatar": {"mode": "success", "position": {"x": 0.5, "y": 0.42}, "speech": "تم."},
            "status_after_step": "completed",
        },
    },
}
