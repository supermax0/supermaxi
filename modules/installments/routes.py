from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from flask import Blueprint, Response, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from extensions import db
from models.customer import Customer
from models.product import Product
from modules.installments.models import (
    InstallmentApplication,
    InstallmentApplicationActivity,
    InstallmentApplicationDocument,
    InstallmentApplicationItem,
    InstallmentContract,
    InstallmentCustomerAccount,
    InstallmentPayment,
    InstallmentPlan,
    InstallmentProduct,
    InstallmentProductMedia,
    InstallmentSchedule,
    InstallmentSettings,
)
from modules.installments.image_enhancement import (
    StorefrontImageError,
    enhance_storefront_image,
    remove_storefront_enhancement_marker,
)
from modules.installments.ad_service import PLATFORM_CONFIG, generate_ad_creative
from modules.installments.schema import ensure_installment_schema
from modules.installments.services import (
    ApplicationService,
    ApprovalService,
    InstallmentCalculationService,
    InstallmentError,
    IRAQI_GOVERNORATES,
    PaymentService,
    allowed_installment_durations,
    find_customer_by_phone,
    normalize_phone,
    synchronize_allowed_duration_plans,
    validate_application_transition,
)
from modules.phone_app.services.rate_limit import allow_request
from modules.storefront.services.category_assets import category_image_path
from modules.storefront.services.category_normalize import merge_washer_category
from utils.activity_logger import log_activity
from utils.branch_migration import ensure_branch_schema
from utils.permission_checks import check_permission, get_current_employee, guard_permission
from utils.product_schema_guard import ensure_product_schema


installments_admin_bp = Blueprint("installments_admin", __name__, url_prefix="/installments")
installments_store_bp = Blueprint("installments_store", __name__, url_prefix="/installment-store")
installments_short_bp = Blueprint("installments_short", __name__)


# خيارات جاهزة للنموذج السريع. حقل العلامة التجارية يقبل كذلك أي قيمة يكتبها
# المستخدم، لذلك لا تصبح القائمة الثابتة قيداً على الماركات المحلية أو الجديدة.
IRAQ_MARKET_BRANDS = (
    "Samsung", "Apple", "Xiaomi", "Redmi", "Poco", "Huawei", "Honor", "Realme", "Oppo", "Vivo",
    "Infinix", "Tecno", "Nokia", "Motorola", "OnePlus", "Nothing", "Google", "ZTE", "Itel", "Asus",
    "Lenovo", "Dell", "HP", "Acer", "MSI", "Microsoft", "Razer", "Canon", "Epson", "Brother",
    "LG", "Sony", "TCL", "Hisense", "Sharp", "Panasonic", "Philips", "Toshiba", "Skyworth", "Haier",
    "Midea", "Gree", "General", "Carrier", "Daikin", "Aux", "Chigo", "York", "Bosch", "Siemens",
    "Beko", "Ariston", "Indesit", "Whirlpool", "Electrolux", "Zanussi", "Vestel", "Candy", "Hoover", "Hitachi",
    "Nikai", "Geepas", "Gosonic", "Royal", "Super General", "Newal", "Kumtel", "Fakir", "Kenwood", "Moulinex",
    "Tefal", "Braun", "Delonghi", "Black+Decker", "Karcher", "Dyson", "JBL", "Harman Kardon", "Bose", "Anker",
    "Soundcore", "Baseus", "Hoco", "Joyroom", "Oraimo", "Green Lion", "Porodo", "Powerology", "Logitech", "Rapoo",
    "PlayStation", "Xbox", "Nintendo", "AMD", "Intel", "Nvidia", "Dahua", "Hikvision", "Ezviz", "Imou",
)

PRODUCT_CATEGORY_CATALOG = {
    "هواتف وأجهزة لوحية": ["هواتف ذكية", "هواتف عادية", "أجهزة لوحية", "ساعات ذكية", "قطع غيار هواتف"],
    "حواسيب ولابتوبات": ["لابتوبات", "حواسيب مكتبية", "شاشات حاسوب", "طابعات", "مكونات حاسوب"],
    "تلفزيونات وشاشات": ["تلفزيونات", "شاشات ذكية", "ريسيفرات", "حوامل شاشات", "أجهزة عرض"],
    "أجهزة منزلية": ["ثلاجات", "مجمدات", "غسالات", "طباخات وأفران", "غسالات صحون", "مكانس", "أجهزة مطبخ"],
    "تكييف وتبريد": ["سبلت", "مبردات هواء", "مراوح", "سخانات", "منقيات هواء"],
    "صوتيات": ["سماعات", "مكبرات صوت", "مسجلات", "مايكروفونات"],
    "ألعاب وترفيه": ["أجهزة ألعاب", "ألعاب", "ملحقات ألعاب"],
    "كاميرات ومراقبة": ["كاميرات", "أنظمة مراقبة", "مسجلات مراقبة", "أقفال ذكية"],
    "طاقة وكهربائيات": ["مولدات", "UPS", "بطاريات", "طاقة شمسية", "محولات وشواحن"],
    "عناية شخصية": ["عطور", "عناية بالبشرة", "عناية بالشعر", "حلاقة", "أجهزة تجميل"],
    "أثاث ومفروشات": ["غرف نوم", "أطقم جلوس", "طاولات", "كراسي", "مراتب"],
    "إكسسوارات": ["شواحن", "كيبلات", "حافظات", "حقائب", "حوامل", "ذاكرة وتخزين"],
    "أخرى": ["منتجات متنوعة"],
}

_PRODUCT_NAME_RULES = (
    ("هواتف وأجهزة لوحية", "ساعات ذكية", ("ساعة ذكية", "smart watch", "smartwatch", "apple watch")),
    ("هواتف وأجهزة لوحية", "أجهزة لوحية", ("تابلت", "tablet", "ipad", "آيباد")),
    ("هواتف وأجهزة لوحية", "هواتف ذكية", ("هاتف", "موبايل", "mobile", "phone", "iphone", "galaxy", "ريدمي", "redmi")),
    ("حواسيب ولابتوبات", "طابعات", ("طابعة", "printer")),
    ("حواسيب ولابتوبات", "لابتوبات", ("لابتوب", "لاب توب", "laptop", "notebook", "macbook")),
    ("حواسيب ولابتوبات", "شاشات حاسوب", ("monitor", "شاشة كمبيوتر", "شاشة حاسوب")),
    ("تلفزيونات وشاشات", "أجهزة عرض", ("بروجكتر", "projector")),
    ("تلفزيونات وشاشات", "تلفزيونات", ("تلفزيون", "tv", "smart tv", "شاشة ذكية", "شاشة led")),
    ("أجهزة منزلية", "ثلاجات", ("ثلاجة", "refrigerator")),
    ("أجهزة منزلية", "مجمدات", ("فريزر", "freezer", "مجمدة")),
    ("أجهزة منزلية", "غسالات صحون", ("غسالة صحون", "dishwasher")),
    ("أجهزة منزلية", "غسالات", ("غسالة", "washer", "washing machine")),
    ("أجهزة منزلية", "طباخات وأفران", ("طباخ", "فرن", "oven", "cooker")),
    ("أجهزة منزلية", "مكانس", ("مكنسة", "vacuum")),
    ("تكييف وتبريد", "سبلت", ("سبلت", "مكيف", "تكييف", "split", "air conditioner")),
    ("تكييف وتبريد", "مبردات هواء", ("مبرد", "air cooler")),
    ("تكييف وتبريد", "مراوح", ("مروحة", "fan")),
    ("صوتيات", "سماعات", ("سماعة", "سماعات", "headphone", "earbuds", "airpods")),
    ("صوتيات", "مكبرات صوت", ("سبيكر", "speaker", "soundbar")),
    ("ألعاب وترفيه", "أجهزة ألعاب", ("بلايستيشن", "playstation", "xbox", "nintendo")),
    ("كاميرات ومراقبة", "كاميرات", ("كاميرا", "camera")),
    ("كاميرات ومراقبة", "أنظمة مراقبة", ("مراقبة", "cctv", "dvr", "nvr")),
    ("طاقة وكهربائيات", "مولدات", ("مولدة", "مولد", "generator")),
    ("طاقة وكهربائيات", "UPS", ("ups", "يو بي اس")),
    ("أثاث ومفروشات", "غرف نوم", ("غرفة نوم", "سرير", "bedroom")),
    ("أثاث ومفروشات", "أطقم جلوس", ("صوفا", "كنبة", "انتريه", "sofa")),
    ("عناية شخصية", "عطور", ("عطر", "perfume")),
    ("عناية شخصية", "حلاقة", ("ماكينة حلاقة", "shaver", "trimmer")),
    ("إكسسوارات", "شواحن", ("شاحن", "charger", "power bank", "باور بانك")),
    ("إكسسوارات", "كيبلات", ("كيبل", "كابل", "cable")),
    ("إكسسوارات", "ذاكرة وتخزين", ("هارد", "ssd", "flash", "ذاكرة", "memory card")),
)


