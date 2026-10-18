"""AI Tutor system analyzer: static/runtime discovery, coverage, validation, snapshots, diff, CI policy, chat integration."""
import copy
import json

import pytest
from flask import Flask

from modules.ai_tutor import registry
from modules.ai_tutor.analyzer import catalog as catalog_mod
from modules.ai_tutor.analyzer import cli, snapshot as snapshots, static_scan
from modules.ai_tutor.chat import knowledge as kb_mod
from modules.ai_tutor.chat import service
from tests.test_ai_tutor_backend import BASE, _enable, _user, tutor_app  # noqa: F401  (fixtures)
from tests.test_ai_tutor_chat import ctx


@pytest.fixture(autouse=True)
def isolated_map(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_TUTOR_SYSTEM_MAP_DIR", str(tmp_path / "map"))
    snapshots.reset_cache()
    kb_mod.load.cache_clear()
    yield
    snapshots.reset_cache()
    kb_mod.load.cache_clear()


@pytest.fixture(scope="module")
def static():
    return static_scan.scan_sources()


def by_id(snapshot, kind, ident):
    return next(i for i in snapshot["items"] if i["kind"] == kind and i["id"] == ident)


def runtime_payload(extra=None, drop=(), extra_page=None):
    elements = [
        {"kind": "page", "id": "staff", "visible": True, "in_modal": False, "label": None},
        {"kind": "action", "id": "doctor.create", "visible": True, "in_modal": False, "label": "إضافة طبيب وحساب"},
        {"kind": "action", "id": "employee.create", "visible": True, "in_modal": False, "label": "إضافة موظف"},
        {"kind": "field", "id": "doctor.name", "visible": True, "in_modal": True, "label": "الاسم الكامل"},
        {"kind": "section", "id": "staff.form", "visible": True, "in_modal": True, "label": None},
    ]
    elements = [e for e in elements if e["id"] not in drop] + ([] if extra_page else list(extra or []))
    pages = [{"id": "staff", "route": "/clinics/staff", "accessible": True, "status": 200, "elements": elements}]
    if extra_page:  # a second crawled page that owns the extra elements
        pages.append({"id": extra_page, "route": f"/clinics/{extra_page}", "accessible": True, "status": 200, "elements": list(extra or [])})
    return {"schema": 1, "generated_at": "2026-10-02T10:00:00Z", "pages": pages,
            "safety": {"clicked": ["doctor.create"], "skipped": [{"id": "doctor.save", "class": "irreversible"}], "writes_observed": 0}}


# ------------------------------------------------------------------ static scan

def test_static_scan_discovers_attributes_and_expands_placeholders(static):
    ids = {(i["kind"], i["id"]) for i in static["items"]}
    assert {("action", "doctor.create"), ("action", "doctor.save"), ("action", "employee.save"), ("action", "specialty.create"),
            ("section", "staff.form"), ("field", "doctor.name"), ("field", "employee.name"), ("field", "staff.name"),
            ("action", "nav.doctors"), ("action", "modal.save")} <= ids
    assert static["unresolved"] == []  # every template placeholder is resolvable
    assert {("action", "specialty.save"), ("action", "specialty.save.edit")} <= ids  # finoraAction options are discovered too


def test_labels_pages_categories_and_pages_catalog(static):
    items = {(i["kind"], i["id"]): i for i in static["items"]}
    assert "إضافة طبيب" in items[("action", "doctor.create")]["labels"][0]
    assert items[("action", "nav.doctors")]["labels"] == ["الأطباء والموظفون"]
    assert items[("action", "doctor.create")]["page"] == "staff" and items[("action", "specialty.create")]["page"] == "specialties"
    assert static_scan.category_of("action", "doctor.create") == "feature"
    assert static_scan.category_of("action", "nav.patients") == "navigation"
    assert static_scan.category_of("action", "modal.save") == "chrome" and static_scan.category_of("action", "doctor.save") == "submit"
    from modules.clinics.routes import PAGE_CONFIG

    assert set(static["pages"]) == set(PAGE_CONFIG)  # extracted from the project, not hard-coded
    assert static["page_route_present"] is True


def test_backend_endpoints_and_permissions_are_extracted(static):
    staff_post = [e for e in static["endpoints"] if e["rule"] == "/clinics/api/staff" and "POST" in e["methods"]]
    assert staff_post and staff_post[0]["permission"] == "clinics_admin"
    assert static["permissions"] and "clinics_admin" in static["permissions"]
    assert static_scan.rule_matches("/clinics/api/staff", "POST", "^/clinics/api/staff$")
    assert static_scan.rule_matches("/clinics/api/staff/<int:employee_id>", "PATCH", r"^/clinics/api/staff/\d+$")
    assert not static_scan.rule_matches("/clinics/api/staff", "POST", "^/clinics/api/nope$")


def test_require_clinics_exposes_its_permission():
    from modules.clinics.guards import require_clinics

    @require_clinics("clinics_admin")
    def view():
        return "ok"

    assert view.clinics_permission == "clinics_admin"


# ---------------------------------------------------------------------- catalog

def test_catalog_statuses_for_the_real_system():
    snap = snapshots.build_snapshot()
    assert by_id(snap, "action", "doctor.create")["status"] == "verified"
    assert by_id(snap, "action", "specialty.create")["status"] == "verified"
    employee = by_id(snap, "action", "employee.create")
    assert employee["status"] == "verified" and employee["knowledge_registered"] and employee["tutorial_registered"]
    assert by_id(snap, "action", "nav.doctors")["verified"] is True  # used by a verified lesson
    assert by_id(snap, "action", "specialty.save.edit")["status"] == "discovered"  # plumbing no lesson uses: no lesson expected
    assert by_id(snap, "action", "employee.save")["status"] == "verified"  # plumbing a verified lesson walks through
    assert [i["id"] for i in snap["items"] if i["status"] in ("stale", "broken")] == []
    statuses = {t["id"]: t["status"] for t in snap["tutorials"]}
    assert statuses["doctor.create"] == "verified" and statuses["specialty.create"] == "verified"
    assert "broken" not in statuses.values()


def test_permission_mapping_is_reported():
    snap = snapshots.build_snapshot()
    create = by_id(snap, "action", "doctor.create")
    assert create["permission"] == "clinics_admin" and create["permission_mapped"] is True
    assert by_id(snap, "action", "nav.menu.open")["permission_mapped"] is None  # global plumbing


def test_coverage_is_reported_as_separate_honest_numbers():
    snap = snapshots.build_snapshot()
    c = snap["coverage"]
    assert set(c["actions"]) == {"all", "feature", "navigation", "chrome", "submit"}
    assert c["actions"]["all"]["discovered"] == sum(c["actions"][k]["discovered"] for k in ("feature", "navigation", "chrome", "submit"))
    feature = c["actions"]["feature"]
    assert feature["knowledge"] == feature["discovered"] and feature["verified"] >= 2 and feature["tutorial"] >= feature["verified"]
    assert feature["tutorial_pct"] == round(100 * feature["tutorial"] / feature["discovered"], 1)
    assert c["discovery"]["pages_total"] == len(static_scan.page_config()) and c["discovery"]["pages_instrumented"] >= 2
    assert c["discovery"]["runtime_available"] is False and c["discovery"]["runtime_confirmed_pct"] is None
    assert c["tutorials"]["broken"] == 0 and c["tutorials"]["verified"] >= 2
    assert c["tutorials"]["total"] == c["tutorials"]["verified"] + c["tutorials"]["unverified"]
    meta = snap["meta"]
    assert meta["actions_count"] == c["counts"]["actions"] and meta["pages_count"] == 31 and meta["fields_count"] == c["counts"]["fields"]


def test_dependency_doctor_to_specialty_is_in_the_map():
    snap = snapshots.build_snapshot()
    dep = next(d for d in snap["dependencies"] if d["from"] == "doctor.create")
    assert dep["to"] == "specialty.create" and dep["to_exists"] and dep["to_runnable"] and dep["fact"]["name"] == "specialties_count"


def test_stale_knowledge_is_flagged_not_deleted(monkeypatch):
    real = kb_mod.ui_references
    monkeypatch.setattr(kb_mod, "ui_references", lambda include_discovered=True: real(include_discovered) + [{"action": "ghost.action"}])
    snap = snapshots.build_snapshot()
    ghost = by_id(snap, "action", "ghost.action")
    assert ghost["status"] == "stale" and ghost["discovered"] is False and ghost["knowledge_registered"]
    assert any(w["code"] == "stale_knowledge" for w in snap["warnings"])
    assert registry.get("doctor.create") is not None  # nothing was modified


# ------------------------------------------------------------ tutorial validation

def test_simulated_missing_target_breaks_the_tutorial_and_fails_ci():
    snap = snapshots.build_snapshot(simulate_missing={"doctor.create"})
    tutorial = next(t for t in snap["tutorials"] if t["id"] == "doctor.create")
    assert tutorial["status"] == "broken" and tutorial["declared_status"] == "verified"
    assert any(p["code"] == "target_missing" and "doctor.create" in p["message"] for p in tutorial["problems"])
    assert by_id(snap, "action", "doctor.create")["status"] == "broken" or not by_id(snap, "action", "doctor.create")["discovered"]
    assert any("verified tutorial «doctor.create» is broken" in f for f in cli.failures(snap))
    assert next(t for t in snap["tutorials"] if t["id"] == "specialty.create")["status"] == "verified"  # others unaffected


def without_lesson(monkeypatch, lesson_id):
    """The registry as it would be if `lesson_id` had never been written (its feature stays in the knowledge registry)."""
    real_all, real_load = registry.load_all, kb_mod._load
    monkeypatch.setattr(registry, "load_all", lambda: {k: v for k, v in real_all().items() if k != lesson_id})

    def fake_load(name):
        data = real_load(name)
        for feature in data.get("features", []):
            if feature.get("tutorial") == lesson_id:
                feature["tutorial"] = None
        return data

    monkeypatch.setattr(kb_mod, "_load", fake_load)
    kb_mod.load.cache_clear()
    snapshots.reset_cache()


def test_missing_tutorials_never_fail_the_build(monkeypatch, capsys):
    without_lesson(monkeypatch, "service.create")
    snap = snapshots.build_snapshot()
    item = by_id(snap, "action", "service.create")
    assert item["status"] == "tutorial_missing" and item["knowledge_registered"] and not item["tutorial_registered"]
    assert any(w["code"] == "tutorial_missing" and "service.create" in w["message"] for w in snap["warnings"])
    assert cli.failures(snap) == []
    assert cli.main([]) == 0
    assert "service.create" in capsys.readouterr().out


def test_cli_exit_codes(monkeypatch, capsys):
    broken = snapshots.build_snapshot(simulate_missing={"doctor.create"})
    monkeypatch.setattr(snapshots, "build_snapshot", lambda runtime=None, simulate_missing=frozenset(): broken)
    assert cli.main([]) == 1
    assert "FAIL: verified tutorial «doctor.create» is broken" in capsys.readouterr().err
    assert cli.main(["--runtime", "does-not-exist.json"]) == 2


def mutated(monkeypatch, mutate):
    definitions = copy.deepcopy(registry.load_all())
    mutate(definitions["doctor.create"])
    monkeypatch.setattr(registry, "load_all", lambda: definitions)
    return snapshots.build_snapshot()


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["steps"][2].update(page="ghost-page"), "page_unknown"),
    (lambda d: d["steps"][1].update(route="/clinics/ghost"), "route_unknown"),
    (lambda d: next(s for s in d["steps"] if s["id"] == "save")["match"].update(url="^/clinics/api/ghost$"), "api_unmatched"),
    (lambda d: next(s for s in d["steps"] if s["id"] == "verify").update(validator="ghost.validator"), "validator_unknown"),
    (lambda d: d["requires_permissions"].append("ghost_permission"), "permission_unknown"),
    (lambda d: d["steps"][5].update(target={"field": "doctor.ghost"}), "target_missing"),
])
def test_tutorial_problems_are_detected(monkeypatch, mutate, code):
    snap = mutated(monkeypatch, mutate)
    tutorial = next(t for t in snap["tutorials"] if t["id"] == "doctor.create")
    assert code in {p["code"] for p in tutorial["problems"]}, tutorial["problems"]
    assert tutorial["status"] == "broken"


