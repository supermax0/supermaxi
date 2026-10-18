"""Real role, source-view, target-branch, approval and replay authorization."""
import json
from uuid import uuid4
import pytest
from tests.test_finance_operations import finance, balance
from tests.test_desktop_stock_operations import stock
from tests.test_desktop_order_returns_shipping import shipment
from tests.test_sales_return_posting import prepare, body, perform


def employee(f, names):
    from models.employee import Employee
    from models.role import Permission, Role
    permissions = []
    for name in names:
        permission = Permission.query.filter_by(name=name).first()
        if permission is None:
            permission = Permission(name=name)
            f["db"].session.add(permission)
        permissions.append(permission)
    role = Role(name=uuid4().hex, permissions=permissions)
    row = Employee(name="موظف المرتجعات", username=uuid4().hex, password="test", role="staff",
        branch_id=f["branch"].id, is_active=True, roles=[role])
    f["db"].session.add(row)
    f["db"].session.commit()
    return row, role


def as_employee(f, row, fn):
    from flask import g, session
    with f["app"].test_request_context("/returns", method="POST"):
        session.update(user_id=row.id, employee_id=row.id, role=row.role, tenant_slug=f["tenant"])
        g.tenant=f["tenant"]; g.branch=f["branch"]; g.branches=[f["branch"]]
        g.view_all_branches=False; g.independent_branches_enabled=True; g.branch_scope_ready=True
        return fn()


def test_staff_source_access_target_branch_and_revoked_replay_are_enforced(shipment):
    from modules.sales_returns.service import execute
    from modules.sales_returns.models import SalesReturn
    from modules.finance.common import FinanceError
    f = shipment
    prepare(f)
    request = body(f)
    user, role = employee(f, ["return_orders", "view_orders", "view_orders_delivered", "view_orders_shipped", "view_orders_returned"])
    request["return_branch_id"] = f["destination"].id
    with pytest.raises(FinanceError) as denied:
        as_employee(f, user, lambda: execute(request))
    assert denied.value.status == 403 and SalesReturn.query.count() == 0
    assert "فرع الاستلام" in str(denied.value)
    assert f["order"].total == 800
    request["return_branch_id"] = f["branch"].id
    result = as_employee(f, user, lambda: execute(request))
    assert result["credit"] == 400 and SalesReturn.query.count() == 1
    assert as_employee(f, user, lambda: execute(request)) == result
    with pytest.raises(FinanceError, match="موظف آخر"):
        perform(f, request)
    role.permissions = [permission for permission in role.permissions if permission.name != "return_orders"]
    f["db"].session.commit()
    with pytest.raises(FinanceError) as denied:
        as_employee(f, user, lambda: execute(request))
    assert denied.value.status == 403
    assert SalesReturn.query.count() == 1 and balance(f) == 20_000_000 and balance(f, "bank") == 400


def test_return_permission_alone_does_not_grant_source_visibility(shipment):
    from modules.sales_returns.service import execute
    from modules.sales_returns.models import SalesReturn
    from modules.finance.common import FinanceError
    f = shipment
    prepare(f)
    request = body(f)
    user, _ = employee(f, ["return_orders"])
    with pytest.raises(FinanceError) as denied:
        as_employee(f, user, lambda: execute(request))
    assert denied.value.status == 403 and SalesReturn.query.count() == 0


def test_large_debt_relief_requires_approval_even_without_cash_refund(shipment):
    from modules.sales_returns.service import execute
    from modules.sales_returns.models import SalesReturn
    from modules.finance.common import FinanceError
    from modules.finance.models import FinancePolicy
    from models.role import Permission
    f = shipment
    prepare(f, paid=False)
    request = body(f)
    user, role = employee(f, ["return_orders", "view_orders", "view_orders_shipped"])
    policy = f["db"].session.get(FinancePolicy, 1)
    policy.settings = json.dumps({**json.loads(policy.settings), "approval_limit": 100})
    f["db"].session.commit()
    with pytest.raises(FinanceError) as denied:
        as_employee(f, user, lambda: execute(request))
    assert denied.value.status == 403 and SalesReturn.query.count() == 0
    permission = Permission.query.filter_by(name="finance.approve_large").one()
    role.permissions.append(permission)
    f["db"].session.commit()
    result = as_employee(f, user, lambda: execute(request))
    assert result["debt_relief"] == 400 and result["refund"] == 0
    assert balance(f) == 20_000_000 and SalesReturn.query.count() == 1
