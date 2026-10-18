"""POS invoice printing permission regression tests."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _make_app():
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
    return app


def test_cashier_can_print_even_with_rbac_roles_assigned():
    from types import SimpleNamespace

    from utils.permission_checks import employee_can

    cashier = SimpleNamespace(
        is_active=True,
        role="cashier",
        roles=[object()],
        has_permission=lambda _name: False,
    )
    assert employee_can(cashier, "print_pos_invoice") is True
    assert employee_can(cashier, "view_pos") is False


def test_cashier_role_receives_print_permission():
    app = _make_app()
    from extensions import db
    from models.employee import Employee
    from models.role import Permission, Role
    from utils.permission_checks import employee_can, ensure_cashier_role_has_messages

    with app.app_context():
        permission = Permission(
            name="print_pos_invoice",
            description="طباعة فاتورة نقطة البيع",
        )
        messages = Permission(name="view_messages", description="مراسلة")
        cashier_role = Role(name="cashier", description="كاشير")
        cashier = Employee(
            name="Cashier",
            username="cashier",
            password="pw",
            role="cashier",
            is_active=True,
        )
        admin = Employee(
            name="Admin",
            username="admin",
            password="pw",
            role="admin",
            is_active=True,
        )
        db.session.add_all([permission, messages, cashier_role, cashier, admin])
        db.session.flush()
        cashier.roles.append(cashier_role)
        db.session.flush()

        assert employee_can(cashier, "print_pos_invoice") is True
        assert employee_can(admin, "print_pos_invoice") is True

        ensure_cashier_role_has_messages()
        db.session.refresh(cashier_role)

        assert any(p.name == "print_pos_invoice" for p in cashier_role.permissions)
        assert employee_can(cashier, "print_pos_invoice") is True


def test_print_permission_is_listed_in_defaults():
    from routes.permissions import DEFAULT_PERMISSIONS

    names = {name for name, _description in DEFAULT_PERMISSIONS}
    assert "print_pos_invoice" in names
