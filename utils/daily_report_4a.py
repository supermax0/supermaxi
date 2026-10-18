"""بيانات نموذج التقرير اليومي 4A — ورقة يدوية فارغة للطباعة."""

from __future__ import annotations

from datetime import date, datetime

ARABIC_WEEKDAYS = (
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)

SUPPLIER_ROWS = 8
EXPENSE_ROWS_PER_COL = 8
PURCHASE_ROWS = 8
NOTES_LINES = 16


def _blank_rows(count: int, blank: dict) -> list[dict]:
    return [dict(blank) for _ in range(count)]


def _arabic_weekday(report_date: date) -> str:
    return ARABIC_WEEKDAYS[report_date.weekday()]


def build_daily_report_4a_data(report_date: date) -> dict:
    """نموذج فارغ للكتابة اليدوية — التاريخ واليوم فقط من النظام."""
    blank_supplier = {"name": "", "document_no": "", "payment": ""}
    blank_expense = {"description": "", "amount": ""}
    blank_purchase = {"supplier_name": "", "amount": ""}

    return {
        "report_date": report_date,
        "report_date_label": report_date.strftime("%Y-%m-%d"),
        "weekday_label": _arabic_weekday(report_date),
        "title": "التقرير اليومي",
        "form_code": "4A",
        "safe_amount_label": "",
        "total_expenses_label": "",
        "remaining_label": "",
        "suppliers": _blank_rows(SUPPLIER_ROWS, blank_supplier),
        "expense_left": _blank_rows(EXPENSE_ROWS_PER_COL, blank_expense),
        "expense_right": _blank_rows(EXPENSE_ROWS_PER_COL, blank_expense),
        "purchases": _blank_rows(PURCHASE_ROWS, blank_purchase),
        "notes_lines": NOTES_LINES,
        "generated_at": datetime.utcnow(),
    }
