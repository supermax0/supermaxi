from datetime import date

import pytest
from flask import Flask, g, session

from extensions import db
from models.account_transaction import AccountTransaction
from models.account import Account
from models.branch import Branch, BranchStock
from models.employee import Employee
from models.delivery_agent import DeliveryAgent  # register Invoice FK target for create_all
from models.product import Product
from models.journal_entry import JournalEntry
from models.purchase import Purchase
from models.purchase_list import PurchaseList, PurchaseListItem
from models.stock_movement import StockMovement
from models.supplier import Supplier
from models.system_settings import SystemSettings  # register branch-schema state table
from models.tenant import Tenant
from models.treasury_account import TreasuryAccount
from modules.wholesale.models.warehouse import Warehouse, WarehouseMovement, WarehouseStock
from services import purchase_list_service as service


@pytest.fixture()
def purchase_list_env(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="purchase-list-test",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'purchase-list.db'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        tenant = Tenant(name="شركة الاختبار", business_type="general")
        other_tenant = Tenant(name="شركة أخرى", business_type="general")
        db.session.add_all([tenant, other_tenant])
        db.session.flush()
        branch = Branch(code="MAIN", name="الرئيسي", is_active=True, is_default=True)
        db.session.add(branch)
        db.session.flush()
        employee = Employee(name="مدير", username="pl-admin", password="x", role="admin", is_active=True, branch_id=branch.id, tenant_id=tenant.id)
        warehouse = Warehouse(code="MAIN", name="المخزن الرئيسي", branch_id=branch.id, is_active=True, tenant_id=tenant.id)
        cash = TreasuryAccount(name="الصندوق الرئيسي", account_type="cash", branch_id=branch.id, is_active=True, is_default=True)
        card = TreasuryAccount(name="Mastercard", account_type="bank", branch_id=branch.id, is_active=True)
        bank = TreasuryAccount(name="مصرف الرافدين", account_type="bank", branch_id=branch.id, is_active=True)
        sx = Supplier(name="Supplier X", branch_id=branch.id)
        sy = Supplier(name="Supplier Y", branch_id=branch.id)
        products = [
            Product(name="A", buy_price=10, sale_price=20, quantity=0, branch_id=branch.id, tenant_id=tenant.id),
            Product(name="B", buy_price=10, sale_price=20, quantity=0, branch_id=branch.id, tenant_id=tenant.id),
            Product(name="C", buy_price=10, sale_price=20, quantity=0, branch_id=branch.id, tenant_id=tenant.id),
            Product(name="D", buy_price=10, sale_price=20, quantity=0, branch_id=branch.id, tenant_id=tenant.id),
        ]
        db.session.add_all([employee, warehouse, cash, card, bank, sx, sy, *products])
        db.session.add_all([
            Account(code="1001", name="النقدية", account_type="asset", is_active=True),
            Account(code="1101", name="المخزون", account_type="asset", is_active=True),
            Account(code="2001", name="ديون الموردين", account_type="liability", is_active=True),
        ])
        db.session.flush()
        db.session.add_all([
            AccountTransaction(branch_id=branch.id, treasury_account_id=cash.id, type="deposit", amount=5_000_000, note="رأس مال"),
            AccountTransaction(branch_id=branch.id, treasury_account_id=card.id, type="deposit", amount=5_000_000, note="رصيد افتتاحي"),
            AccountTransaction(branch_id=branch.id, treasury_account_id=bank.id, type="deposit", amount=5_000_000, note="رصيد افتتاحي"),
        ])
        db.session.commit()
        ids = {"branch": branch.id, "employee": employee.id, "warehouse": warehouse.id,
               "cash": cash.id, "card": card.id, "bank": bank.id, "sx": sx.id, "sy": sy.id,
               "products": [p.id for p in products], "tenant": tenant.id, "other_tenant": other_tenant.id}
    monkeypatch.setattr(service, "allowed_branch_ids", lambda: [ids["branch"]])
    with app.test_request_context("/"):
        session["user_id"] = ids["employee"]
        session["role"] = "admin"
        session["tenant_id"] = ids["tenant"]
        g.branches = [db.session.get(Branch, ids["branch"])]
        yield ids
        db.session.remove()


def _build_manual_qa_list(ids):
    row = service.create_list(branch_id=ids["branch"], warehouse_id=ids["warehouse"],
                              responsible_employee_id=ids["employee"], list_date=date.today(),
                              notes="manual QA", employee_id=ids["employee"])
    specs = [
        (0, ids["sx"], 5, 200_000, "cash", ids["cash"], True),
        (1, ids["sx"], 2, 350_000, "credit", None, True),
        (2, ids["sy"], 20, 5_000, "card", ids["card"], True),
        (3, ids["sy"], 30, 7_000, "credit", None, False),
    ]
    for product_index, supplier_id, qty, price, method, account_id, selected in specs:
        service.add_item(row, {
            "product_id": ids["products"][product_index], "supplier_id": supplier_id,
            "quantity": qty, "purchase_price": price, "payment_method": method,
            "payment_account_id": account_id, "is_selected": selected,
        }, ids["employee"])
    db.session.commit()
    return row.id


def test_draft_has_no_inventory_supplier_or_financial_effect(purchase_list_env):
    ids = purchase_list_env
    list_id = _build_manual_qa_list(ids)
    assert db.session.get(PurchaseList, list_id).status == "open"
    assert Purchase.query.count() == 0
    assert BranchStock.query.count() == 0
    assert WarehouseStock.query.count() == 0
    assert db.session.get(Supplier, ids["sx"]).total_debt == 0
    assert AccountTransaction.query.filter_by(type="withdraw").count() == 0


def test_execution_groups_suppliers_handles_mixed_payment_and_discards(purchase_list_env):
    ids = purchase_list_env
    list_id = _build_manual_qa_list(ids)
    summary = service.execute_list(list_id, employee_id=ids["employee"], discard_unselected=True,
                                   idempotency_key="manual-qa-run")
    assert summary["purchase_invoice_count"] == 2
    assert summary["executed_item_count"] == 3
    assert summary["total"] == 1_800_000
    assert summary["cash"] == 1_000_000
    assert summary["card"] == 100_000
    assert summary["credit"] == 700_000
    purchases = Purchase.query.order_by(Purchase.supplier_id).all()
    assert len(purchases) == 2
    supplier_x_invoice = next(p for p in purchases if p.supplier_id == ids["sx"])
    assert supplier_x_invoice.grand_total == 1_700_000
    assert supplier_x_invoice.paid_total == 1_000_000
    assert supplier_x_invoice.remaining_total == 700_000
    assert len(supplier_x_invoice.payments) == 1
    assert db.session.get(Supplier, ids["sx"]).remaining == 700_000
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [5, 2, 20, 0]
    discarded = PurchaseListItem.query.filter_by(purchase_list_id=list_id, product_id=ids["products"][3]).one()
    assert discarded.status == "discarded"
    assert AccountTransaction.query.filter_by(type="withdraw", purchase_list_id=list_id).count() == 2
    assert StockMovement.query.filter_by(movement_type="purchase_receive").count() == 3
    assert WarehouseStock.query.filter_by(warehouse_id=ids["warehouse"]).count() == 3
    assert WarehouseMovement.query.filter_by(
        warehouse_id=ids["warehouse"], reference_type="purchase", movement_type="in"
    ).count() == 3
    assert [db.session.get(Product, pid).buy_price for pid in ids["products"]] == [200_000, 350_000, 5_000, 10]
    journals = JournalEntry.query.filter_by(reference_type="purchase_list_purchase").all()
    assert sum(row.amount for row in journals) == 1_800_000
    assert all(row.debit_account.code == "1101" for row in journals)
    assert any(row.credit_account.code == "2001" and row.amount == 700_000 for row in journals)
    assert any(row.credit_account.code == f"TR-{ids['card']}" and row.amount == 100_000 for row in journals)


def test_bank_transfer_and_same_source_payments_are_aggregated(purchase_list_env):
    ids = purchase_list_env
    row = service.create_list(
        branch_id=ids["branch"], warehouse_id=ids["warehouse"],
        responsible_employee_id=ids["employee"], list_date=date.today(),
        notes=None, employee_id=ids["employee"],
    )
    for product_id, price in ((ids["products"][0], 100_000), (ids["products"][1], 200_000)):
        service.add_item(row, {
            "product_id": product_id, "supplier_id": ids["sx"], "quantity": 1,
            "purchase_price": price, "payment_method": "cash",
            "payment_account_id": ids["cash"],
        }, ids["employee"])
    service.add_item(row, {
        "product_id": ids["products"][2], "supplier_id": ids["sy"], "quantity": 2,
        "purchase_price": 50_000, "payment_method": "bank_transfer",
        "payment_account_id": ids["bank"],
    }, ids["employee"])
    db.session.commit()

    summary = service.execute_list(row.id, employee_id=ids["employee"], idempotency_key="bank-and-aggregate")
    assert summary["bank_transfer"] == 100_000
    sx_purchase = Purchase.query.filter_by(supplier_id=ids["sx"]).one()
    sy_purchase = Purchase.query.filter_by(supplier_id=ids["sy"]).one()
    assert [(payment.payment_method, payment.amount) for payment in sx_purchase.payments] == [("cash", 300_000)]
    assert [(payment.payment_method, payment.amount) for payment in sy_purchase.payments] == [("bank_transfer", 100_000)]
    bank_withdraw = AccountTransaction.query.filter_by(
        type="withdraw", treasury_account_id=ids["bank"], purchase_list_id=row.id,
    ).one()
    assert bank_withdraw.amount == 100_000


def test_execution_is_idempotent_and_does_not_duplicate_stock(purchase_list_env):
    ids = purchase_list_env
    list_id = _build_manual_qa_list(ids)
    first = service.execute_list(
        list_id, employee_id=ids["employee"], discard_unselected=False,
        idempotency_key="same-request",
    )
    second = service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="same-request")
    assert second == first
    assert Purchase.query.count() == 2
    assert db.session.get(PurchaseList, list_id).status == "partially_executed"
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [5, 2, 20, 0]

    remaining = PurchaseListItem.query.filter_by(
        purchase_list_id=list_id, product_id=ids["products"][3]
    ).one()
    remaining.is_selected = True
    remaining.status = "selected"
    db.session.commit()
    final = service.execute_list(
        list_id, employee_id=ids["employee"], discard_unselected=True,
        idempotency_key="next-partial-execution",
    )
    assert final["list_status"] == "executed"
    assert Purchase.query.count() == 3
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [5, 2, 20, 30]
    with pytest.raises(service.PurchaseListError, match="مسبقاً"):
        service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="different-request")