def test_missing_dependency_tutorial_breaks_the_parent(monkeypatch):
    kb_mod.load()  # the knowledge registry is already built (a missing lesson would otherwise fail its own load-time integrity check)
    definitions = copy.deepcopy(registry.load_all())
    del definitions["specialty.create"]
    monkeypatch.setattr(registry, "load_all", lambda: definitions)
    snap = snapshots.build_snapshot()
    assert "dependency_missing" in {p["code"] for p in next(t for t in snap["tutorials"] if t["id"] == "doctor.create")["problems"]}


def test_a_broken_draft_does_not_fail_the_build(monkeypatch):
    snap = mutated(monkeypatch, lambda d: (d.update(status="draft"), d["steps"][2].update(page="ghost-page")))
    tutorial = next(t for t in snap["tutorials"] if t["id"] == "doctor.create")
    assert tutorial["status"] == "broken" and tutorial["declared_status"] == "draft"
    assert cli.failures(snap) == []  # only a broken VERIFIED tutorial fails


# ----------------------------------------------------------------------- runtime

def test_runtime_scan_is_merged_into_the_catalog():
    cleaned = catalog_mod.validate_runtime(runtime_payload())
    snap = snapshots.build_snapshot(cleaned)
    create = by_id(snap, "action", "doctor.create")
    assert create["discovered_runtime"] and create["discovered_static"] and create["runtime_visible"]
    assert by_id(snap, "field", "doctor.name")["runtime_in_modal"] is True
    assert snap["meta"]["runtime"] is True and snap["coverage"]["discovery"]["runtime_available"] is True
    assert snap["coverage"]["discovery"]["actions_confirmed_runtime"] >= 2
    page = next(p for p in snap["pages"] if p["id"] == "staff")
    assert page["runtime_seen"] is True and page["runtime_accessible"] is True
    # Tutorial targets that were not reached at runtime are only warnings (modal fields need an opener).
    assert next(t for t in snap["tutorials"] if t["id"] == "doctor.create")["status"] == "verified"


