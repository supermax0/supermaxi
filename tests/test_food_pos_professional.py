from flask import Flask
import pytest

from extensions import db


@pytest.fixture()
def pos_db():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.food.models import FOOD_MODELS  # noqa: F401
    from modules.wholesale.models.warehouse import Warehouse  # noqa: F401
    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _catalog(stock=100):
    from models.branch import Branch
    from modules.food.models import FoodProductUnit, FoodProductVariant
    from modules.food.service import create_product

    branch = Branch(code="POS", name="فرع الكاشير", is_active=True, is_default=True)
    db.session.add(branch)
    db.session.flush()
    created = create_product(1, {
        "name": "مشروب اختبار", "brand": "Finora", "category": "مشروبات",
        "variants": [{"variant_name": "برتقال 330ml", "units": [
            {"client_key": "piece", "unit_name": "قطعة", "is_base": True,
             "retail_price": 1000, "wholesale_price": 850,
             "wholesale_minimum": 12, "auto_wholesale": True,
             "barcodes": ["POS-PIECE"]},
            {"client_key": "carton", "unit_name": "كارتون", "parent_key": "piece",
             "parent_multiplier": 24, "retail_price": 22000,
             "wholesale_price": 20000, "barcodes": ["POS-CARTON"]},
        ], "opening_stocks": [{"warehouse_id": branch.id, "unit_key": "piece",
                                "quantity": stock}]}],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    units = {row.unit_name: row for row in FoodProductUnit.query.filter_by(variant_id=variant.id)}
    return branch, variant, units


def test_checkout_is_idempotent_and_split_payment_records_effective_amount(pos_db):
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.food.models import FoodWarehouseStock
    from modules.food.service import create_sale

    branch, variant, units = _catalog()
    payload = {
        "idempotency_key": "same-checkout", "warehouse_id": branch.id,
        "payments": [{"method": "cash", "amount": 500, "received": 1000},
                     {"method": "card", "amount": 500}],
        "items": [{"variant_id": variant.id, "unit_id": units["قطعة"].id,
                   "quantity": 1, "sale_mode": "RETAIL"}],
    }
    first = create_sale(1, payload)
    db.session.commit()
    second = create_sale(1, payload)
    db.session.commit()
    assert second.id == first.id
    assert Invoice.query.count() == 1
    assert FoodWarehouseStock.query.filter_by(warehouse_id=branch.id).one().stock_base == 99
    ledgers = InvoicePaymentLedger.query.order_by(InvoicePaymentLedger.id).all()
    assert [(row.payment_method, row.amount_delta) for row in ledgers] == [("cash", 500), ("card", 500)]
    assert "باقي 500" in ledgers[0].note


def test_backend_rejects_forged_price_and_reports_stock_shortage(pos_db):
    from modules.food.service import FoodError, create_sale, validate_cart

    branch, variant, units = _catalog(stock=2)
    db.session.commit()
    branch_id, variant_id, unit_id = branch.id, variant.id, units["قطعة"].id
    base = {"idempotency_key": "forged-price", "warehouse_id": branch_id,
            "payment_type": "cash", "items": [{"variant_id": variant_id,
            "unit_id": unit_id, "quantity": 1, "price": 1}]}
    with pytest.raises(FoodError, match="صلاحية تغيير السعر"):
        create_sale(1, base)
    db.session.rollback()
    result = validate_cart(1, {"warehouse_id": branch_id, "items": [{
        "variant_id": variant_id, "unit_id": unit_id, "quantity": 3,
    }]})
    assert result["valid"] is False
    assert result["items"][0]["available_base"] == 2


def test_hold_restore_revalidates_and_partial_return_restores_stock(pos_db):
    from models.employee import Employee
    from modules.food.models import FoodSaleReturnLine, FoodWarehouseStock
    from modules.food.service import (create_sale, create_sale_return, hold_sale,
                                      list_held_sales, restore_held_sale)

    branch, variant, units = _catalog()
    held = hold_sale(1, {"warehouse_id": branch.id, "items": [{
        "variant_id": variant.id, "unit_id": units["قطعة"].id,
        "quantity": 2, "sale_mode": "RETAIL"}]})
    db.session.commit()
    assert len(list_held_sales(1)) == 1
    restored = restore_held_sale(1, held["id"])
    assert restored["validation"]["valid"] is True
    db.session.commit()

    invoice = create_sale(1, {"idempotency_key": "return-source",
        "warehouse_id": branch.id, "payment_type": "cash", "items": [{
        "variant_id": variant.id, "unit_id": units["قطعة"].id,
        "quantity": 4, "sale_mode": "RETAIL"}]})
    db.session.commit()
    assert FoodWarehouseStock.query.filter_by(warehouse_id=branch.id).one().stock_base == 96
    admin = Employee(name="مدير", username="pos-admin", password="pw", role="admin", is_active=True)
    db.session.add(admin)
    db.session.commit()
    snapshot_id = invoice.items[0].id
    from modules.food.models import FoodSaleItemSnapshot
    snapshot = FoodSaleItemSnapshot.query.filter_by(order_item_id=snapshot_id).one()
    result = create_sale_return(1, {"idempotency_key": "partial-return",
        "invoice_id": invoice.id, "warehouse_id": branch.id, "refund_method": "cash",
        "items": [{"snapshot_id": snapshot.id, "quantity": 2}]}, admin.id)
    db.session.commit()
    assert result.total == 2000
    assert FoodSaleReturnLine.query.one().quantity == 2
    assert FoodWarehouseStock.query.filter_by(warehouse_id=branch.id).one().stock_base == 98


def test_ranked_catalog_and_exact_barcode_keep_unit_identity(pos_db):
    from modules.food.service import cashier_catalog, lookup_barcode

    branch, variant, units = _catalog()
    result = cashier_catalog(1, search="Finora", warehouse_id=branch.id, per_page=12)
    assert result["products"][0]["id"] == variant.id
    carton = lookup_barcode(1, "POS-CARTON", branch.id)
    assert carton["selected_unit_id"] == units["كارتون"].id
    assert carton["units"][1]["factor"] == 24


def test_scale_barcode_decodes_weight_with_configurable_parser(pos_db):
    from models.branch import Branch
    from modules.food.models import FoodProductUnit, FoodProductVariant, FoodSettings
    from modules.food.service import create_product, lookup_barcode, validate_cart

    branch = Branch(code="SCALE", name="فرع الميزان", is_active=True, is_default=True)
    db.session.add(branch)
    db.session.flush()
    created = create_product(1, {
        "name": "تفاح موزون", "category": "خضار وفواكه", "variants": [{
            "variant_name": "تفاح أحمر", "sku": "12345", "units": [
                {"client_key": "gram", "unit_name": "غرام", "is_base": True,
                 "retail_price": 2, "wholesale_price": 2},
                {"client_key": "kg", "unit_name": "كغم", "parent_key": "gram",
                 "parent_multiplier": 1000, "retail_price": 2000, "wholesale_price": 1800},
            ], "opening_stocks": [{"warehouse_id": branch.id, "unit_key": "kg", "quantity": 10}]
        }],
    })
    settings = FoodSettings.query.filter_by(tenant_id=1).one()
    settings.scale_barcode_enabled = True
    settings.scale_barcode_prefix = "20"
    settings.scale_barcode_product_digits = 5
    settings.scale_barcode_value_digits = 5
    settings.scale_barcode_divisor = 1000
    db.session.commit()
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    kg = FoodProductUnit.query.filter_by(variant_id=variant.id, unit_name="كغم").one()
    decoded = lookup_barcode(1, "2012345012500", branch.id)
    assert decoded["selected_unit_id"] == kg.id
    assert decoded["scale_quantity"] == "1.25"
    checked = validate_cart(1, {"warehouse_id": branch.id, "items": [{
        "variant_id": variant.id, "unit_id": kg.id, "quantity": decoded["scale_quantity"]
    }]})
    assert checked["items"][0]["base_quantity"] == 1250
    assert checked["total"] == 2500


def test_backend_promotion_is_automatic_and_not_client_controlled(pos_db):
    from modules.food.models import FoodPromotion
    from modules.food.service import validate_cart

    branch, variant, units = _catalog()
    db.session.add(FoodPromotion(
        tenant_id=1, name="خصم المشروبات 10%", scope_type="category",
        scope_value="مشروبات", discount_type="percent", discount_value=10,
        minimum_quantity=1, active=True,
    ))
    db.session.commit()
    result = validate_cart(1, {"warehouse_id": branch.id, "items": [{
        "variant_id": variant.id, "unit_id": units["قطعة"].id,
        "quantity": 1, "sale_mode": "RETAIL",
    }]})
    line = result["items"][0]
    assert line["promotion_name"] == "خصم المشروبات 10%"
    assert line["promotion_discount"] == 100
    assert result["total"] == 900
