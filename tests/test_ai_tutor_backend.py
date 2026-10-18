"""AI Tutor backend: registry validation, source-identifier check, gated API, real-state verification."""
import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

from extensions import db
from modules.ai_tutor import registry

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ROOT / "templates" / "clinics" / "workspace.html",
    *sorted((ROOT / "static" / "clinics").glob("*.js")),
]
ATTRIBUTE = {"page": "data-finora-page", "section": "data-finora-section",
             "action": "data-finora-action", "field": "data-finora-field"}


# ------------------------------------------------------------------ registry

def _definition():
    return copy.deepcopy(registry.get("doctor.create"))


def test_shipped_tutorials_are_valid():
    assert "doctor.create" in registry.load_all()


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d["steps"][0].update(type="teleport"), "unsupported step type"),
    (lambda d: d["steps"][0].update(target={"css": "div:nth-child(3)"}), "invalid target"),
    (lambda d: d["steps"][0].update(target={"action": "a", "field": "b"}), "exactly one"),
    (lambda d: d["steps"][1].update(route="staff"), "route"),
    (lambda d: d["steps"][4].update(then="ghost"), "existing step"),
    (lambda d: d["steps"][1].update(id=d["steps"][0]["id"]), "unique"),
    (lambda d: d.update(status="whatever"), "invalid status"),
    (lambda d: d["steps"][-3].update(type="highlight"), "complete step"),
])
def test_invalid_definitions_rejected(mutate, message):
    definition = _definition()
    if message == "complete step":
        for step in definition["steps"]:
            if step["type"] == "complete":
                step["type"] = "highlight"
    else:
        mutate(definition)
    with pytest.raises(registry.TutorialError, match=message):
        registry.validate_definition(definition)


def _expanded_corpus() -> str:
    """UI source with the JS template placeholders expanded to their concrete values."""
    text = chr(10).join(path.read_text(encoding="utf-8") for path in SOURCES)
    expanded = []
    for line in text.splitlines():
        for token, values in (("${fp}", ("doctor", "employee", "staff")), ("${staffType}", ("doctor", "employee")),
                              ("${group.key}", ("daily", "clinical", "finance", "communication", "admin"))):
            if token in line:
                expanded.extend(line.replace(token, value) for value in values)
                break
        else:
            expanded.append(line)
    return chr(10).join(expanded)


def test_every_tutorial_target_exists_in_ui_source():
    """Catches broken selectors before users do (Phase 6 will run this against the live DOM too)."""
    corpus = _expanded_corpus()
    missing = [
        f"{definition['id']}:{step['id']} -> {ref}"
        for definition in registry.load_all().values()
        for step in definition["steps"]
        for ref in registry.target_refs(step)
        for kind, ident in [next(iter(ref.items()))]
        if f'{ATTRIBUTE[kind]}="{ident}"' not in corpus
        and f"finoraAction: `{ident}`" not in corpus
        and not (kind == "action" and f'"{ident}"' in corpus)
    ]
    assert not missing, missing


def test_draft_tutorial_is_not_runnable_by_default(monkeypatch):
    definition = _definition()
    definition["status"] = "draft"
    monkeypatch.delenv("AI_TUTOR_ALLOW_DRAFT", raising=False)
    assert registry.is_runnable(definition) is False
    monkeypatch.setenv("AI_TUTOR_ALLOW_DRAFT", "1")
    assert registry.is_runnable(definition) is True
    for status in ("broken", "needs_review", "disabled"):
        definition["status"] = status
        assert registry.is_runnable(definition) is False


# ----------------------------------------------------------------------- API

