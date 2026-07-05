from flask import Blueprint, flash, render_template, request, redirect, url_for, session
from extensions import db
from flask import send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from io import BytesIO
from datetime import datetime
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.product import Product
from datetime import datetime
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.employee import Employee
from utils.plan_guard import feature_required
from utils.permission_checks import check_permission
from utils.treasury_helpers import resolve_treasury_account_id, treasury_choices_for_form
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_schema_guard import ensure_treasury_schema

suppliers_bp = Blueprint("suppliers", __name__)


def _ensure_supplier_opening_balance_column():
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        if "supplier" not in inspector.get_table_names():
            return
        cols = {col["name"] for col in inspector.get_columns("supplier")}
        if "opening_balance" not in cols:
            db.session.execute(
                text("ALTER TABLE supplier ADD COLUMN opening_balance INTEGER DEFAULT 0")
            )
            db.session.commit()
    except Exception:
        db.session.rollback()


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


def _purchase_invoice_summary(purchase: Purchase) -> dict:
    """ملخص فاتورة شراء واحدة (وليس دمج الأصناف في صف واحد)."""
    items = list(purchase.items or [])
    grand_total = int(purchase.grand_total or purchase.total or 0)
    paid_total = int(purchase.paid_total or 0)
    remaining_total = int(
        purchase.remaining_total
        if purchase.remaining_total is not None
        else max(grand_total - paid_total, 0)
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
        "item_count": item_count,
        "products_label": products_label,
        "grand_total": grand_total,
        "paid_total": paid_total,
        "remaining_total": remaining_total,
        "purchase_date": purchase.purchase_date,
        "status": purchase.status or "confirmed",
    }