def _infer_product_category(name: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", str(name or "").strip().lower())
    for category, subcategory, keywords in _PRODUCT_NAME_RULES:
        if any(keyword in normalized for keyword in keywords):
            return category, subcategory
    return "أخرى", "منتجات متنوعة"


def _ean13_check_digit(first_twelve: str) -> str:
    total = sum(int(value) * (1 if index % 2 == 0 else 3) for index, value in enumerate(first_twelve))
    return str((10 - (total % 10)) % 10)


def _generated_barcode(tenant_id: int, preferred: str | None = None) -> str:
    cleaned = re.sub(r"\D+", "", str(preferred or ""))
    if (
        len(cleaned) == 13
        and cleaned[-1] == _ean13_check_digit(cleaned[:12])
        and not Product.query.filter_by(tenant_id=tenant_id, barcode=cleaned).first()
    ):
        return cleaned
    for _attempt in range(40):
        first_twelve = f"20{tenant_id % 1000:03d}{secrets.randbelow(10_000_000):07d}"
        candidate = first_twelve + _ean13_check_digit(first_twelve)
        if not Product.query.filter_by(tenant_id=tenant_id, barcode=candidate).first():
            return candidate
    raise InstallmentError("تعذر توليد باركود فريد؛ حاول مرة أخرى")


def _generated_sku(tenant_id: int, preferred: str | None = None) -> str:
    cleaned = re.sub(r"[^A-Z0-9_-]+", "-", str(preferred or "").strip().upper()).strip("-")[:100]
    if len(cleaned) >= 3 and not Product.query.filter_by(tenant_id=tenant_id, sku=cleaned).first():
        return cleaned
    for _attempt in range(40):
        candidate = f"FIN-{datetime.utcnow():%y%m%d}-{secrets.token_hex(3).upper()}"
        if not Product.query.filter_by(tenant_id=tenant_id, sku=candidate).first():
            return candidate
    raise InstallmentError("تعذر توليد SKU فريد؛ حاول مرة أخرى")


def _json_error(message: str, status: int = 400, code: str = "validation_error"):
    return jsonify({"success": False, "error": message, "code": code}), status


def _date_arg(name: str) -> date | None:
    value = str(request.args.get(name) or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _bounded_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _csv_download(filename: str, headings: list[str], rows) -> Response:
    stream = io.StringIO()
    stream.write("\ufeff")
    writer = csv.writer(stream)
    writer.writerow(headings)
    writer.writerows(rows)
    return Response(
        stream.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _guard_installment(legacy: str, granular: str, *, json_response: bool | None = None):
    if check_permission(legacy) or check_permission(granular):
        return None
    return guard_permission(legacy, json=json_response)


def _csrf_guard():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if (request.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
        return _json_error("تم رفض طلب من مصدر خارجي", 403, "CSRF_REJECTED")
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if source and urlsplit(source).netloc and urlsplit(source).netloc != request.host:
        return _json_error("تم رفض طلب من مصدر غير موثوق", 403, "CSRF_REJECTED")
    return None


def _valid_magic(mime: str, header: bytes) -> bool:
    checks = {
        "image/jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        "image/png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
        "application/pdf": lambda b: b.startswith(b"%PDF-"),
        "video/mp4": lambda b: len(b) >= 12 and b[4:8] == b"ftyp",
        "video/webm": lambda b: b.startswith(b"\x1aE\xdf\xa3"),
    }
    return bool(checks.get(mime, lambda _b: False)(header))


def _save_settings_image(file, tenant_id: int, kind: str) -> str:
    mime = str(file.mimetype or "").lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if mime not in extensions:
        raise InstallmentError("نوع صورة الهوية البصرية غير مدعوم")
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    header = file.stream.read(16)
    file.stream.seek(0)
    if size <= 0 or size > 5 * 1024 * 1024 or not _valid_magic(mime, header):
        raise InstallmentError("صورة الهوية البصرية غير صالحة أو كبيرة جداً")
    rel_dir = Path("uploads") / "installments" / str(tenant_id) / "branding"
    target_dir = Path(current_app.static_folder) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{kind}-{uuid4().hex}{extensions[mime]}"
    file.save(target_dir / filename)
    return (rel_dir / filename).as_posix()


def _enhance_media_record(media: InstallmentProductMedia) -> str:
    """Convert one stored product image to the current transparent PNG format."""
    if media.media_type != "image":
        return "skipped"
    static_root = Path(current_app.static_folder).resolve()
    upload_root = (static_root / "uploads" / "installments").resolve()
    target = (static_root / media.file_path).resolve()
    target.relative_to(upload_root)
    if not target.is_file():
        raise OSError("missing installment media")

    destination = target if target.suffix.lower() == ".png" else target.with_suffix(".png")
    result = enhance_storefront_image(
        target,
        media.mime_type or "image/jpeg",
        output_path=destination,
        output_mime_type="image/png",
    )
    converted = destination != target
    if not result.get("enhanced") and not converted:
        return "skipped"
    if converted:
        remove_storefront_enhancement_marker(target)
        target.unlink(missing_ok=True)
        media.file_path = destination.relative_to(static_root).as_posix()
    media.mime_type = "image/png"
    media.size_bytes = destination.stat().st_size
    return "updated"


def _auto_enhance_storefront_media(items, *, max_images: int = 16, one_per_product: bool = True) -> int:
    """Lazily upgrade legacy images when they first appear in the public store."""
    updated = 0
    inspected = 0
    for item in items:
        media_rows = sorted(item.media, key=lambda row: (not row.is_main, row.sort_order))
        if one_per_product:
            media_rows = media_rows[:1]
        for media in media_rows:
            if media.media_type != "image" or inspected >= max_images:
                continue
            inspected += 1
            try:
                if _enhance_media_record(media) == "updated":
                    updated += 1
            except (ValueError, OSError, StorefrontImageError):
                current_app.logger.warning("unable to transparently enhance installment media %s", media.file_path)
        if inspected >= max_images:
            break
    if updated:
        db.session.commit()
    return updated


def _tenant_id() -> int:
    contextual_id = getattr(g, "installment_tenant_id", None) or session.get("tenant_id")
    if contextual_id:
        return int(contextual_id)
    product_tenant_id = db.session.query(Product.tenant_id).filter(Product.tenant_id.isnot(None)).limit(1).scalar()
    if product_tenant_id:
        return int(product_tenant_id)
    from models.tenant import Tenant

    tenant = Tenant.query.order_by(Tenant.id.asc()).first()
    if not tenant:
        raise InstallmentError("لا توجد شركة مهيأة في قاعدة البيانات الحالية")
    return int(tenant.id)


def _scoped(model, tenant_id: int | None = None):
    return model.query.filter_by(tenant_id=tenant_id or _tenant_id())


def _sanitize_map_url(raw) -> str | None:
    value = str(raw or "").strip()[:500]
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return None


def _cart_key(tenant_slug: str) -> str:
    return f"installment_cart:{tenant_slug}"


def _favorite_key(tenant_slug: str) -> str:
    return f"installment_favorites:{tenant_slug}"


def _favorite_ids(tenant_slug: str) -> list[int]:
    raw = session.get(_favorite_key(tenant_slug)) or []
    ids: list[int] = []
    seen: set[int] = set()
    for value in raw if isinstance(raw, list) else []:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id <= 0 or product_id in seen:
            continue
        seen.add(product_id)
        ids.append(product_id)
        if len(ids) >= 50:
            break
    return ids


def _favorite_cards(tenant_slug: str) -> list[dict]:
    ids = _favorite_ids(tenant_slug)
    if not ids:
        return []
    allowed_durations = _allowed_durations_for_tenant(_tenant_id())
    products = (
        _scoped(InstallmentProduct)
        .options(
            selectinload(InstallmentProduct.product),
            selectinload(InstallmentProduct.media),
            selectinload(InstallmentProduct.plans),
        )
        .filter(InstallmentProduct.id.in_(ids), InstallmentProduct.status == "published")
        .all()
    )
    by_id = {item.id: item for item in products}
    return [_store_card(by_id[product_id], allowed_durations) for product_id in ids if product_id in by_id]


def _customer_account_key(tenant_slug: str) -> str:
    return f"installment_customer_account:{tenant_slug}"


def _current_store_account(tenant_slug: str | None = None) -> InstallmentCustomerAccount | None:
    cached = getattr(g, "installment_customer_account", None)
    if cached is not None:
        return cached
    slug = str(tenant_slug or getattr(g, "tenant", "") or "").strip().lower()
    account_id = session.get(_customer_account_key(slug))
    if not account_id:
        return None
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        session.pop(_customer_account_key(slug), None)
        session.modified = True
        return None
    account = InstallmentCustomerAccount.query.filter_by(
        id=account_id, tenant_id=_tenant_id(), is_active=True
    ).first()
    if not account:
        session.pop(_customer_account_key(slug), None)
        session.modified = True
        return None
    g.installment_customer_account = account
    return account


def _account_order_data(data: dict, account: InstallmentCustomerAccount | None) -> dict:
    values = dict(data)
    if account and account.customer:
        values["_customer_id"] = account.customer_id
        values["customer_name"] = account.customer.name
        values["phone"] = account.phone
    return values


STORE_APPLICATION_STATUS_LABELS = {
    "new": "تم استلام الطلب",
    "under_review": "قيد المراجعة",
    "documents_required": "مطلوب استكمال مستندات",
    "waiting_approval": "بانتظار الموافقة",
    "approved": "تمت الموافقة",
    "contract_pending": "بانتظار إنشاء العقد",
    "contract_signed": "تم توقيع العقد",
    "ready_for_fulfillment": "جاهز للتجهيز",
    "delivered": "تم التسليم",
    "active": "عقد فعّال",
    "completed": "مكتمل",
    "rejected": "مرفوض",
    "cancelled": "ملغي",
}


def _cart_rows(tenant_slug: str) -> list[dict]:
    raw = session.get(_cart_key(tenant_slug)) or []
    allowed_durations = _allowed_durations_for_tenant(_tenant_id())
    rows = []
    for selection in raw if isinstance(raw, list) else []:
        item = _scoped(InstallmentProduct).filter_by(id=int(selection.get("product_id") or 0), status="published").first()
        plan = _scoped(InstallmentPlan).filter_by(id=int(selection.get("plan_id") or 0), active=True).first()
        quantity = max(1, min(int(selection.get("quantity") or 1), 99))
        if not item or not plan or plan.installment_product_id != item.id or (allowed_durations and plan.months not in allowed_durations):
            continue
        rows.append({"item": item, "plan": plan, "quantity": quantity, "calculation": InstallmentCalculationService.calculate(item.cash_price, plan, quantity)})
    return rows


def _cart_count(tenant_slug: str) -> int:
    return sum(row["quantity"] for row in _cart_rows(tenant_slug))


def _allowed_durations_for_tenant(tenant_id: int) -> set[int]:
    settings = InstallmentSettings.query.filter_by(tenant_id=tenant_id).first()
    return allowed_installment_durations(settings)


def _validate_plan_duration(tenant_id: int, months: int) -> None:
    allowed_durations = _allowed_durations_for_tenant(tenant_id)
    if allowed_durations and months not in allowed_durations:
        choices = "، ".join(str(value) for value in sorted(allowed_durations))
        raise InstallmentError(f"مدة {months} شهر غير مسموحة؛ المدد المتاحة هي: {choices}")


def _ensure_allowed_duration_plans(tenant_id: int, installment_product_id: int | None = None) -> bool:
    """Backfill duration variants for products created before global duration rules existed."""
    allowed_durations = _allowed_durations_for_tenant(tenant_id)
    if not allowed_durations:
        return False

    query = InstallmentProduct.query.filter_by(tenant_id=tenant_id)
    if installment_product_id is not None:
        query = query.filter_by(id=installment_product_id)
    missing_variants = [
        ~InstallmentProduct.plans.any(InstallmentPlan.months == months)
        for months in allowed_durations
    ]
    needs_backfill = query.filter(
        InstallmentProduct.plans.any(),
        db.or_(*missing_variants),
    ).first()
    if not needs_backfill:
        return False

    try:
        created, deactivated = synchronize_allowed_duration_plans(
            tenant_id,
            allowed_durations,
            installment_product_id,
        )
        if created or deactivated:
            db.session.commit()
            return True
    except IntegrityError:
        # Another request may have repaired the same legacy product first.
        db.session.rollback()
    return False


def _store_page_context(tenant_slug: str, **extra) -> dict:
    tenant_id = _tenant_id()
    settings = InstallmentSettings.query.filter_by(tenant_id=tenant_id).first()
    allowed_durations = allowed_installment_durations(settings)
    max_months_query = (
        db.session.query(db.func.max(InstallmentPlan.months))
        .join(InstallmentProduct, InstallmentProduct.id == InstallmentPlan.installment_product_id)
        .filter(
            InstallmentPlan.tenant_id == tenant_id,
            InstallmentPlan.active.is_(True),
            InstallmentProduct.status == "published",
        )
    )
    if allowed_durations:
        max_months_query = max_months_query.filter(InstallmentPlan.months.in_(allowed_durations))
    max_months = max_months_query.scalar() or 0
    context = {
        "tenant_slug": tenant_slug,
        "settings": settings,
        "cart_count": _cart_count(tenant_slug),
        "current_year": date.today().year,
        "max_months": int(max_months),
        "store_page": True,
    }
    context.update(extra)
    return context


def _store_section_name(item: InstallmentProduct) -> str:
    return merge_washer_category(item.category, item.title)


def _published_category_names(tenant_id: int) -> list[str]:
    rows = (
        db.session.query(InstallmentProduct.category, InstallmentProduct.title)
        .filter(
            InstallmentProduct.tenant_id == tenant_id,
            InstallmentProduct.status == "published",
            InstallmentProduct.category.isnot(None),
            InstallmentProduct.category != "",
        )
        .all()
    )
    return sorted({name for category, title in rows if (name := merge_washer_category(category, title))})


def _published_category_cards(tenant_id: int) -> list:
    _ensure_allowed_duration_plans(tenant_id)
    allowed_durations = _allowed_durations_for_tenant(tenant_id)
    items = (
        _scoped(InstallmentProduct, tenant_id)
        .options(selectinload(InstallmentProduct.product), selectinload(InstallmentProduct.media), selectinload(InstallmentProduct.plans))
        .filter(InstallmentProduct.status == "published")
        .order_by(InstallmentProduct.created_at.asc(), InstallmentProduct.id.asc())
        .all()
    )
    grouped: dict[str, list] = {}
    for item in items:
        name = _store_section_name(item)
        if not name:
            continue
        grouped.setdefault(name, []).append(item)
    cards = []
    for name, bucket in sorted(grouped.items(), key=lambda row: row[0]):
        cards.append(
            {
                "name": name,
                "count": len(bucket),
                "preview": _store_card(bucket[0], allowed_durations),
                "category_image": category_image_path(name),
            }
        )
    return cards


def _parse_product_specs(text: str | None) -> dict:
    """Turn product copy into tidy label/value rows and readable feature cards."""
    raw = str(text or "").strip()
    if not raw:
        return {"rows": [], "features": [], "paragraph": ""}

    # Bullets, semicolons, and sentence endings delimit specifications. Arabic
    # and English commas stay inside the value (for example a programs list).
    chunks = [
        part.strip(" \t\r\n-–—•·.!؟")
        for part in re.split(r"\s*(?:[•●▪◦·]+|[؛;]+|\r?\n+|(?<=[.!؟])\s+)\s*", raw)
        if part.strip(" \t\r\n-–—•·.!؟")
    ]
    if len(chunks) <= 1 and len(raw) > 180 and not re.search(r"[:：＝=]", raw):
        return {"rows": [], "features": [], "paragraph": raw}

    rows = []
    features = []
    for chunk in chunks:
        matched = re.split(r"\s*[:：＝=]\s*", chunk, maxsplit=1)
        if len(matched) == 2 and matched[0].strip() and matched[1].strip() and len(matched[0].strip()) <= 48:
            rows.append({"label": matched[0].strip(), "value": matched[1].strip()})
            continue

        dashed = [part.strip() for part in re.split(r"\s+[–—-]\s+", chunk) if part.strip()]
        if len(dashed) > 1:
            features.extend(dashed)
            continue

        features.append(chunk)

    rows = list({(row["label"], row["value"]): row for row in rows}.values())
    features = list(dict.fromkeys(feature for feature in features if feature))
    if not rows and not features:
        return {"rows": [], "features": [], "paragraph": raw}
    return {"rows": rows, "features": features, "paragraph": ""}


def _store_card(item: InstallmentProduct, allowed_durations: set[int] | None = None) -> dict:
    """Prepare display facts once so the public templates stay presentation-only."""
    if allowed_durations is None:
        allowed_durations = _allowed_durations_for_tenant(item.tenant_id)
    plans = [plan for plan in item.plans if plan.active and (not allowed_durations or plan.months in allowed_durations)]
    calculations = []
    for plan in plans:
        result = InstallmentCalculationService.calculate(item.cash_price, plan)
        calculations.append({"plan": plan, "calculation": result})
    best = min(calculations, key=lambda row: row["calculation"].monthly_payment) if calculations else None
    main_media = next((media for media in item.media if media.is_main and media.media_type == "image"), None)
    if not main_media:
        main_media = next((media for media in item.media if media.media_type == "image"), None)
    return {
        "item": item,
        "plans": plans,
        "best": best,
        "max_months": max((plan.months for plan in plans), default=0),
        "main_media": main_media,
    }


@installments_admin_bp.before_request
def _admin_guard():
    if "user_id" not in session:
        return redirect("/pos/login")
    slug = str(session.get("tenant_slug") or "").strip()
    if not slug:
        abort(403)
    g.tenant = slug
    rejected = _csrf_guard()
    if rejected:
        return rejected
    ensure_installment_schema()
    denied = _guard_installment("view_installments", "installments.view", json_response=request.path.startswith("/installments/api/"))
    if denied:
        return denied


@installments_store_bp.before_request
def _public_tenant():
    slug = str((request.view_args or {}).get("tenant_slug") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", slug):
        abort(404)
    g.tenant = slug
    rejected = _csrf_guard()
    if rejected:
        return rejected
    ensure_installment_schema()
    settings = InstallmentSettings.query.first()
    if not settings or not settings.enabled:
        abort(404)
    g.installment_tenant_id = int(settings.tenant_id)


@installments_short_bp.before_request
def _short_public_tenant():
    g.tenant = "super"
    rejected = _csrf_guard()
    if rejected:
        return rejected
    ensure_installment_schema()
    settings = InstallmentSettings.query.first()
    if not settings or not settings.enabled:
        abort(404)
    g.installment_tenant_id = int(settings.tenant_id)


def _public_product_url(tenant_slug: str, product_slug: str) -> str:
    if tenant_slug == "super":
        return url_for("installments_short.supermax_product", slug=product_slug)
    return url_for("installments_store.store_product", tenant_slug=tenant_slug, slug=product_slug)


@installments_store_bp.context_processor
@installments_short_bp.context_processor
def _store_customer_context():
    account = _current_store_account()
    slug = str(getattr(g, "tenant", "") or "")
    favorite_ids = _favorite_ids(slug) if slug else []
    return {
        "store_customer_account": account,
        "store_customer": account.customer if account else None,
        "favorite_ids": favorite_ids,
        "favorite_count": len(favorite_ids),
        "store_product_url": _public_product_url,
    }


@installments_admin_bp.get("/")
def dashboard():
    tenant_id = _tenant_id()
    today = date.today()
    month_start = today.replace(day=1)
    stats = {
        "products": _scoped(InstallmentProduct, tenant_id).count(),
        "new_applications": _scoped(InstallmentApplication, tenant_id).filter(InstallmentApplication.status.in_(["new", "under_review"])).count(),
        "active_contracts": _scoped(InstallmentContract, tenant_id).filter_by(status="active").count(),
        "overdue_amount": db.session.query(db.func.coalesce(db.func.sum(InstallmentSchedule.amount - InstallmentSchedule.paid_amount), 0)).filter(InstallmentSchedule.tenant_id == tenant_id, InstallmentSchedule.due_date < today, InstallmentSchedule.status.in_(["pending", "partial", "overdue"])).scalar(),
        "collected": db.session.query(db.func.coalesce(db.func.sum(InstallmentPayment.amount), 0)).filter(InstallmentPayment.tenant_id == tenant_id, InstallmentPayment.status == "posted").scalar(),
        "collected_month": db.session.query(db.func.coalesce(db.func.sum(InstallmentPayment.amount), 0)).filter(InstallmentPayment.tenant_id == tenant_id, InstallmentPayment.status == "posted", db.func.date(InstallmentPayment.received_at) >= month_start).scalar(),
        "due_today": db.session.query(db.func.coalesce(db.func.sum(InstallmentSchedule.amount - InstallmentSchedule.paid_amount), 0)).filter(InstallmentSchedule.tenant_id == tenant_id, InstallmentSchedule.due_date == today, InstallmentSchedule.status != "paid").scalar(),
        "outstanding": db.session.query(db.func.coalesce(db.func.sum(InstallmentContract.remaining_amount), 0)).filter(InstallmentContract.tenant_id == tenant_id, InstallmentContract.status == "active").scalar(),
    }
    recent = _scoped(InstallmentApplication, tenant_id).order_by(InstallmentApplication.created_at.desc()).limit(10).all()
    return render_template("installments/admin/dashboard.html", stats=stats, recent=recent)


@installments_admin_bp.get("/products")
def products():
    tenant_id = _tenant_id()
    ensure_product_schema()
    query = _scoped(InstallmentProduct, tenant_id)
    q = str(request.args.get("q") or "").strip()
    if q:
        query = query.filter(db.or_(InstallmentProduct.title.ilike(f"%{q}%"), InstallmentProduct.slug.ilike(f"%{q}%")))
    rows = query.order_by(InstallmentProduct.sort_order, InstallmentProduct.updated_at.desc()).limit(250).all()
    source_scope = db.or_(Product.tenant_id == tenant_id, Product.tenant_id.is_(None))
    source_query = Product.query.filter(source_scope, Product.active.is_(True))
    inventory_product_count = source_query.count()
    linked_product_ids = {
        product_id for (product_id,) in db.session.query(InstallmentProduct.product_id).filter_by(tenant_id=tenant_id).all()
    }
    if linked_product_ids:
        source_query = source_query.filter(~Product.id.in_(linked_product_ids))
    source_products = source_query.order_by(Product.name).limit(1000).all()
    brand_options = set(IRAQ_MARKET_BRANDS)
    category_catalog = {key: list(values) for key, values in PRODUCT_CATEGORY_CATALOG.items()}
    for source_product in source_query.limit(2000).all():
        try:
            product_meta = json.loads(source_product.meta_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            product_meta = {}
        if isinstance(product_meta, dict):
            brand = str(product_meta.get("brand") or "").strip()
            category = str(product_meta.get("category") or "").strip()
            subcategory = str(product_meta.get("subcategory") or "").strip()
            if brand:
                brand_options.add(brand)
            if category:
                category_catalog.setdefault(category, [])
                if subcategory and subcategory not in category_catalog[category]:
                    category_catalog[category].append(subcategory)
    try:
        from models.branch import Branch

        ensure_branch_schema()
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.name).all()
    except Exception:
        db.session.rollback()
        branches = []
    return render_template(
        "installments/admin/products.html",
        products=rows,
        source_products=source_products,
        inventory_product_count=inventory_product_count,
        linked_product_count=len(linked_product_ids),
        allowed_durations=sorted(_allowed_durations_for_tenant(tenant_id)),
        brand_options=sorted(brand_options, key=str.casefold),
        category_catalog=category_catalog,
        branches=branches,
        q=q,
    )


@installments_admin_bp.get("/products/<int:product_id>")
def product_detail(product_id: int):
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    allowed_durations = sorted(_allowed_durations_for_tenant(item.tenant_id))
    return render_template("installments/admin/product_detail.html", item=item, allowed_durations=allowed_durations)


def _absolute_asset_url(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw
    if raw.startswith("/static/"):
        return f"{request.host_url.rstrip('/')}{raw}"
    if raw.startswith("static/"):
        raw = raw[7:]
    return url_for("static", filename=raw.lstrip("/"), _external=True)


def _connected_ad_destinations() -> dict[str, list[dict]]:
    """Return public account/page labels only; credentials always stay server-side."""
    result: dict[str, list[dict]] = {key: [] for key in PLATFORM_CONFIG}
    tenant_slug = str(getattr(g, "tenant", "") or "").strip()

    try:
        from modules.publisher.models.publisher_page import PublisherPage

        pages = PublisherPage.query.filter(
            db.or_(PublisherPage.tenant_slug == tenant_slug, PublisherPage.tenant_slug.is_(None))
        ).order_by(PublisherPage.page_name).all()
        for page in pages:
            result["facebook"].append({
                "id": f"publisher:{page.id}",
                "external_id": str(page.page_id or ""),
                "name": page.page_name or f"Facebook Page {page.page_id}",
                "connected": True,
                "can_publish": bool(page.page_token),
            })
    except Exception as exc:
        db.session.rollback()
        current_app.logger.info("Publisher pages unavailable for ad wizard: %s", exc)

    try:
        from modules.ai_sales.models import AISalesChannelAccount
        from modules.ai_sales.schema import ensure_ai_sales_schema

        ensure_ai_sales_schema()
        channels = AISalesChannelAccount.query.filter(
            AISalesChannelAccount.channel_type.in_(("messenger", "instagram")),
            AISalesChannelAccount.is_active.is_(True),
            AISalesChannelAccount.connection_status == "connected",
        ).order_by(AISalesChannelAccount.name).all()
        for channel in channels:
            platform = "instagram" if channel.channel_type == "instagram" else "facebook"
            result[platform].append({
                "id": f"ai-sales:{channel.id}",
                "external_id": str(channel.external_account_id or channel.page_id or ""),
                "name": channel.name or channel.platform_username or platform.title(),
                "connected": True,
                "can_publish": False,
            })
    except Exception as exc:
        db.session.rollback()
        current_app.logger.info("AI Sales social accounts unavailable for ad wizard: %s", exc)

    try:
        from models.social_account import SocialAccount

        accounts = SocialAccount.query.filter(
            db.or_(SocialAccount.tenant_slug == tenant_slug, SocialAccount.tenant_slug.is_(None))
        ).order_by(SocialAccount.username).all()
        platform_aliases = {
            "facebook": "facebook", "instagram": "instagram", "tiktok": "tiktok",
            "google": "google", "google_ads": "google", "googleads": "google",
        }
        for account in accounts:
            platform = platform_aliases.get(str(account.platform or "").strip().lower())
            if not platform:
                continue
            result[platform].append({
                "id": f"social:{account.id}",
                "external_id": str(account.account_id or ""),
                "name": account.username or f"{PLATFORM_CONFIG[platform]['label']} {account.account_id}",
                "connected": True,
                "can_publish": False,
            })
    except Exception as exc:
        db.session.rollback()
        current_app.logger.info("Social accounts unavailable for ad wizard: %s", exc)

    for platform, rows in result.items():
        unique: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (str(row.get("external_id") or ""), str(row.get("name") or "").casefold())
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        result[platform] = unique
    return result


def _product_ad_payload(item: InstallmentProduct) -> dict:
    try:
        source_meta = json.loads(item.product.meta_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        source_meta = {}
    if not isinstance(source_meta, dict):
        source_meta = {}

    active_plans = [plan for plan in item.plans if plan.active]
    calculations = []
    for plan in active_plans:
        try:
            calculations.append(InstallmentCalculationService.calculate(item.cash_price, plan))
        except InstallmentError:
            continue
    store_path = _public_product_url(str(getattr(g, "tenant", "") or ""), item.slug)
    store_url = f"{request.host_url.rstrip('/')}{store_path}"
    media = [{
        "id": str(row.id),
        "type": row.media_type,
        "url": url_for("static", filename=row.file_path, v=row.size_bytes, _external=True),
        "name": row.original_name,
        "is_main": bool(row.is_main),
    } for row in sorted(item.media, key=lambda row: (not row.is_main, row.sort_order, row.id))]
    source_image = _absolute_asset_url(item.product.image_url)
    if source_image and not media:
        media.append({"id": "source", "type": "image", "url": source_image, "name": "صورة المنتج", "is_main": True})

    return {
        "id": item.id,
        "title": item.title,
        "sku": item.product.sku or "",
        "brand": str(source_meta.get("brand") or ""),
        "category": item.category or str(source_meta.get("category") or ""),
        "short_description": item.short_description or "",
        "full_description": item.full_description or item.product.description or "",
        "cash_price": int(item.cash_price or 0),
        "currency": "د.ع",
        "stock": int(item.product.quantity or 0),
        "max_months": max((plan.months for plan in active_plans), default=0),
        "minimum_monthly": min((int(row.monthly_payment) for row in calculations), default=0),
        "warranty": item.warranty_information or "",
        "delivery": item.delivery_information or "",
        "store_url": store_url,
        "media": media,
    }


@installments_admin_bp.get("/api/products/<int:product_id>/ad-kit")
def product_ad_kit(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = (
        _scoped(InstallmentProduct)
        .options(selectinload(InstallmentProduct.product), selectinload(InstallmentProduct.media), selectinload(InstallmentProduct.plans))
        .filter_by(id=product_id)
        .first_or_404()
    )
    try:
        from modules.ai_sales.openai_service import get_openai_api_key
        ai_configured = bool(get_openai_api_key())
    except Exception:
        ai_configured = False
    platforms = {
        key: {"key": key, **value}
        for key, value in PLATFORM_CONFIG.items()
    }
    return jsonify({
        "success": True,
        "product": _product_ad_payload(item),
        "platforms": platforms,
        "destinations": _connected_ad_destinations(),
        "ai_configured": ai_configured,
        "facebook_pages_url": "/publisher/settings",
        "facebook_pages_refresh_url": "/publisher/api/settings/connect-pages",
    })


@installments_admin_bp.post("/api/products/<int:product_id>/ad-copy")
def product_ad_copy(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = (
        _scoped(InstallmentProduct)
        .options(selectinload(InstallmentProduct.product), selectinload(InstallmentProduct.media), selectinload(InstallmentProduct.plans))
        .filter_by(id=product_id)
        .first_or_404()
    )
    data = request.get_json(silent=True) or {}
    platform = str(data.get("platform") or "").strip().lower()
    if platform not in PLATFORM_CONFIG:
        return _json_error("اختر منصة إعلان صحيحة")
    objective = str(data.get("objective") or "sales").strip().lower()
    if objective not in {"sales", "messages", "traffic", "awareness"}:
        objective = "sales"
    tone = str(data.get("tone") or "iraqi").strip().lower()
    if tone not in {"iraqi", "professional", "short"}:
        tone = "iraqi"
    product = _product_ad_payload(item)
    selected_ids = {str(value) for value in (data.get("media_ids") or [])}
    selected_media = [
        {"id": row["id"], "type": row["type"], "name": row["name"], "is_main": row["is_main"]}
        for row in product["media"] if not selected_ids or row["id"] in selected_ids
    ]
    creative = generate_ad_creative(
        {key: value for key, value in product.items() if key != "media"},
        platform=platform,
        objective=objective,
        tone=tone,
        media_summary=selected_media,
    )
    return jsonify({"success": True, "creative": creative, "launch_url": PLATFORM_CONFIG[platform]["launch_url"]})


@installments_admin_bp.post("/api/products/<int:product_id>/publish-facebook")
def publish_product_to_facebook(product_id: int):
    """Publish the reviewed product creative directly to a connected Facebook Page."""
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = (
        _scoped(InstallmentProduct)
        .options(selectinload(InstallmentProduct.product), selectinload(InstallmentProduct.media))
        .filter_by(id=product_id)
        .first_or_404()
    )
    data = request.get_json(silent=True) or {}
    destination_id = str(data.get("destination_id") or "").strip()
    if not destination_id.startswith("publisher:"):
        return _json_error("هذه الصفحة غير مربوطة للنشر المباشر. اربطها من إعدادات الناشر أولاً.")
    try:
        page_record_id = int(destination_id.split(":", 1)[1])
    except (TypeError, ValueError):
        return _json_error("اختيار صفحة فيسبوك غير صحيح")

    message = str(data.get("message") or "").strip()
    if not message:
        return _json_error("اكتب الكليشة أو ولّدها قبل النشر")
    if len(message) > 50_000:
        return _json_error("نص المنشور طويل جداً")

    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.facebook_service import (
        publish_multi_photo_post,
        publish_text_post,
        publish_video_post,
    )
    from modules.publisher.services.token_utils import decrypt_token

    tenant_slug = str(getattr(g, "tenant", "") or "").strip()
    page = PublisherPage.query.filter(
        PublisherPage.id == page_record_id,
        db.or_(PublisherPage.tenant_slug == tenant_slug, PublisherPage.tenant_slug.is_(None)),
    ).first()
    if page is None:
        return _json_error("صفحة فيسبوك المختارة غير موجودة أو لا تخص هذا المتجر", 404)
    page_token = decrypt_token(page.page_token or "")
    if not page_token:
        return _json_error("رمز الصفحة مفقود. أعد ربط صفحة فيسبوك من إعدادات الناشر.")

    selected_ids: set[int] = set()
    for value in data.get("media_ids") or []:
        try:
            selected_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    selected_media = [
        row for row in sorted(item.media, key=lambda row: (not row.is_main, row.sort_order, row.id))
        if row.id in selected_ids
    ]
    static_root = Path(current_app.static_folder).resolve()
    valid_media: list[tuple[InstallmentProductMedia, str]] = []
    for media in selected_media:
        candidate = (static_root / str(media.file_path or "").lstrip("/\\")).resolve()
        try:
            candidate.relative_to(static_root)
        except ValueError:
            continue
        if candidate.is_file():
            valid_media.append((media, str(candidate)))

    images = [path for media, path in valid_media if media.media_type == "image"][:10]
    videos = [path for media, path in valid_media if media.media_type == "video"]
    if images:
        publish_result = publish_multi_photo_post(str(page.page_id), page_token, message, images)
        published_kind = "صور"
        published_count = len(images)
    elif videos:
        publish_result = publish_video_post(str(page.page_id), page_token, message, videos[0])
        published_kind = "فيديو"
        published_count = 1
    else:
        publish_result = publish_text_post(str(page.page_id), page_token, message)
        published_kind = "نص"
        published_count = 0

    if not publish_result.get("success"):
        current_app.logger.warning(
            "Direct Facebook product publish failed: product=%s page=%s code=%s message=%s",
            item.id,
            page.page_id,
            publish_result.get("error_code"),
            publish_result.get("message"),
        )
        return _json_error(
            f"رفض فيسبوك النشر: {publish_result.get('message') or 'تحقق من صلاحية الصفحة والرمز'}",
            502,
            "facebook_publish_failed",
        )

    response_data = publish_result.get("data") or {}
    post_id = str(response_data.get("post_id") or response_data.get("id") or "")
    try:
        log_activity(
            "publish",
            "installments",
            "نشر منتج الأقساط على صفحة فيسبوك",
            entity_type="installment_product",
            entity_id=item.id,
            payload={"page_id": page.page_id, "post_id": post_id, "media_count": published_count},
        )
    except Exception as exc:
        current_app.logger.info("Unable to record Facebook publish activity: %s", exc)
    return jsonify({
        "success": True,
        "message": f"تم نشر المنتج الآن على صفحة {page.page_name or page.page_id}",
        "page_name": page.page_name or str(page.page_id),
        "post_id": post_id,
        "published_kind": published_kind,
        "media_count": published_count,
    })


def _parse_plan(data: dict, tenant_id: int, product_id: int) -> InstallmentPlan:
    months = int(data.get("months") or 0)
    _validate_plan_duration(tenant_id, months)
    plan = InstallmentPlan(
        tenant_id=tenant_id,
        installment_product_id=product_id,
        months=months,
        pricing_mode=str(data.get("pricing_mode") or ""),
        markup_percentage=data.get("markup_percentage") or None,
        fixed_total_price=int(data.get("fixed_total_price") or 0) or None,
        fixed_monthly_amount=int(data.get("fixed_monthly_amount") or 0) or None,
        down_payment_type=str(data.get("down_payment_type") or "none"),
        down_payment_value=data.get("down_payment_value") or 0,
        processing_fee=int(data.get("processing_fee") or 0),
        active=bool(data.get("active", True)),
        sort_order=int(data.get("sort_order") or 0),
    )
    InstallmentCalculationService.calculate(data.get("cash_price") or 0, plan)
    return plan


@installments_admin_bp.post("/api/products")
def create_product():
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        tenant_id = _tenant_id()
        source = Product.query.filter(
            Product.id == int(data.get("product_id") or 0),
            db.or_(Product.tenant_id == tenant_id, Product.tenant_id.is_(None)),
        ).first()
        if not source:
            raise InstallmentError("المنتج الأساسي غير موجود")
        if not source.active:
            raise InstallmentError("المنتج الأساسي معطّل في المخزون")
        slug = re.sub(r"[^a-z0-9-]+", "-", str(data.get("slug") or "").strip().lower()).strip("-")
        if len(slug) < 2:
            raise InstallmentError("الرابط المختصر غير صالح")
        if _scoped(InstallmentProduct, tenant_id).filter(db.or_(InstallmentProduct.slug == slug, InstallmentProduct.product_id == source.id)).first():
            raise InstallmentError("المنتج مضاف مسبقًا إلى الأقساط")
        cash_price = int(data.get("cash_price") or source.sale_price or 0)
        # The installment and cash shops intentionally share one inventory
        # product and one cash price. Publishing here must make it immediately
        # purchasable from the regular cash storefront too.
        source.sale_price = cash_price
        source.store_visible = True
        item = InstallmentProduct(tenant_id=tenant_id, product_id=source.id, title=str(data.get("title") or source.name).strip()[:180], slug=slug, short_description=str(data.get("short_description") or "").strip()[:500] or None, full_description=str(data.get("full_description") or source.description or "").strip() or None, cash_price=cash_price, category=str(data.get("category") or source.catalog_category or "").strip()[:120] or None, warranty_information=str(data.get("warranty_information") or "").strip() or None, delivery_information=str(data.get("delivery_information") or "").strip() or None, status=str(data.get("status") or "draft"), featured=bool(data.get("featured", False)), show_cash_price=bool(data.get("show_cash_price", True)), show_stock=bool(data.get("show_stock", True)))
        if item.status not in {"draft", "published", "disabled"}:
            raise InstallmentError("حالة النشر غير صالحة")
        db.session.add(item)
        db.session.flush()
        plans_data = data.get("plans") or []
        if isinstance(plans_data, str):
            plans_data = json.loads(plans_data)
        for raw in plans_data:
            raw["cash_price"] = cash_price
            db.session.add(_parse_plan(raw, tenant_id, item.id))
        db.session.flush()
        generated_plans, _ = synchronize_allowed_duration_plans(
            tenant_id,
            _allowed_durations_for_tenant(tenant_id),
            item.id,
        )
        db.session.commit()
        log_activity("create", "installments", "إنشاء منتج أقساط", entity_type="installment_product", entity_id=item.id, payload={"product_id": source.id, "generated_plans": generated_plans})
        return jsonify({"success": True, "id": item.id, "generated_plans": generated_plans})
    except (InstallmentError, ValueError, TypeError, json.JSONDecodeError, IntegrityError) as exc:
        db.session.rollback()
        return _json_error(str(exc))


@installments_admin_bp.post("/api/products/quick-create")
def quick_create_product():
    """Create inventory + branch stock + installment storefront record atomically."""
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        ensure_product_schema()
        tenant_id = _tenant_id()
        name = str(data.get("name") or "").strip()
        if len(name) < 2:
            raise InstallmentError("اكتب اسم المنتج أولاً")

        usd_iqd_rate = 1350
        buy_price_usd = float(data.get("buy_price_usd") or 0)
        buy_price = int(round(buy_price_usd * usd_iqd_rate)) if buy_price_usd > 0 else int(data.get("buy_price") or 0)
        opening_stock = int(data.get("opening_stock") or 0)
        if buy_price_usd < 0:
            raise InstallmentError("سعر الشراء بالدولار لا يمكن أن يكون سالباً")
        if buy_price < 0:
            raise InstallmentError("سعر الشراء لا يمكن أن يكون سالباً")
        if opening_stock < 0:
            raise InstallmentError("الكمية لا يمكن أن تكون سالبة")
        raw_profit_percentage = data.get("profit_percentage")
        profit_percentage = float(25 if raw_profit_percentage in (None, "") else raw_profit_percentage)
        if profit_percentage < 0 or profit_percentage > 1000:
            raise InstallmentError("نسبة الربح يجب أن تكون بين 0 و1000%")
        raw_sale_price = data.get("sale_price")
        sale_price = int(raw_sale_price or round(buy_price * (1 + profit_percentage / 100)))
        if sale_price <= 0:
            raise InstallmentError("أدخل سعر بيع أكبر من صفر")
        if sale_price < buy_price:
            raise InstallmentError("سعر البيع لا يمكن أن يكون أقل من سعر الشراء")
        profit_percentage = ((sale_price - buy_price) / buy_price * 100) if buy_price else 0
        if profit_percentage > 1000:
            raise InstallmentError("نسبة الربح الناتجة أكبر من الحد المسموح 1000%")

        inferred_category, inferred_subcategory = _infer_product_category(name)
        category = str(data.get("category") or inferred_category).strip()[:120]
        subcategory = str(data.get("subcategory") or inferred_subcategory).strip()[:120]
        brand = str(data.get("brand") or "").strip()[:120]
        sku = _generated_sku(tenant_id, data.get("sku"))
        barcode = _generated_barcode(tenant_id, data.get("barcode"))

        branch = None
        branch_id = int(data.get("branch_id") or 0)
        if branch_id:
            from models.branch import Branch

            ensure_branch_schema()
            branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
            if not branch:
                raise InstallmentError("الفرع المختار غير موجود أو غير فعال")

        meta = {
            "barcode_type": "EAN13",
            "unit": "piece",
            "category": category,
            "subcategory": subcategory,
            "profit_percentage": round(profit_percentage, 2),
        }
        if buy_price_usd > 0:
            meta.update({"buy_price_usd": round(buy_price_usd, 2), "usd_iqd_rate": usd_iqd_rate})
        if brand:
            meta["brand"] = brand
        if branch:
            meta.update({"branch_id": branch.id, "branch_name": branch.name, "branch_note": branch.name})

        source = Product(
            tenant_id=tenant_id,
            name=name[:150],
            sku=sku,
            barcode=barcode,
            buy_price=buy_price,
            sale_price=sale_price,
            shipping_cost=0,
            marketing_cost=0,
            opening_stock=opening_stock,
            quantity=opening_stock,
            active=True,
            store_visible=True,
            low_stock_threshold=max(0, int(data.get("low_stock_threshold") or 5)),
            description=str(data.get("description") or "").strip() or None,
            meta_json=json.dumps(meta, ensure_ascii=False),
        )
        db.session.add(source)
        db.session.flush()
        if branch:
            from utils.branch_stock_service import set_opening_branch_stock

            set_opening_branch_stock(branch.id, source.id, opening_stock)

        slug_base = re.sub(r"[^a-z0-9-]+", "-", sku.lower()).strip("-") or f"product-{source.id}"
        slug = slug_base
        suffix = 2
        while _scoped(InstallmentProduct, tenant_id).filter_by(slug=slug).first():
            slug = f"{slug_base}-{suffix}"
            suffix += 1

        publish_value = data.get("publish_to_store", True)
        publish_to_store = publish_value not in (False, 0, "0", "false", "False", "off")
        store_summary = str(data.get("short_description") or "").strip()[:500]
        if not store_summary:
            store_summary = " • ".join(value for value in (brand, subcategory) if value)[:500]
        item = InstallmentProduct(
            tenant_id=tenant_id,
            product_id=source.id,
            title=name[:180],
            slug=slug,
            short_description=store_summary or None,
            full_description=source.description,
            cash_price=sale_price,
            category=category,
            status="published" if publish_to_store else "draft",
            show_cash_price=True,
            show_stock=True,
        )
        db.session.add(item)
        db.session.flush()

        allowed_durations = sorted(_allowed_durations_for_tenant(tenant_id))
        default_months = allowed_durations[-1] if allowed_durations else 12
        plan_data = {
            "months": int(data.get("months") or default_months),
            "pricing_mode": "percentage",
            "markup_percentage": float(25 if data.get("installment_markup") in (None, "") else data.get("installment_markup")),
            "down_payment_type": "percentage" if float(data.get("down_payment") or 0) > 0 else "none",
            "down_payment_value": float(data.get("down_payment") or 0),
            "processing_fee": 0,
            "active": True,
            "cash_price": sale_price,
        }
        db.session.add(_parse_plan(plan_data, tenant_id, item.id))
        db.session.flush()
        generated_plans, _ = synchronize_allowed_duration_plans(
            tenant_id,
            _allowed_durations_for_tenant(tenant_id),
            item.id,
        )
        db.session.commit()
        log_activity(
            "create",
            "installments",
            f"إضافة وربط منتج: {source.name}",
            entity_type="installment_product",
            entity_id=item.id,
            payload={"product_id": source.id, "sku": sku, "barcode": barcode, "generated_plans": generated_plans},
        )
        return jsonify({
            "success": True,
            "id": item.id,
            "product_id": source.id,
            "sku": sku,
            "barcode": barcode,
            "category": category,
            "subcategory": subcategory,
            "sale_price": sale_price,
        })
    except (InstallmentError, ValueError, TypeError, IntegrityError) as exc:
        db.session.rollback()
        return _json_error(str(exc))


@installments_admin_bp.patch("/api/products/<int:product_id>")
def update_product(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        if "title" in data:
            title = str(data.get("title") or "").strip()
            if len(title) < 2:
                raise InstallmentError("العنوان غير صالح")
            item.title = title[:180]
        if "status" in data:
            status = str(data.get("status") or "")
            if status not in {"draft", "published", "disabled"}:
                raise InstallmentError("الحالة غير صالحة")
            allowed_durations = _allowed_durations_for_tenant(item.tenant_id)
            has_available_plan = any(
                plan.active and (not allowed_durations or plan.months in allowed_durations)
                for plan in item.plans
            )
            if status == "published" and not has_available_plan:
                raise InstallmentError("لا يمكن النشر دون خطة نشطة")
            item.status = status
            if status == "published" and item.product:
                item.product.store_visible = True
        for field, limit in (("short_description", 500), ("category", 120), ("warranty_information", 4000), ("delivery_information", 4000), ("seo_title", 180), ("seo_description", 500)):
            if field in data:
                setattr(item, field, str(data.get(field) or "").strip()[:limit] or None)
        if "featured" in data:
            item.featured = bool(data.get("featured"))
        if "cash_price" in data:
            cash_price = int(data.get("cash_price") or 0)
            if cash_price < 0:
                raise InstallmentError("السعر النقدي غير صالح")
            for plan in item.plans:
                InstallmentCalculationService.calculate(cash_price, plan)
            item.cash_price = cash_price
            if item.product:
                item.product.sale_price = cash_price
                item.product.store_visible = True
        if "full_description" in data:
            item.full_description = str(data.get("full_description") or "").strip()[:20000] or None
        for field in ("show_cash_price", "show_stock"):
            if field in data:
                setattr(item, field, bool(data.get(field)))
        db.session.commit()
        log_activity("update", "installments", "تحديث منتج أقساط", entity_type="installment_product", entity_id=item.id, payload={"fields": sorted(data.keys())})
        return jsonify({"success": True, "status": item.status})
    except InstallmentError as exc:
        db.session.rollback()
        return _json_error(str(exc), 409)


@installments_admin_bp.delete("/api/products/<int:product_id>")
def delete_product(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    if InstallmentApplicationItem.query.filter_by(tenant_id=item.tenant_id, installment_product_id=item.id).first():
        return _json_error("لا يمكن حذف منتج مرتبط بطلبات؛ يمكن تعطيله بدلًا من ذلك", 409)
    paths = [row.file_path for row in item.media]
    db.session.delete(item)
    db.session.commit()
    upload_root = (Path(current_app.static_folder) / "uploads" / "installments").resolve()
    for rel_path in paths:
        target = (Path(current_app.static_folder) / rel_path).resolve()
        try:
            target.relative_to(upload_root)
            if target.is_file():
                target.unlink()
            remove_storefront_enhancement_marker(target)
        except (ValueError, OSError):
            current_app.logger.warning("unable to remove installment media %s", rel_path)
    return jsonify({"success": True})


@installments_admin_bp.post("/api/plans/calculate")
def calculate_plan_admin():
    data = request.get_json(silent=True) or {}
    try:
        result = InstallmentCalculationService.calculate(data.get("cash_price"), data, int(data.get("quantity") or 1))
        return jsonify({"success": True, "calculation": result.to_dict()})
    except InstallmentError as exc:
        return _json_error(str(exc))


@installments_admin_bp.post("/api/products/<int:product_id>/plans")
def create_plan(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        data["cash_price"] = item.cash_price
        plan = _parse_plan(data, item.tenant_id, item.id)
        db.session.add(plan)
        db.session.flush()
        generated_plans, _ = synchronize_allowed_duration_plans(
            item.tenant_id,
            _allowed_durations_for_tenant(item.tenant_id),
            item.id,
        )
        db.session.commit()
        return jsonify({"success": True, "plan_id": plan.id, "generated_plans": generated_plans})
    except (InstallmentError, ValueError, TypeError, IntegrityError) as exc:
        db.session.rollback()
        return _json_error(str(exc), 409)


@installments_admin_bp.patch("/api/plans/<int:plan_id>")
def update_plan(plan_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    plan = _scoped(InstallmentPlan).filter_by(id=plan_id).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        raw = {
            "months": int(data.get("months", plan.months)),
            "pricing_mode": str(data.get("pricing_mode", plan.pricing_mode)),
            "markup_percentage": data.get("markup_percentage", plan.markup_percentage),
            "fixed_total_price": data.get("fixed_total_price", plan.fixed_total_price),
            "fixed_monthly_amount": data.get("fixed_monthly_amount", plan.fixed_monthly_amount),
            "down_payment_type": str(data.get("down_payment_type", plan.down_payment_type)),
            "down_payment_value": data.get("down_payment_value", plan.down_payment_value),
            "processing_fee": int(data.get("processing_fee", plan.processing_fee) or 0),
        }
        _validate_plan_duration(plan.tenant_id, raw["months"])
        InstallmentCalculationService.calculate(plan.installment_product.cash_price, raw)
        for field, value in raw.items():
            setattr(plan, field, value)
        if "active" in data:
            plan.active = bool(data.get("active"))
        db.session.commit()
        return jsonify({"success": True})
    except (InstallmentError, ValueError, TypeError, IntegrityError) as exc:
        db.session.rollback()
        return _json_error(str(exc), 409)


@installments_admin_bp.delete("/api/plans/<int:plan_id>")
def delete_plan(plan_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    plan = _scoped(InstallmentPlan).filter_by(id=plan_id).first_or_404()
    if InstallmentApplicationItem.query.filter_by(tenant_id=plan.tenant_id, plan_id=plan.id).first():
        plan.active = False
        db.session.commit()
        return jsonify({"success": True, "deactivated": True})
    db.session.delete(plan)
    db.session.commit()
    return jsonify({"success": True, "deleted": True})


@installments_admin_bp.post("/api/plans/<int:plan_id>/duplicate")
def duplicate_plan(plan_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    source = _scoped(InstallmentPlan).filter_by(id=plan_id).first_or_404()
    data = request.get_json(silent=True) or {}
    try:
        months = int(data.get("months") or 0)
        raw = {
            "months": months,
            "pricing_mode": source.pricing_mode,
            "markup_percentage": source.markup_percentage,
            "fixed_total_price": source.fixed_total_price,
            "fixed_monthly_amount": source.fixed_monthly_amount,
            "down_payment_type": source.down_payment_type,
            "down_payment_value": source.down_payment_value,
            "processing_fee": source.processing_fee,
            "active": True,
            "sort_order": source.sort_order + 1,
            "cash_price": source.installment_product.cash_price,
        }
        duplicate = _parse_plan(raw, source.tenant_id, source.installment_product_id)
        db.session.add(duplicate)
        db.session.commit()
        return jsonify({"success": True, "plan_id": duplicate.id})
    except (InstallmentError, ValueError, IntegrityError) as exc:
        db.session.rollback()
        return _json_error(str(exc), 409)


@installments_admin_bp.post("/api/products/<int:product_id>/media")
def upload_product_media(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    file = request.files.get("file")
    if not file or not file.filename:
        return _json_error("لم يتم اختيار ملف")
    mime = str(file.mimetype or "").lower()
    allowed_images = {"image/jpeg", "image/png", "image/webp"}
    allowed_videos = {"video/mp4", "video/webm"}
    if mime not in allowed_images | allowed_videos:
        return _json_error("نوع الملف غير مدعوم")
    media_type = "image" if mime in allowed_images else "video"
    limit = 8 * 1024 * 1024 if media_type == "image" else 100 * 1024 * 1024
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size <= 0 or size > limit:
        return _json_error("حجم الملف غير صالح أو يتجاوز الحد المسموح")
    header = file.stream.read(16)
    file.stream.seek(0)
    if not _valid_magic(mime, header):
        return _json_error("محتوى الملف لا يطابق نوعه")
    extension = ".png" if media_type == "image" else {"video/mp4": ".mp4", "video/webm": ".webm"}[mime]
    rel_dir = Path("uploads") / "installments" / str(item.tenant_id) / str(item.id)
    target_dir = Path(current_app.static_folder) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    target = target_dir / filename
    file.save(target)
    enhancement = {"enhanced": False, "skipped": media_type != "image"}
    if media_type == "image":
        try:
            enhancement = enhance_storefront_image(
                target,
                mime,
                force=True,
                output_path=target,
                output_mime_type="image/png",
            )
            mime = "image/png"
            size = target.stat().st_size
        except StorefrontImageError as exc:
            target.unlink(missing_ok=True)
            remove_storefront_enhancement_marker(target)
            return _json_error(str(exc), 400, "invalid_image")
    media = InstallmentProductMedia(tenant_id=item.tenant_id, installment_product_id=item.id, media_type=media_type, file_path=(rel_dir / filename).as_posix(), original_name=secure_filename(file.filename)[:255] or filename, mime_type=mime, size_bytes=size, is_main=not any(row.is_main for row in item.media), sort_order=len(item.media))
    db.session.add(media)
    db.session.commit()
    return jsonify({"success": True, "enhancement": enhancement, "media": {"id": media.id, "url": url_for("static", filename=media.file_path, v=media.size_bytes), "type": media.media_type}})


@installments_admin_bp.post("/api/products/<int:product_id>/media/auto-enhance")
def auto_enhance_product_media(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    updated = 0
    skipped = 0
    failed = 0
    for media in sorted(item.media, key=lambda row: row.sort_order)[:40]:
        if media.media_type != "image":
            continue
        try:
            if _enhance_media_record(media) == "updated":
                updated += 1
            else:
                skipped += 1
        except (ValueError, OSError, StorefrontImageError):
            failed += 1
            current_app.logger.warning("unable to auto-enhance installment media %s", media.file_path)
    if updated:
        db.session.commit()
    return jsonify({"success": True, "updated": updated, "skipped": skipped, "failed": failed})


@installments_admin_bp.post("/api/media/<int:media_id>/main")
def set_main_media(media_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    media = _scoped(InstallmentProductMedia).filter_by(id=media_id, media_type="image").first_or_404()
    InstallmentProductMedia.query.filter_by(tenant_id=media.tenant_id, installment_product_id=media.installment_product_id).update({"is_main": False})
    media.is_main = True
    db.session.commit()
    return jsonify({"success": True})


@installments_admin_bp.post("/api/products/<int:product_id>/media/reorder")
def reorder_media(product_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    item = _scoped(InstallmentProduct).filter_by(id=product_id).first_or_404()
    try:
        ids = [int(value) for value in ((request.get_json(silent=True) or {}).get("ids") or [])]
    except (TypeError, ValueError):
        return _json_error("ترتيب الوسائط غير صالح", 409)
    owned = {row.id: row for row in item.media}
    if set(ids) != set(owned):
        return _json_error("ترتيب الوسائط غير صالح", 409)
    for position, media_id in enumerate(ids):
        owned[int(media_id)].sort_order = position
    db.session.commit()
    return jsonify({"success": True})


@installments_admin_bp.delete("/api/media/<int:media_id>")
def delete_media(media_id: int):
    denied = _guard_installment("manage_installment_products", "installments.products.manage", json_response=True)
    if denied:
        return denied
    media = _scoped(InstallmentProductMedia).filter_by(id=media_id).first_or_404()
    target = (Path(current_app.static_folder) / media.file_path).resolve()
    upload_root = (Path(current_app.static_folder) / "uploads" / "installments").resolve()
    try:
        target.relative_to(upload_root)
    except ValueError:
        return _json_error("مسار الملف غير صالح", 409)
    was_main = media.is_main
    product_id = media.installment_product_id
    db.session.delete(media)
    db.session.flush()
    if was_main:
        replacement = InstallmentProductMedia.query.filter_by(tenant_id=media.tenant_id, installment_product_id=product_id, media_type="image").order_by(InstallmentProductMedia.sort_order).first()
        if replacement:
            replacement.is_main = True
    db.session.commit()
    try:
        if target.is_file():
            target.unlink()
        remove_storefront_enhancement_marker(target)
    except OSError:
        current_app.logger.warning("unable to remove installment media %s", media.file_path)
    return jsonify({"success": True})


@installments_admin_bp.get("/applications")
def applications():
    status = str(request.args.get("status") or "").strip()
    q = str(request.args.get("q") or "").strip()
    date_from = _date_arg("date_from")
    date_to = _date_arg("date_to")
    page = max(1, int(request.args.get("page") or 1))
    per_page = 30
    query = _scoped(InstallmentApplication)
    if status:
        query = query.filter_by(status=status)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            InstallmentApplication.application_number.ilike(like),
            InstallmentApplication.customer_name.ilike(like),
            InstallmentApplication.phone.ilike(like),
        ))
    if date_from:
        query = query.filter(db.func.date(InstallmentApplication.created_at) >= date_from)
    if date_to:
        query = query.filter(db.func.date(InstallmentApplication.created_at) <= date_to)
    total = query.count()
    rows = query.order_by(InstallmentApplication.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return render_template(
        "installments/admin/applications.html", applications=rows, active_status=status,
        q=q, date_from=date_from, date_to=date_to, page=page,
        pages=max(1, (total + per_page - 1) // per_page), total=total,
    )


@installments_admin_bp.get("/applications/<int:application_id>")
def application_detail(application_id: int):
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    return render_template(
        "installments/admin/application_detail.html",
        application=application,
        status_labels=STORE_APPLICATION_STATUS_LABELS,
    )


@installments_admin_bp.post("/api/applications/<int:application_id>/status")
def change_application_status(application_id: int):
    denied = _guard_installment("review_installment_applications", "installments.applications.review", json_response=True)
    if denied:
        return denied
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    target = str(data.get("status") or "").strip()
    note = str(data.get("note") or "").strip()[:2000]
    try:
        validate_application_transition(application.status, target)
        employee = get_current_employee()
        if target == "cancelled" and application.contract:
            from utils.order_lifecycle import OrderLifecycleError, process_order_cancel
            from utils.cash_calculations import _effective_paid_amount
            from modules.installments.services import append_installment_ledger_delta

            try:
                invoice = application.contract.invoice
                previous_paid = _effective_paid_amount(invoice)
                process_order_cancel(
                    invoice,
                    actor_id=getattr(employee, "id", None),
                    reason=note or "تم إلغاء طلب الأقساط من الإدارة",
                )
                append_installment_ledger_delta(
                    invoice,
                    _effective_paid_amount(invoice) - previous_paid,
                    note="إلغاء طلب أقساط",
                )
            except OrderLifecycleError as exc:
                raise InstallmentError(exc.message) from exc
            db.session.commit()
            return jsonify({"success": True, "status": application.status})

        old = application.status
        application.status = target
        db.session.add(InstallmentApplicationActivity(
            tenant_id=application.tenant_id, application_id=application.id,
            actor_id=getattr(employee, "id", None), action="status_changed",
            from_status=old, to_status=target, note=note or None,
        ))
        db.session.commit()
        return jsonify({"success": True, "status": target})
    except InstallmentError as exc:
        db.session.rollback()
        return _json_error(str(exc), 409, "invalid_status_transition")


@installments_admin_bp.post("/api/applications/<int:application_id>/notes")
def update_application_notes(application_id: int):
    denied = _guard_installment("review_installment_applications", "installments.applications.review", json_response=True)
    if denied:
        return denied
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    application.internal_notes = str(data.get("internal_notes") or "").strip()[:10000] or None
    employee = get_current_employee()
    db.session.add(InstallmentApplicationActivity(
        tenant_id=application.tenant_id, application_id=application.id,
        actor_id=getattr(employee, "id", None), action="internal_notes_updated",
    ))
    db.session.commit()
    return jsonify({"success": True})


@installments_admin_bp.post("/api/applications/<int:application_id>/documents")
def upload_application_document(application_id: int):
    denied = _guard_installment("review_installment_applications", "installments.applications.review", json_response=True)
    if denied:
        return denied
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    file = request.files.get("file")
    document_type = str(request.form.get("document_type") or "other").strip()[:50]
    if not file or not file.filename:
        return _json_error("لم يتم اختيار مستند")
    mime = str(file.mimetype or "").lower()
    extensions = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}
    if mime not in extensions:
        return _json_error("نوع المستند غير مدعوم")
    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    header = file.stream.read(16)
    file.stream.seek(0)
    if size <= 0 or size > 10 * 1024 * 1024 or not _valid_magic(mime, header):
        return _json_error("حجم المستند أو محتواه غير صالح")
    rel_dir = Path("uploads") / "installments" / "documents" / str(application.tenant_id) / str(application.id)
    target_dir = Path(current_app.static_folder) / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extensions[mime]}"
    file.save(target_dir / filename)
    document = InstallmentApplicationDocument(tenant_id=application.tenant_id, application_id=application.id, document_type=document_type, file_path=(rel_dir / filename).as_posix(), original_name=secure_filename(file.filename)[:255] or filename, mime_type=mime, size_bytes=size)
    db.session.add(document)
    db.session.add(InstallmentApplicationActivity(tenant_id=application.tenant_id, application_id=application.id, actor_id=getattr(get_current_employee(), "id", None), action="document_uploaded", note=document_type))
    db.session.commit()
    if not request.is_json and "application/json" not in (request.headers.get("Accept") or ""):
        return redirect(url_for("installments_admin.application_detail", application_id=application.id))
    return jsonify({"success": True, "document_id": document.id})


@installments_admin_bp.post("/api/applications/<int:application_id>/review")
def review_application(application_id: int):
    denied = _guard_installment("review_installment_applications", "installments.applications.review", json_response=True)
    if denied:
        return denied
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    if application.status != "new":
        return _json_error("لا يمكن نقل الطلب للمراجعة من حالته الحالية", 409)
    employee = get_current_employee()
    application.status = "under_review"
    application.assigned_employee_id = getattr(employee, "id", None)
    db.session.add(InstallmentApplicationActivity(tenant_id=application.tenant_id, application_id=application.id, actor_id=getattr(employee, "id", None), action="review_started", from_status="new", to_status="under_review"))
    db.session.commit()
    return jsonify({"success": True, "status": application.status})


@installments_admin_bp.post("/api/applications/<int:application_id>/approve")
def approve_application(application_id: int):
    denied = _guard_installment("approve_installment_applications", "installments.applications.approve", json_response=True)
    if denied:
        return denied
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    employee = get_current_employee()
    try:
        contract = ApprovalService.approve(application, getattr(employee, "id", None))
        log_activity("approve", "installments", "الموافقة على طلب أقساط", entity_type="installment_application", entity_id=application.id, payload={"contract_id": contract.id})
        return jsonify({"success": True, "contract_id": contract.id, "contract_number": contract.contract_number})
    except InstallmentError as exc:
        return _json_error(str(exc), 409)


@installments_admin_bp.post("/api/applications/<int:application_id>/reject")
def reject_application(application_id: int):
    denied = _guard_installment("approve_installment_applications", "installments.applications.approve", json_response=True)
    if denied:
        return denied
    application = _scoped(InstallmentApplication).filter_by(id=application_id).first_or_404()
    reason = str((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if application.status not in {"new", "under_review"} or len(reason) < 3:
        return _json_error("الحالة أو سبب الرفض غير صالح", 409)
    old = application.status
    application.status = "rejected"
    application.rejection_reason = reason[:2000]
    employee = get_current_employee()
    db.session.add(InstallmentApplicationActivity(tenant_id=application.tenant_id, application_id=application.id, actor_id=getattr(employee, "id", None), action="rejected", from_status=old, to_status="rejected", note=reason[:2000]))
    db.session.commit()
    return jsonify({"success": True, "status": application.status})


@installments_admin_bp.get("/contracts")
def contracts():
    query = _scoped(InstallmentContract)
    q = str(request.args.get("q") or "").strip()
    status = str(request.args.get("status") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.join(Customer, Customer.id == InstallmentContract.customer_id).filter(db.or_(
            InstallmentContract.contract_number.ilike(like),
            Customer.name.ilike(like), Customer.phone.ilike(like),
        ))
    if status:
        query = query.filter(InstallmentContract.status == status)
    rows = query.order_by(InstallmentContract.created_at.desc()).limit(250).all()
    return render_template("installments/admin/contracts.html", contracts=rows, q=q, active_status=status)


@installments_admin_bp.get("/contracts/<int:contract_id>")
def contract_detail(contract_id: int):
    contract = _scoped(InstallmentContract).filter_by(id=contract_id).first_or_404()
    return render_template("installments/admin/contract_detail.html", contract=contract, today=date.today())


@installments_admin_bp.get("/contracts/<int:contract_id>/print")
def contract_print(contract_id: int):
    contract = _scoped(InstallmentContract).filter_by(id=contract_id).first_or_404()
    settings = InstallmentSettings.query.filter_by(tenant_id=contract.tenant_id).first()
    cash_total = sum(int(item.cash_price or 0) for item in contract.items)
    financing_cost = max(int(contract.total_amount or 0) - cash_total, 0)
    contract_status_labels = {
        "draft": "مسودة",
        "active": "نافذ",
        "completed": "مكتمل السداد",
        "cancelled": "ملغى",
        "defaulted": "متعثر",
    }
    schedule_status_labels = {
        "pending": "غير مسدد",
        "partial": "مسدد جزئياً",
        "paid": "مسدد",
        "overdue": "متأخر",
        "cancelled": "ملغى",
    }
    return render_template(
        "installments/admin/contract_print.html",
        contract=contract,
        settings=settings,
        cash_total=cash_total,
        financing_cost=financing_cost,
        issued_at=datetime.now(),
        contract_status_label=contract_status_labels.get(contract.status, contract.status),
        schedule_status_labels=schedule_status_labels,
    )


@installments_admin_bp.get("/customers/<int:customer_id>/statement")
def customer_statement(customer_id: int):
    customer = Customer.query.filter_by(id=customer_id, tenant_id=_tenant_id()).first_or_404()
    contracts = _scoped(InstallmentContract).filter_by(customer_id=customer.id).order_by(InstallmentContract.created_at.desc()).limit(250).all()
    return render_template("installments/admin/customer_statement.html", customer=customer, contracts=contracts)


@installments_admin_bp.get("/overdue")
def overdue():
    tenant_id = _tenant_id()
    today = date.today()
    q = str(request.args.get("q") or "").strip()
    aging = str(request.args.get("aging") or "").strip()
    query = _scoped(InstallmentSchedule, tenant_id).join(InstallmentContract).join(Customer).filter(InstallmentSchedule.due_date < today, InstallmentSchedule.status.in_(["pending", "partial", "overdue"]))
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(InstallmentContract.contract_number.ilike(like), Customer.name.ilike(like), Customer.phone.ilike(like)))
    if aging == "1-30":
        query = query.filter(InstallmentSchedule.due_date >= date.fromordinal(today.toordinal() - 30))
    elif aging == "31-60":
        query = query.filter(InstallmentSchedule.due_date < date.fromordinal(today.toordinal() - 30), InstallmentSchedule.due_date >= date.fromordinal(today.toordinal() - 60))
    elif aging == "61+":
        query = query.filter(InstallmentSchedule.due_date < date.fromordinal(today.toordinal() - 60))
    rows = query.order_by(InstallmentSchedule.due_date).limit(500).all()
    for row in rows:
        if row.status == "pending":
            row.status = "overdue"
    if rows:
        db.session.commit()
    return render_template("installments/admin/overdue.html", schedules=rows, total=sum(row.amount - row.paid_amount for row in rows), today=today, q=q, aging=aging)


@installments_admin_bp.get("/reports")
def reports():
    tenant_id = _tenant_id()
    date_from = _date_arg("date_from")
    date_to = _date_arg("date_to")
    by_status = dict(db.session.query(InstallmentApplication.status, db.func.count(InstallmentApplication.id)).filter(InstallmentApplication.tenant_id == tenant_id).group_by(InstallmentApplication.status).all())
    contract_totals = db.session.query(db.func.coalesce(db.func.sum(InstallmentContract.total_amount), 0), db.func.coalesce(db.func.sum(InstallmentContract.paid_amount), 0), db.func.coalesce(db.func.sum(InstallmentContract.remaining_amount), 0)).filter(InstallmentContract.tenant_id == tenant_id).one()
    payments_query = _scoped(InstallmentPayment, tenant_id)
    if date_from:
        payments_query = payments_query.filter(db.func.date(InstallmentPayment.received_at) >= date_from)
    if date_to:
        payments_query = payments_query.filter(db.func.date(InstallmentPayment.received_at) <= date_to)
    payments = payments_query.order_by(InstallmentPayment.received_at.desc()).limit(500).all()
    return render_template("installments/admin/reports.html", by_status=by_status, contract_totals=contract_totals, payments=payments, date_from=date_from, date_to=date_to)


@installments_admin_bp.get("/reports/export/<report_type>.csv")
def export_report(report_type: str):
    tenant_id = _tenant_id()
    date_from = _date_arg("date_from")
    date_to = _date_arg("date_to")
    if report_type == "payments":
        query = _scoped(InstallmentPayment, tenant_id)
        if date_from:
            query = query.filter(db.func.date(InstallmentPayment.received_at) >= date_from)
        if date_to:
            query = query.filter(db.func.date(InstallmentPayment.received_at) <= date_to)
        rows = query.order_by(InstallmentPayment.received_at.desc()).all()
        return _csv_download("installment-payments.csv", ["رقم الدفعة", "العقد", "العميل", "المبلغ", "الطريقة", "الحالة", "التاريخ"], (
            [row.payment_number, row.contract.contract_number, row.contract.customer.name, row.amount, row.payment_method, row.status, row.received_at.isoformat(sep=" ")]
            for row in rows
        ))
    if report_type == "contracts":
        rows = _scoped(InstallmentContract, tenant_id).order_by(InstallmentContract.created_at.desc()).all()
        return _csv_download("installment-contracts.csv", ["العقد", "العميل", "الإجمالي", "المدفوع", "المتبقي", "الحالة", "التاريخ"], (
            [row.contract_number, row.customer.name, row.total_amount, row.paid_amount, row.remaining_amount, row.status, row.created_at.isoformat(sep=" ")]
            for row in rows
        ))
    if report_type == "overdue":
        rows = _scoped(InstallmentSchedule, tenant_id).filter(InstallmentSchedule.due_date < date.today(), InstallmentSchedule.status != "paid").order_by(InstallmentSchedule.due_date).all()
        return _csv_download("installment-overdue.csv", ["العقد", "العميل", "القسط", "الاستحقاق", "المبلغ", "المتبقي"], (
            [row.contract.contract_number, row.contract.customer.name, row.sequence, row.due_date.isoformat(), row.amount, row.amount - row.paid_amount]
            for row in rows
        ))
    abort(404)


@installments_admin_bp.post("/api/contracts/<int:contract_id>/payments")
def create_payment(contract_id: int):
    denied = _guard_installment("collect_installment_payments", "installments.payments.create", json_response=True)
    if denied:
        return denied
    contract = _scoped(InstallmentContract).filter_by(id=contract_id).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    employee = get_current_employee()
    try:
        payment = PaymentService.post(contract, data.get("amount"), data.get("payment_method") or "cash", getattr(employee, "id", None), data.get("reference") or "", data.get("notes") or "", data.get("paid_at"))
        log_activity("payment", "installments", "تحصيل دفعة أقساط", entity_type="installment_payment", entity_id=payment.id, payload={"contract_id": contract.id, "amount": payment.amount})
        return jsonify({"success": True, "payment_id": payment.id, "remaining_amount": contract.remaining_amount, "contract_status": contract.status})
    except InstallmentError as exc:
        return _json_error(str(exc), 409)


@installments_admin_bp.post("/api/contracts/<int:contract_id>/deliver")
def deliver_contract(contract_id: int):
    denied = _guard_installment("approve_installment_applications", "installments.contracts.manage", json_response=True)
    if denied:
        return denied
    contract = _scoped(InstallmentContract).filter_by(id=contract_id).first_or_404()
    employee = get_current_employee()
    try:
        invoice = ApprovalService.fulfill(contract, getattr(employee, "id", None))
        log_activity("deliver", "installments", "تسليم عقد أقساط", entity_type="installment_contract", entity_id=contract.id, payload={"invoice_id": invoice.id})
        return jsonify({"success": True, "invoice_id": invoice.id})
    except InstallmentError as exc:
        return _json_error(str(exc), 409)


@installments_admin_bp.post("/api/payments/<int:payment_id>/reverse")
def reverse_payment(payment_id: int):
    denied = _guard_installment("collect_installment_payments", "installments.payments.reverse", json_response=True)
    if denied:
        return denied
    payment = _scoped(InstallmentPayment).filter_by(id=payment_id).first_or_404()
    data = request.get_json(silent=True) or request.form.to_dict()
    employee = get_current_employee()
    try:
        reversal = PaymentService.reverse(payment, getattr(employee, "id", None), data.get("reason"))
        log_activity("reverse", "installments", "عكس دفعة أقساط", entity_type="installment_payment", entity_id=payment.id, payload={"reversal_id": reversal.id, "reason": data.get("reason")})
        return jsonify({"success": True, "reversal_id": reversal.id, "remaining_amount": payment.contract.remaining_amount})
    except InstallmentError as exc:
        return _json_error(str(exc), 409)


@installments_admin_bp.route("/settings", methods=["GET", "POST"])
def settings_page():
    tenant_id = _tenant_id()
    settings = InstallmentSettings.query.filter_by(tenant_id=tenant_id).first()
    if not settings:
        from models.system_settings import SystemSettings
        company_settings = SystemSettings.get_settings()
        settings = InstallmentSettings(tenant_id=tenant_id, currency=(company_settings.default_currency if company_settings else "د.ع"))
        db.session.add(settings)
        db.session.commit()
    if request.method == "POST":
        denied = _guard_installment("manage_installment_settings", "installments.settings.manage")
        if denied:
            return denied
        settings.enabled = request.form.get("enabled") == "on"
        settings.store_name = str(request.form.get("store_name") or "Finora Installment Store")[:180]
        settings.contact_phone = str(request.form.get("contact_phone") or "").strip()[:30] or None
        settings.whatsapp = str(request.form.get("whatsapp") or "").strip()[:30] or None
        settings.address = str(request.form.get("address") or "").strip()[:300] or None
        settings.map_url = _sanitize_map_url(request.form.get("map_url"))
        settings.terms = str(request.form.get("terms") or "").strip()[:10000] or None
        settings.currency = str(request.form.get("currency") or "IQD").strip().upper()[:10]
        settings.second_phone_required = request.form.get("second_phone_required") == "on"
        settings.guarantor_required = request.form.get("guarantor_required") == "on"
        settings.employment_required = request.form.get("employment_required") == "on"
        settings.allow_advance_payment = request.form.get("allow_advance_payment") == "on"
        settings.reservation_policy = str(request.form.get("reservation_policy") or "on_approval")
        if settings.reservation_policy not in {"on_application", "on_approval", "on_delivery"}:
            settings.reservation_policy = "on_approval"
        settings.documents_config_json = json.dumps([value.strip() for value in request.form.getlist("documents") if value.strip()], ensure_ascii=False)
        durations = sorted({int(value) for value in re.findall(r"\d+", request.form.get("allowed_durations") or "") if 1 <= int(value) <= 120})
        settings.allowed_durations_json = json.dumps(durations)
        generated_plans, deactivated_plans = synchronize_allowed_duration_plans(tenant_id, durations)
        try:
            minimum_down = float(request.form.get("minimum_down_payment_percentage") or 0)
        except ValueError:
            minimum_down = 0
        settings.minimum_down_payment_percentage = max(0, min(minimum_down, 100))
        settings.payment_day = _bounded_int(request.form.get("payment_day"), 1, 28, 1)
        settings.grace_days = _bounded_int(request.form.get("grace_days"), 0, 90, 0)
        for field in ("receivable_account_id", "sales_account_id", "cash_account_id", "bank_account_id", "fee_account_id"):
            raw_id = str(request.form.get(field) or "")
            setattr(settings, field, int(raw_id) if raw_id.isdigit() and int(raw_id) > 0 else None)
        try:
            if request.files.get("logo") and request.files["logo"].filename:
                settings.logo_path = _save_settings_image(request.files["logo"], tenant_id, "logo")
            if request.files.get("banner") and request.files["banner"].filename:
                settings.banner_path = _save_settings_image(request.files["banner"], tenant_id, "banner")
        except InstallmentError as exc:
            db.session.rollback()
            return _json_error(str(exc))
        db.session.commit()
        return redirect(url_for("installments_admin.settings_page", saved=1, deactivated=deactivated_plans, generated=generated_plans))
    from models.account import Account
    try:
        selected_documents = json.loads(settings.documents_config_json or "[]")
        allowed_durations = ", ".join(str(value) for value in json.loads(settings.allowed_durations_json or "[]"))
    except (ValueError, TypeError):
        selected_documents, allowed_durations = [], ""
    return render_template("installments/admin/settings.html", settings=settings, accounts=Account.query.filter_by(is_active=True).order_by(Account.code).all(), selected_documents=selected_documents, allowed_durations=allowed_durations)


@installments_store_bp.get("/<tenant_slug>/account")
def account_page(tenant_slug: str):
    account = _current_store_account(tenant_slug)
    applications = []
    if account:
        applications = (
            _scoped(InstallmentApplication)
            .filter_by(customer_id=account.customer_id)
            .order_by(InstallmentApplication.created_at.desc())
            .limit(100)
              .all()
          )
    visible_contracts = [
        application.contract
        for application in applications
        if application.contract and application.contract.status != "cancelled"
    ]
    settings = InstallmentSettings.query.filter_by(tenant_id=_tenant_id()).first()
    return render_template(
        "installments/store/account.html",
        account=account,
          customer=account.customer if account else None,
          applications=applications,
          contract_count=len(visible_contracts),
          remaining_contract_balance=sum(max(0, int(contract.remaining_amount or 0)) for contract in visible_contracts),
          status_labels=STORE_APPLICATION_STATUS_LABELS,
        mode=str(request.args.get("mode") or "login"),
        error=str(request.args.get("error") or "").strip(),
        tenant_slug=tenant_slug,
        settings=settings,
        cart_count=_cart_count(tenant_slug),
        current_year=date.today().year,
    )


@installments_store_bp.post("/<tenant_slug>/account/register")
def account_register(tenant_slug: str):
    if not allow_request("installment_account_register", limit=5, window_seconds=60):
        message = "محاولات كثيرة، حاول بعد دقيقة"
        return _json_error(message, 429, "rate_limited") if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, mode="register", error=message))
    data = request.get_json(silent=True) or request.form.to_dict()
    name = " ".join(str(data.get("name") or "").split())
    password = str(data.get("password") or "")
    try:
        phone = normalize_phone(data.get("phone"))
    except InstallmentError as exc:
        if request.is_json:
            return _json_error(str(exc))
        return redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, mode="register", error=str(exc)))
    if len(name.split()) < 4 or len(name) > 150:
        message = "يرجى إدخال الاسم الرباعي كاملاً"
        return _json_error(message) if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, mode="register", error=message))
    if len(password) < 8 or len(password) > 128:
        message = "كلمة المرور يجب أن تكون بين 8 و128 حرفاً"
        return _json_error(message) if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, mode="register", error=message))
    tenant_id = _tenant_id()
    if InstallmentCustomerAccount.query.filter_by(tenant_id=tenant_id, phone=phone).first():
        message = "يوجد حساب بهذا الرقم؛ سجّل الدخول بدلاً من إنشاء حساب جديد"
        return _json_error(message, 409, "account_exists") if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, error=message))

    customer = find_customer_by_phone(tenant_id, phone)
    if not customer:
        customer = Customer(tenant_id=tenant_id, name=name, phone=phone)
        db.session.add(customer)
        db.session.flush()
    else:
        customer.name = name
        customer.phone = phone
    account = InstallmentCustomerAccount(
        tenant_id=tenant_id,
        customer_id=customer.id,
        phone=phone,
        password_hash=generate_password_hash(password),
        last_login_at=datetime.utcnow(),
    )
    db.session.add(account)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        message = "تعذر إنشاء الحساب؛ تحقق من الرقم وحاول مرة أخرى"
        return _json_error(message, 409, "account_conflict") if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, mode="register", error=message))
    session[_customer_account_key(tenant_slug)] = account.id
    session.modified = True
    if request.is_json:
        return jsonify({"success": True, "customer_id": customer.id}), 201
    return redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, welcome=1))


@installments_store_bp.post("/<tenant_slug>/account/login")
def account_login(tenant_slug: str):
    if not allow_request("installment_account_login", limit=10, window_seconds=60):
        message = "محاولات كثيرة، حاول بعد دقيقة"
        return _json_error(message, 429, "rate_limited") if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, error=message))
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        phone = normalize_phone(data.get("phone"))
    except InstallmentError:
        phone = ""
    account = InstallmentCustomerAccount.query.filter_by(tenant_id=_tenant_id(), phone=phone, is_active=True).first() if phone else None
    password = str(data.get("password") or "")
    valid = False
    if account:
        try:
            valid = check_password_hash(account.password_hash, password)
        except (TypeError, ValueError):
            valid = False
    if not valid:
        message = "رقم الهاتف أو كلمة المرور غير صحيحة"
        return _json_error(message, 401, "invalid_credentials") if request.is_json else redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug, error=message))
    account.last_login_at = datetime.utcnow()
    db.session.commit()
    session[_customer_account_key(tenant_slug)] = account.id
    session.modified = True
    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug))


