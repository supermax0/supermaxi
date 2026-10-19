"""Real tenant acceptance for status access and more than one grid page."""
from collections import Counter
from datetime import datetime
import json
import re

import pytest

from tests.test_page_read_safety import safety, client, money_state  # noqa: F401


@pytest.fixture(scope="module")
def workspace(safety):
    from extensions import db
    from flask import g
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.role import Role, Permission

    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        customer = Customer(name="Workspace 525", phone="07700000525", city="Baghdad", branch_id=safety["branch"])
        db.session.add(customer)
        db.session.flush()
        statuses = ["تم الطلب", "معباة", "جاري الشحن", "تم التوصيل", "راجع", "ملغي", "تم الطلب"]
        expected = []
        for index in range(525):
            invoice = Invoice(customer_id=customer.id, customer_name=customer.name,
                              total=(index + 1) * 100, paid_amount=0, status=statuses[index % 7],
                              payment_status="غير مسدد", branch_id=safety["branch"],
                              created_at=datetime(2026, 10, 1, 9, 0), barcode=f"WS-{index:04}")
            db.session.add(invoice)
            db.session.flush()
            db.session.add(OrderItem(invoice_id=invoice.id, product_id=safety["product"],
                                     product_name="Workspace product", price=invoice.total // 2,
                                     quantity=2, total=invoice.total, cost=0))
            expected.append({"id": invoice.id, "total": invoice.total, "status": invoice.status})
        users = {}
        role_grants = {
            "cashier": ("view_orders", "view_orders_placed", "view_pos", "view_quick_sale"),
            "staff": ("view_orders", "view_orders_placed", "view_reports"),
            "delivery": ("view_orders", "view_orders_shipped", "view_agents"),
        }
        for role_name, grants in role_grants.items():
            role = Role(name="workspace_" + role_name)
            for name in grants:
                permission = Permission.query.filter_by(name=name).first()
                if permission is None:
                    permission = Permission(name=name)
                    db.session.add(permission)
                role.permissions.append(permission)
            employee = Employee(name="Workspace " + role_name, username="ws_" + role_name,
                                password="unused", role=role_name, is_active=True,
                                branch_id=safety["branch"], tenant_id=safety["company"], roles=[role])
            db.session.add(employee)
            db.session.flush()
            users[role_name] = employee.id
        db.session.commit()
        customer_id = customer.id
    return {"rows": expected, "users": users, "customer": customer_id}


def login_as(client, workspace, role):
    with client.session_transaction() as session:
        session.update(user_id=workspace["users"][role], role=role)


@pytest.mark.parametrize("path", ["/orders/cancelled", "/orders/data?page_type=cancelled", "/orders/api/counts"])
def test_cancelled_orders_require_return_permission(safety, client, workspace, path):
    login_as(client, workspace, "staff")
    response = client.get(path)
    if path.endswith("counts"):
        assert response.status_code == 200
        assert "cancelled" not in response.json["counts"]
    elif path == "/orders/cancelled":
        assert response.status_code == 302 and response.location.endswith("/pos")
        assert client.get(path, headers={"Accept": "application/json"}).status_code == 403
    else:
        assert response.status_code == 403


def data(client, **params):
    response = client.get("/orders/data", query_string={"search": "Workspace 525", **params})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert response.json["success"]
    return response.json


def test_525_orders_pagination_totals_and_sorting(safety, client, workspace):
    before = money_state(safety)
    expected = workspace["rows"]
    ids = []
    for page in (1, 2):
        result = data(client, page=page, page_size=500, sort_field="total", sort_dir="asc")
        assert result["total"] == 525
        assert result["total_pages"] == 2
        assert result["total_amount"] == sum(row["total"] for row in expected)
        assert result["total_quantity"] == 525  # Existing contract counts item rows, not sold units.
        assert len(result["rows"]) == (500 if page == 1 else 25)
        ids.extend(int(row["order_id"]) for row in result["rows"])
    assert ids == [row["id"] for row in expected]
    assert len(set(ids)) == 525
    assert money_state(safety) == before


