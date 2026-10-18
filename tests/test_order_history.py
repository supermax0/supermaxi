from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from routes.orders import _order_history_events


class FakeLog:
    def __init__(self, log_id, action, payload, created_at, employee_name="موظف الاختبار"):
        self.id = log_id
        self.action = action
        self.summary = f"حركة {action}"
        self.created_at = created_at
        self.employee_name = employee_name
        self._payload = payload

    def get_payload(self):
        return self._payload


def test_order_history_expands_changes_and_counts_repeated_dispatches():
    started = datetime(2026, 7, 26, 8, 0)
    order = SimpleNamespace(
        id=591,
        created_at=started,
        employee_name="أحمد",
    )
    logs = [
        FakeLog(1, "view", {}, started + timedelta(minutes=1), "سارة"),
        FakeLog(2, "print", {}, started + timedelta(minutes=2), "سارة"),
        FakeLog(
            3,
            "update",
            {
                "before": {
                    "status": "تم الطلب",
                    "delivery_agent_id": None,
                    "shipping_company_id": None,
                },
                "after": {
                    "status": "جاري الشحن",
                    "delivery_agent_id": 7,
                    "shipping_company_id": 3,
                },
            },
            started + timedelta(minutes=3),
        ),
        FakeLog(
            4,
            "update",
            {
                "before": {"delivery_agent_id": 7},
                "after": {"delivery_agent_id": 8},
            },
            started + timedelta(minutes=4),
        ),
    ]

    with patch(
        "routes.orders._order_history_name_maps",
        return_value=({3: "شركة النقل"}, {7: "علي", 8: "حسن"}),
    ):
        events, stats = _order_history_events(order, logs)

    assert stats == {
        "views": 1,
        "prints": 1,
        "agent_dispatches": 2,
        "shipping_dispatches": 1,
    }
    movements = [event["movement"] for event in events]
    assert "إنشاء الطلب" in movements
    assert "مشاهدة تفاصيل الطلب" in movements
    assert "طباعة الفاتورة" in movements
    assert "تغيير حالة الطلب" in movements
    assert movements.count("إرسال الطلب إلى المندوب") == 2
    assert "إرسال الطلب إلى شركة النقل" in movements
    assert events[0]["details"] == "من علي إلى حسن"