@installments_store_bp.post("/<tenant_slug>/account/logout")
def account_logout(tenant_slug: str):
    session.pop(_customer_account_key(tenant_slug), None)
    session.modified = True
    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("installments_store.account_page", tenant_slug=tenant_slug))


@installments_store_bp.get("/<tenant_slug>/")
def store_index(tenant_slug: str):
    tenant_id = _tenant_id()
    _ensure_allowed_duration_plans(tenant_id)
    allowed_durations = _allowed_durations_for_tenant(tenant_id)
    q = str(request.args.get("q") or "").strip()
    category = str(request.args.get("category") or "").strip()
    query = _scoped(InstallmentProduct, tenant_id).options(
        selectinload(InstallmentProduct.product),
        selectinload(InstallmentProduct.media),
        selectinload(InstallmentProduct.plans),
    ).filter_by(status="published")
    if q:
        like = f"%{q}%"
        query = query.join(Product, Product.id == InstallmentProduct.product_id).filter(db.or_(InstallmentProduct.title.ilike(like), InstallmentProduct.category.ilike(like), Product.sku.ilike(like)))
    products = query.order_by(InstallmentProduct.featured.desc(), InstallmentProduct.sort_order, InstallmentProduct.created_at.desc()).all()
    if category:
        products = [item for item in products if _store_section_name(item) == category]
    products = products[:120]
    _auto_enhance_storefront_media(products, max_images=16, one_per_product=True)
    categories = _published_category_names(tenant_id)
    cards = [_store_card(item, allowed_durations) for item in products]
    featured_cards = [card for card in cards if card["item"].featured and card["plans"]] or [card for card in cards if card["plans"]]
    hero_cards = []
    hero_categories: set[str] = set()
    for card in featured_cards:
        category_key = str(card["item"].category or "").strip().lower()
        if category_key and category_key in hero_categories:
            continue
        hero_cards.append(card)
        if category_key:
            hero_categories.add(category_key)
        if len(hero_cards) >= 3:
            break
    for card in featured_cards:
        if len(hero_cards) >= 3:
            break
        if card not in hero_cards:
            hero_cards.append(card)
    category_cards = _published_category_cards(tenant_id)
    max_months = max((card["max_months"] for card in cards), default=0)
    return render_template(
        "installments/store/index.html",
        products=products,
        cards=cards,
        featured_cards=featured_cards[:10],
        hero_cards=hero_cards,
        tenant_slug=tenant_slug,
        settings=InstallmentSettings.query.filter_by(tenant_id=tenant_id).first(),
        q=q,
        category=category,
        categories=categories,
        category_cards=category_cards,
        max_months=max_months,
        cart_count=_cart_count(tenant_slug),
        current_year=date.today().year,
    )