def test_validation_failure_rolls_back_everything(purchase_list_env):
    ids = purchase_list_env
    list_id = _build_manual_qa_list(ids)
    bad = PurchaseListItem.query.filter_by(purchase_list_id=list_id, product_id=ids["products"][0]).one()
    bad.payment_account_id = None
    db.session.commit()
    with pytest.raises(service.PurchaseListError):
        service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="bad-run")
    assert Purchase.query.count() == 0
    assert db.session.get(PurchaseList, list_id).status == "open"
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [0, 0, 0, 0]
    assert AccountTransaction.query.filter_by(type="withdraw").count() == 0
    assert JournalEntry.query.filter_by(reference_type="purchase_list_purchase").count() == 0


def test_no_selected_items_fails_without_side_effects(purchase_list_env):
    ids = purchase_list_env
    list_id = _build_manual_qa_list(ids)
    for item in PurchaseListItem.query.filter_by(purchase_list_id=list_id).all():
        item.is_selected = False
        item.status = "draft"
    db.session.commit()
    with pytest.raises(service.PurchaseListError, match="حدد"):
        service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="empty")
    assert Purchase.query.count() == 0
    assert db.session.get(PurchaseList, list_id).status == "open"


def test_draft_validation_enforces_tenant_branch_and_required_values(purchase_list_env):
    ids = purchase_list_env
    row = service.create_list(branch_id=ids["branch"], warehouse_id=ids["warehouse"],
                              responsible_employee_id=ids["employee"], list_date=date.today(),
                              notes=None, employee_id=ids["employee"])
    foreign = Product(name="Foreign", buy_price=1, sale_price=2, quantity=0,
                      branch_id=ids["branch"], tenant_id=ids["other_tenant"])
    db.session.add(foreign)
    db.session.flush()
    with pytest.raises(service.PurchaseListError, match="الشركة الحالية"):
        service.add_item(row, {"product_id": foreign.id, "supplier_id": ids["sx"],
                         "quantity": 1, "purchase_price": 1, "payment_method": "credit"}, ids["employee"])

    with pytest.raises(service.PurchaseListError, match="المورد غير موجود"):
        service.add_item(row, {
            "product_id": ids["products"][0], "supplier_id": 999_999,
            "quantity": 1, "purchase_price": 1, "payment_method": "credit",
        }, ids["employee"])
    with pytest.raises(service.PurchaseListError, match="أكبر من صفر"):
        service.add_item(row, {
            "product_id": ids["products"][0], "supplier_id": ids["sx"],
            "quantity": 0, "purchase_price": 1, "payment_method": "credit",
        }, ids["employee"])
    with pytest.raises(service.PurchaseListError, match="سالبة"):
        service.add_item(row, {
            "product_id": ids["products"][0], "supplier_id": ids["sx"],
            "quantity": 1, "purchase_price": -1, "payment_method": "credit",
        }, ids["employee"])

    other_branch = Branch(code="OTHER", name="فرع غير مصرح", is_active=True)
    db.session.add(other_branch)
    db.session.flush()
    other_warehouse = Warehouse(
        code="OTHER", name="مخزن غير مصرح", branch_id=other_branch.id,
        is_active=True, tenant_id=ids["tenant"],
    )
    db.session.add(other_warehouse)
    db.session.flush()
    other_cash = TreasuryAccount(
        name="صندوق فرع آخر", account_type="cash", branch_id=other_branch.id, is_active=True,
    )
    db.session.add(other_cash)
    db.session.flush()
    with pytest.raises(service.PurchaseListError, match="لا يتبع فرع القائمة"):
        service.add_item(row, {
            "product_id": ids["products"][0], "supplier_id": ids["sx"],
            "quantity": 1, "purchase_price": 1, "payment_method": "cash",
            "payment_account_id": other_cash.id,
        }, ids["employee"])
    with pytest.raises(service.PurchaseListError, match="لا يمكنك"):
        service.create_list(
            branch_id=other_branch.id, warehouse_id=other_warehouse.id,
            responsible_employee_id=ids["employee"], list_date=date.today(),
            notes=None, employee_id=ids["employee"],
        )


