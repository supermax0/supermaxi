from flask import Blueprint, flash, render_template, request, redirect, url_for, session, jsonify
from extensions import db
from utils.branch_scope import resolve_write_branch_id
from utils.branch_mode import independent_branches_enabled
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from io import BytesIO
from datetime import datetime
from types import SimpleNamespace
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.product import Product
from datetime import datetime
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.employee import Employee
from models.supplier_sale import SupplierSale
from utils.plan_guard import feature_required
from utils.permission_checks import check_permission
from utils.treasury_helpers import treasury_choices_for_form
from utils.treasury_calculations import InsufficientTreasuryBalance
from utils.supplier_sale_service import (
    SupplierSaleError,
    cancel_supplier_sale,
    create_supplier_sale,
    ensure_supplier_sale_schema,
    supplier_sale_summary,
)
from utils.supplier_exchange_rate import get_supplier_exchange_rate
from utils.supplier_payment_allocation import (
    effective_purchase_payment_totals,
    purchase_allocation_totals_for_ids,
)
from utils.supplier_payment_ops import (
    create_supplier_cash_payment,
    prepare_supplier_payment_allocations,
    shared_supplier_key,
    shared_supplier_member_ids,
    SupplierPaymentError,
)

suppliers_bp = Blueprint("suppliers", __name__)


# Native management-client endpoints. Reuse the same account balances, branch
# identity and payment service as the existing supplier pages.
def _management_supplier_query():
    query = Supplier.query
    if not independent_branches_enabled():
        query = query.execution_options(skip_branch_scope=True)
    return query


def _management_supplier_rows(supplier_id=None):
    from sqlalchemy import func

    suppliers = _management_supplier_query().order_by(Supplier.name, Supplier.id).all()
    if supplier_id is not None:
        target = next((s for s in suppliers if s.id == supplier_id), None)
        if target is None:
            return []
        key = shared_supplier_key(target)
        suppliers = [s for s in suppliers if s.id == supplier_id or (
            not independent_branches_enabled() and shared_supplier_key(s) == key
        )]
    groups = {}
    for supplier in suppliers:
        key = str(supplier.id) if independent_branches_enabled() else shared_supplier_key(supplier)
        groups.setdefault(key, []).append(supplier)
    ids = [s.id for s in suppliers]
    if not ids:
        return []
    purchases = Purchase.query.filter(Purchase.supplier_id.in_(ids))
    if not independent_branches_enabled():
        purchases = purchases.execution_options(skip_branch_scope=True)
    purchases = purchases.filter(func.coalesce(Purchase.status, "confirmed").notin_(["draft", "cancelled"]))
    purchase_stats = {
        row[0]: row[1:] for row in purchases.with_entities(
            Purchase.supplier_id,
            func.sum(func.coalesce(func.nullif(Purchase.grand_total, 0), Purchase.total, 0)),
            func.count(Purchase.id), func.max(Purchase.purchase_date),
        ).group_by(Purchase.supplier_id).all()
    }
    payment_stats = {
        row[0]: row[1:] for row in SupplierPayment.query.execution_options(skip_branch_scope=True)
        .filter(SupplierPayment.supplier_id.in_(ids), SupplierPayment.deleted_at.is_(None))
        .with_entities(SupplierPayment.supplier_id, func.count(SupplierPayment.id), func.max(SupplierPayment.created_at))
        .group_by(SupplierPayment.supplier_id).all()
    }
    rows = []
    for members in groups.values():
        members.sort(key=lambda s: (int(s.branch_id or 0), s.id))
        s = next((s for s in members if s.id == supplier_id), members[0])
        debt = sum(int(m.total_debt or 0) for m in members)
        paid = sum(int(m.total_paid or 0) for m in members)
        pstats = [purchase_stats.get(m.id, (0, 0, None)) for m in members]
        paystats = [payment_stats.get(m.id, (0, None)) for m in members]
        dates = [str(p[2])[:10] for p in pstats if p[2]] + [str(p[1])[:10] for p in paystats if p[1]]
        rows.append({
            "id": s.id, "name": s.name, "phone": s.phone or "", "phone2": s.phone2 or "",
            "address": s.address or "", "created_at": s.created_at.isoformat() if s.created_at else "",
            "opening_balance": sum(int(m.opening_balance or 0) for m in members),
            "total_debt": debt, "total_paid": paid, "remaining": debt - paid,
            "total_purchases": sum(int(p[0] or 0) for p in pstats),
            "purchase_count": sum(int(p[1] or 0) for p in pstats),
            "payment_count": sum(int(p[0] or 0) for p in paystats),
            "last_transaction": max(dates, default=""), "member_count": len(members),
        })
    return rows


