"""بيانات التقارير التفصيلية: المبيعات، المندوبون، المخزن، والموردون."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json

from sqlalchemy import and_, inspect, or_
from sqlalchemy.orm import load_only

from extensions import db
from models.branch import Branch, BranchStock
from models.customer import Customer
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.order_item import OrderItem
from models.product import Product
from models.purchase import Purchase
from models.purchase_payment import PurchasePayment
from models.stock_movement import StockMovement
from models.supplier import Supplier
from models.treasury_account import TreasuryAccount
from utils.cash_calculations import _effective_paid_amount


VALID_REPORT_TYPES = {"sales", "materials", "delivery", "inventory", "suppliers"}

SALES_PAYMENT_FILTERS = (
    ("cash", "نقدي"),
    ("bank", "تحويل بنكي"),
    ("credit", "آجل / غير مسدد"),
    ("mixed", "دفع مختلط"),
)


def _parse_date(value: str | None, fallback: date) -> date:
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback


def resolve_report_period(args, *, today: date | None = None) -> tuple[date, date, str]:
    """يعيد فترة شاملة. الافتراضي هو اليوم في جميع التقارير التفصيلية."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    raw_period = (args.get("period") or "").strip()
    period = raw_period or "today"

    presets = {
        "yesterday": (yesterday, yesterday),
        "today": (today, today),
        "last_7_days": (today - timedelta(days=6), today),
        "this_month": (today.replace(day=1), today),
    }
    preset_from, preset_to = presets.get(period, (today, today))
    date_from = _parse_date(args.get("date_from"), preset_from)
    date_to = _parse_date(args.get("date_to"), preset_to)
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    if period == "custom" or (not raw_period and (args.get("date_from") or args.get("date_to"))):
        period = "custom"
    elif period not in presets:
        period = "today"
    return date_from, date_to, period


def _date_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    return datetime.combine(date_from, time.min), datetime.combine(date_to + timedelta(days=1), time.min)


def _money(value) -> str:
    return f"{int(value or 0):,} د.ع"


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


MATERIAL_TYPE_LABELS = {
    "session_material": "مادة جلسات",
    "retail_product": "منتج بيع للزبون",
    "tool": "أداة",
    "consumable": "مستهلكات",
}


