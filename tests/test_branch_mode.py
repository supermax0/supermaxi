from utils.branch_mode import mode_enabled_from_flags
from utils.dashboard_ui_defaults import get_default_dashboard_ui_flags


def test_independent_branches_are_enabled_by_default():
    assert mode_enabled_from_flags({}) is True
    assert mode_enabled_from_flags(None) is True
    assert get_default_dashboard_ui_flags()["independent_branches_enabled"] is True


def test_company_can_remain_on_legacy_mode_before_migration():
    assert mode_enabled_from_flags({"independent_branches_enabled": False}) is False


def test_completed_migration_cannot_be_disabled_by_flag():
    assert mode_enabled_from_flags(
        {
            "independent_branches_enabled": False,
            "branch_scope_v3_done": True,
        }
    ) is True


def test_explicit_legacy_compatibility_overrides_completed_migration():
    assert mode_enabled_from_flags(
        {
            "independent_branches_enabled": True,
            "branch_scope_v3_done": True,
            "legacy_shared_mode_enabled": True,
        }
    ) is False


def test_shared_compat_migration_does_not_mirror_existing_branch_stock():
    import os
    from pathlib import Path

    from app import app
    from extensions import db
    from extensions_tenant import clear_tenant_engine, init_tenant_db
    from flask import g
    from models.branch import Branch, BranchStock
    from models.product import Product
    from utils.branch_migration import _run_data_migration, ensure_branch_schema

    tenant = f"test_branch_shared_stock_{os.getpid()}"
    database = Path(__file__).resolve().parents[1] / "tenants" / f"{tenant}.db"
    clear_tenant_engine(tenant)
    if database.exists():
        database.unlink()

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_branch_schema()
        main = Branch.query.filter_by(is_default=True).first()
        second = Branch(code="B2", name="Second", is_active=True)
        db.session.add(second)
        db.session.flush()
        product = Product(
            name="Already localized",
            buy_price=10,
            sale_price=20,
            quantity=7,
            active=True,
            branch_id=second.id,
        )
        db.session.add(product)
        db.session.flush()
        db.session.add(
            BranchStock(
                branch_id=second.id,
                product_id=product.id,
                quantity=7,
                opening_stock=0,
            )
        )
        db.session.commit()

        _run_data_migration()

        rows = BranchStock.query.filter_by(product_id=product.id).all()
        assert [(row.branch_id, row.quantity) for row in rows] == [(second.id, 7)]
        assert not BranchStock.query.filter_by(
            branch_id=main.id,
            product_id=product.id,
        ).first()

    clear_tenant_engine(tenant)


