"""Unit tests for merging open AGT reports and parsing multi order ids."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import json

from utils.agent_report_helpers import merge_open_agent_reports


def _report(report_id, number, orders, selections=None, executed=False):
    return SimpleNamespace(
        id=report_id,
        report_number=number,
        is_executed=executed,
        orders_data=json.dumps(orders, ensure_ascii=False),
        order_status_selections=json.dumps(selections or {}, ensure_ascii=False),
        orders_count=len(orders),
        total_amount=sum(int(o.get("remaining") or o.get("total") or 0) for o in orders),
        notes="",
        created_at=None,
    )


def test_merge_open_agent_reports_moves_orders_and_selections():
    target = _report(
        1,
        "AGT-1-20260910-0001",
        [{"id": 10, "remaining": 1000}],
        {"10": "Delivered"},
    )
    source = _report(
        2,
        "AGT-1-20260910-0002",
        [{"id": 20, "remaining": 2500}, {"id": 10, "remaining": 1000}],
        {"20": "Delayed"},
    )
    deleted = []

    fake_session = MagicMock()
    fake_session.delete.side_effect = lambda obj: deleted.append(obj.id)

    with (
        patch("utils.agent_report_helpers.db") as fake_db,
        patch("utils.agent_report_helpers.dismiss_shipping_report_alerts") as dismiss,
        patch("utils.agent_report_helpers.notify_agent_report_ready", return_value=True),
        patch("utils.agent_report_helpers.get_agent_name_for_report", return_value="وسام"),
        patch("utils.agent_report_helpers.sync_open_report_payment_amounts", side_effect=lambda r: setattr(r, "total_amount", 3500) or 3500),
    ):
        fake_db.session = fake_session
        result = merge_open_agent_reports(target, [source])

    orders = json.loads(target.orders_data)
    selections = json.loads(target.order_status_selections)
    assert [o["id"] for o in orders] == [10, 20]
    assert selections["10"] == "Delivered"
    assert selections["20"] == "Delayed"
    assert result["moved_orders"] == 1
    assert result["merged_from"] == ["AGT-1-20260910-0002"]
    assert deleted == [2]
    assert dismiss.call_count >= 2


def test_merge_rejects_different_agents():
    target = _report(1, "AGT-1-20260910-0001", [{"id": 1, "remaining": 1}])
    source = _report(2, "AGT-2-20260910-0001", [{"id": 2, "remaining": 1}])
    try:
        merge_open_agent_reports(target, [source])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "نفس المندوب" in str(exc)


def test_parse_order_ids_payload_accepts_list_and_text():
    from routes.agents import _parse_order_ids_payload

    assert _parse_order_ids_payload({"order_id": "7"}) == [7]
    assert _parse_order_ids_payload({"order_ids": [7, 8, 7]}) == [7, 8]
    assert _parse_order_ids_payload({"order_ids": "7, 8 9"}) == [7, 8, 9]
