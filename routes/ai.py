from flask import Blueprint, request, jsonify, session
from extensions import db
from models.customer import Customer

from ai.ocr import extract_text
from ai.ai_service import analyze as ai_analyze
from ai import ai_utils as ai_layer_utils
from ai.parser import (
    extract_phone,
    extract_name,
    extract_address,
    extract_city,
    extract_area
)
from ai.learner import learn, learn_city, learn_area
import re
import pytesseract
import cv2
import numpy as np
from PIL import Image


# مسار Tesseract (مهم)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

# ===============================
# OCR from image
# ===============================
@ai_bp.route("/ocr", methods=["POST"])
def ocr_image():
    # التحقق من نوع البيانات المرسلة
    # إذا كان JSON، فهو confirmation request
    if request.is_json:
        return jsonify({"error": "use /ai/ocr/confirm for confirmation"}), 400
    
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "no_image"}), 400

    try:
        raw_text = extract_text(file.read())
        
        # إذا كان النص فارغاً أو لا يحتوي على أحرف عربية، قد تكون المشكلة في تثبيت اللغة
        if not raw_text or not any('\u0600' <= c <= '\u06FF' for c in raw_text):
            # جرب التحقق من تثبيت اللغة العربية
            try:
                langs = pytesseract.get_languages(config='')
                if 'ara' not in langs:
                    return jsonify({
                        "error": "arabic_language_not_installed",
                        "message": "اللغة العربية غير مثبتة في Tesseract. يرجى تثبيت اللغة العربية.",
                        "raw_text": raw_text,
                        "name": extract_name(raw_text) if raw_text else "",
                        "phone": extract_phone(raw_text) if raw_text else "",
                        "address": extract_address(raw_text) if raw_text else "",
                        "city": extract_city(raw_text) if raw_text else ""
                    })
            except:
                pass
        
        return jsonify({
            "raw_text": raw_text,
            "name": extract_name(raw_text),
            "phone": extract_phone(raw_text),
            "address": extract_address(raw_text),
            "city": extract_city(raw_text)
        })
    except Exception as e:
        return jsonify({
            "error": "ocr_error",
            "message": str(e),
            "raw_text": "",
            "name": "",
            "phone": "",
            "address": "",
            "city": ""
        }), 500

# ===============================
# Confirm + Learn + Save
# ===============================
@ai_bp.route("/ocr/confirm", methods=["POST"])
def ocr_confirm():
    data = request.get_json() or {}

    raw = data.get("raw_text", "")
    name = data.get("name")
    phone = data.get("phone")
    address = data.get("address")
    city = data.get("city")

    # التحقق من البيانات المطلوبة
    if not name or not phone:
        return jsonify({
            "status": "error",
            "error": "name and phone are required"
        }), 400

    # تعلم من النص الخام
    learn(raw, f"{name}\n{phone}\n{address}")
    
    # تعلم المحافظة إذا كانت موجودة
    if city and city.strip():
        learn_city(raw, city.strip())
        # أيضاً تعلم المحافظة من العنوان إذا كانت موجودة فيه
        if address and city.strip() in address:
            learn_city(address, city.strip())
    
    # تعلم المنطقة من العنوان إذا كان موجوداً
    if address and address.strip():
        # محاولة استخراج المنطقة من العنوان
        area_keywords = ["حي", "منطقة", "محلة", "قرب", "شارع", "مجمع"]
        area_found = False
        
        for keyword in area_keywords:
            if keyword in address:
                parts = address.split(keyword)
                if len(parts) > 1:
                    # أخذ الكلمات بعد الكلمة المفتاحية
                    area = parts[1].strip()
                    # تنظيف المنطقة
                    area = re.sub(r'^[\d\s\-_.,:;]+', '', area).strip()
                    # أخذ أول 3-4 كلمات
                    area_words = area.split()[:4]
                    area = ' '.join(area_words).strip()
                    if area and len(area) > 2:
                        learn_area(raw, area)
                        # أيضاً تعلم من العنوان مباشرة
                        learn_area(address, area)
                        area_found = True
                        break
        
        # إذا لم نجد كلمة مفتاحية، نتعلم العنوان كاملاً كمنطقة
        if not area_found and len(address.strip()) > 3:
            # تنظيف العنوان من الأرقام في البداية
            cleaned_address = re.sub(r'^[\d\s\-_.,:;]+', '', address.strip()).strip()
            if cleaned_address and len(cleaned_address) > 3:
                learn_area(raw, cleaned_address)
                learn_area(address, cleaned_address)

    existing = Customer.query.filter_by(phone=phone).first()
    if existing:
        # تحديث البيانات إذا تغيرت
        if city and city != existing.city:
            existing.city = city
        if address and address != existing.address:
            existing.address = address
        db.session.commit()
        
        return jsonify({
            "status": "exists",
            "id": existing.id,
            "name": existing.name,
            "phone": existing.phone
        })

    customer = Customer(
        name=name or "زبون",
        phone=phone,
        address=address,
        city=city
    )

    db.session.add(customer)
    db.session.commit()

    return jsonify({
        "status": "success",
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone
    })


# ===============================
# AI Analyze (محلل مالي / تقارير ذكية)
# ===============================
@ai_bp.route("/analyze", methods=["POST"])
def analyze_route():
    """
    POST JSON: type (sales|profit|inventory|report|orders), period, message (optional),
    date_from, date_to (optional for custom period).
    Returns JSON: success, analysis (text), error, period_label.
    """
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول.", "analysis": None}), 401

    data = request.get_json(silent=True) or {}
    analyze_type = (data.get("type") or "").strip().lower()
    period = (data.get("period") or "last_30_days").strip().lower()
    message = (data.get("message") or "").strip()
    custom_date_from = (data.get("date_from") or "").strip() or None
    custom_date_to = (data.get("date_to") or "").strip() or None

    # Rate limit by session (or IP if no session)
    identifier = str(session.get("user_id") or request.remote_addr or "anon")
    allowed, rate_err = ai_layer_utils.check_rate_limit(identifier)
    if not allowed:
        return jsonify({"success": False, "error": rate_err, "analysis": None}), 429

    result = ai_analyze(
        analyze_type=analyze_type or "report",
        period=period,
        message=message,
        custom_date_from=custom_date_from,
        custom_date_to=custom_date_to,
    )
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result)