def _material_type(product: Product) -> tuple[str, str]:
    """يعيد مفتاحاً ثابتاً واسماً واضحاً لتصنيف المادة من بيانات المنتج."""
    try:
        meta = json.loads((product.meta_json or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}

    beauty_type = str(meta.get("beauty_product_type") or "").strip()
    if beauty_type:
        return f"beauty:{beauty_type}", MATERIAL_TYPE_LABELS.get(beauty_type, beauty_type)

    category = str(product.catalog_category or meta.get("category") or "").strip()
    if category:
        return f"category:{category}", category

    return "uncategorized", "غير مصنف"


def _invoice_payment_methods(invoice_ids: list[int]) -> dict[int, str]:
    """يصنّف التحصيل حسب نوع حساب الخزينة: نقدي أو تحويل بنكي."""
    if not invoice_ids:
        return {}
    bind = db.session.get_bind(mapper=InvoicePaymentLedger)
    inspector = inspect(bind)
    if not inspector.has_table(InvoicePaymentLedger.__tablename__):
        return {}
    ledger_columns = {column["name"] for column in inspector.get_columns(InvoicePaymentLedger.__tablename__)}
    if not {"invoice_id", "amount_delta"}.issubset(ledger_columns):
        return {}
    selected_columns = [
        InvoicePaymentLedger.id,
        InvoicePaymentLedger.invoice_id,
        InvoicePaymentLedger.amount_delta,
        InvoicePaymentLedger.recorded_at,
    ]
    has_method = "payment_method" in ledger_columns
    has_account = "treasury_account_id" in ledger_columns
    if has_method:
        selected_columns.append(InvoicePaymentLedger.payment_method)
    if has_account:
        selected_columns.append(InvoicePaymentLedger.treasury_account_id)
    rows = (
        InvoicePaymentLedger.query
        .options(load_only(*selected_columns))
        .filter(InvoicePaymentLedger.invoice_id.in_(invoice_ids))
        .order_by(InvoicePaymentLedger.invoice_id.asc(), InvoicePaymentLedger.recorded_at.desc())
        .all()
    )

    account_ids = {
        row.treasury_account_id for row in rows
        if has_account and row.treasury_account_id is not None
    }
    account_details = {}
    if account_ids and inspector.has_table(TreasuryAccount.__tablename__):
        treasury_columns = {column["name"] for column in inspector.get_columns(TreasuryAccount.__tablename__)}
        if {"account_type", "name"}.issubset(treasury_columns):
            account_details = {
                row.id: ((row.account_type or "").strip().lower(), (row.name or "").strip())
                for row in TreasuryAccount.query.options(load_only(
                    TreasuryAccount.id, TreasuryAccount.account_type, TreasuryAccount.name,
                )).filter(TreasuryAccount.id.in_(account_ids)).all()
            }

    balances = defaultdict(int)
    explicit_types = defaultdict(set)
    for row in rows:
        account_id = row.treasury_account_id if has_account else None
        balances[(row.invoice_id, account_id)] += int(row.amount_delta or 0)
        if has_method and int(row.amount_delta or 0) > 0:
            normalized = _normalize_payment_method(row.payment_method)
            if normalized:
                explicit_types[(row.invoice_id, account_id)].add(normalized)

    method_types = defaultdict(set)
    for (invoice_id, account_id), balance in balances.items():
        if balance <= 0:
            continue
        explicit_labels = explicit_types[(invoice_id, account_id)]
        if explicit_labels:
            method_types[invoice_id].update(
                _treasury_method_label(account_id, account_details, explicit=explicit)
                for explicit in explicit_labels
            )
        else:
            method_types[invoice_id].add(
                _treasury_method_label(account_id, account_details)
            )

    result: dict[int, str] = {}
    for invoice_id, labels in method_types.items():
        result[invoice_id] = _compose_payment_labels(labels)
    return result


def _normalize_payment_method(value) -> str | None:
    method = (value or "").strip().lower()
    if not method:
        return None
    if any(token in method for token in ("bank", "transfer", "تحويل", "حوالة", "حواله")):
        return "تحويل بنكي"
    if any(token in method for token in ("cash", "نقد", "صندوق")):
        return "نقدي"
    if any(token in method for token in ("credit", "آجل", "اجل")):
        return "آجل"
    return None


def _treasury_method_label(
    account_id: int | None,
    account_details: dict[int, tuple[str, str]],
    *,
    explicit: str | None = None,
) -> str:
    """يعرض اسم البنك/البطاقة كما هو مسجل في الحسابات."""
    account_type, account_name = account_details.get(
        account_id,
        ("cash", "") if account_id is None else ("bank", ""),
    )
    if explicit == "آجل":
        return "آجل"
    if explicit == "نقدي" or (not explicit and account_type == "cash"):
        return "نقدي"
    if explicit == "تحويل بنكي" or account_type != "cash":
        return f"تحويل بنكي — {account_name}" if account_name else "تحويل بنكي"
    return "نقدي"


def _compose_payment_labels(labels) -> str:
    labels = {label for label in labels if label}
    has_cash = "نقدي" in labels
    bank_names = sorted({
        label.split("—", 1)[1].strip()
        for label in labels
        if label.startswith("تحويل بنكي") and "—" in label and label.split("—", 1)[1].strip()
    })
    has_bank = any(label.startswith("تحويل بنكي") for label in labels)
    bank_label = "تحويل بنكي"
    if bank_names:
        bank_label += " — " + "، ".join(bank_names)
    if has_cash and has_bank:
        return f"نقدي + {bank_label}"
    if has_bank:
        return bank_label
    if has_cash:
        return "نقدي"
    if "آجل" in labels:
        return "آجل"
    return "—"


def _payment_label(invoice: Invoice, methods: dict[int, str]) -> str:
    status = (invoice.payment_status or "").strip()
    paid = int(_effective_paid_amount(invoice) or 0)
    if status == "غير مسدد" or paid <= 0:
        return "آجل"
    method = methods.get(invoice.id) or "نقدي"
    if status == "جزئي":
        return f"{method} (جزئي)"
    return method


def _payment_filter_key(label: str) -> str:
    """يحوّل وصف طريقة الدفع المعروض إلى قيمة ثابتة قابلة للتصفية."""
    normalized = (label or "").strip()
    if not normalized or normalized == "—":
        return "credit"
    if "آجل" in normalized:
        return "credit"
    has_cash = "نقدي" in normalized
    has_bank = "تحويل بنكي" in normalized
    if has_cash and has_bank:
        return "mixed"
    if has_bank:
        return "bank"
    return "cash"


def _purchase_payment_methods(purchase_ids: list[int]) -> dict[int, str]:
    if not purchase_ids:
        return {}
    bind = db.session.get_bind(mapper=PurchasePayment)
    inspector = inspect(bind)
    if not inspector.has_table(PurchasePayment.__tablename__):
        return {}
    columns = {column["name"] for column in inspector.get_columns(PurchasePayment.__tablename__)}
    if not {"purchase_id", "amount"}.issubset(columns):
        return {}

    selected_columns = [PurchasePayment.id, PurchasePayment.purchase_id, PurchasePayment.amount]
    has_method = "payment_method" in columns
    has_account = "treasury_account_id" in columns
    if has_method:
        selected_columns.append(PurchasePayment.payment_method)
    if has_account:
        selected_columns.append(PurchasePayment.treasury_account_id)
    payments = (
        PurchasePayment.query.options(load_only(*selected_columns))
        .filter(PurchasePayment.purchase_id.in_(purchase_ids), PurchasePayment.amount > 0)
        .all()
    )

    account_ids = {
        row.treasury_account_id for row in payments
        if has_account and row.treasury_account_id is not None
    }
    account_details = {}
    if account_ids and inspector.has_table(TreasuryAccount.__tablename__):
        treasury_columns = {column["name"] for column in inspector.get_columns(TreasuryAccount.__tablename__)}
        if {"account_type", "name"}.issubset(treasury_columns):
            account_details = {
                row.id: ((row.account_type or "").strip().lower(), (row.name or "").strip())
                for row in TreasuryAccount.query.options(load_only(
                    TreasuryAccount.id, TreasuryAccount.account_type, TreasuryAccount.name,
                )).filter(TreasuryAccount.id.in_(account_ids)).all()
            }

    labels_by_purchase = defaultdict(set)
    for payment in payments:
        explicit = _normalize_payment_method(payment.payment_method) if has_method else None
        account_id = payment.treasury_account_id if has_account else None
        labels_by_purchase[payment.purchase_id].add(
            _treasury_method_label(account_id, account_details, explicit=explicit)
        )

    result = {}
    for purchase_id, labels in labels_by_purchase.items():
        result[purchase_id] = _compose_payment_labels(labels)
    return result


def _purchase_payment_label(purchase: Purchase, paid: int, remaining: int, methods: dict[int, str]) -> str:
    if paid <= 0 and remaining > 0:
        return "آجل"
    mode = (purchase.purchase_mode or "").strip().lower()
    method = methods.get(purchase.id)
    if not method:
        method = {
            "cash": "نقدي",
            "bank": "تحويل بنكي",
            "transfer": "تحويل بنكي",
            "mixed": "نقدي + تحويل بنكي",
        }.get(mode, "نقدي" if paid > 0 else "آجل")
    if paid > 0 and remaining > 0:
        return f"{method} (جزئي)"
    return method


def _invoice_rows(
    invoices: list[Invoice],
    *,
    include_agent: bool = False,
    payment_method: str | None = None,
) -> tuple[list[dict], dict]:
    methods = _invoice_payment_methods([row.id for row in invoices])
    employee_ids = {row.employee_id for row in invoices if row.employee_id}
    employee_names = {
        row.id: row.name for row in Employee.query.options(load_only(Employee.id, Employee.name))
        .filter(Employee.id.in_(employee_ids)).all()
    } if employee_ids else {}
    agent_ids = {row.delivery_agent_id for row in invoices if include_agent and row.delivery_agent_id}
    agent_names = {
        row.id: row.name for row in DeliveryAgent.query.options(load_only(DeliveryAgent.id, DeliveryAgent.name))
        .filter(DeliveryAgent.id.in_(agent_ids)).all()
    } if agent_ids else {}
    rows = []
    total_amount = 0
    total_collected = 0
    for invoice in invoices:
        payment_label = _payment_label(invoice, methods)
        if payment_method and _payment_filter_key(payment_label) != payment_method:
            continue
        total = int(invoice.total or 0)
        collected = int(_effective_paid_amount(invoice) or 0)
        total_amount += total
        total_collected += collected
        row = {
            "invoice_no": invoice.id,
            "customer": invoice.customer_name or "—",
            "amount": _money(total),
            "payment_method": payment_label,
            "payment_method_key": _payment_filter_key(payment_label),
            "employee": invoice.employee_name or employee_names.get(invoice.employee_id, "—"),
            "date": invoice.created_at.strftime("%Y-%m-%d %H:%M") if invoice.created_at else "—",
        }
        if include_agent:
            row.update({
                "agent": agent_names.get(invoice.delivery_agent_id, "—"),
                "status": invoice.shipping_status or invoice.status or "—",
            })
        rows.append(row)
    return rows, {
        "count": len(rows),
        "total_amount": total_amount,
        "total_collected": total_collected,
        "total_remaining": max(total_amount - total_collected, 0),
    }


def _sales_report(
    date_from: date,
    date_to: date,
    employee_id: int | None,
    customer_id: int | None = None,
    payment_method: str | None = None,
) -> dict:
    start_at, end_at = _date_bounds(date_from, date_to)
    query = Invoice.query.filter(
        Invoice.created_at >= start_at,
        Invoice.created_at < end_at,
        Invoice.status != "ملغي",
    ).options(load_only(
        Invoice.id, Invoice.customer_name, Invoice.employee_id, Invoice.employee_name,
        Invoice.status, Invoice.payment_status, Invoice.total, Invoice.paid_amount,
        Invoice.created_at,
    ))
    if employee_id:
        query = query.filter(Invoice.employee_id == employee_id)
    if customer_id:
        query = query.filter(Invoice.customer_id == customer_id)
    invoices = query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(5000).all()
    rows, totals = _invoice_rows(invoices, payment_method=payment_method)

    employees = (
        Employee.query.options(load_only(Employee.id, Employee.name, Employee.is_active))
        .filter_by(is_active=True)
        .order_by(Employee.name)
        .all()
    )
    customers = (
        Customer.query.options(load_only(Customer.id, Customer.name, Customer.phone))
        .order_by(Customer.name)
        .limit(5000)
        .all()
    )
    employee_options = [(row.id, row.name) for row in employees]
    customer_options = [
        (row.id, f"{row.name} — {row.phone}" if row.phone else row.name)
        for row in customers
    ]
    payment_options = list(SALES_PAYMENT_FILTERS)

    def selected_label(options, selected):
        if not selected:
            return "الكل"
        return next((name for option_id, name in options if option_id == selected), "غير معروف")

    sales_filters = [
        {
            "name": "customer_id",
            "label": "العميل",
            "icon": "fa-user",
            "options": customer_options,
            "selected": customer_id,
            "selected_label": selected_label(customer_options, customer_id),
        },
        {
            "name": "employee_id",
            "label": "الموظف",
            "icon": "fa-user-tie",
            "options": employee_options,
            "selected": employee_id,
            "selected_label": selected_label(employee_options, employee_id),
        },
        {
            "name": "payment_method",
            "label": "طريقة الدفع",
            "icon": "fa-credit-card",
            "options": payment_options,
            "selected": payment_method,
            "selected_label": selected_label(payment_options, payment_method),
        },
    ]
    return {
        "title": "تقرير المبيعات",
        "subtitle": "تفاصيل الفواتير حسب العميل والموظف وطريقة الدفع والفترة",
        "icon": "fa-chart-line",
        "filter_name": "employee_id",
        "filter_label": "المستخدم / الموظف",
        "filter_options": employee_options,
        "selected_filter": employee_id,
        "filters": sales_filters,
        "active_filter_count": sum(1 for item in sales_filters if item["selected"]),
        "columns": [
            ("invoice_no", "رقم الفاتورة"), ("customer", "اسم العميل"),
            ("amount", "المبلغ"), ("payment_method", "طريقة الدفع"),
            ("employee", "الموظف"), ("date", "التاريخ"),
        ],
        "rows": rows,
        "summaries": [
            ("عدد الفواتير", f"{totals['count']:,}", "primary"),
            ("المبلغ الكلي", _money(totals["total_amount"]), "success"),
            ("المحصل", _money(totals["total_collected"]), "info"),
            ("المتبقي", _money(totals["total_remaining"]), "warning"),
        ],
    }


def _materials_sales_report(
    date_from: date,
    date_to: date,
    product_id: int | None,
    material_type: str | None = None,
) -> dict:
    """تفاصيل مبيعات المواد مع تصفية حسب المادة وتصنيفها والفترة."""
    start_at, end_at = _date_bounds(date_from, date_to)
    query = (
        db.session.query(OrderItem, Invoice, Product)
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .join(Product, Product.id == OrderItem.product_id)
        .filter(
            Invoice.created_at >= start_at,
            Invoice.created_at < end_at,
            Invoice.status != "ملغي",
        )
        .options(
            load_only(
                OrderItem.id, OrderItem.invoice_id, OrderItem.product_id,
                OrderItem.product_name, OrderItem.price, OrderItem.quantity,
                OrderItem.cost, OrderItem.total,
            ),
            load_only(
                Invoice.id, Invoice.customer_name, Invoice.status, Invoice.created_at,
            ),
            load_only(
                Product.id, Product.name, Product.catalog_category, Product.meta_json,
            ),
        )
    )
    if product_id:
        query = query.filter(OrderItem.product_id == product_id)

    records = (
        query.order_by(Invoice.created_at.desc(), Invoice.id.desc(), OrderItem.id.desc())
        .limit(5000)
        .all()
    )

    products = (
        Product.query.options(load_only(
            Product.id, Product.name, Product.sku, Product.barcode,
            Product.catalog_category, Product.meta_json,
        ))
        .order_by(Product.name)
        .limit(5000)
        .all()
    )
    product_options = [(row.id, row.name) for row in products]
    type_by_product = {row.id: _material_type(row) for row in products}
    type_options = sorted(set(type_by_product.values()), key=lambda item: item[1])

    rows = []
    total_quantity = total_sales = total_cost = 0
    for item, invoice, product in records:
        type_key, type_label = type_by_product.get(product.id, _material_type(product))
        if material_type and type_key != material_type:
            continue
        quantity = int(item.quantity or 0)
        sales_value = int(item.total if item.total is not None else (item.price or 0) * quantity)
        cost_value = int(item.cost or 0) * quantity
        total_quantity += quantity
        total_sales += sales_value
        total_cost += cost_value
        rows.append({
            "invoice_no": invoice.id,
            "material": item.product_name or product.name or "—",
            "material_type": type_label,
            "quantity": f"{quantity:,}",
            "unit_price": _money(item.price),
            "amount": _money(sales_value),
            "cost": _money(cost_value),
            "profit": _money(sales_value - cost_value),
            "customer": invoice.customer_name or "—",
            "date": invoice.created_at.strftime("%Y-%m-%d %H:%M") if invoice.created_at else "—",
        })

    def selected_label(options, selected):
        if not selected:
            return "الكل"
        return next((name for option_id, name in options if str(option_id) == str(selected)), "غير معروف")

    filters = [
        {
            "name": "product_id", "label": "المادة / المنتج", "icon": "fa-box",
            "options": product_options, "selected": product_id,
            "selected_label": selected_label(product_options, product_id),
        },
        {
            "name": "material_type", "label": "تصنيف المادة", "icon": "fa-tags",
            "options": type_options, "selected": material_type,
            "selected_label": selected_label(type_options, material_type),
        },
    ]
    return {
        "title": "تقرير مبيعات المواد",
        "subtitle": "تفاصيل المواد المباعة والكميات والتكلفة والربح حسب الفترة",
        "icon": "fa-box-open",
        "filter_name": "product_id",
        "filter_label": "المادة / المنتج",
        "filter_options": product_options,
        "selected_filter": product_id,
        "filters": filters,
        "active_filter_count": sum(1 for item in filters if item["selected"]),
        "columns": [
            ("invoice_no", "رقم الفاتورة"), ("material", "المادة"),
            ("material_type", "نوع المادة"), ("quantity", "الكمية"),
            ("unit_price", "سعر الوحدة"), ("amount", "إجمالي البيع"),
            ("cost", "التكلفة"), ("profit", "الربح"),
            ("customer", "العميل"), ("date", "التاريخ"),
        ],
        "rows": rows,
        "summaries": [
            ("عدد المواد المباعة", f"{len(rows):,}", "primary"),
            ("إجمالي الكمية", f"{total_quantity:,}", "info"),
            ("إجمالي المبيعات", _money(total_sales), "success"),
            ("إجمالي الربح", _money(total_sales - total_cost), "warning"),
        ],
    }


def _delivery_report(date_from: date, date_to: date, agent_id: int | None) -> dict:
    start_at, end_at = _date_bounds(date_from, date_to)
    query = Invoice.query.filter(
        Invoice.created_at >= start_at,
        Invoice.created_at < end_at,
        Invoice.status != "ملغي",
        Invoice.delivery_agent_id.isnot(None),
    ).options(load_only(
        Invoice.id, Invoice.customer_name, Invoice.employee_id, Invoice.employee_name,
        Invoice.status, Invoice.payment_status, Invoice.total, Invoice.paid_amount,
        Invoice.shipping_status, Invoice.delivery_agent_id, Invoice.created_at,
    ))
    if agent_id:
        query = query.filter(Invoice.delivery_agent_id == agent_id)
    invoices = query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(5000).all()
    rows, totals = _invoice_rows(invoices, include_agent=True)
    return {
        "title": "تقرير مندوب التوصيل",
        "subtitle": "الطلبات المسندة إلى مندوبي التوصيل",
        "icon": "fa-motorcycle",
        "filter_name": "agent_id",
        "filter_label": "مندوب التوصيل",
        "filter_options": [(row.id, row.name) for row in DeliveryAgent.query.options(load_only(DeliveryAgent.id, DeliveryAgent.name, DeliveryAgent.is_active)).filter_by(is_active=True).order_by(DeliveryAgent.name).all()],
        "selected_filter": agent_id,
        "columns": [
            ("invoice_no", "رقم الفاتورة"), ("customer", "اسم العميل"),
            ("amount", "المبلغ"), ("payment_method", "طريقة الدفع"),
            ("agent", "المندوب"), ("employee", "الموظف"),
            ("status", "حالة التوصيل"), ("date", "التاريخ"),
        ],
        "rows": rows,
        "summaries": [
            ("عدد الفواتير", f"{totals['count']:,}", "primary"),
            ("المبلغ الكلي", _money(totals["total_amount"]), "success"),
            ("المحصل", _money(totals["total_collected"]), "info"),
            ("المتبقي", _money(totals["total_remaining"]), "warning"),
        ],
    }


def _inventory_report(date_from: date, date_to: date, branch_id: int | None) -> dict:
    start_at, end_at = _date_bounds(date_from, date_to)
    products = Product.query.options(load_only(
        Product.id, Product.name, Product.sku, Product.barcode, Product.buy_price,
        Product.quantity, Product.low_stock_threshold,
    )).order_by(Product.name).limit(5000).all()
    product_ids = [row.id for row in products]

    if branch_id:
        stocks = BranchStock.query.options(load_only(
            BranchStock.product_id, BranchStock.quantity,
        )).filter(
            BranchStock.branch_id == branch_id,
            BranchStock.product_id.in_(product_ids),
        ).all() if product_ids else []
        current_by_product = {row.product_id: int(row.quantity or 0) for row in stocks}
    else:
        current_by_product = {row.id: int(row.quantity or 0) for row in products}

    movement_bind = db.session.get_bind(mapper=StockMovement)
    movement_table_exists = inspect(movement_bind).has_table(StockMovement.__tablename__)
    movement_query = (
        StockMovement.query.filter(StockMovement.product_id.in_(product_ids))
        if product_ids and movement_table_exists else None
    )
    if movement_query is not None and branch_id:
        movement_query = movement_query.filter(StockMovement.branch_id == branch_id)
    movements = movement_query.filter(StockMovement.created_at >= start_at).all() if movement_query is not None else []

    in_range = defaultdict(lambda: {"in": 0, "out": 0})
    net_after = defaultdict(int)
    for movement in movements:
        quantity = int(movement.quantity or 0)
        signed = quantity if movement.direction == "in" else -quantity
        if movement.created_at and movement.created_at >= end_at:
            net_after[movement.product_id] += signed
        elif movement.created_at and movement.created_at >= start_at:
            in_range[movement.product_id][movement.direction] += quantity

    rows = []
    total_units = total_in = total_out = total_value = 0
    for product in products:
        current = current_by_product.get(product.id, 0)
        closing = current - net_after[product.id]
        incoming = in_range[product.id]["in"]
        outgoing = in_range[product.id]["out"]
        opening = closing - incoming + outgoing
        value = closing * int(product.buy_price or 0)
        total_units += closing
        total_in += incoming
        total_out += outgoing
        total_value += value
        threshold = int(product.low_stock_threshold or 0)
        status = "نافد" if closing <= 0 else ("منخفض" if closing <= threshold else "متوفر")
        rows.append({
            "product": product.name,
            "code": product.sku or product.barcode or "—",
            "opening": f"{opening:,}",
            "incoming": f"{incoming:,}",
            "outgoing": f"{outgoing:,}",
            "closing": f"{closing:,}",
            "buy_price": _money(product.buy_price),
            "value": _money(value),
            "status": status,
        })

    return {
        "title": "تقرير جرد المخزن",
        "subtitle": "أرصدة الأصناف وحركتها خلال الفترة",
        "icon": "fa-boxes-stacked",
        "filter_name": "branch_id",
        "filter_label": "الفرع / المخزن",
        "filter_options": [(row.id, row.name) for row in Branch.query.options(load_only(Branch.id, Branch.name, Branch.is_active)).filter_by(is_active=True).order_by(Branch.name).all()],
        "selected_filter": branch_id,
        "columns": [
            ("product", "المنتج"), ("code", "الرمز / الباركود"),
            ("opening", "أول المدة"), ("incoming", "الداخل"), ("outgoing", "الخارج"),
            ("closing", "آخر المدة"), ("buy_price", "سعر الشراء"),
            ("value", "القيمة"), ("status", "حالة المخزون"),
        ],
        "rows": rows,
        "summaries": [
            ("عدد الأصناف", f"{len(rows):,}", "primary"),
            ("وحدات آخر المدة", f"{total_units:,}", "success"),
            ("الداخل / الخارج", f"{total_in:,} / {total_out:,}", "info"),
            ("قيمة المخزون", _money(total_value), "warning"),
        ],
    }


def _supplier_report(date_from: date, date_to: date, supplier_id: int | None) -> dict:
    start_at, end_at = _date_bounds(date_from, date_to)
    query = Purchase.query.options(load_only(
        Purchase.id, Purchase.supplier_id, Purchase.invoice_no, Purchase.supplier_invoice_no,
        Purchase.total, Purchase.grand_total, Purchase.paid_total, Purchase.remaining_total,
        Purchase.purchase_mode, Purchase.created_by_employee_id, Purchase.purchase_date,
        Purchase.created_at,
    )).filter(or_(
        and_(Purchase.purchase_date.isnot(None), Purchase.purchase_date >= date_from, Purchase.purchase_date <= date_to),
        and_(Purchase.purchase_date.is_(None), Purchase.created_at >= start_at, Purchase.created_at < end_at),
    ))
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)
    purchases = query.order_by(Purchase.purchase_date.desc(), Purchase.created_at.desc()).limit(5000).all()
    purchase_methods = _purchase_payment_methods([row.id for row in purchases])

    supplier_ids = {row.supplier_id for row in purchases if row.supplier_id}
    supplier_names = {
        row.id: row.name for row in Supplier.query.options(load_only(Supplier.id, Supplier.name))
        .filter(Supplier.id.in_(supplier_ids)).all()
    } if supplier_ids else {}
    employee_ids = {row.created_by_employee_id for row in purchases if row.created_by_employee_id}
    employee_names = {
        row.id: row.name for row in Employee.query.options(load_only(Employee.id, Employee.name))
        .filter(Employee.id.in_(employee_ids)).all()
    } if employee_ids else {}

    rows = []
    total_amount = total_paid = total_remaining = 0
    for purchase in purchases:
        amount = int(purchase.grand_total or purchase.total or 0)
        paid = int(purchase.paid_total or 0)
        remaining = int(purchase.remaining_total or 0)
        mode = (purchase.purchase_mode or "").strip().lower()
        if not paid and not remaining and amount:
            if mode == "cash":
                paid = amount
            else:
                remaining = amount
        total_amount += amount
        total_paid += paid
        total_remaining += remaining
        rows.append({
            "invoice_no": purchase.supplier_invoice_no or purchase.invoice_no or purchase.id,
            "supplier": supplier_names.get(purchase.supplier_id, "—"),
            "amount": _money(amount),
            "paid": _money(paid),
            "remaining": _money(remaining),
            "payment_method": _purchase_payment_label(purchase, paid, remaining, purchase_methods),
            "employee": employee_names.get(purchase.created_by_employee_id, "—"),
            "date": purchase.purchase_date.strftime("%Y-%m-%d") if purchase.purchase_date else (purchase.created_at.strftime("%Y-%m-%d %H:%M") if purchase.created_at else "—"),
        })

    return {
        "title": "تقرير الموردين",
        "subtitle": "فواتير الشراء والمدفوع والمتبقي حسب المورد",
        "icon": "fa-truck-field",
        "filter_name": "supplier_id",
        "filter_label": "المورد",
        "filter_options": [(row.id, row.name) for row in Supplier.query.options(load_only(Supplier.id, Supplier.name)).order_by(Supplier.name).all()],
        "selected_filter": supplier_id,
        "columns": [
            ("invoice_no", "رقم الفاتورة"), ("supplier", "المورد"), ("amount", "المبلغ"),
            ("paid", "المدفوع"), ("remaining", "المتبقي"), ("payment_method", "طريقة الدفع"),
            ("employee", "الموظف"), ("date", "التاريخ"),
        ],
        "rows": rows,
        "summaries": [
            ("عدد الفواتير", f"{len(rows):,}", "primary"),
            ("المبلغ الكلي", _money(total_amount), "success"),
            ("المدفوع", _money(total_paid), "info"),
            ("المتبقي", _money(total_remaining), "warning"),
        ],
    }


