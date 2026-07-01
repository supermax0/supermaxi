COURIER_SETTLEMENT_RECIPE = {
    "workflow_type": "courier_settlement",
    "title": "كشف تسديد شركة توصيل",
    "description": "قراءة أولية لكشف التسوية — بدون مطابقة",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "بداية",
            "report_messages": [
                "تم اختيار سير كشف تسديد شركة التوصيل.",
            ],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.62, "y": 0.5},
                "speech": "أراجع كشف التسوية...",
            },
            "next_step_id": "read_statement_foundation",
        },
        "read_statement_foundation": {
            "id": "read_statement_foundation",
            "title": "قراءة أساس كشف التسوية",
            "handler": "document_intelligence.run_active_document",
            "report_messages": [
                "تم تجهيز أساس قراءة كشف التسوية. المطابقة الحقيقية ستُبنى في المرحلة التالية.",
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.58, "y": 0.5},
                "speech": "أحلل بنية كشف التسوية...",
            },
            "next_step_id": "placeholder_review",
        },
        "placeholder_review": {
            "id": "placeholder_review",
            "title": "مراجعة تجريبية",
            "report_messages": ["لا يوجد مطابقة طلبات في Phase 4."],
            "open_windows": [
                {
                    "type": "assistant_notes",
                    "title": "ملاحظات LEON",
                    "placement": "bottom",
                    "position": {"x": 260, "y": 420, "width": 360, "height": 200},
                    "props": {"notes": ["مطابقة الطلبات — قريباً", "الترحيل — معطل"]},
                },
                {
                    "type": "approval_panel",
                    "title": "موافقة مطلوبة",
                    "placement": "bottom",
                    "position": {"x": 200, "y": 340, "width": 400, "height": 220},
                    "props": {"demo": True, "message": "موافقة تجريبية — لا ترحيل."},
                },
            ],
            "avatar": {
                "mode": "waiting_approval",
                "position": {"x": 0.5, "y": 0.48},
                "speech": "موافقة تجريبية فقط.",
            },
            "requires_approval": True,
            "next_step_id": "complete",
            "status_after_step": "waiting_approval",
        },
        "complete": {
            "id": "complete",
            "title": "اكتمال",
            "report_messages": ["اكتمل الهيكل التجريبي لكشف التسوية."],
            "avatar": {"mode": "success", "position": {"x": 0.5, "y": 0.42}, "speech": "تم."},
            "status_after_step": "completed",
        },
    },
}
