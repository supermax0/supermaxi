# -*- coding: utf-8 -*-
"""Tests for order installment lifecycle (timed POS order mode)."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TENANT = f"test_order_installment_{os.getpid()}"


def _ctx():
    from app import app
    from flask import g
    from extensions_tenant import init_tenant_db
    from modules.order_installment_lifecycle.schema_guard import ensure_order_installment_tables

    ctx = app.app_context()
    ctx.push()
    g.tenant = TENANT
    init_tenant_db(TENANT)
    ensure_order_installment_tables()
    return app, ctx


def _make_employee(name="Oil Emp", role="cashier", perms=None):
    from extensions import db
    from models.employee import Employee
    from models.role import Role, Permission
    from routes.permissions import ensure_default_permissions

    ensure_default_permissions()
    emp = Employee(
        name=name,
        username=f"{name.replace(' ', '_')}_{os.getpid()}_{id(name)}",
        password="x",
        role=role,
        is_active=True,
    )
    db.session.add(emp)
    db.session.flush()
    if perms:
        role_obj = Role(name=f"oil_role_{emp.id}", description="oil")
        db.session.add(role_obj)
        db.session.flush()
        for pname in perms:
            perm = Permission.query.filter_by(name=pname).first()
            if perm:
                role_obj.permissions.append(perm)
        emp.roles.append(role_obj)
    db.session.commit()
    return emp


def _enable_feature(**kwargs):
    from extensions import db
    from modules.order_installment_lifecycle import service as svc

    payload = {
        "enabled": True,
        "duration_value": 7,
        "duration_unit": "days",
        "auto_settle_enabled": True,
        "confirm_on_create": False,
    }
    payload.update(kwargs)
    svc.update_settings(payload)
    db.session.commit()


def test_global_off_blocks_mode_even_with_permission():
    app, ctx = _ctx()
    try:
        from flask import session
        from modules.order_installment_lifecycle import service as svc
        from modules.order_installment_lifecycle.constants import ERROR_FEATURE_DISABLED

        emp = _make_employee(
            perms=["installment.mode.toggle", "installment.create", "installment.view"]
        )
        with app.test_request_context("/"):
            session["user_id"] = emp.id
            try:
                svc.set_installment_mode(True, employee=emp)
                assert False, "expected feature disabled error"
            except svc.OrderInstallmentError as exc:
                assert exc.code == ERROR_FEATURE_DISABLED
    finally:
        ctx.pop()


def test_mode_requires_permission_when_feature_on():
    app, ctx = _ctx()
    try:
        from flask import session
        from modules.order_installment_lifecycle import service as svc
        from modules.order_installment_lifecycle.constants import ERROR_PERMISSION_DENIED

        _enable_feature()
        emp = _make_employee(perms=["installment.view"])
        with app.test_request_context("/"):
            session["user_id"] = emp.id
            try:
                svc.set_installment_mode(True, employee=emp)
                assert False, "expected permission denied"
            except svc.OrderInstallmentError as exc:
                assert exc.code == ERROR_PERMISSION_DENIED
    finally:
        ctx.pop()


def test_create_lifecycle_sets_due_at():
    app, ctx = _ctx()
    try:
        from flask import session
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from modules.order_installment_lifecycle import service as svc
        from modules.order_installment_lifecycle.constants import STATUS_ACTIVE

        _enable_feature(duration_value=7, duration_unit="days")
        emp = _make_employee(
            perms=[
                "installment.mode.toggle",
                "installment.create",
                "installment.view",
            ]
        )
        customer = Customer(name="Oil Customer", phone="07701112233")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            employee_id=emp.id,
            employee_name=emp.name,
            total=900000,
            status="تم الطلب",
            payment_status="غير مسدد",
            created_at=datetime.utcnow(),
        )
        db.session.add(invoice)
        db.session.flush()

        with app.test_request_context("/"):
            session["user_id"] = emp.id
            svc.set_installment_mode(True, employee=emp)
            lifecycle = svc.start_lifecycle(invoice, emp)
            db.session.commit()

        assert lifecycle is not None
        assert lifecycle.status == STATUS_ACTIVE
        assert lifecycle.order_id == invoice.id
        expected = (invoice.created_at or datetime.utcnow()) + timedelta(days=7)
        assert abs((lifecycle.due_at - expected).total_seconds()) < 2
    finally:
        ctx.pop()


def test_full_return_stops_auto_settle():
    app, ctx = _ctx()
    try:
        from flask import session
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from modules.order_installment_lifecycle import service as svc
        from modules.order_installment_lifecycle.constants import STATUS_RETURNED

        _enable_feature()
        emp = _make_employee(
            perms=["installment.mode.toggle", "installment.create", "installment.view"]
        )
        customer = Customer(name="Oil Return", phone="07701112234")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=500000,
            status="جاري الشحن",
            payment_status="غير مسدد",
            barcode="OIL-RET-1",
            created_at=datetime.utcnow(),
        )
        db.session.add(invoice)
        db.session.flush()
        with app.test_request_context("/"):
            session["user_id"] = emp.id
            svc.set_installment_mode(True, employee=emp)
            lifecycle = svc.start_lifecycle(invoice, emp)
            lifecycle.due_at = datetime.utcnow() - timedelta(minutes=1)
            db.session.commit()

            invoice.status = "راجع"
            invoice.payment_status = "راجع"
            invoice.paid_amount = 0
            svc.on_order_returned(invoice)
            db.session.commit()

        lifecycle = svc.get_lifecycle_for_order(invoice.id)
        assert lifecycle.status == STATUS_RETURNED
        result = svc.auto_settle_due(lifecycle.id)
        db.session.commit()
        assert result.get("ok") is False
        assert result.get("skipped") in {"status", "order_blocked"}
    finally:
        ctx.pop()


def test_auto_settle_idempotent():
    app, ctx = _ctx()
    try:
        from flask import session
        from extensions import db
        from models.customer import Customer
        from models.invoice import Invoice
        from modules.order_installment_lifecycle import service as svc
        from modules.order_installment_lifecycle.constants import STATUS_AUTO_SETTLED
        from utils.payment_ledger import ensure_invoice_payment_ledger_table
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from sqlalchemy import func

        _enable_feature()
        ensure_invoice_payment_ledger_table()
        emp = _make_employee(
            perms=["installment.mode.toggle", "installment.create", "installment.view"]
        )
        customer = Customer(name="Oil Settle", phone="07701112235")
        db.session.add(customer)
        db.session.flush()
        invoice = Invoice(
            customer_id=customer.id,
            customer_name=customer.name,
            total=600000,
            status="تم الطلب",
            payment_status="غير مسدد",
            paid_amount=0,
            created_at=datetime.utcnow(),
        )
        db.session.add(invoice)
        db.session.flush()
        with app.test_request_context("/"):
            session["user_id"] = emp.id
            svc.set_installment_mode(True, employee=emp)
            lifecycle = svc.start_lifecycle(invoice, emp)
            lifecycle.due_at = datetime.utcnow() - timedelta(minutes=1)
            db.session.commit()

            first = svc.auto_settle_due(lifecycle.id)
            db.session.commit()
            second = svc.auto_settle_due(lifecycle.id)
            db.session.commit()

        assert first.get("ok") is True
        assert first.get("amount") == 600000
        assert second.get("ok") is False
        lifecycle = svc.get_lifecycle_for_order(invoice.id)
        assert lifecycle.status == STATUS_AUTO_SETTLED
        db.session.refresh(invoice)
        assert invoice.payment_status == "مسدد"
        assert int(invoice.paid_amount or 0) == 600000
        ledger_sum = (
            db.session.query(func.coalesce(func.sum(InvoicePaymentLedger.amount_delta), 0))
            .filter(InvoicePaymentLedger.invoice_id == invoice.id)
            .scalar()
        )
        assert int(ledger_sum or 0) == 600000
    finally:
        ctx.pop()


def test_login_resets_installment_mode():
    app, ctx = _ctx()
    try:
        from flask import session
        from modules.order_installment_lifecycle.constants import SESSION_MODE_KEY

        with app.test_request_context("/"):
            session[SESSION_MODE_KEY] = True
            session.clear()
            session.permanent = True
            session["user_id"] = 1
            session[SESSION_MODE_KEY] = False
            assert session.get(SESSION_MODE_KEY) is False
    finally:
        ctx.pop()


def test_permissions_catalog_includes_installment_keys():
    from routes.permissions import DEFAULT_PERMISSIONS

    names = {name for name, _ in DEFAULT_PERMISSIONS}
    assert {
        "installment.view",
        "installment.mode.toggle",
        "installment.create",
        "installment.settings",
    } <= names