def build_operational_report(report_type: str, args) -> dict:
    if report_type not in VALID_REPORT_TYPES:
        raise ValueError("نوع التقرير غير مدعوم")
    date_from, date_to, period = resolve_report_period(args)
    filter_name = {
        "sales": "employee_id",
        "materials": "product_id",
        "delivery": "agent_id",
        "inventory": "branch_id",
        "suppliers": "supplier_id",
    }[report_type]
    selected = _positive_int(args.get(filter_name))
    builders = {
        "sales": _sales_report,
        "materials": _materials_sales_report,
        "delivery": _delivery_report,
        "inventory": _inventory_report,
        "suppliers": _supplier_report,
    }
    if report_type == "sales":
        customer_id = _positive_int(args.get("customer_id"))
        payment_method = (args.get("payment_method") or "").strip().lower()
        valid_payment_methods = {value for value, _label in SALES_PAYMENT_FILTERS}
        if payment_method not in valid_payment_methods:
            payment_method = None
        data = _sales_report(
            date_from,
            date_to,
            selected,
            customer_id=customer_id,
            payment_method=payment_method,
        )
    elif report_type == "materials":
        material_type = (args.get("material_type") or "").strip() or None
        data = _materials_sales_report(
            date_from,
            date_to,
            selected,
            material_type=material_type,
        )
    else:
        data = builders[report_type](date_from, date_to, selected)
    selected_filter_label = "الكل"
    if selected:
        selected_filter_label = next(
            (name for option_id, name in data.get("filter_options", []) if option_id == selected),
            "غير معروف",
        )
    data.update({
        "report_type": report_type,
        "date_from": date_from,
        "date_to": date_to,
        "period": period,
        "selected_filter_label": selected_filter_label,
        "generated_at": datetime.now(),
    })
    return data
