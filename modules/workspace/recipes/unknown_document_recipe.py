UNKNOWN_DOCUMENT_RECIPE = {
    "workflow_type": "unknown_document",
    "title": "مستند غير معروف",
    "description": "تحليل أولي ثم اختيار نوع العمل",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "بداية",
            "report_messages": ["سأبدأ بقراءة المستند مبدئياً لاقتراح نوع العمل."],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "أبدأ بفهم المستند...",
            },
            "next_step_id": "run_document_intelligence",
        },
        "run_document_intelligence": {
            "id": "run_document_intelligence",
            "title": "فهم المستند",
            "handler": "document_intelligence.run_active_document",
            "report_messages": [],
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.55, "y": 0.5},
                "speech": "أقرأ المستند مبدئياً...",
            },
            "resolve_next_step": {
                "metadata_key": "last_intelligence.document_kind",
                "when": {"unknown_document": "select_workflow"},
                "default": "suggest_workflow",
            },
        },
        "suggest_workflow": {
            "id": "suggest_workflow",
            "title": "اقتراح نوع العمل",
            "requires_user_input": True,
            "allowed_inputs": [
                "mock_workspace",
                "courier_settlement",
                "return_statement",
                "purchase_invoice",
            ],
            "report_messages": [
                "تم اقتراح نوع المستند بناءً على القراءة الأولية.",
                "يرجى تأكيد أو تغيير نوع العمل من النافذة.",
            ],
            "open_windows": [
                {
                    "type": "workflow_selector",
                    "title": "اختيار نوع العمل",
                    "placement": "bottom",
                    "position": {"x": 180, "y": 400, "width": 420, "height": 260},
                    "props": {"useRecommendedFromSession": True},
                },
            ],
            "avatar": {
                "mode": "asking_user",
                "position": {"x": 0.5, "y": 0.52},
                "speech": "هل نوع المستند المقترح صحيح؟",
            },
            "next_step_id": "complete",
            "status_after_step": "waiting_user",
        },
        "select_workflow": {
            "id": "select_workflow",
            "title": "اختيار نوع العمل",
            "requires_user_input": True,
            "allowed_inputs": [
                "mock_workspace",
                "courier_settlement",
                "return_statement",
                "purchase_invoice",
            ],
            "report_messages": [
                "لم أتمكن من تحديد نوع المستند بثقة كافية.",
                "يرجى اختيار نوع العمل يدوياً.",
            ],
            "open_windows": [
                {
                    "type": "workflow_selector",
                    "title": "اختيار نوع العمل",
                    "placement": "bottom",
                    "position": {"x": 180, "y": 400, "width": 420, "height": 260},
                },
            ],
            "avatar": {
                "mode": "asking_user",
                "position": {"x": 0.5, "y": 0.52},
                "speech": "ما نوع هذا المستند؟",
            },
            "next_step_id": "complete",
            "status_after_step": "waiting_user",
        },
        "complete": {
            "id": "complete",
            "title": "تم التسجيل",
            "report_messages": [
                "تم تسجيل اختيار المستخدم. لا ترحيل — Phase 4 فقط.",
            ],
            "avatar": {"mode": "success", "position": {"x": 0.5, "y": 0.45}, "speech": "تم التسجيل."},
            "status_after_step": "completed",
        },
    },
}
