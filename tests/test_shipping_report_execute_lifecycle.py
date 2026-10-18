"""Regression: executing shipping reports must use the full cancel/delay accounting lifecycle."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TENANT_CANCEL = f"test_shipping_report_cancel_lifecycle_{os.getpid()}"
TENANT_DELAY = f"test_shipping_report_delay_lifecycle_{os.getpid()}"
TENANT_DELIVERED = f"test_shipping_report_delivered_settlement_{os.getpid()}"
TENANT_AGENT_RETURN = f"test_agent_report_original_branch_return_{os.getpid()}"
TENANT_REDISPATCH = f"test_agent_report_delayed_redispatch_{os.getpid()}"


def _fresh_tenant_db(tenant: str):
    db_file = ROOT / "tenants" / f"{tenant}.db"
    if db_file.exists():
        db_file.unlink()


def test_shipping_report_cancel_reverses_payment_and_restores_color_stock():
    _fresh_tenant_db(TENANT_CANCEL)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.order_item import OrderItem
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from models.shipping_report import ShippingReport
    from utils.payment_ledger import append_payment_ledger_delta
    from utils.shipping_report_execute import execute_shipping_report

    with app.app_context():
        g.tenant = TENANT_CANCEL
        init_tenant_db(TENANT_CANCEL)

        customer = Customer(name="Report Customer", phone="07740000000")
        product = Product(name="Report Color Item", buy_price=300, sale_price=1000, quantity=0, active=True)
        db.session.add_all([customer, product])
        db.session.flush()
        db.session.add(ProductColorVariant(product_id=product.id, color_name="red", quantity=0))

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=1000,
            paid_amount=1000,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=1000,
                cost=300,
                total=1000,
                variant_color="red",
            )
        )
        append_payment_ledger_delta(invoice.id, 1000)
        report = ShippingReport(
            report_number="SR-CANCEL-LIFECYCLE",
            shipping_company_name="Courier",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=1000,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "\u0645\u0644\u063a\u064a"}),
        )
        db.session.add(report)
        db.session.commit()

        result = execute_shipping_report(report)
        assert result["success"], result

        db.session.refresh(invoice)
        db.session.refresh(product)
        color = ProductColorVariant.query.filter_by(product_id=product.id, color_name="red").first()
        ledger_amounts = [
            int(row.amount_delta)
            for row in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(InvoicePaymentLedger.id).all()
        ]

        assert invoice.status == "\u0645\u0644\u063a\u064a"
        assert invoice.payment_status == "\u0645\u0644\u063a\u064a"
        assert int(invoice.paid_amount or 0) == 0
        assert int(product.quantity or 0) == 1
        assert int(color.quantity or 0) == 1
        assert ledger_amounts == [1000, -1000]


def test_shipping_report_delay_reverses_previous_payment():
    _fresh_tenant_db(TENANT_DELAY)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.order_item import OrderItem
    from models.product import Product
    from models.shipping_report import ShippingReport
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.payment_ledger import append_payment_ledger_delta
    from utils.shipping_report_execute import execute_shipping_report

    with app.app_context():
        g.tenant = TENANT_DELAY
        init_tenant_db(TENANT_DELAY)

        customer = Customer(name="Delay Customer", phone="07750000000")
        product = Product(name="Delay Stock Item", buy_price=250, sale_price=750, quantity=0, active=True)
        db.session.add_all([customer, product])
        db.session.flush()
        branch = get_default_branch()
        set_branch_stock(branch.id, product.id, 0)
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=branch.id,
            total=750,
            paid_amount=750,
            status="\u062a\u0645 \u0627\u0644\u062a\u0648\u0635\u064a\u0644",
            payment_status="\u0645\u0633\u062f\u062f",
            stock_is_deducted=True,
        )
        db.session.add(invoice)
        db.session.flush()
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=1,
                price=750,
                cost=250,
                total=750,
                fulfillment_branch_id=branch.id,
            )
        )
        append_payment_ledger_delta(invoice.id, 750)
        report = ShippingReport(
            report_number="SR-DELAY-LIFECYCLE",
            shipping_company_name="Courier",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=750,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "\u0645\u0624\u062c\u0644"}),
        )
        db.session.add(report)
        db.session.commit()

        result = execute_shipping_report(report)
        assert result["success"], result

        db.session.refresh(invoice)
        db.session.refresh(product)
        ledger_amounts = [
            int(row.amount_delta)
            for row in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(InvoicePaymentLedger.id).all()
        ]

        assert invoice.status == "\u062a\u0645 \u0627\u0644\u0637\u0644\u0628"
        assert invoice.payment_status == "\u063a\u064a\u0631 \u0645\u0633\u062f\u062f"
        assert int(invoice.paid_amount or 0) == 0
        assert invoice.stock_is_deducted is False
        assert get_branch_stock(branch.id, product.id) == 1
        assert ledger_amounts == [750, -750]


def test_shipping_report_delivered_creates_shipping_collection():
    _fresh_tenant_db(TENANT_DELIVERED)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.invoice import Invoice
    from models.shipping import ShippingCompany
    from models.shipping_payment import ShippingPayment
    from models.shipping_report import ShippingReport
    from utils.shipping_report_execute import execute_shipping_report

    with app.app_context():
        g.tenant = TENANT_DELIVERED
        init_tenant_db(TENANT_DELIVERED)

        customer = Customer(name="Delivered Customer", phone="07760000000")
        company = ShippingCompany(name="Courier", phone="07770000000")
        db.session.add_all([customer, company])
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            shipping_company_id=company.id,
            total=460000,
            paid_amount=0,
            status="\u062c\u0627\u0631\u064a \u0627\u0644\u0634\u062d\u0646",
            payment_status="\u063a\u064a\u0631 \u0645\u0633\u062f\u062f",
        )
        db.session.add(invoice)
        db.session.flush()
        report = ShippingReport(
            report_number="SR-DELIVERED-SETTLEMENT",
            shipping_company_name="Courier",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=460000,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "\u0648\u0627\u0635\u0644"}),
        )
        db.session.add(report)
        db.session.commit()

        result = execute_shipping_report(report)
        assert result["success"], result

        db.session.refresh(invoice)
        settlement = ShippingPayment.query.filter_by(
            invoice_id=invoice.id,
            action="\u062a\u0633\u062f\u064a\u062f",
        ).one()
        assert invoice.payment_status == "\u0645\u0633\u062f\u062f"
        assert invoice.shipping_status == "\u062a\u0645 \u0627\u0644\u062a\u0633\u062f\u064a\u062f"
        assert settlement.shipping_company_id == company.id
        assert settlement.amount == 460000


def test_agent_report_return_uses_deducted_branch_and_new_lifecycle_key():
    """An AGT report must never override each item's persisted fulfillment branch."""
    _fresh_tenant_db(TENANT_AGENT_RETURN)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.branch import Branch
    from models.customer import Customer
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.shipping_report import ShippingReport
    from models.stock_movement import StockMovement
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.shipping_report_execute import execute_shipping_report
    from utils.stock_movement_guard import claim_stock_movement

    with app.app_context():
        g.tenant = TENANT_AGENT_RETURN
        init_tenant_db(TENANT_AGENT_RETURN)
        ensure_branch_schema()

        main_branch = get_default_branch()
        other_branch = Branch(
            code="KAR",
            name="فرع الكرادة",
            is_active=True,
            is_default=False,
        )
        customer = Customer(name="Agent Return Customer", phone="07781111111")
        product = Product(
            name="Agent Return Item",
            buy_price=250,
            sale_price=750,
            quantity=0,
            active=True,
        )
        db.session.add_all([other_branch, customer, product])
        db.session.flush()
        set_branch_stock(main_branch.id, product.id, 0)
        set_branch_stock(other_branch.id, product.id, 0)

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=main_branch.id,
            total=750,
            status="جاري الشحن",
            payment_status="غير مسدد",
            stock_is_deducted=True,
        )
        db.session.add(invoice)
        db.session.flush()
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=750,
            cost=250,
            total=750,
            fulfillment_branch_id=main_branch.id,
        )
        db.session.add(item)
        db.session.flush()

        # Legacy history from a previous return cycle used the fixed v1 key
        # and a different destination. A newer outbound v2 proves that this is
        # a real second dispatch, so its correct main-branch return may use v2.
        claim_stock_movement(
            f"order:{invoice.id}:item:{item.id}:deduct:v1",
            movement_type="order_deduct",
            direction="out",
            product_id=product.id,
            branch_id=main_branch.id,
            quantity=1,
            unit_cost=250,
            source_type="invoice",
            source_id=invoice.id,
            source_line_id=item.id,
            details={"variant_color": None},
        )
        claim_stock_movement(
            f"order:{invoice.id}:item:{item.id}:restore:v1",
            movement_type="order_restore",
            direction="in",
            product_id=product.id,
            branch_id=other_branch.id,
            quantity=1,
            unit_cost=250,
            source_type="invoice",
            source_id=invoice.id,
            source_line_id=item.id,
            details={"return_branch_id": other_branch.id, "variant_color": None},
        )
        claim_stock_movement(
            f"order:{invoice.id}:item:{item.id}:deduct:v2",
            movement_type="order_deduct",
            direction="out",
            product_id=product.id,
            branch_id=main_branch.id,
            quantity=1,
            unit_cost=250,
            source_type="invoice",
            source_id=invoice.id,
            source_line_id=item.id,
            details={"variant_color": None},
        )

        report = ShippingReport(
            report_number="AGT-1-20260803-0001",
            shipping_company_name="كشف المندوب: اختبار",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=750,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "ملغي"}),
        )
        db.session.add(report)
        db.session.commit()

        result = execute_shipping_report(
            report,
            return_branch_id=other_branch.id,
        )
        assert result["success"], result

        db.session.refresh(invoice)
        assert invoice.stock_is_deducted is False
        assert get_branch_stock(main_branch.id, product.id) == 1
        assert get_branch_stock(other_branch.id, product.id) == 0
        assert StockMovement.query.filter_by(
            movement_key=f"order:{invoice.id}:item:{item.id}:restore:v2"
        ).one().branch_id == main_branch.id