@pytest.mark.parametrize("page_type,statuses", [
    ("ordered", {"تم الطلب"}), ("packed", {"معباة"}),
    ("shipping", {"جاري الشحن"}), ("delivered", {"تم التوصيل"}),
    ("returned", {"راجع", "ملغي"}), ("cancelled", {"ملغي"}),
])
def test_status_views_totals_cover_complete_result(client, workspace, page_type, statuses):
    expected = [row for row in workspace["rows"] if row["status"] in statuses]
    result = data(client, page_type=page_type, page_size=100)
    assert result["total"] == len(expected)
    assert result["total_amount"] == sum(row["total"] for row in expected)


def test_numeric_filter_and_empty_result_keep_correct_totals(client, workspace):
    result = data(client, filter_model=json.dumps({"total": {"type": "greaterThan", "filter": 50000}}),
                  sort_field="total", sort_dir="desc")
    expected = [row for row in workspace["rows"] if row["total"] > 50000]
    assert result["total"] == 25
    assert result["total_amount"] == sum(row["total"] for row in expected)
    assert [int(row["total"]) for row in result["rows"]] == sorted([row["total"] for row in expected], reverse=True)
    empty = data(client, amount_min=999999)
    assert empty["rows"] == [] and empty["total_amount"] == empty["total_quantity"] == empty["total"] == 0


def test_staff_all_view_never_includes_forbidden_statuses(client, workspace):
    login_as(client, workspace, "staff")
    result = data(client, page_size=500)
    expected = [row for row in workspace["rows"] if row["status"] == "تم الطلب"]
    assert result["total"] == len(expected)
    assert {row["status"] for row in result["rows"]} == {"تم الطلب"}
    assert result["total_amount"] == sum(row["total"] for row in expected)


@pytest.mark.parametrize("role", ["cashier", "staff", "delivery"])
def test_status_tabs_and_direct_routes_follow_actual_permissions(safety, client, workspace, role):
    login_as(client, workspace, role)
    allowed = "shipping" if role == "delivery" else "ordered"
    for page_type in ("ordered", "packed", "shipping", "delivered", "returned", "cancelled"):
        result = client.get("/orders/data", query_string={"page_type": page_type})
        page = client.get("/orders/" + page_type)
        if page_type == allowed:
            assert result.status_code == page.status_code == 200
        else:
            assert result.status_code == 403
            assert page.status_code == 302 and page.location.endswith("/pos")
            assert client.get("/orders/" + page_type, headers={"Accept": "application/json"}).status_code == 403
    from extensions import db
    from flask import g
    from models.system_settings import SystemSettings
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        settings = SystemSettings.get_settings()
        previous = settings.ui_flags
        settings.set_ui_flags({**settings.get_ui_flags(), "navigation_v2": True})
        db.session.commit()
    try:
        html = client.get("/orders/").get_data(as_text=True)
        assert 'id="ordersWorkspace"' in html
        assert set(re.findall(r'data-orders-status="([^"]+)"', html)) == {"all", allowed}
    finally:
        with safety["app"].app_context():
            g.tenant = safety["tenant"]
            SystemSettings.get_settings().ui_flags = previous
            db.session.commit()


