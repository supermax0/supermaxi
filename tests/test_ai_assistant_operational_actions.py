"""Regression tests for approved operational actions created by the AI assistant."""
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_ai_assistant_actions_{os.getpid()}"


def _fresh_tenant_db():
    db_file = ROOT / "tenants" / f"{TENANT}.db"
    if db_file.exists():
        db_file.unlink()


def _setup():
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.employee import Employee

    g.tenant = TENANT
    init_tenant_db(TENANT)
    employee = Employee(name="AI Admin", username="ai-admin", password="test", role="admin")
    db.session.add(employee)
    db.session.commit()
    return app, employee


def test_duplicate_shipping_collection_plan_deletes_only_latest_and_restores_due():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from flask import g
    from models.shipping import ShippingCompany
    from models.shipping_payment import ShippingPayment
    from utils.ai_assistant_service import (
        approve_action_plan,
        build_shipping_duplicate_payment_plan,
        execute_action_plan,
    )
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        _, employee = _setup()
        cash = get_default_cash_account()
        company = ShippingCompany(name="Test Courier", opening_balance=100_000)
        db.session.add(company)
        db.session.flush()
        db.session.add_all(
            [
                ShippingPayment(
                    shipping_company_id=company.id,
                    amount=182_000,
                    action="قبض",
                    treasury_account_id=cash.id,
                ),
                ShippingPayment(
                    shipping_company_id=company.id,
                    amount=182_000,
                    action="قبض",
                    treasury_account_id=cash.id,
                ),
            ]
        )
        db.session.commit()

        plan, meta = build_shipping_duplicate_payment_plan(
            "قبضت بالغلط مرتين من شركة النقل 182 الف احذف وحدة",
            employee_id=employee.id,
        )
        assert plan is not None
        assert meta["matched_groups"] == 1
        deleted_id = plan.items[0].target_id
        assert calculate_treasury_balance(cash.id) == 364_000

        db.session.commit()
        approve_action_plan(plan.id, employee_id=employee.id)
        execute_action_plan(plan.id, employee_id=employee.id)

        assert ShippingPayment.query.get(deleted_id) is None
        assert ShippingPayment.query.count() == 1
        assert company.opening_balance == 282_000
        assert calculate_treasury_balance(cash.id) == 182_000
        try:
            execute_action_plan(plan.id, employee_id=employee.id)
        except ValueError as exc:
            assert "موافقة" in str(exc)
        else:
            raise AssertionError("An executed AI plan must not run twice")


def test_router_cash_asset_plan_posts_asset_and_withdraws_cash():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.fixed_asset import FixedAsset
    from utils.ai_assistant_service import (
        approve_action_plan,
        build_fixed_asset_action_plan,
        execute_action_plan,
    )
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        _, employee = _setup()
        cash = get_default_cash_account()
        db.session.add(AccountTransaction(type="deposit", amount=500_000, note="test funding", treasury_account_id=cash.id))
        db.session.commit()

        plan, meta = build_fixed_asset_action_plan(
            "اليوم اشتريت راوتر بسعر 125 الف رتبه وسحب من الصندوق",
            employee_id=employee.id,
        )
        assert plan is not None
        assert meta["cash_effect"] == -125_000
        db.session.commit()
        approve_action_plan(plan.id, employee_id=employee.id)
        execute_action_plan(plan.id, employee_id=employee.id)

        asset = FixedAsset.query.filter_by(name="راوتر").one()
        assert asset.status == "active"
        assert asset.payment_method == "cash"
        assert asset.acquisition_journal_entry_id is not None
        assert calculate_treasury_balance(cash.id) == 375_000


def test_car_asset_capital_plan_does_not_change_cash_or_create_supplier_debt():
    _fresh_tenant_db()
    from app import app
    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.fixed_asset_category import FixedAssetCategory
    from utils.ai_assistant_service import (
        approve_action_plan,
        build_fixed_asset_action_plan,
        execute_action_plan,
    )
    from utils.fixed_assets_service import build_asset_from_form, seed_default_categories
    from utils.treasury_calculations import calculate_treasury_balance
    from utils.treasury_helpers import get_default_cash_account

    with app.app_context():
        _, employee = _setup()
        cash = get_default_cash_account()
        db.session.add(AccountTransaction(type="deposit", amount=1_000_000, note="test funding", treasury_account_id=cash.id))
        seed_default_categories()
        category = FixedAssetCategory.query.filter(FixedAssetCategory.name.ilike("%سيارات%")).first()
        asset = build_asset_from_form(
            {
                "name": "سيارة كيا",
                "category_id": category.id,
                "purchase_price": 25_000_000,
                "purchase_date": "2026-05-01",
                "payment_method": "cash",
                "treasury_account_id": cash.id,
            },
            user_id=employee.id,
            as_draft=True,
        )
        db.session.commit()
        cash_before = calculate_treasury_balance(cash.id)

        plan, _ = build_fixed_asset_action_plan(
            "رتبلي الاصل مال سيارة بس ماريده ياخذ من الصندوق",
            employee_id=employee.id,
        )
        assert plan is not None
        db.session.commit()
        approve_action_plan(plan.id, employee_id=employee.id)
        execute_action_plan(plan.id, employee_id=employee.id)

        assert asset.status == "active"
        assert asset.payment_method == "capital"
        assert asset.paid_amount == 0
        assert asset.credit_amount == 0
        assert calculate_treasury_balance(cash.id) == cash_before