def test_legacy_company_remains_unscoped_and_uses_internal_default_branch():
    import os
    from datetime import date
    from pathlib import Path

    from app import app
    from extensions import db
    from extensions_tenant import clear_tenant_engine, init_tenant_db
    from flask import g, session
    from models.account_transaction import AccountTransaction
    from models.branch import Branch
    from models.customer import Customer
    from models.employee import Employee
    from models.expense import Expense
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.system_settings import SystemSettings
    from models.treasury_account import TreasuryAccount
    from routes.expenses import _post_expense_to_treasury
    from routes.pos import create_order
    from utils.branch_context import can_switch_branch, init_branch_context
    from utils.branch_migration import ensure_branch_schema, get_default_branch
    from utils.branch_mode import clear_branch_mode_cache
    from utils.branch_scope import resolve_write_branch_id
    from utils.treasury_helpers import resolve_treasury_account_id

    tenant = f"test_branch_legacy_mode_{os.getpid()}"
    root = Path(__file__).resolve().parents[1]
    database = root / "tenants" / f"{tenant}.db"
    clear_tenant_engine(tenant)
    if database.exists():
        database.unlink()

    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        settings = SystemSettings.query.first()
        flags = settings.get_ui_flags()
        flags["independent_branches_enabled"] = False
        flags["branch_scope_v3_done"] = True
        flags["legacy_shared_mode_enabled"] = True
        settings.set_ui_flags(flags)
        db.session.commit()
        clear_branch_mode_cache()
        ensure_branch_schema()

        main = get_default_branch()
        second = Branch(code="LEGACY-B2", name="فرع قديم ثانٍ", is_active=True)
        admin = Employee(
            name="Legacy Admin",
            username=f"legacy-admin-{os.getpid()}",
            password="x",
            role="admin",
            is_active=True,
            branch_id=main.id,
        )
        cashier = Employee(
            name="Legacy Cashier",
            username=f"legacy-cashier-{os.getpid()}",
            password="x",
            role="cashier",
            is_active=True,
            branch_id=main.id,
        )
        first_product = Product(
            name="Legacy Main Product",
            sale_price=100,
            buy_price=50,
            quantity=1,
            active=True,
            branch_id=main.id,
        )
        db.session.add_all([second, admin, cashier, first_product])
        db.session.flush()
        second_product = Product(
            name="Legacy Second Product",
            sale_price=200,
            buy_price=100,
            quantity=1,
            active=True,
            branch_id=second.id,
        )
        second_customer = Customer(
            name="Legacy Second Customer",
            phone=f"770{os.getpid()}",
            city="بغداد",
            address="اختبار",
            branch_id=second.id,
        )
        second_cash = TreasuryAccount(
            branch_id=second.id,
            name="Legacy Shared Cash",
            account_type="cash",
            is_default=False,
            is_active=True,
        )
        db.session.add_all([second_product, second_customer, second_cash])
        db.session.flush()
        db.session.add(
            AccountTransaction(
                branch_id=second.id,
                type="deposit",
                amount=1000,
                note="Legacy shared cash test",
                treasury_account_id=second_cash.id,
            )
        )
        db.session.commit()

        main_id = main.id
        second_id = second.id
        second_product_id = second_product.id
        second_customer_id = second_customer.id
        cashier_id = cashier.id
        second_cash_id = second_cash.id

        with app.test_request_context("/inventory"):
            g.tenant = tenant
            session.update(user_id=admin.id, role="admin", tenant_slug=tenant)
            init_branch_context()
            assert g.independent_branches_enabled is False
            assert can_switch_branch() is False
            assert {row.id for row in Product.query.all()} == {
                first_product.id,
                second_product.id,
            }
            assert resolve_write_branch_id({"branch_id": second_id}) == main_id

        # Legacy companies keep the old shared-catalog behavior: a regular
        # employee can sell a product/customer carrying any historical branch
        # id without choosing a branch.  The invoice uses the hidden default
        # branch while the stock line remembers the product's actual branch.
        with app.test_request_context(
            "/pos/create-order",
            method="POST",
            json={
                "customer_id": second_customer_id,
                "items": [
                    {
                        "product_id": second_product_id,
                        "qty": 1,
                        "price": 200,
                    }
                ],
            },
        ):
            g.tenant = tenant
            session.update(
                user_id=cashier_id,
                role="cashier",
                tenant_slug=tenant,
            )
            init_branch_context()
            response = create_order()
            assert response.status_code == 200
            payload = response.get_json()
            assert payload["success"] is True
            invoice_id = payload["invoice_id"]

        invoice = Invoice.query.get(invoice_id)
        line = OrderItem.query.filter_by(invoice_id=invoice_id).one()
        assert invoice.branch_id == main_id
        assert line.product_id == second_product_id
        assert line.fulfillment_branch_id == second_id

        # The same compatibility rule applies to cash/bank accounts.  A
        # legacy expense may use an account carrying the other historical
        # branch id, while independent-branch tenants remain strict.
        with app.test_request_context(
            "/expenses/",
            method="POST",
            data={"treasury_account_id": str(second_cash_id)},
        ):
            g.tenant = tenant
            session.update(
                user_id=cashier_id,
                role="cashier",
                tenant_slug=tenant,
            )
            init_branch_context()
            assert resolve_treasury_account_id(str(second_cash_id)) == second_cash_id
            expense = Expense(
                branch_id=main_id,
                title="Legacy cross-branch expense",
                category="أخرى",
                amount=100,
                expense_date=date.today(),
                treasury_account_id=second_cash_id,
                cash_posted=False,
            )
            db.session.add(expense)
            db.session.flush()
            withdrawal = _post_expense_to_treasury(expense, second_cash_id)
            db.session.commit()
            assert withdrawal.treasury_account_id == second_cash_id
            assert withdrawal.branch_id == main_id

        persisted_flags = SystemSettings.query.first().get_ui_flags()
        assert persisted_flags["independent_branches_enabled"] is False
        assert persisted_flags["branch_scope_v3_done"] is True
        assert persisted_flags["legacy_shared_mode_enabled"] is True