def test_delayed_order_is_deducted_again_when_dispatched_next_day():
    """خرج، تأجل ورجع، ثم خرج ووصل: التاريخ يجب أن يكون خارج/داخل/خارج."""
    _fresh_tenant_db(TENANT_REDISPATCH)
    from app import app
    from flask import g
    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.shipping_report import ShippingReport
    from models.stock_movement import StockMovement
    from utils.branch_migration import get_default_branch
    from utils.branch_stock_service import get_branch_stock, set_branch_stock
    from utils.order_stock_policy import prepare_order_for_dispatch
    from utils.shipping_report_execute import execute_shipping_report
    from routes.orders import create_agent_report_internal

    with app.app_context():
        g.tenant = TENANT_REDISPATCH
        init_tenant_db(TENANT_REDISPATCH)

        branch = get_default_branch()
        customer = Customer(name="Redispatch Customer", phone="07782222222")
        agent = DeliveryAgent(name="Redispatch Agent", is_active=True)
        product = Product(
            name="Redispatch Item",
            buy_price=300,
            sale_price=900,
            quantity=0,
            active=True,
        )
        db.session.add_all([customer, agent, product])
        db.session.flush()
        set_branch_stock(branch.id, product.id, 1)

        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            branch_id=branch.id,
            total=900,
            status="تم الطلب",
            shipping_status="تم الطلب",
            payment_status="غير مسدد",
            stock_is_deducted=False,
        )
        db.session.add(invoice)
        db.session.flush()
        item = OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=1,
            price=900,
            cost=300,
            total=900,
            fulfillment_branch_id=branch.id,
        )
        db.session.add(item)
        db.session.flush()

        assert prepare_order_for_dispatch(invoice) is True
        first_report = ShippingReport(
            report_number=f"AGT-{agent.id}-20260802-0001",
            shipping_company_name="كشف المندوب: اختبار",
            orders_data=json.dumps([{"id": invoice.id}]),
            total_amount=900,
            orders_count=1,
            order_status_selections=json.dumps({str(invoice.id): "مؤجل"}),
        )
        db.session.add(first_report)
        db.session.commit()
        assert get_branch_stock(branch.id, product.id) == 0

        delayed = execute_shipping_report(first_report)
        assert delayed["success"], delayed
        db.session.refresh(invoice)
        assert invoice.status == "تم الطلب"
        assert invoice.stock_is_deducted is False
        assert get_branch_stock(branch.id, product.id) == 1

        # إنشاء كشف اليوم التالي نفسه هو خروج فعلي جديد،
        # لا إعادة استخدام للحركة الأولى.
        with app.test_request_context("/orders/create-agent-report"):
            created = create_agent_report_internal(
                [invoice.id],
                agent.id,
                save_to_db=True,
            )
        assert created["success"], created
        second_report = ShippingReport.query.get(created["report_id"])
        second_report.order_status_selections = json.dumps({str(invoice.id): "واصل"})
        db.session.commit()
        assert get_branch_stock(branch.id, product.id) == 0

        delivered = execute_shipping_report(second_report)
        assert delivered["success"], delivered
        db.session.refresh(invoice)
        assert invoice.status == "تم التوصيل"
        assert invoice.shipping_status == "تم التوصيل"
        assert invoice.payment_status == "مسدد"
        assert invoice.stock_is_deducted is True
        assert get_branch_stock(branch.id, product.id) == 0

        movements = StockMovement.query.filter_by(
            source_type="invoice",
            source_id=invoice.id,
            source_line_id=item.id,
        ).order_by(StockMovement.id.asc()).all()
        assert [row.direction for row in movements] == ["out", "in", "out"]
        assert [row.movement_key for row in movements] == [
            f"order:{invoice.id}:item:{item.id}:deduct:v1",
            f"order:{invoice.id}:item:{item.id}:restore:v1",
            f"order:{invoice.id}:item:{item.id}:deduct:v2",
        ]


if __name__ == "__main__":
    test_shipping_report_cancel_reverses_payment_and_restores_color_stock()
    test_shipping_report_delay_reverses_previous_payment()
    test_shipping_report_delivered_creates_shipping_collection()
    test_agent_report_return_uses_deducted_branch_and_new_lifecycle_key()
    test_delayed_order_is_deducted_again_when_dispatched_next_day()
    print("shipping report lifecycle tests passed")
