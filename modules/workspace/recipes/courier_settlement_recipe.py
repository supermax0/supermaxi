COURIER_SETTLEMENT_RECIPE = {
    "workflow_type": "courier_settlement",
    "title": "كشف تسديد شركة توصيل",
    "description": "تحليل قراءة فقط لكشف التسوية — بدون ترحيل",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "بداية",
            "report_messages": ["تم اختيار سير كشف تسديد شركة التوصيل."],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.62, "y": 0.5},
                "speech": "أراجع كشف التسوية...",
            },
            "next_step_id": "ensure_document_intelligence",
        },
        "ensure_document_intelligence": {
            "id": "ensure_document_intelligence",
            "title": "فهم المستند",
            "handler": "document_intelligence.run_active_document",
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.58, "y": 0.5},
                "speech": "أقرأ المستند أولاً...",
            },
            "next_step_id": "run_readonly_courier_analysis",
        },
        "run_readonly_courier_analysis": {
            "id": "run_readonly_courier_analysis",
            "title": "تحليل قراءة فقط",
            "handler": "courier_analysis.run_readonly",
            "scan_overlay": {"active": True, "progress": 0, "scanMode": "preview", "currentPage": 1},
            "avatar": {
                "mode": "matching",
                "position": {"x": 0.55, "y": 0.5},
                "speech": "أطابق الصفوف مع الطلبات قراءة فقط...",
            },
            "next_step_id": "review_results",
        },
        "review_results": {
            "id": "review_results",
            "title": "مراجعة النتائج",
            "report_messages": [
                "هذه نتائج قراءة فقط، لا يوجد ترحيل.",
                "راجع ملخص الكشف والمشاكل والمعاينة المالية.",
            ],
            "avatar": {
                "mode": "success",
                "position": {"x": 0.5, "y": 0.48},
                "speech": "اكتمل التحليل — راجع النتائج.",
            },
            "status_after_step": "waiting_user",
            "next_step_id": "complete",
        },
        "complete": {
            "id": "complete",
            "title": "اكتمال",
            "report_messages": ["اكتمل تحليل كشف التسديد قراءة فقط."],
            "avatar": {"mode": "success", "position": {"x": 0.5, "y": 0.42}, "speech": "تم."},
            "status_after_step": "completed",
        },
    },
}