def test_runtime_discovers_elements_the_source_scan_cannot_see():
    extra = [{"kind": "action", "id": "appointment.reschedule", "visible": True, "in_modal": False, "label": "تأجيل موعد"}]
    snap = snapshots.build_snapshot(catalog_mod.validate_runtime(runtime_payload(extra)))
    item = by_id(snap, "action", "appointment.reschedule")
    assert item["discovered_runtime"] and not item["discovered_static"] and item["status"] == "knowledge_missing"
    assert item["label_ar"] == "تأجيل موعد"


@pytest.mark.parametrize("bad", [
    None, {"schema": 2, "pages": []}, {"schema": 1, "pages": "x"},
    {"schema": 1, "pages": [{"id": "BAD ID", "elements": []}]},
    {"schema": 1, "pages": [{"id": "staff", "elements": [{"kind": "script", "id": "x"}]}]},
    {"schema": 1, "pages": [{"id": "staff", "elements": [{"kind": "action", "id": "<img onerror=1>"}]}]},
    {"schema": 1, "pages": [{"id": "p", "elements": [{"kind": "field", "id": "a"}] * (catalog_mod.MAX_RUNTIME_ELEMENTS + 1)}]},
])
def test_runtime_upload_is_validated(bad):
    with pytest.raises(ValueError):
        catalog_mod.validate_runtime(bad)


