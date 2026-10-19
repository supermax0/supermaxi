"""Desktop-inspired home preserves its data, privacy controls and role-specific shell."""
import re
from tests.test_page_read_safety import safety, client, money_state


def test_home_keeps_data_controls_and_no_financial_writes(safety, client):
    before = money_state(safety)
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="finoraDesktopHome"' in html and '/static/css/dashboard-desktop.css?v=20261019b' in html
    for field in ['finoraSalesValue', 'finoraPurchasesValue', 'finoraInventoryValue', 'desktopHomePeriod',
                  'periodLabel', 'dashboardPrivacyBtn', 'salesChart', 'profitChart', 'statusChart',
                  'financialYearChart', 'searchModal', 'profitModal', 'addExpenseModal', 'dashAlertsModal']:
        assert html.count('id="'+field+'"') == 1, field
    assert 'data-dashboard-private="true"' in html
    assert 'finora-sparkline' not in html
    assert money_state(safety) == before


def staff_session(safety, client, role):
    from flask import g
    from extensions import db
    from models.employee import Employee
    with safety["app"].app_context():
        g.tenant = safety["tenant"]
        employee = Employee(name="Home staff", username="home_"+role, password="unused", role=role,
                            is_active=True, tenant_id=safety["company"], branch_id=safety["branch"])
        db.session.add(employee)
        db.session.commit()
        user_id = employee.id
    with client.session_transaction() as session:
        session.update(user_id=user_id, role=role)


def test_cashier_has_welcome_without_financial_dashboard(safety, client, monkeypatch):
    staff_session(safety, client, 'cashier')
    monkeypatch.setattr('utils.permission_checks.check_permission', lambda key: key in {'view_dashboard', 'can_view_dashboard'})
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'dashboard-welcome-title' in html
    assert 'id="finoraDesktopHome"' not in html and 'id="finoraSalesValue"' not in html
    assert '/static/css/dashboard-desktop.css?v=20261019b' in html


def test_launcher_obeys_inventory_and_order_permissions(safety, client, monkeypatch):
    staff_session(safety, client, 'sales')
    monkeypatch.setattr('utils.permission_checks.check_permission', lambda key: key in {'view_dashboard', 'can_view_dashboard'})
    import importlib
    index_routes = importlib.import_module('routes.index')
    original = index_routes.render_template
    def render(name, **kwargs):
        if name == 'dashbord.html':
            kwargs.update(is_admin=False, can_see_orders=False, can_manage_inventory=False,
                          can_manage_customers=False, can_use_pos=False, show_pos=False)
        return original(name, **kwargs)
    monkeypatch.setattr(index_routes, 'render_template', render)
    html = client.get('/').get_data(as_text=True)
    launcher = re.search(r'<nav class="desktop-home-launcher".*?</nav>', html, re.S)[0]
    assert 'href="/inventory/"' not in launcher and 'href="/orders/"' not in launcher
    assert 'href="/customers/"' not in launcher and 'href="/pos"' not in launcher
