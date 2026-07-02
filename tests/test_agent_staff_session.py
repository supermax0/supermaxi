"""Regression tests for staff + delivery-agent sessions sharing one browser."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeEmployee:
    id = 99
    role = "cashier"
    is_active = True


class _FakeAgent:
    id = 7
    name = "Agent Seven"


def test_agent_messaging_session_restores_staff_session():
    from utils import agent_employee_link

    original = agent_employee_link.ensure_agent_employee
    agent_employee_link.ensure_agent_employee = lambda agent: _FakeEmployee()
    try:
        sess = {
            "user_id": 1,
            "name": "ammar",
            "role": "admin",
            "tenant_slug": "wasam",
            "tenant_id": 12,
            "plan_key": "pro",
        }

        assert agent_employee_link.bind_agent_messaging_session(sess, _FakeAgent(), "wasam")
        assert sess["user_id"] == _FakeEmployee.id
        assert sess["agent_employee_id"] == _FakeEmployee.id
        assert sess["staff_user_id"] == 1
        assert sess["staff_role"] == "admin"

        agent_employee_link.clear_agent_messaging_session(sess)
        assert sess["user_id"] == 1
        assert sess["name"] == "ammar"
        assert sess["role"] == "admin"
        assert sess["tenant_slug"] == "wasam"
        assert "agent_portal" not in sess
        assert "staff_user_id" not in sess
        print("test_agent_messaging_session_restores_staff_session ok")
    finally:
        agent_employee_link.ensure_agent_employee = original


def test_clear_agent_session_does_not_logout_active_staff_session():
    from utils import agent_employee_link

    sess = {
        "user_id": 1,
        "name": "ammar",
        "role": "admin",
        "tenant_slug": "wasam",
    }

    agent_employee_link.clear_agent_messaging_session(sess)
    assert sess["user_id"] == 1
    assert sess["role"] == "admin"
    print("test_clear_agent_session_does_not_logout_active_staff_session ok")


if __name__ == "__main__":
    test_agent_messaging_session_restores_staff_session()
    test_clear_agent_session_does_not_logout_active_staff_session()
    print("agent staff session tests passed")
