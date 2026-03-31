from io import BytesIO

import pandas as pd
from flask import Blueprint, render_template, request, jsonify, send_file
from extensions import db
from models.customer import Customer
from models.invoice import Invoice

customers_bp = Blueprint("customers", __name__, url_prefix="/customers")

# ==================================================
# Customers Page
# ==================================================
@customers_bp.route("/")
def customers():
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    cities = [
        c[0] for c in
        db.session.query(Customer.city)
        .filter(Customer.city.isnot(None))
        .distinct()
        .order_by(Customer.city)
        .all()
    ]
    return render_template(
        "customers.html",
        customers=customers,
        cities=cities
    )

# ==================================================
# Add Customer
# ==================================================
@customers_bp.route("/add", methods=["POST"])
def add_customer():
    data = request.json

    customer = Customer(
        name=data.get("name"),
        phone=data.get("phone"),
        phone2=data.get("phone2"),
        city=data.get("city"),
        address=data.get("address"),
        notes=data.get("notes")
    )

    db.session.add(customer)
    db.session.commit()
    
    # تعلم المحافظة والمنطقة من البيانات المدخلة
    from ai.learner import learn_city, learn_area
    import re
    
    if customer.city and customer.city.strip():
        # استخدام اسم الزبون والعنوان كنص للتعلم
        learning_text = f"{customer.name} {customer.address or ''} {customer.city}"
        learn_city(learning_text, customer.city.strip())
        # أيضاً تعلم من العنوان إذا كانت المحافظة موجودة فيه
        if customer.address and customer.city.strip() in customer.address:
            learn_city(customer.address, customer.city.strip())
    
    if customer.address and customer.address.strip():
        # محاولة استخراج المنطقة من العنوان
        area_keywords = ["حي", "منطقة", "محلة", "قرب", "شارع", "مجمع"]
        area_found = False
        
        for keyword in area_keywords:
            if keyword in customer.address:
                parts = customer.address.split(keyword)
                if len(parts) > 1:
                    # أخذ الكلمات بعد الكلمة المفتاحية
                    area = parts[1].strip()
                    # تنظيف المنطقة
                    area = re.sub(r'^[\d\s\-_.,:;]+', '', area).strip()
                    # أخذ أول 3-4 كلمات
                    area_words = area.split()[:4]
                    area = ' '.join(area_words).strip()
                    if area and len(area) > 2:
                        learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                        learn_area(learning_text, area)
                        # أيضاً تعلم من العنوان مباشرة
                        learn_area(customer.address, area)
                        area_found = True
                        break
        
        # إذا لم نجد كلمة مفتاحية، نتعلم العنوان كاملاً كمنطقة
        if not area_found and len(customer.address.strip()) > 3:
            # تنظيف العنوان من الأرقام في البداية
            cleaned_address = re.sub(r'^[\d\s\-_.,:;]+', '', customer.address.strip()).strip()
            if cleaned_address and len(cleaned_address) > 3:
                learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                learn_area(learning_text, cleaned_address)
                learn_area(customer.address, cleaned_address)
    
    return jsonify({
        "success": True,
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone
    })

# ==================================================
# Update Customer
# ==================================================
@customers_bp.route("/update/<int:id>", methods=["POST"])
def update_customer(id):
    customer = Customer.query.get_or_404(id)
    data = request.json

    customer.name = data.get("name")
    customer.phone = data.get("phone")
    customer.phone2 = data.get("phone2")
    customer.city = data.get("city")
    customer.address = data.get("address")
    customer.notes = data.get("notes")

    db.session.commit()
    
    # تعلم المحافظة والمنطقة من البيانات المحدثة
    from ai.learner import learn_city, learn_area
    
    if customer.city and customer.city.strip():
        # استخدام اسم الزبون والعنوان كنص للتعلم
        learning_text = f"{customer.name} {customer.address or ''} {customer.city}"
        learn_city(learning_text, customer.city.strip())
    
    if customer.address and customer.address.strip():
        # محاولة استخراج المنطقة من العنوان
        area_keywords = ["حي", "منطقة", "محلة"]
        for keyword in area_keywords:
            if keyword in customer.address:
                parts = customer.address.split(keyword)
                if len(parts) > 1:
                    area = parts[1].strip().split()[0] if parts[1].strip().split() else None
                    if area and len(area) > 2:
                        learning_text = f"{customer.name} {customer.address} {customer.city or ''}"
                        learn_area(learning_text, area)
                        break
    
    return jsonify({"success": True})

