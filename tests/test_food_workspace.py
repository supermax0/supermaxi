"""Regression tests for the isolated food workspace foundation."""
from datetime import date
import pytest
from flask import Flask

from extensions import db
from modules.food.guards import BUSINESS_TYPE, FOOD_PERMISSIONS, FOOD_PRODUCT_PERMISSIONS
from modules.food.service import (
    FoodError,
    apply_inventory_count,
    as_int,
    create_product,
    create_purchase,
    create_sale,
    decompose_stock,
    reports,
)


class _Unit:
    def __init__(self, name, factor, *, active=True, base=False):
        self.unit_name = name
        self.conversion_factor = factor
        self.active = active
        self.is_base = base


def test_business_type_and_permissions_are_isolated():
    from routes.superadmin import BUSINESS_TYPES, _clean_business_type

    assert BUSINESS_TYPE == "food_wholesale_retail"
    assert BUSINESS_TYPES[BUSINESS_TYPE] == "مواد غذائية – جملة ومفرد"
    assert _clean_business_type(BUSINESS_TYPE) == BUSINESS_TYPE
    assert "food_cashier" in FOOD_PERMISSIONS
    assert all(name.startswith("food_") for name in FOOD_PERMISSIONS)
    assert "products.create" in FOOD_PRODUCT_PERMISSIONS


def test_demo_catalog_contains_ten_complete_unique_products(food_db):
    from modules.food.demo_data import seed_demo_products
    from modules.food.models import FoodProductBarcode, FoodProductProfile, FoodProductUnit, FoodProductVariant

    result = seed_demo_products(1)
    assert result["total"] == 10
    assert len(result["created"]) == 10
    assert FoodProductProfile.query.count() == 10
    assert FoodProductVariant.query.count() == 10
    assert FoodProductUnit.query.count() == 20
    assert FoodProductBarcode.query.count() == 20
    rerun = seed_demo_products(1)
    assert len(rerun["created"]) == 0
    assert len(rerun["skipped"]) == 10


def test_stock_is_decomposed_from_base_units_only():
    units = [_Unit("كيس", 1, base=True), _Unit("تكة", 12), _Unit("كارتون", 72)]
    assert decompose_stock(175, units) == "2 كارتون + 2 تكة + 7 كيس"


def test_packaging_names_are_not_hard_coded():
    units = [_Unit("حبة", 1, base=True), _Unit("باكيت", 6), _Unit("صندوق", 24)]
    assert decompose_stock(31, units) == "1 صندوق + 1 باكيت + 1 حبة"


def test_integer_money_and_quantities_reject_negative_values():
    assert as_int("34,000", minimum=0) == 34000
    try:
        as_int(-1, minimum=0)
    except FoodError:
        pass
    else:
        raise AssertionError("negative values must be rejected")


def test_food_blueprint_routes_are_namespaced():
    from modules.food.routes import food_bp

    assert food_bp.url_prefix == "/food"


def test_finance_movement_hub_summarizes_each_register(food_db):
    from datetime import datetime
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from modules.food.models import FoodCashSession, FoodExpense
    from modules.food.service import finance_movement_overview, list_finance_movements

    customer = Customer(tenant_id=1, name="عميل الاختبار", phone="0770000000")
    supplier = Supplier(name="مورد الاختبار")
    db.session.add_all([customer, supplier])
    db.session.flush()
    invoice = Invoice(tenant_id=1, customer_id=customer.id, customer_name=customer.name, total=5000, paid_amount=1000, status="تم الطلب", source_module="food")
    db.session.add(invoice)
    db.session.flush()
    db.session.add_all([
        InvoicePaymentLedger(tenant_id=1, invoice_id=invoice.id, source_module="food", note="قبض عميل", amount_delta=1000),
        SupplierPayment(tenant_id=1, supplier_id=supplier.id, source_module="food", amount=700, note="تسديد مورد"),
        FoodExpense(tenant_id=1, title="نقل", category="تشغيل", amount=300, expense_date=date.today()),
        FoodCashSession(tenant_id=1, business_date=date.today(), opening_cash=2000, status="open", opened_at=datetime.utcnow()),
    ])
    db.session.commit()

    receipts = list_finance_movements(1, "receipts")
    assert receipts["count"] == 1
    assert receipts["total"] == 1000
    assert receipts["rows"][0]["party"] == customer.name
    overview = {item["section"]: item for item in finance_movement_overview(1)}
    assert overview["payments"]["total"] == 700
    assert overview["expenses"]["count"] == 1
    assert overview["cash-sessions"]["href"] == "/food/finance/cash-sessions"