def _supplier_purchases_query(supplier_id: int):
    from sqlalchemy.orm import joinedload

    return (
        Purchase.query.options(
            joinedload(Purchase.items).joinedload(PurchaseItem.product),
        )
        .filter_by(supplier_id=supplier_id)
        .order_by(Purchase.purchase_date.desc(), Purchase.id.desc())
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

    _ensure_supplier_opening_balance_column()

    if request.method == "POST":
        opening_balance = _parse_opening_balance(request.form.get("opening_balance"))
        supplier = Supplier(
            name=request.form["name"],
            phone=request.form.get("phone"),
            address=request.form.get("address"),
            opening_balance=opening_balance,
            total_debt=opening_balance,
        )
        db.session.add(supplier)
        db.session.commit()
        return redirect(url_for("suppliers.suppliers"))

    suppliers = Supplier.query.all()
    return render_template("suppliers.html", suppliers=suppliers)


# =============================
# Supplier Details
# =============================
@suppliers_bp.route("/<int:id>")
def supplier_details(id):
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403
    _ensure_supplier_opening_balance_column()
    supplier = Supplier.query.get_or_404(id)
    purchases = _supplier_purchases_query(id).all()
    purchase_invoices = [_purchase_invoice_summary(p) for p in purchases]
    payments = (
        SupplierPayment.query.filter_by(supplier_id=id)
        .order_by(SupplierPayment.created_at.desc())
        .all()
    )

    return render_template(
        "supplier_details.html",
        supplier=supplier,
        purchases=purchases,
        purchase_invoices=purchase_invoices,
        payments=payments,
        treasury_choices=treasury_choices_for_form(),
    )


# =============================
# Add Payment (Partial / Full)
# =============================
@suppliers_bp.route("/pay/<int:id>", methods=["POST"])
def supplier_pay(id):
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403
    supplier = Supplier.query.get_or_404(id)

    try:
        amount = int(float(str(request.form.get("amount", "0")).replace(",", "")))
    except (TypeError, ValueError):
        amount = 0
    note = request.form.get("note", "")
    remaining = int(supplier.remaining or 0)
    if amount <= 0:
        flash("أدخل مبلغ دفع صحيح أكبر من صفر.", "error")
        return redirect(url_for("suppliers.supplier_details", id=id))
    if amount > remaining:
        flash("مبلغ الدفع أكبر من المتبقي على المورد.", "error")
        return redirect(url_for("suppliers.supplier_details", id=id))

    ensure_treasury_schema()
    treasury_account_id = resolve_treasury_account_id(request.form.get("treasury_account_id"))
    try:
        assert_sufficient_balance(treasury_account_id, amount)
    except InsufficientTreasuryBalance as exc:
        flash(str(exc), "error")
        return redirect(url_for("suppliers.supplier_details", id=id))

    payment = SupplierPayment(
        supplier_id=id,
        amount=amount,
        note=note,
        treasury_account_id=treasury_account_id,
    )

    supplier.total_paid = int(supplier.total_paid or 0) + amount

    db.session.add(payment)
    db.session.commit()

    return redirect(url_for("suppliers.supplier_details", id=id))
@suppliers_bp.route("/statement/pdf/<int:id>")
def supplier_statement_pdf(id):
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403
    supplier = Supplier.query.get_or_404(id)

    products = Purchase.query.filter_by(supplier_id=id).all()
    payments = SupplierPayment.query.filter_by(supplier_id=id).all()

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
    pdf.drawString(2*cm, y, f"Date: {datetime.now().strftime('%Y-%m-%d')}")
    y -= 1*cm

    # ================= PRODUCTS =================
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(2*cm, y, "Purchases")
    y -= 0.7*cm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2*cm, y, "Product")
    pdf.drawString(9*cm, y, "Qty")
    pdf.drawString(11*cm, y, "Buy Price")
    pdf.drawString(15*cm, y, "Total")
    y -= 0.4*cm

    total_purchase = 0
    for p in products:
        total = p.buy_price * p.quantity
        total_purchase += total

        pdf.drawString(2*cm, y, p.name)
        pdf.drawString(9*cm, y, str(p.quantity))
        pdf.drawString(11*cm, y, str(p.buy_price))
        pdf.drawString(15*cm, y, str(total))
        y -= 0.4*cm

        if y < 2*cm:
            pdf.showPage()
            y = height - 2*cm

    y -= 0.7*cm

    # ================= PAYMENTS =================
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(2*cm, y, "Payments")
    y -= 0.7*cm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2*cm, y, "Date")
    pdf.drawString(7*cm, y, "Amount")
    pdf.drawString(11*cm, y, "Note")
    y -= 0.4*cm

    total_paid = 0
    for pay in payments:
        total_paid += pay.amount

        pdf.drawString(2*cm, y, pay.created_at.strftime("%Y-%m-%d"))
        pdf.drawString(7*cm, y, str(pay.amount))
        pdf.drawString(11*cm, y, pay.note or "-")
        y -= 0.4*cm

        if y < 2*cm:
            pdf.showPage()
            y = height - 2*cm

    y -= 1*cm

    # ================= SUMMARY =================
    remaining = total_purchase - total_paid

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(2*cm, y, f"Total Purchases: {total_purchase}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Total Paid: {total_paid}")
    y -= 0.6*cm
    pdf.drawString(2*cm, y, f"Remaining Balance: {remaining}")

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
    supplier = Supplier.query.get_or_404(id)

    purchases = _supplier_purchases_query(id).all()
    purchase_invoices = [_purchase_invoice_summary(p) for p in purchases]
    payments = SupplierPayment.query.filter_by(supplier_id=id).all()

    opening_balance = int(getattr(supplier, "opening_balance", 0) or 0)
    total_purchase = sum(p["grand_total"] for p in purchase_invoices)
    total_paid = int(supplier.total_paid or 0)
    total_debt = int(supplier.total_debt or 0)
    remaining = int(supplier.remaining or 0)

    return render_template(
        "supplier_statement_print.html",
        supplier=supplier,
        purchases=purchases,
        purchase_invoices=purchase_invoices,
        payments=payments,
        opening_balance=opening_balance,
        total_purchase=total_purchase,
        total_paid=total_paid,
        total_debt=total_debt,
        remaining=remaining,
        today=datetime.now(),
    )