# ==================================================
# Delete Customer (if no orders)
# ==================================================
@customers_bp.route("/delete/<int:id>")
def delete_customer(id):
    customer = Customer.query.get_or_404(id)

    has_orders = Invoice.query.filter_by(customer_id=id).first()
    if has_orders:
        return jsonify({"error": "لا يمكن حذف زبون لديه طلبات"}), 400

    db.session.delete(customer)
    db.session.commit()
    return jsonify({"success": True})

# ==================================================
# Customer Orders
# ==================================================
@customers_bp.route("/orders/<int:id>")
def customer_orders(id):
    orders = Invoice.query.filter_by(customer_id=id).order_by(Invoice.created_at.desc()).all()
    return jsonify([
        {
            "id": o.id,
            "total": o.total,
            "status": o.status,
            "payment": o.payment_status,
            "date": o.created_at.strftime("%Y-%m-%d")
        } for o in orders
    ])


# ==================================================
# Export Customers
# ==================================================
@customers_bp.route("/export")
def export_customers():
    customers = Customer.query.order_by(Customer.created_at.desc()).all()
    rows = []
    for c in customers:
        rows.append({
            "المعرف": c.id,
            "الاسم": c.name or "",
            "الرقم": c.phone or "",
            "الرقم الآخر": c.phone2 or "",
            "المحافظة": c.city or "",
            "العنوان": c.address or "",
            "ملاحظات": c.notes or "",
            "تاريخ الإضافة": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "",
        })

    df = pd.DataFrame(rows)
    output = BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="customers.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ==================================================
# Import Customers
# ==================================================
@customers_bp.route("/import", methods=["POST"])
def import_customers():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "لم يتم اختيار ملف"})

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"success": False, "error": "لم يتم اختيار ملف"})

    raw_bytes = file.read()
    if not raw_bytes:
        return jsonify({"success": False, "error": "الملف فارغ"})

    df = None
    read_errors = []
    for reader in (
        lambda: pd.read_excel(BytesIO(raw_bytes), engine="openpyxl"),
        lambda: pd.read_excel(BytesIO(raw_bytes)),
        lambda: pd.read_csv(BytesIO(raw_bytes), encoding="utf-8-sig"),
        lambda: pd.read_csv(BytesIO(raw_bytes), encoding="cp1256"),
    ):
        try:
            df = reader()
            if df is not None:
                break
        except Exception as e:
            read_errors.append(str(e))

    if df is None:
        msg = read_errors[0] if read_errors else "تعذر قراءة الملف"
        return jsonify({"success": False, "error": f"تعذر قراءة الملف: {msg}"})

    # تنظيف أسماء الأعمدة لتجاوز اختلافات الفراغات/BOM
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]

    columns_map = {
        "الاسم": "name",
        "name": "name",
        "الرقم": "phone",
        "phone": "phone",
        "رقم": "phone",
        "الرقم الآخر": "phone2",
        "phone2": "phone2",
        "المحافظة": "city",
        "city": "city",
        "العنوان": "address",
        "address": "address",
        "ملاحظات": "notes",
        "notes": "notes",
    }

    normalized_rows = []
    for _, row in df.iterrows():
        item = {}
        for original_col, target_key in columns_map.items():
            if original_col in df.columns:
                value = row.get(original_col)
                item[target_key] = "" if pd.isna(value) else str(value).strip()
        normalized_rows.append(item)

    imported = 0
    skipped = 0
    for item in normalized_rows:
        name = (item.get("name") or "").strip()
        phone = (item.get("phone") or "").strip()
        if not name or not phone:
            skipped += 1
            continue

        existing = Customer.query.filter_by(phone=phone).first()
        if existing:
            existing.name = name
            existing.phone2 = (item.get("phone2") or "").strip() or None
            existing.city = (item.get("city") or "").strip() or None
            existing.address = (item.get("address") or "").strip() or None
            existing.notes = (item.get("notes") or "").strip() or None
        else:
            db.session.add(Customer(
                name=name,
                phone=phone,
                phone2=(item.get("phone2") or "").strip() or None,
                city=(item.get("city") or "").strip() or None,
                address=(item.get("address") or "").strip() or None,
                notes=(item.get("notes") or "").strip() or None,
            ))
        imported += 1

    if imported > 0:
        db.session.commit()
    else:
        db.session.rollback()

    return jsonify({
        "success": True,
        "message": f"تم استيراد/تحديث {imported} زبون",
        "imported": imported,
        "skipped": skipped,
    })
