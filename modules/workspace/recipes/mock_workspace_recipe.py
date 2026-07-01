MOCK_WORKSPACE_RECIPE = {
    "workflow_type": "mock_workspace",
    "title": "تجربة مساحة العمل",
    "description": "سير تجريبي لمحرك Workflow — بدون ترحيل مالي",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "تهيئة الجلسة",
            "description": "فتح النوافذ الأساسية",
            "report_messages": [
                "تم تشغيل محرك Workflow التجريبي.",
                "سيتم تشغيل الخطوات بشكل حتمي.",
            ],
            "ensure_windows": [
                {"type": "document_viewer", "title": "معاينة المستند", "placement": "right"},
                {"type": "live_report", "title": "تقرير التحليل", "placement": "left"},
            ],
            "avatar": {
                "mode": "idle",
                "position": {"x": 0.5, "y": 0.55},
                "speech": "أبدأ تجربة المساحة الآن.",
            },
            "next_step_id": "preview_document",
            "status_after_step": "running",
        },
        "preview_document": {
            "id": "preview_document",
            "title": "معاينة المستند",
            "report_messages": ["تم تجهيز نافذة معاينة المستند."],
            "update_windows": [
                {
                    "type": "document_viewer",
                    "patch": {"status": "streaming"},
                }
            ],
            "scan_overlay": {"active": True, "progress": 0, "scanMode": "preview", "currentPage": 1},
            "avatar": {
                "mode": "reading_document",
                "position": {"x": 0.62, "y": 0.5},
                "speech": "أراجع المستند المرفوع...",
            },
            "next_step_id": "write_report",
        },
        "write_report": {
            "id": "write_report",
            "title": "كتابة التقرير",
            "report_messages": [
                "يتم الآن بث التقرير من خلال Workflow Engine.",
                "هذه تجربة Runtime فقط ولا يوجد تحليل مالي حقيقي.",
            ],
            "scan_overlay": {"active": False, "progress": 100, "scanMode": "preview"},
            "avatar": {
                "mode": "writing_report",
                "position": {"x": 0.32, "y": 0.48},
                "speech": "أكتب التقرير...",
            },
            "next_step_id": "open_notes",
        },
        "open_notes": {
            "id": "open_notes",
            "title": "ملاحظات LEON",
            "report_messages": [
                "تم فتح نافذة ملاحظات LEON بواسطة Window Orchestrator.",
            ],
            "open_windows": [
                {
                    "type": "assistant_notes",
                    "title": "ملاحظات LEON",
                    "placement": "bottom",
                    "position": {"x": 280, "y": 420, "width": 340, "height": 220},
                    "props": {
                        "notes": [
                            "محرك Workflow يعمل بشكل حتمي.",
                            "المرحلة 3 — Runtime فقط.",
                        ]
                    },
                }
            ],
            "avatar": {"mode": "success", "position": {"x": 0.5, "y": 0.42}, "speech": "تقدم ممتاز!"},
            "next_step_id": "approval_demo",
        },
        "approval_demo": {
            "id": "approval_demo",
            "title": "موافقة تجريبية",
            "report_messages": [
                "هذه موافقة تجريبية فقط ولا تنفذ أي ترحيل.",
            ],
            "open_windows": [
                {
                    "type": "approval_panel",
                    "title": "موافقة مطلوبة",
                    "placement": "bottom",
                    "position": {"x": 200, "y": 360, "width": 400, "height": 240},
                    "props": {
                        "demo": True,
                        "message": "هذه موافقة تجريبية في Phase 3 ولا تنفذ أي ترحيل.",
                    },
                }
            ],
            "avatar": {
                "mode": "waiting_approval",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "أنتظر موافقتك للمتابعة...",
            },
            "requires_approval": True,
            "next_step_id": "complete",
            "status_after_step": "waiting_approval",
        },
        "complete": {
            "id": "complete",
            "title": "اكتمال",
            "report_messages": ["اكتمل Workflow التجريبي بنجاح."],
            "avatar": {
                "mode": "success",
                "position": {"x": 0.5, "y": 0.42},
                "speech": "اكتملت التجربة بنجاح!",
                "progress": 1,
            },
            "status_after_step": "completed",
        },
    },
}