def test_finance_documents_keep_reference_and_clean_note(food_db):
    from models.customer import Customer
    from models.invoice import Invoice
    from models.supplier import Supplier
    from modules.food.service import (
        create_expense,
        list_finance_movements,
        record_customer_receipt,
        record_supplier_payment,
    )

    customer = Customer(tenant_id=1, name="عميل مستند", phone="07701112222")
    supplier = Supplier(name="مورد مستند", total_debt=9000, total_paid=0)
    db.session.add_all([customer, supplier])
    db.session.flush()
    invoice = Invoice(
        tenant_id=1, customer_id=customer.id, customer_name=customer.name,
        total=6000, paid_amount=0, status="تم الطلب", source_module="food",
    )
    db.session.add(invoice)
    db.session.flush()

    receipt = record_customer_receipt(1, customer.id, 2500, "RCV-MANUAL-1", "دفعة أولى")
    payment = record_supplier_payment(1, supplier.id, 3000, "PAY-MANUAL-1", "تحويل مصرفي")
    expense = create_expense(1, {
        "title": "نقل", "category": "تشغيل", "amount": 750,
        "document_number": "EXP-MANUAL-1", "note": "سيارة رقم 4",
    })
    db.session.commit()

    assert receipt == {"applied": 2500, "document_number": "RCV-MANUAL-1"}
    assert payment == {"applied": 3000, "document_number": "PAY-MANUAL-1"}
    assert expense["document_number"] == "EXP-MANUAL-1"
    receipt_row = list_finance_movements(1, "receipts")["rows"][0]
    payment_row = list_finance_movements(1, "payments")["rows"][0]
    expense_row = list_finance_movements(1, "expenses")["rows"][0]
    assert (receipt_row["reference"], receipt_row["note"]) == ("RCV-MANUAL-1", "دفعة أولى")
    assert (payment_row["reference"], payment_row["note"]) == ("PAY-MANUAL-1", "تحويل مصرفي")
    assert expense_row["reference"] == "EXP-MANUAL-1"
    assert "سيارة رقم 4" in expense_row["note"]


