from datetime import date, datetime, timedelta
import json
from unittest.mock import patch

import pytest
from utils.business_time import business_today
from utils.payment_ledger import calendar_day_bounds_utc
from flask import Flask, session

from extensions import db
from models.branch import Branch, BranchStock
from models.daily_closing import DailyClosingSnapshotHistory, DailyInventoryCount, DailySession
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.product import Product
from models.stock_movement import StockMovement
from models.shipping_report import ShippingReport
from models.order_item import OrderItem
from utils.daily_closing_service import _cash_breakdown, _window, archive_snapshot_for_reopen, build_daily_closing_data, build_period_overview, close_session, linked_data_changed
from routes.daily_closing import _keep_current_daily_open, save as save_daily, stock_details


@pytest.fixture()
def daily_app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="daily-closing-test",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        # Importing the model package registers every referenced FK table.
        import models  # noqa: F401

        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def _seed(daily_app, *, opening_cash=100_000):
    branch = Branch(code="MAIN", name="الفرع الرئيسي", is_default=True)
    employee = Employee(name="مدير الاختبار", username="daily-admin", password="x", role="admin", branch_id=None)
    db.session.add_all([branch, employee])
    db.session.flush()
    employee.branch_id = branch.id
    product = Product(name="شاشة 43", buy_price=100, sale_price=150, quantity=12, branch_id=branch.id)
    db.session.add(product)
    db.session.flush()
    db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=12, opening_stock=10))
    now = datetime.utcnow()
    day_start = calendar_day_bounds_utc(business_today())[0]
    opened = max(now - timedelta(hours=2), day_start)
    elapsed = now - opened
    daily = DailySession(
        report_number="DR-20260825-001", company_key="tenant-a", branch_id=branch.id,
        business_date=business_today(), opened_by=employee.id, opened_at=opened,
        opening_cash=opening_cash, status="open",
    )
    db.session.add(daily)
    db.session.flush()
    db.session.add_all([
        StockMovement(movement_key="purchase:1", movement_type="purchase", direction="in", product_id=product.id, branch_id=branch.id, quantity=5, unit_cost=100, total_cost=500, source_type="purchase", source_id=1, created_at=opened + min(timedelta(minutes=10), elapsed / 3)),
        StockMovement(movement_key="sale:1", movement_type="sale", direction="out", product_id=product.id, branch_id=branch.id, quantity=3, unit_cost=100, total_cost=300, source_type="invoice", source_id=900, created_at=opened + min(timedelta(minutes=20), elapsed * 2 / 3)),
        DailyInventoryCount(daily_session_id=daily.id, company_key="tenant-a", branch_id=branch.id, product_id=product.id, warehouse_id=0, actual_quantity=12, counted_by=employee.id),
    ])
    db.session.commit()
    return daily, product, employee


