from flask import Blueprint, flash, render_template, request, redirect, url_for, session, jsonify
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
from models.product import Product
from models.supplier_sale import SupplierSale
from utils.plan_guard import feature_required
from utils.permission_checks import check_permission
from utils.treasury_helpers import resolve_treasury_account_id, treasury_choices_for_form
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.supplier_sale_service import (
    SupplierSaleError,
    cancel_supplier_sale,
    create_supplier_sale,
    ensure_supplier_sale_schema,
    supplier_sale_summary,
)

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


def _supplier_sales_query(supplier_id: int):
    from sqlalchemy.orm import joinedload

    return (
        SupplierSale.query.options(joinedload(SupplierSale.items))
        .filter_by(supplier_id=supplier_id)
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
    ensure_supplier_sale_schema()
    supplier = Supplier.query.get_or_404(id)
    purchases = _supplier_purchases_query(id).all()
    purchase_invoices = [_purchase_invoice_summary(p) for p in purchases]
    sales = _supplier_sales_query(id).all()
    sale_invoices = [supplier_sale_summary(s) for s in sales]
    payments = (
        SupplierPayment.query.filter_by(supplier_id=id)
        .order_by(SupplierPayment.created_at.desc())
        .all()
    )
    remaining = int(supplier.remaining or 0)
    supplier_receivable = abs(remaining) if remaining < 0 else 0

    return render_template(
        "supplier_details.html",
        supplier=supplier,
        purchases=purchases,
        purchase_invoices=purchase_invoices,
        sales=sales,
        sale_invoices=sale_invoices,
        payments=payments,
        treasury_choices=treasury_choices_for_form(),
        supplier_receivable=supplier_receivable,
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
    if remaining <= 0:
        flash("لا يمكن تسديد دفعة — المورد لا يدين لنا أو تمت تسوية الدين بالكامل.", "error")
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
        payment_method="cash",
    )

    supplier.total_paid = int(supplier.total_paid or 0) + amount

    db.session.add(payment)
    db.session.commit()
    flash("تم تسجيل الدفعة بنجاح.", "success")

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
    purchases = _supplier_purchases_query(supplier.id).all()
    purchase_invoices = [_purchase_invoice_summary(p) for p in purchases]
    sales = _supplier_sales_query(supplier.id).all()
    sale_invoices = [supplier_sale_summary(s) for s in sales]
    payments = SupplierPayment.query.filter_by(supplier_id=supplier.id).all()

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

    purchases = _supplier_purchases_query(id).all()
    purchase_invoices = [_purchase_invoice_summary(p) for p in purchases]
    sales = _supplier_sales_query(id).all()
    sale_invoices = [supplier_sale_summary(s) for s in sales]
    payments = SupplierPayment.query.filter_by(supplier_id=id).all()

    opening_balance = int(getattr(supplier, "opening_balance", 0) or 0)
    total_purchase = sum(p["grand_total"] for p in purchase_invoices)
    total_sales = sum(s["grand_total"] for s in sale_invoices)
    total_paid = int(supplier.total_paid or 0)
    total_debt = int(supplier.total_debt or 0)
    remaining = int(supplier.remaining or 0)
    supplier_receivable = abs(remaining) if remaining < 0 else 0

    return render_template(
        "supplier_statement_print.html",
        supplier=supplier,
        purchases=purchases,
        purchase_invoices=purchase_invoices,
        sale_invoices=sale_invoices,
        payments=payments,
        opening_balance=opening_balance,
        total_purchase=total_purchase,
        total_sales=total_sales,
        total_paid=total_paid,
        total_debt=total_debt,
        remaining=remaining,
        supplier_receivable=supplier_receivable,
        today=datetime.now(),
    )

