RETURN_STATEMENT_RECIPE = {
    "workflow_type": "return_statement",
    "title": "كشف راجع",
    "description": "قراءة أولية لكشف الراجع — بدون تحقق باركود",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "بداية",
            "report_messages": ["تم اختيار سير كشف الراجع."],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.62, "y": 0.5},
                "speech": "أراجع كشف المرتجعات...",
            },
            "next_step_id": "read_return_foundation",
        },
        "read_return_foundation": {
            "id": "read_return_foundation",
            "title": "قراءة أساس كشف الراجع",
            "handler": "document_intelligence.run_active_document",
            "report_messages": [
                "تم تجهيز أساس قراءة كشف الراجع. التحقق من الباركود سيُبنى في المرحلة التالية.",
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.58, "y": 0.5},
                "speech": "أحلل بنية كشف الراجع...",
            },
            "next_step_id": "placeholder_barcode",
        },
        "placeholder_barcode": {
            "id": "placeholder_barcode",
            "title": "الباركود",
            "report_messages": ["سيتم إضافة تحقق الباركود في مرحلة لاحقة."],
            "open_windows": [
                {
                    "type": "assistant_notes",
                    "title": "ملاحظات LEON",
                    "placement": "bottom",
                    "position": {"x": 260, "y": 420, "width": 360, "height": 200},
                    "props": {"notes": ["تحقق الباركود — Phase 5", "لا ترحيل مخزني"]},
                }
            ],
            "avatar": {
                "mode": "asking_user",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "الباركود قريباً...",
            },
            "next_step_id": "complete",
        },
        "complete": {
            "id": "complete",
            "title": "اكتمال",
            "report_messages": ["اكتمل الهيكل التجريبي لكشف الراجع."],
            "avatar": {"mode": "success", "position": {"x": 0.5, "y": 0.42}, "speech": "تم."},
            "status_after_step": "completed",
        },
    },
}
