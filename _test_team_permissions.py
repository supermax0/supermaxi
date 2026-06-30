"""Integration smoke tests for team/permissions plan."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def test_imports():
    from utils.permission_checks import check_permission, employee_can, LEGACY_TO_RBAC, migrate_legacy_permissions_to_roles
    from utils.agent_passwords import hash_agent_password, verify_agent_password
    from routes import employees, agents, pages, permissions
    assert "manage_employees" in dict(permissions.DEFAULT_PERMISSIONS)
    assert "view_orders_shipped" in dict(permissions.DEFAULT_PERMISSIONS)
    assert len(LEGACY_TO_RBAC) >= 10
    pwd = hash_agent_password("secret123")
    assert verify_agent_password(pwd, "secret123")
    assert not verify_agent_password(pwd, "wrong")
    print("imports ok")


def test_routes_use_central_permission():
    import inspect
    from routes import inventory, expenses, purchases, cash, inventory_ledger, orders, pos
    for mod in (inventory, expenses, purchases, cash, inventory_ledger, orders, pos):
        src = inspect.getsource(mod)
        assert (
            "from utils.permission_checks import check_permission" in src
            or "employee_can" in src
            or "has_permission" in src
        ), mod.__name__
    print("central permission imports ok")


def test_templates():
  tpl = (ROOT / "templates/employees.html").read_text(encoding="utf-8")
  assert "employees-admin.css" in tpl
  assert "employees-admin.js" in tpl
  js = (ROOT / "static/js/employees-admin.js").read_text(encoding="utf-8")
  assert "/admin/permissions/employee/" in js
  assert 'method="post"' in js.lower() and "/employees/toggle/" in js
  er = (ROOT / "templates/admin/permissions/employee_roles.html").read_text(encoding="utf-8")
  assert "employees.employees" in er
  roles = (ROOT / "templates/admin/permissions/roles.html").read_text(encoding="utf-8")
  assert "can_*" in roles or "RBAC" in roles or "الصلاحيات القديمة" in roles
  pages = (ROOT / "templates/pages.html").read_text(encoding="utf-8")
  assert "update-visibility" in pages or "updateVisibility" in pages
  agents_tpl = (ROOT / "templates/agents.html").read_text(encoding="utf-8")
  assert "/employees" in agents_tpl
  print("templates ok")


def test_app_open_routes():
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    app_server_py = (ROOT / "app_server.py").read_text(encoding="utf-8")
    assert "/delivery-agent" in app_py
    assert "/delivery-agent" in app_server_py
    print("open routes ok")


if __name__ == "__main__":
    test_imports()
    test_routes_use_central_permission()
    test_templates()
    test_app_open_routes()
    print("ALL TESTS PASSED")