@pytest.fixture()
def tutor_app(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ALLOW_DRAFT", "1")
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", SQLALCHEMY_TRACK_MODIFICATIONS=False,
                      TESTING=True, SECRET_KEY="tutor-tests")
    db.init_app(app)
    import models  # noqa: F401
    from models.core.tenant import Tenant as CoreTenant
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from models.employee import Employee
    from models.tenant import Tenant
    from modules.ai_tutor.models import AI_TUTOR_MODELS  # noqa: F401
    from modules.ai_tutor.routes import ai_tutor_bp
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401
    from routes.features_api import features_api_bp
    from routes.superadmin_features import superadmin_features_bp
    app.register_blueprint(ai_tutor_bp)
    app.register_blueprint(features_api_bp)
    app.register_blueprint(superadmin_features_bp)

    with app.app_context():
        db.create_all()
        from models.core.super_admin import SuperAdmin

        admin_super = SuperAdmin(username="root")
        admin_super.set_password("test-only-secret")
        db.session.add(admin_super)
        db.session.add(CoreTenant(name="A", slug="clinic-a", db_path="a.db", is_active=True))
        db.session.add(CoreTenant(name="B", slug="clinic-b", db_path="b.db", is_active=True))
        tenant = Tenant(name="A", business_type="clinics", plan_key="basic", plan_name="x", monthly_price=0)
        db.session.add(tenant)
        db.session.flush()
        owner = Employee(tenant_id=tenant.id, name="Owner", username="owner", password="x", role="admin", is_active=True)
        plain = Employee(tenant_id=tenant.id, name="Plain", username="plain", password="x", role="staff", is_active=True)
        db.session.add_all([owner, plain])
        db.session.commit()
        app.config["IDS"] = {"tenant": tenant.id, "owner": owner.id, "plain": plain.id}
        from services import feature_service

        feature_service.invalidate_cache()
        yield app
        db.session.remove()
        db.drop_all()


def _enable(app, slug="clinic-a"):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["is_superadmin"], sess["superadmin_id"] = True, 1
    assert client.patch(f"/superadmin/features/tenants/{slug}/clinic_ai_tutor", json={"enabled": True}).status_code == 200


def _user(app, who="owner", slug="clinic-a"):
    client = app.test_client()
    ids = app.config["IDS"]
    with client.session_transaction() as sess:
        sess["user_id"], sess["tenant_id"], sess["tenant_slug"] = ids[who], ids["tenant"], slug
    return client


BASE = "/api/clinic/ai-tutor"


def test_every_tutor_route_rejects_disabled_tenant(tutor_app):
    client = _user(tutor_app)
    for method, path in [("get", "/tutorials"), ("get", "/tutorials/doctor.create"), ("get", "/active"),
                         ("post", "/tutorials/doctor.create/start"), ("post", "/tutorials/doctor.create/progress"),
                         ("post", "/tutorials/doctor.create/verify"), ("post", "/tutorials/doctor.create/complete"),
                         ("post", "/tutorials/doctor.create/resume")]:
        res = getattr(client, method)(BASE + path)
        assert res.status_code == 403, path
        assert res.get_json() == {"error": "FEATURE_NOT_ENABLED", "feature": "clinic_ai_tutor"}


def test_other_tenant_stays_blocked_and_anonymous_rejected(tutor_app):
    _enable(tutor_app, "clinic-a")
    assert _user(tutor_app, slug="clinic-b").get(BASE + "/tutorials").status_code == 403
    assert tutor_app.test_client().get(BASE + "/tutorials").status_code == 401


def test_permission_filters_tutorials(tutor_app):
    _enable(tutor_app)
    owner_ids = [t["id"] for t in _user(tutor_app, "owner").get(BASE + "/tutorials").get_json()["tutorials"]]
    assert {"doctor.create", "specialty.create"} <= set(owner_ids) and owner_ids == sorted(owner_ids)
    assert _user(tutor_app, "plain").get(BASE + "/tutorials").get_json()["tutorials"] == []
    assert _user(tutor_app, "plain").post(BASE + "/tutorials/doctor.create/start").status_code in (403, 404)


def test_unknown_or_draft_tutorial_hidden(tutor_app, monkeypatch):
    _enable(tutor_app)
    client = _user(tutor_app)
    assert client.post(BASE + "/tutorials/nope/start").status_code == 404
    monkeypatch.delenv("AI_TUTOR_ALLOW_DRAFT")
    if registry.get("doctor.create")["status"] != "verified":
        assert client.post(BASE + "/tutorials/doctor.create/start").status_code == 404


def _create_doctor(app, created_at=None):
    from modules.clinics.models import ClinicDoctor

    row = ClinicDoctor(tenant_id=app.config["IDS"]["tenant"], full_name="Dr Test")
    if created_at:
        row.created_at = created_at
    db.session.add(row)
    db.session.commit()


