from utils.order_status import PENDING_STATUSES
from utils.permission_checks import allowed_order_statuses_for, employee_can_access_order


class FakeEmployee:
    is_active = True
    role = "staff"

    def __init__(self, permissions):
        self.permissions = set(permissions)

    def has_permission(self, permission_name):
        return permission_name in self.permissions


class FakeOrder:
    status = "معباة"


def test_packed_orders_are_pending():
    assert "معباة" in PENDING_STATUSES


def test_packed_order_permission_is_independent():
    employee = FakeEmployee({"view_orders", "view_orders_packed"})

    assert allowed_order_statuses_for(employee) == ["معباة"]
    assert employee_can_access_order(employee, FakeOrder())