@installments_store_bp.get("/<tenant_slug>/<slug>")
def store_product(tenant_slug: str, slug: str):
    if tenant_slug == "super" and request.endpoint == "installments_store.store_product":
        return redirect(url_for("installments_short.supermax_product", slug=slug), code=301)
    product = _scoped(InstallmentProduct).options(
        selectinload(InstallmentProduct.product),
        selectinload(InstallmentProduct.media),
        selectinload(InstallmentProduct.plans),
    ).filter_by(slug=slug, status="published").first_or_404()
    if _ensure_allowed_duration_plans(product.tenant_id, product.id):
        db.session.expire(product, ["plans"])
    _auto_enhance_storefront_media([product], max_images=40, one_per_product=False)
    allowed_durations = _allowed_durations_for_tenant(product.tenant_id)
    plans = sorted(
        [plan for plan in product.plans if plan.active and (not allowed_durations or plan.months in allowed_durations)],
        key=lambda plan: plan.months,
    )
    if not plans:
        abort(404)
    calculations = {plan.id: InstallmentCalculationService.calculate(product.cash_price, plan).to_dict() for plan in plans}
    categories = _published_category_names(product.tenant_id)
    description = product.full_description or product.short_description or (product.product.description if product.product else None)
    specs = _parse_product_specs(description)
    return render_template(
        "installments/store/product.html",
        item=product,
        plans=plans,
        calculations=calculations,
        tenant_slug=tenant_slug,
        settings=InstallmentSettings.query.filter_by(tenant_id=product.tenant_id).first(),
        categories=categories,
        specs=specs,
        cart_count=_cart_count(tenant_slug),
        current_year=date.today().year,
    )