@suppliers_bp.route("/api/page")
@feature_required("suppliers")
def management_suppliers_page(*, _snapshot=False):
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    rows = _management_supplier_rows()
    summary = {
        "count": len(rows), "payable": sum(max(s["remaining"], 0) for s in rows),
        "credit": sum(max(-s["remaining"], 0) for s in rows),
        "purchases": sum(s["total_purchases"] for s in rows),
    }
    search = (request.args.get("search") or "").strip().casefold()
    if search:
        rows = [s for s in rows if search in " ".join((s["name"], s["phone"], s["phone2"], s["address"])).casefold()]
    min_balance = max(request.args.get("min_balance", 0, type=int) or 0, 0)
    if min_balance:
        rows = [s for s in rows if abs(s["remaining"]) >= min_balance]
    counts = {"all": len(rows), "debt": sum(s["remaining"] > 0 for s in rows),
              "credit": sum(s["remaining"] < 0 for s in rows), "settled": sum(s["remaining"] == 0 for s in rows)}
    tab = request.args.get("tab", "all")
    if tab == "debt":
        rows = [s for s in rows if s["remaining"] > 0]
    elif tab == "credit":
        rows = [s for s in rows if s["remaining"] < 0]
    elif tab == "settled":
        rows = [s for s in rows if s["remaining"] == 0]
    sort = request.args.get("sort", "name")
    rows.sort(key=lambda s: (s["name"].casefold(), s["id"]))
    if sort == "balance":
        rows.sort(key=lambda s: abs(s["remaining"]), reverse=True)
    elif sort == "recent":
        rows.sort(key=lambda s: s["last_transaction"], reverse=True)
    page_size = (len(rows) or 1) if _snapshot else min(max(request.args.get("page_size", 25, type=int) or 25, 1), 100)
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(request.args.get("page", 1, type=int) or 1, 1), total_pages)
    return jsonify(success=True, rows=rows[(page - 1) * page_size:page * page_size],
                   total=total, page=page, page_size=page_size, total_pages=total_pages, counts=counts, summary=summary)


@suppliers_bp.route("/api/<int:id>")
@feature_required("suppliers")
def management_supplier_details(id):
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    supplier = _management_supplier_query().filter(Supplier.id == id).first_or_404()
    member_ids = shared_supplier_member_ids(supplier)
    for member_id in member_ids:
        _prepare_supplier_payment_allocations(member_id)
    purchases_query = _supplier_purchases_query(member_ids)
    sales_query = _supplier_sales_query(member_ids)
    if not independent_branches_enabled():
        purchases_query = purchases_query.execution_options(skip_branch_scope=True)
        sales_query = sales_query.execution_options(skip_branch_scope=True)
    purchases = _supplier_purchase_invoice_summaries(member_ids, purchases_query.all())
    payments = _supplier_payments_query(member_ids).filter(SupplierPayment.deleted_at.is_(None)).all()
    sales = [supplier_sale_summary(s) for s in sales_query.all()]
    return jsonify(
        success=True, supplier=_management_supplier_rows(id)[0],
        purchases=[{
            "id": p["id"], "invoice_no": p["invoice_no"], "date": str(p["purchase_date"] or ""),
            "status": p["status"], "products_label": p["products_label"],
            "grand_total": p["grand_total"], "paid_total": p["paid_total"], "remaining_total": p["remaining_total"],
        } for p in purchases],
        payments=[{
            "id": p.id, "date": p.created_at.isoformat() if p.created_at else "", "amount": int(p.amount or 0),
            "note": p.note or "", "document_number": p.document_number or "",
            "payment_method": p.payment_method or "cash", "invoice_labels": _supplier_payment_invoice_labels(p),
        } for p in payments],
        sales=[{
            "id": s["id"], "invoice_no": s["invoice_no"], "date": str(s["sale_date"] or ""),
            "grand_total": s["grand_total"], "products_label": s["products_label"],
        } for s in sales],
        treasury_accounts=[{"id": a.id, "name": a.name, "is_default": bool(a.is_default)} for a in treasury_choices_for_form()],
    )


def _management_supplier_fields(data):
    if not isinstance(data, dict):
        raise ValueError("بيانات المورد غير صحيحة")
    fields = {}
    for key, limit in (("name", 150), ("phone", 50), ("phone2", 50), ("address", 255)):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError("تحقق من طول ونوع بيانات المورد")
        fields[key] = value.strip() or None
    if not fields["name"]:
        raise ValueError("اسم المورد مطلوب")
    return fields


def _management_dinars(value):
    from decimal import Decimal, InvalidOperation
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.to_integral_value() or not 0 <= amount <= 2147483647:
            raise ValueError("المبلغ يجب أن يكون عدداً صحيحاً بالدينار")
        return int(amount)
    except (InvalidOperation, TypeError):
        raise ValueError("المبلغ غير صحيح")


@suppliers_bp.route("/api/create", methods=["POST"])
@feature_required("suppliers")
def management_supplier_create():
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    data = request.get_json(silent=True)
    try:
        fields = _management_supplier_fields(data)
        opening = _management_dinars(data.get("opening_balance", 0))
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    supplier = Supplier(**fields, branch_id=resolve_write_branch_id(data), opening_balance=opening,
                        total_debt=opening, total_paid=0)
    db.session.add(supplier)
    db.session.commit()
    return jsonify(success=True, id=supplier.id, message="تمت إضافة المورد بنجاح")


