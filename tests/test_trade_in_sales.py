import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
def _make_app(*, trade_in_enabled=True):
    from flask import Flask
    from extensions import db

    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    import models  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import models.page  # noqa: F401
    import models.user  # noqa: F401

    with app.app_context():
        db.create_all()
        from models.tenant import Tenant

        db.session.add(
            Tenant(
                name="Test Company",
                feature_overrides_json=json.dumps(
                    {}
                    if trade_in_enabled is None
                    else {"trade_in_sales": bool(trade_in_enabled)}
                ),
            )
        )
        db.session.commit()
        from utils.inventory_audit_trail import ensure_inventory_audit_schema_on_engine
        ensure_inventory_audit_schema_on_engine(db.engine)
    return app


def test_trade_in_price_and_paid_receipt_are_idempotent():
    app = _make_app()
    from extensions import db
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.trade_in_receipt import TradeInReceipt
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import get_branch_stock
    from utils.trade_in_service import (
        REPLACEMENT_PRODUCT_BARCODE,
        resolve_sale_selection,
        reverse_trade_in_receipt,
        sync_trade_in_receipts,
    )

    with app.app_context():
        db.session.add(
            Branch(code="MAIN", name="الفرع الرئيسي", is_active=True, is_default=True)
        )

        customer = Customer(name="Trade Customer", phone="07701111111")
        new_product = Product(
            name="ثلاجة جديدة",
            buy_price=500_000,
            sale_price=1_000_000,
            exchange_sale_price=700_000,
            quantity=5,
            opening_stock=5,
            active=True,
        )
        db.session.add_all([customer, new_product])
        db.session.flush()

        mode, price, source = resolve_sale_selection(
            new_product,
            {
                "sale_mode": "exchange",
                "price": 1,
            },
        )
        assert mode == "exchange"
        assert price == 700_000
        assert source is None

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1_400_000,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
        )
        db.session.add(invoice)
        db.session.flush()
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=new_product.id,
            product_name=new_product.name,
            quantity=2,
            price=700_000,
            cost=500_000,
            total=1_400_000,
            sale_mode="exchange",
        )
        db.session.add(item)
        db.session.flush()

        assert sync_trade_in_receipts(invoice) == 0
        receipt = TradeInReceipt.query.filter_by(order_item_id=item.id).one()
        assert receipt.status == "pending"
        assert Product.query.filter_by(barcode=REPLACEMENT_PRODUCT_BARCODE).first() is None

        invoice.payment_status = "مسدد"
        assert sync_trade_in_receipts(invoice) == 2
        db.session.commit()

        replacement = Product.query.filter_by(barcode=REPLACEMENT_PRODUCT_BARCODE).one()
        branch = get_default_branch()
        assert replacement.name == "استبدال"
        assert replacement.buy_price == 0
        assert replacement.sale_price == 15_000
        assert replacement.store_visible is False
        assert get_branch_stock(branch.id, replacement.id) == 2

        from models.stock_movement import StockMovement
        assert StockMovement.query.filter_by(source_type="trade_in_receipt", source_id=receipt.id).count() == 1

        assert sync_trade_in_receipts(invoice) == 0
        assert get_branch_stock(branch.id, replacement.id) == 2

        receipt = TradeInReceipt.query.filter_by(order_item_id=item.id).one()
        assert reverse_trade_in_receipt(receipt) == 2
        db.session.commit()
        assert receipt.status == "reversed"
        assert get_branch_stock(branch.id, replacement.id) == 0
        assert StockMovement.query.filter_by(source_type="trade_in_reversal", source_id=receipt.id).count() == 1


def test_trade_in_feature_is_disabled_by_company_setting():
    app = _make_app(trade_in_enabled=False)
    from extensions import db
    from models.product import Product
    from utils.trade_in_service import (
        TradeInError,
        product_sale_options,
        resolve_sale_selection,
    )

    with app.app_context():
        product = Product(
            name="جهاز",
            buy_price=100,
            sale_price=200,
            exchange_sale_price=150,
            quantity=1,
            active=True,
        )
        db.session.add(product)
        db.session.flush()
        options = product_sale_options(product)
        assert options["has_exchange_sale"] is False
        assert options["exchange_sale_price"] is None
        try:
            resolve_sale_selection(product, {"sale_mode": "exchange"})
        except TradeInError as exc:
            assert "غير مفعّلة" in str(exc)
        else:
            raise AssertionError("exchange sale must be rejected while disabled")


def test_trade_in_feature_defaults_to_disabled_without_override():
    app = _make_app(trade_in_enabled=None)
    from utils.tenant_feature_flags import tenant_feature_enabled

    with app.app_context():
        assert tenant_feature_enabled("trade_in_sales", default=False) is False


