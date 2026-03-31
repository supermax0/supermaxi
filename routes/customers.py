from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pandas as pd
from flask import Blueprint, render_template, request, jsonify, send_file
from extensions import db
from models.customer import Customer
from models.invoice import Invoice

customers_bp = Blueprint("customers", __name__, url_prefix="/customers")


def _xlsx_xml_to_dataframe(raw_bytes):
    """Fallback reader for malformed xlsx style metadata."""
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    def _col_to_idx(cell_ref):
        letters = "".join(ch for ch in (cell_ref or "") if ch.isalpha()).upper()
        if not letters:
            return None
        num = 0
        for ch in letters:
            num = num * 26 + (ord(ch) - 64)
        return num - 1

    with ZipFile(BytesIO(raw_bytes)) as zf:
        shared_strings = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(".//x:si", ns):
                text_parts = [t.text or "" for t in si.findall(".//x:t", ns)]
                shared_strings.append("".join(text_parts))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        first_sheet = workbook.find(".//x:sheets/x:sheet", ns)
        if first_sheet is None:
            return pd.DataFrame()

        rid = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            if rel.attrib.get("Id") == rid:
                target = rel.attrib.get("Target")
                break
        if not target:
            return pd.DataFrame()

        if not target.startswith("worksheets/"):
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
        else:
            target = f"xl/{target}"

        sheet_root = ET.fromstring(zf.read(target))
        rows_data = []
        for row in sheet_root.findall(".//x:sheetData/x:row", ns):
            values_by_col = {}
            max_col = -1
            for c in row.findall("x:c", ns):
                col_idx = _col_to_idx(c.attrib.get("r"))
                if col_idx is None:
                    col_idx = max_col + 1
                max_col = max(max_col, col_idx)

                ctype = c.attrib.get("t")
                value = ""
                v = c.find("x:v", ns)
                if ctype == "s":
                    raw = (v.text or "") if v is not None else ""
                    try:
                        value = shared_strings[int(raw)]
                    except Exception:
                        value = raw
                elif ctype == "inlineStr":
                    tnode = c.find(".//x:is/x:t", ns)
                    value = tnode.text if tnode is not None else ""
                elif v is not None:
                    value = v.text or ""
                else:
                    value = ""

                values_by_col[col_idx] = value

            values = [values_by_col.get(i, "") for i in range(max_col + 1)] if max_col >= 0 else []
            rows_data.append(values)

    if not rows_data:
        return pd.DataFrame()

    max_len = max(len(r) for r in rows_data)
    normalized = [r + [""] * (max_len - len(r)) for r in rows_data]
    # choose first meaningful row as header (skip blank/report-title rows)
    header_idx = 0
    for i, row in enumerate(normalized):
        non_empty = [str(x).strip() for x in row if str(x).strip()]
        if len(non_empty) >= 2:
            header_idx = i
            break

    headers = [str(h).strip() for h in normalized[header_idx]]
    # ensure unique, non-empty headers
    safe_headers = []
    seen = {}
    for i, h in enumerate(headers):
        key = h or f"col_{i+1}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}_{seen[key]}"
        safe_headers.append(key)

    data_rows = normalized[header_idx + 1:]
    # drop fully empty rows
    data_rows = [r for r in data_rows if any(str(x).strip() for x in r)]
    return pd.DataFrame(data_rows, columns=safe_headers)

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
        try:
            df = _xlsx_xml_to_dataframe(raw_bytes)
        except Exception as e:
            read_errors.append(str(e))

    if df is None:
        msg = read_errors[0] if read_errors else "تعذر قراءة الملف"
        return jsonify({"success": False, "error": f"تعذر قراءة الملف: {msg}"})

    # تنظيف أسماء الأعمدة لتجاوز اختلافات الفراغات/BOM
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]

    def _norm_col(name):
        text = str(name or "").strip().replace("\ufeff", "").replace("\u200f", "").replace("\u200e", "")
        return text.lower()

    columns_map = {
        "الاسم": "name",
        "الإسم": "name",
        "name": "name",
        "الرقم": "phone",
        "الموبايل": "phone",
        "phone": "phone",
        "رقم": "phone",
        "الرقم الآخر": "phone2",
        "phone2": "phone2",
        "المحافظة": "city",
        "المحافظات": "city",
        "city": "city",
        "العنوان": "address",
        "address": "address",
        "ملاحظات": "notes",
        "notes": "notes",
        "تاريخ الإضافة": "created_at",
        "أضيف في": "created_at",
        "وأضاف في": "created_at",
        "created_at": "created_at",
    }
    normalized_columns = {_norm_col(k): v for k, v in columns_map.items()}

    normalized_rows = []
    for _, row in df.iterrows():
        item = {}
        for col in df.columns:
            target_key = normalized_columns.get(_norm_col(col))
            if target_key:
                value = row.get(col)
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
            raw_created_at = (item.get("created_at") or "").strip()
            if raw_created_at:
                parsed_date = pd.to_datetime(raw_created_at, errors="coerce", dayfirst=True)
                if pd.notna(parsed_date):
                    existing.created_at = parsed_date.to_pydatetime()
        else:
            customer = Customer(
                name=name,
                phone=phone,
                phone2=(item.get("phone2") or "").strip() or None,
                city=(item.get("city") or "").strip() or None,
                address=(item.get("address") or "").strip() or None,
                notes=(item.get("notes") or "").strip() or None,
            )
            raw_created_at = (item.get("created_at") or "").strip()
            if raw_created_at:
                parsed_date = pd.to_datetime(raw_created_at, errors="coerce", dayfirst=True)
                if pd.notna(parsed_date):
                    customer.created_at = parsed_date.to_pydatetime()
            db.session.add(customer)
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
