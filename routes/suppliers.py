from flask import Blueprint, render_template, request, redirect, url_for, session
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
from models.employee import Employee
from utils.plan_guard import feature_required

suppliers_bp = Blueprint("suppliers", __name__)

def check_permission(permission_name):
    """فحص الصلاحية - helper function"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    # Admin لديه جميع الصلاحيات
    if employee.role == "admin":
        return True
        
    perm_map = {
        "can_see_orders": "view_orders",
        "can_see_reports": "view_reports",
        "can_manage_inventory": "manage_inventory",
        "can_see_expenses": "view_expenses",
        "can_manage_suppliers": "manage_suppliers",
        "can_manage_customers": "manage_customers",
        "can_see_accounts": "view_accounts",
        "can_see_financial": "view_financial",
        "can_edit_price": "edit_price",
    }
    rbac_name = perm_map.get(permission_name, permission_name)
    return employee.has_permission(rbac_name)

# =============================
# Suppliers Page
# =============================
@suppliers_bp.route("/", methods=["GET", "POST"])
@feature_required("suppliers")
def suppliers():
    # فحص الصلاحية
    if not check_permission("can_manage_suppliers"):
        return redirect("/pos"), 403

    if request.method == "POST":
        supplier = Supplier(
            name=request.form["name"],
            phone=request.form.get("phone"),
            address=request.form.get("address")
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
    supplier = Supplier.query.get_or_404(id)
    products = Purchase.query.filter_by(supplier_id=id).all()
    payments = SupplierPayment.query.filter_by(supplier_id=id).all()

    return render_template(
        "supplier_details.html",
        supplier=supplier,
        products=products,
        payments=payments
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

    amount = int(request.form["amount"])
    note = request.form.get("note", "")

    payment = SupplierPayment(
        supplier_id=id,
        amount=amount,
        note=note
    )

    supplier.total_paid += amount

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
    supplier = Supplier.query.get_or_404(id)

    purchases  = Purchase.query.filter_by(supplier_id=id).all()
    payments = SupplierPayment.query.filter_by(supplier_id=id).all()

    total_purchase = sum(p.total for p in purchases)

    total_paid = sum(p.amount for p in payments)
    remaining = total_purchase - total_paid

    return render_template(
        "supplier_statement_print.html",
        supplier=supplier,
        purchases=purchases,
        payments=payments,
        total_purchase=total_purchase,
        total_paid=total_paid,
        remaining=remaining,
        today=datetime.now()   # 🔴 هذا السطر لازم يكون موجود
    )