def test_a_runtime_scan_that_wrote_data_is_untrustworthy():
    payload = runtime_payload()
    payload["safety"]["writes_observed"] = 2
    snap = snapshots.build_snapshot(catalog_mod.validate_runtime(payload))
    assert any(w["code"] == "runtime_wrote_data" for w in snap["warnings"])
    assert any("write requests" in f for f in cli.failures(snap))


def test_crawler_never_clicks_dangerous_actions():
    # Mirrors scripts/ai_tutor_runtime_scan.mjs (tested end-to-end in the browser spec).
    text = open(static_scan.ROOT / "scripts" / "ai_tutor_runtime_scan.mjs", encoding="utf-8").read()
    opener_line = next(line for line in text.splitlines() if line.startswith("export const SAFE_OPENERS"))
    assert all(f'"{opener}"' in opener_line for opener in ("appointment.create", "doctor.create", "employee.create", "patient.create", "specialty.create"))
    # only form OPENERS (they open a modal that is cancelled): nothing that saves, pays, deletes or changes state
    assert not any(word in opener_line for word in ("save", "invoice", "checkin", "queue", "visit", "delete", "refund"))
    for word in ("delete", "refund", "financial", "irreversible", "save", "approve"):
        assert word in text


# --------------------------------------------------------------- snapshot + diff