@installments_short_bp.get("/supermax/<slug>")
def supermax_product(slug: str):
    return store_product("super", slug)


@installments_store_bp.get("/<tenant_slug>/product/<slug>")
def legacy_store_product(tenant_slug: str, slug: str):
    """Redirect previously shared links to the shorter canonical product URL."""
    product = _scoped(InstallmentProduct).filter_by(slug=slug, status="published").first_or_404()
    destination = (
        f"/supermax/{product.slug}"
        if tenant_slug == "super"
        else url_for("installments_store.store_product", tenant_slug=tenant_slug, slug=product.slug)
    )
    return redirect(
        destination,
        code=301,
    )


@installments_store_bp.get("/<tenant_slug>/favorites")
def favorites_page(tenant_slug: str):
    cards = _favorite_cards(tenant_slug)
    return render_template(
        "installments/store/favorites.html",
        **_store_page_context(tenant_slug, cards=cards, active_page="favorites"),
    )


@installments_store_bp.post("/<tenant_slug>/favorites/<int:product_id>")
def favorite_toggle(tenant_slug: str, product_id: int):
    item = _scoped(InstallmentProduct).filter_by(id=product_id, status="published").first()
    if not item:
        return _json_error("المنتج غير متاح", 404, "PRODUCT_NOT_AVAILABLE")
    ids = _favorite_ids(tenant_slug)
    if product_id in ids:
        ids = [value for value in ids if value != product_id]
        favorited = False
    else:
        ids = [product_id, *[value for value in ids if value != product_id]][:50]
        favorited = True
    session[_favorite_key(tenant_slug)] = ids
    session.modified = True
    if request.is_json or "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"success": True, "favorited": favorited, "count": len(ids), "product_id": product_id})
    return redirect(url_for("installments_store.favorites_page", tenant_slug=tenant_slug))


