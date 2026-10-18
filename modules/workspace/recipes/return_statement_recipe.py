RETURN_STATEMENT_RECIPE = {
    "workflow_type": "return_statement",
    "title": "كشف راجع",
    "description": "تحليل كشف الراجع ومطابقته، ثم تنفيذ الطلبات المؤكدة وإعادة مخزونها بعد الموافقة",
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
                "progress": 5,
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
                "تمت قراءة كشف الراجع واستخراج النص والجداول المتاحة للمراجعة.",
            ],
            "avatar": {
                "mode": "reading_document",
                "progress": 12,
                "position": {"x": 0.58, "y": 0.5},
                "speech": "أحلل بنية كشف الراجع...",
            },
            "next_step_id": "run_return_analysis",
        },
        "run_return_analysis": {
            "id": "run_return_analysis",
            "title": "تحليل ومطابقة كشف الراجع",
            "handler": "return_analysis.run_readonly",
            "report_messages": ["بدأت مطابقة صفوف الراجع مع الطلبات في النظام."],
            "avatar": {
                "mode": "matching",
                "progress": 60,
                "position": {"x": 0.55, "y": 0.5},
                "speech": "أطابق صفوف الراجع مع الطلبات وأتحقق من الباركود...",
            },
            "next_step_id": "placeholder_barcode",
        },
        "placeholder_barcode": {
            "id": "placeholder_barcode",
            "title": "مراجعة وتنفيذ بيانات الراجع",
            "report_messages": ["تم تجهيز تقرير كشف الراجع. راجع الصفوف ثم نفّذ الطلبات المطابقة بعد الموافقة."],
            "open_windows": [
                {
                    "type": "assistant_notes",
                    "title": "ملاحظات LEON",
                    "placement": "bottom",
                    "position": {"x": 260, "y": 420, "width": 360, "height": 200},
                    "props": {"notes": ["راجع الصفوف المطابقة وغير المطابقة، ويمكنك حذف أي صف غير مطلوب.", "التنفيذ يحتاج موافقة صريحة ويعيد الأصناف للمخزون مرة واحدة فقط."]},
                }
            ],
            "avatar": {
                "mode": "success",
                "progress": 98,
                "position": {"x": 0.5, "y": 0.5},
                "speech": "اكتملت قراءة كشف الراجع، والنتائج جاهزة للمراجعة.",
            },
            "next_step_id": "complete",
        },
        "complete": {
            "id": "complete",
            "title": "اكتمال",
            "report_messages": ["اكتمل تحليل كشف الراجع. راجع التقرير والصفوف ثم نفّذ الطلبات المؤكدة عند الحاجة."],
            "avatar": {"mode": "success", "progress": 100, "position": {"x": 0.5, "y": 0.42}, "speech": "اكتمل تحليل كشف الراجع، والتقرير جاهز للمراجعة والتنفيذ."},
            "status_after_step": "completed",
        },
    },
}
