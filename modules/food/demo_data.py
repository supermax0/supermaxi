"""Idempotent demo catalog for the food workspace.

The seed is intentionally opt-in: it never runs during app startup or a normal
request, and it only touches the tenant selected by the caller.
"""
from __future__ import annotations

from datetime import date, timedelta

from extensions import db
from models.branch import Branch
from models.product import Product
from modules.food.models import FoodProductProfile
from modules.food.service import create_product


DEMO_NAMES = (
    "شيبس بطاطا ملح [تجريبي]",
    "عصير برتقال طبيعي [تجريبي]",
    "حليب كامل الدسم [تجريبي]",
    "أرز بسمتي فاخر [تجريبي]",
    "سكر أبيض ناعم [تجريبي]",
    "زيت دوار الشمس [تجريبي]",
    "معجون طماطم [تجريبي]",
    "مياه معدنية [تجريبي]",
    "بسكويت شوكولاتة [تجريبي]",
    "عدس أحمر [تجريبي]",
)


def _unit(name, key, *, base=False, parent_key=None, multiplier=1,
          purchase=0, retail=0, wholesale=0, wholesale_minimum=1,
          barcodes=(), auto_wholesale=False):
    return {
        "client_key": key,
        "unit_name": name,
        "is_base": base,
        "parent_key": parent_key,
        "parent_multiplier": multiplier,
        "conversion_factor": multiplier if parent_key else 1,
        "purchase_price": purchase,
        "retail_price": retail,
        "wholesale_price": wholesale,
        "wholesale_minimum": wholesale_minimum,
        "auto_wholesale": auto_wholesale,
        "barcodes": list(barcodes),
    }


def demo_product_payloads(warehouse_id: int | None, supplier_id: int | None) -> list[dict]:
    """Return ten complete, realistic product payloads."""
    today = date.today()
    definitions = [
        ("سناكات", "Master", "قطعة", "باكيت", 6, 350, 500, 450, "6291000000001", True),
        ("مشروبات", "Finora", "علبة", "كرتون", 24, 450, 750, 650, "6291000000002", True),
        ("ألبان", "Finora", "علبة", "كرتون", 12, 900, 1250, 1100, "6291000000003", True),
        ("حبوب", "الرافدين", "كغم", "كيس", 5, 1800, 2400, 2200, "6291000000004", False),
        ("مواد أساسية", "الرافدين", "كغم", "كيس", 5, 1100, 1500, 1350, "6291000000005", False),
        ("زيوت", "الصفوة", "لتر", "كرتون", 12, 2500, 3200, 2950, "6291000000006", False),
        ("معلبات", "الحدائق", "علبة", "كرتون", 24, 700, 1000, 900, "6291000000007", True),
        ("مياه", "نقاء", "قنينة", "كرتون", 12, 150, 250, 220, "6291000000008", True),
        ("بسكويت", "SweetCo", "قطعة", "كرتون", 20, 300, 500, 450, "6291000000009", True),
        ("بقوليات", "الرافدين", "كغم", "كيس", 5, 1700, 2300, 2100, "6291000000010", False),
    ]
    payloads = []
    for index, (category, brand, base_name, pack_name, pack_factor,
                purchase, retail, wholesale, barcode, track_expiry) in enumerate(definitions):
        base_key = f"base-{index + 1}"
        pack_key = f"pack-{index + 1}"
        units = [
            _unit(base_name, base_key, base=True, purchase=purchase,
                  retail=retail, wholesale=wholesale,
                  wholesale_minimum=6, barcodes=(barcode,)),
            _unit(pack_name, pack_key, parent_key=base_key, multiplier=pack_factor,
                  purchase=purchase * pack_factor, retail=retail * pack_factor,
                  wholesale=wholesale * pack_factor, wholesale_minimum=2,
                  auto_wholesale=True, barcodes=(f"6292000000{index + 1:03d}",)),
        ]
        variant = {
            "client_key": f"variant-{index + 1}",
            "variant_name": f"{base_name} قياسي",
            "flavor": "أصلي",
            "sku": f"DEMO-FOOD-{index + 1:02d}",
            "size_value": 1,
            "size_unit": "pcs",
            "units": units,
        }
        if warehouse_id:
            opening = {
                "warehouse_id": warehouse_id,
                "unit_key": pack_key,
                "quantity": 8 + index,
                "unit_cost": purchase * pack_factor,
            }
            if track_expiry:
                opening.update({
                    "batch_number": f"DEMO-{index + 1:02d}-A",
                    "production_date": (today - timedelta(days=10)).isoformat(),
                    "expiry_date": (today + timedelta(days=90 + index * 15)).isoformat(),
                })
            variant["opening_stocks"] = [opening]
        payloads.append({
            "name": f"{DEMO_NAMES[index]}",
            "short_name": f"DEMO-{index + 1:02d}",
            "category": category,
            "brand": brand,
            "origin_country": "العراق",
            "default_supplier_id": supplier_id,
            "supplier_product_code": f"SUP-DEMO-{index + 1:02d}",
            "description": "بيانات تجريبية للتأكد من دورة المنتج والمخزون والكاشير.",
            "track_stock": True,
            "track_expiry": track_expiry,
            "track_batches": track_expiry,
            "issue_policy": "FEFO" if track_expiry else "FIFO",
            "expiry_warning_days": 30,
            "storage_type": "normal",
            "storage_location": f"DEMO-A{index + 1:02d}",
            "taxable": False,
            "status": "active",
            "variants": [variant],
        })
    return payloads


def seed_demo_products(tenant_id: int = 1, *, employee_id: int | None = None) -> dict:
    """Create missing demo products for the current tenant and return a report."""
    warehouse = Branch.query.filter_by(is_active=True, is_default=True).first()
    warehouse = warehouse or Branch.query.filter_by(is_active=True).first()
    if warehouse is None:
        warehouse = Branch(code="DEMO-FOOD", name="مخزن تجريبي للغذائيات", is_active=True, is_default=True)
        db.session.add(warehouse)
        db.session.flush()
    # Supplier is optional. Some legacy tenant databases have an older
    # supplier schema; keeping this nullable makes the demo seed compatible
    # without changing that legacy table.
    supplier_id = None
    existing = {
        name for (name,) in db.session.query(Product.name).join(
            FoodProductProfile, FoodProductProfile.product_id == Product.id
        ).filter(FoodProductProfile.tenant_id == tenant_id, Product.name.in_(DEMO_NAMES)).all()
    }
    created = []
    skipped = []
    for payload in demo_product_payloads(warehouse.id, supplier_id):
        if payload["name"] in existing:
            skipped.append(payload["name"])
            continue
        result = create_product(tenant_id, payload, employee_id)
        created.append(result)
    db.session.commit()
    return {
        "created": created,
        "skipped": skipped,
        "warehouse_id": warehouse.id,
        "supplier_id": supplier_id,
        "total": len(created) + len(skipped),
    }