def test_snapshot_metadata_and_staleness():
    snap = snapshots.build_snapshot()
    meta = snap["meta"]
    assert {"app_version", "git_commit", "created_at", "pages_count", "actions_count", "fields_count", "fingerprint", "runtime"} <= set(meta)
    assert snapshots.is_stale(snap) is False and snapshots.is_stale(None) is True
    old = copy.deepcopy(snap)
    old["meta"]["fingerprint"] = "0000"
    assert snapshots.is_stale(old) is True


def test_first_scan_then_diff_reports_added_removed_and_changed():
    first = snapshots.run_scan()
    assert first["diff"]["first_scan"] is True and not any(i["new"] for i in first["items"])
    snapshots.save_runtime(runtime_payload([{"kind": "action", "id": "appointment.reschedule", "visible": True, "in_modal": False, "label": "تأجيل موعد"}]))
    second = snapshots.run_scan()
    assert [a["id"] for a in second["diff"]["added"]] == ["appointment.reschedule"]
    assert by_id(second, "action", "appointment.reschedule")["new"] is True
    snapshots.save_runtime(runtime_payload())
    third = snapshots.run_scan()
    assert [r["id"] for r in third["diff"]["removed"]] == ["appointment.reschedule"] and third["diff"]["added"] == []
    assert any(h.name.endswith(".json") for h in (snapshots.storage_dir() / "history").iterdir())


def test_diff_detects_changed_target_page_and_new_broken_tutorial():
    previous = snapshots.build_snapshot()
    current = copy.deepcopy(previous)
    item = by_id(current, "action", "doctor.create")
    item["page"] = "settings"
    item["files"] = ["static/clinics/other.js"]
    next(t for t in current["tutorials"] if t["id"] == "doctor.create")["status"] = "broken"
    result = snapshots.diff(previous, current)
    changed = next(c for c in result["changed"] if c["id"] == "doctor.create")
    assert set(changed["change"]) == {"page", "files"}
    assert result["broken_tutorials"] == ["doctor.create"]
    assert {p["page"] for p in result["pages_changed"]} >= {"staff", "settings"}
    assert snapshots.diff(current, previous)["fixed_tutorials"] == ["doctor.create"]


def test_simulated_scans_are_never_saved():
    snapshots.run_scan()
    saved = snapshots.load_latest()["meta"]["created_at"]
    sim = snapshots.run_scan(simulate_missing=frozenset({"doctor.create"}), persist=True)
    assert sim["meta"]["simulated"] == ["doctor.create"]
    assert snapshots.load_latest()["meta"]["created_at"] == saved
    assert all(t["status"] != "broken" for t in snapshots.load_latest()["tutorials"])


# ----------------------------------------- the analyzer protects users + feeds the chat

def test_broken_tutorial_is_withheld_but_only_while_the_snapshot_is_fresh():
    definition = registry.get("doctor.create")
    assert registry.is_runnable(definition) is True
    broken = snapshots.build_snapshot(simulate_missing={"doctor.create"})
    snapshots._write("latest.json", broken)
    snapshots.reset_cache()
    assert registry.is_runnable(definition) is False and registry.is_runnable(registry.get("specialty.create")) is True
    stale = copy.deepcopy(broken)
    stale["meta"]["fingerprint"] = "outdated"
    snapshots._write("latest.json", stale)
    snapshots.reset_cache()
    assert registry.is_runnable(definition) is True  # a snapshot from older sources is ignored, never trusted


