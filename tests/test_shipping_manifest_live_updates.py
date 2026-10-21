"""Order edits refresh draft amounts/ownership without rewriting approved settlement history."""
import json

import pytest
from tests.test_shipping_center_phase2 import ctx  # noqa: F401
from tests.test_shipping_center_api import API, app, _client, _json  # noqa: F401


def _change(ctx, order_id, **values):
    from flask import g
    from extensions import db
    from models.invoice import Invoice
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        order = db.session.get(Invoice, order_id)
        for field, value in values.items():
            setattr(order, field, value)
        db.session.commit()
        db.session.remove()


def test_draft_prices_and_summary_follow_live_order_edits(ctx):
    client = _client(ctx)
    manifest = _json(client.post(f"{API}/manifests", json={"agent_id": ctx["agent"], "from_portal": True}))["manifest"]
    _change(ctx, ctx["f1"], total=125000)
    updated = _json(client.get(f"{API}/manifests/{manifest['id']}"))["manifest"]
    assert next(row for row in updated["rows"] if row["id"] == ctx["f1"])["remaining"] == 125000
    assert updated["expected_net"] == 185000
    assert updated["selections"] == manifest["selections"]
    assert updated["total_amount"] == sum(row["remaining"] for row in updated["rows"])


@pytest.mark.parametrize("remove", [False, True])
def test_reassignment_removes_orders_from_old_agent_drafts_and_portal_only(ctx, remove):
    from flask import g
    from extensions import db
    from models.delivery_agent import DeliveryAgent
    from models.shipping_report import ShippingReport
    client = _client(ctx)
    manifest = _json(client.post(f"{API}/manifests", json={"agent_id": ctx["agent"], "from_portal": True}))["manifest"]
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        other = DeliveryAgent(name="مندوب آخر", phone="07809999", is_active=True, branch_id=ctx["branch"])
        db.session.add(other)
        db.session.commit()
        target_id = None if remove else other.id
        db.session.remove()
    result = client.post("/orders/update-delivery-agent", json={"order_id": ctx["f1"], "agent_id": target_id})
    assert result.status_code == 200, result.get_json()
    updated = _json(client.get(f"{API}/manifests/{manifest['id']}"))["manifest"]
    assert ctx["f1"] not in {row["id"] for row in updated["rows"]}
    assert str(ctx["f1"]) not in updated["selections"]
    assert str(ctx["f1"]) not in updated["meta"]["agent_claim"]
    portal = _json(client.get(f"{API}/agents/{ctx['agent']}/portal"))
    assert portal["count"] == 2
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        for report in ShippingReport.query.filter_by(is_executed=False).all():
            assert ctx["f1"] not in {row["id"] for row in json.loads(report.orders_data)}
        db.session.remove()


def test_approved_snapshots_survive_price_and_agent_changes(ctx):
    client = _client(ctx)
    manifest = _json(client.post(f"{API}/manifests", json={"agent_id": ctx["agent"], "from_portal": True}))["manifest"]
    approved = _json(client.post(f"{API}/manifests/{manifest['id']}/approve", json={"received_amount": 140000}))["manifest"]
    _change(ctx, ctx["f1"], total=999000, delivery_agent_id=None)
    again = _json(client.get(f"{API}/manifests/{manifest['id']}"))["manifest"]
    assert again == approved
    assert sum(row["allocated"] for row in again["rows"]) == 140000


def test_reassignment_rollback_keeps_order_and_draft_membership_together(ctx):
    from flask import g
    from extensions import db
    from models.invoice import Invoice
    from models.shipping_report import ShippingReport
    client = _client(ctx)
    manifest = _json(client.post(f"{API}/manifests", json={"agent_id": ctx["agent"], "from_portal": True}))["manifest"]
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        order = db.session.get(Invoice, ctx["f1"])
        order.delivery_agent_id = None
        db.session.flush()
        db.session.rollback()
        assert db.session.get(Invoice, ctx["f1"]).delivery_agent_id == ctx["agent"]
        assert ctx["f1"] in {row["id"] for row in json.loads(db.session.get(ShippingReport, manifest["id"]).orders_data)}
        db.session.remove()


def test_switching_between_duplicate_agent_records_keeps_the_same_persons_draft(ctx):
    from flask import g
    from extensions import db
    from models.delivery_agent import DeliveryAgent
    client = _client(ctx)
    manifest = _json(client.post(f"{API}/manifests", json={"agent_id": ctx["agent"], "from_portal": True}))["manifest"]
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        agent = db.session.get(DeliveryAgent, ctx["agent"])
        duplicate = DeliveryAgent(name=agent.name, phone=agent.phone, branch_id=ctx["branch"], is_active=True)
        db.session.add(duplicate)
        db.session.commit()
        duplicate_id = duplicate.id
        db.session.remove()
    _change(ctx, ctx["f1"], delivery_agent_id=duplicate_id)
    updated = _json(client.get(f"{API}/manifests/{manifest['id']}"))["manifest"]
    assert {row["id"] for row in updated["rows"]} == {ctx["f1"], ctx["f2"], ctx["f3"]}


def test_existing_stale_drafts_are_reconciled_on_read_without_writing(ctx):
    from flask import g
    from extensions import db
    from models.invoice import Invoice
    from models.shipping_report import ShippingReport
    client = _client(ctx)
    manifest = _json(client.post(f"{API}/manifests", json={"agent_id": ctx["agent"], "from_portal": True}))["manifest"]
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        # Simulate a reassignment made before the synchronization hook existed.
        Invoice.query.filter_by(id=ctx["f1"]).update({"delivery_agent_id": None}, synchronize_session=False)
        db.session.commit()
        before = db.session.get(ShippingReport, manifest["id"]).orders_data
        db.session.remove()
    current = _json(client.get(f"{API}/manifests/{manifest['id']}"))["manifest"]
    assert {row["id"] for row in current["rows"]} == {ctx["f2"], ctx["f3"]}
    assert current["orders_count"] == 2 and str(ctx["f1"]) not in current["selections"]
    with ctx["app"].app_context():
        g.tenant = ctx["tenant"]
        assert db.session.get(ShippingReport, manifest["id"]).orders_data == before
        db.session.remove()