@installments_store_bp.get("/<tenant_slug>/api/products/<int:product_id>/plans/<int:plan_id>/calculate")
def public_calculate(tenant_slug: str, product_id: int, plan_id: int):
    item = _scoped(InstallmentProduct).filter_by(id=product_id, status="published").first()
    if not item:
        return _json_error("المنتج غير متاح", 404, "PRODUCT_NOT_AVAILABLE")
    plan = _scoped(InstallmentPlan).filter_by(id=plan_id, installment_product_id=item.id, active=True).first()
    allowed_durations = _allowed_durations_for_tenant(item.tenant_id)
    if not plan or (allowed_durations and plan.months not in allowed_durations):
        return _json_error("خطة التقسيط غير متاحة", 404, "PLAN_NOT_AVAILABLE")
    try:
        result = InstallmentCalculationService.calculate(item.cash_price, plan, int(request.args.get("quantity") or 1))
        return jsonify({"success": True, "calculation": result.to_dict()})
    except InstallmentError as exc:
        return _json_error(str(exc))


@installments_store_bp.post("/<tenant_slug>/cart")
def cart_add(tenant_slug: str):
    data = request.get_json(silent=True) or request.form.to_dict()
    item = _scoped(InstallmentProduct).filter_by(id=int(data.get("installment_product_id") or 0), status="published").first()
    plan = _scoped(InstallmentPlan).filter_by(id=int(data.get("plan_id") or 0), active=True).first()
    quantity = max(1, min(int(data.get("quantity") or 1), 99))
    if not item or not item.product or not item.product.active:
        return _json_error("المنتج غير متاح", 409, "PRODUCT_NOT_AVAILABLE")
    if not plan or plan.installment_product_id != item.id:
        return _json_error("خطة التقسيط غير متاحة", 409, "PLAN_NOT_AVAILABLE")
    allowed_durations = _allowed_durations_for_tenant(item.tenant_id)
    if allowed_durations and plan.months not in allowed_durations:
        return _json_error("مدة خطة التقسيط غير مسموحة حالياً", 409, "PLAN_DURATION_NOT_ALLOWED")
    cart = session.get(_cart_key(tenant_slug)) or []
    cart = [row for row in cart if not (int(row.get("product_id") or 0) == item.id and int(row.get("plan_id") or 0) == plan.id)]
    cart.append({"product_id": item.id, "plan_id": plan.id, "quantity": quantity})
    session[_cart_key(tenant_slug)] = cart[:25]
    session.modified = True
    if request.is_json:
        return jsonify({"success": True, "count": sum(int(row.get("quantity") or 1) for row in cart[:25])})
    return redirect(url_for("installments_store.cart_page", tenant_slug=tenant_slug))