def test_chat_three_cases_exists_without_lesson_missing_and_with_lesson():
    kb_mod.load.cache_clear()
    case_none = service.answer("وين نظام العمليات الجراحية", ctx())
    assert case_none["type"] == "not_found" and case_none["message"].startswith("ما لقيت هذه الميزة ضمن النسخة الحالية.")
    case_two = service.answer("أريد أسوي موعد", ctx())
    assert "الميزة موجودة بالنظام، لكن الشرح التفاعلي الخاص بها بعده غير متوفر." in case_two["message"]
    assert not any(a["type"] == "start_tutorial" for a in case_two["actions"])
    case_three = service.answer("شلون أضيف طبيب", ctx())
    assert case_three["type"] == "tutorial_suggestion" and case_three["tutorial_id"] == "doctor.create"


def test_discovered_only_feature_gets_location_but_no_invented_steps():
    extra = [{"kind": "action", "id": "appointment.reschedule", "visible": True, "in_modal": False, "label": "تأجيل موعد"}]
    snapshots.save_runtime(runtime_payload(extra, extra_page="appointments"))
    snapshots.run_scan()
    snapshots.reset_cache()
    kb_mod.load.cache_clear()
    assert "discovered:appointment.reschedule" in kb_mod.load().entries
    for phrase in ("وين تأجيل موعد", "تأجيل موعد"):
        r = service.answer(phrase, ctx(page="dashboard"))
        assert "الميزة موجودة في صفحة" in r["message"] and "الشرح التفاعلي الخاص بها بعده غير متوفر" in r["message"], phrase
        assert not any(a["type"] == "start_tutorial" for a in r["actions"])
        assert all(a["type"] in ("show_me",) for a in r["actions"])
    ambiguous = service.answer("شلون اسوي تأجيل موعد", ctx())  # booking vs rescheduling: it asks instead of guessing
    assert ambiguous["type"] == "clarification" and any(a.get("intent") == "discovered:appointment.reschedule" for a in ambiguous["actions"])
    page_help = service.answer("شنو هاي الصفحة", ctx(page="appointments"))
    assert "تأجيل موعد" in page_help["message"]
    denied = service.answer("وين تأجيل موعد", ctx(allowed_pages={"staff"}))
    assert denied["message"] == "ما عندك صلاحية تنفيذ هذه العملية." and denied["actions"] == []
    # Without a fresh scan the discovered entry disappears again (nothing is assumed).
    snapshots.clear_all()
    snapshots.reset_cache()
    kb_mod.load.cache_clear()
    assert "discovered:appointment.reschedule" not in kb_mod.load().entries


def test_chat_never_suggests_what_the_user_cannot_do():
    r = service.answer("شلون أضيف طبيب", ctx(allowed_pages={"patients"}))
    assert r["message"] == "ما عندك صلاحية تنفيذ هذه العملية." and r["actions"] == []
    ok = service.answer("شلون أضيف طبيب", ctx(allowed_pages={"staff", "specialties"}))
    assert ok["type"] == "tutorial_suggestion"


def test_show_me_falls_back_to_the_sidebar_when_the_scan_lost_the_target():
    broken = snapshots.build_snapshot(simulate_missing={"specialty.create"})
    snapshots._write("latest.json", broken)
    snapshots.reset_cache()
    kb_mod.load.cache_clear()
    available = {d["id"] for d in registry.load_all().values() if registry.is_runnable(d)}  # what the API would offer
    r = service.answer("وين أضيف اختصاص؟", ctx(page="specialties", available_tutorials=available, runnable_tutorials=available))
    show = next(a for a in r["actions"] if a["type"] == "show_me")
    assert show["target"] == {"action": "nav.specialties"}  # never points at an element the scan cannot find
    assert not any(a["type"] == "start_tutorial" for a in r["actions"])  # its lesson is withheld too