def test_full_progress_flow_with_real_state_verification(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    started = client.post(BASE + "/tutorials/doctor.create/start").get_json()
    steps = [s["id"] for s in started["tutorial"]["steps"]]
    assert started["progress"]["current_step"] == steps[0] and started["progress"]["status"] == "in_progress"

    # Verification and completion must fail while no doctor exists.
    assert client.post(BASE + "/tutorials/doctor.create/verify",
                       json={"validator": "doctor.created_since_start"}).get_json()["verified"] is False
    assert client.post(BASE + "/tutorials/doctor.create/complete").status_code == 422

    # Progress moves forward only.
    ok = client.post(BASE + "/tutorials/doctor.create/progress",
                     json={"event": "step_completed", "step_id": steps[0], "next_step_id": steps[2]})
    assert ok.get_json()["progress"]["step_index"] == 2
    late = client.post(BASE + "/tutorials/doctor.create/progress",
                       json={"event": "step_completed", "step_id": steps[0], "next_step_id": steps[1]})
    assert late.get_json()["progress"]["step_index"] == 2
    assert client.get(BASE + "/active").get_json()["active"]["progress"]["current_step"] == steps[2]

    # Explicit, user-approved rewind is the only way back.
    rewound = client.post(BASE + "/tutorials/doctor.create/progress", json={"event": "rewind", "step_id": steps[1]})
    assert rewound.get_json()["progress"]["step_index"] == 1

    # A doctor that pre-dates the run does not count.
    _create_doctor(tutor_app, created_at=datetime.utcnow() - timedelta(days=1))
    assert client.post(BASE + "/tutorials/doctor.create/verify",
                       json={"validator": "doctor.created_since_start"}).get_json()["verified"] is False
    _create_doctor(tutor_app)
    assert client.post(BASE + "/tutorials/doctor.create/verify",
                       json={"validator": "doctor.created_since_start"}).get_json()["verified"] is True

    done = client.post(BASE + "/tutorials/doctor.create/complete").get_json()["progress"]
    assert done["status"] == "completed" and done["completed_at"]
    assert client.get(BASE + "/active").get_json()["active"] is None


def test_progress_rejects_garbage(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    assert client.post(BASE + "/tutorials/doctor.create/progress",
                       json={"event": "step_completed", "step_id": "name", "next_step_id": "phone"}).status_code == 409
    client.post(BASE + "/tutorials/doctor.create/start")
    for body in ({"event": "hack", "step_id": "name"},
                 {"event": "step_completed", "step_id": "ghost", "next_step_id": "name"},
                 {"event": "step_completed", "step_id": "name", "next_step_id": "ghost"}):
        assert client.post(BASE + "/tutorials/doctor.create/progress", json=body).status_code == 400
    assert client.post(BASE + "/tutorials/doctor.create/verify", json={"validator": "os.system"}).status_code == 400


def test_target_missing_pauses_and_logs_without_field_content(tutor_app):
    from modules.ai_tutor.models import TrainingActivityLog

    _enable(tutor_app)
    client = _user(tutor_app)
    client.post(BASE + "/tutorials/doctor.create/start")
    res = client.post(BASE + "/tutorials/doctor.create/progress",
                      json={"event": "target_missing", "step_id": "name", "detail": "field:doctor.name"})
    assert res.get_json()["progress"]["status"] == "paused"
    assert client.get(BASE + "/active").get_json()["active"] is None
    events = [(r.event, r.step_id) for r in TrainingActivityLog.query.order_by(TrainingActivityLog.id)]
    assert events == [("tutorial_started", "open-staff-menu"), ("target_missing", "name")]
    assert client.post(BASE + "/tutorials/doctor.create/resume").get_json()["progress"]["status"] == "in_progress"


def test_progress_is_isolated_per_user_and_version_change_discards_stale_runs(tutor_app):
    from modules.ai_tutor.models import UserTrainingProgress

    _enable(tutor_app)
    owner = _user(tutor_app, "owner")
    owner.post(BASE + "/tutorials/doctor.create/start")
    assert owner.get(BASE + "/active").get_json()["active"] is not None
    row = UserTrainingProgress.query.one()
    row.tutorial_version = 0  # simulates a run started before the tutorial changed
    db.session.commit()
    assert owner.get(BASE + "/active").get_json()["active"] is None
    assert UserTrainingProgress.query.one().status == "not_started"


def test_disabling_feature_blocks_active_run_immediately(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    client.post(BASE + "/tutorials/doctor.create/start")
    admin = tutor_app.test_client()
    with admin.session_transaction() as sess:
        sess["is_superadmin"], sess["superadmin_id"] = True, 1
    admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor", json={"enabled": False})
    assert client.get(BASE + "/active").status_code == 403


# ------------------------------------------------- dependencies / reconcile / titles

def test_reconcile_policy_is_validated():
    definition = _definition()
    save = next(s for s in definition["steps"] if s["id"] == "save")
    save["reconcile"] = {"kind": "ui", "when": {"page": "staff"}}
    with pytest.raises(registry.TutorialError, match="backend state"):
        registry.validate_definition(definition)  # an irreversible step can never be skipped from UI state alone
    save["reconcile"] = {"kind": "backend"}
    with pytest.raises(registry.TutorialError, match="validator"):
        registry.validate_definition(definition)
    definition = _definition()
    next(s for s in definition["steps"] if s["id"] == "name")["reconcile"] = {"kind": "ui", "when": {"nope": 1}}
    with pytest.raises(registry.TutorialError, match="reconcile.when"):
        registry.validate_definition(definition)


def test_dependency_and_title_rules_are_validated():
    definition = _definition()
    definition["dependencies"][0]["fact"]["name"] = "nonexistent_count"
    with pytest.raises(registry.TutorialError, match="fact rule"):
        registry.validate_definition(definition)
    definition = _definition()
    definition["title_first_ar"] = ""
    with pytest.raises(registry.TutorialError, match="title_first_ar"):
        registry.validate_definition(definition)


def test_dependency_target_tutorial_exists():
    assert registry.get("doctor.create")["dependencies"][0]["tutorial"] == "specialty.create"
    assert registry.get("specialty.create") is not None


def test_onboarding_wording_depends_on_doctor_count():
    definition = registry.get("doctor.create")
    assert registry.onboarding_title(definition, {"doctors_count": 0, "specialties_count": 1}) == "إضافة أول طبيب"
    assert registry.onboarding_title(definition, {"doctors_count": 3, "specialties_count": 1}) == "إضافة طبيب"
    assert definition["title_ar"] == "إضافة طبيب"  # the lesson itself is never "first doctor"


def test_facts_and_onboarding_api(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    facts = client.get(BASE + "/facts").get_json()["facts"]
    assert {"doctors_count": 0, "specialties_count": 0, "patients_count": 0} == {k: facts[k] for k in ("doctors_count", "specialties_count", "patients_count")}
    assert set(facts) == set(__import__("modules.ai_tutor.facts", fromlist=["FACT_NAMES"]).FACT_NAMES)
    first = client.get(BASE + "/onboarding").get_json()
    assert first["show"] is True
    assert first["suggestions"][0] == {"id": "doctor.create", "title_ar": "إضافة أول طبيب"}
    _create_doctor(tutor_app)
    assert client.get(BASE + "/onboarding").get_json()["suggestions"][0]["title_ar"] == "إضافة طبيب"
    assert client.post(BASE + "/onboarding/dismiss", json={"forever": False}).get_json()["stored"] is False
    assert client.get(BASE + "/onboarding").get_json()["show"] is True  # "later" is not stored server-side
    assert client.post(BASE + "/onboarding/dismiss", json={"forever": True}).get_json()["stored"] is True
    assert client.get(BASE + "/onboarding").get_json()["show"] is False
    assert _user(tutor_app, "plain").get(BASE + "/onboarding").get_json()["show"] is False  # no permitted lessons
    # The welcome row never shows up as an "active" tutorial or in the lesson list.
    assert client.get(BASE + "/active").get_json()["active"] is None
    listed = [t["id"] for t in client.get(BASE + "/tutorials").get_json()["tutorials"]]
    assert "_onboarding" not in listed and {"doctor.create", "specialty.create"} <= set(listed)


def test_dependency_flow_parks_parent_and_resumes_it(tutor_app):
    from modules.ai_tutor.models import UserTrainingProgress
    from modules.clinics.models import ClinicSpecialty

    _enable(tutor_app)
    client = _user(tutor_app)
    parent_steps = [s["id"] for s in registry.get("doctor.create")["steps"]]

    # A child may only be started for a parent that is in progress and actually depends on it.
    refuse = client.post(BASE + "/tutorials/specialty.create/start",
                         json={"parent": {"tutorial_id": "doctor.create", "step_id": parent_steps[0]}})
    assert refuse.status_code == 409
    client.post(BASE + "/tutorials/doctor.create/start")
    bad_parent = client.post(BASE + "/tutorials/specialty.create/start",
                             json={"parent": {"tutorial_id": "specialty.create", "step_id": "name"}})
    assert bad_parent.status_code in (400, 409)

    started = client.post(BASE + "/tutorials/specialty.create/start",
                          json={"parent": {"tutorial_id": "doctor.create", "step_id": parent_steps[0]}}).get_json()
    assert started["progress"]["parent"] == {"tutorial_id": "doctor.create", "step_id": parent_steps[0]}
    rows = {r.tutorial_id: r.status for r in UserTrainingProgress.query}
    assert rows["doctor.create"] == "paused" and rows["specialty.create"] == "in_progress"
    assert client.get(BASE + "/active").get_json()["active"]["tutorial"]["id"] == "specialty.create"

    # The child cannot complete until a specialty really exists.
    assert client.post(BASE + "/tutorials/specialty.create/complete").status_code == 422
    db.session.add(ClinicSpecialty(tenant_id=tutor_app.config["IDS"]["tenant"], name_ar="طب الأسنان", code="dentistry"))
    db.session.commit()
    done = client.post(BASE + "/tutorials/specialty.create/complete").get_json()
    assert done["parent"] == {"tutorial_id": "doctor.create", "step_id": parent_steps[0]}

    resumed = client.post(BASE + "/tutorials/doctor.create/resume", json={"step_id": done["parent"]["step_id"]}).get_json()
    assert resumed["progress"]["status"] == "in_progress" and resumed["progress"]["current_step"] == parent_steps[0]
    assert client.get(BASE + "/active").get_json()["active"]["tutorial"]["id"] == "doctor.create"
    assert client.get(BASE + "/facts").get_json()["facts"]["specialties_count"] == 1


def test_abandoning_child_clears_link_and_keeps_parent_paused(tutor_app):
    from modules.ai_tutor.models import UserTrainingProgress

    _enable(tutor_app)
    client = _user(tutor_app)
    first = registry.get("doctor.create")["steps"][0]["id"]
    client.post(BASE + "/tutorials/doctor.create/start")
    client.post(BASE + "/tutorials/specialty.create/start",
                json={"parent": {"tutorial_id": "doctor.create", "step_id": first}})
    client.post(BASE + "/tutorials/specialty.create/progress", json={"event": "abandoned", "step_id": "name"})
    child = UserTrainingProgress.query.filter_by(tutorial_id="specialty.create").one()
    assert child.status == "not_started" and child.parent_tutorial_id is None
    assert UserTrainingProgress.query.filter_by(tutorial_id="doctor.create").one().status == "paused"


def test_exit_saves_place_and_resume_continues(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    steps = [s["id"] for s in registry.get("doctor.create")["steps"]]
    client.post(BASE + "/tutorials/doctor.create/start")
    client.post(BASE + "/tutorials/doctor.create/progress",
                json={"event": "step_completed", "step_id": steps[0], "next_step_id": steps[5]})
    client.post(BASE + "/tutorials/doctor.create/progress", json={"event": "paused", "step_id": steps[5]})
    assert client.get(BASE + "/active").get_json()["active"] is None
    again = client.post(BASE + "/tutorials/doctor.create/resume").get_json()["progress"]
    assert again["status"] == "in_progress" and again["step_index"] == 5


def test_additive_schema_adds_parent_columns_to_existing_tables(tutor_app):
    from sqlalchemy import inspect, text

    from modules.ai_tutor import schema

    with tutor_app.app_context():
        db.session.execute(text("DROP TABLE user_training_progress"))
        db.session.execute(text("CREATE TABLE user_training_progress (id INTEGER PRIMARY KEY, tenant_id INTEGER NOT NULL, "
                                "user_id INTEGER NOT NULL, tutorial_id VARCHAR(80) NOT NULL, tutorial_version INTEGER NOT NULL, "
                                "current_step VARCHAR(80), step_index INTEGER NOT NULL, status VARCHAR(20) NOT NULL, "
                                "started_at DATETIME, completed_at DATETIME, last_activity_at DATETIME NOT NULL)"))
        db.session.commit()
        schema._ensured.clear()
        schema.ensure_ai_tutor_schema()
        names = {c["name"] for c in inspect(db.session.get_bind()).get_columns("user_training_progress")}
    assert {"parent_tutorial_id", "parent_step_id"} <= names