@installments_store_bp.get("/<tenant_slug>/cart")
def cart_page(tenant_slug: str):
    rows = _cart_rows(tenant_slug)
    totals = {
        "cash_price": sum(row["calculation"].cash_price for row in rows),
        "installment_total": sum(row["calculation"].installment_total for row in rows),
        "down_payment": sum(row["calculation"].down_payment for row in rows),
        "financed_amount": sum(row["calculation"].financed_amount for row in rows),
    }
    settings = InstallmentSettings.query.filter_by(tenant_id=_tenant_id()).first()
    return render_template(
        "installments/store/cart.html",
        rows=rows,
        totals=totals,
        tenant_slug=tenant_slug,
        idempotency_key=secrets.token_urlsafe(24),
        governorates=IRAQI_GOVERNORATES,
        settings=settings,
        cart_count=_cart_count(tenant_slug),
        current_year=date.today().year,
    )


@installments_store_bp.post("/<tenant_slug>/cart/update")
def cart_update(tenant_slug: str):
    data = request.get_json(silent=True) or request.form.to_dict()
    product_id = int(data.get("product_id") or 0)
    old_plan_id = int(data.get("old_plan_id") or data.get("plan_id") or 0)
    new_plan_id = int(data.get("plan_id") or 0)
    quantity = max(1, min(int(data.get("quantity") or 1), 99))
    item = _scoped(InstallmentProduct).filter_by(id=product_id, status="published").first()
    plan = _scoped(InstallmentPlan).filter_by(id=new_plan_id, installment_product_id=product_id, active=True).first()
    allowed_durations = _allowed_durations_for_tenant(item.tenant_id) if item else set()
    if not item or not item.product or not item.product.active or not plan or (allowed_durations and plan.months not in allowed_durations):
        return _json_error("الخطة أو المنتج غير متاح", 409, "cart_item_unavailable")
    cart = session.get(_cart_key(tenant_slug)) or []
    updated = False
    for row in cart:
        if int(row.get("product_id") or 0) == product_id and int(row.get("plan_id") or 0) == old_plan_id:
            row.update({"plan_id": new_plan_id, "quantity": quantity})
            updated = True
            break
    if not updated:
        return _json_error("عنصر السلة غير موجود", 404, "cart_item_not_found")
    session[_cart_key(tenant_slug)] = cart
    session.modified = True
    return jsonify({"success": True})


