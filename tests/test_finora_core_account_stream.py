"""Private owner reviews and reports cannot escape through the realtime stream."""
from tests.test_finora_core_accounts import accounts, env, link, propose, BASE  # noqa: F401
from tests.test_finora_core_api import _auth


def test_owner_configuration_and_support_events_are_private(accounts, monkeypatch):
    from modules.finora_core import api
    link(accounts)
    assert propose(accounts, operation="permissions", employee_id=2, permission_preset="sales", role_ids=[1]).status_code == 201
    assert propose(accounts, operation="feature", feature="unknown-feature", enabled=True).status_code == 400
    assert propose(accounts, operation="profile", profile="car_parts").status_code == 400
    monkeypatch.setattr(api, "STREAM_LIFETIME_SECONDS", 0.3)
    client, owner = accounts[1], accounts[2]
    viewer, _ = _auth(client, "viewer")
    restricted = client.get(f"{BASE}/events/stream", headers={**viewer, "Last-Event-ID": "0"}).get_data(as_text=True)
    assert "event: support.issue" not in restricted
    assert "event: approval.required" not in restricted
    assert "permissionDiff" not in restricted
    assert "missing_template" not in restricted
    visible = client.get(f"{BASE}/events/stream", headers={**owner, "Last-Event-ID": "0"}).get_data(as_text=True)
    assert "event: support.issue" in visible
    assert "event: approval.required" in visible
    assert "permissionDiff" in visible
    assert "missing_template" in visible
