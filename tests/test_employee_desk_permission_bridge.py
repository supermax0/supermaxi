from types import SimpleNamespace

from utils import permission_checks


class FakeEmployee:
    def __init__(self, *, role="cashier", roles=None, active=True, direct=False):
        self.role = role
        self.roles = list(roles or [])
        self.is_active = active
        self._direct = direct

    def has_permission(self, _permission_name):
        return self._direct


def test_legacy_cashier_without_rbac_assignment_inherits_primary_role(monkeypatch):
    employee = FakeEmployee(role="cashier", roles=[])
    monkeypatch.setattr(
        permission_checks,
        "_primary_role_has_permission",
        lambda current, permission: current is employee and permission == "use_employee_desk",
    )

    assert permission_checks.employee_can(employee, "use_employee_desk") is True


def test_explicit_employee_role_permissions_still_work(monkeypatch):
    employee = FakeEmployee(role="cashier", roles=[SimpleNamespace(name="custom")], direct=True)
    monkeypatch.setattr(
        permission_checks,
        "_primary_role_has_permission",
        lambda *_args: False,
    )

    assert permission_checks.employee_can(employee, "use_employee_desk") is True


def test_inactive_employee_cannot_use_desk(monkeypatch):
    employee = FakeEmployee(active=False)
    monkeypatch.setattr(
        permission_checks,
        "_primary_role_has_permission",
        lambda *_args: True,
    )

    assert permission_checks.employee_can(employee, "use_employee_desk") is False
