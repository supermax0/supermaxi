from io import BytesIO

from openpyxl import load_workbook

from utils.leon_presentation import build_leon_presentation, export_presentation


def _sales_presentation():
    return build_leon_presentation(
        session_id=77,
        message="اعرض مبيعات اليوم",
        reply="مبيعات اليوم جاهزة من النظام.",
        tool_runs=[
            {
                "name": "get_sales_summary",
                "arguments": {"date_from": "2026-08-10", "date_to": "2026-08-10"},
                "result": {
                    "period": "2026-08-10",
                    "orders_count": 18,
                    "total_sales": 1_240_000,
                    "collected_cash": 980_000,
                    "remaining_receivable": 260_000,
                    "breakdown": {
                        "الفرع الرئيسي": {"orders": 10, "total": 800_000},
                        "فرع الكرادة": {"orders": 8, "total": 440_000},
                    },
                },
            }
        ],
        local_findings={"snapshot": {}},
    )


def test_sales_tool_builds_widgets_and_downloads():
    presentation = _sales_presentation()
    assert presentation["version"] == 1
    assert presentation["widgets"][0]["type"] == "metric_grid"
    assert presentation["widgets"][0]["items"][1]["value"] == 1_240_000
    assert presentation["widgets"][1]["type"] == "bar_list"
    assert presentation["files"][0]["url"] == "/assistant/api/chat/sessions/77/export.xlsx"


def test_restricted_tool_never_exposes_rows():
    presentation = build_leon_presentation(
        session_id=9,
        message="اعرض الموردين",
        reply="غير متاح حسب صلاحياتك.",
        tool_runs=[{"name": "get_supplier_debts", "result": {"restricted": True, "message": "غير متاح حسب صلاحياتك"}}],
        local_findings={"snapshot": {}},
    )
    assert presentation["widgets"] == [
        {
            "type": "notice",
            "tone": "warning",
            "title": "النتيجة غير متاحة",
            "message": "غير متاح حسب صلاحياتك",
        }
    ]


def test_exports_create_real_files():
    presentation = _sales_presentation()

    csv_payload, csv_type, csv_name = export_presentation(presentation, "csv")
    assert csv_payload.startswith(b"\xef\xbb\xbf")
    assert csv_type.startswith("text/csv")
    assert csv_name.endswith(".csv")

    xlsx_payload, xlsx_type, xlsx_name = export_presentation(presentation, "xlsx")
    workbook = load_workbook(BytesIO(xlsx_payload), read_only=True)
    assert workbook.active.title == "ملخص LEON"
    assert "spreadsheetml" in xlsx_type
    assert xlsx_name.endswith(".xlsx")

    pdf_payload, pdf_type, pdf_name = export_presentation(presentation, "pdf")
    assert pdf_payload.startswith(b"%PDF")
    assert pdf_type == "application/pdf"
    assert pdf_name.endswith(".pdf")