def test_api_hides_a_broken_tutorial_from_users(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    assert client.post(BASE + "/tutorials/doctor.create/start").status_code == 200
    snapshots._write("latest.json", snapshots.build_snapshot(simulate_missing={"doctor.create"}))
    snapshots.reset_cache()
    assert client.post(BASE + "/tutorials/doctor.create/start").status_code == 404
    listed = [t["id"] for t in client.get(BASE + "/tutorials").get_json()["tutorials"]]
    assert "doctor.create" not in listed and "specialty.create" in listed
    answer = client.post(BASE + "/ask", json={"message": "شلون أضيف طبيب"}).get_json()["response"]
    assert not any(a["type"] == "start_tutorial" for a in answer["actions"])


# ------------------------------------------------------------- admin blueprint

@pytest.fixture()
def admin_client(monkeypatch):
    from routes.superadmin_ai_tutor import superadmin_ai_tutor_bp

    app = Flask(__name__, template_folder=str(static_scan.ROOT / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="analyzer-tests")
    app.register_blueprint(superadmin_ai_tutor_bp)
    # The page itself extends the full superadmin layout; JSON endpoints are what we exercise here.
    return app


def login(client, superadmin=True):
    with client.session_transaction() as sess:
        if superadmin:
            sess["is_superadmin"] = True
        else:
            sess["user_id"], sess["tenant_slug"] = 7, "clinic-a"


def test_system_map_is_superadmin_only(admin_client):
    for method, path in [("get", "/superadmin/ai-tutor/system-map/data"), ("post", "/superadmin/ai-tutor/system-map/scan"),
                         ("post", "/superadmin/ai-tutor/system-map/runtime")]:
        assert getattr(admin_client.test_client(), method)(path, json={}).status_code == 403
        tenant = admin_client.test_client()
        login(tenant, superadmin=False)
        assert getattr(tenant, method)(path, json={}).status_code == 403
    page = admin_client.test_client().get("/superadmin/ai-tutor/system-map")
    assert page.status_code == 302 and "/superadmin/login" in page.headers["Location"]


def test_admin_scan_snapshot_and_runtime_upload_flow(admin_client):
    client = admin_client.test_client()
    login(client)
    assert client.get("/superadmin/ai-tutor/system-map/data").get_json()["snapshot"] is None
    assert client.post("/superadmin/ai-tutor/system-map/runtime", json={"schema": 9}).status_code == 400
    assert client.post("/superadmin/ai-tutor/system-map/runtime", json=runtime_payload()).get_json()["ok"] is True
    scanned = client.post("/superadmin/ai-tutor/system-map/scan", json={}).get_json()
    assert scanned["ok"] and scanned["snapshot"]["meta"]["runtime"] is True and scanned["runtime"]["present"] is True and scanned["stale"] is False
    data = client.get("/superadmin/ai-tutor/system-map/data").get_json()
    assert data["snapshot"]["meta"]["created_at"] == scanned["snapshot"]["meta"]["created_at"]
    assert {t["id"]: t["status"] for t in data["snapshot"]["tutorials"]}["doctor.create"] == "verified"


def test_simulation_is_test_only_and_never_persisted(admin_client):
    client = admin_client.test_client()
    login(client)
    client.post("/superadmin/ai-tutor/system-map/scan", json={})
    saved = client.get("/superadmin/ai-tutor/system-map/data").get_json()["snapshot"]["meta"]["created_at"]
    sim = client.post("/superadmin/ai-tutor/system-map/scan", json={"simulate_missing": ["doctor.create"]}).get_json()
    assert sim["simulated"] is True and next(t for t in sim["snapshot"]["tutorials"] if t["id"] == "doctor.create")["status"] == "broken"
    assert client.get("/superadmin/ai-tutor/system-map/data").get_json()["snapshot"]["meta"]["created_at"] == saved
    assert client.post("/superadmin/ai-tutor/system-map/scan", json={"simulate_missing": "doctor.create"}).status_code == 400
    admin_client.config["TESTING"] = False  # production-like: simulation refused
    assert client.post("/superadmin/ai-tutor/system-map/scan", json={"simulate_missing": ["doctor.create"]}).status_code == 403


def test_reset_endpoint_is_superadmin_and_test_only(admin_client):
    path = "/superadmin/ai-tutor/system-map/reset"
    assert admin_client.test_client().post(path).status_code == 403
    client = admin_client.test_client()
    login(client)
    client.post("/superadmin/ai-tutor/system-map/scan", json={})
    assert client.get("/superadmin/ai-tutor/system-map/data").get_json()["snapshot"] is not None
    assert client.post(path).get_json() == {"ok": True}
    assert client.get("/superadmin/ai-tutor/system-map/data").get_json()["snapshot"] is None
    admin_client.config["TESTING"] = False  # production-like: refused
    assert client.post(path).status_code == 403