@suppliers_bp.route("/api/<int:id>/update", methods=["POST"])
@feature_required("suppliers")
def management_supplier_update(id):
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    supplier = _management_supplier_query().filter(Supplier.id == id).first_or_404()
    try:
        fields = _management_supplier_fields(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    # A shared account is represented by branch-local copies. Keep their
    # contact identity together when renamed; historic balances stay separate.
    members = [supplier]
    if not independent_branches_enabled():
        members = Supplier.query.execution_options(skip_branch_scope=True).filter(
            Supplier.id.in_(shared_supplier_member_ids(supplier))
        ).all()
    for member in members:
        for key, value in fields.items():
            setattr(member, key, value)
    db.session.commit()
    return jsonify(success=True, id=id, message="تم تحديث بيانات المورد")


@suppliers_bp.route("/api/<int:id>/pay", methods=["POST"])
@feature_required("suppliers")
def management_supplier_pay(id):
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    _management_supplier_query().filter(Supplier.id == id).first_or_404()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(success=False, error="بيانات الدفعة غير صحيحة"), 400
    try:
        amount = _management_dinars(data.get("amount"))
        datetime.strptime(str(data.get("payment_date", "")), "%Y-%m-%d")
        result = create_supplier_cash_payment(
            id, amount=amount, treasury_account_id=data.get("treasury_account_id"),
            note=data.get("note", ""), document_number=data.get("document_number"),
            payment_date=data.get("payment_date"), commit=True,
        )
    except (ValueError, SupplierPaymentError, InsufficientTreasuryBalance) as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(success=True, id=id, message=result["message"])


@suppliers_bp.before_request
def _suppliers_schema_guard():
    _ensure_supplier_schema()
    ensure_supplier_sale_schema()


@suppliers_bp.route("/api/sale-products")
@feature_required("suppliers")
def management_supplier_sale_products(*, _snapshot=False):
    from sqlalchemy import or_
    from utils.branch_context import current_branch_id
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import _branch_product_id, get_branch_stock
    from utils.product_color_service import get_branch_product_colors, product_has_colors

    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    q = (request.args.get("q") or "").strip()[:150]
    if not q and not _snapshot:
        return jsonify([])
    branch_id = current_branch_id()
    if not branch_id:
        branch = get_default_branch()
        branch_id = branch.id if branch else None
    query = Product.query.filter(Product.active.is_(True))
    independent = independent_branches_enabled()
    if independent and branch_id:
        default_branch = get_default_branch()
        scope = Product.branch_id == branch_id
        if default_branch and default_branch.id == branch_id:
            scope = or_(scope, Product.branch_id.is_(None))
        query = query.filter(scope)
    exact = query.filter(Product.barcode == q).all() if q else []
    like = f"%{q}%"
    products = query.order_by(Product.name, Product.id).all() if _snapshot else exact if exact else query.filter(or_(
        Product.name.ilike(like), Product.barcode.ilike(like), Product.sku.ilike(like)
    )).order_by(Product.name, Product.id).all()
    if not independent:
        # Branch copies are one catalogue item. Prefer the actual selling branch
        # before collapsing them, so its price/ID stay paired with its stock.
        products.sort(key=lambda p: (p.branch_id != branch_id, p.id))
        from services.pos_catalog import shared_catalog_groups
        representatives = [members[0] for members in shared_catalog_groups(products)]
        resolved = {}
        for product in representatives:
            local_id = _branch_product_id(branch_id, product.id) if branch_id else product.id
            local = db.session.get(Product, local_id)
            if local and local.active:
                product = local
            resolved.setdefault(product.id, product)
        products = sorted(resolved.values(), key=lambda p: (p.name, p.id))
    if not _snapshot:
        products = products[:1 if exact else 15]
    rows = []
    for product in products:
        has_colors = product_has_colors(product)
        colors = get_branch_product_colors(product.id, branch_id) if has_colors and branch_id else []
        rows.append({
            "id": product.id, "name": product.name, "sku": product.sku or "", "barcode": product.barcode or "",
            "sale_price": int(product.sale_price or 0),
            "quantity": get_branch_stock(branch_id, product.id) if branch_id else int(product.quantity or 0),
            "has_colors": has_colors,
            "colors": [{"name": c["name"], "qty": int(c["qty"] or 0), "sale_price": int(c.get("sale_price") or product.sale_price or 0)} for c in colors],
        })
    return jsonify(rows)


@suppliers_bp.route("/api/<int:id>/sale", methods=["POST"])
@feature_required("suppliers")
def management_supplier_sale(id):
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    try:
        sale = _create_management_supplier_sale(id, request.get_json(silent=True))
        db.session.commit()
    except (ValueError, SupplierSaleError) as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 400
    remaining = _management_supplier_rows(id)[0]["remaining"]
    return jsonify(success=True, message=f"تم تسجيل بيع للمورد — {sale.invoice_no}",
                   sale_id=sale.id, invoice_no=sale.invoice_no, grand_total=int(sale.grand_total or 0),
                   remaining=remaining, supplier_receivable=max(-remaining, 0))


def _create_management_supplier_sale(id, data):
    """Shared native/sync validation; the caller owns the entire transaction."""
    from utils.product_color_service import product_has_colors

    supplier = _management_supplier_query().filter(Supplier.id == id).first_or_404()
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("بيانات فاتورة البيع غير صحيحة")
    if not 1 <= len(data["items"]) <= 100:
        raise ValueError("أضف من صنف واحد إلى 100 صنف")
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > 255:
        raise ValueError("الملاحظات يجب ألا تتجاوز 255 حرفاً")
    items = []
    for item in data["items"]:
        if not isinstance(item, dict):
            raise ValueError("بيانات الصنف غير صحيحة")
        product_id = _management_dinars(item.get("product_id"))
        qty = _management_dinars(item.get("qty"))
        price = _management_dinars(item.get("price"))
        if product_id <= 0 or qty <= 0 or price <= 0:
            raise ValueError("حدد المنتج وأدخل كمية وسعراً أكبر من صفر")
        product = Product.query.filter(Product.id == product_id, Product.active.is_(True)).first()
        if product is None:
            raise ValueError("المنتج غير موجود في الفرع الحالي")
        color = item.get("variant_color", "")
        if not isinstance(color, str) or len(color) > 80:
            raise ValueError("اللون غير صحيح")
        if product_has_colors(product) and not color.strip():
            raise ValueError(f"اختر لون المنتج {product.name}")
        items.append({"product_id": product_id, "qty": qty, "price": price, "variant_color": color.strip()})
    if sum(i["qty"] * i["price"] for i in items) > 2147483647:
        raise ValueError("إجمالي الفاتورة يتجاوز الحد المسموح")
    employee = db.session.get(Employee, session.get("user_id")) if session.get("user_id") else None
    return create_supplier_sale(supplier, items, note=note.strip(), employee=employee)


def _ensure_supplier_schema():
    try:
        from sqlalchemy import inspect, text

        bind = db.session.get_bind()
        inspector = inspect(bind)
        table_names = set(inspector.get_table_names())
        altered = False
        if "supplier" in table_names:
            cols = {col["name"] for col in inspector.get_columns("supplier")}
            if "opening_balance" not in cols:
                db.session.execute(
                    text("ALTER TABLE supplier ADD COLUMN opening_balance INTEGER DEFAULT 0")
                )
                altered = True
            if "phone2" not in cols:
                db.session.execute(
                    text("ALTER TABLE supplier ADD COLUMN phone2 VARCHAR(50)")
                )
                altered = True
        if "supplier_payment" in table_names:
            pay_cols = {col["name"] for col in inspector.get_columns("supplier_payment")}
            if "document_number" not in pay_cols:
                db.session.execute(
                    text("ALTER TABLE supplier_payment ADD COLUMN document_number VARCHAR(100)")
                )
                altered = True
        if altered:
            db.session.commit()
    except Exception:
        db.session.rollback()


def _ensure_supplier_opening_balance_column():
    """Backward-compatible alias used by older call sites. """
    _ensure_supplier_schema()


def _clean_optional_text(raw_value):
    if raw_value is None:
        return None
    cleaned = str(raw_value).strip()
    return cleaned or None


def _parse_opening_balance(raw_value):
    if raw_value is None:
        return 0
    cleaned = str(raw_value).strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return 0
    try:
        return max(0, int(float(cleaned)))
    except (TypeError, ValueError):
        return 0


def _shared_supplier_key(supplier: Supplier) -> str:
    """Match branch-local supplier copies in the shared company view."""
    return shared_supplier_key(supplier)


def _shared_supplier_rows(suppliers: list[Supplier]) -> list[SimpleNamespace]:
    """Present copies of one supplier as a single financial row.

    This is deliberately presentation-only: historic purchases, payments and
    supplier IDs remain untouched, while the shared-mode list shows the true
    company-wide balance.
    """
    groups: dict[str, list[Supplier]] = {}
    for supplier in suppliers:
        groups.setdefault(_shared_supplier_key(supplier), []).append(supplier)

    rows: list[SimpleNamespace] = []
    for members in groups.values():
        members.sort(key=lambda supplier: (int(supplier.branch_id or 0), int(supplier.id)))
        representative = members[0]
        total_debt = sum(int(supplier.total_debt or 0) for supplier in members)
        total_paid = sum(int(supplier.total_paid or 0) for supplier in members)
        rows.append(SimpleNamespace(
            id=representative.id,
            name=representative.name,
            phone=representative.phone,
            phone2=representative.phone2,
            address=representative.address,
            opening_balance=sum(int(supplier.opening_balance or 0) for supplier in members),
            total_debt=total_debt,
            total_paid=total_paid,
            remaining=total_debt - total_paid,
            member_count=len(members),
        ))
    return sorted(rows, key=lambda supplier: ((supplier.name or "").casefold(), supplier.id))


def _shared_supplier_member_ids(supplier: Supplier) -> list[int]:
    """Return all branch copies represented by a supplier row in shared mode."""
    return shared_supplier_member_ids(supplier)


def _shared_supplier_view(supplier: Supplier) -> SimpleNamespace | Supplier:
    """Build the account header for a company-wide supplier view."""
    member_ids = _shared_supplier_member_ids(supplier)
    if len(member_ids) == 1:
        return supplier
    members = (
        Supplier.query.execution_options(skip_branch_scope=True)
        .filter(Supplier.id.in_(member_ids))
        .all()
    )
    return SimpleNamespace(
        id=supplier.id,
        name=supplier.name,
        phone=supplier.phone,
        phone2=supplier.phone2,
        address=supplier.address,
        opening_balance=sum(int(row.opening_balance or 0) for row in members),
        total_debt=sum(int(row.total_debt or 0) for row in members),
        total_paid=sum(int(row.total_paid or 0) for row in members),
        remaining=sum(int(row.remaining or 0) for row in members),
        member_ids=member_ids,
    )


def _purchase_invoice_summary(
    purchase: Purchase,
    allocated_amount: int = 0,
) -> dict:
    """ملخص فاتورة شراء واحدة (وليس دمج الأصناف في صف واحد)."""
    items = list(purchase.items or [])
    grand_total = int(purchase.grand_total or purchase.total or 0)
    paid_total, remaining_total, later_paid_total = effective_purchase_payment_totals(
        purchase,
        allocated_amount,
    )

    if items:
        item_count = len(items)
        names = [
            (it.product.name if it.product else "—")
            for it in items[:3]
        ]
        products_label = "، ".join(names)
        if item_count > 3:
            products_label += f" (+{item_count - 3})"
    else:
        item_count = 1
        legacy_product = getattr(purchase, "product", None)
        products_label = legacy_product.name if legacy_product else (purchase.invoice_no or "—")

    return {
        "id": purchase.id,
        "invoice_no": purchase.invoice_no or f"LEG-{purchase.id}",
        "supplier_invoice_no": (purchase.supplier_invoice_no or "").strip() or None,
        "item_count": item_count,
        "products_label": products_label,
        "grand_total": grand_total,
        "paid_total": paid_total,
        "initial_paid_total": max(paid_total - later_paid_total, 0),
        "later_paid_total": later_paid_total,
        "remaining_total": remaining_total,
        "purchase_date": purchase.purchase_date,
        "status": purchase.status or "confirmed",
    }


def _supplier_purchases_query(supplier_id: int | list[int]):
    from sqlalchemy.orm import joinedload

    return (
        Purchase.query.options(
            joinedload(Purchase.items).joinedload(PurchaseItem.product),
        )
        .filter(Purchase.supplier_id.in_(
            supplier_id if isinstance(supplier_id, list) else [supplier_id]
        ))
        .order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
    )


def _supplier_purchase_invoice_summaries(
    supplier_id: int | list[int],
    purchases: list[Purchase],
) -> list[dict]:
    supplier_ids = supplier_id if isinstance(supplier_id, list) else [supplier_id]
    allocated_by_purchase = purchase_allocation_totals_for_ids(
        [purchase.id for purchase in purchases]
    )
    return [
        _purchase_invoice_summary(
            purchase,
            allocated_by_purchase.get(purchase.id, 0),
        )
        for purchase in purchases
    ]


def _supplier_payment_invoice_labels(payment: SupplierPayment) -> list[str]:
    """Purchase invoice references cleared by this payment (supplier no preferred)."""
    labels: list[str] = []
    seen: set[str] = set()
    for allocation in payment.allocations or []:
        kind = (allocation.allocation_type or "").strip().lower()
        if kind == "purchase" and allocation.purchase:
            purchase = allocation.purchase
            label = (
                (purchase.supplier_invoice_no or "").strip()
                or (purchase.invoice_no or "").strip()
                or f"LEG-{purchase.id}"
            )
        elif kind == "opening_balance":
            label = "الرصيد الافتتاحي"
        elif kind == "on_account":
            label = "رصيد غير مخصص"
        else:
            continue
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def _supplier_payment_rows(
    payments: list[SupplierPayment],
    current_remaining: int,
) -> list[dict]:
    """Newest-first payment rows with balance before/after each payment."""
    running = max(int(current_remaining or 0), 0)
    rows: list[dict] = []
    for payment in payments:
        amount = max(int(payment.amount or 0), 0)
        balance_after = running
        balance_before = running + amount
        rows.append(
            {
                "id": payment.id,
                "created_at": payment.created_at,
                "document_number": payment.document_number,
                "amount": amount,
                "balance_before": balance_before,
                "balance_after": balance_after,
                "note": payment.note,
                "payment_method": payment.payment_method or "cash",
                "invoice_labels": _supplier_payment_invoice_labels(payment),
                "allocations": payment.allocations or [],
            }
        )
        running = balance_before
    return rows


def _supplier_payments_query(supplier_id: int | list[int]):
    from sqlalchemy.orm import joinedload

    from models.supplier_payment_allocation import SupplierPaymentAllocation

    return (
        SupplierPayment.query.options(
            joinedload(SupplierPayment.allocations)
            .joinedload(SupplierPaymentAllocation.purchase)
        )
        .execution_options(skip_branch_scope=True)
        .filter(
            SupplierPayment.supplier_id.in_(
                supplier_id if isinstance(supplier_id, list) else [supplier_id]
            )
        )
        .order_by(SupplierPayment.created_at.desc(), SupplierPayment.id.desc())
    )


def _prepare_supplier_payment_allocations(supplier_id: int) -> None:
    """Persist one-time FIFO allocations for payments created before this feature."""
    prepare_supplier_payment_allocations(supplier_id)


def _supplier_sales_query(supplier_id: int | list[int]):
    from sqlalchemy.orm import joinedload

    return (
        SupplierSale.query.options(joinedload(SupplierSale.items))
        .filter(SupplierSale.supplier_id.in_(
            supplier_id if isinstance(supplier_id, list) else [supplier_id]
        ))
        .filter(SupplierSale.status != "cancelled")
        .order_by(SupplierSale.sale_date.desc(), SupplierSale.id.desc())
    )


# =============================
# Suppliers Page
# =============================
@suppliers_bp.route("/", methods=["GET", "POST"])
@feature_required("suppliers")
def suppliers():
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403

    _ensure_supplier_schema()

    if request.method == "POST":
        opening_balance = _parse_opening_balance(request.form.get("opening_balance"))
        supplier = Supplier(
            branch_id=resolve_write_branch_id(request.form),
            name=(request.form.get("name") or "").strip(),
            phone=_clean_optional_text(request.form.get("phone")),
            phone2=_clean_optional_text(request.form.get("phone2")),
            address=_clean_optional_text(request.form.get("address")),
            opening_balance=opening_balance,
            total_debt=opening_balance,
        )
        if not supplier.name:
            flash("اسم المورد مطلوب", "error")
            return redirect(url_for("suppliers.suppliers"))
        db.session.add(supplier)
        db.session.commit()
        return redirect(url_for("suppliers.suppliers"))

    # In shared mode suppliers are company-wide records.  Request an explicit
    # unscoped query here rather than inheriting a stale dashboard branch
    # criterion, which otherwise makes the list look like it contains only
    # the main branch's suppliers.
    supplier_query = Supplier.query
    if not independent_branches_enabled():
        supplier_query = supplier_query.execution_options(skip_branch_scope=True)
    suppliers = supplier_query.order_by(Supplier.name.asc(), Supplier.id.asc()).all()
    # Presentation data for the redesigned list, scoped to the same visible
    # supplier records and aggregated across their shared branch copies.
    from sqlalchemy import func
    purchase_stats = {}
    if suppliers:
        stats_query = db.session.query(
            Purchase.supplier_id, func.count(Purchase.id), func.max(Purchase.purchase_date),
        ).filter(
            Purchase.supplier_id.in_([supplier.id for supplier in suppliers]),
            func.coalesce(Purchase.status, "confirmed") != "cancelled",
        )
        if not independent_branches_enabled():
            stats_query = stats_query.execution_options(skip_branch_scope=True)
        raw_stats = {
            supplier_id: (int(count or 0), last_date.isoformat() if last_date else "")
            for supplier_id, count, last_date in stats_query.group_by(Purchase.supplier_id).all()
        }
        if independent_branches_enabled():
            purchase_stats = raw_stats
        else:
            groups = {}
            for supplier in suppliers:
                groups.setdefault(_shared_supplier_key(supplier), []).append(supplier)
            for members in groups.values():
                representative = min(members, key=lambda supplier: (int(supplier.branch_id or 0), int(supplier.id)))
                values = [raw_stats.get(supplier.id, (0, "")) for supplier in members]
                purchase_stats[representative.id] = (sum(value[0] for value in values), max(value[1] for value in values))
    if not independent_branches_enabled():
        suppliers = _shared_supplier_rows(suppliers)
    return render_template(
        "suppliers.html",
        suppliers=suppliers,
        purchase_stats=purchase_stats,
        supplier_exchange_rate=get_supplier_exchange_rate(),
    )


@suppliers_bp.route("/api/quick-create", methods=["POST"])
def suppliers_quick_create():
    """JSON variant of the supplier form (same fields, branch and permission) for API clients."""
    if not check_permission("can_manage_suppliers"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    _ensure_supplier_schema()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "اسم المورد مطلوب"}), 400
    supplier = Supplier(
        branch_id=resolve_write_branch_id(data),
        name=name,
        phone=_clean_optional_text(data.get("phone")),
        address=_clean_optional_text(data.get("address")),
        opening_balance=0,
        total_debt=0,
    )
    db.session.add(supplier)
    db.session.commit()
    return jsonify({"success": True, "supplier": {"id": supplier.id, "name": supplier.name}})