def test_existing_replacement_product_is_renamed_without_duplicate():
    app = _make_app()
    from extensions import db
    from models.product import Product
    from utils.trade_in_service import (
        REPLACEMENT_PRODUCT_BARCODE,
        ensure_replacement_product_with_session,
    )

    with app.app_context():
        existing = Product(
            name="منتج مستبدل",
            barcode=REPLACEMENT_PRODUCT_BARCODE,
            buy_price=0,
            sale_price=15_000,
            quantity=3,
            active=True,
            store_visible=False,
        )
        db.session.add(existing)
        db.session.flush()
        result = ensure_replacement_product_with_session(db.session, tenant_id=None)
        db.session.commit()
        assert result.id == existing.id
        assert result.name == "استبدال"
        assert Product.query.filter_by(barcode=REPLACEMENT_PRODUCT_BARCODE).count() == 1


def test_duplicate_replacement_products_are_merged_into_existing_stock():
    app = _make_app()
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from utils.trade_in_service import (
        REPLACEMENT_PRODUCT_BARCODE,
        ensure_replacement_product_with_session,
    )

    with app.app_context():
        branch = Branch(
            code="MAIN",
            name="الفرع الرئيسي",
            is_active=True,
            is_default=True,
        )
        first = Product(
            name="استبدال",
            barcode=REPLACEMENT_PRODUCT_BARCODE,
            buy_price=0,
            sale_price=15_000,
            quantity=2,
            active=True,
            store_visible=False,
        )
        duplicate = Product(
            name="استبدال",
            barcode=REPLACEMENT_PRODUCT_BARCODE,
            buy_price=0,
            sale_price=15_000,
            quantity=3,
            active=True,
            store_visible=False,
        )
        db.session.add_all([branch, first, duplicate])
        db.session.flush()
        db.session.add_all(
            [
                BranchStock(branch_id=branch.id, product_id=first.id, quantity=2),
                BranchStock(branch_id=branch.id, product_id=duplicate.id, quantity=3),
            ]
        )
        db.session.flush()

        result = ensure_replacement_product_with_session(db.session, tenant_id=None)
        db.session.commit()

        assert result.id == first.id
        assert result.quantity == 5
        assert BranchStock.query.filter_by(
            branch_id=branch.id, product_id=result.id
        ).one().quantity == 5
        assert Product.query.filter_by(
            barcode=REPLACEMENT_PRODUCT_BARCODE, active=True
        ).count() == 1
        assert duplicate.active is False
        assert duplicate.quantity == 0
        assert duplicate.barcode.endswith(f"__ARCHIVED__{duplicate.id}")


def test_tenant_request_reuses_null_tenant_replacement_product(monkeypatch):
    from types import SimpleNamespace

    app = _make_app()
    from extensions import db
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.tenant import Tenant
    from utils import trade_in_service
    from utils.trade_in_service import (
        REPLACEMENT_PRODUCT_BARCODE,
        sync_trade_in_receipts,
    )

    with app.app_context():
        monkeypatch.setattr(trade_in_service, "has_request_context", lambda: True)
        monkeypatch.setattr(
            trade_in_service,
            "g",
            SimpleNamespace(tenant="test-company"),
        )
        tenant = Tenant.query.first()
        branch = Branch(
            code="MAIN",
            name="الفرع الرئيسي",
            is_active=True,
            is_default=True,
        )
        customer = Customer(
            tenant_id=tenant.id,
            name="زبون",
            phone="07700000000",
        )
        sold_product = Product(
            tenant_id=tenant.id,
            name="جهاز جديد",
            buy_price=100,
            sale_price=200,
            exchange_sale_price=150,
            quantity=2,
            active=True,
        )
        replacement = Product(
            tenant_id=None,
            name="استبدال",
            barcode=REPLACEMENT_PRODUCT_BARCODE,
            buy_price=0,
            sale_price=15_000,
            quantity=0,
            active=True,
            store_visible=False,
        )
        db.session.add_all([branch, customer, sold_product, replacement])
        db.session.flush()
        invoice = Invoice(
            tenant_id=tenant.id,
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=branch.id,
            total=150,
            status="تم الطلب",
            payment_status="مسدد",
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=sold_product.id,
                product_name=sold_product.name,
                quantity=1,
                price=150,
                cost=100,
                total=150,
                sale_mode="exchange",
            )
        )
        db.session.flush()

        assert sync_trade_in_receipts(invoice) == 1
        db.session.commit()

        rows = Product.query.filter_by(barcode=REPLACEMENT_PRODUCT_BARCODE).all()
        assert [row.id for row in rows] == [replacement.id]
        assert replacement.quantity == 1