def test_inventory_count_uses_real_stock_movements(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = build_daily_closing_data(daily)
        count = report["inventory_counts"][0]
        assert count["opening"] == 10
        assert count["incoming"] == 5
        assert count["outgoing"] == 3
        assert count["expected"] == 12
        assert count["variance"] == 0
        assert report["stock"]["outgoing"][0]["sales"] == 3
        assert report["stock"]["incoming"][0]["purchase"] == 5


def test_inventory_count_never_mixes_other_branch_stock(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, product, employee = _seed(daily_app)
        other = Branch(code="KAR", name="فرع الكرادة", is_default=False)
        db.session.add(other)
        db.session.flush()
        db.session.add_all([
            BranchStock(branch_id=other.id, product_id=product.id, quantity=999, opening_stock=999),
            StockMovement(
                movement_key="purchase:other-branch", movement_type="purchase", direction="in",
                product_id=product.id, branch_id=other.id, quantity=50,
                unit_cost=100, total_cost=5_000, source_type="purchase", source_id=2,
                created_at=datetime.utcnow() - timedelta(minutes=10),
            ),
        ])
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = build_daily_closing_data(daily)
        count = report["inventory_counts"][0]
        assert count["expected"] == 12
        assert count["incoming"] == 5
        assert all(row["product_id"] == product.id for row in report["stock"]["details"])
        assert sum(row["quantity"] for row in report["stock"]["details"] if row["direction"] == "in") == 5


def test_direct_overview_can_aggregate_all_branches_without_daily_session(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, product, employee = _seed(daily_app)
        other = Branch(code="KAR", name="فرع الكرادة", is_default=False)
        db.session.add(other)
        db.session.flush()
        db.session.add(StockMovement(
            movement_key="sale:all-branches", movement_type="sale", direction="out",
            product_id=product.id, branch_id=other.id, quantity=4,
            unit_cost=100, total_cost=400, source_type="invoice", source_id=99,
            created_at=datetime.utcnow() - timedelta(minutes=5),
        ))
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        start, end = _window(daily)
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = build_period_overview(
                branch_id=None, business_date=daily.business_date,
                period_start=start, period_end=end,
            )
        assert report["session"]["branch_name"] == "كل الفروع"
        assert report["is_overview"] is True
        assert sum(row["quantity"] for row in report["stock"]["details"] if row["direction"] == "out") == 7


def test_close_freezes_snapshot_and_detects_later_source_change(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = close_session(daily, actual_cash=100_000)
            db.session.commit()
            assert daily.status == "closed"
            assert daily.snapshot_json
            assert report["cash"]["variance"] == 0
            BranchStock.query.filter_by(branch_id=daily.branch_id, product_id=product.id).update({"quantity": 11})
            db.session.commit()
            assert linked_data_changed(daily) is True


def test_legacy_closed_snapshot_gets_cash_breakdown_for_printing(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, _product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            close_session(daily, actual_cash=100_000)
        frozen = json.loads(daily.snapshot_json)
        frozen["cash"].pop("breakdown", None)
        daily.snapshot_json = json.dumps(frozen, ensure_ascii=False)
        db.session.commit()
        restored = build_daily_closing_data(daily, live=False)
        assert restored["cash"]["breakdown"]["cash_sales"] == 0
        assert restored["cash"]["breakdown"]["other_out"] == 0


def test_reopen_archive_preserves_previous_closed_snapshot(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, _product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            close_session(daily, actual_cash=100_000)
        original_snapshot = daily.snapshot_json
        archived = archive_snapshot_for_reopen(daily, reason="تصحيح جرد مادة")
        db.session.commit()
        stored = DailyClosingSnapshotHistory.query.get(archived.id)
        assert stored.snapshot_json == original_snapshot
        assert stored.snapshot_version == 1
        assert stored.reopen_reason == "تصحيح جرد مادة"
        assert daily.snapshot_version == 2


def test_close_requires_reason_for_cash_variance(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, _product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            with pytest.raises(ValueError, match="سبب الفرق"):
                close_session(daily, actual_cash=90_000, variance_reason="")
            report = close_session(daily, actual_cash=90_000, variance_reason="عجز قيد المراجعة")
        assert report["cash"]["variance"] == -10_000
        assert daily.variance_reason == "عجز قيد المراجعة"


def test_close_requires_actual_count_for_every_selected_item(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, _product, employee = _seed(daily_app)
        daily.counts[0].actual_quantity = None
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            with pytest.raises(ValueError, match="أكمل الجرد"):
                close_session(daily, actual_cash=100_000)


def test_debt_receipt_uses_payment_date_for_older_invoice(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, _product, employee = _seed(daily_app)
        old_invoice = Invoice(
            customer_id=1, customer_name="عميل قديم", employee_id=employee.id,
            employee_name=employee.name, branch_id=daily.branch_id,
            status="تم التسليم", payment_status="جزئي", total=200_000,
            paid_amount=50_000, created_at=datetime.utcnow() - timedelta(days=4),
        )
        db.session.add(old_invoice)
        db.session.flush()
        db.session.add(InvoicePaymentLedger(
            branch_id=daily.branch_id, invoice_id=old_invoice.id,
            amount_delta=50_000, payment_method="cash", recorded_at=datetime.utcnow(),
        ))
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = build_daily_closing_data(daily)
        assert report["sales"]["total_sales"] == 0
        assert report["sales"]["debt_receipts"] == 50_000
        assert report["sales"]["cash_sales"] == 0


def test_company_key_prevents_cross_tenant_session_lookup(daily_app):
    with daily_app.app_context():
        daily, _product, _employee = _seed(daily_app)
        visible = DailySession.query.filter_by(id=daily.id, company_key="tenant-a").first()
        hidden = DailySession.query.filter_by(id=daily.id, company_key="tenant-b").first()
        assert visible is not None
        assert hidden is None


def test_window_covers_full_iraq_business_day_even_if_opened_late(daily_app):
    with daily_app.app_context():
        daily, _product, _employee = _seed(daily_app)
        daily.business_date = date(2026, 8, 25)
        daily.opened_at = datetime(2026, 8, 25, 13, 21)
        start, end = _window(daily, end_at=datetime(2026, 8, 25, 14, 0))
        assert start == datetime(2026, 8, 24, 21, 0)
        assert end == datetime(2026, 8, 25, 14, 0)


def test_cash_breakdown_keeps_named_outgoing_categories_traceable():
    cash = {
        "total_in": 180_000,
        "total_out": 100_000,
        "movements": [
            {"out": 30_000, "type": "تسديد مورد", "description": "دفعة تجهيز", "reference_type": "supplier_payment"},
            {"out": 20_000, "type": "سحب صاحب الشركة", "description": "", "reference_type": "owner_withdrawal"},
            {"out": 10_000, "type": "مرتجع عميل", "description": "", "reference_type": "customer_return"},
            {"out": 15_000, "type": "حركة أخرى", "description": "", "reference_type": "other"},
        ],
    }
    sales = {"cash_sales": 100_000, "debt_receipts_by_method": {"cash": 50_000}}
    expenses = {"cash_total": 25_000}
    result = _cash_breakdown(cash, sales, expenses)
    assert result == {
        "cash_sales": 100_000,
        "debt_receipts": 50_000,
        "other_in": 30_000,
        "cash_expenses": 25_000,
        "supplier_payments": 30_000,
        "owner_withdrawals": 20_000,
        "customer_refunds": 10_000,
        "other_out": 15_000,
    }


def test_courier_movement_uses_items_from_agent_report_not_invoice_creation_date(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, product, employee = _seed(daily_app)
        agent = DeliveryAgent(name="وسام رحيم", branch_id=daily.branch_id)
        db.session.add(agent)
        db.session.flush()
        old_invoice = Invoice(
            customer_id=1, customer_name="عميل كشف", employee_id=employee.id,
            employee_name=employee.name, branch_id=daily.branch_id,
            delivery_agent_id=agent.id, status="تم الطلب", payment_status="غير مسدد",
            total=300, paid_amount=0, created_at=datetime.utcnow() - timedelta(days=3),
        )
        unrelated = Invoice(
            customer_id=2, customer_name="خارج الكشف", employee_id=employee.id,
            employee_name=employee.name, branch_id=daily.branch_id,
            delivery_agent_id=agent.id, status="تم الطلب", payment_status="غير مسدد",
            total=150, paid_amount=0, created_at=datetime.utcnow(),
        )
        db.session.add_all([old_invoice, unrelated])
        db.session.flush()
        db.session.add_all([
            OrderItem(invoice_id=old_invoice.id, product_id=product.id, product_name="شاشة ميزان حجم 43", price=150, quantity=2, cost=100, total=300),
            OrderItem(invoice_id=unrelated.id, product_id=product.id, product_name="لا يجب أن تظهر", price=150, quantity=1, cost=100, total=150),
            ShippingReport(
                report_number=f"AGT-{agent.id}-20260827-0001",
                shipping_company_name=f"كشف المندوب: {agent.name}",
                orders_data=json.dumps([{
                    "id": old_invoice.id,
                    "items": [{"product_name": "شاشة ميزان حجم 43", "quantity": 2}],
                }], ensure_ascii=False),
                order_status_selections=json.dumps({str(old_invoice.id): "Delivered"}),
                orders_count=1, total_amount=300, created_at=datetime.utcnow(), is_executed=True,
            ),
            StockMovement(
                movement_key="order-deduct:agent-report", movement_type="order_deduct", direction="out",
                product_id=product.id, branch_id=daily.branch_id, quantity=2,
                unit_cost=100, total_cost=200, source_type="invoice", source_id=old_invoice.id,
                created_at=datetime.utcnow(),
            ),
        ])
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = build_daily_closing_data(daily)
        assert report["couriers"] == [{
            "agent": "وسام رحيم", "product": "شاشة ميزان حجم 43",
            "delivered": 2, "sold": 2, "returned": 0, "remaining": 0,
        }]
        stock_row = next(row for row in report["stock"]["outgoing"] if row["product_id"] == product.id)
        assert stock_row["delivery_out"] == 2
        assert stock_row["other_out"] == 0


def test_known_stock_movement_names_do_not_fall_into_other(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, product, employee = _seed(daily_app)
        db.session.add_all([
            StockMovement(
                movement_key="order-deduct:direct", movement_type="order_deduct", direction="out",
                product_id=product.id, branch_id=daily.branch_id, quantity=4,
                unit_cost=100, total_cost=400, source_type="invoice", source_id=999,
                created_at=datetime.utcnow(),
            ),
            StockMovement(
                movement_key="transfer-send:1", movement_type="transfer_send", direction="out",
                product_id=product.id, branch_id=daily.branch_id, quantity=1,
                unit_cost=100, total_cost=100, source_type="stock_transfer", source_id=5,
                created_at=datetime.utcnow(),
            ),
        ])
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            report = build_daily_closing_data(daily)
        stock_row = next(row for row in report["stock"]["outgoing"] if row["product_id"] == product.id)
        assert stock_row["sales"] == 7
        assert stock_row["transfer_out"] == 1
        assert stock_row["other_out"] == 0


def test_today_closed_daily_is_preserved_in_history_then_kept_open(daily_app):
    with daily_app.app_context(), daily_app.test_request_context("/"):
        daily, _product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("utils.daily_closing_service.get_cash_movements", return_value=[]):
            close_session(daily, actual_cash=100_000)
        db.session.commit()
        _keep_current_daily_open(daily)
        assert daily.status == "open"
        assert daily.closed_at is None
        assert daily.snapshot_json is None
        assert DailyClosingSnapshotHistory.query.filter_by(daily_session_id=daily.id).count() == 1


def test_non_admin_cannot_change_current_cash(daily_app):
    with daily_app.app_context(), daily_app.test_request_context(
        "/reports/daily-closing/1/save", method="POST", json={"actual_closing_cash": 55_000}
    ):
        daily, _product, employee = _seed(daily_app)
        employee.role = "cashier"
        db.session.commit()
        session.update(user_id=employee.id, name=employee.name, role="cashier", tenant_slug="tenant-a")
        with patch("routes.daily_closing._guard"), patch("routes.daily_closing._daily_or_404", return_value=daily):
            response, status = save_daily(daily.id)
        assert status == 403
        assert response.get_json()["error"] == "تغيير الصندوق الحالي متاح للسوبر أدمن فقط"
        assert daily.actual_closing_cash is None


def test_super_admin_current_cash_immediately_persists_variance(daily_app):
    with daily_app.app_context(), daily_app.test_request_context(
        "/reports/daily-closing/1/save", method="POST", json={"actual_closing_cash": 90_000}
    ):
        daily, _product, employee = _seed(daily_app)
        session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
        with patch("routes.daily_closing._guard"), patch("routes.daily_closing._daily_or_404", return_value=daily), patch(
            "utils.daily_closing_service.get_cash_movements", return_value=[]
        ):
            response = save_daily(daily.id)
        assert response.status_code == 200
        assert daily.actual_closing_cash == 90_000
        assert daily.expected_closing_cash == 100_000
        assert daily.cash_variance == -10_000
        assert response.get_json()["report"]["cash"]["variance"] == -10_000


def test_stock_details_uses_full_business_day_not_session_open_time(daily_app):
    with daily_app.app_context():
        daily, product, employee = _seed(daily_app)
        # A completed business day keeps the late-opening scenario valid even
        # when this test runs just after midnight in Baghdad.
        daily.business_date = business_today() - timedelta(days=1)
        day_start, _day_end = _window(daily)
        daily.opened_at = day_start + timedelta(hours=12)
        early = StockMovement(
            movement_key="early-order-deduct", movement_type="order_deduct", direction="out",
            product_id=product.id, branch_id=daily.branch_id, quantity=2,
            unit_cost=100, total_cost=200, source_type="invoice", source_id=777,
            created_at=day_start + timedelta(minutes=30),
        )
        db.session.add(early)
        db.session.commit()
        assert early.created_at < daily.opened_at
        with daily_app.test_request_context(
            f"/reports/daily-closing/{daily.id}/stock-details?product_id={product.id}&category=sales"
        ):
            session.update(user_id=employee.id, name=employee.name, role="admin", tenant_slug="tenant-a")
            with patch("routes.daily_closing._guard"), patch("routes.daily_closing._daily_or_404", return_value=daily):
                response = stock_details(daily.id)
        payload = response.get_json()
        assert payload["success"] is True
        assert any(row["reference_id"] == 777 and row["quantity"] == 2 for row in payload["rows"])
