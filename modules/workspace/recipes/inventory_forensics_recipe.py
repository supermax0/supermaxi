INVENTORY_FORENSICS_RECIPE = {
    "workflow_type": "inventory_forensics",
    "title": "المحقق الذكي للمخزون",
    "description": "تتبع دخول وخروج كل منتج وقطعة وكشف الفروقات بين الفروع",
    "initial_step_id": "start",
    "steps": {
        "start": {
            "id": "start",
            "title": "تهيئة تدقيق المخزون",
            "report_messages": ["تم تشغيل المحقق الذكي لحركات المخزون."],
            "avatar": {
                "mode": "matching",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "أجهز سجل الحركات والفروع والمنتجات للتدقيق.",
                "progress": 35,
            },
            "next_step_id": "open_forensics",
        },
        "open_forensics": {
            "id": "open_forensics",
            "title": "فتح نافذة التحقيق",
            "handler": "inventory_forensics.open",
            "report_messages": ["اختر المنتج والفرع والفترة من نافذة التحقيق."],
            "avatar": {
                "mode": "waiting_user",
                "position": {"x": 0.5, "y": 0.5},
                "speech": "اختر المنتج الذي تشك بكميته، وأنا أعيد بناء حركاته قطعةً قطعة.",
                "progress": 100,
            },
            "next_step_id": "complete",
        },
        "complete": {
            "id": "complete",
            "title": "جاهز للتحقيق",
            "report_messages": ["نافذة المحقق جاهزة للبحث والتحليل."],
            "avatar": {
                "mode": "waiting_user",
                "position": {"x": 0.5, "y": 0.46},
                "speech": "حدد المنتج واضغط تحليل الحركات.",
                "progress": 100,
            },
            "status_after_step": "completed",
        },
    },
}