@installments_store_bp.post("/<tenant_slug>/cart/clear")
def cart_clear(tenant_slug: str):
    session[_cart_key(tenant_slug)] = []
    session.modified = True
    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("installments_store.cart_page", tenant_slug=tenant_slug))


@installments_store_bp.post("/<tenant_slug>/cart/remove/<int:product_id>/<int:plan_id>")
def cart_remove(tenant_slug: str, product_id: int, plan_id: int):
    cart = session.get(_cart_key(tenant_slug)) or []
    session[_cart_key(tenant_slug)] = [row for row in cart if not (int(row.get("product_id") or 0) == product_id and int(row.get("plan_id") or 0) == plan_id)]
    session.modified = True
    return redirect(url_for("installments_store.cart_page", tenant_slug=tenant_slug))


@installments_store_bp.post("/<tenant_slug>/cart/checkout")
def cart_checkout(tenant_slug: str):
    if not allow_request("installment_checkout", limit=8, window_seconds=60):
        return _json_error("طلبات كثيرة، يرجى المحاولة بعد دقيقة", 429, "rate_limited")
    data = _account_order_data(request.get_json(silent=True) or request.form.to_dict(), _current_store_account(tenant_slug))
    rows = _cart_rows(tenant_slug)
    try:
        selections = [(row["item"], row["plan"], row["quantity"]) for row in rows]
        application, tracking_token = ApplicationService.create_many(selections, data, request.headers.get("Idempotency-Key") or data.get("idempotency_key"))
        if not tracking_token:
            return _json_error("تم إرسال هذا الطلب مسبقًا", 409)
        session[_cart_key(tenant_slug)] = []
        session.modified = True
        return jsonify({"success": True, "application_number": application.application_number, "tracking_token": tracking_token, "status": application.status}), 201
    except InstallmentError as exc:
        return _json_error(str(exc))


@installments_store_bp.post("/<tenant_slug>/applications")
def submit_application(tenant_slug: str):
    if not allow_request("installment_application", limit=8, window_seconds=60):
        return _json_error("طلبات كثيرة، يرجى المحاولة بعد دقيقة", 429, "rate_limited")
    data = _account_order_data(request.get_json(silent=True) or request.form.to_dict(), _current_store_account(tenant_slug))
    try:
        item = _scoped(InstallmentProduct).filter_by(id=int(data.get("installment_product_id") or 0)).first()
        plan = _scoped(InstallmentPlan).filter_by(id=int(data.get("plan_id") or 0)).first()
        if not item or not plan:
            return _json_error("المنتج أو الخطة غير متاحة", 404, "PRODUCT_OR_PLAN_NOT_AVAILABLE")
        application, tracking_token = ApplicationService.create(item, plan, data, request.headers.get("Idempotency-Key") or data.get("idempotency_key"))
        if not tracking_token:
            return _json_error("تم إرسال هذا الطلب مسبقًا", 409)
        return jsonify({"success": True, "application_number": application.application_number, "tracking_token": tracking_token, "status": application.status}), 201
    except InstallmentError as exc:
        current_app.logger.warning("installment checkout rejected: %s", exc)
        return _json_error(str(exc))


@installments_store_bp.route("/<tenant_slug>/track", methods=["GET", "POST"])
def track_application(tenant_slug: str):
    settings = InstallmentSettings.query.filter_by(tenant_id=_tenant_id()).first()
    template_context = {
        "tenant_slug": tenant_slug,
        "settings": settings,
        "cart_count": _cart_count(tenant_slug),
        "current_year": date.today().year,
    }
    if request.method == "GET":
        return render_template("installments/store/tracking.html", **template_context)
    if not allow_request("installment_tracking", limit=20, window_seconds=60):
        return _json_error("طلبات كثيرة، يرجى المحاولة بعد دقيقة", 429, "rate_limited")
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        application = ApplicationService.tracked(data.get("tracking_token"), data.get("phone"), _tenant_id())
    except InstallmentError as exc:
        return _json_error(str(exc))
    if not application:
        if request.is_json:
            return _json_error("لم يتم العثور على الطلب بهذه البيانات", 404)
        return render_template("installments/store/tracking.html", error="لم يتم العثور على الطلب بهذه البيانات", **template_context), 404
    payload = {"number": application.application_number, "status": application.status, "created_at": application.created_at.isoformat(), "rejection_reason": application.rejection_reason if application.status == "rejected" else None, "contract_number": application.contract.contract_number if application.contract else None}
    if request.is_json:
        return jsonify({"success": True, "application": payload})
    return render_template("installments/store/tracking.html", application=payload, **template_context)


@installments_store_bp.get("/<tenant_slug>/about")
def about_page(tenant_slug: str):
    return render_template("installments/store/about.html", **_store_page_context(tenant_slug, active_page="about"))


@installments_store_bp.get("/<tenant_slug>/how-it-works")
def how_it_works_page(tenant_slug: str):
    return render_template("installments/store/how_it_works.html", **_store_page_context(tenant_slug, active_page="how_it_works"))


@installments_store_bp.get("/<tenant_slug>/categories")
def categories_page(tenant_slug: str):
    cards = _published_category_cards(_tenant_id())
    return render_template(
        "installments/store/categories.html",
        **_store_page_context(tenant_slug, active_page="categories", category_cards=cards),
    )


@installments_store_bp.get("/<tenant_slug>/contact")
def contact_page(tenant_slug: str):
    return render_template("installments/store/contact.html", **_store_page_context(tenant_slug, active_page="contact"))


@installments_store_bp.get("/<tenant_slug>/faq")
def faq_page(tenant_slug: str):
    return render_template("installments/store/faq.html", **_store_page_context(tenant_slug, active_page="faq"))


@installments_store_bp.get("/<tenant_slug>/terms")
def terms_page(tenant_slug: str):
    return render_template("installments/store/terms.html", **_store_page_context(tenant_slug, active_page="terms"))