@pytest.fixture()
def food_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    import models  # noqa: F401 - registers the existing Finora core models
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.food.models import FOOD_MODELS  # noqa: F401
    from modules.wholesale.models.warehouse import Warehouse  # noqa: F401

    with app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def test_purchase_and_mixed_sale_use_base_stock_and_keep_snapshots(food_db):
    from models.supplier import Supplier
    from modules.food.models import (
        FoodExpiryBatch,
        FoodProductUnit,
        FoodProductVariant,
        FoodSaleBatchAllocation,
        FoodSaleItemSnapshot,
    )

    supplier = Supplier(name="المورد")
    db.session.add(supplier)
    db.session.commit()
    created = create_product(1, {
        "name": "Master Chips",
        "brand": "Master",
        "category": "جبس",
        "track_expiry": True,
        "variants": [{
            "variant_name": "Cheese 30g",
            "flavor": "Cheese",
            "units": [
                {"unit_name": "كيس", "conversion_factor": 1, "is_base": True, "retail_price": 500, "wholesale_price": 450, "purchase_price": 350, "barcodes": ["10001"]},
                {"unit_name": "تكة", "conversion_factor": 12, "retail_price": 6000, "wholesale_price": 5400, "purchase_price": 4200, "barcodes": ["10002"]},
                {"unit_name": "كارتون", "conversion_factor": 72, "retail_price": 34000, "wholesale_price": 31000, "purchase_price": 25000, "barcodes": ["10003"]},
            ],
        }],
    })
    db.session.commit()
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    units = {row.unit_name: row for row in FoodProductUnit.query.filter_by(variant_id=variant.id).all()}

    purchase = create_purchase(1, {
        "supplier_id": supplier.id,
        "payment_type": "cash",
        "items": [{"variant_id": variant.id, "unit_id": units["كارتون"].id, "quantity": 10, "bonus": 0, "purchase_price": 25000, "expiry_date": "2099-01-01"}],
    })
    db.session.commit()
    assert purchase.grand_total == 250000
    assert variant.stock_base == 720

    invoice = create_sale(1, {
        "payment_type": "cash",
        "items": [
            {"variant_id": variant.id, "unit_id": units["كارتون"].id, "quantity": 2, "sale_mode": "WHOLESALE"},
            {"variant_id": variant.id, "unit_id": units["كيس"].id, "quantity": 3, "sale_mode": "RETAIL"},
        ],
    })
    db.session.commit()
    assert invoice.total == 63500
    assert variant.stock_base == 573
    snapshots = FoodSaleItemSnapshot.query.order_by(FoodSaleItemSnapshot.id).all()
    assert [row.sale_mode for row in snapshots] == ["WHOLESALE", "RETAIL"]
    assert [row.quantity_base for row in snapshots] == [144, 3]
    assert FoodExpiryBatch.query.one().quantity_base == 573
    report = reports(1, "today")
    assert report["sales"]["total"] == 63500
    assert report["sales"]["wholesale"] == 0
    assert report["sales"]["mixed"] == 63500
    assert report["cash"]["cash_sales"] == 63500

    from modules.food.service import dashboard

    assert dashboard(1)["expiry_warning_count"] == 0

    units["كارتون"].conversion_factor = 60
    db.session.commit()
    assert snapshots[0].unit_factor_snapshot == 72

    # Cancellation/return must use the immutable snapshot (72), not the unit's
    # newly edited factor (60), and a retry must not restore twice.
    from utils.order_lifecycle import restore_order_stock_once

    assert restore_order_stock_once(invoice) is True
    invoice.status = "راجع"
    db.session.commit()
    assert variant.stock_base == 720
    assert FoodExpiryBatch.query.one().quantity_base == 720
    assert restore_order_stock_once(invoice) is False
    db.session.commit()
    assert variant.stock_base == 720
    returned_report = reports(1, "today")
    assert returned_report["sales"]["total"] == 0
    assert returned_report["cash"]["cash_sales"] == 0

    count_result = apply_inventory_count(1, {
        "note": "جرد نهاية اليوم",
        "items": [{"variant_id": variant.id, "actual_base": 700}],
    })
    db.session.commit()
    assert count_result["changed"] == 1
    assert count_result["difference"] == -20
    assert variant.stock_base == 700
    assert FoodExpiryBatch.query.one().quantity_base == 700

    from modules.food.models import FoodInventoryMovement

    movements = FoodInventoryMovement.query.filter_by(variant_id=variant.id).all()
    assert sum(row.quantity_base for row in movements) == 700

    from models.invoice import Invoice
    from utils.invoice_hard_delete import hard_delete_invoice

    result = hard_delete_invoice(invoice)
    db.session.commit()
    assert result["restored_stock"] is False
    assert result["removed_food_snapshots"] == 2
    assert db.session.get(Invoice, invoice.id) is None
    assert FoodSaleItemSnapshot.query.count() == 0
    assert FoodSaleBatchAllocation.query.count() == 0
    assert variant.stock_base == 700