@pytest.mark.parametrize("activity", ["general", "starter_business", "hr_management", "clinics", "beauty_center", "wholesale", "food_wholesale_retail"])
@pytest.mark.parametrize("plan", ["basic", "pro", "enterprise"])
@pytest.mark.parametrize("role", ["admin", "cashier", "staff", "delivery"])
def test_real_sidebar_matrix_keeps_identical_guarded_links(safety, workspace, activity, plan, role):
    """Render the real base and real context processors; no access-condition stubs."""
    from extensions import db
    from flask import g, session, render_template
    from models.core.tenant import Tenant as CoreTenant
    from models.tenant import Tenant
    from models.system_settings import SystemSettings
    from utils.sidebar_navigation import _RenderedLinks

    before = money_state(safety)
    with safety["app"].app_context():
        g.tenant = None
        core = CoreTenant.query.filter_by(slug=safety["tenant"]).one()
        previous_activity = core.business_type
        core.business_type = activity
        db.session.commit()
        g.tenant = safety["tenant"]
        tenant = db.session.get(Tenant, safety["company"])
        previous_plan = tenant.plan_key
        tenant.plan_key = plan
        settings = SystemSettings.get_settings()
        previous_flags = settings.ui_flags
        settings.set_ui_flags({**settings.get_ui_flags(), "navigation_v2": True})
        db.session.commit()
    try:
        rendered = []
        for mode in ("classic", "organized"):
            with safety["app"].test_request_context("/orders/?navigation=" + mode):
                g.tenant = safety["tenant"]
                session.update(user_id=safety["admin"] if role == "admin" else workspace["users"][role],
                               role=role, tenant_slug=safety["tenant"], tenant_id=safety["company"],
                               branch_id=safety["branch"], business_type=activity, plan_key=plan)
                html = render_template("base.html")
                if role == "admin" and plan == "enterprise":
                    appearance = render_template("settings_appearance.html", settings=SystemSettings.get_settings())
                    switch = re.search(r'<input[^>]*id="organizedNavigation"[^>]*>', appearance).group(0)
                    assert ('disabled' in switch) == (activity not in {"general", "starter_business"})
                match = re.search(r'<nav class="menu"[^>]*>(.*?)</nav>', html, re.S)
                assert match
                parser = _RenderedLinks()
                parser.feed(match.group(1))
                rendered.append(Counter("".join(link["html"]) for link in parser.links))
                expected_organized = mode == "organized" and activity in {"general", "starter_business"}
                # The base template also mentions the selector inside its
                # active-link JavaScript; inspect the actual navigation tag.
                assert bool(re.search(r'<nav\b[^>]*\bdata-organized-navigation(?:\s|>)', html)) == expected_organized
        assert rendered[0] == rendered[1]
        assert money_state(safety) == before
    finally:
        with safety["app"].app_context():
            g.tenant = None
            CoreTenant.query.filter_by(slug=safety["tenant"]).one().business_type = previous_activity
            db.session.commit()
            g.tenant = safety["tenant"]
            db.session.get(Tenant, safety["company"]).plan_key = previous_plan
            SystemSettings.get_settings().ui_flags = previous_flags
            db.session.commit()


def test_workspace_opt_in_and_classic_rollback(safety, client, workspace):
    before = money_state(safety)
    for enabled in (True, False):
        saved = client.post("/settings/appearance/update", json={"ui_flags": {"navigation_v2": enabled}})
        assert saved.status_code == 200 and saved.json["success"]
        html = client.get("/orders/").get_data(as_text=True)
        assert ('id="ordersWorkspace"' in html) == enabled
        assert 'orders-views.js' not in html
        assert 'ordersSavedFilter' not in html
        assert 'id="ordersWorkspace"' not in client.get("/orders/?navigation=classic").get_data(as_text=True)
    assert money_state(safety) == before


def test_return_permission_grants_cancelled_data_and_counts(safety, client, workspace):
    from extensions import db
    from flask import g
    from models.employee import Employee
    from models.role import Permission
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        employee = db.session.get(Employee, workspace["users"]["staff"])
        role = employee.roles[0]
        permission = Permission.query.filter_by(name="view_orders_returned").one()
        role.permissions.append(permission)
        db.session.commit()
    try:
        login_as(client, workspace, "staff")
        assert client.get("/orders/cancelled").status_code == 200
        result = data(client, page_type="cancelled")
        assert result["total"] == 75
        assert client.get("/orders/api/counts").json["counts"]["cancelled"] == 75
    finally:
        with safety["app"].app_context():
            g.tenant = safety["tenant"]
            employee = db.session.get(Employee, workspace["users"]["staff"])
            permission = Permission.query.filter_by(name="view_orders_returned").one()
            employee.roles[0].permissions.remove(permission)
            db.session.commit()