# =============================
# Update Supplier Info
# =============================
@suppliers_bp.route("/<int:id>/update", methods=["POST"])
@feature_required("suppliers")
def update_supplier(id):
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403

    _ensure_supplier_schema()
    supplier = Supplier.query.get_or_404(id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("اسم المورد مطلوب", "error")
        return redirect(url_for("suppliers.supplier_details", id=id))

    supplier.name = name
    supplier.phone = _clean_optional_text(request.form.get("phone"))
    supplier.phone2 = _clean_optional_text(request.form.get("phone2"))
    supplier.address = _clean_optional_text(request.form.get("address"))
    db.session.commit()
    flash("تم تحديث بيانات المورد", "success")

    next_url = (request.form.get("next") or "").strip()
    if next_url.startswith("/suppliers"):
        return redirect(next_url)
    return redirect(url_for("suppliers.supplier_details", id=id))


# =============================
# Supplier Details
# =============================
@suppliers_bp.route("/<int:id>")
def supplier_details(id):
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403
    _ensure_supplier_schema()
    ensure_supplier_sale_schema()
    supplier = Supplier.query.get_or_404(id)
    supplier = _shared_supplier_view(supplier)
    supplier_ids = getattr(supplier, "member_ids", [supplier.id])
    for supplier_id in supplier_ids:
        _prepare_supplier_payment_allocations(supplier_id)
    purchases = _supplier_purchases_query(supplier_ids).all()
    purchase_invoices = _supplier_purchase_invoice_summaries(supplier_ids, purchases)
    sales = _supplier_sales_query(supplier_ids).all()
    sale_invoices = [supplier_sale_summary(s) for s in sales]
    payments = _supplier_payments_query(supplier_ids).all()
    remaining = int(supplier.remaining or 0)
    supplier_receivable = abs(remaining) if remaining < 0 else 0
    payment_rows = _supplier_payment_rows(payments, remaining)

    return render_template(
        "supplier_details.html",
        supplier=supplier,
        purchases=purchases,
        purchase_invoices=purchase_invoices,
        sales=sales,
        sale_invoices=sale_invoices,
        payments=payments,
        payment_rows=payment_rows,
        treasury_choices=treasury_choices_for_form(),
        supplier_receivable=supplier_receivable,
    )


# =============================
# Add Payment (Partial / Full)
# =============================
@suppliers_bp.route("/pay/<int:id>", methods=["POST"])
def supplier_pay(id):
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403
    Supplier.query.get_or_404(id)
    try:
        result = create_supplier_cash_payment(
            id,
            amount=request.form.get("amount", "0"),
            treasury_account_id=request.form.get("treasury_account_id"),
            note=request.form.get("note", ""),
            document_number=request.form.get("document_number"),
            payment_date=request.form.get("payment_date"),
            commit=True,
        )
        flash(result.get("message") or "تم تسجيل الدفعة بنجاح.", "success")
    except SupplierPaymentError as exc:
        flash(exc.message, "error")
    except InsufficientTreasuryBalance as exc:
        flash(str(exc), "error")
    return redirect(url_for("suppliers.supplier_details", id=id))


@suppliers_bp.route("/payment/<int:payment_id>/delete", methods=["POST"])
def supplier_payment_delete(payment_id):
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403

    payment = SupplierPayment.query.get_or_404(payment_id)
    if (payment.payment_method or "cash").strip().lower() == "offset":
        flash("لا يمكن حذف دفعة تسوية مرتبطة ببيع للمورد — ألغِ البيع من جدول المبيعات.", "error")
        return redirect(url_for("suppliers.supplier_details", id=payment.supplier_id))

    supplier = Supplier.query.get_or_404(payment.supplier_id)
    amount = int(payment.amount or 0)
    supplier_id = supplier.id

    supplier.total_paid = max(int(supplier.total_paid or 0) - amount, 0)
    db.session.delete(payment)
    db.session.commit()
    flash(f"تم حذف دفعة {amount:,} د.ع من سجل المورد.", "success")

    return redirect(url_for("suppliers.supplier_details", id=supplier_id))


@suppliers_bp.route("/<int:id>/sale", methods=["POST"])
def supplier_sale_create(id):
    if not check_permission("can_manage_suppliers"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    supplier = Supplier.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    note = (data.get("note") or "").strip()
    employee = Employee.query.get(session.get("user_id")) if session.get("user_id") else None

    try:
        sale = create_supplier_sale(supplier, items, note=note, employee=employee)
        db.session.commit()
    except SupplierSaleError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": f"خطأ غير متوقع: {exc}"}), 500

    remaining = int(supplier.remaining or 0)
    receivable = abs(remaining) if remaining < 0 else 0
    return jsonify(
        {
            "success": True,
            "message": f"تم تسجيل بيع للمورد — {sale.invoice_no}",
            "sale_id": sale.id,
            "invoice_no": sale.invoice_no,
            "grand_total": int(sale.grand_total or 0),
            "remaining": remaining,
            "supplier_receivable": receivable,
            "redirect": url_for("suppliers.supplier_details", id=supplier.id),
        }
    )


@suppliers_bp.route("/sale/<int:sale_id>/cancel", methods=["POST"])
def supplier_sale_cancel(sale_id):
    if not check_permission("can_manage_suppliers"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403

    sale = SupplierSale.query.get_or_404(sale_id)
    supplier_id = sale.supplier_id

    try:
        cancel_supplier_sale(sale)
        db.session.commit()
    except SupplierSaleError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": f"خطأ غير متوقع: {exc}"}), 500

    supplier = Supplier.query.get(supplier_id)
    remaining = int(supplier.remaining or 0) if supplier else 0
    return jsonify(
        {
            "success": True,
            "message": "تم إلغاء البيع واسترجاع المخزون.",
            "remaining": remaining,
            "redirect": url_for("suppliers.supplier_details", id=supplier_id),
        }
    )


@suppliers_bp.route("/api/products/search")
def supplier_products_search():
    if not check_permission("can_manage_suppliers"):
        return jsonify([]), 403

    q = (request.args.get("q") or "").strip()
    query = Product.query.filter_by(active=True)
    if q:
        like = f"%{q}%"
        query = query.filter(Product.name.ilike(like))
    rows = query.order_by(Product.name.asc()).limit(40).all()
    return jsonify(
        [
            {
                "id": p.id,
                "name": p.name,
                "sale_price": int(p.sale_price or 0),
                "quantity": int(p.quantity or 0),
            }
            for p in rows
        ]
    )


def _supplier_statement_context(supplier: Supplier) -> dict:
    supplier_ids = getattr(supplier, "member_ids", [supplier.id])
    purchases = _supplier_purchases_query(supplier_ids).all()
    purchase_invoices = _supplier_purchase_invoice_summaries(supplier_ids, purchases)
    sales = _supplier_sales_query(supplier_ids).all()
    sale_invoices = [supplier_sale_summary(s) for s in sales]
    payments = (
        SupplierPayment.query.execution_options(skip_branch_scope=True)
        .filter(SupplierPayment.supplier_id.in_(supplier_ids))
        .all()
    )

    total_cash_paid = 0
    total_offset_paid = 0
    for pay in payments:
        amount = int(pay.amount or 0)
        method = (pay.payment_method or "cash").strip().lower()
        if method == "offset":
            total_offset_paid += amount
        else:
            total_cash_paid += amount

    return {
        "purchases": purchases,
        "purchase_invoices": purchase_invoices,
        "sale_invoices": sale_invoices,
        "payments": payments,
        "opening_balance": int(getattr(supplier, "opening_balance", 0) or 0),
        "total_purchase": sum(p["grand_total"] for p in purchase_invoices),
        "total_sales": sum(s["grand_total"] for s in sale_invoices),
        "total_cash_paid": total_cash_paid,
        "total_offset_paid": total_offset_paid,
        "total_paid": int(supplier.total_paid or 0),
        "total_debt": int(supplier.total_debt or 0),
        "remaining": int(supplier.remaining or 0),
    }


@suppliers_bp.route("/statement/pdf/<int:id>")
def supplier_statement_pdf(id):
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403
    _ensure_supplier_opening_balance_column()
    ensure_supplier_sale_schema()
    supplier = Supplier.query.get_or_404(id)
    supplier = _shared_supplier_view(supplier)
    for supplier_id in getattr(supplier, "member_ids", [supplier.id]):
        _prepare_supplier_payment_allocations(supplier_id)
    statement = _supplier_statement_context(supplier)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 2*cm

    # ================= HEADER =================
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(2*cm, y, "Supplier Account Statement")
    y -= 1*cm

    pdf.setFont("Helvetica", 11)
    pdf.drawString(2*cm, y, f"Supplier: {supplier.name}")
    y -= 0.7*cm
    pdf.drawString(2*cm, y, f"Phone: {supplier.phone or '-'}")
    y -= 0.7*cm
    if getattr(supplier, "phone2", None):
        pdf.drawString(2*cm, y, f"Phone 2: {supplier.phone2}")
        y -= 0.7*cm
    if getattr(supplier, "address", None):
        pdf.drawString(2*cm, y, f"Address: {supplier.address}")
        y -= 0.7*cm
    y -= 0.7*cm
    pdf.drawString(2*cm, y, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    y -= 1*cm

    def new_page_if_needed():
        nonlocal y
        if y < 2*cm:
            pdf.showPage()
            y = height - 2*cm

    # ================= PURCHASES =================
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(2*cm, y, "Purchase Invoices")
    y -= 0.7*cm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2*cm, y, "Invoice")
    pdf.drawString(6*cm, y, "Items")
    pdf.drawString(11*cm, y, "Total")
    pdf.drawString(14*cm, y, "Paid")
    pdf.drawString(17*cm, y, "Remain")
    y -= 0.4*cm

    for row in statement["purchase_invoices"]:
        pdf.drawString(2*cm, y, str(row["invoice_no"])[:18])
        pdf.drawString(6*cm, y, str(row["products_label"])[:28])
        pdf.drawString(11*cm, y, str(row["grand_total"]))
        pdf.drawString(14*cm, y, str(row["paid_total"]))
        pdf.drawString(17*cm, y, str(row["remaining_total"]))
        y -= 0.4*cm
        new_page_if_needed()

    y -= 0.7*cm

    # ================= PAYMENTS =================
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(2*cm, y, "Payments and Supplier Sale Offsets")
    y -= 0.7*cm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2*cm, y, "Date")
    pdf.drawString(6*cm, y, "Method")
    pdf.drawString(9*cm, y, "Amount")
    pdf.drawString(12*cm, y, "Note")
    y -= 0.4*cm

    for pay in statement["payments"]:
        method = (pay.payment_method or "cash").strip().lower()
        pdf.drawString(2*cm, y, pay.created_at.strftime("%Y-%m-%d"))
        pdf.drawString(6*cm, y, method)
        pdf.drawString(9*cm, y, str(int(pay.amount or 0)))
        pdf.drawString(12*cm, y, (pay.note or "-")[:36])
        y -= 0.4*cm
        new_page_if_needed()

    y -= 1*cm

    # ================= SUMMARY =================
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(2*cm, y, f"Opening Balance: {statement['opening_balance']}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Purchase Invoices Total: {statement['total_purchase']}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Supplier Sale Offsets: {statement['total_sales']}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Ledger Debt Total: {statement['total_debt']}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Cash Paid: {statement['total_cash_paid']}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Total Paid/Settled: {statement['total_paid']}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Remaining Balance: {statement['remaining']}")

    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"supplier_{supplier.id}_statement.pdf",
        mimetype="application/pdf"
    )
@suppliers_bp.route("/statement/print/<int:id>")
def supplier_statement_print(id):
    _ensure_supplier_opening_balance_column()
    ensure_supplier_sale_schema()
    supplier = Supplier.query.get_or_404(id)
    supplier = _shared_supplier_view(supplier)
    supplier_ids = getattr(supplier, "member_ids", [supplier.id])
    for supplier_id in supplier_ids:
        _prepare_supplier_payment_allocations(supplier_id)

    purchases = _supplier_purchases_query(supplier_ids).all()
    purchase_invoices = _supplier_purchase_invoice_summaries(supplier_ids, purchases)
    sales = _supplier_sales_query(supplier_ids).all()
    sale_invoices = [supplier_sale_summary(s) for s in sales]
    payments = _supplier_payments_query(supplier_ids).all()

    opening_balance = int(getattr(supplier, "opening_balance", 0) or 0)
    total_purchase = sum(p["grand_total"] for p in purchase_invoices)
    total_sales = sum(s["grand_total"] for s in sale_invoices)
    total_paid = int(supplier.total_paid or 0)
    total_debt = int(supplier.total_debt or 0)
    remaining = int(supplier.remaining or 0)
    supplier_receivable = abs(remaining) if remaining < 0 else 0
    payment_rows = _supplier_payment_rows(payments, remaining)

    return render_template(
        "supplier_statement_print.html",
        supplier=supplier,
        purchases=purchases,
        purchase_invoices=purchase_invoices,
        sale_invoices=sale_invoices,
        payments=payments,
        payment_rows=payment_rows,
        opening_balance=opening_balance,
        total_purchase=total_purchase,
        total_sales=total_sales,
        total_paid=total_paid,
        total_debt=total_debt,
        remaining=remaining,
        supplier_receivable=supplier_receivable,
        today=datetime.now(),
    )