def test_food_purchase_reverse_is_isolated_and_exactly_once(food_db):
    from models.supplier import Supplier
    from modules.food.models import (
        FoodExpiryBatch,
        FoodProductUnit,
        FoodProductVariant,
        FoodPurchaseItemSnapshot,
    )
    from modules.food.service import reverse_purchase

    supplier = Supplier(name="مورد الإلغاء")
    db.session.add(supplier)
    db.session.commit()
    created = create_product(1, {
        "name": "مادة صلاحية",
        "track_expiry": True,
        "variants": [{
            "variant_name": "النوع الأول",
            "units": [
                {"unit_name": "حبة", "conversion_factor": 1, "is_base": True, "purchase_price": 100},
                {"unit_name": "كارتون", "conversion_factor": 24, "purchase_price": 2400},
            ],
        }],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    carton = FoodProductUnit.query.filter_by(variant_id=variant.id, unit_name="كارتون").one()
    purchase = create_purchase(1, {
        "supplier_id": supplier.id,
        "payment_type": "cash",
        "items": [{
            "variant_id": variant.id,
            "unit_id": carton.id,
            "quantity": 5,
            "purchase_price": 2400,
            "expiry_date": "2099-12-31",
        }],
    })
    db.session.commit()
    assert variant.stock_base == 120
    assert supplier.total_debt == 12000
    assert supplier.total_paid == 12000

    assert reverse_purchase(purchase, "إلغاء الفاتورة") is True
    purchase.status = "cancelled"
    db.session.commit()
    assert variant.stock_base == 0
    assert variant.average_cost == 0
    assert FoodExpiryBatch.query.one().quantity_base == 0
    assert supplier.total_debt == 0
    assert supplier.total_paid == 0
    assert reverse_purchase(purchase, "إلغاء الفاتورة") is False

    assert reverse_purchase(purchase, "حذف الفاتورة", hard_delete=True) is False
    db.session.delete(purchase)
    db.session.commit()
    assert FoodPurchaseItemSnapshot.query.count() == 0


def test_untracked_food_product_never_changes_inventory(food_db):
    from models.supplier import Supplier
    from modules.food.models import FoodInventoryMovement, FoodProductUnit, FoodProductVariant
    from utils.order_lifecycle import restore_order_stock_once

    supplier = Supplier(name="مورد خدمة")
    db.session.add(supplier)
    db.session.commit()
    created = create_product(1, {
        "name": "خدمة توصيل",
        "track_stock": False,
        "variants": [{
            "variant_name": "خدمة",
            "opening_stock": 999,
            "units": [{
                "unit_name": "مرة",
                "conversion_factor": 1,
                "is_base": True,
                "retail_price": 5000,
                "wholesale_price": 5000,
                "purchase_price": 1000,
            }],
        }],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    unit = FoodProductUnit.query.filter_by(variant_id=variant.id).one()
    assert variant.stock_base == 0
    from modules.food.service import dashboard, inventory

    assert inventory(1)["low_stock"] == []
    assert dashboard(1)["out_of_stock_count"] == 0
    with pytest.raises(FoodError, match="لا تستخدم تتبّع المخزون"):
        apply_inventory_count(1, {
            "items": [{"variant_id": variant.id, "actual_base": 4}],
        })
    purchase = create_purchase(1, {
        "supplier_id": supplier.id,
        "payment_type": "cash",
        "items": [{"variant_id": variant.id, "unit_id": unit.id, "quantity": 3}],
    })
    invoice = create_sale(1, {
        "payment_type": "cash",
        "items": [{"variant_id": variant.id, "unit_id": unit.id, "quantity": 2, "sale_mode": "RETAIL"}],
    })
    db.session.commit()
    assert variant.stock_base == 0
    assert FoodInventoryMovement.query.filter_by(variant_id=variant.id).count() == 0
    assert restore_order_stock_once(invoice) is True
    assert variant.stock_base == 0
    assert purchase.stock_applied is True


def test_chained_units_multiple_barcodes_and_barcode_conflict(food_db):
    from modules.food.models import FoodProductUnit, FoodProductVariant
    from modules.food.service import check_barcode

    created = create_product(1, {
        "name": "Master Chips",
        "variants": [{
            "variant_name": "Cheese 30g",
            "units": [
                {"client_key": "piece", "unit_name": "قطعة", "is_base": True,
                 "barcodes": [{"value": "111111", "is_primary": True}, "111119"]},
                {"client_key": "pack", "unit_name": "باكيت", "parent_key": "piece",
                 "parent_multiplier": 6, "barcodes": ["222222"]},
                {"client_key": "carton", "unit_name": "كارتون", "parent_key": "pack",
                 "parent_multiplier": 12, "barcodes": ["333333"]},
            ],
        }],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    units = {row.unit_name: row for row in FoodProductUnit.query.filter_by(variant_id=variant.id)}
    assert units["قطعة"].conversion_factor == 1
    assert units["باكيت"].conversion_factor == 6
    assert units["كارتون"].conversion_factor == 72
    assert check_barcode(1, "333333")["available"] is False
    with pytest.raises(FoodError, match="مستخدم بالفعل"):
        create_product(1, {
            "name": "منتج آخر",
            "variants": [{"variant_name": "افتراضي", "units": [
                {"unit_name": "قطعة", "is_base": True, "barcodes": ["333333"]}
            ]}],
        })


def test_circular_unit_conversion_is_rejected(food_db):
    with pytest.raises(FoodError, match="تحويل دائري"):
        create_product(1, {
            "name": "تحويل خاطئ",
            "variants": [{"variant_name": "افتراضي", "units": [
                {"client_key": "base", "unit_name": "قطعة", "is_base": True},
                {"client_key": "pack", "unit_name": "باكيت", "parent_key": "carton", "parent_multiplier": 6},
                {"client_key": "carton", "unit_name": "كارتون", "parent_key": "pack", "parent_multiplier": 12},
            ]}],
        })


def test_opening_stock_is_split_by_warehouse_and_mixed_sale_is_exact(food_db):
    from models.branch import Branch
    from modules.food.models import FoodProductUnit, FoodProductVariant, FoodWarehouseStock

    main = Branch(code="MAIN", name="المخزن الرئيسي", is_active=True, is_default=True)
    branch = Branch(code="B1", name="مخزن الفرع 1", is_active=True)
    db.session.add_all([main, branch])
    db.session.flush()
    created = create_product(1, {
        "name": "Pepsi 330ml",
        "track_stock": True,
        "variants": [{
            "variant_name": "Pepsi 330ml",
            "units": [
                {"client_key": "piece", "unit_name": "قطعة", "is_base": True, "retail_price": 500},
                {"client_key": "pack", "unit_name": "باكيت", "parent_key": "piece", "parent_multiplier": 6, "retail_price": 2800},
                {"client_key": "carton", "unit_name": "كارتون", "parent_key": "pack", "parent_multiplier": 4, "retail_price": 10500},
            ],
            "opening_stocks": [
                {"warehouse_id": main.id, "unit_key": "carton", "quantity": 10},
                {"warehouse_id": branch.id, "unit_key": "pack", "quantity": 3},
            ],
        }],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    stocks = {row.warehouse_id: row.stock_base for row in FoodWarehouseStock.query.all()}
    assert stocks == {main.id: 240, branch.id: 18}
    assert variant.stock_base == 258
    units = {row.unit_name: row for row in FoodProductUnit.query.filter_by(variant_id=variant.id)}
    create_sale(1, {"payment_type": "cash", "warehouse_id": main.id, "items": [
        {"variant_id": variant.id, "unit_id": units["كارتون"].id, "quantity": 1},
        {"variant_id": variant.id, "unit_id": units["باكيت"].id, "quantity": 2},
        {"variant_id": variant.id, "unit_id": units["قطعة"].id, "quantity": 3},
    ]})
    db.session.flush()
    assert FoodWarehouseStock.query.filter_by(warehouse_id=main.id).one().stock_base == 201
    assert variant.stock_base == 219


def test_fefo_skips_expired_batch_and_product_update_keeps_snapshots(food_db):
    from datetime import timedelta
    from models.branch import Branch
    from models.supplier import Supplier
    from modules.food.models import (
        FoodExpiryBatch, FoodProductUnit, FoodProductVariant, FoodSaleBatchAllocation,
        FoodSaleItemSnapshot,
    )
    from modules.food.service import get_product, update_product

    main = Branch(code="MAIN", name="الرئيسي", is_active=True, is_default=True)
    supplier = Supplier(name="مورد الصلاحية")
    db.session.add_all([main, supplier])
    db.session.flush()
    created = create_product(1, {
        "name": "لبن",
        "track_expiry": True,
        "variants": [{"variant_name": "كامل الدسم", "units": [
            {"client_key": "piece", "unit_name": "علبة", "is_base": True,
             "retail_price": 1000, "barcodes": ["MILK-1"]}
        ]}],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    unit = FoodProductUnit.query.filter_by(variant_id=variant.id).one()
    today = date.today()
    for expiry, batch in [
        (today - timedelta(days=1), "OLD"),
        (today + timedelta(days=5), "FIRST"),
        (today + timedelta(days=20), "SECOND"),
    ]:
        create_purchase(1, {"supplier_id": supplier.id, "warehouse_id": main.id,
            "payment_type": "cash", "items": [{"variant_id": variant.id, "unit_id": unit.id,
            "quantity": 10, "purchase_price": 500, "batch_number": batch,
            "expiry_date": expiry.isoformat()}]})
    db.session.flush()
    invoice = create_sale(1, {"payment_type": "cash", "warehouse_id": main.id, "items": [
        {"variant_id": variant.id, "unit_id": unit.id, "quantity": 12}
    ]})
    db.session.flush()
    snapshot = FoodSaleItemSnapshot.query.filter_by(order_item_id=invoice.items[0].id).one()
    allocations = FoodSaleBatchAllocation.query.filter_by(sale_snapshot_id=snapshot.id).all()
    allocated_batches = {db.session.get(FoodExpiryBatch, row.batch_id).batch_number: row.quantity_base for row in allocations}
    assert allocated_batches == {"FIRST": 10, "SECOND": 2}
    assert FoodExpiryBatch.query.filter_by(batch_number="OLD").one().quantity_base == 10

    detail = get_product(1, created["id"])
    detail["name"] = "لبن محدث"
    detail["variants"][0]["units"][0]["retail_price"] = 1200
    update_product(1, created["id"], detail)
    db.session.flush()
    assert FoodSaleItemSnapshot.query.get(snapshot.id).unit_price_snapshot == 1000


def test_fifo_policy_uses_oldest_received_valid_batch(food_db):
    from datetime import timedelta
    from models.branch import Branch
    from models.supplier import Supplier
    from modules.food.models import (
        FoodExpiryBatch, FoodProductUnit, FoodProductVariant, FoodSaleBatchAllocation,
        FoodSaleItemSnapshot,
    )

    warehouse = Branch(code="FIFO", name="مخزن FIFO", is_active=True, is_default=True)
    supplier = Supplier(name="مورد FIFO")
    db.session.add_all([warehouse, supplier])
    db.session.flush()
    created = create_product(1, {
        "name": "عصير FIFO", "track_expiry": True, "issue_policy": "FIFO",
        "variants": [{"variant_name": "برتقال", "units": [
            {"client_key": "piece", "unit_name": "علبة", "is_base": True,
             "retail_price": 750, "barcodes": ["FIFO-JUICE"]}
        ]}],
    })
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    unit = FoodProductUnit.query.filter_by(variant_id=variant.id).one()
    today = date.today()
    for batch, expiry in (("RECEIVED-FIRST", today + timedelta(days=30)),
                          ("EXPIRES-FIRST", today + timedelta(days=5))):
        create_purchase(1, {"supplier_id": supplier.id, "warehouse_id": warehouse.id,
            "payment_type": "cash", "items": [{"variant_id": variant.id, "unit_id": unit.id,
            "quantity": 10, "purchase_price": 400, "batch_number": batch,
            "expiry_date": expiry.isoformat()}]})
        db.session.flush()
    invoice = create_sale(1, {"payment_type": "cash", "warehouse_id": warehouse.id,
        "items": [{"variant_id": variant.id, "unit_id": unit.id, "quantity": 6}]})
    db.session.flush()
    snapshot = FoodSaleItemSnapshot.query.filter_by(order_item_id=invoice.items[0].id).one()
    allocation = FoodSaleBatchAllocation.query.filter_by(sale_snapshot_id=snapshot.id).one()
    assert db.session.get(FoodExpiryBatch, allocation.batch_id).batch_number == "RECEIVED-FIRST"


def test_new_variant_on_edit_accepts_warehouse_opening_balance(food_db):
    from models.branch import Branch
    from modules.food.models import FoodWarehouseStock
    from modules.food.service import get_product, update_product

    warehouse = Branch(code="EDIT", name="مخزن التعديل", is_active=True, is_default=True)
    db.session.add(warehouse)
    db.session.flush()
    created = create_product(1, {
        "name": "مياه", "variants": [{"variant_name": "صغير", "units": [
            {"client_key": "piece", "unit_name": "قنينة", "is_base": True,
             "retail_price": 250, "barcodes": ["WATER-S"]}
        ]}],
    })
    detail = get_product(1, created["id"])
    detail["variants"].append({
        "variant_name": "كبير", "units": [
            {"client_key": "large-piece", "unit_name": "قنينة", "is_base": True,
             "retail_price": 500, "barcodes": ["WATER-L"]}
        ],
        "opening_stocks": [{"warehouse_id": warehouse.id,
                            "unit_key": "large-piece", "quantity": 8}],
    })
    update_product(1, created["id"], detail)
    db.session.flush()
    stocks = FoodWarehouseStock.query.filter_by(warehouse_id=warehouse.id).all()
    assert len(stocks) == 1
    assert stocks[0].stock_base == 8


def test_legacy_product_is_projected_without_changing_original_data(food_db):
    from models.product import Product
    from modules.food.models import FoodProductBarcode, FoodProductUnit, FoodProductVariant
    from modules.food.service import list_products

    legacy = Product(
        tenant_id=1, name="منتج قديم", sku="OLD-SKU", barcode="OLD-123",
        buy_price=700, sale_price=1000, opening_stock=15, quantity=12,
        low_stock_threshold=3, active=True,
    )
    db.session.add(legacy)
    db.session.commit()
    rows = list_products(1)
    assert len(rows) == 1
    assert rows[0]["product_id"] == legacy.id
    assert rows[0]["variant_name"] == "افتراضي"
    assert rows[0]["stock_base"] == 12
    unit = FoodProductUnit.query.join(FoodProductVariant).filter(
        FoodProductVariant.profile_id == rows[0]["profile_id"]
    ).one()
    assert (unit.purchase_price, unit.retail_price, unit.conversion_factor) == (700, 1000, 1)
    assert FoodProductBarcode.query.one().barcode == "OLD-123"
    assert db.session.get(Product, legacy.id).quantity == 12


def test_food_invoices_list_detail_and_payment(food_db):
    from models.customer import Customer
    from models.employee import Employee
    from models.supplier import Supplier
    from modules.food.models import FoodProductUnit, FoodProductVariant
    from modules.food.service import (
        create_product,
        create_purchase,
        create_sale,
        get_invoice_detail,
        list_invoices,
        register_invoice_payment,
    )

    admin = Employee(name="مدير", username="food-inv-admin", password="x", role="admin", is_active=True)
    supplier = Supplier(name="مورد فواتير")
    customer = Customer(tenant_id=1, name="أبو أحمد", phone="0770001111")
    db.session.add_all([admin, supplier, customer])
    db.session.commit()
    created = create_product(1, {
        "name": "Pepsi",
        "category": "مشروبات",
        "variants": [{
            "variant_name": "330ml",
            "units": [
                {"unit_name": "قطعة", "conversion_factor": 1, "is_base": True,
                 "retail_price": 1000, "wholesale_price": 800, "purchase_price": 500, "barcodes": ["P1"]},
                {"unit_name": "كارتون", "conversion_factor": 24,
                 "retail_price": 22000, "wholesale_price": 18000, "purchase_price": 12000, "barcodes": ["P24"]},
            ],
        }],
    })
    db.session.commit()
    variant = FoodProductVariant.query.filter_by(profile_id=created["id"]).one()
    units = {row.unit_name: row for row in FoodProductUnit.query.filter_by(variant_id=variant.id).all()}
    create_purchase(1, {
        "supplier_id": supplier.id, "payment_type": "cash",
        "items": [{"variant_id": variant.id, "unit_id": units["كارتون"].id, "quantity": 5, "purchase_price": 12000}],
    })
    db.session.commit()

    invoice = create_sale(1, {
        "customer_id": customer.id,
        "payment_type": "partial",
        "paid_amount": 10000,
        "items": [
            {"variant_id": variant.id, "unit_id": units["كارتون"].id, "quantity": 1, "sale_mode": "WHOLESALE"},
            {"variant_id": variant.id, "unit_id": units["قطعة"].id, "quantity": 2, "sale_mode": "RETAIL"},
        ],
    }, employee_id=admin.id)
    db.session.commit()

    listed = list_invoices(1, {"range": "today", "page": 1, "page_size": 20})
    assert listed["total"] >= 1
    assert listed["kpis"]["invoices"]["value"] >= 1
    row = next(r for r in listed["rows"] if r["id"] == invoice.id)
    assert row["sale_type"] == "MIXED"
    assert row["remaining"] > 0
    assert row["status"] in {"partial", "credit"}
    assert any(item["unit_name"] == "كارتون" for item in get_invoice_detail(1, invoice.id)["items"])

    detail = get_invoice_detail(1, invoice.id)
    assert len(detail["items"]) == 2
    assert detail["can_receive_payment"] is True
    assert detail["customer"]["name"] == "أبو أحمد"

    before_remaining = detail["remaining"]
    paid = register_invoice_payment(
        1, invoice.id, {"amount": 5000, "method": "cash", "note": "قبض اختبار"}, employee_id=admin.id
    )
    db.session.commit()
    assert paid["remaining"] == before_remaining - 5000
    refreshed = get_invoice_detail(1, invoice.id)
    assert refreshed["paid"] >= 15000
    assert any(p["amount"] == 5000 for p in refreshed["payments"])


def test_food_orders_page_registers_invoice_apis():
    from modules.food import routes as food_routes
    from modules.food.routes import PAGE_CONFIG

    assert "orders" in PAGE_CONFIG
    assert PAGE_CONFIG["orders"][1] == "food_orders"
    assert callable(food_routes.api_invoices_list)
    assert callable(food_routes.api_invoice_detail)
    assert callable(food_routes.api_invoice_payment)
    assert callable(food_routes.workspace_page)