def test_unassigned_replacement_requires_recorded_branch_in_multi_branch_company():
    app = _make_app()
    from extensions import db
    from models.branch import Branch, BranchStock
    from models.product import Product
    from utils.trade_in_service import REPLACEMENT_PRODUCT_BARCODE, ensure_replacement_product_with_session
    with app.app_context():
        first = Branch(name="الأول", code="one", is_default=True, is_active=True)
        second = Branch(name="الثاني", code="two", is_active=True)
        legacy = Product(name="استبدال", barcode=REPLACEMENT_PRODUCT_BARCODE,
                         quantity=6, buy_price=0, sale_price=15000, active=True)
        db.session.add_all([first, second, legacy])
        db.session.flush()
        db.session.add(BranchStock(branch_id=first.id, product_id=legacy.id, quantity=6))
        db.session.commit()
        reused = ensure_replacement_product_with_session(db.session, branch_id=first.id)
        other = ensure_replacement_product_with_session(db.session, branch_id=second.id)
        assert reused.id == legacy.id
        assert other.id != legacy.id and other.branch_id == second.id and other.quantity == 0
        assert legacy.quantity == 6
        # The helper belongs to the caller's transaction; it never commits.
        new_id = other.id
        db.session.rollback()
        assert db.session.get(Product, new_id) is None
        assert db.session.get(Product, legacy.id).quantity == 6


def test_replacement_product_is_admin_only():
    from types import SimpleNamespace

    app = _make_app()
    from models.product import Product
    from utils.trade_in_service import (
        REPLACEMENT_PRODUCT_BARCODE,
        employee_can_access_replacement_product,
    )

    with app.app_context():
        replacement = Product(
            name="استبدال",
            barcode=REPLACEMENT_PRODUCT_BARCODE,
            buy_price=0,
            sale_price=15_000,
        )
        regular = Product(name="ثلاجة", buy_price=100, sale_price=200)

        assert employee_can_access_replacement_product(
            SimpleNamespace(role="admin"), replacement
        )
        assert not employee_can_access_replacement_product(
            SimpleNamespace(role="cashier"), replacement
        )
        assert not employee_can_access_replacement_product(None, replacement)
        assert employee_can_access_replacement_product(
            SimpleNamespace(role="cashier"), regular
        )


def test_receipt_item_uses_short_sale_labels():
    app = _make_app()
    from models.order_item import OrderItem
    from utils.order_shipping import order_item_display_name

    with app.app_context():
        item = OrderItem(
            product_name="ثلاجة",
            quantity=1,
            price=100,
            cost=50,
            total=100,
            sale_mode="normal",
        )
        assert item.display_name == "ثلاجة — بيع"
        assert order_item_display_name(item) == "ثلاجة — بيع"

        item.sale_mode = "exchange"
        assert item.display_name == "ثلاجة — استبدال"
        assert order_item_display_name(item) == "ثلاجة — استبدال"


def test_normal_and_exchange_lines_share_color_and_branch_stock():
    app = _make_app()
    from extensions import db
    from models.branch import Branch
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import set_branch_stock
    from utils.order_stock_lock import check_stock_rows

    with app.app_context():
        db.session.add(
            Branch(code="MAIN", name="الفرع الرئيسي", is_active=True, is_default=True)
        )
        db.session.flush()
        product = Product(
            name="غسالة ملونة",
            buy_price=100,
            sale_price=200,
            exchange_sale_price=150,
            quantity=5,
            opening_stock=5,
            active=True,
            meta_json=json.dumps({"has_colors": True}),
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(
            ProductColorVariant(product_id=product.id, color_name="أبيض", quantity=5)
        )
        db.session.commit()
        branch = get_default_branch()
        set_branch_stock(branch.id, product.id, 5)
        db.session.commit()

        result = check_stock_rows(
            [
                {
                    "product": product,
                    "quantity": 3,
                    "variant_color": "أبيض",
                    "sale_mode": "normal",
                },
                {
                    "product": product,
                    "quantity": 3,
                    "variant_color": "أبيض",
                    "sale_mode": "exchange",
                },
            ],
            preferred_branch_id=branch.id,
        )
        assert result.can_fulfill is False
        assert any("المطلوب 6" in reason for reason in result.reasons)


def test_sqlite_schema_guards_upgrade_legacy_tables(monkeypatch):
    from sqlalchemy import create_engine, inspect, text
    from utils import order_item_schema_guard, product_schema_guard

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE product (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE invoice (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE branch (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE order_item ("
                "id INTEGER PRIMARY KEY, invoice_id INTEGER, product_id INTEGER"
                ")"
            )
        )

    monkeypatch.setattr(product_schema_guard, "_product_schema_engine", lambda: engine)
    monkeypatch.setattr(order_item_schema_guard, "_schema_engine", lambda: engine)
    product_schema_guard.ensure_product_schema()
    order_item_schema_guard.ensure_order_item_schema()

    schema = inspect(engine)
    assert "exchange_sale_price" in {
        column["name"] for column in schema.get_columns("product")
    }
    order_columns = {
        column["name"] for column in schema.get_columns("order_item")
    }
    assert {
        "sale_mode",
        "variant_color",
        "trade_in_source_product_id",
        "trade_in_source_product_name",
    }.issubset(order_columns)
    assert "trade_in_receipt" in schema.get_table_names()
