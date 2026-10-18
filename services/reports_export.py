"""Excel and printable (PDF) output for the ten reports.

Both formats use the same column specs and pull every row through
reports_service.section_report, so an export always equals what the screen
shows for the same filters and permissions.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Callable

from services import reports_service as rs

MAX_EXPORT_ROWS = 20_000

SECTION_TITLES = {
    "sales": "تقرير المبيعات",
    "profit": "الأرباح والخسائر",
    "expenses": "تقرير المصاريف",
    "cash": "النقد والبنوك",
    "customers": "العملاء والديون",
    "purchases": "المشتريات والموردين",
    "inventory": "تقرير المخزون",
    "invoices": "تقرير الفواتير",
    "employees": "تقرير الموظفين",
    "cashflow": "التدفق النقدي",
    "equity": "المركز المالي وأين ذهبت الأرباح",
}

PERIOD_LABELS = {
    "today": "اليوم",
    "yesterday": "أمس",
    "this_week": "هذا الأسبوع",
    "this_month": "هذا الشهر",
    "last_month": "الشهر السابق",
    "this_year": "هذه السنة",
    "custom": "فترة مخصصة",
}

Column = tuple[str, str, bool]  # (key, Arabic header, is_money)

INVOICE_COLUMNS: list[Column] = [
    ("date", "التاريخ", False),
    ("id", "رقم الفاتورة", False),
    ("customer", "العميل", False),
    ("employee", "الموظف", False),
    ("branch", "الفرع", False),
    ("gross", "الإجمالي", True),
    ("discount", "الخصم", True),
    ("total", "الصافي", True),
    ("paid", "المدفوع", True),
    ("remaining", "المتبقي", True),
    ("state", "الحالة", False),
]

COLUMNS: dict[str, dict[str, list[Column]]] = {
    "sales": {"": INVOICE_COLUMNS},
    "invoices": {"": INVOICE_COLUMNS},
    "expenses": {
        "": [
            ("date", "التاريخ", False),
            ("id", "رقم العملية", False),
            ("category", "التصنيف", False),
            ("description", "الوصف", False),
            ("amount", "المبلغ", True),
            ("employee", "الموظف", False),
            ("branch", "الفرع", False),
            ("payment_method", "طريقة الدفع", False),
            ("account", "الحساب", False),
        ]
    },
    "cash": {
        "": [
            ("date", "التاريخ", False),
            ("account", "الحساب", False),
            ("type", "نوع الحركة", False),
            ("reference", "المرجع", False),
            ("reason", "البيان", False),
            ("cash_in", "داخل", True),
            ("cash_out", "خارج", True),
            ("balance", "الرصيد", True),
        ]
    },
    "customers": {
        "customers": [
            ("name", "العميل", False),
            ("phone", "الهاتف", False),
            ("orders", "عدد الطلبات", False),
            ("purchases", "إجمالي المشتريات", True),
            ("paid", "إجمالي المدفوع", True),
            ("debt", "الدين الحالي", True),
            ("last_purchase", "آخر عملية شراء", False),
        ],
        "debts": [
            ("customer", "العميل", False),
            ("phone", "الهاتف", False),
            ("invoice_id", "الفاتورة", False),
            ("total", "إجمالي الدين", True),
            ("paid", "المدفوع", True),
            ("remaining", "المتبقي", True),
            ("due_date", "تاريخ الاستحقاق", False),
            ("days_overdue", "أيام التأخير", False),
        ],
    },
    "purchases": {
        "purchases": [
            ("date", "التاريخ", False),
            ("invoice_no", "الفاتورة", False),
            ("supplier", "المورد", False),
            ("amount", "المبلغ", True),
            ("paid", "المدفوع", True),
            ("remaining", "المتبقي", True),
            ("status", "الحالة", False),
        ],
        "suppliers": [
            ("name", "المورد", False),
            ("phone", "الهاتف", False),
            ("purchases", "مشتريات الفترة", True),
            ("invoices", "عدد الفواتير", False),
            ("total_paid", "إجمالي المدفوع", True),
            ("balance", "الرصيد المستحق", True),
            ("last_purchase", "آخر عملية شراء", False),
        ],
    },
    "inventory": {
        "stock": [
            ("name", "المنتج", False),
            ("sku", "SKU", False),
            ("category", "التصنيف", False),
            ("quantity", "الكمية", False),
            ("average_cost", "متوسط التكلفة", True),
            ("value", "قيمة المخزون", True),
            ("sale_price", "سعر البيع", True),
        ],
        "low": [
            ("name", "المنتج", False),
            ("quantity", "الكمية الحالية", False),
            ("threshold", "الحد الأدنى", False),
            ("shortage", "النقص", False),
        ],
        "stagnant": [
            ("name", "المنتج", False),
            ("quantity", "الكمية", False),
            ("value", "رأس المال المجمد", True),
            ("days", "أيام بلا بيع", False),
            ("last_sale", "آخر بيع", False),
        ],
        "movements": [
            ("date", "التاريخ", False),
            ("product", "المنتج", False),
            ("type", "نوع الحركة", False),
            ("direction", "الاتجاه", False),
            ("quantity", "الكمية", False),
            ("value", "القيمة", True),
            ("source", "المصدر", False),
        ],
    },
    "employees": {
        "": [
            ("name", "الموظف", False),
            ("sales", "المبيعات", True),
            ("orders", "عدد الطلبات", False),
            ("average", "متوسط الطلب", True),
            ("collections", "التحصيلات", True),
            ("discounts", "الخصومات", True),
            ("returns", "المرتجعات", True),
            ("profit", "الربح", True),
            ("commission", "العمولة", True),
        ]
    },
    "cashflow": {
        "": [
            ("key", "الفترة", False),
            ("inflow", "الداخل", True),
            ("outflow", "الخارج", True),
            ("net", "الصافي", True),
        ]
    },
    "equity": {
        "": [
            ("label", "البند", False),
            ("amount", "المبلغ", True),
        ]
    },
    "profit": {
        "": [
            ("label", "البند", False),
            ("amount", "المبلغ", True),
        ]
    },
}


def _view_key(section: str, args) -> str:
    specs = COLUMNS[section]
    if "" in specs:
        return ""
    key = args.get("tab") or next(iter(specs))
    return key if key in specs else next(iter(specs))


def profit_lines(report: dict[str, Any]) -> list[dict[str, Any]]:
    st = report["statement"]
    return [
        {"label": "الإيرادات", "amount": st["gross_revenue"]},
        {"label": "(-) المرتجعات", "amount": -st["returns"]},
        {"label": "(-) الخصومات", "amount": -st["discounts"]},
        {"label": "= صافي الإيرادات", "amount": st["net_revenue"]},
        {"label": "(-) تكلفة البضاعة المباعة", "amount": -st["cogs"]},
        {"label": "= إجمالي الربح", "amount": st["gross_profit"]},
        {"label": "(-) المصاريف التشغيلية", "amount": -st["operating_expenses"]},
        *([{"label":"(-) صافي خسائر المخزون / العكس","amount":-st.get('inventory_losses',0)}] if st.get('inventory_losses') else []),
        {"label": "(-) الاستهلاك ومصاريف أخرى", "amount": -(st["other_expenses"]-st.get('inventory_losses',0))},
        {"label": "= صافي الربح", "amount": st["net_profit"]},
    ]


def equity_lines(report: dict[str, Any]) -> list[dict[str, Any]]:
    pos, p = report["position"], report["profit"]
    rows: list[dict[str, Any]] = [{"label": "— ما تملكه الشركة الآن (الأصول) —", "amount": None}]
    rows += [{"label": a["label"], "amount": a["amount"]} for a in pos["assets"]]
    rows.append({"label": "= إجمالي الأصول", "amount": pos["total_assets"]})
    rows.append({"label": "— ما على الشركة (الالتزامات) —", "amount": None})
    rows += [{"label": a["label"], "amount": a["amount"]} for a in pos["liabilities"]]
    rows.append({"label": "= إجمالي الالتزامات", "amount": pos["total_liabilities"]})
    rows.append({"label": "= حقوق الملكية (الأصول − الالتزامات)", "amount": pos["equity"]})
    rows.append({"label": "— أين ذهب ربح الفترة —", "amount": None})
    rows.append({"label": "صافي ربح الفترة", "amount": p["net_profit"]})
    rows += [{"label": b["label"], "amount": b["amount"]} for b in report["bridge"]]
    rows.append({"label": "= التغيّر الفعلي في النقد", "amount": report["cash"]["net_change"]})
    return rows


def collect(section: str, filters: rs.ReportFilters, args) -> tuple[dict[str, Any], list[dict[str, Any]], list[Column]]:
    """Report + every row (all pages) + the columns for this view."""
    view = _view_key(section, args)
    columns = list(COLUMNS[section][view])
    if section == "employees" and not rs.can_view("profit"):
        columns = [c for c in columns if c[0] != "profit"]
    params: dict[str, Any] = {k: args.get(k) for k in args.keys()}
    params["page_size"] = rs.PAGE_SIZE_MAX
    params["page"] = 1
    report = rs.section_report(section, filters, params)
    if section == "profit":
        return report, profit_lines(report), columns
    if section == "equity":
        return report, equity_lines(report), columns
    if section == "cashflow":
        return report, report["series"], columns
    rows = list(report.get("rows") or [])
    pagination = report.get("pagination")
    while pagination and pagination["page"] < pagination["total_pages"] and len(rows) < MAX_EXPORT_ROWS:
        params["page"] = pagination["page"] + 1
        nxt = rs.section_report(section, filters, params)
        rows.extend(nxt.get("rows") or [])
        pagination = nxt.get("pagination")
    return report, rows[:MAX_EXPORT_ROWS], columns


METRIC_LABELS = {
    "gross": "إجمالي المبيعات",
    "net": "صافي المبيعات",
    "invoices": "عدد الفواتير",
    "items": "عدد المنتجات المباعة",
    "average": "متوسط الفاتورة",
    "discounts": "الخصومات",
    "returns": "المرتجعات",
    "cogs": "تكلفة البضاعة المباعة",
    "gross_profit": "إجمالي الربح",
    "total": "الإجمالي",
    "count": "العدد",
    "cash_in": "إجمالي المقبوضات",
    "cash_out": "إجمالي المدفوعات",
    "opening": "الرصيد الافتتاحي",
    "closing": "الرصيد الختامي",
    "transfers": "التحويلات بين الحسابات",
    "credit_sales": "المبيعات الآجلة",
    "collections": "التحصيلات",
    "receivables": "ديون العملاء",
    "due_today": "المستحق اليوم",
    "overdue": "المتأخر",
    "amount": "إجمالي المشتريات",
    "paid": "المدفوع",
    "remaining": "المتبقي",
    "quantity": "الكمية",
    "supplier_debts": "ديون الموردين",
    "value": "قيمة المخزون",
    "low_stock": "المنتجات الناقصة",
    "stagnant": "المنتجات الراكدة",
    "stagnant_value": "رأس المال المجمد",
    "partial": "مدفوعة جزئياً",
    "credit": "آجلة",
    "cancelled": "ملغاة",
    "returned": "مرتجعة",
    "outstanding": "المتبقي للتحصيل",
}


def summary_items(section: str, report: dict[str, Any]) -> list[tuple[str, Any]]:
    if section == "cashflow":
        f = report["flow"]
        return [
            ("الرصيد الافتتاحي", f["opening"]),
            ("إجمالي التدفقات الداخلة", f["inflow"]),
            ("إجمالي التدفقات الخارجة", f["outflow"]),
            ("صافي التحويلات بين الحسابات", f["net_transfers"]),
            ("الرصيد النقدي الختامي", f["closing"]),
        ]
    if section == "employees":
        return [(METRIC_LABELS.get(k, k), v) for k, v in report["totals"].items()]
    if section == "equity":
        return [("حقوق الملكية", report["position"]["equity"]), ("صافي ربح الفترة", report["profit"]["net_profit"]),
                ("التغيّر في النقد", report["cash"]["net_change"])]
    if section == "profit":
        m = report["margins"]
        return [
            ("هامش الربح الإجمالي %", m["gross_margin_pct"]),
            ("هامش صافي الربح %", m["net_margin_pct"]),
        ]
    metrics = report.get("metrics") or {}
    return [
        (METRIC_LABELS[k], v)
        for k, v in metrics.items()
        if k in METRIC_LABELS and isinstance(v, (int, float)) and v is not None
    ]


def filter_lines(filters: rs.ReportFilters, branch_name: str | None, employee_name: str | None) -> list[tuple[str, str]]:
    return [
        ("الفترة", f"{PERIOD_LABELS.get(filters.period, filters.period)}: {filters.date_from} — {filters.date_to}"),
        ("الفرع", branch_name or "كل الفروع المسموحة"),
        ("الموظف", employee_name or "كل الموظفين"),
        ("تاريخ التصدير", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]


def to_xlsx(
    section: str,
    report: dict[str, Any],
    rows: list[dict[str, Any]],
    columns: list[Column],
    meta_lines: list[tuple[str, str]],
    company: str,
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    summary = wb.active
    summary.title = "الملخص"
    summary.sheet_view.rightToLeft = True
    summary.append([company])
    summary["A1"].font = Font(bold=True, size=14)
    summary.append([SECTION_TITLES[section]])
    summary["A2"].font = Font(bold=True, size=12)
    summary.append([])
    for label, value in meta_lines:
        summary.append([label, value])
    summary.append([])
    for label, value in summary_items(section, report):
        summary.append([label, value])
        summary.cell(row=summary.max_row, column=2).number_format = "#,##0"
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 34

    data = wb.create_sheet("البيانات")
    data.sheet_view.rightToLeft = True
    data.append([header for _key, header, _money in columns])
    head_fill = PatternFill("solid", fgColor="EDE9FE")
    for cell in data[1]:
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        data.append([row.get(key) for key, _h, _m in columns])
    for index, (_key, header, money) in enumerate(columns, start=1):
        letter = data.cell(row=1, column=index).column_letter
        data.column_dimensions[letter].width = max(12, min(40, len(header) + 8))
        if money:
            for (cell,) in data.iter_rows(min_row=2, min_col=index, max_col=index):
                cell.number_format = "#,##0"
    if rows and section not in ("profit", "equity"):
        data.append([])
        totals = ["الإجمالي"] + [
            sum(int(r.get(key) or 0) for r in rows) if money and key not in ("balance",) else None
            for key, _h, money in columns[1:]
        ]
        data.append(totals)
        for cell in data[data.max_row]:
            cell.font = Font(bold=True)
            cell.number_format = "#,##0"
    data.freeze_panes = "A2"
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _fmt(value: Any, money: bool) -> str:
    if value is None:
        return "—"
    if money and isinstance(value, (int, float)):
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def to_html(
    section: str,
    report: dict[str, Any],
    rows: list[dict[str, Any]],
    columns: list[Column],
    meta_lines: list[tuple[str, str]],
    company: str,
    logo_url: str | None,
    render: Callable[..., str],
) -> str:
    totals = {
        key: sum(int(r.get(key) or 0) for r in rows) for key, _h, money in columns if money and key != "balance"
    }
    return render(
        "reports_v2_print.html",
        title=SECTION_TITLES[section],
        company=company,
        logo_url=logo_url,
        meta_lines=meta_lines,
        summary=[(label, _fmt(value, True)) for label, value in summary_items(section, report)],
        columns=columns,
        rows=[[_fmt(r.get(key), money) for key, _h, money in columns] for r in rows],
        totals=[] if section in ("profit", "equity") else [(_fmt(totals[key], True) if key in totals else "") for key, _h, _m in columns],
        truncated=len(rows) >= MAX_EXPORT_ROWS,
    )
