"""Project-map integrity, analysis recovery and conversation-scoped MCP authorization."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
import jsonschema

from tests.finora_core_support import env, _api, _auth  # noqa: F401
from tests.test_finora_core_brain import brain, core, FakeProvider  # noqa: F401
from tests.test_finora_core_telegram import telegram, say  # noqa: F401
from tests.test_finora_core_projects import REQUEST, brief, profile
from modules.finora_core.project_graph import analyze_graph, build_graph


def graph_fixture():
    return build_graph({"revision": 3, "brief": brief()})


def analysis(graph):
    return {"relations": [{"source": n["id"], "target": "entity:" + next(x["id"].split(":", 1)[1] for x in graph["nodes"] if x["kind"] == "entity"),
                            "relation": "uses_data", "reason": "تستخدم بيانات الموعد لعرض الحجز"}
                           for n in graph["nodes"] if n["kind"] == "feature"], "unresolvedFeatures": []}


def seed(state):
    state["state"]["provider"] = FakeProvider(brief())
    say(state, REQUEST)
    result = _api(state, "get", "/conversations/1/project/graph", headers=state["auth"])
    assert result.status_code == 200, result.get_json()
    return result.get_json()


def mint(state):
    result = _api(state, "post", "/conversations/1/project/mcp-connection", headers=state["auth"], json={})
    assert result.status_code == 200, result.get_json()
    return result.get_json()


def rpc(state, token, method, params=None, cid=1, **extra):
    return _api(state, "post", f"/conversations/{cid}/project/mcp", headers={"Authorization": "Bearer " + token, **extra},
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_compiler_preserves_conditional_branches_and_unique_nodes():
    draft = {"revision": 3, "brief": brief()}
    original = copy.deepcopy(draft)
    draft["brief"]["workflows"][0]["steps"][0]["next"].append({"stepId": "confirm", "condition": "اختار من المفضلة"})
    draft["brief"]["entities"].append({"name": "حجز", "fields": ["مرجع"], "relatedTo": ["ملعب"]})
    graph = build_graph(draft)
    ids = {n["id"] for n in graph["nodes"]}
    assert len(ids) == len(graph["nodes"])
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    transitions = [e for e in graph["edges"] if e["source"] == "step:reserve:search" and e["relation"] == "transition"]
    assert len(transitions) == 2
    assert any("مرجع" in n["details"].get("fields", []) for n in graph["nodes"])
    assert all("estimate" not in n["details"] for n in graph["nodes"])
    assert not graph["executable"]
    assert draft["revision"] == original["revision"]


def test_analysis_recovers_coverage_and_marks_proposals_separately():
    graph = graph_fixture()
    good = analysis(graph)
    model = FakeProvider({"relations": [], "unresolvedFeatures": []}, good)
    annotation = analyze_graph(model, graph)
    assert len(model.calls) == 2
    enriched = build_graph({"revision": 3, "brief": brief()}, annotation)
    assert enriched["enriched"]
    assert any(e["basis"] == "proposed" for e in enriched["edges"])
    assert not build_graph({"revision": 4, "brief": brief()}, annotation)["enriched"]


@pytest.mark.parametrize("fault", ["foreign", "own_page", "secret", "uncovered"])
def test_analysis_rejects_unsafe_or_incomplete_links(fault):
    graph = graph_fixture()
    output = analysis(graph)
    if fault == "foreign":
        output["relations"][0]["target"] = "page:another_customer"
    elif fault == "own_page":
        output["relations"][0]["target"] = "page:venues"
    elif fault == "secret":
        output["relations"][0]["reason"] = "sk-proj-" + "testonly" * 4
    else:
        output["relations"].pop()
    model = FakeProvider(output)
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        analyze_graph(model, graph)
    assert len(model.calls) == 2


def test_graph_analysis_keeps_financial_state_and_rejects_stale_write(telegram, monkeypatch):
    from modules.finora_core import project_graph_api
    graph = seed(telegram)
    before = profile(telegram)["project"]
    monkeypatch.setattr(project_graph_api, "get_provider", lambda: FakeProvider(analysis(graph)))
    result = _api(telegram, "post", "/conversations/1/project/graph/analyze", headers=telegram["auth"], json={"planHash": graph["planHash"]})
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["enriched"]
    assert profile(telegram)["project"] == before
    assert _api(telegram, "post", "/conversations/1/project/graph/analyze", headers=telegram["auth"], json={"planHash": "stale"}).status_code == 409
    monkeypatch.setattr(project_graph_api, "get_provider", lambda: FakeProvider({"relations": [], "unresolvedFeatures": []}))
    failed = _api(telegram, "post", "/conversations/1/project/graph/analyze", headers=telegram["auth"], json={"planHash": graph["planHash"]})
    assert failed.status_code == 422
    assert _api(telegram, "get", "/conversations/1/project/graph", headers=telegram["auth"]).get_json()["enriched"]


def test_mcp_protocol_scope_rotation_and_revocation(telegram):
    from modules.finora_core.models import FcSetting
    graph = seed(telegram)
    assert _api(telegram, "get", "/conversations/1/project/graph").status_code == 401
    first = mint(telegram)
    token = first["token"]
    stored = core(telegram, lambda s: [(r.key, r.value) for r in s.query(FcSetting).filter(FcSetting.key.startswith("project_mcp:")).all()])
    assert token not in json.dumps(stored)
    assert all(len(key) <= FcSetting.key.type.length for key, _ in stored)
    assert first["readOnly"]
    initialized = rpc(telegram, token, "initialize", {"protocolVersion": "2025-11-25"})
    assert initialized.get_json()["result"]["protocolVersion"] == "2025-11-25"
    assert rpc(telegram, token, "initialize", {"protocolVersion": []}).get_json()["error"]["code"] == -32602
    assert rpc(telegram, token, "tools/call", {"name": {}}).get_json()["error"]["code"] == -32602
    headers = {"Authorization": "Bearer " + token}
    assert _api(telegram, "post", "/conversations/1/project/mcp", headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert _api(telegram, "get", "/conversations/1/project/mcp", headers=headers).status_code == 405
    listing = rpc(telegram, token, "tools/list").get_json()["result"]["tools"]
    assert len(listing) == 3 and all(t["annotations"]["readOnlyHint"] for t in listing)
    output = rpc(telegram, token, "tools/call", {"name": "get_project_graph"}).get_json()["result"]["structuredContent"]
    assert output == graph
    node = rpc(telegram, token, "tools/call", {"name": "get_project_node", "arguments": {"nodeId": "page:booking"}}).get_json()["result"]["structuredContent"]
    assert node["node"]["title"] == "الحجز" and node["connections"]
    plan = rpc(telegram, token, "tools/call", {"name": "get_project_plan"}).get_json()["result"]["structuredContent"]
    assert "estimate" not in plan["project"] and not plan["automaticExecutionEnabled"]
    assert "error" in rpc(telegram, token, "tools/call", {"name": "get_project_plan", "arguments": {"conversationId": 2}}).get_json()
    assert "error" in rpc(telegram, token, "tools/call", {"name": "create_account"}).get_json()
    assert rpc(telegram, token, "ping", cid=2).status_code == 403
    assert rpc(telegram, token, "ping", Origin="https://evil.example").status_code == 403
    assert rpc(telegram, token, "ping", **{"MCP-Protocol-Version": "unsupported"}).status_code == 400
    second = mint(telegram)
    assert rpc(telegram, token, "ping").status_code == 401
    assert rpc(telegram, second["token"], "ping").status_code == 200
    revoked = _api(telegram, "post", "/conversations/1/project/mcp-connection/revoke", headers=telegram["auth"], json={})
    assert revoked.status_code == 200
    assert rpc(telegram, second["token"], "ping").status_code == 401


def test_mcp_expiry_owner_permissions_and_relinked_customer(telegram):
    from modules.finora_core.models import FcSetting, FcOperatorRole
    seed(telegram)
    token = mint(telegram)["token"]
    def expire(s):
        row = s.query(FcSetting).filter(FcSetting.key.startswith("project_mcp:")).one()
        value = json.loads(row.value)
        value["expiresAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        row.value = json.dumps(value)
        s.commit()
    core(telegram, expire)
    assert rpc(telegram, token, "ping").status_code == 401
    token = mint(telegram)["token"]
    def restrict(s):
        s.add(FcOperatorRole(superadmin_id=1, role="read_only")); s.commit()
    core(telegram, restrict)
    assert rpc(telegram, token, "ping").status_code == 403
    restricted = _auth(telegram)
    assert _api(telegram, "post", "/conversations/1/project/mcp-connection", headers=restricted, json={}).status_code == 403


def test_inflight_analysis_cannot_overwrite_new_plan(telegram, monkeypatch):
    from modules.finora_core import project_graph_api
    from modules.finora_core.models import FcSetting
    graph = seed(telegram)
    def change_plan():
        def update(s):
            row = s.query(FcSetting).filter(FcSetting.key.startswith("project:")).one()
            draft = json.loads(row.value)
            draft["revision"] += 1
            row.value = json.dumps(draft, ensure_ascii=False)
            s.commit()
        core(telegram, update)
    monkeypatch.setattr(project_graph_api, "get_provider", lambda: FakeProvider(analysis(graph), on_call=change_plan))
    result = _api(telegram, "post", "/conversations/1/project/graph/analyze", headers=telegram["auth"], json={"planHash": graph["planHash"]})
    assert result.status_code == 409
    assert not _api(telegram, "get", "/conversations/1/project/graph", headers=telegram["auth"]).get_json()["enriched"]

