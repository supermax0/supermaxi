"""POS access regression tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_pos_redirects_to_pos_login_without_session():
    from app import app

    with app.test_client() as client:
        resp = client.get("/pos", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/pos/login")
        login = client.get("/pos/login")
        assert login.status_code == 200
        assert "تسجيل الدخول" in login.get_data(as_text=True)
        print("test_pos_redirects_to_pos_login_without_session ok")


def test_legacy_cashier_can_view_pos_without_rbac_roles():
    from app import app

    tenant = "test_pos_access"
    with app.app_context():
        from flask import g
        from extensions import db
        from extensions_tenant import init_tenant_db
        from models.employee import Employee
        from utils.permission_checks import employee_can

        g.tenant = tenant
        init_tenant_db(tenant)
        emp = Employee(
            name="Legacy Cashier",
            username="legacy_cashier",
            password="pw",
            role="cashier",
            is_active=True,
        )
        db.session.add(emp)
        db.session.commit()

        assert employee_can(emp, "view_pos")
        print("test_legacy_cashier_can_view_pos_without_rbac_roles ok")


def test_pos_login_get_is_not_permission_guarded():
    from app import app

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 999
        resp = client.get("/pos/login")
        assert resp.status_code == 200
        assert "تسجيل الدخول" in resp.get_data(as_text=True)
        print("test_pos_login_get_is_not_permission_guarded ok")


if __name__ == "__main__":
    test_pos_redirects_to_pos_login_without_session()
    test_legacy_cashier_can_view_pos_without_rbac_roles()
    test_pos_login_get_is_not_permission_guarded()
    print("pos access tests passed")