def test_forced_inventory_payment_and_accounting_failures_roll_back_everything(purchase_list_env, monkeypatch):
    ids = purchase_list_env
    list_id = _build_manual_qa_list(ids)
    import routes.purchases as purchases_route

    original = purchases_route._add_purchase_withdraw
    calls = {"count": 0}
    def fail_on_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("forced payment failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(purchases_route, "_add_purchase_withdraw", fail_on_second)
    with pytest.raises(RuntimeError, match="forced payment"):
        service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="forced-failure")
    assert Purchase.query.count() == 0
    assert db.session.get(PurchaseList, list_id).status == "open"
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [0, 0, 0, 0]
    assert AccountTransaction.query.filter_by(type="withdraw").count() == 0
    assert JournalEntry.query.filter_by(reference_type="purchase_list_purchase").count() == 0

    monkeypatch.setattr(purchases_route, "_add_purchase_withdraw", original)
    original_stock = purchases_route._apply_purchase_item_stock
    stock_calls = {"count": 0}
    def fail_inventory_on_second(*args, **kwargs):
        stock_calls["count"] += 1
        if stock_calls["count"] == 2:
            raise RuntimeError("forced inventory failure")
        return original_stock(*args, **kwargs)
    monkeypatch.setattr(purchases_route, "_apply_purchase_item_stock", fail_inventory_on_second)
    with pytest.raises(RuntimeError, match="forced inventory"):
        service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="inventory-failure")
    assert Purchase.query.count() == 0
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [0, 0, 0, 0]
    assert StockMovement.query.count() == 0
    assert WarehouseMovement.query.count() == 0

    monkeypatch.setattr(purchases_route, "_apply_purchase_item_stock", original_stock)
    import services.purchase_list_accounting as accounting
    original_post = accounting.post_split_purchase_journals
    posting_calls = {"count": 0}
    def fail_accounting_on_second(*args, **kwargs):
        posting_calls["count"] += 1
        if posting_calls["count"] == 2:
            raise RuntimeError("forced accounting failure")
        return original_post(*args, **kwargs)
    monkeypatch.setattr(accounting, "post_split_purchase_journals", fail_accounting_on_second)
    with pytest.raises(RuntimeError, match="forced accounting"):
        service.execute_list(list_id, employee_id=ids["employee"], idempotency_key="accounting-failure")
    assert Purchase.query.count() == 0
    assert db.session.get(Supplier, ids["sx"]).total_debt == 0
    assert [db.session.get(Product, pid).quantity for pid in ids["products"]] == [0, 0, 0, 0]
    assert AccountTransaction.query.filter_by(type="withdraw").count() == 0
    assert JournalEntry.query.filter_by(reference_type="purchase_list_purchase").count() == 0


