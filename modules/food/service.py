"""Transactional application service for food products, stock and checkout."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, inspect, or_

from extensions import db
from models.customer import Customer
from models.branch import Branch
from models.employee import Employee
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.order_item import OrderItem
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from modules.food.models import (
    FoodExpiryBatch,
    FoodCashSession,
    FoodCheckoutRequest,
    FoodCustomerProfile,
    FoodExpense,
    FoodHeldSale,
    FoodInventoryMovement,
    FoodPosAuditLog,
    FoodPromotion,
    FoodProductBarcode,
    FoodProductAuditLog,
    FoodProductProfile,
    FoodProductPriceTier,
    FoodProductUnit,
    FoodProductVariant,
    FoodPurchaseItemSnapshot,
    FoodSaleBatchAllocation,
    FoodSaleItemSnapshot,
    FoodSettings,
    FoodSaleReturn,
    FoodSaleReturnBatchAllocation,
    FoodSaleReturnLine,
    FoodSupplierProfile,
    FoodWarehouseStock,
)


class FoodError(ValueError):
    pass


BUSINESS_TIMEZONE = ZoneInfo("Asia/Baghdad")


def _business_today() -> date:
    return datetime.now(BUSINESS_TIMEZONE).date()


def _local_date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(start, datetime.min.time(), tzinfo=BUSINESS_TIMEZONE)
    local_end = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=BUSINESS_TIMEZONE)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def as_int(value, default=0, *, minimum=None) -> int:
    try:
        result = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        result = default
    if minimum is not None and result < minimum:
        raise FoodError(f"القيمة يجب ألا تقل عن {minimum}")
    return result


def as_decimal(value, default=None, *, minimum=None) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FoodError("القيمة الرقمية غير صالحة") from exc
    if minimum is not None and result < Decimal(str(minimum)):
        raise FoodError(f"القيمة يجب ألا تقل عن {minimum}")
    return result


def _sale_quantity(value, conversion_factor: int) -> tuple[Decimal, int]:
    """Normalize a POS quantity while keeping inventory in integer base units.

    Weighted units use a conversion such as 1 kg = 1000 g. A decimal sale is
    accepted only when it resolves to a whole base unit, preventing invisible
    stock fractions that the current inventory ledger cannot represent.
    """
    quantity = as_decimal(value, Decimal("0"), minimum="0.001") or Decimal("0")
    if quantity.as_tuple().exponent < -3:
        raise FoodError("الكمية تدعم ثلاث منازل عشرية كحد أقصى")
    base = quantity * Decimal(int(conversion_factor or 1))
    integral = base.to_integral_value()
    if base != integral:
        raise FoodError("الكمية لا تتوافق مع دقة وحدة المخزون الأساسية")
    return quantity, int(integral)


def _money_for_quantity(unit_price: int, quantity: Decimal) -> int:
    return int((Decimal(int(unit_price or 0)) * quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _optional_int(value, *, minimum=0) -> int | None:
    if value in (None, ""):
        return None
    return as_int(value, 0, minimum=minimum)


def _parse_date(value, label: str, *, required=False) -> date | None:
    if value in (None, ""):
        if required:
            raise FoodError(f"{label} مطلوب")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise FoodError(f"{label} غير صالح") from exc


def _default_warehouse_id() -> int | None:
    row = Branch.query.filter_by(is_active=True, is_default=True).first()
    row = row or Branch.query.filter_by(is_active=True).order_by(Branch.id).first()
    return int(row.id) if row else None


def _valid_warehouse(warehouse_id) -> int | None:
    value = as_int(warehouse_id, 0)
    if not value:
        return _default_warehouse_id()
    row = Branch.query.filter_by(id=value, is_active=True).first()
    if not row:
        raise FoodError("المخزن أو الفرع المحدد غير صالح")
    return int(row.id)


def _warehouse_stock(tenant_id: int, variant_id: int, warehouse_id: int, *, lock=False) -> FoodWarehouseStock:
    query = FoodWarehouseStock.query.filter_by(
        tenant_id=tenant_id, variant_id=variant_id, warehouse_id=warehouse_id
    )
    if lock:
        query = query.with_for_update()
    row = query.first()
    if not row:
        row = FoodWarehouseStock(
            tenant_id=tenant_id, variant_id=variant_id, warehouse_id=warehouse_id,
            opening_base=0, stock_base=0,
        )
        db.session.add(row)
        db.session.flush()
    return row


def _ensure_legacy_warehouse_stock(variant: FoodProductVariant, warehouse_id: int | None) -> None:
    """Place a pre-multi-warehouse balance in the selected/default warehouse once."""
    if warehouse_id is None or int(variant.stock_base or 0) <= 0:
        return
    exists = FoodWarehouseStock.query.filter_by(
        tenant_id=variant.tenant_id, variant_id=variant.id
    ).first()
    if exists:
        return
    db.session.add(FoodWarehouseStock(
        tenant_id=variant.tenant_id, variant_id=variant.id, warehouse_id=warehouse_id,
        opening_base=int(variant.stock_base or 0), stock_base=int(variant.stock_base or 0),
    ))
    db.session.flush()


def _sync_variant_stock(variant: FoodProductVariant) -> int:
    rows = FoodWarehouseStock.query.filter_by(
        tenant_id=variant.tenant_id, variant_id=variant.id
    ).all()
    if rows:
        variant.stock_base = sum(int(row.stock_base or 0) for row in rows)
    return int(variant.stock_base or 0)


def _adjust_warehouse_stock(
    variant: FoodProductVariant,
    warehouse_id: int | None,
    difference: int,
    *, opening=False,
    allow_negative=False,
) -> None:
    if warehouse_id is None:
        variant.stock_base = int(variant.stock_base or 0) + int(difference)
        return
    row = _warehouse_stock(variant.tenant_id, variant.id, warehouse_id, lock=True)
    after = int(row.stock_base or 0) + int(difference)
    if after < 0 and not allow_negative:
        raise FoodError("المخزون غير كافٍ في المخزن المحدد")
    row.stock_base = after
    if opening:
        row.opening_base = int(row.opening_base or 0) + int(difference)
    _sync_variant_stock(variant)


def _primary_barcode(unit: FoodProductUnit) -> str | None:
    active = [row for row in unit.barcodes if row.active]
    primary = next((row for row in active if row.is_primary), active[0] if active else None)
    return primary.barcode if primary else None


def _settings(tenant_id: int) -> FoodSettings:
    row = FoodSettings.query.filter_by(tenant_id=tenant_id).first()
    if not row:
        row = FoodSettings(tenant_id=tenant_id)
        db.session.add(row)
        db.session.flush()
    return row


def _employee_can(employee_id: int | None, permission: str) -> bool:
    employee = db.session.get(Employee, employee_id) if employee_id else None
    if not employee or not employee.is_active:
        return False
    return employee.role == "admin" or employee.has_permission(permission)


def _negative_stock_allowed(tenant_id: int, employee_id: int | None) -> bool:
    settings = _settings(tenant_id)
    policy = str(settings.negative_stock_policy or "prevent").lower()
    if policy == "allow":
        return True
    if policy == "permission":
        return _employee_can(employee_id, "cashier.sell_negative_stock")
    return False


def _discount_amount(raw: dict, gross: int, employee_id: int | None) -> tuple[int, str, Decimal]:
    discount_type = str(raw.get("discount_type") or "amount").strip().lower()
    raw_value = raw.get("discount_value")
    if raw_value in (None, ""):
        raw_value = raw.get("discount") or 0
    value = as_decimal(raw_value, Decimal("0"), minimum=0) or Decimal("0")
    if discount_type not in {"amount", "percent"}:
        raise FoodError("نوع الخصم غير صالح")
    amount = (
        int((Decimal(gross) * value / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if discount_type == "percent" else int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    )
    if amount <= 0:
        return 0, discount_type, value
    if not _employee_can(employee_id, "cashier.discount_item"):
        raise FoodError("ليس لديك صلاحية خصم المادة")
    employee = db.session.get(Employee, employee_id) if employee_id else None
    max_percent = None if employee and employee.role == "admin" else (Decimal("20") if employee and employee.role == "manager" else Decimal("5"))
    effective_percent = Decimal(amount) * Decimal("100") / Decimal(max(1, gross))
    if max_percent is not None and effective_percent > max_percent:
        raise FoodError(f"الحد الأقصى لخصم المادة هو {max_percent}%")
    if amount > gross:
        raise FoodError("خصم المادة أكبر من قيمتها")
    return amount, discount_type, value


def _validate_invoice_discount(amount: int, subtotal: int, employee_id: int | None) -> None:
    if amount <= 0:
        return
    if not _employee_can(employee_id, "cashier.discount_invoice"):
        raise FoodError("ليس لديك صلاحية خصم الفاتورة")
    employee = db.session.get(Employee, employee_id) if employee_id else None
    max_percent = None if employee and employee.role == "admin" else (20 if employee and employee.role == "manager" else 5)
    if max_percent is not None and amount * 100 > max(1, subtotal) * max_percent:
        raise FoodError(f"الحد الأقصى لخصم الفاتورة هو {max_percent}%")


def _promotion_discount(tenant_id: int, variant: FoodProductVariant, unit: FoodProductUnit,
                        quantity: Decimal, gross: int) -> tuple[int, str | None, int | None]:
    """Resolve the best active server-side rule for a line; no client trust involved."""
    now = datetime.utcnow()
    rules = FoodPromotion.query.filter(
        FoodPromotion.tenant_id == tenant_id,
        FoodPromotion.active.is_(True),
        or_(FoodPromotion.starts_at.is_(None), FoodPromotion.starts_at <= now),
        or_(FoodPromotion.ends_at.is_(None), FoodPromotion.ends_at >= now),
        FoodPromotion.minimum_quantity <= quantity,
    ).order_by(FoodPromotion.priority.desc(), FoodPromotion.id).all()
    candidates = []
    for rule in rules:
        scope = str(rule.scope_type or "all").lower()
        value = str(rule.scope_value or "")
        matches = (
            scope == "all"
            or (scope == "variant" and value == str(variant.id))
            or (scope == "unit" and value == str(unit.id))
            or (scope == "category" and value == str(variant.profile.category or ""))
            or (scope == "subcategory" and value == str(variant.profile.subcategory or ""))
        )
        if not matches:
            continue
        discount_value = Decimal(rule.discount_value or 0)
        amount = (
            int((Decimal(gross) * discount_value / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if rule.discount_type == "percent"
            else int(discount_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        )
        candidates.append((min(gross, max(0, amount)), rule.name, rule.id))
    return max(candidates, key=lambda item: item[0]) if candidates else (0, None, None)


def _audit_pos(tenant_id: int, employee_id: int | None, action: str, *, entity_type=None,
               entity_id=None, details=None) -> None:
    db.session.add(FoodPosAuditLog(
        tenant_id=tenant_id,
        employee_id=employee_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json.dumps(details or {}, ensure_ascii=False, sort_keys=True, default=str),
    ))


def _request_fingerprint(payload: dict) -> str:
    canonical = dict(payload)
    canonical.pop("idempotency_key", None)
    return hashlib.sha256(json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")).hexdigest()


def _customer_debt(tenant_id: int, customer_id: int) -> int:
    rows = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.customer_id == customer_id,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    returned = {
        invoice_id: int(total or 0)
        for invoice_id, total in db.session.query(
            FoodSaleReturn.invoice_id, func.sum(FoodSaleReturn.total)
        ).filter(FoodSaleReturn.tenant_id == tenant_id).group_by(FoodSaleReturn.invoice_id).all()
    }
    return max(0, sum(
        max(0, int(row.total or 0) - returned.get(row.id, 0) - int(row.paid_amount or 0))
        for row in rows
    ))


def _variant(tenant_id: int, variant_id: int, *, lock=False) -> FoodProductVariant:
    query = FoodProductVariant.query.filter_by(tenant_id=tenant_id, id=variant_id)
    if lock:
        query = query.with_for_update()
    row = query.first()
    if not row or not row.active or not row.profile.active or not row.profile.product.active:
        raise FoodError("النوع غير موجود ضمن هذه الشركة")
    return row


def _unit(tenant_id: int, variant_id: int, unit_id: int) -> FoodProductUnit:
    row = FoodProductUnit.query.filter_by(
        tenant_id=tenant_id, variant_id=variant_id, id=unit_id, active=True
    ).first()
    if not row:
        raise FoodError("وحدة التعبئة غير صالحة لهذا النوع")
    return row


def decompose_stock(quantity: int, units: list[FoodProductUnit]) -> str:
    quantity = int(quantity or 0)
    if quantity < 0:
        base = next((u for u in units if u.is_base), units[-1] if units else None)
        return f"{quantity} {base.unit_name if base else 'وحدة'}"
    parts = []
    remaining = quantity
    for unit in sorted((u for u in units if u.active), key=lambda u: u.conversion_factor, reverse=True):
        factor = int(unit.conversion_factor or 1)
        count, remaining = divmod(remaining, factor)
        if count:
            parts.append(f"{count} {unit.unit_name}")
    return " + ".join(parts) if parts else "0"


def _variant_dict(row: FoodProductVariant, warehouse_id: int | None = None) -> dict:
    units = sorted(row.units, key=lambda item: (not item.is_base, item.conversion_factor))
    profile = row.profile
    product = profile.product
    stock_base = int(row.stock_base or 0)
    if warehouse_id is not None:
        warehouse_stock = FoodWarehouseStock.query.filter_by(
            tenant_id=row.tenant_id, variant_id=row.id, warehouse_id=warehouse_id
        ).first()
        stock_base = int(warehouse_stock.stock_base or 0) if warehouse_stock else 0
    return {
        "id": row.id,
        "product_id": product.id,
        "profile_id": profile.id,
        "product_name": product.name,
        "short_name": profile.short_name,
        "brand": profile.brand,
        "category": profile.category,
        "subcategory": profile.subcategory,
        "status": profile.status,
        "track_stock": bool(profile.track_stock),
        "track_expiry": bool(profile.track_expiry),
        "track_batches": bool(profile.track_batches),
        "variant_name": row.variant_name,
        "flavor": row.flavor,
        "size": row.size,
        "size_value": str(row.size_value) if row.size_value is not None else None,
        "size_unit": row.size_unit,
        "sku": row.sku,
        "image_url": row.image_url or product.image_url,
        "stock_base": stock_base,
        "stock_display": decompose_stock(stock_base, units),
        "minimum_stock": int(row.minimum_stock or 0),
        "reorder_quantity": int(row.reorder_quantity or 0),
        "average_cost": int(row.average_cost or 0),
        "default_sale_unit_id": row.default_sale_unit_id,
        "default_purchase_unit_id": row.default_purchase_unit_id,
        "units": [
            {
                "id": unit.id,
                "name": unit.unit_name,
                "factor": int(unit.conversion_factor),
                "quantity_step": ("0.001" if str(unit.unit_name or "").strip().lower()
                                  in {"kg", "كغم", "كيلو", "g", "غرام", "gram",
                                      "l", "لتر", "ml", "مل"} else "1"),
                "retail_price": int(unit.retail_price or 0),
                "wholesale_price": int(unit.wholesale_price or 0),
                "purchase_price": int(unit.purchase_price or 0),
                "is_base": bool(unit.is_base),
                "parent_unit_id": unit.parent_unit_id,
                "parent_multiplier": int(unit.parent_multiplier or 1),
                "wholesale_minimum": int(unit.wholesale_minimum or 1),
                "auto_wholesale": bool(unit.auto_wholesale),
                "can_sell": bool(unit.can_sell),
                "can_purchase": bool(unit.can_purchase),
                "barcodes": [b.barcode for b in unit.barcodes if b.active],
            }
            for unit in units if unit.active
        ],
    }


def ensure_legacy_product_profiles(tenant_id: int) -> int:
    """Add a food projection for legacy Product rows without changing their IDs or history."""
    profiled_ids = db.session.query(FoodProductProfile.product_id).filter(
        FoodProductProfile.tenant_id == tenant_id
    )
    legacy_rows = Product.query.execution_options(skip_branch_scope=True).filter(
        Product.tenant_id == tenant_id,
        ~Product.id.in_(profiled_ids),
    ).order_by(Product.id).all()
    imported = 0
    for product in legacy_rows:
        profile = FoodProductProfile(
            tenant_id=tenant_id, product_id=product.id,
            short_name=(product.name or "")[:100] or None,
            category=getattr(product, "catalog_category", None),
            track_stock=True, track_expiry=False, status="active" if product.active else "paused",
            active=bool(product.active),
        )
        db.session.add(profile)
        db.session.flush()
        variant = FoodProductVariant(
            tenant_id=tenant_id, profile_id=profile.id,
            variant_name="افتراضي", sku=product.sku,
            stock_base=max(0, int(product.quantity or 0)),
            average_cost=max(0, int(product.buy_price or 0)),
            minimum_stock=max(0, int(product.low_stock_threshold or 0)),
            active=bool(product.active), status="active" if product.active else "paused",
        )
        db.session.add(variant)
        db.session.flush()
        unit = FoodProductUnit(
            tenant_id=tenant_id, variant_id=variant.id, unit_name="قطعة",
            conversion_factor=1, purchase_price=max(0, int(product.buy_price or 0)),
            retail_price=max(0, int(product.sale_price or 0)),
            wholesale_price=max(0, int(product.sale_price or 0)),
            wholesale_minimum=1, is_base=True, can_sell=True, can_purchase=True,
        )
        db.session.add(unit)
        db.session.flush()
        variant.default_sale_unit_id = unit.id
        variant.default_purchase_unit_id = unit.id
        barcode = str(product.barcode or "").strip()
        if barcode and not FoodProductBarcode.query.filter_by(
            tenant_id=tenant_id, barcode=barcode, active=True
        ).first():
            db.session.add(FoodProductBarcode(
                tenant_id=tenant_id, profile_id=profile.id, variant_id=variant.id,
                unit_id=unit.id, barcode=barcode, is_primary=True,
            ))
        if variant.stock_base:
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id, variant_id=variant.id, unit_id=unit.id,
                movement_type="legacy_import", quantity_base=variant.stock_base,
                quantity_before=0, quantity_after=variant.stock_base,
                note="ترحيل آمن من المنتج القديم",
            ))
        db.session.add(FoodProductAuditLog(
            tenant_id=tenant_id, profile_id=profile.id, action="legacy_import",
            after_value=json.dumps({"product_id": product.id}, ensure_ascii=False),
        ))
        imported += 1
    if imported:
        db.session.flush()
    return imported


def list_products(tenant_id: int, search="", category="", warehouse_id=None) -> list[dict]:
    ensure_legacy_product_profiles(tenant_id)
    query = FoodProductVariant.query.join(FoodProductProfile).join(Product).filter(
        FoodProductVariant.tenant_id == tenant_id,
        FoodProductVariant.active.is_(True),
        FoodProductProfile.active.is_(True),
        Product.active.is_(True),
    )
    if category:
        query = query.filter(FoodProductProfile.category == category)
    term = str(search or "").strip()
    if term:
        like = f"%{term}%"
        barcode_variant_ids = db.session.query(FoodProductBarcode.variant_id).filter(
            FoodProductBarcode.tenant_id == tenant_id,
            FoodProductBarcode.active.is_(True),
            FoodProductBarcode.barcode.ilike(like),
        )
        query = query.filter(or_(
            Product.name.ilike(like),
            FoodProductProfile.brand.ilike(like),
            FoodProductVariant.variant_name.ilike(like),
            FoodProductVariant.flavor.ilike(like),
            FoodProductVariant.sku.ilike(like),
            FoodProductVariant.id.in_(barcode_variant_ids),
        ))
    warehouse_id = as_int(warehouse_id, 0) or None
    return [_variant_dict(row, warehouse_id) for row in query.order_by(Product.name, FoodProductVariant.variant_name).limit(250)]


def categories(tenant_id: int) -> list[str]:
    rows = db.session.query(FoodProductProfile.category).filter(
        FoodProductProfile.tenant_id == tenant_id,
        FoodProductProfile.active.is_(True),
        FoodProductProfile.category.isnot(None),
    ).distinct().order_by(FoodProductProfile.category).all()
    return [str(value) for (value,) in rows if value]


def subcategories(tenant_id: int) -> dict[str, list[str]]:
    rows = db.session.query(FoodProductProfile.category, FoodProductProfile.subcategory).filter(
        FoodProductProfile.tenant_id == tenant_id,
        FoodProductProfile.active.is_(True),
        FoodProductProfile.category.isnot(None),
        FoodProductProfile.subcategory.isnot(None),
    ).distinct().order_by(FoodProductProfile.category, FoodProductProfile.subcategory).all()
    result: dict[str, list[str]] = {}
    for category, subcategory in rows:
        if category and subcategory:
            result.setdefault(str(category), []).append(str(subcategory))
    return result


def list_promotions(tenant_id: int) -> list[dict]:
    return [{
        "id": row.id, "name": row.name, "scope_type": row.scope_type,
        "scope_value": row.scope_value, "discount_type": row.discount_type,
        "discount_value": str(row.discount_value or 0),
        "minimum_quantity": str(row.minimum_quantity or 1), "priority": row.priority,
        "active": bool(row.active),
        "starts_at": row.starts_at.isoformat() if row.starts_at else None,
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
    } for row in FoodPromotion.query.filter_by(tenant_id=tenant_id)
        .order_by(FoodPromotion.priority.desc(), FoodPromotion.id.desc()).all()]


def save_promotion(tenant_id: int, payload: dict, promotion_id=None) -> dict:
    row = FoodPromotion.query.filter_by(tenant_id=tenant_id, id=promotion_id).first() if promotion_id else FoodPromotion(tenant_id=tenant_id)
    if not row:
        raise FoodError("العرض غير موجود")
    name = str(payload.get("name") or "").strip()[:150]
    if not name:
        raise FoodError("اسم العرض مطلوب")
    scope_type = str(payload.get("scope_type") or "all").lower()
    discount_type = str(payload.get("discount_type") or "percent").lower()
    if scope_type not in {"all", "variant", "unit", "category", "subcategory"}:
        raise FoodError("نطاق العرض غير صالح")
    if discount_type not in {"amount", "percent"}:
        raise FoodError("نوع خصم العرض غير صالح")
    value = as_decimal(payload.get("discount_value"), Decimal("0.001"), minimum=Decimal("0.001"))
    if discount_type == "percent" and value > 100:
        raise FoodError("نسبة العرض لا يمكن أن تتجاوز 100%")
    def parse_time(raw):
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError as exc:
            raise FoodError("تاريخ العرض غير صالح") from exc
    row.name = name
    row.scope_type = scope_type
    row.scope_value = str(payload.get("scope_value") or "").strip()[:150] or None
    row.discount_type = discount_type
    row.discount_value = value
    row.minimum_quantity = as_decimal(payload.get("minimum_quantity"), Decimal("1"), minimum=Decimal("0.001"))
    row.priority = as_int(payload.get("priority"), 0)
    row.active = bool(payload.get("active", True))
    row.starts_at = parse_time(payload.get("starts_at"))
    row.ends_at = parse_time(payload.get("ends_at"))
    if row.ends_at and row.starts_at and row.ends_at < row.starts_at:
        raise FoodError("نهاية العرض يجب أن تكون بعد بدايته")
    db.session.add(row)
    db.session.flush()
    return next(item for item in list_promotions(tenant_id) if item["id"] == row.id)


PROFILE_STATUSES = {"active", "paused", "archived", "seasonal", "draft"}
STORAGE_TYPES = {"normal", "chilled", "frozen"}
RETURN_POLICIES = {"normal", "non_returnable", "supplier", "supplier_expiry"}
SIZE_UNITS = {"g", "kg", "ml", "L", "pcs"}


def _normalized_barcodes(raw_values) -> list[dict]:
    if isinstance(raw_values, str):
        raw_values = [part.strip() for part in raw_values.split(",")]
    result = []
    for index, raw in enumerate(raw_values or []):
        if isinstance(raw, dict):
            value = str(raw.get("value") or raw.get("barcode") or "").strip()
            primary = bool(raw.get("is_primary"))
            row_id = as_int(raw.get("id"), 0) or None
        else:
            value, primary, row_id = str(raw or "").strip(), index == 0, None
        if value:
            result.append({"id": row_id, "value": value[:160], "is_primary": primary})
    if result and not any(row["is_primary"] for row in result):
        result[0]["is_primary"] = True
    primary_seen = False
    for row in result:
        if row["is_primary"] and not primary_seen:
            primary_seen = True
        elif row["is_primary"]:
            row["is_primary"] = False
    return result


def _unit_plan(variant_data: dict) -> list[dict]:
    raw_units = variant_data.get("units") or []
    if not isinstance(raw_units, list) or not raw_units:
        raise FoodError("كل نوع يحتاج وحدة بيع أو شراء واحدة على الأقل")
    if sum(1 for row in raw_units if bool(row.get("is_base"))) != 1:
        raise FoodError("حدد وحدة أساسية واحدة فقط لكل نوع")
    plan = []
    keys = set()
    names = set()
    for index, raw in enumerate(raw_units):
        key = str(raw.get("client_key") or raw.get("key") or raw.get("id") or f"unit-{index}")
        name = str(raw.get("unit_name") or raw.get("name") or "").strip()
        if not name:
            raise FoodError("اسم الوحدة مطلوب")
        if key in keys or name.casefold() in names:
            raise FoodError(f"الوحدة مكررة داخل النوع: {name}")
        keys.add(key)
        names.add(name.casefold())
        is_base = bool(raw.get("is_base"))
        plan.append({
            "key": key,
            "id": as_int(raw.get("id"), 0) or None,
            "name": name[:80],
            "is_base": is_base,
            "parent_key": None if is_base else str(raw.get("parent_key") or raw.get("parent_unit_key") or "").strip() or None,
            "parent_multiplier": 1 if is_base else as_int(raw.get("parent_multiplier"), 0, minimum=0),
            "direct_factor": as_int(raw.get("conversion_factor", raw.get("factor")), 1, minimum=1),
            "retail_price": as_int(raw.get("retail_price"), 0, minimum=0),
            "wholesale_price": as_int(raw.get("wholesale_price"), 0, minimum=0),
            "wholesale_minimum": as_int(raw.get("wholesale_minimum"), 1, minimum=1),
            "auto_wholesale": bool(raw.get("auto_wholesale", False)),
            "purchase_price": as_int(raw.get("purchase_price"), 0, minimum=0),
            "can_sell": bool(raw.get("can_sell", True)),
            "can_purchase": bool(raw.get("can_purchase", True)),
            "barcodes": _normalized_barcodes(raw.get("barcodes")),
            "sort_order": index,
        })
    by_key = {row["key"]: row for row in plan}
    visiting: set[str] = set()
    complete: set[str] = set()

    def resolve(row: dict) -> int:
        if row["key"] in complete:
            return int(row["factor"])
        if row["key"] in visiting:
            raise FoodError("يوجد تحويل دائري بين الوحدات")
        visiting.add(row["key"])
        if row["is_base"]:
            factor = 1
        elif row["parent_key"]:
            parent = by_key.get(row["parent_key"])
            if not parent:
                raise FoodError(f"الوحدة الأب غير موجودة للوحدة {row['name']}")
            multiplier = as_int(row["parent_multiplier"], 0, minimum=1)
            factor = resolve(parent) * multiplier
        else:
            factor = int(row["direct_factor"])
        row["factor"] = factor
        visiting.remove(row["key"])
        complete.add(row["key"])
        return factor

    for unit_row in plan:
        resolve(unit_row)
    return plan


def _validate_product_uniqueness(tenant_id: int, variants: list[dict], *, exclude_profile_id=None) -> None:
    codes: list[str] = []
    skus: list[str] = []
    for variant_data in variants:
        sku = str(variant_data.get("sku") or "").strip()
        if sku:
            skus.append(sku)
        for unit in variant_data["_unit_plan"]:
            codes.extend(row["value"] for row in unit["barcodes"])
    duplicate_code = next((code for code in codes if codes.count(code) > 1), None)
    if duplicate_code:
        raise FoodError(f"الباركود مكرر داخل النموذج: {duplicate_code}")
    duplicate_sku = next((sku for sku in skus if skus.count(sku) > 1), None)
    if duplicate_sku:
        raise FoodError(f"SKU مكرر داخل النموذج: {duplicate_sku}")
    if codes:
        query = FoodProductBarcode.query.filter(
            FoodProductBarcode.tenant_id == tenant_id,
            FoodProductBarcode.active.is_(True),
            FoodProductBarcode.barcode.in_(codes),
        )
        if exclude_profile_id:
            query = query.filter(FoodProductBarcode.profile_id != exclude_profile_id)
        conflict = query.first()
        if conflict:
            row = conflict.unit.variant
            raise FoodError(
                f"الباركود {conflict.barcode} مستخدم بالفعل في: "
                f"{row.profile.product.name} / {row.variant_name} / {conflict.unit.unit_name}"
            )
    if skus:
        query = FoodProductVariant.query.filter(
            FoodProductVariant.tenant_id == tenant_id,
            FoodProductVariant.sku.in_(skus),
        )
        if exclude_profile_id:
            query = query.filter(FoodProductVariant.profile_id != exclude_profile_id)
        conflict = query.first()
        if conflict:
            raise FoodError(f"SKU مستخدم بالفعل: {conflict.sku}")


def _prepare_product_payload(tenant_id: int, payload: dict, *, exclude_profile_id=None) -> tuple[str, list[dict]]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise FoodError("اسم المنتج مطلوب")
    variants = payload.get("variants") or []
    if not isinstance(variants, list) or not variants:
        raise FoodError("أضف نوعاً واحداً على الأقل")
    for variant_data in variants:
        variant_data["_unit_plan"] = _unit_plan(variant_data)
        size_unit = str(variant_data.get("size_unit") or "").strip()
        if size_unit and size_unit not in SIZE_UNITS:
            raise FoodError("وحدة الحجم غير صالحة")
        as_decimal(variant_data.get("size_value"), None, minimum=0)
    _validate_product_uniqueness(tenant_id, variants, exclude_profile_id=exclude_profile_id)
    return name[:150], variants


def _profile_status(payload: dict) -> str:
    requested = str(payload.get("status") or ("active" if payload.get("active", True) else "paused")).lower()
    return requested if requested in PROFILE_STATUSES else "active"


def _set_profile_fields(profile: FoodProductProfile, product: Product, payload: dict) -> None:
    status = _profile_status(payload)
    product.name = str(payload.get("name") or product.name).strip()[:150]
    product.description = str(payload.get("description") or "").strip() or None
    product.image_url = str(payload.get("image_url") or "").strip() or None
    product.low_stock_threshold = as_int(payload.get("minimum_stock"), 0, minimum=0)
    product.active = status in {"active", "seasonal"}
    profile.short_name = str(payload.get("short_name") or "").strip()[:100] or None
    profile.brand = str(payload.get("brand") or "").strip()[:120] or None
    profile.category = str(payload.get("category") or "").strip()[:120] or None
    profile.subcategory = str(payload.get("subcategory") or "").strip()[:120] or None
    profile.origin_country = str(payload.get("origin_country") or "").strip()[:100] or None
    profile.default_supplier_id = as_int(payload.get("default_supplier_id"), 0) or None
    profile.supplier_product_code = str(payload.get("supplier_product_code") or "").strip()[:120] or None
    profile.track_stock = bool(payload.get("track_stock", True))
    profile.track_expiry = bool(payload.get("track_expiry", False))
    profile.track_batches = bool(payload.get("track_batches", profile.track_expiry)) if profile.track_expiry else False
    profile.shelf_life_value = _optional_int(payload.get("shelf_life_value"), minimum=1)
    profile.shelf_life_unit = str(payload.get("shelf_life_unit") or "").strip()[:20] or None
    settings_row = _settings(profile.tenant_id)
    default_warning = int(getattr(settings_row, "expiry_warning_days", None) or 30)
    configured_issue = str(getattr(settings_row, "default_issue_policy", None) or "").upper()
    if configured_issue not in {"FIFO", "FEFO"}:
        configured_issue = "FEFO" if profile.track_expiry else "FIFO"
    if not profile.track_expiry:
        configured_issue = "FIFO"
    profile.expiry_warning_days = as_int(payload.get("expiry_warning_days"), default_warning, minimum=1)
    profile.issue_policy = str(payload.get("issue_policy") or configured_issue).upper()
    if profile.issue_policy not in {"FIFO", "FEFO"}:
        profile.issue_policy = configured_issue
    profile.reorder_quantity = as_int(payload.get("reorder_quantity"), 0, minimum=0)
    profile.maximum_stock = _optional_int(payload.get("maximum_stock"), minimum=0)
    profile.storage_location = str(payload.get("storage_location") or "").strip()[:255] or None
    storage_type = str(payload.get("storage_type") or "normal").lower()
    profile.storage_type = storage_type if storage_type in STORAGE_TYPES else "normal"
    return_policy = str(payload.get("return_policy") or "normal").lower()
    profile.return_policy = return_policy if return_policy in RETURN_POLICIES else "normal"
    profile.taxable = bool(payload.get("taxable", False))
    profile.tax_rate = as_decimal(payload.get("tax_rate"), Decimal("0"), minimum=0) if profile.taxable else Decimal("0")
    profile.auto_wholesale_pricing = bool(payload.get("auto_wholesale_pricing", True))
    profile.status = status
    profile.active = status != "archived"


def _create_units(tenant_id: int, profile: FoodProductProfile, variant: FoodProductVariant, plan: list[dict]) -> dict[str, FoodProductUnit]:
    units_by_key: dict[str, FoodProductUnit] = {}
    for row in plan:
        unit = FoodProductUnit(
            tenant_id=tenant_id, variant_id=variant.id, unit_name=row["name"],
            conversion_factor=row["factor"], retail_price=row["retail_price"],
            wholesale_price=row["wholesale_price"], wholesale_minimum=row["wholesale_minimum"],
            auto_wholesale=row["auto_wholesale"], purchase_price=row["purchase_price"],
            is_base=row["is_base"], can_sell=row["can_sell"], can_purchase=row["can_purchase"],
            sort_order=row["sort_order"], parent_multiplier=(row["parent_multiplier"] or None),
        )
        db.session.add(unit)
        db.session.flush()
        units_by_key[row["key"]] = unit
    for row in plan:
        unit = units_by_key[row["key"]]
        unit.parent_unit_id = units_by_key[row["parent_key"]].id if row["parent_key"] else None
        for barcode in row["barcodes"]:
            db.session.add(FoodProductBarcode(
                tenant_id=tenant_id, profile_id=profile.id, variant_id=variant.id,
                unit_id=unit.id, barcode=barcode["value"], is_primary=barcode["is_primary"],
            ))
        if row["wholesale_price"] and row["wholesale_minimum"]:
            db.session.add(FoodProductPriceTier(
                tenant_id=tenant_id, unit_id=unit.id, tier_code="WHOLESALE",
                minimum_quantity=row["wholesale_minimum"], price=row["wholesale_price"],
                active=row["auto_wholesale"],
            ))
    return units_by_key


def _apply_opening_stock(
    tenant_id: int,
    profile: FoodProductProfile,
    variant: FoodProductVariant,
    units_by_key: dict[str, FoodProductUnit],
    variant_data: dict,
    employee_id: int | None,
) -> None:
    if not profile.track_stock:
        variant.stock_base = 0
        return
    rows = variant_data.get("opening_stocks") or []
    if not rows:
        legacy = as_int(variant_data.get("opening_stock"), 0, minimum=0)
        variant.stock_base = legacy
        if legacy:
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id, variant_id=variant.id, movement_type="opening",
                quantity_base=legacy, quantity_before=0, quantity_after=legacy,
                note="رصيد افتتاحي", employee_id=employee_id,
            ))
        return
    total_value = 0
    total_base = 0
    for opening in rows:
        unit = units_by_key.get(str(opening.get("unit_key") or ""))
        if not unit:
            raise FoodError("وحدة الرصيد الافتتاحي غير صالحة")
        quantity = as_int(opening.get("quantity"), 0, minimum=0)
        if not quantity:
            continue
        quantity_base = quantity * int(unit.conversion_factor)
        warehouse_id = _valid_warehouse(opening.get("warehouse_id"))
        if warehouse_id is None:
            raise FoodError("أضف مخزناً أو فرعاً قبل تسجيل رصيد متعدد المخازن")
        before = int(variant.stock_base or 0)
        _adjust_warehouse_stock(variant, warehouse_id, quantity_base, opening=True)
        base_cost = as_int(opening.get("unit_cost"), int(unit.purchase_price or 0), minimum=0) // max(1, int(unit.conversion_factor))
        total_value += quantity_base * base_cost
        total_base += quantity_base
        movement = FoodInventoryMovement(
            tenant_id=tenant_id, variant_id=variant.id, unit_id=unit.id,
            warehouse_id=warehouse_id, movement_type="opening", quantity_base=quantity_base,
            quantity_before=before, quantity_after=int(variant.stock_base or 0),
            note="رصيد افتتاحي", employee_id=employee_id,
        )
        db.session.add(movement)
        if profile.track_expiry:
            production = _parse_date(opening.get("production_date"), "تاريخ الإنتاج")
            expiry = _parse_date(opening.get("expiry_date"), "تاريخ الانتهاء", required=True)
            if production and expiry <= production:
                raise FoodError("تاريخ الانتهاء يجب أن يكون بعد تاريخ الإنتاج")
            batch = FoodExpiryBatch(
                tenant_id=tenant_id, variant_id=variant.id, warehouse_id=warehouse_id,
                received_unit_id=unit.id, batch_number=str(opening.get("batch_number") or "").strip() or None,
                production_date=production, expiry_date=expiry, quantity_base=quantity_base,
                received_quantity=quantity, unit_factor_snapshot=unit.conversion_factor,
                unit_cost_snapshot=as_int(opening.get("unit_cost"), int(unit.purchase_price or 0), minimum=0),
                supplier_id=profile.default_supplier_id, status="sellable",
            )
            db.session.add(batch)
            db.session.flush()
            movement.batch_id = batch.id
    if total_base:
        variant.average_cost = total_value // total_base


def create_product(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    name, variants = _prepare_product_payload(tenant_id, payload)
    status = _profile_status(payload)
    product = Product(
        tenant_id=tenant_id, name=name, sku=None, barcode=None, buy_price=0, sale_price=0,
        opening_stock=0, quantity=0, active=status in {"active", "seasonal"},
        low_stock_threshold=0,
    )
    db.session.add(product)
    db.session.flush()
    profile = FoodProductProfile(tenant_id=tenant_id, product_id=product.id)
    _set_profile_fields(profile, product, payload)
    db.session.add(profile)
    db.session.flush()
    first_prices = None
    for variant_data in variants:
        size_value = as_decimal(variant_data.get("size_value"), None, minimum=0)
        size_unit = str(variant_data.get("size_unit") or "").strip() or None
        legacy_size = str(variant_data.get("size") or "").strip() or (
            f"{size_value.normalize()} {size_unit}" if size_value is not None and size_unit else None
        )
        variant = FoodProductVariant(
            tenant_id=tenant_id, profile_id=profile.id,
            variant_name=str(variant_data.get("variant_name") or variant_data.get("name") or name).strip()[:150] or name,
            flavor=str(variant_data.get("flavor") or "").strip()[:100] or None,
            size=legacy_size, size_value=size_value, size_unit=size_unit,
            sku=str(variant_data.get("sku") or "").strip()[:100] or None,
            image_url=str(variant_data.get("image_url") or "").strip() or None,
            stock_base=0, average_cost=as_int(variant_data.get("cost"), 0, minimum=0),
            minimum_stock=as_int(variant_data.get("minimum_stock"), product.low_stock_threshold, minimum=0),
            reorder_quantity=as_int(variant_data.get("reorder_quantity"), profile.reorder_quantity, minimum=0),
            maximum_stock=_optional_int(variant_data.get("maximum_stock", profile.maximum_stock), minimum=0),
            storage_location=str(variant_data.get("storage_location") or profile.storage_location or "").strip() or None,
            status=str(variant_data.get("status") or "active"), active=True,
        )
        db.session.add(variant)
        db.session.flush()
        units_by_key = _create_units(tenant_id, profile, variant, variant_data["_unit_plan"])
        default_sale_key = str(variant_data.get("default_sale_unit_key") or "")
        default_purchase_key = str(variant_data.get("default_purchase_unit_key") or "")
        base_unit = next(unit for key, unit in units_by_key.items() if unit.is_base)
        variant.default_sale_unit_id = (units_by_key.get(default_sale_key) or base_unit).id
        variant.default_purchase_unit_id = (units_by_key.get(default_purchase_key) or base_unit).id
        _apply_opening_stock(tenant_id, profile, variant, units_by_key, variant_data, employee_id)
        if first_prices is None:
            first_prices = (base_unit.purchase_price or variant.average_cost, base_unit.retail_price)
    if first_prices:
        product.buy_price = int(first_prices[0] or 0)
        product.sale_price = int(first_prices[1] or 0)
    db.session.add(FoodProductAuditLog(
        tenant_id=tenant_id, profile_id=profile.id, action="create",
        after_value=json.dumps({"name": product.name, "status": profile.status}, ensure_ascii=False),
        employee_id=employee_id,
    ))
    db.session.flush()
    return {"id": profile.id, "product_id": product.id, "name": product.name, "status": profile.status}


def _unit_detail(unit: FoodProductUnit) -> dict:
    return {
        "id": unit.id,
        "client_key": f"unit-{unit.id}",
        "unit_name": unit.unit_name,
        "conversion_factor": int(unit.conversion_factor or 1),
        "parent_key": f"unit-{unit.parent_unit_id}" if unit.parent_unit_id else None,
        "parent_multiplier": int(unit.parent_multiplier or 1),
        "retail_price": int(unit.retail_price or 0),
        "wholesale_price": int(unit.wholesale_price or 0),
        "wholesale_minimum": int(unit.wholesale_minimum or 1),
        "auto_wholesale": bool(unit.auto_wholesale),
        "purchase_price": int(unit.purchase_price or 0),
        "is_base": bool(unit.is_base),
        "can_sell": bool(unit.can_sell),
        "can_purchase": bool(unit.can_purchase),
        "barcodes": [
            {"id": row.id, "value": row.barcode, "is_primary": bool(row.is_primary)}
            for row in unit.barcodes if row.active
        ],
    }


def get_product(tenant_id: int, profile_id: int) -> dict:
    profile = FoodProductProfile.query.filter_by(tenant_id=tenant_id, id=profile_id).first()
    if not profile:
        raise FoodError("المنتج غير موجود ضمن هذه الشركة")
    product = profile.product
    variants = []
    for variant in sorted((row for row in profile.variants if row.active), key=lambda row: row.id):
        stocks = FoodWarehouseStock.query.filter_by(
            tenant_id=tenant_id, variant_id=variant.id
        ).order_by(FoodWarehouseStock.warehouse_id).all()
        batches = FoodExpiryBatch.query.filter_by(
            tenant_id=tenant_id, variant_id=variant.id
        ).filter(FoodExpiryBatch.quantity_base > 0).order_by(FoodExpiryBatch.expiry_date).all()
        variants.append({
            "id": variant.id,
            "variant_name": variant.variant_name,
            "flavor": variant.flavor,
            "size_value": str(variant.size_value) if variant.size_value is not None else "",
            "size_unit": variant.size_unit or "",
            "sku": variant.sku or "",
            "image_url": variant.image_url or "",
            "minimum_stock": int(variant.minimum_stock or 0),
            "reorder_quantity": int(variant.reorder_quantity or 0),
            "maximum_stock": variant.maximum_stock,
            "storage_location": variant.storage_location or "",
            "default_sale_unit_id": variant.default_sale_unit_id,
            "default_purchase_unit_id": variant.default_purchase_unit_id,
            "stock_base": int(variant.stock_base or 0),
            "average_cost": int(variant.average_cost or 0),
            "units": [_unit_detail(unit) for unit in sorted(
                (unit for unit in variant.units if unit.active), key=lambda unit: (unit.sort_order, unit.id)
            )],
            "warehouse_stocks": [{
                "warehouse_id": row.warehouse_id,
                "opening_base": int(row.opening_base or 0),
                "stock_base": int(row.stock_base or 0),
            } for row in stocks],
            "batches": [{
                "id": row.id, "warehouse_id": row.warehouse_id,
                "batch_number": row.batch_number or "",
                "production_date": row.production_date.isoformat() if row.production_date else None,
                "expiry_date": row.expiry_date.isoformat(),
                "quantity_base": int(row.quantity_base or 0), "status": row.status,
            } for row in batches],
        })
    return {
        "id": profile.id, "product_id": product.id, "name": product.name,
        "short_name": profile.short_name or "", "brand": profile.brand or "",
        "category": profile.category or "", "subcategory": profile.subcategory or "",
        "origin_country": profile.origin_country or "",
        "default_supplier_id": profile.default_supplier_id,
        "supplier_product_code": profile.supplier_product_code or "",
        "description": product.description or "", "image_url": product.image_url or "",
        "track_stock": bool(profile.track_stock), "track_expiry": bool(profile.track_expiry),
        "track_batches": bool(profile.track_batches),
        "shelf_life_value": profile.shelf_life_value, "shelf_life_unit": profile.shelf_life_unit,
        "expiry_warning_days": int(profile.expiry_warning_days or 30),
        "issue_policy": profile.issue_policy or ("FEFO" if profile.track_expiry else "FIFO"),
        "minimum_stock": int(product.low_stock_threshold or 0),
        "reorder_quantity": int(profile.reorder_quantity or 0),
        "maximum_stock": profile.maximum_stock, "storage_location": profile.storage_location or "",
        "storage_type": profile.storage_type or "normal", "return_policy": profile.return_policy or "normal",
        "taxable": bool(profile.taxable), "tax_rate": str(profile.tax_rate or 0),
        "auto_wholesale_pricing": bool(profile.auto_wholesale_pricing),
        "status": profile.status or ("active" if profile.active else "archived"),
        "variants": variants,
    }


def product_form_options(tenant_id: int) -> dict:
    suppliers = Supplier.query.order_by(Supplier.name).all()
    warehouses = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.name).all()
    brands = db.session.query(FoodProductProfile.brand).filter(
        FoodProductProfile.tenant_id == tenant_id,
        FoodProductProfile.brand.isnot(None),
    ).distinct().order_by(FoodProductProfile.brand).all()
    return {
        "categories": categories(tenant_id),
        "brands": [value for (value,) in brands if value],
        "suppliers": [{"id": row.id, "name": row.name} for row in suppliers],
        "warehouses": [{"id": row.id, "name": row.name, "is_default": bool(row.is_default)} for row in warehouses],
        "size_units": sorted(SIZE_UNITS),
    }


def check_barcode(tenant_id: int, value: str, *, exclude_barcode_id=None) -> dict:
    code = str(value or "").strip()
    if not code:
        return {"available": False, "message": "أدخل الباركود"}
    query = FoodProductBarcode.query.filter_by(tenant_id=tenant_id, barcode=code, active=True)
    if exclude_barcode_id:
        query = query.filter(FoodProductBarcode.id != int(exclude_barcode_id))
    conflict = query.first()
    if not conflict:
        return {"available": True, "message": "الباركود متاح"}
    variant = conflict.unit.variant
    return {
        "available": False,
        "message": (
            f"هذا الباركود مستخدم بالفعل في: {variant.profile.product.name} / "
            f"{variant.variant_name} / {conflict.unit.unit_name}"
        ),
        "conflict": {"profile_id": conflict.profile_id, "variant_id": conflict.variant_id, "unit_id": conflict.unit_id},
    }


def _audit(profile: FoodProductProfile, action: str, field: str, before, after, employee_id) -> None:
    if before == after:
        return
    db.session.add(FoodProductAuditLog(
        tenant_id=profile.tenant_id, profile_id=profile.id, action=action, field_name=field,
        before_value=json.dumps(before, ensure_ascii=False, default=str),
        after_value=json.dumps(after, ensure_ascii=False, default=str), employee_id=employee_id,
    ))


def update_product(tenant_id: int, profile_id: int, payload: dict, employee_id: int | None = None) -> dict:
    profile = FoodProductProfile.query.filter_by(tenant_id=tenant_id, id=profile_id).with_for_update().first()
    if not profile:
        raise FoodError("المنتج غير موجود ضمن هذه الشركة")
    name, variants = _prepare_product_payload(tenant_id, payload, exclude_profile_id=profile.id)
    product = profile.product
    before_profile = get_product(tenant_id, profile.id)
    payload = dict(payload, name=name)
    _set_profile_fields(profile, product, payload)
    existing_variants = {row.id: row for row in profile.variants}
    kept_variant_ids: set[int] = set()
    first_prices = None
    for variant_data in variants:
        variant_id = as_int(variant_data.get("id"), 0)
        variant = existing_variants.get(variant_id) if variant_id else None
        is_new_variant = variant is None
        if variant is None:
            variant = FoodProductVariant(
                tenant_id=tenant_id, profile_id=profile.id, variant_name=name,
                stock_base=0, average_cost=0, minimum_stock=0, active=True,
            )
            db.session.add(variant)
            db.session.flush()
        elif int(variant.profile_id) != profile.id:
            raise FoodError("النوع لا يتبع المنتج المحدد")
        kept_variant_ids.add(variant.id)
        variant.variant_name = str(variant_data.get("variant_name") or name).strip()[:150] or name
        variant.flavor = str(variant_data.get("flavor") or "").strip()[:100] or None
        variant.size_value = as_decimal(variant_data.get("size_value"), None, minimum=0)
        variant.size_unit = str(variant_data.get("size_unit") or "").strip() or None
        variant.size = (
            f"{format(variant.size_value, 'f')} {variant.size_unit}"
            if variant.size_value is not None and variant.size_unit else None
        )
        variant.sku = str(variant_data.get("sku") or "").strip()[:100] or None
        variant.image_url = str(variant_data.get("image_url") or "").strip() or None
        variant.minimum_stock = as_int(variant_data.get("minimum_stock"), product.low_stock_threshold, minimum=0)
        variant.reorder_quantity = as_int(variant_data.get("reorder_quantity"), profile.reorder_quantity, minimum=0)
        variant.maximum_stock = _optional_int(variant_data.get("maximum_stock", profile.maximum_stock), minimum=0)
        variant.storage_location = str(variant_data.get("storage_location") or profile.storage_location or "").strip() or None
        variant.status = str(variant_data.get("status") or "active")
        variant.active = variant.status not in {"archived", "disabled"}
        existing_units = {unit.id: unit for unit in variant.units}
        units_by_key: dict[str, FoodProductUnit] = {}
        kept_unit_ids: set[int] = set()
        for row in variant_data["_unit_plan"]:
            unit = existing_units.get(row["id"]) if row["id"] else None
            if unit is None:
                unit = FoodProductUnit(
                    tenant_id=tenant_id, variant_id=variant.id, unit_name=row["name"],
                    conversion_factor=row["factor"], retail_price=0, wholesale_price=0,
                    purchase_price=0, is_base=row["is_base"], active=True,
                )
                db.session.add(unit)
                db.session.flush()
            elif int(unit.variant_id) != variant.id:
                raise FoodError("الوحدة لا تتبع النوع المحدد")
            before_unit = {
                "conversion": int(unit.conversion_factor or 1),
                "purchase": int(unit.purchase_price or 0),
                "retail": int(unit.retail_price or 0),
                "wholesale": int(unit.wholesale_price or 0),
                "barcodes": sorted(barcode.barcode for barcode in unit.barcodes if barcode.active),
            }
            if int(unit.conversion_factor or 1) != int(row["factor"]):
                used = FoodSaleItemSnapshot.query.filter_by(unit_id=unit.id).first() or FoodPurchaseItemSnapshot.query.filter_by(unit_id=unit.id).first()
                if used and not bool(payload.get("confirm_conversion_change")):
                    raise FoodError("تم استخدام هذه الوحدة في فواتير سابقة. أكد تغيير التحويل للمتابعة مع إبقاء الفواتير القديمة على Snapshot السابق")
            kept_unit_ids.add(unit.id)
            unit.unit_name = row["name"]
            unit.conversion_factor = row["factor"]
            unit.parent_multiplier = row["parent_multiplier"] or None
            unit.retail_price = row["retail_price"]
            unit.wholesale_price = row["wholesale_price"]
            unit.wholesale_minimum = row["wholesale_minimum"]
            unit.auto_wholesale = row["auto_wholesale"]
            unit.purchase_price = row["purchase_price"]
            unit.is_base = row["is_base"]
            unit.can_sell = row["can_sell"]
            unit.can_purchase = row["can_purchase"]
            unit.sort_order = row["sort_order"]
            unit.active = True
            units_by_key[row["key"]] = unit
            after_unit = {
                "conversion": int(row["factor"]), "purchase": int(row["purchase_price"]),
                "retail": int(row["retail_price"]), "wholesale": int(row["wholesale_price"]),
                "barcodes": sorted(barcode["value"] for barcode in row["barcodes"]),
            }
            for audit_field in ("conversion", "purchase", "retail", "wholesale", "barcodes"):
                _audit(
                    profile, "update_unit", f"unit.{unit.id}.{audit_field}",
                    before_unit[audit_field], after_unit[audit_field], employee_id,
                )
        for row in variant_data["_unit_plan"]:
            unit = units_by_key[row["key"]]
            unit.parent_unit_id = units_by_key[row["parent_key"]].id if row["parent_key"] else None
            wanted_codes = {barcode["value"]: barcode for barcode in row["barcodes"]}
            for barcode in FoodProductBarcode.query.filter_by(
                tenant_id=tenant_id, profile_id=profile.id, unit_id=unit.id
            ).all():
                if barcode.barcode not in wanted_codes:
                    barcode.active = False
            for value, barcode_data in wanted_codes.items():
                barcode = FoodProductBarcode.query.filter_by(
                    tenant_id=tenant_id, profile_id=profile.id, barcode=value
                ).first()
                if not barcode:
                    barcode = FoodProductBarcode(tenant_id=tenant_id, profile_id=profile.id, barcode=value)
                    db.session.add(barcode)
                barcode.variant_id = variant.id
                barcode.unit_id = unit.id
                barcode.is_primary = barcode_data["is_primary"]
                barcode.active = True
            tier = FoodProductPriceTier.query.filter_by(
                tenant_id=tenant_id, unit_id=unit.id, tier_code="WHOLESALE"
            ).first()
            if not tier:
                tier = FoodProductPriceTier(tenant_id=tenant_id, unit_id=unit.id, tier_code="WHOLESALE")
                db.session.add(tier)
            tier.minimum_quantity = row["wholesale_minimum"]
            tier.price = row["wholesale_price"]
            tier.active = bool(row["auto_wholesale"] and row["wholesale_price"])
        for unit in existing_units.values():
            if unit.id not in kept_unit_ids:
                unit.active = False
                for barcode in unit.barcodes:
                    barcode.active = False
        base_unit = next(unit for unit in units_by_key.values() if unit.is_base)
        default_sale_key = str(variant_data.get("default_sale_unit_key") or "")
        default_purchase_key = str(variant_data.get("default_purchase_unit_key") or "")
        variant.default_sale_unit_id = (units_by_key.get(default_sale_key) or next((u for u in units_by_key.values() if u.id == as_int(variant_data.get("default_sale_unit_id"), 0)), None) or base_unit).id
        variant.default_purchase_unit_id = (units_by_key.get(default_purchase_key) or next((u for u in units_by_key.values() if u.id == as_int(variant_data.get("default_purchase_unit_id"), 0)), None) or base_unit).id
        if is_new_variant:
            _apply_opening_stock(tenant_id, profile, variant, units_by_key, variant_data, employee_id)
        if first_prices is None:
            first_prices = (base_unit.purchase_price or variant.average_cost, base_unit.retail_price)
    for variant in existing_variants.values():
        if variant.id not in kept_variant_ids:
            variant.active = False
            variant.status = "archived"
            for unit in variant.units:
                unit.active = False
                for barcode in unit.barcodes:
                    barcode.active = False
    if first_prices:
        product.buy_price = int(first_prices[0] or 0)
        product.sale_price = int(first_prices[1] or 0)
    after_profile = {"name": product.name, "status": profile.status, "variants": len(variants)}
    _audit(profile, "update", "product", {"name": before_profile["name"], "status": before_profile["status"], "variants": len(before_profile["variants"])}, after_profile, employee_id)
    db.session.flush()
    return {"id": profile.id, "product_id": product.id, "name": product.name, "status": profile.status}


def archive_product(tenant_id: int, profile_id: int, employee_id: int | None = None) -> dict:
    profile = FoodProductProfile.query.filter_by(tenant_id=tenant_id, id=profile_id).with_for_update().first()
    if not profile:
        raise FoodError("المنتج غير موجود ضمن هذه الشركة")
    before = profile.status
    profile.status = "archived"
    profile.active = False
    profile.product.active = False
    _audit(profile, "archive", "status", before, "archived", employee_id)
    db.session.flush()
    return {"id": profile.id, "status": profile.status}


def lookup_barcode(tenant_id: int, barcode: str, warehouse_id=None) -> dict:
    code = str(barcode or "").strip()
    row = FoodProductBarcode.query.filter_by(tenant_id=tenant_id, barcode=code, active=True).first()
    scale_quantity = None
    if not row:
        settings = _settings(tenant_id)
        prefix = str(settings.scale_barcode_prefix or "20")
        product_digits = max(1, int(settings.scale_barcode_product_digits or 5))
        value_digits = max(1, int(settings.scale_barcode_value_digits or 5))
        expected = len(prefix) + product_digits + value_digits + 1
        if bool(settings.scale_barcode_enabled) and code.isdigit() and len(code) == expected and code.startswith(prefix):
            product_code = code[len(prefix):len(prefix) + product_digits]
            raw_value = code[len(prefix) + product_digits:len(prefix) + product_digits + value_digits]
            variant = FoodProductVariant.query.filter(
                FoodProductVariant.tenant_id == tenant_id,
                FoodProductVariant.sku.in_((product_code, product_code.lstrip("0") or "0")),
                FoodProductVariant.active.is_(True),
            ).first()
            if variant:
                sell_units = [unit for unit in variant.units if unit.active and unit.can_sell]
                kilogram_names = {"kg", "kilogram", "كغم", "كيلو", "كيلوغرام"}
                weight_names = kilogram_names | {"g", "gram", "غرام"}
                weighted = next((unit for unit in sell_units
                                 if str(unit.unit_name or "").strip().lower() in kilogram_names), None)
                weighted = weighted or next((unit for unit in sell_units
                                             if str(unit.unit_name or "").strip().lower() in weight_names), None)
                if weighted:
                    row = type("ScaleBarcode", (), {"variant_id": variant.id, "unit_id": weighted.id})()
                    scale_quantity = Decimal(raw_value) / Decimal(max(1, int(settings.scale_barcode_divisor or 1000)))
        if not row:
            raise FoodError("الباركود غير مسجل")
    data = _variant_dict(_variant(tenant_id, row.variant_id), as_int(warehouse_id, 0) or None)
    data["selected_unit_id"] = row.unit_id
    if scale_quantity is not None:
        data["scale_quantity"] = str(scale_quantity.normalize())
        data["scale_barcode"] = code
    return data


def cashier_catalog(tenant_id: int, *, search="", category="", subcategory="", warehouse_id=None,
                    page=1, per_page=48, mode="catalog") -> dict:
    """Small, ranked cashier feed; exact barcode lookup remains a separate path."""
    ensure_legacy_product_profiles(tenant_id)
    page = max(1, as_int(page, 1))
    per_page = min(100, max(12, as_int(per_page, 48)))
    warehouse_id = as_int(warehouse_id, 0) or None
    query = FoodProductVariant.query.join(FoodProductProfile).join(Product).filter(
        FoodProductVariant.tenant_id == tenant_id,
        FoodProductVariant.active.is_(True),
        FoodProductProfile.active.is_(True),
        Product.active.is_(True),
    )
    if category:
        query = query.filter(FoodProductProfile.category == str(category))
    if subcategory:
        query = query.filter(FoodProductProfile.subcategory == str(subcategory))
    term = str(search or "").strip()
    if term:
        like = f"%{term}%"
        starts = f"{term}%"
        barcode_ids = db.session.query(FoodProductBarcode.variant_id).filter(
            FoodProductBarcode.tenant_id == tenant_id,
            FoodProductBarcode.active.is_(True),
            FoodProductBarcode.barcode == term,
        )
        query = query.filter(or_(
            Product.name.ilike(like), FoodProductProfile.short_name.ilike(like),
            FoodProductProfile.brand.ilike(like), FoodProductVariant.variant_name.ilike(like),
            FoodProductVariant.flavor.ilike(like), FoodProductVariant.size.ilike(like),
            FoodProductVariant.sku.ilike(like), FoodProductVariant.id.in_(barcode_ids),
        )).order_by(
            case((FoodProductVariant.id.in_(barcode_ids), 0), else_=1),
            case((FoodProductVariant.sku == term, 0), else_=1),
            case((Product.name == term, 0), else_=1),
            case((Product.name.ilike(starts), 0), else_=1),
            Product.name, FoodProductVariant.variant_name,
        )
    elif mode in {"best", "recent"}:
        since = datetime.utcnow() - timedelta(days=30)
        activity = (
            db.session.query(
                FoodSaleItemSnapshot.variant_id.label("variant_id"),
                (func.sum(FoodSaleItemSnapshot.quantity_base) if mode == "best"
                 else func.max(Invoice.created_at)).label("rank_value"),
            )
            .join(OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id)
            .join(Invoice, Invoice.id == OrderItem.invoice_id)
            .filter(
                FoodSaleItemSnapshot.tenant_id == tenant_id,
                Invoice.source_module == "food",
                Invoice.created_at >= since,
                ~Invoice.status.in_(("ملغي", "راجع", "مرتجع")),
            )
        )
        if warehouse_id:
            activity = activity.filter(FoodSaleItemSnapshot.warehouse_id == warehouse_id)
        activity = activity.group_by(FoodSaleItemSnapshot.variant_id).subquery()
        query = query.join(activity, activity.c.variant_id == FoodProductVariant.id).order_by(
            activity.c.rank_value.desc()
        )
    else:
        query = query.order_by(Product.name, FoodProductVariant.variant_name)
    total = query.order_by(None).count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    settings = _settings(tenant_id)
    products = [_variant_dict(row, warehouse_id) for row in rows]
    if settings.hide_out_of_stock:
        products = [row for row in products if not row["track_stock"] or row["stock_base"] > 0]
    return {
        "products": products,
        "categories": categories(tenant_id),
        "subcategories": subcategories(tenant_id),
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": page * per_page < total,
    }


def validate_cart(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    warehouse_id = _valid_warehouse(payload.get("warehouse_id"))
    results, subtotal = [], 0
    for raw in payload.get("items") or []:
        variant = _variant(tenant_id, as_int(raw.get("variant_id"), 0))
        unit = _unit(tenant_id, variant.id, as_int(raw.get("unit_id"), 0))
        quantity, base_quantity = _sale_quantity(raw.get("quantity"), unit.conversion_factor)
        mode = str(raw.get("sale_mode") or "RETAIL").upper()
        if mode not in {"RETAIL", "WHOLESALE"}:
            raise FoodError("نوع التسعير غير صالح")
        auto_wholesale = bool(
            unit.auto_wholesale and quantity >= int(unit.wholesale_minimum or 1)
            and int(unit.wholesale_price or 0) > 0
        )
        if auto_wholesale:
            mode = "WHOLESALE"
        price = int(unit.wholesale_price if mode == "WHOLESALE" else unit.retail_price)
        if raw.get("price") is not None:
            requested_price = as_int(raw.get("price"), price, minimum=0)
            if requested_price != price and not _employee_can(employee_id, "cashier.override_price"):
                raise FoodError("ليس لديك صلاحية تغيير السعر")
            price = requested_price
        line_gross = _money_for_quantity(price, quantity)
        manual_discount, discount_type, discount_value = _discount_amount(raw, line_gross, employee_id)
        promotion_discount, promotion_name, promotion_id = _promotion_discount(
            tenant_id, variant, unit, quantity, line_gross
        )
        discount = min(line_gross, manual_discount + promotion_discount)
        line_total = max(0, line_gross - discount)
        available = int(variant.stock_base or 0)
        if warehouse_id:
            stock = FoodWarehouseStock.query.filter_by(
                tenant_id=tenant_id, warehouse_id=warehouse_id, variant_id=variant.id
            ).first()
            available = int(stock.stock_base or 0) if stock else 0
        valid_stock = not variant.profile.track_stock or available >= base_quantity or _negative_stock_allowed(tenant_id, employee_id)
        results.append({
            "variant_id": variant.id, "unit_id": unit.id, "quantity": str(quantity),
            "base_quantity": base_quantity, "sale_mode": mode, "unit_price": price,
            "discount": discount, "line_total": line_total, "stock_ok": valid_stock,
            "discount_type": discount_type, "discount_value": str(discount_value),
            "manual_discount": manual_discount, "promotion_discount": promotion_discount,
            "promotion_name": promotion_name, "promotion_id": promotion_id,
            "available_base": available, "available_display": decompose_stock(available, variant.units),
            "auto_wholesale_applied": auto_wholesale,
        })
        subtotal += line_total
    invoice_discount = as_int(payload.get("invoice_discount"), 0, minimum=0)
    _validate_invoice_discount(invoice_discount, subtotal, employee_id)
    if invoice_discount > subtotal:
        raise FoodError("خصم الفاتورة أكبر من الإجمالي")
    return {"items": results, "subtotal": subtotal, "discount": invoice_discount,
            "tax": 0, "total": subtotal - invoice_discount,
            "valid": all(row["stock_ok"] for row in results)}


def hold_sale(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    validation = validate_cart(tenant_id, payload, employee_id)
    if not payload.get("items"):
        raise FoodError("السلة فارغة")
    hold = FoodHeldSale(
        tenant_id=tenant_id,
        hold_no=f"H{datetime.utcnow():%m%d%H%M%S}{uuid.uuid4().hex[:3].upper()}",
        employee_id=employee_id,
        warehouse_id=_valid_warehouse(payload.get("warehouse_id")),
        customer_id=as_int(payload.get("customer_id"), 0) or None,
        default_sale_mode=str(payload.get("default_sale_mode") or "RETAIL").upper(),
        cart_json=json.dumps(payload.get("items") or [], ensure_ascii=False),
        invoice_discount=validation["discount"],
        note=str(payload.get("note") or "").strip()[:1000] or None,
        total_snapshot=validation["total"],
    )
    db.session.add(hold)
    db.session.flush()
    _audit_pos(tenant_id, employee_id, "hold_create", entity_type="held_sale", entity_id=hold.id)
    return held_sale_dict(hold)


def held_sale_dict(row: FoodHeldSale) -> dict:
    customer = db.session.get(Customer, row.customer_id) if row.customer_id else None
    return {"id": row.id, "hold_no": row.hold_no, "warehouse_id": row.warehouse_id,
            "customer_id": row.customer_id, "customer_name": customer.name if customer else "عميل نقدي",
            "default_sale_mode": row.default_sale_mode, "items": json.loads(row.cart_json or "[]"),
            "invoice_discount": int(row.invoice_discount or 0), "note": row.note,
            "total": int(row.total_snapshot or 0), "created_at": row.created_at.isoformat()}


def list_held_sales(tenant_id: int, employee_id: int | None = None) -> list[dict]:
    query = FoodHeldSale.query.filter_by(tenant_id=tenant_id, status="held")
    if employee_id and not _employee_can(employee_id, "cashier.void_sale"):
        query = query.filter(FoodHeldSale.employee_id == employee_id)
    return [held_sale_dict(row) for row in query.order_by(FoodHeldSale.created_at.desc()).limit(100)]


def restore_held_sale(tenant_id: int, hold_id: int, employee_id: int | None = None) -> dict:
    row = FoodHeldSale.query.filter_by(tenant_id=tenant_id, id=hold_id, status="held").first()
    if not row:
        raise FoodError("الفاتورة المعلقة غير موجودة")
    data = held_sale_dict(row)
    variant_ids = {as_int(item.get("variant_id"), 0) for item in data["items"]}
    data["products"] = [_variant_dict(_variant(tenant_id, variant_id), row.warehouse_id)
                        for variant_id in variant_ids if variant_id]
    validation = validate_cart(tenant_id, {"warehouse_id": row.warehouse_id,
        "invoice_discount": row.invoice_discount, "items": data["items"]}, employee_id)
    data["validation"] = validation
    row.status = "restored"
    _audit_pos(tenant_id, employee_id, "hold_restore", entity_type="held_sale", entity_id=row.id)
    return data


def delete_held_sale(tenant_id: int, hold_id: int, employee_id: int | None = None) -> bool:
    if not _employee_can(employee_id, "cashier.void_sale"):
        raise FoodError("ليس لديك صلاحية إلغاء الفاتورة المعلقة")
    row = FoodHeldSale.query.filter_by(tenant_id=tenant_id, id=hold_id, status="held").first()
    if not row:
        raise FoodError("الفاتورة المعلقة غير موجودة")
    row.status = "cancelled"
    _audit_pos(tenant_id, employee_id, "hold_delete", entity_type="held_sale", entity_id=row.id)
    return True


def branch_stock(tenant_id: int, variant_id: int) -> list[dict]:
    _variant(tenant_id, variant_id)
    rows = (db.session.query(FoodWarehouseStock, Branch)
            .join(Branch, Branch.id == FoodWarehouseStock.warehouse_id)
            .filter(FoodWarehouseStock.tenant_id == tenant_id,
                    FoodWarehouseStock.variant_id == variant_id,
                    Branch.is_active.is_(True)).order_by(Branch.name).all())
    variant = _variant(tenant_id, variant_id)
    return [{"branch_id": branch.id, "branch_name": branch.name,
             "stock_base": int(stock.stock_base or 0),
             "stock_display": decompose_stock(int(stock.stock_base or 0), variant.units)}
            for stock, branch in rows]


def _walk_in_customer(tenant_id: int) -> Customer:
    customer = Customer.query.filter_by(tenant_id=tenant_id, phone="FOOD-WALK-IN").first()
    if not customer:
        customer = Customer(tenant_id=tenant_id, name="زبون نقدي", phone="FOOD-WALK-IN")
        db.session.add(customer)
        db.session.flush()
    return customer


def create_sale(tenant_id: int, payload: dict, employee_id: int | None = None) -> Invoice:
    """Create a complete POS sale inside the caller's transaction.

    Product pricing, unit conversion, stock, customer ownership, discounts and
    payment allocation are always recalculated here. The client only sends IDs
    and cashier intent.
    """
    lines = payload.get("items") or []
    if not isinstance(lines, list) or not lines:
        raise FoodError("السلة فارغة")
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    # Internal service callers from older integrations did not send a key.
    # HTTP checkout always injects one; retain compatibility without making
    # those trusted calls collide with each other.
    if not idempotency_key:
        idempotency_key = f"legacy-{uuid.uuid4()}"
        payload = dict(payload, idempotency_key=idempotency_key)
    if len(idempotency_key) > 120:
        raise FoodError("مفتاح العملية غير صالح")
    fingerprint = _request_fingerprint(payload)
    existing_request = FoodCheckoutRequest.query.filter_by(
        tenant_id=tenant_id, idempotency_key=idempotency_key
    ).first()
    if existing_request:
        if existing_request.request_fingerprint != fingerprint:
            raise FoodError("مفتاح العملية مستخدم لطلب مختلف")
        existing_invoice = db.session.get(Invoice, existing_request.invoice_id)
        if existing_invoice:
            return existing_invoice
        raise FoodError("العملية السابقة لم تكتمل؛ استخدم محاولة دفع جديدة")
    checkout_request = FoodCheckoutRequest(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.session.add(checkout_request)
    db.session.flush()

    customer_id = as_int(payload.get("customer_id"), 0)
    customer = db.session.get(Customer, customer_id) if customer_id else _walk_in_customer(tenant_id)
    if not customer or customer.tenant_id != tenant_id:
        raise FoodError("العميل غير صالح")
    warehouse_id = _valid_warehouse(payload.get("warehouse_id"))
    employee = db.session.get(Employee, employee_id) if employee_id else None
    if employee and employee.default_warehouse_id and employee.role != "admin":
        if int(employee.default_warehouse_id) != int(warehouse_id or 0):
            raise FoodError("هذا المخزن غير مرتبط بالكاشير الحالي")

    invoice_discount = as_int(payload.get("invoice_discount"), 0, minimum=0)

    settings_row = _settings(tenant_id)
    sale_note = str(payload.get("note") or "").strip()
    footer = str(getattr(settings_row, "receipt_footer", None) or "").strip()
    if footer and footer not in sale_note:
        sale_note = f"{sale_note}\n{footer}".strip() if sale_note else footer

    invoice = Invoice(
        tenant_id=tenant_id,
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=employee_id,
        employee_name=None,
        status="تم التسليم",
        payment_status="غير مسدد",
        total=0,
        paid_amount=0,
        source_module="food",
        invoice_no=f"FD-{datetime.utcnow():%Y%m%d%H%M%S%f}",
        branch_id=warehouse_id,
        warehouse_id=warehouse_id,
        note=sale_note[:1000] or None,
        sale_type="cash",
        is_stock_locked=False,
        stock_is_deducted=True,
        stock_deducted_at=datetime.utcnow(),
    )
    db.session.add(invoice)
    db.session.flush()
    grand_total = 0
    for line in lines:
        variant = _variant(tenant_id, as_int(line.get("variant_id"), 0), lock=True)
        unit = _unit(tenant_id, variant.id, as_int(line.get("unit_id"), 0))
        if not unit.can_sell:
            raise FoodError(f"الوحدة غير مفعلة للبيع: {unit.unit_name}")
        line_warehouse_id = _valid_warehouse(line.get("warehouse_id") or warehouse_id)
        if line_warehouse_id != warehouse_id:
            raise FoodError("يجب أن تستخدم جميع مواد الفاتورة مخزن الكاشير نفسه")
        quantity, quantity_base = _sale_quantity(line.get("quantity"), unit.conversion_factor)
        sale_mode = str(line.get("sale_mode") or "RETAIL").upper()
        if sale_mode not in {"RETAIL", "WHOLESALE"}:
            raise FoodError("نوع البيع يجب أن يكون مفرد أو جملة")
        if unit.auto_wholesale and quantity >= int(unit.wholesale_minimum or 1) and int(unit.wholesale_price or 0) > 0:
            sale_mode = "WHOLESALE"
        price = int(unit.wholesale_price if sale_mode == "WHOLESALE" else unit.retail_price)
        if line.get("price") is not None:
            requested_price = as_int(line.get("price"), price, minimum=0)
            if requested_price != price:
                if not _employee_can(employee_id, "cashier.override_price"):
                    raise FoodError("ليس لديك صلاحية تغيير السعر")
                _audit_pos(tenant_id, employee_id, "price_override", entity_type="variant",
                           entity_id=variant.id, details={"original": price, "new": requested_price,
                               "reason": str(line.get("price_override_reason") or "").strip()[:300]})
                price = requested_price
        line_gross = _money_for_quantity(price, quantity)
        manual_discount, discount_type, discount_value = _discount_amount(line, line_gross, employee_id)
        promotion_discount, promotion_name, promotion_id = _promotion_discount(
            tenant_id, variant, unit, quantity, line_gross
        )
        discount = min(line_gross, manual_discount + promotion_discount)
        if manual_discount:
            _audit_pos(tenant_id, employee_id, "item_discount", entity_type="variant",
                       entity_id=variant.id, details={"amount": manual_discount,
                           "type": discount_type, "value": str(discount_value)})
        if promotion_discount:
            _audit_pos(tenant_id, employee_id, "promotion_applied", entity_type="promotion",
                       entity_id=promotion_id, details={"variant_id": variant.id,
                           "amount": promotion_discount, "name": promotion_name})
        line_total = max(0, line_gross - discount)
        before = int(variant.stock_base or 0)
        tracks_stock = bool(variant.profile.track_stock)
        if tracks_stock:
            _ensure_legacy_warehouse_stock(variant, line_warehouse_id)
            available = before
            if line_warehouse_id is not None:
                available = int(_warehouse_stock(tenant_id, variant.id, line_warehouse_id, lock=True).stock_base or 0)
            if available < quantity_base and not _negative_stock_allowed(tenant_id, employee_id):
                raise FoodError(
                    f"المخزون غير كافٍ: {variant.profile.product.name} / {variant.variant_name}. "
                    f"المتاح: {decompose_stock(available, variant.units)}"
                )
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=variant.profile.product_id,
            product_name=variant.profile.product.name,
            price=price,
            # The legacy shared order line is integer-only. Food invoices use
            # the exact decimal snapshot below for display, returns and audit.
            quantity=int(quantity.to_integral_value(rounding=ROUND_HALF_UP)),
            cost=int(variant.average_cost or 0) * int(unit.conversion_factor),
            total=line_total,
            discount_value=discount,
            warehouse_id=line_warehouse_id,
            sale_mode="normal",
        )
        db.session.add(item)
        db.session.flush()
        snapshot = FoodSaleItemSnapshot(
            tenant_id=tenant_id,
            order_item_id=item.id,
            variant_id=variant.id,
            unit_id=unit.id,
            warehouse_id=line_warehouse_id,
            sale_mode=sale_mode,
            product_name_snapshot=variant.profile.product.name,
            variant_name_snapshot=variant.variant_name,
            unit_name_snapshot=unit.unit_name,
            unit_factor_snapshot=unit.conversion_factor,
            unit_price_snapshot=price,
            cost_snapshot=item.cost,
            barcode_snapshot=_primary_barcode(unit),
            quantity_snapshot=quantity,
            discount_snapshot=discount,
            tax_snapshot=0,
            line_total_snapshot=line_total,
            note_snapshot=str(line.get("note") or "").strip()[:500] or None,
            quantity_base=quantity_base,
        )
        db.session.add(snapshot)
        db.session.flush()
        if tracks_stock and variant.profile.track_expiry:
            remaining = quantity_base
            batch_query = FoodExpiryBatch.query.filter(
                FoodExpiryBatch.tenant_id == tenant_id,
                FoodExpiryBatch.variant_id == variant.id,
                FoodExpiryBatch.quantity_base > 0,
                FoodExpiryBatch.expiry_date >= _business_today(),
                FoodExpiryBatch.status == "sellable",
            )
            if line_warehouse_id is not None:
                batch_query = batch_query.filter(or_(
                    FoodExpiryBatch.warehouse_id.is_(None),
                    FoodExpiryBatch.warehouse_id == line_warehouse_id,
                ))
            if (variant.profile.issue_policy or "FEFO").upper() == "FIFO":
                batch_query = batch_query.order_by(FoodExpiryBatch.created_at, FoodExpiryBatch.id)
            else:
                batch_query = batch_query.order_by(FoodExpiryBatch.expiry_date, FoodExpiryBatch.id)
            batches = batch_query.with_for_update().all()
            had_batches = bool(batches)
            for batch in batches:
                available_batch = max(0, int(batch.quantity_base or 0) - int(batch.reserved_quantity_base or 0))
                consumed = min(remaining, available_batch)
                if not consumed:
                    continue
                batch.quantity_base = int(batch.quantity_base or 0) - consumed
                db.session.add(FoodSaleBatchAllocation(
                    tenant_id=tenant_id,
                    sale_snapshot_id=snapshot.id,
                    batch_id=batch.id,
                    quantity_base=consumed,
                ))
                remaining -= consumed
                if remaining <= 0:
                    break
            if had_batches and remaining > 0:
                raise FoodError(f"لا توجد دفعات صالحة كافية للصرف حسب FEFO: {variant.variant_name}")
        if tracks_stock:
            _adjust_warehouse_stock(
                variant, warehouse_id, -quantity_base,
                allow_negative=_negative_stock_allowed(tenant_id, employee_id),
            )
            after = int(variant.stock_base or 0)
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id,
                variant_id=variant.id,
                unit_id=unit.id,
                warehouse_id=line_warehouse_id,
                movement_type="sale",
                quantity_base=-quantity_base,
                quantity_before=before,
                quantity_after=after,
                reference_type="invoice",
                reference_id=invoice.id,
                employee_id=employee_id,
            ))
        grand_total += line_total
    if invoice_discount > grand_total:
        raise FoodError("خصم الفاتورة أكبر من الإجمالي")
    _validate_invoice_discount(invoice_discount, grand_total, employee_id)
    invoice.discount_amount = invoice_discount
    grand_total -= invoice_discount
    invoice.total = grand_total

    raw_payments = payload.get("payments")
    if not isinstance(raw_payments, list) or not raw_payments:
        legacy_type = str(payload.get("payment_type") or "cash").lower()
        if legacy_type == "partial":
            raw_payments = [{"method": "cash", "amount": payload.get("paid_amount") or 0},
                            {"method": "credit", "amount": max(0, grand_total - as_int(payload.get("paid_amount"), 0))}]
        elif legacy_type == "credit":
            raw_payments = [{"method": "credit", "amount": grand_total}]
        else:
            raw_payments = [{"method": legacy_type, "amount": grand_total,
                             "received": payload.get("cash_received") or grand_total}]
    allowed_methods = {"cash", "card", "transfer", "credit"}
    payments = []
    for payment in raw_payments:
        method = str(payment.get("method") or "").lower()
        if method not in allowed_methods:
            raise FoodError("طريقة دفع غير صالحة")
        amount = as_int(payment.get("amount"), 0, minimum=0)
        if amount:
            payments.append({"method": method, "amount": amount,
                             "received": as_int(payment.get("received"), amount, minimum=0)})
    if sum(row["amount"] for row in payments) != grand_total:
        raise FoodError("مجموع الدفعات يجب أن يساوي إجمالي الفاتورة")
    credit_amount = sum(row["amount"] for row in payments if row["method"] == "credit")
    if credit_amount:
        if customer.phone == "FOOD-WALK-IN":
            raise FoodError("يجب اختيار عميل للبيع الآجل")
        if not _employee_can(employee_id, "cashier.sell_credit"):
            raise FoodError("ليس لديك صلاحية البيع الآجل")
        profile = FoodCustomerProfile.query.filter_by(
            tenant_id=tenant_id, customer_id=customer.id
        ).first()
        if profile and profile.credit_limit is not None:
            projected = _customer_debt(tenant_id, customer.id) + credit_amount
            if projected > int(profile.credit_limit) and not _employee_can(employee_id, "cashier.override_credit_limit"):
                raise FoodError("سيتم تجاوز حد ائتمان العميل")
            if projected > int(profile.credit_limit):
                _audit_pos(tenant_id, employee_id, "credit_limit_override",
                           entity_type="customer", entity_id=customer.id,
                           details={"credit_limit": profile.credit_limit, "projected": projected})
    paid_amount = sum(row["amount"] for row in payments if row["method"] != "credit")
    invoice.paid_amount = paid_amount
    invoice.payment_status = "مسدد" if invoice.paid_amount >= grand_total else ("جزئي" if invoice.paid_amount else "غير مسدد")
    invoice.sale_type = "credit" if credit_amount == grand_total else ("partial" if credit_amount else "cash")
    for payment in payments:
        if payment["method"] == "credit":
            continue
        if payment["method"] == "cash" and payment["received"] < payment["amount"]:
            raise FoodError("المبلغ المستلم أقل من الدفعة النقدية")
        db.session.add(InvoicePaymentLedger(
            tenant_id=tenant_id,
            branch_id=warehouse_id,
            invoice_id=invoice.id,
            source_module="food",
            payment_method=payment["method"],
            amount_delta=payment["amount"],
            note=(f"مستلم {payment['received']}، باقي {payment['received'] - payment['amount']}"
                  if payment["method"] == "cash" else None),
        ))
    if invoice_discount:
        _audit_pos(tenant_id, employee_id, "invoice_discount", entity_type="invoice",
                   entity_id=invoice.id, details={"amount": invoice_discount})
    _audit_pos(tenant_id, employee_id, "sale_complete", entity_type="invoice",
               entity_id=invoice.id, details={"total": grand_total, "payments": payments})
    checkout_request.invoice_id = invoice.id
    db.session.flush()
    return invoice


def search_sales_for_return(tenant_id: int, term="", limit=30) -> list[dict]:
    query = Invoice.query.outerjoin(Customer).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي",)),
    )
    term = str(term or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(Invoice.invoice_no.ilike(like), Invoice.barcode.ilike(like),
                                 Customer.name.ilike(like), Customer.phone.ilike(like)))
    rows = query.order_by(Invoice.created_at.desc()).limit(min(100, max(1, as_int(limit, 30)))).all()
    result = []
    for invoice in rows:
        line_rows = []
        for snapshot in (FoodSaleItemSnapshot.query.join(OrderItem)
                         .filter(FoodSaleItemSnapshot.tenant_id == tenant_id,
                                 OrderItem.invoice_id == invoice.id).all()):
            returned = db.session.query(func.coalesce(func.sum(FoodSaleReturnLine.quantity), 0)).filter(
                FoodSaleReturnLine.tenant_id == tenant_id,
                FoodSaleReturnLine.sale_snapshot_id == snapshot.id,
            ).scalar()
            original_qty = Decimal(snapshot.quantity_snapshot or snapshot.quantity_base or 0)
            line_rows.append({
                "snapshot_id": snapshot.id,
                "product_name": snapshot.product_name_snapshot or snapshot.order_item.product_name,
                "variant_name": snapshot.variant_name_snapshot,
                "unit_name": snapshot.unit_name_snapshot,
                "quantity": str(original_qty), "returned_quantity": str(returned or 0),
                "returnable_quantity": str(max(Decimal("0"), original_qty - Decimal(returned or 0))),
                "unit_price": int(snapshot.unit_price_snapshot or 0),
            })
        result.append({"id": invoice.id, "invoice_no": invoice.invoice_no,
                       "customer_name": invoice.customer_name, "total": int(invoice.total or 0),
                       "paid": int(invoice.paid_amount or 0), "created_at": invoice.created_at.isoformat(),
                       "items": line_rows})
    return result


def create_sale_return(tenant_id: int, payload: dict, employee_id: int | None = None) -> FoodSaleReturn:
    if not _employee_can(employee_id, "cashier.return"):
        raise FoodError("ليس لديك صلاحية تنفيذ المرتجع")
    key = str(payload.get("idempotency_key") or "").strip()
    if not key:
        raise FoodError("مفتاح عملية المرتجع مطلوب")
    existing = FoodSaleReturn.query.filter_by(tenant_id=tenant_id, idempotency_key=key).first()
    if existing:
        return existing
    invoice = Invoice.query.filter_by(
        tenant_id=tenant_id, id=as_int(payload.get("invoice_id"), 0), source_module="food"
    ).with_for_update().first()
    if not invoice or invoice.status == "ملغي":
        raise FoodError("الفاتورة غير صالحة للمرتجع")
    lines = payload.get("items") or []
    if not lines:
        raise FoodError("اختر مادة واحدة على الأقل للمرتجع")
    refund_method = str(payload.get("refund_method") or "cash").lower()
    if refund_method not in {"cash", "card", "transfer", "credit"}:
        raise FoodError("طريقة استرداد غير صالحة")
    sale_return = FoodSaleReturn(
        tenant_id=tenant_id, return_no=f"FR-{datetime.utcnow():%Y%m%d%H%M%S%f}",
        idempotency_key=key, invoice_id=invoice.id,
        warehouse_id=_valid_warehouse(payload.get("warehouse_id") or invoice.warehouse_id),
        employee_id=employee_id, refund_method=refund_method,
        reason=str(payload.get("reason") or "").strip()[:1000] or None,
    )
    db.session.add(sale_return)
    db.session.flush()
    total = 0
    for raw in lines:
        snapshot = FoodSaleItemSnapshot.query.filter_by(
            tenant_id=tenant_id, id=as_int(raw.get("snapshot_id"), 0)
        ).with_for_update().first()
        if not snapshot or snapshot.order_item.invoice_id != invoice.id:
            raise FoodError("سطر المرتجع لا ينتمي إلى الفاتورة")
        quantity = as_decimal(raw.get("quantity"), Decimal("0"), minimum=Decimal("0.001"))
        returned = Decimal(db.session.query(func.coalesce(func.sum(FoodSaleReturnLine.quantity), 0)).filter(
            FoodSaleReturnLine.tenant_id == tenant_id,
            FoodSaleReturnLine.sale_snapshot_id == snapshot.id,
        ).scalar() or 0)
        original = Decimal(snapshot.quantity_snapshot or snapshot.order_item.quantity or 0)
        if returned + quantity > original:
            raise FoodError("كمية المرتجع أكبر من الكمية المتبقية")
        factor = Decimal(snapshot.unit_factor_snapshot or 1)
        quantity_base = quantity * factor
        amount = int((Decimal(snapshot.line_total_snapshot or snapshot.order_item.total or 0)
                      * quantity / original).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return_line = FoodSaleReturnLine(
            tenant_id=tenant_id, return_id=sale_return.id, sale_snapshot_id=snapshot.id,
            quantity=quantity, quantity_base=quantity_base, amount=amount,
        )
        db.session.add(return_line)
        db.session.flush()
        variant = _variant(tenant_id, snapshot.variant_id, lock=True)
        if variant.profile.track_stock:
            warehouse_id = sale_return.warehouse_id or snapshot.warehouse_id
            before = int(variant.stock_base or 0)
            _adjust_warehouse_stock(variant, warehouse_id, int(quantity_base))
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id, variant_id=variant.id, unit_id=snapshot.unit_id,
                warehouse_id=warehouse_id, movement_type="sale_return",
                quantity_base=int(quantity_base), quantity_before=before,
                quantity_after=int(variant.stock_base or 0), reference_type="food_sale_return",
                reference_id=sale_return.id, note=sale_return.reason, employee_id=employee_id,
            ))
            remaining_base = int(quantity_base)
            for allocation in FoodSaleBatchAllocation.query.filter_by(
                tenant_id=tenant_id, sale_snapshot_id=snapshot.id
            ).order_by(FoodSaleBatchAllocation.id).all():
                already = db.session.query(func.coalesce(func.sum(FoodSaleReturnBatchAllocation.quantity_base), 0)).join(
                    FoodSaleReturnLine, FoodSaleReturnLine.id == FoodSaleReturnBatchAllocation.return_line_id
                ).filter(FoodSaleReturnLine.sale_snapshot_id == snapshot.id,
                         FoodSaleReturnBatchAllocation.batch_id == allocation.batch_id).scalar()
                room = max(0, int(allocation.quantity_base or 0) - int(already or 0))
                restore = min(room, remaining_base)
                if not restore:
                    continue
                batch = db.session.get(FoodExpiryBatch, allocation.batch_id)
                if batch and int(batch.tenant_id) == tenant_id:
                    batch.quantity_base = int(batch.quantity_base or 0) + restore
                    db.session.add(FoodSaleReturnBatchAllocation(
                        tenant_id=tenant_id, return_line_id=return_line.id,
                        batch_id=batch.id, quantity_base=restore,
                    ))
                remaining_base -= restore
                if remaining_base <= 0:
                    break
        total += amount
    sale_return.total = total
    if refund_method != "credit" and total:
        refundable = min(total, int(invoice.paid_amount or 0))
        if refundable:
            db.session.add(InvoicePaymentLedger(
                tenant_id=tenant_id, branch_id=sale_return.warehouse_id,
                invoice_id=invoice.id, source_module="food_return",
                payment_method=refund_method, amount_delta=-refundable,
                note=f"مرتجع {sale_return.return_no}",
            ))
            invoice.paid_amount = max(0, int(invoice.paid_amount or 0) - refundable)
    invoice_snapshots = (FoodSaleItemSnapshot.query.join(OrderItem)
                         .filter(FoodSaleItemSnapshot.tenant_id == tenant_id,
                                 OrderItem.invoice_id == invoice.id).all())
    all_returned = bool(invoice_snapshots)
    for snapshot in invoice_snapshots:
        returned_qty = Decimal(db.session.query(
            func.coalesce(func.sum(FoodSaleReturnLine.quantity), 0)
        ).filter(FoodSaleReturnLine.tenant_id == tenant_id,
                 FoodSaleReturnLine.sale_snapshot_id == snapshot.id).scalar() or 0)
        original_qty = Decimal(snapshot.quantity_snapshot or snapshot.order_item.quantity or 0)
        if returned_qty < original_qty:
            all_returned = False
            break
    if all_returned:
        invoice.status = "راجع"
        invoice.stock_is_deducted = False
    _audit_pos(tenant_id, employee_id, "sale_return", entity_type="food_sale_return",
               entity_id=sale_return.id, details={"invoice_id": invoice.id, "total": total})
    db.session.flush()
    return sale_return


def restore_sale_stock(order: Invoice, employee_id: int | None = None) -> bool:
    """Restore a food invoice to variant base stock exactly once.

    The invoice-level stock flag is claimed in the same transaction as the
    variant movements, so a retry cannot return the same quantities twice.
    """
    if str(getattr(order, "source_module", "") or "").strip().lower() != "food":
        raise FoodError("الفاتورة ليست من مساحة المواد الغذائية")
    if not bool(getattr(order, "stock_is_deducted", False)):
        return False

    tenant_id = int(order.tenant_id)
    snapshots = (
        FoodSaleItemSnapshot.query.join(
            OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id
        )
        .filter(
            FoodSaleItemSnapshot.tenant_id == tenant_id,
            OrderItem.invoice_id == int(order.id),
        )
        .order_by(FoodSaleItemSnapshot.id)
        .all()
    )
    if not snapshots:
        raise FoodError("لا توجد تفاصيل مخزون أغذية قابلة للاسترجاع لهذه الفاتورة")

    now = datetime.utcnow()
    claimed = (
        db.session.query(Invoice)
        .filter(
            Invoice.id == int(order.id),
            Invoice.tenant_id == tenant_id,
            Invoice.source_module == "food",
            Invoice.stock_is_deducted.is_(True),
        )
        .update(
            {Invoice.stock_is_deducted: False, Invoice.stock_restored_at: now},
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.session.expire(order)
        return False

    for snapshot in snapshots:
        variant = _variant(tenant_id, int(snapshot.variant_id), lock=True)
        if not variant.profile.track_stock:
            continue
        quantity_base = int(snapshot.quantity_base or 0)
        before = int(variant.stock_base or 0)
        _ensure_legacy_warehouse_stock(variant, snapshot.warehouse_id)
        _adjust_warehouse_stock(variant, snapshot.warehouse_id, quantity_base)
        after = int(variant.stock_base or 0)
        for allocation in FoodSaleBatchAllocation.query.filter_by(
            tenant_id=tenant_id, sale_snapshot_id=snapshot.id
        ).with_for_update().all():
            batch = db.session.get(FoodExpiryBatch, allocation.batch_id)
            if batch and int(batch.tenant_id) == tenant_id:
                batch.quantity_base = int(batch.quantity_base or 0) + int(allocation.quantity_base or 0)
        db.session.add(FoodInventoryMovement(
            tenant_id=tenant_id,
            variant_id=variant.id,
            unit_id=snapshot.unit_id,
            warehouse_id=snapshot.warehouse_id,
            movement_type="sale_restore",
            quantity_base=quantity_base,
            quantity_before=before,
            quantity_after=after,
            reference_type="invoice",
            reference_id=int(order.id),
            note="إلغاء أو ترجيع فاتورة أغذية",
            employee_id=employee_id,
        ))

    db.session.flush()
    db.session.expire(order)
    return True


def apply_inventory_count(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    """Apply an approved physical count using base-unit quantities only."""
    lines = payload.get("items") or []
    if not isinstance(lines, list) or not lines:
        raise FoodError("أدخل نتيجة جرد واحدة على الأقل")
    note = str(payload.get("note") or "جرد يدوي").strip()[:500] or "جرد يدوي"
    seen: set[int] = set()
    changed = 0
    total_difference = 0
    results = []
    for line in lines:
        variant_id = as_int(line.get("variant_id"), 0, minimum=1)
        if variant_id in seen:
            raise FoodError("لا يمكن تكرار النوع نفسه في الجرد")
        seen.add(variant_id)
        actual = as_int(line.get("actual_base"), 0, minimum=0)
        variant = _variant(tenant_id, variant_id, lock=True)
        if not variant.profile.track_stock:
            raise FoodError(f"المادة لا تستخدم تتبّع المخزون: {variant.profile.product.name}")
        warehouse_id = _valid_warehouse(line.get("warehouse_id")) if line.get("warehouse_id") else None
        _ensure_legacy_warehouse_stock(variant, warehouse_id)
        before = (
            int(_warehouse_stock(tenant_id, variant.id, warehouse_id, lock=True).stock_base or 0)
            if warehouse_id is not None else int(variant.stock_base or 0)
        )
        difference = actual - before
        if difference:
            if variant.profile.track_expiry:
                if difference < 0:
                    remaining_reduction = abs(difference)
                    batches = FoodExpiryBatch.query.filter(
                        FoodExpiryBatch.tenant_id == tenant_id,
                        FoodExpiryBatch.variant_id == variant.id,
                        FoodExpiryBatch.quantity_base > 0,
                    ).order_by(FoodExpiryBatch.expiry_date, FoodExpiryBatch.id).with_for_update().all()
                    if warehouse_id is not None:
                        batches = [batch for batch in batches if batch.warehouse_id in (None, warehouse_id)]
                    for batch in batches:
                        reduced = min(remaining_reduction, int(batch.quantity_base or 0))
                        batch.quantity_base = int(batch.quantity_base or 0) - reduced
                        remaining_reduction -= reduced
                        if remaining_reduction <= 0:
                            break
                else:
                    try:
                        counted_expiry = date.fromisoformat(str(line.get("expiry_date") or ""))
                    except ValueError as exc:
                        raise FoodError("حدد صلاحية للزيادة في المادة التي تتبع الصلاحية") from exc
                    db.session.add(FoodExpiryBatch(
                        tenant_id=tenant_id,
                        variant_id=variant.id,
                        warehouse_id=warehouse_id,
                        batch_number="تسوية جرد",
                        expiry_date=counted_expiry,
                        quantity_base=difference,
                    ))
            if warehouse_id is None:
                variant.stock_base = actual
            else:
                warehouse_stock = _warehouse_stock(tenant_id, variant.id, warehouse_id, lock=True)
                warehouse_stock.stock_base = actual
                _sync_variant_stock(variant)
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id,
                variant_id=variant.id,
                warehouse_id=warehouse_id,
                movement_type="inventory_count",
                quantity_base=difference,
                quantity_before=before,
                quantity_after=actual,
                reference_type="inventory_count",
                note=note,
                employee_id=employee_id,
            ))
            changed += 1
            total_difference += difference
        results.append({
            "variant_id": variant.id,
            "before": before,
            "actual": actual,
            "difference": difference,
        })
    db.session.flush()
    return {"counted": len(results), "changed": changed, "difference": total_difference, "items": results}


def create_purchase(tenant_id: int, payload: dict, employee_id: int | None = None) -> Purchase:
    from modules.food.purchase_service import check_duplicate_supplier_invoice

    supplier = db.session.get(Supplier, as_int(payload.get("supplier_id"), 0))
    if not supplier:
        raise FoodError("اختر المورد")
    lines = payload.get("items") or []
    if not lines:
        raise FoodError("فاتورة الشراء فارغة")
    warehouse_id = _valid_warehouse(payload.get("warehouse_id"))
    first_variant = _variant(tenant_id, as_int(lines[0].get("variant_id"), 0))
    purchase_date = _business_today()
    if payload.get("purchase_date"):
        try:
            purchase_date = date.fromisoformat(str(payload.get("purchase_date")))
        except ValueError as exc:
            raise FoodError("تاريخ فاتورة الشراء غير صالح") from exc

    supplier_invoice_no = str(payload.get("supplier_invoice_no") or "").strip() or None
    if supplier_invoice_no:
        dup = check_duplicate_supplier_invoice(tenant_id, supplier.id, supplier_invoice_no)
        if dup:
            raise FoodError(
                f"هذه الفاتورة مسجلة مسبقاً لهذا المورد ({dup.get('invoice_no') or dup['id']})."
            )

    save_as_draft = bool(payload.get("draft") or payload.get("is_draft") or payload.get("save_as_draft"))
    confirm = not save_as_draft
    payment_mode = str(
        payload.get("payment_type") or payload.get("payment_mode") or payload.get("purchase_mode") or "cash"
    ).strip().lower()
    if payment_mode not in {"cash", "credit", "partial", "mixed", "card", "transfer"}:
        payment_mode = "cash"

    purchase = Purchase(
        supplier_id=supplier.id,
        product_id=first_variant.profile.product_id,
        quantity=0,
        price=0,
        total=0,
        invoice_no=f"FP-{datetime.utcnow():%Y%m%d%H%M%S%f}",
        supplier_invoice_no=supplier_invoice_no,
        purchase_mode=payment_mode,
        status="draft" if save_as_draft else "confirmed",
        is_draft=save_as_draft,
        source_module="food",
        warehouse_id=warehouse_id,
        branch_id=warehouse_id,
        stock_applied=False,
        notes=str(payload.get("notes") or payload.get("note") or "").strip() or None,
        created_by_employee_id=employee_id,
        sub_total=0,
        grand_total=0,
        paid_total=0,
        remaining_total=0,
        purchase_date=purchase_date,
        currency=str(payload.get("currency") or "IQD").strip().upper() or "IQD",
    )
    db.session.add(purchase)
    db.session.flush()

    parsed_lines = []
    subtotal = 0
    for line in lines:
        variant = _variant(tenant_id, as_int(line.get("variant_id"), 0), lock=confirm)
        unit = _unit(tenant_id, variant.id, as_int(line.get("unit_id"), 0))
        if not unit.can_purchase:
            raise FoodError(f"الوحدة غير مفعلة للشراء: {unit.unit_name}")
        line_warehouse_id = _valid_warehouse(line.get("warehouse_id") or warehouse_id)
        quantity = as_int(line.get("quantity"), 0, minimum=1)
        bonus = as_int(line.get("bonus") or line.get("bonus_quantity"), 0, minimum=0)
        unit_cost = as_int(line.get("purchase_price"), int(unit.purchase_price or 0), minimum=0)
        discount = as_int(line.get("discount"), 0, minimum=0)
        line_total = max(0, quantity * unit_cost - discount)
        quantity_base = (quantity + bonus) * int(unit.conversion_factor)
        expiry = _parse_date(
            line.get("expiry_date"), "تاريخ الصلاحية",
            required=bool(variant.profile.track_expiry) and confirm,
        )
        production = _parse_date(line.get("production_date"), "تاريخ الإنتاج")
        if production and expiry and expiry <= production:
            raise FoodError("تاريخ الانتهاء يجب أن يكون بعد تاريخ الإنتاج")
        item = PurchaseItem(
            purchase_id=purchase.id,
            product_id=variant.profile.product_id,
            quantity=quantity,
            unit_cost_before_discount=unit_cost,
            discount_value=discount,
            final_unit_cost=max(0, unit_cost - (discount // quantity)),
            line_total=line_total,
        )
        db.session.add(item)
        db.session.flush()
        db.session.add(FoodPurchaseItemSnapshot(
            tenant_id=tenant_id,
            purchase_item_id=item.id,
            variant_id=variant.id,
            unit_id=unit.id,
            warehouse_id=line_warehouse_id,
            variant_name_snapshot=variant.variant_name,
            unit_name_snapshot=unit.unit_name,
            unit_factor_snapshot=unit.conversion_factor,
            unit_price_snapshot=unit_cost,
            barcode_snapshot=_primary_barcode(unit) or str(line.get("barcode") or "").strip() or None,
            bonus_quantity=bonus,
            expiry_date=expiry,
            quantity_base=quantity_base,
        ))
        parsed_lines.append({
            "item": item,
            "variant": variant,
            "unit": unit,
            "line_warehouse_id": line_warehouse_id,
            "quantity": quantity,
            "bonus": bonus,
            "unit_cost": unit_cost,
            "line_total": line_total,
            "quantity_base": quantity_base,
            "expiry": expiry,
            "production": production,
            "batch_number": str(line.get("batch_number") or "").strip() or None,
        })
        subtotal += line_total

    purchase.quantity = sum(row["quantity"] for row in parsed_lines)
    purchase.price = parsed_lines[0]["unit_cost"] if parsed_lines else 0
    purchase.total = subtotal
    purchase.sub_total = subtotal
    purchase.discount_value = as_int(
        payload.get("discount") or payload.get("discount_value"), 0, minimum=0
    )
    shipping_extra = as_int(
        payload.get("shipping_extra") or payload.get("shipping") or payload.get("transport"), 0, minimum=0
    )
    customs_extra = as_int(payload.get("customs_extra") or payload.get("customs"), 0, minimum=0)
    other_extra = as_int(
        payload.get("other_extra") or payload.get("expenses") or payload.get("other"), 0, minimum=0
    )
    purchase.shipping_extra = shipping_extra
    purchase.customs_extra = customs_extra
    purchase.other_extra = other_extra
    extras = shipping_extra + customs_extra + other_extra
    purchase.grand_total = max(0, subtotal - purchase.discount_value + extras)

    # Allocate landed extras onto line final unit cost for inventory costing.
    if extras > 0 and subtotal > 0 and parsed_lines:
        allocated = 0
        for idx, row in enumerate(parsed_lines):
            share = (
                extras - allocated
                if idx == len(parsed_lines) - 1
                else int(round(extras * (row["line_total"] / subtotal)))
            )
            if idx < len(parsed_lines) - 1:
                allocated += share
            landed_line = row["line_total"] + share
            qty = max(1, row["quantity"])
            row["item"].final_unit_cost = int(round(landed_line / qty))
            row["landed_line_total"] = landed_line
    else:
        for row in parsed_lines:
            row["landed_line_total"] = row["line_total"]

    if payment_mode == "cash":
        paid = purchase.grand_total
    elif payment_mode == "credit":
        paid = 0
    else:
        paid = as_int(payload.get("paid_amount") or payload.get("paid_total"), 0, minimum=0)
    purchase.paid_total = min(purchase.grand_total, paid)
    purchase.remaining_total = purchase.grand_total - purchase.paid_total

    if confirm:
        for row in parsed_lines:
            variant = row["variant"]
            unit = row["unit"]
            quantity_base = row["quantity_base"]
            line_warehouse_id = row["line_warehouse_id"]
            unit_cost = row["unit_cost"]
            quantity = row["quantity"]
            bonus = row["bonus"]
            landed_line_total = row["landed_line_total"]
            before = int(variant.stock_base or 0)
            after = before + quantity_base if variant.profile.track_stock else before
            if variant.profile.track_stock:
                old_value = before * int(variant.average_cost or 0)
                # Spread paid+landed cost across all received base units (incl. bonus).
                incoming_base_cost = landed_line_total // max(1, quantity_base)
                variant.average_cost = (old_value + quantity_base * incoming_base_cost) // max(1, after)
                _ensure_legacy_warehouse_stock(variant, line_warehouse_id)
                _adjust_warehouse_stock(variant, line_warehouse_id, quantity_base)
                after = int(variant.stock_base or 0)
            unit.purchase_price = unit_cost
            if variant.profile.track_stock:
                db.session.add(FoodInventoryMovement(
                    tenant_id=tenant_id,
                    variant_id=variant.id,
                    unit_id=unit.id,
                    warehouse_id=line_warehouse_id,
                    movement_type="purchase",
                    quantity_base=quantity_base,
                    quantity_before=before,
                    quantity_after=after,
                    reference_type="purchase",
                    reference_id=purchase.id,
                    employee_id=employee_id,
                ))
            if row["expiry"] and variant.profile.track_stock:
                db.session.add(FoodExpiryBatch(
                    tenant_id=tenant_id,
                    variant_id=variant.id,
                    warehouse_id=line_warehouse_id,
                    received_unit_id=unit.id,
                    batch_number=row["batch_number"],
                    production_date=row["production"],
                    expiry_date=row["expiry"],
                    quantity_base=quantity_base,
                    received_quantity=quantity + bonus,
                    unit_factor_snapshot=unit.conversion_factor,
                    unit_cost_snapshot=int(row["item"].final_unit_cost or unit_cost),
                    supplier_id=supplier.id,
                    purchase_id=purchase.id,
                    status="sellable",
                ))
        purchase.stock_applied = True
        supplier.total_debt = int(supplier.total_debt or 0) + purchase.grand_total
        supplier.total_paid = int(supplier.total_paid or 0) + purchase.paid_total
        if purchase.paid_total:
            db.session.add(SupplierPayment(
                supplier_id=supplier.id,
                tenant_id=tenant_id,
                amount=purchase.paid_total,
                source_module="food",
                note=f"دفعة فاتورة {purchase.invoice_no}",
                payment_method="cash" if payment_mode in {"cash", "partial", "mixed"} else payment_mode,
            ))

    db.session.flush()
    return purchase


def reverse_purchase(purchase: Purchase, reason: str, *, hard_delete: bool = False) -> bool:
    """Reverse a food purchase from variant stock and supplier balances once."""
    if str(getattr(purchase, "source_module", "") or "").strip().lower() != "food":
        raise FoodError("الفاتورة ليست من مشتريات المواد الغذائية")
    if not bool(getattr(purchase, "stock_applied", False)):
        if hard_delete:
            item_ids = [int(row.id) for row in PurchaseItem.query.filter_by(purchase_id=purchase.id).all()]
            if item_ids:
                FoodPurchaseItemSnapshot.query.filter(
                    FoodPurchaseItemSnapshot.purchase_item_id.in_(item_ids)
                ).delete(synchronize_session=False)
        return False

    snapshots = FoodPurchaseItemSnapshot.query.join(
        PurchaseItem, PurchaseItem.id == FoodPurchaseItemSnapshot.purchase_item_id
    ).filter(PurchaseItem.purchase_id == int(purchase.id)).order_by(FoodPurchaseItemSnapshot.id).all()
    if not snapshots:
        raise FoodError("لا توجد تفاصيل مخزون أغذية قابلة لعكس فاتورة الشراء")
    tenant_id = int(snapshots[0].tenant_id)
    for snapshot in snapshots:
        if int(snapshot.tenant_id) != tenant_id:
            raise FoodError("بيانات فاتورة الشراء غير متطابقة مع الشركة")
        variant = _variant(tenant_id, int(snapshot.variant_id), lock=True)
        if not variant.profile.track_stock:
            continue
        quantity_base = int(snapshot.quantity_base or 0)
        before = int(variant.stock_base or 0)
        _ensure_legacy_warehouse_stock(variant, snapshot.warehouse_id)
        available_stock = before
        if snapshot.warehouse_id is not None:
            available_stock = int(_warehouse_stock(
                tenant_id, variant.id, snapshot.warehouse_id, lock=True
            ).stock_base or 0)
        if available_stock < quantity_base:
            raise FoodError(
                f"لا يمكن {reason}: جزء من مخزون {variant.variant_name} بيع أو خرج بعد الشراء"
            )
        if snapshot.expiry_date:
            batches = FoodExpiryBatch.query.filter(
                FoodExpiryBatch.tenant_id == tenant_id,
                FoodExpiryBatch.variant_id == variant.id,
                FoodExpiryBatch.expiry_date == snapshot.expiry_date,
                FoodExpiryBatch.quantity_base > 0,
            ).order_by(FoodExpiryBatch.id.desc()).with_for_update().all()
            purchase_batches = [row for row in batches if row.purchase_id == int(purchase.id)]
            batches = purchase_batches or [
                row for row in batches if row.warehouse_id in (None, snapshot.warehouse_id)
            ]
            available = sum(int(row.quantity_base or 0) for row in batches)
            if available < quantity_base:
                raise FoodError(
                    f"لا يمكن {reason}: دفعة الصلاحية الخاصة بـ {variant.variant_name} استُهلكت"
                )
            remaining = quantity_base
            for batch in batches:
                reduced = min(remaining, int(batch.quantity_base or 0))
                batch.quantity_base = int(batch.quantity_base or 0) - reduced
                remaining -= reduced
                if remaining <= 0:
                    break
        after = before - quantity_base
        purchase_item = db.session.get(PurchaseItem, snapshot.purchase_item_id)
        base_cost = (
            int(purchase_item.final_unit_cost or 0) // max(1, int(snapshot.unit_factor_snapshot or 1))
            if purchase_item else 0
        )
        remaining_value = max(0, before * int(variant.average_cost or 0) - quantity_base * base_cost)
        variant.average_cost = remaining_value // after if after else 0
        _adjust_warehouse_stock(variant, snapshot.warehouse_id, -quantity_base)
        after = int(variant.stock_base or 0)
        db.session.add(FoodInventoryMovement(
            tenant_id=tenant_id,
            variant_id=variant.id,
            unit_id=snapshot.unit_id,
            warehouse_id=snapshot.warehouse_id,
            movement_type="purchase_reverse",
            quantity_base=-quantity_base,
            quantity_before=before,
            quantity_after=after,
            reference_type="purchase",
            reference_id=int(purchase.id),
            note=reason,
        ))

    supplier = db.session.get(Supplier, purchase.supplier_id)
    if supplier:
        supplier.total_debt = max(0, int(supplier.total_debt or 0) - int(purchase.grand_total or purchase.total or 0))
        supplier.total_paid = max(0, int(supplier.total_paid or 0) - int(purchase.paid_total or 0))
        SupplierPayment.query.filter_by(
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            source_module="food",
            note=f"دفعة فاتورة {purchase.invoice_no}",
        ).delete(synchronize_session=False)
    purchase.stock_applied = False
    if hard_delete:
        snapshot_ids = [int(row.id) for row in snapshots]
        if snapshot_ids:
            db.session.execute(
                FoodPurchaseItemSnapshot.__table__.delete().where(
                    FoodPurchaseItemSnapshot.id.in_(snapshot_ids)
                )
            )
            for row in snapshots:
                if inspect(row).persistent:
                    db.session.expunge(row)
        movement_rows = FoodInventoryMovement.query.filter_by(
            reference_type="purchase", reference_id=int(purchase.id)
        ).all()
        if movement_rows:
            db.session.execute(
                FoodInventoryMovement.__table__.delete().where(
                    FoodInventoryMovement.id.in_([row.id for row in movement_rows])
                )
            )
            for row in movement_rows:
                if inspect(row).persistent:
                    db.session.expunge(row)
    db.session.flush()
    return True


def inventory(tenant_id: int) -> dict:
    products = list_products(tenant_id)
    movements = FoodInventoryMovement.query.filter_by(tenant_id=tenant_id).order_by(
        FoodInventoryMovement.created_at.desc()
    ).limit(200).all()
    employee_ids = {row.employee_id for row in movements if row.employee_id}
    employee_names = {
        row.id: row.name for row in Employee.query.filter(Employee.id.in_(employee_ids or [-1])).all()
    }
    variant_map = {row["id"]: row for row in products}
    batches = FoodExpiryBatch.query.filter(
        FoodExpiryBatch.tenant_id == tenant_id,
        FoodExpiryBatch.quantity_base > 0,
    ).order_by(FoodExpiryBatch.expiry_date).limit(100).all()
    warehouse_ids = {
        warehouse_id for warehouse_id in
        [*(row.warehouse_id for row in movements), *(row.warehouse_id for row in batches)]
        if warehouse_id
    }
    warehouse_names = {
        row.id: row.name for row in Branch.query.filter(
            Branch.id.in_(warehouse_ids or [-1]),
        ).all()
    }
    today = _business_today()

    def expiry_status(expiry_date: date) -> str:
        days = (expiry_date - today).days
        if days < 0:
            return "expired"
        if days == 0:
            return "today"
        if days <= 7:
            return "within_7"
        if days <= 30:
            return "within_30"
        return "healthy"
    return {
        "products": products,
        "low_stock": [
            row for row in products
            if row["track_stock"] and row["stock_base"] <= row["minimum_stock"]
        ],
        "movements": [{
            "id": row.id,
            "variant_id": row.variant_id,
            "product": (variant_map.get(row.variant_id) or {}).get("product_name", "—"),
            "variant": (variant_map.get(row.variant_id) or {}).get("variant_name", "—"),
            "type": row.movement_type,
            "quantity_base": row.quantity_base,
            "before": row.quantity_before,
            "after": row.quantity_after,
            "reference_type": row.reference_type,
            "reference_id": row.reference_id,
            "warehouse": warehouse_names.get(row.warehouse_id, "المخزون العام"),
            "note": row.note,
            "employee": employee_names.get(row.employee_id, "—"),
            "created_at": row.created_at.isoformat(),
        } for row in movements],
        "expiry": [{
            "id": row.id,
            "variant_id": row.variant_id,
            "product": (variant_map.get(row.variant_id) or {}).get("product_name", "—"),
            "variant": (variant_map.get(row.variant_id) or {}).get("variant_name", "—"),
            "batch": row.batch_number,
            "warehouse": warehouse_names.get(row.warehouse_id, "المخزون العام"),
            "production_date": row.production_date.isoformat() if row.production_date else None,
            "quantity_base": row.quantity_base,
            "expiry_date": row.expiry_date.isoformat(),
            "days_left": (row.expiry_date - today).days,
            "status": expiry_status(row.expiry_date),
        } for row in batches],
    }


def _period_sales_split(tenant_id: int, start_dt: datetime, end_dt: datetime) -> dict:
    invoices = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.source_module == "food",
        Invoice.created_at >= start_dt,
        Invoice.created_at < end_dt,
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    returns = FoodSaleReturn.query.filter(
        FoodSaleReturn.tenant_id == tenant_id,
        FoodSaleReturn.created_at >= start_dt,
        FoodSaleReturn.created_at < end_dt,
    ).all()
    partial_returns = [
        row for row in returns
        if (inv := db.session.get(Invoice, row.invoice_id)) and inv.status != "راجع"
    ]
    invoice_ids = [row.id for row in invoices]
    modes_by_invoice: dict[int, set] = {row.id: set() for row in invoices}
    if invoice_ids:
        for invoice_id, mode in db.session.query(OrderItem.invoice_id, FoodSaleItemSnapshot.sale_mode).join(
            FoodSaleItemSnapshot, FoodSaleItemSnapshot.order_item_id == OrderItem.id,
        ).filter(OrderItem.invoice_id.in_(invoice_ids)).all():
            modes_by_invoice.setdefault(invoice_id, set()).add(mode)
    retail = wholesale = mixed = 0
    for invoice in invoices:
        amount = int(invoice.total or 0)
        modes = modes_by_invoice.get(invoice.id) or set()
        if modes == {"RETAIL"}:
            retail += amount
        elif modes == {"WHOLESALE"}:
            wholesale += amount
        else:
            mixed += amount
    return_modes: dict[int, set] = {}
    return_invoice_ids = {row.invoice_id for row in partial_returns}
    if return_invoice_ids:
        for invoice_id, mode in db.session.query(OrderItem.invoice_id, FoodSaleItemSnapshot.sale_mode).join(
            FoodSaleItemSnapshot, FoodSaleItemSnapshot.order_item_id == OrderItem.id,
        ).filter(OrderItem.invoice_id.in_(return_invoice_ids)).all():
            return_modes.setdefault(invoice_id, set()).add(mode)
    for sale_return in partial_returns:
        amount = int(sale_return.total or 0)
        modes = return_modes.get(sale_return.invoice_id) or set()
        if modes == {"RETAIL"}:
            retail -= amount
        elif modes == {"WHOLESALE"}:
            wholesale -= amount
        else:
            mixed -= amount
    sales_total = sum(int(i.total or 0) for i in invoices) - sum(int(r.total or 0) for r in partial_returns)
    return {
        "invoices": invoices,
        "partial_returns": partial_returns,
        "sales_total": max(0, sales_total),
        "invoice_count": len(invoices),
        "retail": max(0, retail),
        "wholesale": max(0, wholesale),
        "mixed": max(0, mixed),
    }


def _period_profit(tenant_id: int, start_dt: datetime, end_dt: datetime) -> int:
    rows = db.session.query(
        FoodSaleItemSnapshot.line_total_snapshot,
        FoodSaleItemSnapshot.cost_snapshot,
        FoodSaleItemSnapshot.quantity_snapshot,
        FoodSaleItemSnapshot.quantity_base,
        FoodSaleItemSnapshot.unit_factor_snapshot,
    ).join(OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        FoodSaleItemSnapshot.tenant_id == tenant_id,
        Invoice.source_module == "food",
        Invoice.created_at >= start_dt,
        Invoice.created_at < end_dt,
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    profit = 0
    for line_total, cost, qty_snap, qty_base, factor in rows:
        quantity = float(qty_snap) if qty_snap is not None else (
            float(qty_base or 0) / float(factor or 1)
        )
        revenue = int(line_total or 0)
        profit += revenue - int(round(int(cost or 0) * quantity))
    return max(0, profit)


def _payment_term_days_for_customer(tenant_id: int, customer_id: int | None, settings: FoodSettings) -> int:
    default_days = max(0, int(getattr(settings, "default_receivable_days", None) or 30))
    if not customer_id:
        return default_days
    profile = FoodCustomerProfile.query.filter_by(tenant_id=tenant_id, customer_id=customer_id).first()
    if profile and profile.payment_term_days is not None:
        return max(0, int(profile.payment_term_days))
    return default_days


def _payment_term_days_for_supplier(tenant_id: int, supplier_id: int | None, settings: FoodSettings) -> int:
    default_days = max(0, int(getattr(settings, "default_payable_days", None) or 30))
    if not supplier_id:
        return default_days
    profile = FoodSupplierProfile.query.filter_by(tenant_id=tenant_id, supplier_id=supplier_id).first()
    if profile and profile.payment_term_days is not None:
        return max(0, int(profile.payment_term_days))
    return default_days


def _due_date_from_created(created_at: datetime | None, term_days: int) -> date | None:
    if not created_at:
        return None
    local = created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date()
    return local + timedelta(days=max(0, int(term_days)))


def _cash_session_dict(row: FoodCashSession | None) -> dict | None:
    if not row:
        return None
    document_number, clean_note = _unpack_finance_note(row.note, "جلسة صندوق")
    return {
        "id": row.id,
        "business_date": row.business_date.isoformat(),
        "warehouse_id": row.warehouse_id,
        "opening_cash": int(row.opening_cash or 0),
        "expected_closing_cash": int(row.expected_closing_cash) if row.expected_closing_cash is not None else None,
        "actual_closing_cash": int(row.actual_closing_cash) if row.actual_closing_cash is not None else None,
        "cash_variance": int(row.cash_variance) if row.cash_variance is not None else None,
        "status": row.status,
        "note": clean_note,
        "document_number": document_number or f"CSH-{row.id}",
        "variance_reason": row.variance_reason,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }


def get_cash_session(tenant_id: int, business_date: date | None = None, warehouse_id=None) -> dict:
    day = business_date or _business_today()
    warehouse_id = as_int(warehouse_id, 0) or None
    query = FoodCashSession.query.filter_by(tenant_id=tenant_id, business_date=day)
    if warehouse_id is None:
        query = query.filter(FoodCashSession.warehouse_id.is_(None))
    else:
        query = query.filter_by(warehouse_id=warehouse_id)
    row = query.first()
    return {"session": _cash_session_dict(row), "business_date": day.isoformat()}


def open_cash_session(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    day = _parse_date(payload.get("business_date"), "تاريخ الجلسة") or _business_today()
    warehouse_id = as_int(payload.get("warehouse_id"), 0) or None
    opening = as_int(payload.get("opening_cash"), 0, minimum=0)
    existing = get_cash_session(tenant_id, day, warehouse_id)["session"]
    if existing and existing["status"] == "closed":
        raise FoodError("جلسة هذا اليوم مغلقة مسبقاً — أعد فتحها أولاً إن لزم")
    if existing:
        row = db.session.get(FoodCashSession, existing["id"])
        row.opening_cash = opening
        document_number = _finance_document_no("CSH", payload.get("document_number") or existing.get("document_number"))
        row.note = _pack_finance_note("جلسة صندوق", document_number, payload.get("note") or existing.get("note"))
        row.opened_by = employee_id or row.opened_by
    else:
        document_number = _finance_document_no("CSH", payload.get("document_number"))
        row = FoodCashSession(
            tenant_id=tenant_id,
            business_date=day,
            warehouse_id=warehouse_id,
            opening_cash=opening,
            status="open",
            opened_by=employee_id,
            note=_pack_finance_note("جلسة صندوق", document_number, payload.get("note")),
        )
        db.session.add(row)
    db.session.flush()
    return _cash_session_dict(row)


def close_cash_session(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    day = _parse_date(payload.get("business_date"), "تاريخ الجلسة") or _business_today()
    warehouse_id = as_int(payload.get("warehouse_id"), 0) or None
    actual = as_int(payload.get("actual_closing_cash"), 0, minimum=0)
    session_info = get_cash_session(tenant_id, day, warehouse_id)["session"]
    if not session_info:
        raise FoodError("لا توجد جلسة صندوق مفتوحة لهذا اليوم — سجّل الرصيد الافتتاحي أولاً")
    row = db.session.get(FoodCashSession, session_info["id"])
    start_dt, end_dt = _local_date_bounds(day, day)
    movement = _period_cash(tenant_id, start_dt, end_dt, business_date=day, warehouse_id=warehouse_id)
    expected = int(movement["expected_balance"] if movement["expected_balance"] is not None else (
        int(row.opening_cash or 0) + int(movement["net"])
    ))
    row.expected_closing_cash = expected
    row.actual_closing_cash = actual
    row.cash_variance = actual - expected
    row.status = "closed"
    row.closed_by = employee_id
    row.closed_at = datetime.utcnow()
    row.variance_reason = str(payload.get("variance_reason") or "").strip()[:500] or None
    db.session.flush()
    return _cash_session_dict(row)


def reopen_cash_session(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    day = _parse_date(payload.get("business_date"), "تاريخ الجلسة") or _business_today()
    warehouse_id = as_int(payload.get("warehouse_id"), 0) or None
    session_info = get_cash_session(tenant_id, day, warehouse_id)["session"]
    if not session_info:
        raise FoodError("لا توجد جلسة صندوق لهذا اليوم")
    row = db.session.get(FoodCashSession, session_info["id"])
    row.status = "open"
    row.actual_closing_cash = None
    row.cash_variance = None
    row.expected_closing_cash = None
    row.closed_at = None
    row.closed_by = None
    row.variance_reason = None
    row.opened_by = employee_id or row.opened_by
    db.session.flush()
    return _cash_session_dict(row)


def list_expenses(tenant_id: int, start: date | None = None, end: date | None = None) -> list[dict]:
    query = FoodExpense.query.filter_by(tenant_id=tenant_id)
    if start:
        query = query.filter(FoodExpense.expense_date >= start)
    if end:
        query = query.filter(FoodExpense.expense_date <= end)
    rows = query.order_by(FoodExpense.expense_date.desc(), FoodExpense.id.desc()).limit(200).all()
    result = []
    for row in rows:
        document_number, clean_note = _unpack_finance_note(row.note, "مصروف تشغيل")
        result.append({
            "id": row.id,
            "title": row.title,
            "category": row.category,
            "amount": int(row.amount or 0),
            "expense_date": row.expense_date.isoformat(),
            "note": clean_note,
            "document_number": document_number or f"EXP-{row.id}",
            "warehouse_id": row.warehouse_id,
            "employee_id": row.employee_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })
    return result


def create_expense(tenant_id: int, payload: dict, employee_id: int | None = None) -> dict:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise FoodError("عنوان المصروف مطلوب")
    amount = as_int(payload.get("amount"), 0, minimum=1)
    expense_date = _parse_date(payload.get("expense_date"), "تاريخ المصروف") or _business_today()
    document_number = _finance_document_no("EXP", payload.get("document_number"))
    clean_note = str(payload.get("note") or "").strip()[:255] or None
    row = FoodExpense(
        tenant_id=tenant_id,
        title=title[:150],
        category=str(payload.get("category") or "").strip()[:100] or None,
        amount=amount,
        expense_date=expense_date,
        note=_pack_finance_note("مصروف تشغيل", document_number, clean_note)[:255],
        warehouse_id=as_int(payload.get("warehouse_id"), 0) or None,
        employee_id=employee_id,
    )
    db.session.add(row)
    db.session.flush()
    return {
        "id": row.id,
        "title": row.title,
        "category": row.category,
        "amount": int(row.amount or 0),
        "expense_date": row.expense_date.isoformat(),
        "note": clean_note,
        "document_number": document_number,
    }


def delete_expense(tenant_id: int, expense_id: int) -> None:
    row = FoodExpense.query.filter_by(tenant_id=tenant_id, id=expense_id).first()
    if not row:
        raise FoodError("المصروف غير موجود")
    db.session.delete(row)


def list_finance_movements(tenant_id: int, section: str, limit: int = 250) -> dict:
    """Tenant-scoped movement register used by the professional finance pages."""
    limit = min(max(int(limit or 250), 1), 500)
    rows: list[dict] = []
    if section == "receipts":
        ledger = (
            InvoicePaymentLedger.query.join(Invoice, Invoice.id == InvoicePaymentLedger.invoice_id)
            .filter(
                InvoicePaymentLedger.tenant_id == tenant_id,
                InvoicePaymentLedger.source_module == "food",
                or_(InvoicePaymentLedger.note == "قبض عميل",
                    InvoicePaymentLedger.note.startswith("قبض عميل\n", autoescape=True)),
                Invoice.source_module == "food",
            )
            .order_by(InvoicePaymentLedger.recorded_at.desc(), InvoicePaymentLedger.id.desc())
            .limit(limit).all()
        )
        customer_ids = {invoice.customer_id for item in ledger if (invoice := db.session.get(Invoice, item.invoice_id)) and invoice.customer_id}
        names = {row.id: row.name for row in Customer.query.filter(Customer.id.in_(customer_ids or [-1])).all()}
        for item in ledger:
            invoice = db.session.get(Invoice, item.invoice_id)
            document_number, clean_note = _unpack_finance_note(item.note, "قبض عميل")
            rows.append({"id": item.id, "date": item.recorded_at.isoformat(), "party": names.get(getattr(invoice, "customer_id", None), getattr(invoice, "customer_name", None) or "عميل نقدي"), "reference": document_number or getattr(invoice, "invoice_no", None) or f"#{item.invoice_id}", "amount": int(item.amount_delta or 0), "note": clean_note})
    elif section == "payments":
        payments = SupplierPayment.query.filter(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.source_module == "food",
            SupplierPayment.deleted_at.is_(None),
        ).order_by(SupplierPayment.created_at.desc(), SupplierPayment.id.desc()).limit(limit).all()
        supplier_ids = {item.supplier_id for item in payments}
        names = {row.id: row.name for row in Supplier.query.filter(Supplier.id.in_(supplier_ids or [-1])).all()}
        rows = [{"id": item.id, "date": item.created_at.isoformat() if item.created_at else None, "party": names.get(item.supplier_id, "—"), "reference": item.document_number or f"#{item.id}", "amount": int(item.amount or 0), "note": item.note} for item in payments]
    elif section == "expenses":
        expenses = FoodExpense.query.filter_by(tenant_id=tenant_id).order_by(FoodExpense.expense_date.desc(), FoodExpense.id.desc()).limit(limit).all()
        for item in expenses:
            document_number, clean_note = _unpack_finance_note(item.note, "مصروف تشغيل")
            rows.append({"id": item.id, "date": item.expense_date.isoformat(), "party": item.title, "reference": document_number or item.category or "مصروف", "amount": int(item.amount or 0), "note": clean_note})
    elif section == "cash-sessions":
        sessions = FoodCashSession.query.filter_by(tenant_id=tenant_id).order_by(FoodCashSession.business_date.desc(), FoodCashSession.id.desc()).limit(limit).all()
        rows = [{"id": item.id, "date": item.business_date.isoformat(), "party": "جلسة صندوق", "reference": "مغلقة" if item.status == "closed" else "مفتوحة", "amount": int(item.actual_closing_cash if item.actual_closing_cash is not None else item.opening_cash or 0), "note": item.variance_reason or item.note} for item in sessions]
    else:
        raise FoodError("نوع الحركة المالية غير صالح")
    return {"section": section, "count": len(rows), "total": sum(int(row["amount"] or 0) for row in rows), "rows": rows}


def finance_movement_overview(tenant_id: int) -> list[dict]:
    config = {
        "receipts": ("سندات قبض العملاء", "تحصيل الذمم المستحقة", "fa-arrow-down", "in"),
        "payments": ("تسديدات الموردين", "دفع المبالغ المستحقة", "fa-arrow-up", "out"),
        "expenses": ("مصروفات التشغيل", "مصروفات نشاط المواد الغذائية", "fa-receipt", "out"),
        "cash-sessions": ("الصندوق اليومي", "الافتتاح والإغلاق والجرد", "fa-vault", "in"),
    }
    result = []
    for section, (title, description, icon, tone) in config.items():
        data = list_finance_movements(tenant_id, section)
        latest = data["rows"][0]["date"] if data["rows"] else None
        result.append({"section": section, "title": title, "description": description, "icon": icon, "tone": tone, "count": data["count"], "total": data["total"], "latest": latest, "href": f"/food/finance/{section}"})
    return result


def upsert_customer_payment_terms(tenant_id: int, customer_id: int, payment_term_days) -> dict:
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise FoodError("العميل غير موجود")
    days = None if payment_term_days in (None, "") else as_int(payment_term_days, 0, minimum=0)
    profile = FoodCustomerProfile.query.filter_by(tenant_id=tenant_id, customer_id=customer_id).first()
    if not profile:
        profile = FoodCustomerProfile(tenant_id=tenant_id, customer_id=customer_id)
        db.session.add(profile)
    profile.payment_term_days = days
    db.session.flush()
    return {"customer_id": customer_id, "payment_term_days": profile.payment_term_days}


def upsert_supplier_payment_terms(tenant_id: int, supplier_id: int, payment_term_days) -> dict:
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        raise FoodError("المورد غير موجود")
    days = None if payment_term_days in (None, "") else as_int(payment_term_days, 0, minimum=0)
    profile = FoodSupplierProfile.query.filter_by(tenant_id=tenant_id, supplier_id=supplier_id).first()
    if not profile:
        profile = FoodSupplierProfile(tenant_id=tenant_id, supplier_id=supplier_id)
        db.session.add(profile)
    profile.payment_term_days = days
    db.session.flush()
    return {"supplier_id": supplier_id, "payment_term_days": profile.payment_term_days}


# ---------------------------------------------------------------------------
# Customers & suppliers management (Food parties)
# ---------------------------------------------------------------------------

WALK_IN_PHONE = "FOOD-WALK-IN"


def _return_totals_for_tenant(tenant_id: int) -> dict[int, int]:
    return {
        int(invoice_id): int(total or 0)
        for invoice_id, total in db.session.query(
            FoodSaleReturn.invoice_id, func.sum(FoodSaleReturn.total)
        ).filter(FoodSaleReturn.tenant_id == tenant_id).group_by(FoodSaleReturn.invoice_id).all()
    }


def _invoice_due(invoice: Invoice, returned_map: dict[int, int]) -> int:
    if invoice.status in ("ملغي", "راجع"):
        return 0
    return max(0, int(invoice.total or 0) - returned_map.get(invoice.id, 0) - int(invoice.paid_amount or 0))


def _customer_financials(tenant_id: int, customer_id: int, *, returned_map: dict[int, int] | None = None,
                         term_days: int = 30) -> dict:
    returned_map = returned_map if returned_map is not None else _return_totals_for_tenant(tenant_id)
    invoices = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.customer_id == customer_id,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).order_by(Invoice.created_at.desc()).all()
    today = _business_today()
    total = 0
    paid = 0
    debt = 0
    overdue = 0
    open_count = 0
    oldest_debt_at = None
    for inv in invoices:
        inv_total = int(inv.total or 0)
        inv_paid = int(inv.paid_amount or 0)
        due = _invoice_due(inv, returned_map)
        total += inv_total
        paid += min(inv_paid, inv_total)
        if due:
            debt += due
            open_count += 1
            if oldest_debt_at is None or (inv.created_at and inv.created_at < oldest_debt_at):
                oldest_debt_at = inv.created_at
            due_date = _due_date_from_created(inv.created_at, term_days)
            if due_date and due_date < today:
                overdue += due
    last_invoice = invoices[0] if invoices else None
    return {
        "total_purchases": total,
        "paid": paid,
        "debt": debt,
        "overdue": overdue,
        "open_invoices": open_count,
        "invoice_count": len(invoices),
        "last_invoice_at": last_invoice.created_at.isoformat() if last_invoice and last_invoice.created_at else None,
        "oldest_debt_at": oldest_debt_at.isoformat() if oldest_debt_at else None,
    }


def _supplier_financials(tenant_id: int, supplier: Supplier, *, term_days: int = 30) -> dict:
    debt = max(0, int(supplier.total_debt or 0) - int(supplier.total_paid or 0))
    today = _business_today()
    purchases = Purchase.query.filter_by(supplier_id=supplier.id, source_module="food").order_by(
        Purchase.created_at.desc()
    ).all()
    overdue = 0
    open_count = 0
    oldest_due_at = None
    for purchase in purchases:
        remaining = max(0, int(purchase.remaining_total or 0))
        if not remaining:
            continue
        open_count += 1
        if oldest_due_at is None or (purchase.created_at and purchase.created_at < oldest_due_at):
            oldest_due_at = purchase.created_at
        due_date = _due_date_from_created(purchase.created_at, term_days)
        if due_date and due_date < today:
            overdue += remaining
    last_purchase = purchases[0] if purchases else None
    return {
        "total_purchases": int(supplier.total_debt or 0),
        "paid": int(supplier.total_paid or 0),
        "debt": debt,
        "overdue": overdue,
        "open_purchases": open_count,
        "purchase_count": len(purchases),
        "last_purchase_at": last_purchase.created_at.isoformat() if last_purchase and last_purchase.created_at else None,
        "oldest_debt_at": oldest_due_at.isoformat() if oldest_due_at else None,
    }


def list_customers(tenant_id: int, q: str | None = None, tab: str = "all", limit: int = 300) -> dict:
    settings_row = _settings(tenant_id)
    returned_map = _return_totals_for_tenant(tenant_id)
    profiles = {
        row.customer_id: row
        for row in FoodCustomerProfile.query.filter_by(tenant_id=tenant_id).all()
    }
    query = Customer.query.filter(Customer.tenant_id == tenant_id)
    term = str(q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.outerjoin(
            FoodCustomerProfile,
            and_(
                FoodCustomerProfile.customer_id == Customer.id,
                FoodCustomerProfile.tenant_id == tenant_id,
            ),
        ).filter(or_(
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
            Customer.address.ilike(like),
            FoodCustomerProfile.company_name.ilike(like),
            FoodCustomerProfile.customer_code.ilike(like),
        ))
    customers = query.order_by(Customer.name).limit(max(1, min(int(limit or 300), 1000))).all()
    rows = []
    for customer in customers:
        if customer.phone == WALK_IN_PHONE:
            continue
        profile = profiles.get(customer.id)
        term_days = (
            int(profile.payment_term_days)
            if profile and profile.payment_term_days is not None
            else int(settings_row.default_receivable_days or 30)
        )
        money = _customer_financials(
            tenant_id, customer.id, returned_map=returned_map, term_days=term_days
        )
        credit_limit = int(profile.credit_limit) if profile and profile.credit_limit is not None else None
        active = True if not profile else bool(profile.active)
        credit_usage = None
        if credit_limit is not None and credit_limit > 0:
            credit_usage = round(min(100.0, (money["debt"] / credit_limit) * 100), 1)
        rows.append({
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "phone2": customer.phone2,
            "address": customer.address,
            "city": customer.city,
            "notes": customer.notes,
            "company_name": profile.company_name if profile else None,
            "customer_code": profile.customer_code if profile else None,
            "credit_limit": credit_limit,
            "payment_term_days": int(profile.payment_term_days) if profile and profile.payment_term_days is not None else None,
            "active": active,
            "credit_usage": credit_usage,
            "is_over_credit": bool(credit_limit is not None and money["debt"] > credit_limit),
            **money,
        })

    summary = {
        "total": len(rows),
        "with_debt": sum(1 for row in rows if row["debt"] > 0),
        "overdue_count": sum(1 for row in rows if row["overdue"] > 0),
        "clear_count": sum(1 for row in rows if row["debt"] <= 0 and row["active"]),
        "credit_count": sum(1 for row in rows if row["credit_limit"] is not None),
        "debt_total": sum(row["debt"] for row in rows),
        "overdue_total": sum(row["overdue"] for row in rows),
        "inactive": sum(1 for row in rows if not row["active"]),
    }

    tab_key = str(tab or "all").lower()
    if tab_key == "debt":
        rows = [row for row in rows if row["debt"] > 0]
    elif tab_key == "overdue":
        rows = [row for row in rows if row["overdue"] > 0]
    elif tab_key == "credit":
        rows = [row for row in rows if row["credit_limit"] is not None]
    elif tab_key == "inactive":
        rows = [row for row in rows if not row["active"]]
    elif tab_key == "clear":
        rows = [row for row in rows if row["debt"] <= 0 and row["active"]]

    return {"rows": rows, "summary": summary, "tab": tab_key}


def get_customer_detail(tenant_id: int, customer_id: int) -> dict:
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer or customer.phone == WALK_IN_PHONE:
        raise FoodError("العميل غير موجود")
    settings_row = _settings(tenant_id)
    profile = FoodCustomerProfile.query.filter_by(tenant_id=tenant_id, customer_id=customer.id).first()
    term_days = (
        int(profile.payment_term_days)
        if profile and profile.payment_term_days is not None
        else int(settings_row.default_receivable_days or 30)
    )
    returned_map = _return_totals_for_tenant(tenant_id)
    money = _customer_financials(
        tenant_id, customer.id, returned_map=returned_map, term_days=term_days
    )
    invoices = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.customer_id == customer.id,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي",)),
    ).order_by(Invoice.created_at.desc()).limit(40).all()
    invoice_rows = []
    for inv in invoices:
        due = _invoice_due(inv, returned_map)
        returned = returned_map.get(inv.id, 0)
        invoice_rows.append({
            "id": inv.id,
            "invoice_no": inv.invoice_no or inv.id,
            "total": int(inv.total or 0),
            "paid": int(inv.paid_amount or 0),
            "returned": returned,
            "remaining": due,
            "status": inv.status,
            "payment_status": inv.payment_status,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "due_date": (
                _due_date_from_created(inv.created_at, term_days).isoformat()
                if inv.created_at else None
            ),
            "href": f"/food/orders?open={inv.id}",
        })
    receipts = (
        InvoicePaymentLedger.query.join(Invoice, Invoice.id == InvoicePaymentLedger.invoice_id)
        .filter(
            Invoice.tenant_id == tenant_id,
            Invoice.customer_id == customer.id,
            InvoicePaymentLedger.source_module == "food",
            InvoicePaymentLedger.note == "قبض عميل",
        )
        .order_by(InvoicePaymentLedger.recorded_at.desc())
        .limit(30)
        .all()
    )
    receipt_rows = [{
        "id": row.id,
        "amount": int(row.amount_delta or 0),
        "invoice_id": row.invoice_id,
        "note": row.note,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
    } for row in receipts]
    credit_limit = int(profile.credit_limit) if profile and profile.credit_limit is not None else None
    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "phone2": customer.phone2,
        "address": customer.address,
        "city": customer.city,
        "notes": customer.notes,
        "company_name": profile.company_name if profile else None,
        "customer_code": profile.customer_code if profile else None,
        "credit_limit": credit_limit,
        "payment_term_days": int(profile.payment_term_days) if profile and profile.payment_term_days is not None else None,
        "default_payment_term_days": int(settings_row.default_receivable_days or 30),
        "active": True if not profile else bool(profile.active),
        "available_credit": max(0, credit_limit - money["debt"]) if credit_limit is not None else None,
        "invoices": invoice_rows,
        "receipts": receipt_rows,
        **money,
    }


def create_customer(tenant_id: int, payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    if not name:
        raise FoodError("اسم العميل مطلوب")
    if not phone:
        raise FoodError("هاتف العميل مطلوب")
    if phone == WALK_IN_PHONE:
        raise FoodError("رقم الهاتف محجوز للنظام")
    existing = Customer.query.filter_by(tenant_id=tenant_id, phone=phone).first()
    if existing:
        raise FoodError("يوجد عميل بنفس رقم الهاتف")
    row = Customer(
        tenant_id=tenant_id,
        name=name,
        phone=phone,
        phone2=str(payload.get("phone2") or "").strip() or None,
        city=str(payload.get("city") or "").strip() or None,
        address=str(payload.get("address") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    profile = FoodCustomerProfile(
        tenant_id=tenant_id,
        customer_id=row.id,
        company_name=str(payload.get("company_name") or "").strip() or None,
        customer_code=str(payload.get("customer_code") or "").strip() or None,
        credit_limit=_optional_int(payload.get("credit_limit"), minimum=0),
        payment_term_days=_optional_int(payload.get("payment_term_days"), minimum=0),
        active=bool(payload.get("active", True)),
    )
    db.session.add(profile)
    db.session.flush()
    return get_customer_detail(tenant_id, row.id)


def update_customer(tenant_id: int, customer_id: int, payload: dict) -> dict:
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer or customer.phone == WALK_IN_PHONE:
        raise FoodError("العميل غير موجود")
    name = str(payload.get("name") or customer.name).strip()
    phone = str(payload.get("phone") or customer.phone).strip()
    if not name:
        raise FoodError("اسم العميل مطلوب")
    if not phone:
        raise FoodError("هاتف العميل مطلوب")
    if phone == WALK_IN_PHONE:
        raise FoodError("رقم الهاتف محجوز للنظام")
    conflict = Customer.query.filter(
        Customer.tenant_id == tenant_id,
        Customer.phone == phone,
        Customer.id != customer.id,
    ).first()
    if conflict:
        raise FoodError("يوجد عميل بنفس رقم الهاتف")
    customer.name = name
    customer.phone = phone
    if "phone2" in payload:
        customer.phone2 = str(payload.get("phone2") or "").strip() or None
    if "city" in payload:
        customer.city = str(payload.get("city") or "").strip() or None
    if "address" in payload:
        customer.address = str(payload.get("address") or "").strip() or None
    if "notes" in payload:
        customer.notes = str(payload.get("notes") or "").strip() or None

    profile = FoodCustomerProfile.query.filter_by(tenant_id=tenant_id, customer_id=customer.id).first()
    if not profile:
        profile = FoodCustomerProfile(tenant_id=tenant_id, customer_id=customer.id)
        db.session.add(profile)
    if "company_name" in payload:
        profile.company_name = str(payload.get("company_name") or "").strip() or None
    if "customer_code" in payload:
        profile.customer_code = str(payload.get("customer_code") or "").strip() or None
    if "credit_limit" in payload:
        profile.credit_limit = _optional_int(payload.get("credit_limit"), minimum=0)
    if "payment_term_days" in payload:
        profile.payment_term_days = _optional_int(payload.get("payment_term_days"), minimum=0)
    if "active" in payload:
        profile.active = bool(payload.get("active"))
    db.session.flush()
    return get_customer_detail(tenant_id, customer.id)


def list_suppliers(tenant_id: int, q: str | None = None, tab: str = "all", limit: int = 300) -> dict:
    settings_row = _settings(tenant_id)
    profiles = {
        row.supplier_id: row
        for row in FoodSupplierProfile.query.filter_by(tenant_id=tenant_id).all()
    }
    query = Supplier.query
    term = str(q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(or_(
            Supplier.name.ilike(like),
            Supplier.phone.ilike(like),
            Supplier.phone2.ilike(like),
            Supplier.address.ilike(like),
        ))
    suppliers = query.order_by(Supplier.name).limit(max(1, min(int(limit or 300), 1000))).all()
    rows = []
    for supplier in suppliers:
        profile = profiles.get(supplier.id)
        term_days = (
            int(profile.payment_term_days)
            if profile and profile.payment_term_days is not None
            else int(settings_row.default_payable_days or 30)
        )
        money = _supplier_financials(tenant_id, supplier, term_days=term_days)
        active = True if not profile else bool(profile.active)
        rows.append({
            "id": supplier.id,
            "name": supplier.name,
            "phone": supplier.phone,
            "phone2": supplier.phone2,
            "address": supplier.address,
            "payment_term_days": int(profile.payment_term_days) if profile and profile.payment_term_days is not None else None,
            "active": active,
            **money,
        })

    summary = {
        "total": len(rows),
        "with_debt": sum(1 for row in rows if row["debt"] > 0),
        "overdue_count": sum(1 for row in rows if row["overdue"] > 0),
        "clear_count": sum(1 for row in rows if row["debt"] <= 0 and row["active"]),
        "debt_total": sum(row["debt"] for row in rows),
        "overdue_total": sum(row["overdue"] for row in rows),
        "inactive": sum(1 for row in rows if not row["active"]),
    }

    tab_key = str(tab or "all").lower()
    if tab_key == "debt":
        rows = [row for row in rows if row["debt"] > 0]
    elif tab_key == "overdue":
        rows = [row for row in rows if row["overdue"] > 0]
    elif tab_key == "inactive":
        rows = [row for row in rows if not row["active"]]
    elif tab_key == "clear":
        rows = [row for row in rows if row["debt"] <= 0 and row["active"]]

    return {"rows": rows, "summary": summary, "tab": tab_key}


def get_supplier_detail(tenant_id: int, supplier_id: int) -> dict:
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        raise FoodError("المورد غير موجود")
    settings_row = _settings(tenant_id)
    profile = FoodSupplierProfile.query.filter_by(tenant_id=tenant_id, supplier_id=supplier.id).first()
    term_days = (
        int(profile.payment_term_days)
        if profile and profile.payment_term_days is not None
        else int(settings_row.default_payable_days or 30)
    )
    money = _supplier_financials(tenant_id, supplier, term_days=term_days)
    purchases = Purchase.query.filter_by(
        supplier_id=supplier.id, source_module="food"
    ).order_by(Purchase.created_at.desc()).limit(40).all()
    purchase_rows = []
    for purchase in purchases:
        remaining = max(0, int(purchase.remaining_total or 0))
        purchase_rows.append({
            "id": purchase.id,
            "invoice_no": purchase.invoice_no or purchase.id,
            "supplier_invoice_no": getattr(purchase, "supplier_invoice_no", None),
            "total": int(purchase.grand_total or purchase.total or 0),
            "paid": int(purchase.paid_total or 0),
            "remaining": remaining,
            "status": getattr(purchase, "status", None),
            "created_at": purchase.created_at.isoformat() if purchase.created_at else None,
            "due_date": (
                _due_date_from_created(purchase.created_at, term_days).isoformat()
                if purchase.created_at else None
            ),
            "href": f"/food/purchases?open={purchase.id}",
        })
    payments = SupplierPayment.query.filter(
        SupplierPayment.tenant_id == tenant_id,
        SupplierPayment.supplier_id == supplier.id,
        SupplierPayment.source_module == "food",
        SupplierPayment.deleted_at.is_(None),
    ).order_by(SupplierPayment.created_at.desc()).limit(30).all()
    payment_rows = [{
        "id": row.id,
        "amount": int(row.amount or 0),
        "note": row.note,
        "payment_method": row.payment_method,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in payments]
    return {
        "id": supplier.id,
        "name": supplier.name,
        "phone": supplier.phone,
        "phone2": supplier.phone2,
        "address": supplier.address,
        "payment_term_days": int(profile.payment_term_days) if profile and profile.payment_term_days is not None else None,
        "default_payment_term_days": int(settings_row.default_payable_days or 30),
        "active": True if not profile else bool(profile.active),
        "opening_balance": int(supplier.opening_balance or 0),
        "purchases": purchase_rows,
        "payments": payment_rows,
        **money,
    }


def create_supplier(tenant_id: int, payload: dict) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise FoodError("اسم المورد مطلوب")
    row = Supplier(
        name=name,
        phone=str(payload.get("phone") or "").strip() or None,
        phone2=str(payload.get("phone2") or "").strip() or None,
        address=str(payload.get("address") or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    days = _optional_int(payload.get("payment_term_days"), minimum=0)
    active = bool(payload.get("active", True))
    if days is not None or "active" in payload:
        db.session.add(FoodSupplierProfile(
            tenant_id=tenant_id,
            supplier_id=row.id,
            payment_term_days=days,
            active=active,
        ))
    db.session.flush()
    return get_supplier_detail(tenant_id, row.id)


def update_supplier(tenant_id: int, supplier_id: int, payload: dict) -> dict:
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        raise FoodError("المورد غير موجود")
    name = str(payload.get("name") or supplier.name).strip()
    if not name:
        raise FoodError("اسم المورد مطلوب")
    supplier.name = name
    if "phone" in payload:
        supplier.phone = str(payload.get("phone") or "").strip() or None
    if "phone2" in payload:
        supplier.phone2 = str(payload.get("phone2") or "").strip() or None
    if "address" in payload:
        supplier.address = str(payload.get("address") or "").strip() or None

    profile = FoodSupplierProfile.query.filter_by(tenant_id=tenant_id, supplier_id=supplier.id).first()
    if not profile and ("payment_term_days" in payload or "active" in payload):
        profile = FoodSupplierProfile(tenant_id=tenant_id, supplier_id=supplier.id)
        db.session.add(profile)
    if profile:
        if "payment_term_days" in payload:
            profile.payment_term_days = _optional_int(payload.get("payment_term_days"), minimum=0)
        if "active" in payload:
            profile.active = bool(payload.get("active"))
    db.session.flush()
    return get_supplier_detail(tenant_id, supplier.id)


def _period_cash(
    tenant_id: int,
    start_dt: datetime,
    end_dt: datetime,
    *,
    business_date: date | None = None,
    warehouse_id=None,
) -> dict:
    ledger_rows = InvoicePaymentLedger.query.join(
        Invoice, Invoice.id == InvoicePaymentLedger.invoice_id
    ).filter(
        InvoicePaymentLedger.tenant_id == tenant_id,
        InvoicePaymentLedger.source_module.in_(("food", "food_return")),
        InvoicePaymentLedger.recorded_at >= start_dt,
        InvoicePaymentLedger.recorded_at < end_dt,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    customer_receipts = sum(int(row.amount_delta or 0) for row in ledger_rows if row.note == "قبض عميل")
    cash_sales = sum(int(row.amount_delta or 0) for row in ledger_rows if row.note != "قبض عميل")
    supplier_payments = sum(
        int(row.amount or 0) for row in SupplierPayment.query.filter(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.source_module == "food",
            SupplierPayment.deleted_at.is_(None),
            SupplierPayment.created_at >= start_dt,
            SupplierPayment.created_at < end_dt,
        ).all()
    )
    start_day = business_date or start_dt.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date()
    end_day = (end_dt - timedelta(seconds=1)).replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date()
    expenses_total = int(db.session.query(func.coalesce(func.sum(FoodExpense.amount), 0)).filter(
        FoodExpense.tenant_id == tenant_id,
        FoodExpense.expense_date >= start_day,
        FoodExpense.expense_date <= end_day,
    ).scalar() or 0)

    opening_balance = None
    actual_balance = None
    difference = None
    session_payload = None
    single_day = start_day == end_day
    if single_day:
        session = get_cash_session(tenant_id, start_day, warehouse_id)["session"]
        session_payload = session
        if session:
            opening_balance = int(session["opening_cash"] or 0)
            if session.get("actual_closing_cash") is not None:
                actual_balance = int(session["actual_closing_cash"])

    total_in = cash_sales + customer_receipts
    total_out = supplier_payments + expenses_total
    net = total_in - total_out
    expected_balance = (opening_balance + net) if opening_balance is not None else None
    if expected_balance is not None and actual_balance is not None:
        difference = actual_balance - expected_balance

    return {
        "cash_sales": cash_sales,
        "customer_receipts": customer_receipts,
        "supplier_payments": supplier_payments,
        "expenses": expenses_total,
        "opening_balance": opening_balance,
        "actual_balance": actual_balance,
        "total_in": total_in,
        "total_out": total_out,
        "net": net,
        "expected_balance": expected_balance,
        "difference": difference,
        "session": session_payload,
        "unavailable": [],
    }


def dashboard(
    tenant_id: int,
    range_key: str = "today",
    start_value=None,
    end_value=None,
    *,
    view_profit: bool = True,
) -> dict:
    """Operational dashboard payload for the food workspace home page."""
    key, start, end, start_dt, end_dt = _report_window(range_key, start_value, end_value)
    prev_start, prev_end = _previous_window(start, end)
    prev_start_dt, prev_end_dt = _local_date_bounds(prev_start, prev_end)
    today = _business_today()
    now_local = datetime.now(BUSINESS_TIMEZONE)
    settings = FoodSettings.query.filter_by(tenant_id=tenant_id).first()
    expiry_warning_days = int(settings.expiry_warning_days if settings else 30)

    current = _period_sales_split(tenant_id, start_dt, end_dt)
    previous = _period_sales_split(tenant_id, prev_start_dt, prev_end_dt)
    purchases_total = int(db.session.query(func.coalesce(func.sum(Purchase.grand_total), 0)).filter(
        Purchase.source_module == "food",
        Purchase.created_at >= start_dt,
        Purchase.created_at < end_dt,
    ).scalar() or 0)
    prev_purchases = int(db.session.query(func.coalesce(func.sum(Purchase.grand_total), 0)).filter(
        Purchase.source_module == "food",
        Purchase.created_at >= prev_start_dt,
        Purchase.created_at < prev_end_dt,
    ).scalar() or 0)
    cash = _period_cash(tenant_id, start_dt, end_dt)
    prev_cash = _period_cash(tenant_id, prev_start_dt, prev_end_dt)
    profit = _period_profit(tenant_id, start_dt, end_dt) if view_profit else None
    prev_profit = _period_profit(tenant_id, prev_start_dt, prev_end_dt) if view_profit else None

    avg_invoice = int(current["sales_total"] / current["invoice_count"]) if current["invoice_count"] else 0
    prev_avg = int(previous["sales_total"] / previous["invoice_count"]) if previous["invoice_count"] else 0

    # Hourly / daily sales chart
    chart_points = []
    compare_points = []
    single_day = start == end
    if single_day:
        hour_totals: dict[int, dict] = {h: {"sales": 0, "count": 0} for h in range(24)}
        for invoice in current["invoices"]:
            local_ts = invoice.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            bucket = hour_totals[local_ts.hour]
            bucket["sales"] += int(invoice.total or 0)
            bucket["count"] += 1
        for sale_return in current["partial_returns"]:
            local_ts = sale_return.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            hour_totals[local_ts.hour]["sales"] -= int(sale_return.total or 0)
        prev_hours: dict[int, int] = {h: 0 for h in range(24)}
        for invoice in previous["invoices"]:
            local_ts = invoice.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            prev_hours[local_ts.hour] += int(invoice.total or 0)
        for hour in range(24):
            label_hour = hour % 12 or 12
            suffix = "ص" if hour < 12 else "م"
            chart_points.append({
                "label": f"{label_hour} {suffix}",
                "hour": hour,
                "sales": max(0, hour_totals[hour]["sales"]),
                "invoices": hour_totals[hour]["count"],
            })
            compare_points.append({"label": f"{label_hour} {suffix}", "hour": hour, "sales": prev_hours[hour]})
    else:
        day_count = (end - start).days + 1
        day_totals = {
            (start + timedelta(days=offset)).isoformat(): {"sales": 0, "count": 0}
            for offset in range(day_count)
        }
        for invoice in current["invoices"]:
            local_ts = invoice.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            key_day = local_ts.date().isoformat()
            if key_day in day_totals:
                day_totals[key_day]["sales"] += int(invoice.total or 0)
                day_totals[key_day]["count"] += 1
        for key_day, bucket in day_totals.items():
            day = date.fromisoformat(key_day)
            chart_points.append({
                "label": day.strftime("%d/%m"),
                "date": key_day,
                "sales": bucket["sales"],
                "invoices": bucket["count"],
            })

    products = list_products(tenant_id)
    product_map = {row["id"]: row for row in products}
    out_of_stock = [row for row in products if row["track_stock"] and row["stock_base"] <= 0]
    low_stock = [
        row for row in products
        if row["track_stock"] and row["stock_base"] > 0 and row["stock_base"] <= row["minimum_stock"]
    ]
    inventory_cost = sum(int(row["stock_base"]) * int(row["average_cost"]) for row in products if row["track_stock"])
    inventory_sell = 0
    for row in products:
        if not row["track_stock"]:
            continue
        base_unit = next((u for u in row["units"] if u.get("is_base")), (row["units"] or [{}])[0])
        retail = int((base_unit or {}).get("retail_price") or 0)
        inventory_sell += int(row["stock_base"]) * retail
    expected_profit = max(0, inventory_sell - inventory_cost) if view_profit else None

    batches = FoodExpiryBatch.query.filter(
        FoodExpiryBatch.tenant_id == tenant_id,
        FoodExpiryBatch.quantity_base > 0,
    ).order_by(FoodExpiryBatch.expiry_date).limit(300).all()
    expiry_buckets = {"today": 0, "within_3": 0, "within_7": 0, "within_30": 0, "expired": 0}
    expiry_value_risk = 0
    critical_expiry = []
    for batch in batches:
        days_left = (batch.expiry_date - today).days
        product = product_map.get(batch.variant_id) or {}
        unit_cost = int(product.get("average_cost") or 0)
        value = int(batch.quantity_base or 0) * unit_cost
        item = {
            "id": batch.id,
            "variant_id": batch.variant_id,
            "product": product.get("product_name") or batch.variant_id,
            "variant": product.get("variant_name") or "",
            "quantity_base": int(batch.quantity_base or 0),
            "expiry_date": batch.expiry_date.isoformat(),
            "days_left": days_left,
            "value": value,
            "image_url": product.get("image_url"),
        }
        if days_left < 0:
            expiry_buckets["expired"] += 1
            expiry_value_risk += value
            critical_expiry.append(item)
        elif days_left == 0:
            expiry_buckets["today"] += 1
            expiry_value_risk += value
            critical_expiry.append(item)
        elif days_left <= 3:
            expiry_buckets["within_3"] += 1
            expiry_value_risk += value
            critical_expiry.append(item)
        elif days_left <= 7:
            expiry_buckets["within_7"] += 1
            expiry_value_risk += value
        elif days_left <= 30:
            expiry_buckets["within_30"] += 1
        if days_left <= expiry_warning_days:
            pass
    critical_expiry = sorted(critical_expiry, key=lambda row: row["days_left"])[:3]
    expiry_warning_count = FoodExpiryBatch.query.filter(
        FoodExpiryBatch.tenant_id == tenant_id,
        FoodExpiryBatch.quantity_base > 0,
        FoodExpiryBatch.expiry_date <= today + timedelta(days=expiry_warning_days),
    ).count()

    # Top products by qty / profit / slow movers
    top_line_rows = db.session.query(
        FoodSaleItemSnapshot.variant_id,
        FoodSaleItemSnapshot.quantity_base,
        FoodSaleItemSnapshot.line_total_snapshot,
        FoodSaleItemSnapshot.cost_snapshot,
        FoodSaleItemSnapshot.quantity_snapshot,
        FoodSaleItemSnapshot.unit_factor_snapshot,
    ).join(OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        FoodSaleItemSnapshot.tenant_id == tenant_id,
        Invoice.source_module == "food",
        Invoice.created_at >= start_dt,
        Invoice.created_at < end_dt,
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    top_agg: dict[int, dict] = {}
    for variant_id, qty_base, line_total, cost, qty_snap, factor in top_line_rows:
        bucket = top_agg.setdefault(variant_id, {"qty": 0, "sales": 0, "profit": 0})
        quantity = float(qty_snap) if qty_snap is not None else (
            float(qty_base or 0) / float(factor or 1)
        )
        revenue = int(line_total or 0)
        bucket["qty"] += int(qty_base or 0)
        bucket["sales"] += revenue
        bucket["profit"] += revenue - int(round(int(cost or 0) * quantity))

    def _product_row(variant_id, qty, sales_amount, profit_amount=None):
        product = product_map.get(variant_id) or {}
        return {
            "variant_id": variant_id,
            "product": product.get("product_name") or "—",
            "variant": product.get("variant_name") or "",
            "image_url": product.get("image_url"),
            "quantity_base": int(qty or 0),
            "sales": int(sales_amount or 0),
            "profit": int(profit_amount or 0) if view_profit else None,
        }

    top_selling = [
        _product_row(variant_id, data["qty"], data["sales"], data["profit"])
        for variant_id, data in sorted(top_agg.items(), key=lambda item: item[1]["qty"], reverse=True)[:5]
    ]
    top_profit = sorted(
        [_product_row(variant_id, data["qty"], data["sales"], data["profit"]) for variant_id, data in top_agg.items()],
        key=lambda row: row["profit"] or 0,
        reverse=True,
    )[:5] if view_profit else []

    last_sale_rows = db.session.query(
        FoodSaleItemSnapshot.variant_id,
        func.max(Invoice.created_at).label("last_sale"),
    ).join(OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        FoodSaleItemSnapshot.tenant_id == tenant_id,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).group_by(FoodSaleItemSnapshot.variant_id).all()
    last_sale_map = {variant_id: last_sale for variant_id, last_sale in last_sale_rows}
    dead_stock = []
    dead_value = 0
    for product in products:
        if not product["track_stock"] or product["stock_base"] <= 0:
            continue
        last_sale = last_sale_map.get(product["id"])
        days_idle = (today - last_sale.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date()).days if last_sale else 999
        if days_idle < 30:
            continue
        value = int(product["stock_base"]) * int(product["average_cost"])
        dead_value += value
        dead_stock.append({
            "variant_id": product["id"],
            "product": product["product_name"],
            "variant": product["variant_name"],
            "image_url": product.get("image_url"),
            "days_idle": days_idle if days_idle < 900 else None,
            "stock_base": product["stock_base"],
            "value": value,
        })
    dead_stock = sorted(dead_stock, key=lambda row: -(row["days_idle"] or 999))[:10]

    # Reorder suggestions: low stock + recent daily velocity
    velocity_rows = db.session.query(
        FoodSaleItemSnapshot.variant_id,
        func.sum(FoodSaleItemSnapshot.quantity_base).label("qty"),
    ).join(OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        FoodSaleItemSnapshot.tenant_id == tenant_id,
        Invoice.source_module == "food",
        Invoice.created_at >= (_local_date_bounds(today - timedelta(days=6), today)[0]),
        Invoice.created_at < end_dt if end >= today else (_local_date_bounds(today, today)[1]),
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).group_by(FoodSaleItemSnapshot.variant_id).all()
    velocity_map = {variant_id: float(qty or 0) / 7.0 for variant_id, qty in velocity_rows}
    reorder = []
    for product in products:
        if not product["track_stock"]:
            continue
        stock = int(product["stock_base"])
        minimum = int(product["minimum_stock"] or 0)
        suggested = int(product.get("reorder_quantity") or 0)
        daily = velocity_map.get(product["id"], 0.0)
        days_cover = int(stock / daily) if daily > 0 else None
        needs = stock <= minimum or (days_cover is not None and days_cover <= 3)
        if not needs:
            continue
        if suggested <= 0:
            suggested = max(minimum - stock, int(daily * 7) - stock, 1)
        reorder.append({
            "variant_id": product["id"],
            "product": product["product_name"],
            "variant": product["variant_name"],
            "stock_base": stock,
            "stock_display": product.get("stock_display"),
            "days_cover": days_cover,
            "suggested_qty": max(1, suggested),
            "minimum_stock": minimum,
        })
    reorder = sorted(
        reorder,
        key=lambda row: (row["days_cover"] if row["days_cover"] is not None else -1, row["stock_base"]),
    )[:8]

    returned_by_invoice = {
        invoice_id: int(total or 0)
        for invoice_id, total in db.session.query(
            FoodSaleReturn.invoice_id, func.sum(FoodSaleReturn.total)
        ).filter(FoodSaleReturn.tenant_id == tenant_id).group_by(FoodSaleReturn.invoice_id).all()
    }
    settings_row = _settings(tenant_id)
    customer_debt_total = 0
    customer_overdue = 0
    customer_debt_count = 0
    for customer in Customer.query.filter_by(tenant_id=tenant_id).all():
        term_days = _payment_term_days_for_customer(tenant_id, customer.id, settings_row)
        invoices = Invoice.query.filter_by(
            tenant_id=tenant_id, customer_id=customer.id, source_module="food"
        ).filter(Invoice.status != "ملغي").all()
        debt = 0
        overdue = 0
        for inv in invoices:
            due = max(0, int(inv.total or 0) - returned_by_invoice.get(inv.id, 0) - int(inv.paid_amount or 0))
            if not due:
                continue
            debt += due
            due_date = _due_date_from_created(inv.created_at, term_days)
            if due_date and due_date < today:
                overdue += due
        if debt:
            customer_debt_count += 1
            customer_debt_total += debt
            customer_overdue += overdue

    supplier_debt_total = 0
    supplier_overdue = 0
    supplier_debt_count = 0
    for supplier in Supplier.query.all():
        debt = max(0, int(supplier.total_debt or 0) - int(supplier.total_paid or 0))
        if not debt:
            continue
        supplier_debt_count += 1
        supplier_debt_total += debt
        term_days = _payment_term_days_for_supplier(tenant_id, supplier.id, settings_row)
        unpaid = Purchase.query.filter_by(supplier_id=supplier.id, source_module="food").filter(
            Purchase.remaining_total > 0
        ).all()
        overdue_amount = 0
        for purchase in unpaid:
            due_date = _due_date_from_created(purchase.created_at, term_days)
            if due_date and due_date < today:
                overdue_amount += max(0, int(purchase.remaining_total or 0))
        supplier_overdue += overdue_amount

    # Recent activity timeline
    recent = []
    for invoice in Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.source_module == "food",
        ~Invoice.status.in_(("ملغي",)),
    ).order_by(Invoice.created_at.desc()).limit(8).all():
        recent.append({
            "type": "sale",
            "title": f"فاتورة بيع #{invoice.invoice_no or invoice.id}",
            "amount": int(invoice.total or 0),
            "direction": "in",
            "at": invoice.created_at.isoformat(),
            "href": "/food/orders",
        })
    for row in InvoicePaymentLedger.query.filter(
        InvoicePaymentLedger.tenant_id == tenant_id,
        InvoicePaymentLedger.source_module == "food",
        InvoicePaymentLedger.note == "قبض عميل",
    ).order_by(InvoicePaymentLedger.recorded_at.desc()).limit(5).all():
        recent.append({
            "type": "receipt",
            "title": "قبض من عميل",
            "amount": int(row.amount_delta or 0),
            "direction": "in",
            "at": row.recorded_at.isoformat(),
            "href": "/food/finance",
        })
    for row in Purchase.query.filter(
        Purchase.source_module == "food",
    ).order_by(Purchase.created_at.desc()).limit(5).all():
        supplier = db.session.get(Supplier, row.supplier_id)
        recent.append({
            "type": "purchase",
            "title": f"شراء من {supplier.name if supplier else 'مورد'}",
            "amount": int(row.grand_total or row.total or 0),
            "direction": "out",
            "at": row.created_at.isoformat(),
            "href": "/food/purchases",
        })
    for row in SupplierPayment.query.filter(
        SupplierPayment.tenant_id == tenant_id,
        SupplierPayment.source_module == "food",
        SupplierPayment.deleted_at.is_(None),
    ).order_by(SupplierPayment.created_at.desc()).limit(5).all():
        supplier = db.session.get(Supplier, row.supplier_id)
        recent.append({
            "type": "payment",
            "title": f"تسديد للمورد {supplier.name if supplier else ''}".strip(),
            "amount": int(row.amount or 0),
            "direction": "out",
            "at": row.created_at.isoformat(),
            "href": "/food/finance",
        })
    for row in FoodExpense.query.filter_by(tenant_id=tenant_id).order_by(
        FoodExpense.created_at.desc()
    ).limit(5).all():
        recent.append({
            "type": "expense",
            "title": f"مصروف: {row.title}",
            "amount": int(row.amount or 0),
            "direction": "out",
            "at": row.created_at.isoformat() if row.created_at else row.expense_date.isoformat(),
            "href": "/food/finance",
        })
    recent = sorted(recent, key=lambda row: row["at"] or "", reverse=True)[:8]

    alerts = []
    if low_stock:
        alerts.append({
            "level": "warning",
            "text": f"{len(low_stock)} منتج قليل المخزون",
            "href": "/food/inventory",
        })
    if expiry_buckets["within_30"] or expiry_buckets["within_7"] or expiry_buckets["today"]:
        soon = expiry_buckets["today"] + expiry_buckets["within_3"] + expiry_buckets["within_7"] + expiry_buckets["within_30"]
        alerts.append({
            "level": "warning",
            "text": f"{soon} منتج تنتهي صلاحيته خلال 30 يوم",
            "href": "/food/inventory",
        })
    if customer_overdue:
        alerts.append({
            "level": "danger",
            "text": f"{customer_overdue:,} د.ع ديون عملاء متأخرة",
            "href": "/food/customers",
        })
    if supplier_debt_total:
        alerts.append({
            "level": "info",
            "text": f"{supplier_debt_total:,} د.ع مستحق لموردين",
            "href": "/food/suppliers",
        })
    if out_of_stock:
        alerts.append({
            "level": "danger",
            "text": f"{len(out_of_stock)} مادة نافدة من المخزن",
            "href": "/food/inventory",
        })
    if cash.get("difference") not in (None, 0):
        alerts.append({
            "level": "danger",
            "text": f"يوجد فرق بالصندوق {int(cash['difference']):,} د.ع",
            "href": "/food/finance",
        })
    alerts = alerts[:5]

    insights = []
    sales_pct = _pct_change(current["sales_total"], previous["sales_total"])
    if sales_pct is not None:
        direction = "أعلى" if sales_pct >= 0 else "أقل"
        insights.append(f"مبيعات الفترة {direction} من الفترة السابقة بنسبة {abs(sales_pct)}٪.")
    if top_selling:
        top = top_selling[0]
        insights.append(f"{top['product']} هو الأكثر طلباً في الفترة، تأكد من توفره.")
    if customer_debt_count and customer_overdue:
        insights.append(f"{customer_debt_count} عملاء لديهم ذمم، منها متأخر بقيمة {customer_overdue:,} د.ع.")
    elif reorder:
        insights.append(f"{len(reorder)} منتج وصل إلى حد إعادة الطلب.")
    if expiry_value_risk:
        insights.append(f"قيمة المواد المعرضة لانتهاء الصلاحية تبلغ {expiry_value_risk:,} د.ع.")
    if single_day and chart_points:
        peak = max(chart_points, key=lambda row: row["sales"])
        if peak["sales"] > 0:
            insights.append(f"أعلى فترة بيع كانت حوالي الساعة {peak['label']} بقيمة {peak['sales']:,} د.ع.")
    insights = insights[:3]

    compare_label = {
        "today": "عن أمس",
        "yesterday": "عن اليوم السابق",
        "last_7": "عن السبعة أيام السابقة",
        "week": "عن الأسبوع السابق",
        "month": "عن الشهر السابق",
        "last_month": "عن الشهر الذي قبله",
        "custom": "عن الفترة السابقة",
    }.get(key, "عن الفترة السابقة")

    sales_total = current["sales_total"]
    payload = {
        # Legacy flat keys (kept for compatibility)
        "sales_today": sales_total,
        "cash_in_today": cash["total_in"],
        "purchases_today": purchases_total,
        "invoice_count": current["invoice_count"],
        "retail_sales": current["retail"],
        "wholesale_sales": current["wholesale"],
        "mixed_sales": current["mixed"],
        "customer_debt": customer_debt_total,
        "supplier_debt": supplier_debt_total,
        "inventory_value": inventory_cost,
        "low_stock_count": len(low_stock),
        "out_of_stock_count": len(out_of_stock),
        "expiry_warning_count": expiry_warning_count,
        # Rich dashboard payload
        "period": {
            "key": key,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "compare_label": compare_label,
            "generated_at": now_local.isoformat(),
            "server_time": now_local.strftime("%I:%M %p").lstrip("0"),
            "server_date": now_local.strftime("%Y-%m-%d"),
        },
        "permissions": {"view_profit": bool(view_profit)},
        "kpis": {
            "sales": {
                "value": sales_total,
                "previous": previous["sales_total"],
                "change_pct": sales_pct,
                "href": "/food/orders",
            },
            "profit": {
                "value": profit,
                "previous": prev_profit,
                "change_pct": _pct_change(profit or 0, prev_profit or 0) if view_profit else None,
                "available": bool(view_profit),
                "href": "/food/reports",
            },
            "purchases": {
                "value": purchases_total,
                "previous": prev_purchases,
                "change_pct": _pct_change(purchases_total, prev_purchases),
                "href": "/food/purchases",
            },
            "net_cash": {
                "value": cash["net"],
                "previous": prev_cash["net"],
                "change_pct": _pct_change(cash["net"], prev_cash["net"]),
                "href": "/food/finance",
            },
            "invoices": {
                "value": current["invoice_count"],
                "previous": previous["invoice_count"],
                "change": _delta_change(current["invoice_count"], previous["invoice_count"]),
                "href": "/food/orders",
            },
            "avg_invoice": {
                "value": avg_invoice,
                "previous": prev_avg,
                "change_pct": _pct_change(avg_invoice, prev_avg),
                "href": "/food/orders",
            },
        },
        "sales_chart": {
            "granularity": "hour" if single_day else "day",
            "current": chart_points,
            "previous": compare_points if single_day else [],
            "compare_label": "الفترة السابقة" if single_day else None,
        },
        "sales_by_type": {
            "retail": current["retail"],
            "wholesale": current["wholesale"],
            "mixed": current["mixed"],
            "total": sales_total,
        },
        "inventory": {
            "out_of_stock": len(out_of_stock),
            "low_stock": len(low_stock),
            "expiry_soon": expiry_buckets["today"] + expiry_buckets["within_3"] + expiry_buckets["within_7"] + expiry_buckets["within_30"],
            "expired": expiry_buckets["expired"],
            "cost_value": inventory_cost,
            "sell_value": inventory_sell,
            "expected_profit": expected_profit,
            "href": "/food/inventory",
        },
        "cash_flow": cash,
        "receivables": {
            "total": customer_debt_total,
            "overdue": customer_overdue,
            "count": customer_debt_count,
            "href": "/food/customers",
        },
        "payables": {
            "total": supplier_debt_total,
            "overdue": supplier_overdue,
            "count": supplier_debt_count,
            "href": "/food/suppliers",
        },
        "top_products": {
            "best_selling": top_selling[:5],
            "most_profitable": top_profit,
            "slow": dead_stock[:5],
        },
        "dead_stock": {
            "count": len(dead_stock),
            "value": dead_value,
            "days_threshold": 30,
            "items": dead_stock[:3],
            "href": "/food/inventory",
        },
        "expiry": {
            **expiry_buckets,
            "at_risk_value": expiry_value_risk,
            "critical": critical_expiry,
            "href": "/food/inventory",
        },
        "reorder": {
            "items": reorder,
            "href": "/food/purchases",
        },
        "alerts": alerts,
        "recent_activity": recent,
        "insights": insights,
        "backend_requirements": [],
    }
    return payload


def _report_window(range_key: str = "today", start_value=None, end_value=None):
    today = _business_today()
    key = str(range_key or "today").strip().lower().replace("-", "_")
    if key in {"yesterday"}:
        start = end = today - timedelta(days=1)
    elif key in {"last_7", "last_7_days", "7d"}:
        start, end = today - timedelta(days=6), today
        key = "last_7"
    elif key in {"week", "this_week"}:
        start, end = today - timedelta(days=today.weekday()), today
        key = "week"
    elif key in {"month", "this_month"}:
        start, end = today.replace(day=1), today
        key = "month"
    elif key in {"last_month", "previous_month"}:
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
        key = "last_month"
    elif key == "custom":
        try:
            start = date.fromisoformat(str(start_value))
            end = date.fromisoformat(str(end_value))
        except (TypeError, ValueError) as exc:
            raise FoodError("حدد تاريخ بداية ونهاية صالحين") from exc
        if end < start:
            raise FoodError("تاريخ النهاية يجب أن يكون بعد البداية")
    else:
        start = end = today
        key = "today"
    start_dt, end_dt = _local_date_bounds(start, end)
    return key, start, end, start_dt, end_dt


def _previous_window(start: date, end: date) -> tuple[date, date]:
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start, prev_end


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return round(((current - previous) / abs(previous)) * 100.0, 1)


def _delta_change(current: float, previous: float) -> float:
    return current - previous


def _debt_age_bucket(days: int) -> str:
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


def _empty_aging() -> dict:
    return {"0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0}


def reports(
    tenant_id: int,
    range_key="today",
    start_value=None,
    end_value=None,
    *,
    view_profit: bool = True,
) -> dict:
    """Return food-only operational reports for one inclusive date window."""
    key, start, end, start_dt, end_dt = _report_window(range_key, start_value, end_value)
    prev_start, prev_end = _previous_window(start, end)
    prev_start_dt, prev_end_dt = _local_date_bounds(prev_start, prev_end)
    today = _business_today()
    compare_label = {
        "today": "عن أمس",
        "yesterday": "عن اليوم السابق",
        "last_7": "عن السبعة أيام السابقة",
        "week": "عن الأسبوع السابق",
        "month": "عن الشهر السابق",
        "last_month": "عن الشهر الذي قبله",
        "custom": "عن الفترة السابقة",
    }.get(key, "عن الفترة السابقة")

    current = _period_sales_split(tenant_id, start_dt, end_dt)
    previous = _period_sales_split(tenant_id, prev_start_dt, prev_end_dt)
    invoices = current["invoices"]
    partial_returns = current["partial_returns"]
    retail = current["retail"]
    wholesale = current["wholesale"]
    mixed = current["mixed"]
    return_total = sum(int(row.total or 0) for row in partial_returns)
    gross = sum(int(row.total or 0) for row in invoices)
    sales_total = current["sales_total"]

    return_total_by_invoice = {
        invoice_id: int(total or 0)
        for invoice_id, total in db.session.query(
            FoodSaleReturn.invoice_id, func.sum(FoodSaleReturn.total)
        ).filter(FoodSaleReturn.tenant_id == tenant_id).group_by(FoodSaleReturn.invoice_id).all()
    }
    invoice_ids = [row.id for row in invoices]
    modes_by_invoice = {row.id: set() for row in invoices}
    if invoice_ids:
        for invoice_id, mode in db.session.query(OrderItem.invoice_id, FoodSaleItemSnapshot.sale_mode).join(
            FoodSaleItemSnapshot,
            FoodSaleItemSnapshot.order_item_id == OrderItem.id,
        ).filter(OrderItem.invoice_id.in_(invoice_ids)).all():
            modes_by_invoice.setdefault(invoice_id, set()).add(mode)

    sale_rows = []
    for invoice in invoices:
        modes = modes_by_invoice.get(invoice.id) or set()
        label = "مفرد" if modes == {"RETAIL"} else ("جملة" if modes == {"WHOLESALE"} else "مختلط")
        amount = int(invoice.total or 0)
        returned = return_total_by_invoice.get(invoice.id, 0)
        sale_rows.append({
            "id": invoice.id,
            "invoice_no": invoice.invoice_no,
            "customer": invoice.customer_name or "زبون نقدي",
            "sale_mode": label,
            "sale_type": "نقدي" if invoice.sale_type == "cash" else "آجل",
            "total": amount,
            "returned": returned,
            "net": max(0, amount - returned),
            "paid": int(invoice.paid_amount or 0),
            "debt": max(0, amount - returned - int(invoice.paid_amount or 0)),
            "created_at": invoice.created_at.isoformat(),
        })

    return_rows = []
    for sale_return in sorted(partial_returns, key=lambda row: row.created_at or datetime.min, reverse=True):
        invoice = db.session.get(Invoice, sale_return.invoice_id)
        return_rows.append({
            "id": sale_return.id,
            "invoice_id": sale_return.invoice_id,
            "invoice_no": invoice.invoice_no if invoice else sale_return.invoice_id,
            "customer": (invoice.customer_name if invoice else None) or "—",
            "total": int(sale_return.total or 0),
            "created_at": sale_return.created_at.isoformat() if sale_return.created_at else None,
        })

    cash = _period_cash(tenant_id, start_dt, end_dt)
    prev_cash = _period_cash(tenant_id, prev_start_dt, prev_end_dt)
    profit = _period_profit(tenant_id, start_dt, end_dt) if view_profit else None
    prev_profit = _period_profit(tenant_id, prev_start_dt, prev_end_dt) if view_profit else None
    avg_invoice = int(sales_total / current["invoice_count"]) if current["invoice_count"] else 0
    prev_avg = int(previous["sales_total"] / previous["invoice_count"]) if previous["invoice_count"] else 0

    chart_points = []
    compare_points = []
    single_day = start == end
    if single_day:
        hour_totals = {h: {"sales": 0, "count": 0} for h in range(24)}
        for invoice in invoices:
            local_ts = invoice.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            hour_totals[local_ts.hour]["sales"] += int(invoice.total or 0)
            hour_totals[local_ts.hour]["count"] += 1
        for sale_return in partial_returns:
            local_ts = sale_return.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            hour_totals[local_ts.hour]["sales"] -= int(sale_return.total or 0)
        prev_hours = {h: 0 for h in range(24)}
        for invoice in previous["invoices"]:
            local_ts = invoice.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            prev_hours[local_ts.hour] += int(invoice.total or 0)
        for hour in range(24):
            label_hour = hour % 12 or 12
            suffix = "ص" if hour < 12 else "م"
            chart_points.append({
                "label": f"{label_hour} {suffix}",
                "sales": max(0, hour_totals[hour]["sales"]),
                "invoices": hour_totals[hour]["count"],
            })
            compare_points.append({"label": f"{label_hour} {suffix}", "sales": prev_hours[hour]})
    else:
        day_count = (end - start).days + 1
        day_totals = {
            (start + timedelta(days=offset)).isoformat(): {"sales": 0, "count": 0}
            for offset in range(day_count)
        }
        for invoice in invoices:
            local_ts = invoice.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            key_day = local_ts.date().isoformat()
            if key_day in day_totals:
                day_totals[key_day]["sales"] += int(invoice.total or 0)
                day_totals[key_day]["count"] += 1
        for sale_return in partial_returns:
            local_ts = sale_return.created_at.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE)
            key_day = local_ts.date().isoformat()
            if key_day in day_totals:
                day_totals[key_day]["sales"] = max(0, day_totals[key_day]["sales"] - int(sale_return.total or 0))
        for key_day, bucket in day_totals.items():
            day = date.fromisoformat(key_day)
            chart_points.append({
                "label": day.strftime("%d/%m"),
                "date": key_day,
                "sales": bucket["sales"],
                "invoices": bucket["count"],
            })

    top_line_rows = db.session.query(
        FoodSaleItemSnapshot.variant_id,
        FoodSaleItemSnapshot.quantity_base,
        FoodSaleItemSnapshot.line_total_snapshot,
        FoodSaleItemSnapshot.cost_snapshot,
        FoodSaleItemSnapshot.quantity_snapshot,
        FoodSaleItemSnapshot.unit_factor_snapshot,
    ).join(OrderItem, OrderItem.id == FoodSaleItemSnapshot.order_item_id).join(
        Invoice, Invoice.id == OrderItem.invoice_id
    ).filter(
        FoodSaleItemSnapshot.tenant_id == tenant_id,
        Invoice.source_module == "food",
        Invoice.created_at >= start_dt,
        Invoice.created_at < end_dt,
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    products = list_products(tenant_id)
    product_map = {row["id"]: row for row in products}
    top_agg: dict[int, dict] = {}
    for variant_id, qty_base, line_total, cost, qty_snap, factor in top_line_rows:
        bucket = top_agg.setdefault(variant_id, {"qty": 0, "sales": 0, "profit": 0})
        quantity = float(qty_snap) if qty_snap is not None else (
            float(qty_base or 0) / float(factor or 1)
        )
        revenue = int(line_total or 0)
        bucket["qty"] += int(qty_base or 0)
        bucket["sales"] += revenue
        bucket["profit"] += revenue - int(round(int(cost or 0) * quantity))

    def _product_row(variant_id, qty, sales_amount, profit_amount=None):
        product = product_map.get(variant_id) or {}
        return {
            "variant_id": variant_id,
            "product": product.get("product_name") or "—",
            "variant": product.get("variant_name") or "",
            "quantity_base": int(qty or 0),
            "sales": int(sales_amount or 0),
            "profit": int(profit_amount or 0) if view_profit else None,
        }

    top_by_qty = [
        _product_row(variant_id, data["qty"], data["sales"], data["profit"])
        for variant_id, data in sorted(top_agg.items(), key=lambda item: item[1]["qty"], reverse=True)[:15]
    ]
    top_by_sales = [
        _product_row(variant_id, data["qty"], data["sales"], data["profit"])
        for variant_id, data in sorted(top_agg.items(), key=lambda item: item[1]["sales"], reverse=True)[:15]
    ]
    top_by_profit = [
        _product_row(variant_id, data["qty"], data["sales"], data["profit"])
        for variant_id, data in sorted(top_agg.items(), key=lambda item: item[1]["profit"], reverse=True)[:15]
    ] if view_profit else []

    customer_rows = []
    customer_aging = _empty_aging()
    for customer in Customer.query.filter_by(tenant_id=tenant_id).order_by(Customer.name).all():
        customer_invoices = Invoice.query.filter_by(
            tenant_id=tenant_id, customer_id=customer.id, source_module="food"
        ).order_by(Invoice.created_at).all()
        debt_invoices = [
            row for row in customer_invoices
            if int(row.total or 0) - return_total_by_invoice.get(row.id, 0) > int(row.paid_amount or 0)
            and row.status != "ملغي"
        ]
        debt = sum(
            max(0, int(row.total or 0) - return_total_by_invoice.get(row.id, 0) - int(row.paid_amount or 0))
            for row in debt_invoices
        )
        if not debt:
            continue
        oldest = debt_invoices[0].created_at if debt_invoices else None
        oldest_local = (
            oldest.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date()
            if oldest else today
        )
        age_days = max(0, (today - oldest_local).days)
        bucket = _debt_age_bucket(age_days)
        customer_aging[bucket] += debt
        latest_receipt = InvoicePaymentLedger.query.join(Invoice).filter(
            Invoice.customer_id == customer.id,
            Invoice.tenant_id == tenant_id,
            InvoicePaymentLedger.source_module == "food",
            InvoicePaymentLedger.note == "قبض عميل",
        ).order_by(InvoicePaymentLedger.recorded_at.desc()).first()
        customer_rows.append({
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "debt": debt,
            "age_days": age_days,
            "age_bucket": bucket,
            "last_invoice": customer_invoices[-1].created_at.isoformat() if customer_invoices else None,
            "last_receipt": latest_receipt.recorded_at.isoformat() if latest_receipt else None,
            "oldest_debt": oldest.isoformat() if oldest else None,
        })
    customer_rows.sort(key=lambda row: row["debt"], reverse=True)

    supplier_rows = []
    supplier_aging = _empty_aging()
    for supplier in Supplier.query.order_by(Supplier.name).all():
        debt = max(0, int(supplier.total_debt or 0) - int(supplier.total_paid or 0))
        food_purchases = Purchase.query.filter_by(
            supplier_id=supplier.id, source_module="food"
        ).order_by(Purchase.created_at).all()
        if not debt and not food_purchases:
            continue
        oldest_due_row = next((row for row in food_purchases if int(row.remaining_total or 0) > 0), None)
        oldest_due = oldest_due_row.created_at if oldest_due_row else None
        age_days = 0
        bucket = "0_30"
        if oldest_due:
            oldest_local = oldest_due.replace(tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date()
            age_days = max(0, (today - oldest_local).days)
            bucket = _debt_age_bucket(age_days)
            if debt:
                supplier_aging[bucket] += debt
        latest_payment = SupplierPayment.query.filter_by(
            tenant_id=tenant_id, supplier_id=supplier.id, source_module="food"
        ).filter(SupplierPayment.deleted_at.is_(None)).order_by(SupplierPayment.created_at.desc()).first()
        supplier_rows.append({
            "id": supplier.id,
            "name": supplier.name,
            "debt": debt,
            "age_days": age_days,
            "age_bucket": bucket,
            "last_purchase": food_purchases[-1].created_at.isoformat() if food_purchases else None,
            "last_payment": latest_payment.created_at.isoformat() if latest_payment else None,
            "oldest_due": oldest_due.isoformat() if oldest_due else None,
        })
    supplier_rows.sort(key=lambda row: row["debt"], reverse=True)

    purchases = Purchase.query.filter(
        Purchase.source_module == "food",
        Purchase.created_at >= start_dt,
        Purchase.created_at < end_dt,
    ).order_by(Purchase.created_at.desc()).all()
    purchase_rows = []
    for row in purchases:
        supplier = db.session.get(Supplier, row.supplier_id)
        purchase_rows.append({
            "id": row.id,
            "invoice_no": row.invoice_no,
            "supplier": supplier.name if supplier else "—",
            "total": int(row.grand_total or row.total or 0),
            "paid": int(row.paid_total or 0),
            "remaining": int(row.remaining_total or 0),
            "created_at": row.created_at.isoformat(),
        })
    purchases_total = sum(row["total"] for row in purchase_rows)
    prev_purchases = int(db.session.query(func.coalesce(func.sum(Purchase.grand_total), 0)).filter(
        Purchase.source_module == "food",
        Purchase.created_at >= prev_start_dt,
        Purchase.created_at < prev_end_dt,
    ).scalar() or 0)

    inventory_data = inventory(tenant_id)
    movement_total = func.sum(func.abs(FoodInventoryMovement.quantity_base))
    movement_totals = db.session.query(FoodInventoryMovement.variant_id, movement_total).filter(
        FoodInventoryMovement.tenant_id == tenant_id,
        FoodInventoryMovement.created_at >= start_dt,
        FoodInventoryMovement.created_at < end_dt,
    ).group_by(FoodInventoryMovement.variant_id).order_by(movement_total.desc()).limit(20).all()
    product_by_variant = {row["id"]: row for row in inventory_data["products"]}
    top_movement = [{
        "variant_id": variant_id,
        "product": (product_by_variant.get(variant_id) or {}).get("product_name", "—"),
        "variant": (product_by_variant.get(variant_id) or {}).get("variant_name", "—"),
        "quantity_base": int(total or 0),
    } for variant_id, total in movement_totals]
    tracked = [row for row in inventory_data["products"] if row.get("track_stock")]
    inventory_value = sum(int(row["stock_base"]) * int(row["average_cost"]) for row in tracked)
    out_of_stock = [row for row in tracked if int(row["stock_base"] or 0) <= 0]

    cash_sales_amount = sum(int(row.total or 0) for row in invoices if row.sale_type == "cash")
    credit_sales_amount = sum(int(row.total or 0) for row in invoices if row.sale_type != "cash")

    return {
        "range": {
            "key": key,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "compare_start": prev_start.isoformat(),
            "compare_end": prev_end.isoformat(),
            "compare_label": compare_label,
        },
        "permissions": {"view_profit": bool(view_profit)},
        "summary": {
            "sales": sales_total,
            "sales_change_pct": _pct_change(sales_total, previous["sales_total"]),
            "invoices": current["invoice_count"],
            "invoices_change": _delta_change(current["invoice_count"], previous["invoice_count"]),
            "avg_invoice": avg_invoice,
            "avg_invoice_change_pct": _pct_change(avg_invoice, prev_avg),
            "profit": profit,
            "profit_change_pct": _pct_change(profit or 0, prev_profit or 0) if view_profit else None,
            "purchases": purchases_total,
            "purchases_change_pct": _pct_change(purchases_total, prev_purchases),
            "net_cash": cash["net"],
            "net_cash_change_pct": _pct_change(cash["net"], prev_cash["net"]),
            "returns": return_total,
            "customer_debt": sum(row["debt"] for row in customer_rows),
            "supplier_debt": sum(row["debt"] for row in supplier_rows if row["debt"] > 0),
        },
        "chart": {
            "granularity": "hour" if single_day else "day",
            "current": chart_points,
            "previous": compare_points,
            "compare_label": compare_label if single_day else None,
        },
        "sales": {
            "total": sales_total,
            "gross": gross,
            "returns": return_total,
            "count": current["invoice_count"],
            "avg_invoice": avg_invoice,
            "retail": max(0, retail),
            "wholesale": max(0, wholesale),
            "mixed": max(0, mixed),
            "cash": cash_sales_amount,
            "credit": credit_sales_amount,
            "previous_total": previous["sales_total"],
            "change_pct": _pct_change(sales_total, previous["sales_total"]),
            "rows": sale_rows,
            "return_rows": return_rows,
        },
        "cash": {
            "cash_sales": cash["cash_sales"],
            "customer_receipts": cash["customer_receipts"],
            "other_in": 0,
            "total_in": cash["total_in"],
            "supplier_payments": cash["supplier_payments"],
            "expenses": cash["expenses"],
            "other_out": 0,
            "total_out": cash["total_out"],
            "net": cash["net"],
            "opening_balance": cash.get("opening_balance"),
            "expected_balance": cash.get("expected_balance"),
            "actual_balance": cash.get("actual_balance"),
            "difference": cash.get("difference"),
            "change_pct": _pct_change(cash["net"], prev_cash["net"]),
        },
        "customer_debts": {
            "total": sum(row["debt"] for row in customer_rows),
            "count": len(customer_rows),
            "aging": customer_aging,
            "rows": customer_rows,
        },
        "supplier_debts": {
            "total": sum(row["debt"] for row in supplier_rows if row["debt"] > 0),
            "count": len([row for row in supplier_rows if row["debt"] > 0]),
            "aging": supplier_aging,
            "rows": supplier_rows,
        },
        "purchases": {
            "total": purchases_total,
            "count": len(purchase_rows),
            "paid": sum(row["paid"] for row in purchase_rows),
            "remaining": sum(row["remaining"] for row in purchase_rows),
            "change_pct": _pct_change(purchases_total, prev_purchases),
            "rows": purchase_rows,
        },
        "inventory": {
            "value": inventory_value,
            "sku_count": len(tracked),
            "low_stock": inventory_data["low_stock"],
            "out_of_stock": out_of_stock,
            "top_movement": top_movement,
        },
        "top_products": {
            "by_quantity": top_by_qty,
            "by_sales": top_by_sales,
            "by_profit": top_by_profit,
        },
        "profit": {
            "value": profit,
            "previous": prev_profit,
            "change_pct": _pct_change(profit or 0, prev_profit or 0) if view_profit else None,
            "available": bool(view_profit),
            "margin_pct": round((profit / sales_total) * 100, 1) if view_profit and sales_total and profit is not None else None,
        },
    }


def _finance_document_no(prefix: str, supplied=None) -> str:
    value = str(supplied or "").strip()
    if value:
        return value[:100]
    return f"{prefix}-{_business_today():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _pack_finance_note(label: str, document_number: str, note=None) -> str:
    parts = [label, f"[[FINORA-DOC:{document_number}]]"]
    clean_note = str(note or "").strip()
    if clean_note:
        parts.append(clean_note[:500])
    return "\n".join(parts)


def _unpack_finance_note(raw, label: str = "") -> tuple[str | None, str | None]:
    document_number = None
    clean_lines = []
    for line in str(raw or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("[[FINORA-DOC:") and stripped.endswith("]] "):
            # Compatibility with an early spaced marker, if one ever existed.
            document_number = stripped[13:-3].strip() or None
        elif stripped.startswith("[[FINORA-DOC:") and stripped.endswith("]]" ):
            document_number = stripped[13:-2].strip() or None
        elif stripped and stripped != label:
            clean_lines.append(stripped)
    return document_number, ("\n".join(clean_lines) or None)


def record_customer_receipt(
    tenant_id: int,
    customer_id: int,
    amount: int,
    document_number=None,
    note=None,
) -> dict:
    customer = Customer.query.filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        raise FoodError("العميل غير موجود")
    remaining = as_int(amount, 0, minimum=1)
    applied = 0
    document_number = _finance_document_no("RCV", document_number)
    ledger_note = _pack_finance_note("قبض عميل", document_number, note)
    invoices = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.customer_id == customer_id,
        Invoice.source_module == "food",
        Invoice.status != "ملغي",
    ).order_by(Invoice.created_at).all()
    returned = {
        invoice_id: int(total or 0)
        for invoice_id, total in db.session.query(
            FoodSaleReturn.invoice_id, func.sum(FoodSaleReturn.total)
        ).filter(FoodSaleReturn.tenant_id == tenant_id).group_by(FoodSaleReturn.invoice_id).all()
    }
    for invoice in invoices:
        due = max(0, int(invoice.total or 0) - returned.get(invoice.id, 0) - int(invoice.paid_amount or 0))
        portion = min(due, remaining)
        if not portion:
            continue
        invoice.paid_amount = int(invoice.paid_amount or 0) + portion
        invoice.payment_status = "مسدد" if invoice.paid_amount >= invoice.total else "جزئي"
        db.session.add(InvoicePaymentLedger(
            tenant_id=tenant_id, invoice_id=invoice.id, source_module="food",
            payment_method="cash", amount_delta=portion, note=ledger_note,
        ))
        remaining -= portion
        applied += portion
        if not remaining:
            break
    if not applied:
        raise FoodError("لا توجد ذمة مستحقة على العميل")
    return {"applied": applied, "document_number": document_number}


def record_supplier_payment(
    tenant_id: int,
    supplier_id: int,
    amount: int,
    document_number=None,
    note=None,
) -> dict:
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        raise FoodError("المورد غير موجود")
    due = max(0, int(supplier.total_debt or 0) - int(supplier.total_paid or 0))
    paid = min(due, as_int(amount, 0, minimum=1))
    if not paid:
        raise FoodError("لا توجد ذمة مستحقة للمورد")
    supplier.total_paid = int(supplier.total_paid or 0) + paid
    document_number = _finance_document_no("PAY", document_number)
    db.session.add(SupplierPayment(
        supplier_id=supplier.id, tenant_id=tenant_id, amount=paid,
        source_module="food", note=str(note or "").strip()[:255] or "تسديد مورد",
        document_number=document_number,
    ))
    return {"applied": paid, "document_number": document_number}


# ---------------------------------------------------------------------------
# Food invoices management center (list / detail / payment / void)
# ---------------------------------------------------------------------------

_PAYMENT_METHOD_LABELS = {
    "cash": "نقدي",
    "card": "بطاقة",
    "transfer": "تحويل",
    "credit": "آجل",
    "mixed": "مختلط",
}

_SALE_MIX_LABELS = {
    "RETAIL": "مفرد",
    "WHOLESALE": "جملة",
    "MIXED": "مختلط",
    "—": "—",
}


def _return_totals_map(tenant_id: int, invoice_ids: list[int] | None = None) -> dict[int, int]:
    query = db.session.query(
        FoodSaleReturn.invoice_id, func.coalesce(func.sum(FoodSaleReturn.total), 0)
    ).filter(FoodSaleReturn.tenant_id == tenant_id)
    if invoice_ids is not None:
        if not invoice_ids:
            return {}
        query = query.filter(FoodSaleReturn.invoice_id.in_(invoice_ids))
    return {int(invoice_id): int(total or 0) for invoice_id, total in query.group_by(FoodSaleReturn.invoice_id)}


def _sale_mix_map(invoice_ids: list[int]) -> dict[int, str]:
    if not invoice_ids:
        return {}
    modes: dict[int, set] = {int(i): set() for i in invoice_ids}
    for invoice_id, mode in db.session.query(OrderItem.invoice_id, FoodSaleItemSnapshot.sale_mode).join(
        FoodSaleItemSnapshot, FoodSaleItemSnapshot.order_item_id == OrderItem.id
    ).filter(OrderItem.invoice_id.in_(invoice_ids)).all():
        modes.setdefault(int(invoice_id), set()).add(str(mode or "").upper())
    result = {}
    for invoice_id, values in modes.items():
        cleaned = {v for v in values if v}
        if cleaned == {"RETAIL"}:
            result[invoice_id] = "RETAIL"
        elif cleaned == {"WHOLESALE"}:
            result[invoice_id] = "WHOLESALE"
        elif cleaned:
            result[invoice_id] = "MIXED"
        else:
            result[invoice_id] = "—"
    return result


def _item_counts_map(invoice_ids: list[int]) -> dict[int, int]:
    if not invoice_ids:
        return {}
    rows = db.session.query(OrderItem.invoice_id, func.count(OrderItem.id)).filter(
        OrderItem.invoice_id.in_(invoice_ids)
    ).group_by(OrderItem.invoice_id).all()
    return {int(invoice_id): int(count or 0) for invoice_id, count in rows}


def _payment_methods_map(tenant_id: int, invoice_ids: list[int]) -> dict[int, list[str]]:
    if not invoice_ids:
        return {}
    rows = db.session.query(
        InvoicePaymentLedger.invoice_id, InvoicePaymentLedger.payment_method
    ).filter(
        InvoicePaymentLedger.tenant_id == tenant_id,
        InvoicePaymentLedger.invoice_id.in_(invoice_ids),
        InvoicePaymentLedger.amount_delta > 0,
    ).all()
    result: dict[int, list[str]] = {}
    for invoice_id, method in rows:
        key = str(method or "cash").lower()
        bucket = result.setdefault(int(invoice_id), [])
        if key not in bucket:
            bucket.append(key)
    return result


def _invoice_display_status(invoice: Invoice, return_total: int) -> tuple[str, str]:
    status = str(invoice.status or "")
    if status == "ملغي":
        return "void", "ملغاة"
    if status == "راجع":
        return "full_return", "مرتجع كامل"
    net = max(0, int(invoice.total or 0) - int(return_total or 0))
    paid = int(invoice.paid_amount or 0)
    remaining = max(0, net - paid)
    if return_total > 0:
        return "partial_return", "مرتجع جزئي"
    if remaining <= 0:
        return "completed", "مكتملة"
    if paid > 0:
        return "partial", "جزئي"
    return "credit", "آجل"


def _payment_label(methods: list[str], remaining: int, paid: int) -> str:
    if remaining > 0 and paid <= 0:
        return "آجل"
    cleaned = [m for m in methods if m and m != "credit"]
    if not cleaned:
        return "آجل" if remaining > 0 else "نقدي"
    if len(cleaned) > 1:
        return "مختلط"
    return _PAYMENT_METHOD_LABELS.get(cleaned[0], cleaned[0])


def _is_walk_in(invoice: Invoice, customer: Customer | None) -> bool:
    phone = str((customer.phone if customer else None) or "").strip()
    name = str(invoice.customer_name or (customer.name if customer else "") or "").strip()
    return phone == "FOOD-WALK-IN" or name in {"زبون نقدي", "عميل نقدي"} or not invoice.customer_id


def invoice_filter_options(tenant_id: int) -> dict:
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name).all()
    cashier_ids = [
        row[0] for row in db.session.query(Invoice.employee_id).filter(
            Invoice.tenant_id == tenant_id,
            Invoice.source_module == "food",
            Invoice.employee_id.isnot(None),
        ).distinct().all()
    ]
    cashiers = []
    if cashier_ids:
        cashiers = Employee.query.filter(Employee.id.in_(cashier_ids)).order_by(Employee.name).all()
    return {
        "branches": [{"id": row.id, "name": row.name} for row in branches],
        "cashiers": [{"id": row.id, "name": row.name} for row in cashiers],
        "permissions": {
            "view": True,
            "create": _employee_can(None, "cashier.sell") or True,
            "receive_payment": True,
            "return": True,
            "void": True,
            "reprint": True,
            "view_cost": False,
            "view_profit": False,
            "export": True,
        },
    }


def _food_invoices_base_query(tenant_id: int, filters: dict):
    query = Invoice.query.outerjoin(Customer, Customer.id == Invoice.customer_id).filter(
        Invoice.tenant_id == tenant_id,
        Invoice.source_module == "food",
    )
    start_dt = filters.get("start_dt")
    end_dt = filters.get("end_dt")
    if start_dt is not None:
        query = query.filter(Invoice.created_at >= start_dt)
    if end_dt is not None:
        query = query.filter(Invoice.created_at < end_dt)

    branch_id = as_int(filters.get("branch_id"), 0) or None
    if branch_id:
        query = query.filter(or_(Invoice.branch_id == branch_id, Invoice.warehouse_id == branch_id))

    cashier_id = as_int(filters.get("cashier_id"), 0) or None
    if cashier_id:
        query = query.filter(Invoice.employee_id == cashier_id)

    term = str(filters.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        product_match = db.session.query(OrderItem.invoice_id).join(
            FoodSaleItemSnapshot, FoodSaleItemSnapshot.order_item_id == OrderItem.id
        ).outerjoin(
            FoodProductVariant, FoodProductVariant.id == FoodSaleItemSnapshot.variant_id
        ).outerjoin(
            FoodProductProfile, FoodProductProfile.id == FoodProductVariant.profile_id
        ).outerjoin(
            Product, Product.id == FoodProductProfile.product_id
        ).outerjoin(
            FoodProductBarcode, FoodProductBarcode.unit_id == FoodSaleItemSnapshot.unit_id
        ).filter(
            FoodSaleItemSnapshot.tenant_id == tenant_id,
            or_(
                FoodSaleItemSnapshot.barcode_snapshot == term,
                FoodProductBarcode.barcode == term,
                FoodSaleItemSnapshot.product_name_snapshot.ilike(like),
                FoodSaleItemSnapshot.variant_name_snapshot.ilike(like),
                Product.name.ilike(like),
                FoodProductVariant.sku.ilike(like),
            ),
        )
        # Exact barcode / invoice number first path avoids broad LIKE when possible.
        exact = or_(
            Invoice.invoice_no == term,
            Invoice.barcode == term,
            Invoice.invoice_no.ilike(like),
            Invoice.barcode.ilike(like),
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
            Invoice.customer_name.ilike(like),
            Invoice.id.in_(product_match),
        )
        query = query.filter(exact)
    return query


def _apply_status_and_type_filters(query, tenant_id: int, filters: dict):
    """Apply status tab / payment / sale-type filters that need derived fields."""
    status_tab = str(filters.get("status_tab") or filters.get("status") or "all").strip().lower()
    payment_method = str(filters.get("payment_method") or "").strip().lower()
    sale_type = str(filters.get("sale_type") or "").strip().upper()
    invoice_status = str(filters.get("invoice_status") or "").strip().lower()

    if status_tab in {"void", "cancelled", "ملغاة"} or invoice_status in {"void", "cancelled"}:
        return query.filter(Invoice.status == "ملغي")
    if status_tab in {"returns", "return", "مرتجعات"} or invoice_status in {"returns", "partial_return", "full_return"}:
        returned_ids = db.session.query(FoodSaleReturn.invoice_id).filter(
            FoodSaleReturn.tenant_id == tenant_id
        )
        if invoice_status == "full_return" or status_tab == "full_return":
            return query.filter(Invoice.status == "راجع")
        if invoice_status == "partial_return":
            return query.filter(Invoice.id.in_(returned_ids), Invoice.status != "راجع", Invoice.status != "ملغي")
        return query.filter(or_(Invoice.status == "راجع", Invoice.id.in_(returned_ids)))

    query = query.filter(Invoice.status != "ملغي")

    if status_tab in {"completed", "مكتملة"} or invoice_status == "completed":
        returned_ids = db.session.query(FoodSaleReturn.invoice_id).filter(
            FoodSaleReturn.tenant_id == tenant_id
        )
        query = query.filter(
            Invoice.status != "راجع",
            ~Invoice.id.in_(returned_ids),
            Invoice.payment_status == "مسدد",
        )
    elif status_tab in {"due", "credit", "partial", "مستحق", "آجل"} or invoice_status in {
        "due", "credit", "partial", "unpaid"
    }:
        returned_ids = db.session.query(FoodSaleReturn.invoice_id).filter(
            FoodSaleReturn.tenant_id == tenant_id
        )
        query = query.filter(
            Invoice.status != "راجع",
            or_(
                Invoice.payment_status.in_(("غير مسدد", "جزئي")),
                Invoice.sale_type.in_(("credit", "partial")),
            ),
        )
        if invoice_status == "credit" or status_tab == "credit":
            query = query.filter(Invoice.payment_status == "غير مسدد")
        elif invoice_status == "partial" or status_tab == "partial":
            query = query.filter(Invoice.payment_status == "جزئي")

    if payment_method and payment_method not in {"all", "الكل", ""}:
        if payment_method == "credit":
            query = query.filter(or_(
                Invoice.payment_status == "غير مسدد",
                Invoice.sale_type == "credit",
            ))
        elif payment_method == "mixed":
            # Invoices with more than one positive payment method.
            multi = db.session.query(InvoicePaymentLedger.invoice_id).filter(
                InvoicePaymentLedger.tenant_id == tenant_id,
                InvoicePaymentLedger.amount_delta > 0,
            ).group_by(InvoicePaymentLedger.invoice_id).having(
                func.count(func.distinct(InvoicePaymentLedger.payment_method)) > 1
            )
            query = query.filter(Invoice.id.in_(multi))
        else:
            paid_ids = db.session.query(InvoicePaymentLedger.invoice_id).filter(
                InvoicePaymentLedger.tenant_id == tenant_id,
                InvoicePaymentLedger.payment_method == payment_method,
                InvoicePaymentLedger.amount_delta > 0,
            )
            query = query.filter(Invoice.id.in_(paid_ids))

    if sale_type and sale_type not in {"ALL", "الكل", ""}:
        # Restrict mix classification to the already-filtered query window.
        candidate_ids = [row.id for row in query.with_entities(Invoice.id).all()]
        if not candidate_ids:
            return query.filter(Invoice.id == -1)
        mode_rows = db.session.query(OrderItem.invoice_id, FoodSaleItemSnapshot.sale_mode).join(
            FoodSaleItemSnapshot, FoodSaleItemSnapshot.order_item_id == OrderItem.id
        ).filter(OrderItem.invoice_id.in_(candidate_ids))
        by_invoice: dict[int, set] = {}
        for invoice_id, mode in mode_rows.all():
            by_invoice.setdefault(int(invoice_id), set()).add(str(mode or "").upper())
        matched = []
        for invoice_id, modes in by_invoice.items():
            if sale_type == "RETAIL" and modes == {"RETAIL"}:
                matched.append(invoice_id)
            elif sale_type == "WHOLESALE" and modes == {"WHOLESALE"}:
                matched.append(invoice_id)
            elif sale_type == "MIXED" and len(modes) > 1:
                matched.append(invoice_id)
        return query.filter(Invoice.id.in_(matched or [-1]))

    return query


def _serialize_invoice_row(
    invoice: Invoice,
    *,
    return_total: int,
    sale_mix: str,
    item_count: int,
    methods: list[str],
    customer: Customer | None = None,
) -> dict:
    net = max(0, int(invoice.total or 0) - int(return_total or 0))
    paid = int(invoice.paid_amount or 0)
    remaining = max(0, net - paid)
    status_key, status_label = _invoice_display_status(invoice, return_total)
    walk_in = _is_walk_in(invoice, customer)
    return {
        "id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "barcode": invoice.barcode,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "customer_id": None if walk_in else invoice.customer_id,
        "customer_name": "عميل نقدي" if walk_in else (invoice.customer_name or (customer.name if customer else "عميل نقدي")),
        "customer_phone": None if walk_in else (customer.phone if customer else None),
        "sale_type": sale_mix,
        "sale_type_label": _SALE_MIX_LABELS.get(sale_mix, sale_mix),
        "payment_method": _payment_label(methods, remaining, paid),
        "payment_methods": methods,
        "item_count": item_count,
        "total": int(invoice.total or 0),
        "return_total": int(return_total or 0),
        "net_total": net,
        "paid": paid,
        "remaining": remaining,
        "status": status_key,
        "status_label": status_label,
        "payment_status": invoice.payment_status,
        "cashier_id": invoice.employee_id,
        "cashier_name": invoice.employee_name,
        "branch_id": invoice.branch_id or invoice.warehouse_id,
        "warehouse_id": invoice.warehouse_id,
        "print_url": f"/orders/invoice/{invoice.id}",
    }


def list_invoices(tenant_id: int, filters: dict | None = None) -> dict:
    filters = dict(filters or {})
    range_key = filters.get("range") or "today"
    key, start, end, start_dt, end_dt = _report_window(
        range_key, filters.get("start"), filters.get("end")
    )
    filters["start_dt"] = start_dt
    filters["end_dt"] = end_dt

    page = max(1, as_int(filters.get("page"), 1))
    page_size = as_int(filters.get("page_size") or filters.get("per_page"), 20)
    page_size = min(100, max(1, page_size))

    base = _food_invoices_base_query(tenant_id, filters)
    filtered = _apply_status_and_type_filters(base, tenant_id, filters)
    total = filtered.count()
    rows = (
        filtered.order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    invoice_ids = [row.id for row in rows]
    returns = _return_totals_map(tenant_id, invoice_ids)
    mixes = _sale_mix_map(invoice_ids)
    counts = _item_counts_map(invoice_ids)
    methods = _payment_methods_map(tenant_id, invoice_ids)
    customers = {
        c.id: c for c in Customer.query.filter(
            Customer.id.in_([r.customer_id for r in rows if r.customer_id])
        ).all()
    } if rows else {}

    serialized = [
        _serialize_invoice_row(
            row,
            return_total=returns.get(row.id, 0),
            sale_mix=mixes.get(row.id, "—"),
            item_count=counts.get(row.id, 0),
            methods=methods.get(row.id, []),
            customer=customers.get(row.customer_id) if row.customer_id else None,
        )
        for row in rows
    ]

    # KPI cards follow the same date/branch/cashier/search window, not status tab.
    kpi_filters = dict(filters)
    kpi_filters.pop("status_tab", None)
    kpi_filters.pop("status", None)
    kpi_filters.pop("invoice_status", None)
    kpi_base = _food_invoices_base_query(tenant_id, kpi_filters)
    kpi_base = kpi_base.filter(Invoice.status != "ملغي")
    kpis = _invoice_kpis(tenant_id, kpi_base, start_dt, end_dt, start, end)

    # Tab counters for the same filter window (except status tab itself).
    tab_base = _food_invoices_base_query(tenant_id, {
        **filters, "status_tab": "all", "invoice_status": "", "status": "all"
    })
    returned_ids = db.session.query(FoodSaleReturn.invoice_id).filter(
        FoodSaleReturn.tenant_id == tenant_id
    )
    tabs = {
        "all": tab_base.count(),
        "completed": tab_base.filter(
            Invoice.status != "ملغي",
            Invoice.status != "راجع",
            ~Invoice.id.in_(returned_ids),
            Invoice.payment_status == "مسدد",
        ).count(),
        "due": tab_base.filter(
            Invoice.status != "ملغي",
            Invoice.status != "راجع",
            Invoice.payment_status.in_(("غير مسدد", "جزئي")),
        ).count(),
        "returns": tab_base.filter(
            or_(Invoice.status == "راجع", Invoice.id.in_(returned_ids))
        ).count(),
        "void": tab_base.filter(Invoice.status == "ملغي").count(),
    }

    return {
        "rows": serialized,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
        "range": {"key": key, "start": start.isoformat(), "end": end.isoformat()},
        "kpis": kpis,
        "tabs": tabs,
    }


def _invoice_kpis(tenant_id: int, query, start_dt, end_dt, start: date, end: date) -> dict:
    invoices = query.filter(Invoice.status != "راجع").all()
    invoice_ids = [row.id for row in invoices]
    returns_in_period = FoodSaleReturn.query.filter(
        FoodSaleReturn.tenant_id == tenant_id,
        FoodSaleReturn.created_at >= start_dt,
        FoodSaleReturn.created_at < end_dt,
    ).all()
    return_total = sum(int(row.total or 0) for row in returns_in_period)
    all_returns = _return_totals_map(tenant_id, invoice_ids)
    gross = sum(int(row.total or 0) for row in invoices)
    # Period returns card uses returns created in the window; sales net those returns.
    sales = max(0, gross - return_total)
    paid = sum(int(invoice.paid_amount or 0) for invoice in invoices)
    remaining = sum(
        max(0, int(row.total or 0) - all_returns.get(row.id, 0) - int(row.paid_amount or 0))
        for row in invoices
    )
    count = len(invoices)
    avg = int(round(sales / count)) if count else 0

    prev_start, prev_end = _previous_window(start, end)
    prev_start_dt, prev_end_dt = _local_date_bounds(prev_start, prev_end)
    prev_invoices = Invoice.query.filter(
        Invoice.tenant_id == tenant_id,
        Invoice.source_module == "food",
        Invoice.created_at >= prev_start_dt,
        Invoice.created_at < prev_end_dt,
        ~Invoice.status.in_(("ملغي", "راجع")),
    ).all()
    prev_returns = sum(
        int(row.total or 0) for row in FoodSaleReturn.query.filter(
            FoodSaleReturn.tenant_id == tenant_id,
            FoodSaleReturn.created_at >= prev_start_dt,
            FoodSaleReturn.created_at < prev_end_dt,
        ).all()
    )
    prev_gross = sum(int(row.total or 0) for row in prev_invoices)
    prev_sales = max(0, prev_gross - prev_returns)
    prev_paid = sum(int(row.paid_amount or 0) for row in prev_invoices)
    prev_remaining = sum(
        max(0, int(row.total or 0) - int(row.paid_amount or 0)) for row in prev_invoices
    )
    prev_count = len(prev_invoices)
    prev_avg = int(round(prev_sales / prev_count)) if prev_count else 0

    def card(value, previous, *, money=True):
        return {
            "value": int(value),
            "previous": int(previous),
            "change": _pct_change(value, previous),
            "money": money,
        }

    return {
        "sales": card(sales, prev_sales),
        "invoices": card(count, prev_count, money=False),
        "collected": card(paid, prev_paid),
        "remaining": card(remaining, prev_remaining),
        "returns": card(return_total, prev_returns),
        "average": card(avg, prev_avg),
    }


def get_invoice_detail(tenant_id: int, invoice_id: int, *, view_cost=False, view_profit=False) -> dict:
    invoice = Invoice.query.filter_by(
        tenant_id=tenant_id, id=invoice_id, source_module="food"
    ).first()
    if not invoice:
        raise FoodError("الفاتورة غير موجودة")

    customer = db.session.get(Customer, invoice.customer_id) if invoice.customer_id else None
    profile = None
    if customer:
        profile = FoodCustomerProfile.query.filter_by(
            tenant_id=tenant_id, customer_id=customer.id
        ).first()

    snapshots = (
        FoodSaleItemSnapshot.query.join(OrderItem)
        .filter(FoodSaleItemSnapshot.tenant_id == tenant_id, OrderItem.invoice_id == invoice.id)
        .order_by(FoodSaleItemSnapshot.id)
        .all()
    )
    return_total = _return_totals_map(tenant_id, [invoice.id]).get(invoice.id, 0)
    returned_by_snapshot = {
        int(snapshot_id): Decimal(qty or 0)
        for snapshot_id, qty in db.session.query(
            FoodSaleReturnLine.sale_snapshot_id, func.coalesce(func.sum(FoodSaleReturnLine.quantity), 0)
        ).join(FoodSaleReturn, FoodSaleReturn.id == FoodSaleReturnLine.return_id).filter(
            FoodSaleReturn.tenant_id == tenant_id,
            FoodSaleReturn.invoice_id == invoice.id,
        ).group_by(FoodSaleReturnLine.sale_snapshot_id).all()
    }

    items = []
    revenue = 0
    cost_total = 0
    modes = set()
    for snapshot in snapshots:
        qty = Decimal(snapshot.quantity_snapshot if snapshot.quantity_snapshot is not None else (
            Decimal(snapshot.quantity_base or 0) / Decimal(snapshot.unit_factor_snapshot or 1)
        ))
        line_total = int(snapshot.line_total_snapshot if snapshot.line_total_snapshot is not None
                         else snapshot.order_item.total or 0)
        discount = int(snapshot.discount_snapshot or 0)
        mode = str(snapshot.sale_mode or "RETAIL").upper()
        modes.add(mode)
        revenue += line_total
        line_cost = int(round(int(snapshot.cost_snapshot or 0) * float(qty)))
        cost_total += line_cost
        batch_rows = []
        for allocation in FoodSaleBatchAllocation.query.filter_by(
            tenant_id=tenant_id, sale_snapshot_id=snapshot.id
        ).all():
            batch = db.session.get(FoodExpiryBatch, allocation.batch_id)
            if not batch:
                continue
            batch_rows.append({
                "batch_number": batch.batch_number,
                "quantity_base": int(allocation.quantity_base or 0),
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
            })
        items.append({
            "snapshot_id": snapshot.id,
            "product_name": snapshot.product_name_snapshot or snapshot.order_item.product_name,
            "variant_name": snapshot.variant_name_snapshot,
            "unit_name": snapshot.unit_name_snapshot,
            "quantity": str(qty),
            "unit_price": int(snapshot.unit_price_snapshot or 0),
            "discount": discount,
            "tax": int(snapshot.tax_snapshot or 0),
            "line_total": line_total,
            "sale_mode": mode,
            "sale_mode_label": _SALE_MIX_LABELS.get(mode, mode),
            "barcode": snapshot.barcode_snapshot,
            "returned_quantity": str(returned_by_snapshot.get(snapshot.id, Decimal("0"))),
            "returnable_quantity": str(max(Decimal("0"), qty - returned_by_snapshot.get(snapshot.id, Decimal("0")))),
            "batches": batch_rows,
            "cost": line_cost if view_cost else None,
        })

    if modes == {"RETAIL"}:
        sale_mix = "RETAIL"
    elif modes == {"WHOLESALE"}:
        sale_mix = "WHOLESALE"
    elif modes:
        sale_mix = "MIXED"
    else:
        sale_mix = "—"

    ledger = InvoicePaymentLedger.query.filter_by(
        tenant_id=tenant_id, invoice_id=invoice.id
    ).order_by(InvoicePaymentLedger.recorded_at.asc(), InvoicePaymentLedger.id.asc()).all()
    payments = [{
        "id": row.id,
        "amount": int(row.amount_delta or 0),
        "method": str(row.payment_method or "cash").lower(),
        "method_label": _PAYMENT_METHOD_LABELS.get(str(row.payment_method or "cash").lower(), row.payment_method),
        "note": row.note,
        "source_module": row.source_module,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
    } for row in ledger]

    payment_breakdown: dict[str, int] = {}
    for row in payments:
        if row["amount"] <= 0:
            continue
        payment_breakdown[row["method_label"]] = payment_breakdown.get(row["method_label"], 0) + row["amount"]

    returns = FoodSaleReturn.query.filter_by(
        tenant_id=tenant_id, invoice_id=invoice.id
    ).order_by(FoodSaleReturn.created_at.desc()).all()
    return_rows = [{
        "id": row.id,
        "return_no": row.return_no,
        "total": int(row.total or 0),
        "refund_method": row.refund_method,
        "reason": row.reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in returns]

    audits = FoodPosAuditLog.query.filter(
        FoodPosAuditLog.tenant_id == tenant_id,
        or_(
            and_(FoodPosAuditLog.entity_type == "invoice", FoodPosAuditLog.entity_id == invoice.id),
            and_(
                FoodPosAuditLog.entity_type == "food_sale_return",
                FoodPosAuditLog.entity_id.in_([r.id for r in returns] or [-1]),
            ),
        ),
    ).order_by(FoodPosAuditLog.created_at.asc()).limit(100).all()
    employee_ids = {a.employee_id for a in audits if a.employee_id}
    employee_names = {
        e.id: e.name for e in Employee.query.filter(Employee.id.in_(employee_ids)).all()
    } if employee_ids else {}
    action_labels = {
        "sale_complete": "تم إنشاء الفاتورة",
        "invoice_discount": "خصم على الفاتورة",
        "sale_return": "تم تسجيل مرتجع",
        "invoice_payment": "تم تسجيل قبض",
        "invoice_void": "تم إلغاء الفاتورة",
        "invoice_reprint": "تمت إعادة طباعة الفاتورة",
    }
    timeline = []
    for audit in audits:
        timeline.append({
            "at": audit.created_at.isoformat() if audit.created_at else None,
            "action": audit.action,
            "label": action_labels.get(audit.action, audit.action),
            "employee": employee_names.get(audit.employee_id) or "—",
            "details": json.loads(audit.details_json or "{}"),
        })
    for pay in payments:
        if pay["amount"] > 0 and not any(
            t["action"] == "invoice_payment" and t.get("details", {}).get("ledger_id") == pay["id"]
            for t in timeline
        ):
            timeline.append({
                "at": pay["recorded_at"],
                "action": "payment",
                "label": f"استلام {pay['method_label']} {pay['amount']:,}",
                "employee": invoice.employee_name or "—",
                "details": pay,
            })
    timeline.sort(key=lambda row: row.get("at") or "")

    branch = db.session.get(Branch, invoice.branch_id or invoice.warehouse_id) if (
        invoice.branch_id or invoice.warehouse_id
    ) else None
    net = max(0, int(invoice.total or 0) - return_total)
    paid = int(invoice.paid_amount or 0)
    remaining = max(0, net - paid)
    status_key, status_label = _invoice_display_status(invoice, return_total)
    walk_in = _is_walk_in(invoice, customer)
    customer_debt = _customer_debt(tenant_id, customer.id) if customer and not walk_in else 0

    subtotal = revenue + int(invoice.discount_amount or 0)
    profit = revenue - cost_total if view_profit else None
    margin = round((profit / revenue) * 100, 1) if view_profit and revenue else None

    return {
        **_serialize_invoice_row(
            invoice,
            return_total=return_total,
            sale_mix=sale_mix,
            item_count=len(items),
            methods=[p["method"] for p in payments if p["amount"] > 0],
            customer=customer,
        ),
        "discount": int(invoice.discount_amount or 0),
        "subtotal": subtotal,
        "notes": getattr(invoice, "notes", None),
        "branch_name": branch.name if branch else None,
        "warehouse_name": branch.name if branch else None,
        "customer": None if walk_in else {
            "id": customer.id if customer else None,
            "name": invoice.customer_name or (customer.name if customer else None),
            "phone": customer.phone if customer else None,
            "company_name": profile.company_name if profile else None,
            "balance": customer_debt,
        },
        "items": items,
        "payments": payments,
        "payment_breakdown": payment_breakdown,
        "returns": return_rows,
        "timeline": timeline,
        "remaining": remaining,
        "status": status_key,
        "status_label": status_label,
        "can_receive_payment": remaining > 0 and status_key not in {"void", "full_return"},
        "can_return": status_key not in {"void", "full_return"},
        "can_void": status_key not in {"void", "full_return"} and paid == 0,
        "profit": {
            "revenue": revenue,
            "cost": cost_total if view_cost else None,
            "profit": profit,
            "margin": margin,
        } if view_profit or view_cost else None,
        "print_url": f"/orders/invoice/{invoice.id}",
    }


def register_invoice_payment(
    tenant_id: int,
    invoice_id: int,
    payload: dict,
    employee_id: int | None = None,
) -> dict:
    invoice = Invoice.query.filter_by(
        tenant_id=tenant_id, id=invoice_id, source_module="food"
    ).with_for_update().first()
    if not invoice:
        raise FoodError("الفاتورة غير موجودة")
    if invoice.status in {"ملغي", "راجع"}:
        raise FoodError("لا يمكن تسجيل قبض على فاتورة ملغاة أو مرتجعة بالكامل")

    return_total = _return_totals_map(tenant_id, [invoice.id]).get(invoice.id, 0)
    net = max(0, int(invoice.total or 0) - return_total)
    remaining = max(0, net - int(invoice.paid_amount or 0))
    if remaining <= 0:
        raise FoodError("لا يوجد متبقي على هذه الفاتورة")

    amount = as_int(payload.get("amount"), 0, minimum=1)
    if amount > remaining:
        raise FoodError(f"المبلغ أكبر من المتبقي ({remaining:,})")
    method = str(payload.get("method") or payload.get("payment_method") or "cash").lower()
    if method not in {"cash", "card", "transfer"}:
        raise FoodError("طريقة الدفع غير صالحة")
    note = str(payload.get("note") or "").strip()[:500] or "قبض فاتورة"

    invoice.paid_amount = int(invoice.paid_amount or 0) + amount
    invoice.payment_status = "مسدد" if invoice.paid_amount >= net else "جزئي"
    if invoice.paid_amount >= net:
        invoice.sale_type = "cash"
    elif invoice.paid_amount > 0:
        invoice.sale_type = "partial"

    ledger = InvoicePaymentLedger(
        tenant_id=tenant_id,
        branch_id=invoice.warehouse_id or invoice.branch_id,
        invoice_id=invoice.id,
        source_module="food",
        payment_method=method,
        amount_delta=amount,
        note=note,
        treasury_account_id=as_int(payload.get("treasury_account_id"), 0) or None,
    )
    db.session.add(ledger)
    db.session.flush()
    _audit_pos(
        tenant_id, employee_id, "invoice_payment",
        entity_type="invoice", entity_id=invoice.id,
        details={"amount": amount, "method": method, "ledger_id": ledger.id},
    )
    return {
        "id": invoice.id,
        "paid": int(invoice.paid_amount or 0),
        "remaining": max(0, net - int(invoice.paid_amount or 0)),
        "payment_status": invoice.payment_status,
        "ledger_id": ledger.id,
    }


def void_invoice(tenant_id: int, invoice_id: int, employee_id: int | None = None, reason: str = "") -> dict:
    if not _employee_can(employee_id, "cashier.void_sale"):
        raise FoodError("ليس لديك صلاحية إلغاء الفاتورة")
    invoice = Invoice.query.filter_by(
        tenant_id=tenant_id, id=invoice_id, source_module="food"
    ).with_for_update().first()
    if not invoice:
        raise FoodError("الفاتورة غير موجودة")
    if invoice.status == "ملغي":
        raise FoodError("الفاتورة ملغاة مسبقاً")
    if invoice.status == "راجع":
        raise FoodError("لا يمكن إلغاء فاتورة مرتجعة بالكامل — استخدم المرتجع")
    returns = FoodSaleReturn.query.filter_by(tenant_id=tenant_id, invoice_id=invoice.id).count()
    if returns:
        raise FoodError("لا يمكن إلغاء فاتورة عليها مرتجعات — أكمل المرتجع بدلاً من الإلغاء")
    if int(invoice.paid_amount or 0) > 0:
        raise FoodError("لا يمكن إلغاء فاتورة مدفوعة جزئياً أو كلياً دون تسوية المدفوعات")

    restore_sale_stock(invoice, employee_id)
    invoice.status = "ملغي"
    invoice.payment_status = "ملغي"
    _audit_pos(
        tenant_id, employee_id, "invoice_void",
        entity_type="invoice", entity_id=invoice.id,
        details={"reason": str(reason or "").strip()[:500]},
    )
    db.session.flush()
    return {"id": invoice.id, "status": "void", "status_label": "ملغاة"}


def export_invoices_rows(tenant_id: int, filters: dict | None = None) -> list[dict]:
    """Return up to 5000 rows for export respecting current filters."""
    payload = dict(filters or {})
    payload["page"] = 1
    payload["page_size"] = 5000
    data = list_invoices(tenant_id, payload)
    return data["rows"]


def mark_invoice_reprinted(tenant_id: int, invoice_id: int, employee_id: int | None = None) -> dict:
    invoice = Invoice.query.filter_by(
        tenant_id=tenant_id, id=invoice_id, source_module="food"
    ).first()
    if not invoice:
        raise FoodError("الفاتورة غير موجودة")
    _audit_pos(
        tenant_id, employee_id, "invoice_reprint",
        entity_type="invoice", entity_id=invoice.id, details={},
    )
    return {"id": invoice.id, "print_url": f"/orders/invoice/{invoice.id}"}
