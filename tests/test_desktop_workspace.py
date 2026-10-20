"""Workspace acceptance checks against real tenant ORM/report/debt engines."""
from datetime import datetime

import pytest
from flask import g

from tests.test_desktop_data_api import ctx, _client, JSON, TENANT  # noqa: F401


def test_workspace_sales_matches_the_existing_sales_report(ctx):
    client = _client(ctx)
    summary = client.get("/api/v1/desktop/workspace/sales", headers=JSON)
    report = client.get("/reports/api/v2/section/sales?period=today", headers=JSON)
    yesterday = client.get("/reports/api/v2/section/sales?period=yesterday", headers=JSON)
    assert summary.status_code == report.status_code == yesterday.status_code == 200
    body = summary.get_json()
    assert body["value"] == report.get_json()["metrics"]["net"]
    assert body["previous"] == yesterday.get_json()["metrics"]["net"]
    assert body["date"] == report.get_json()["filters"]["date_from"]
    assert "no-store" in summary.headers["Cache-Control"]


def test_workspace_receivables_match_actual_customer_balances(ctx):
    client = _client(ctx)
    summary = client.get("/api/v1/desktop/workspace/receivables", headers=JSON)
    reference = client.get("/api/v1/desktop/customers?page=1&page_size=10&tab=all", headers=JSON)
    assert summary.status_code == reference.status_code == 200
    body, stats = summary.get_json(), reference.get_json()["data"]["stats"]
    assert body["value"] == stats["debt"]
    assert body["overdue"] == stats["overdue"]
    assert body["debtors"] == stats["debtors"]


@pytest.mark.parametrize("path", ["sales", "receivables", "activity", "shipping"])
def test_workspace_requires_authenticated_tenant(ctx, path, monkeypatch):
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    response = ctx["app"].test_client().get(f"/api/v1/desktop/workspace/{path}", headers=JSON)
    assert response.status_code == 401


@pytest.mark.parametrize("path,reference", [("sales", "/reports/api/v2/section/sales?period=today"), ("receivables", "/api/v1/desktop/customers")])
def test_workspace_uses_the_same_section_permissions(ctx, path, reference):
    client = _client(ctx, "clerk_id", role="cashier")
    result = client.get(f"/api/v1/desktop/workspace/{path}", headers=JSON)
    assert (result.status_code == 200) == (client.get(reference, headers=JSON).status_code == 200)


def test_activity_does_not_disclose_payloads_or_other_branches_and_pages_safely(ctx, monkeypatch):
    from extensions import db
    from models.activity_log import ActivityLog
    from models.branch import Branch

    with ctx["app"].app_context():
        g.tenant = TENANT
        second = Branch(code="WS-OTHER", name="فرع آخر", is_active=True)
        db.session.add(second)
        db.session.flush()
        other_id = second.id
        for index in range(23):
            db.session.add(ActivityLog(employee_id=ctx["ids"]["admin_id"], employee_name="Admin",
                branch_id=ctx["ids"]["branch_id"], action="update", category="orders", entity_type="invoice",
                entity_id=str(index + 1), summary="private customer and financial details", payload_json='{"secret":"private"}',
                created_at=datetime(2026, 10, 20, 8)))
        hidden = ActivityLog(employee_id=ctx["ids"]["admin_id"], branch_id=other_id, action="update", category="orders",
                             entity_type="invoice", entity_id="9000", summary="other branch")
        db.session.add(hidden)
        db.session.commit()
        hidden_id = hidden.id

    # Use the real context initializer with independent mode and a selected branch.
    monkeypatch.setattr("utils.branch_context.independent_branches_enabled", lambda: True)
    monkeypatch.setattr("utils.branch_mode.independent_branches_enabled", lambda: True)
    client = _client(ctx)
    with client.session_transaction() as sess:
        sess["branch_id"] = ctx["ids"]["branch_id"]
        sess["view_all_branches"] = False
    first = client.get("/api/v1/desktop/workspace/activity", headers=JSON)
    assert first.status_code == 200, first.get_data(as_text=True)
    body = first.get_json()
    assert len(body["rows"]) == 20 and body["has_more"]
    assert hidden_id not in [row["id"] for row in body["rows"]]
    assert "secret" not in first.get_data(as_text=True)
    assert "private customer" not in first.get_data(as_text=True)
    before = body["rows"][-1]["id"]
    older = client.get(f"/api/v1/desktop/workspace/activity?before={before}", headers=JSON).get_json()
    assert older["rows"] and all(row["id"] < before for row in older["rows"])
    assert not set(row["id"] for row in body["rows"]) & set(row["id"] for row in older["rows"])
    assert client.get("/api/v1/desktop/workspace/activity?before=invalid", headers=JSON).status_code == 400


def test_client_branch_override_does_not_change_workspace_context(ctx):
    client = _client(ctx)
    ordinary = client.get("/api/v1/desktop/workspace/receivables", headers=JSON).get_json()
    attempted = client.get("/api/v1/desktop/workspace/receivables?branch_id=999999&tenant_slug=other", headers=JSON).get_json()
    assert ordinary["value"] == attempted["value"] and ordinary["debtors"] == attempted["debtors"]


def test_sales_summary_stays_aggregated_with_thousands_of_invoices(ctx, record_property):
    from time import perf_counter
    from sqlalchemy import event
    from extensions import db
    from models.invoice import Invoice
    from utils.date_periods import get_period_dates

    client = _client(ctx)
    # Warm the existing schema guards, then compare query counts before/after growing the data.
    client.get("/api/v1/desktop/workspace/sales", headers=JSON)
    with ctx["app"].app_context():
        g.tenant = TENANT
        engine = db.session.get_bind()
    statements = []
    def count_sql(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", count_sql)
    try:
        baseline = client.get("/api/v1/desktop/workspace/sales", headers=JSON)
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)
    baseline_count = len(statements)
    previous = baseline.get_json()["value"]
    with ctx["app"].app_context():
        g.tenant = TENANT
        today, _ = get_period_dates("today")
        stamp = datetime.combine(today, datetime.min.time()).replace(hour=10)
        customer_id = db.session.get(Invoice, ctx["ids"]["order_ids"][0]).customer_id
        db.session.bulk_insert_mappings(Invoice, [{"customer_id": customer_id, "customer_name": "عميل اختبار الأداء", "branch_id": ctx["ids"]["branch_id"], "total": 100,
            "paid_amount": 50, "payment_status": "جزئي", "status": "تم الطلب", "is_stock_locked": False,
            "created_at": stamp} for _ in range(5000)])
        db.session.commit()
    statements.clear()
    event.listen(engine, "before_cursor_execute", count_sql)
    started = perf_counter()
    try:
        response = client.get("/api/v1/desktop/workspace/sales", headers=JSON)
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)
    elapsed = round((perf_counter() - started) * 1000, 1)
    record_property("workspace_seeded_invoices", 5000)
    record_property("workspace_sales_ms", elapsed)
    record_property("workspace_baseline_sql_count", baseline_count)
    record_property("workspace_sql_count", len(statements))
    assert response.status_code == 200
    assert response.get_json()["value"] == previous + 500000
    assert len(response.data) < 500
    # Schema/auth guards have a fixed cost; invoice growth must not create N+1 reads.
    assert len(statements) <= baseline_count + 2