def test_execute_endpoint_permission_is_enforced_server_side(monkeypatch):
    import routes.purchase_lists as purchase_list_routes

    app = Flask(__name__)
    app.config.update(SECRET_KEY="permission-test")
    monkeypatch.setattr(purchase_list_routes, "_can", lambda _permission: False)
    with app.test_request_context("/purchases/lists/api/1/execute", method="POST", json={}):
        response, status = purchase_list_routes.api_execute(1)
    assert status == 403
    assert response.get_json()["error"] == "غير مصرح"


def test_product_search_accepts_branch_id(purchase_list_env, monkeypatch):
    from flask import current_app

    import routes.purchase_lists as purchase_list_routes

    ids = purchase_list_env
    monkeypatch.setattr(purchase_list_routes, "_can", lambda _permission: True)
    monkeypatch.setattr(purchase_list_routes, "allowed_branch_ids", lambda: [ids["branch"]])
    monkeypatch.setattr(purchase_list_routes, "current_tenant_id", lambda: ids["tenant"])
    with current_app.test_request_context(
        f"/purchases/lists/api/products/search?q=A&branch_id={ids['branch']}"
    ):
        response = purchase_list_routes.api_product_search()
    payload = response.get_json()
    assert payload["success"] is True
    names = [row["name"] for row in payload["products"]]
    assert "A" in names
