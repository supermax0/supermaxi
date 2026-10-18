"""Phase 7 backend tests: the clinic core journey lessons, their server-side verification and the lesson graph."""
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.ai_tutor import registry
from modules.ai_tutor.models import TrainingActivityLog
from tests.test_ai_tutor_backend import BASE, _enable, _user, tutor_app  # noqa: F401  (fixtures)


def _dental_specialty(app):
    """treatment_plan.create needs this (Phase 8A: availability.required_specialty)."""
    from modules.clinics.models import ClinicSpecialty

    row = ClinicSpecialty(tenant_id=app.config["IDS"]["tenant"], name_ar="الأسنان", code="dentistry", is_active=True)
    db.session.add(row)
    db.session.commit()
    return row


def _patient(app, created_at=None, name="مريض"):
    from modules.clinics.models import ClinicPatient

    count = ClinicPatient.query.count()
    row = ClinicPatient(tenant_id=app.config["IDS"]["tenant"], file_number=f"F{count + 1}", full_name=name)
    if created_at:
        row.created_at = created_at
    db.session.add(row)
    db.session.commit()
    return row


def _start(client, lesson):
    res = client.post(f"{BASE}/tutorials/{lesson}/start")
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


# ------------------------------------------------------------------ patient.create

def test_patient_lesson_is_backend_verified(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    _patient(tutor_app, created_at=datetime.utcnow() - timedelta(days=1), name="قديم")  # before the lesson: never counts
    _start(client, "patient.create")
    verify = lambda: client.post(f"{BASE}/tutorials/patient.create/verify", json={"validator": "patient.created_since_start"})
    assert verify().get_json()["verified"] is False
    assert client.post(f"{BASE}/tutorials/patient.create/complete").status_code == 422  # opening the form is not a result
    _patient(tutor_app, name="جديد")
    assert verify().get_json()["verified"] is True
    done = client.post(f"{BASE}/tutorials/patient.create/complete").get_json()
    assert done["progress"]["status"] == "completed"


def test_patient_lesson_needs_the_patients_permission(tutor_app):
    _enable(tutor_app)
    assert _user(tutor_app, "plain").post(f"{BASE}/tutorials/patient.create/start").status_code in (403, 404)


def test_patient_count_fact_ignores_archived(tutor_app):
    from modules.ai_tutor.facts import collect_facts

    _enable(tutor_app)
    tenant = tutor_app.config["IDS"]["tenant"]
    assert collect_facts(tenant)["patients_count"] == 0
    _patient(tutor_app)
    archived = _patient(tutor_app)
    archived.status = "archived"
    db.session.commit()
    assert collect_facts(tenant)["patients_count"] == 1
    assert registry.onboarding_title(registry.get("patient.create"), {"patients_count": 0}) == "إضافة أول مريض"


# --------------------------------------------------------------- appointment.create

def _appointment(app, created_at=None):
    from modules.clinics.models import ClinicAppointment

    patient = _patient(app)
    row = ClinicAppointment(tenant_id=app.config["IDS"]["tenant"], patient_id=patient.id,
                            appointment_date=datetime.utcnow().date(), start_time=datetime.utcnow().time(),
                            end_time=datetime.utcnow().time(), status="confirmed")
    if created_at:
        row.created_at = created_at
    db.session.add(row)
    db.session.commit()
    return row


def test_appointment_lesson_is_backend_verified(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    _appointment(tutor_app, created_at=datetime.utcnow() - timedelta(days=1))  # earlier appointment never counts
    _start(client, "appointment.create")
    check = lambda: client.post(f"{BASE}/tutorials/appointment.create/verify", json={"validator": "appointment.created_since_start"}).get_json()["verified"]
    assert check() is False
    assert client.post(f"{BASE}/tutorials/appointment.create/complete").status_code == 422
    _appointment(tutor_app)
    assert check() is True
    assert client.post(f"{BASE}/tutorials/appointment.create/complete").get_json()["progress"]["status"] == "completed"


def test_appointment_dependencies_are_data_driven_and_chain_through_the_registry():
    """Patient first, then doctor (which itself needs a specialty): the chain is declared, never hard-coded in the engine."""
    deps = registry.get("appointment.create")["dependencies"]
    assert [(d["fact"]["name"], d["tutorial"]) for d in deps] == [("patients_count", "patient.create"), ("doctors_count", "doctor.create")]
    assert [d["tutorial"] for d in registry.get("doctor.create")["dependencies"]] == ["specialty.create"]
    assert registry.get("patient.create").get("dependencies") is None


def test_dependency_stack_is_two_levels_deep_and_resumes_each_parent(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    _start(client, "appointment.create")
    parent = lambda lesson, step: {"parent": {"tutorial_id": lesson, "step_id": step}}
    doctor = client.post(f"{BASE}/tutorials/doctor.create/start", json=parent("appointment.create", "open-appointments-menu"))
    assert doctor.status_code == 200
    specialty = client.post(f"{BASE}/tutorials/specialty.create/start", json=parent("doctor.create", "open-staff-menu"))
    assert specialty.status_code == 200
    from modules.ai_tutor.models import UserTrainingProgress

    rows = {r.tutorial_id: (r.status, r.parent_tutorial_id) for r in UserTrainingProgress.query.all()}
    assert rows == {"appointment.create": ("paused", None), "doctor.create": ("paused", "appointment.create"),
                    "specialty.create": ("in_progress", "doctor.create")}
    assert client.get(f"{BASE}/active").get_json()["active"]["progress"]["tutorial_id"] == "specialty.create"  # exactly one active lesson


# ----------------------------------------------- check-in -> queue -> visit (appointment stages)

def _stage(app, status):
    """An appointment for today that is already in `status`, with the history row a real status change leaves."""
    from modules.clinics.models import ClinicAppointmentStatusHistory

    row = _appointment(app)
    row.status = status
    db.session.add(ClinicAppointmentStatusHistory(tenant_id=row.tenant_id, appointment_id=row.id, from_status="confirmed", to_status=status))
    db.session.commit()
    return row


def test_stage_facts_count_only_todays_appointments_in_that_stage(tutor_app):
    from modules.ai_tutor.facts import collect_facts

    tenant = tutor_app.config["IDS"]["tenant"]
    assert {k: v for k, v in collect_facts(tenant).items() if k.startswith("appointments_")} == {
        "appointments_scheduled_today": 0, "appointments_arrived_today": 0, "appointments_waiting_today": 0}
    _appointment(tutor_app)
    _stage(tutor_app, "arrived")
    _stage(tutor_app, "waiting")
    old = _appointment(tutor_app)
    old.appointment_date = datetime.utcnow().date() - timedelta(days=2)
    db.session.commit()
    facts = collect_facts(tenant)
    assert (facts["appointments_scheduled_today"], facts["appointments_arrived_today"], facts["appointments_waiting_today"]) == (1, 1, 1)


@pytest.mark.parametrize("lesson,validator,status", [
    ("appointment.checkin", "appointment.checked_in_since_start", "arrived"),
    ("queue.add", "appointment.queued_since_start", "waiting"),
])
def test_stage_lessons_are_verified_by_the_status_history_after_start(tutor_app, lesson, validator, status):
    _enable(tutor_app)
    client = _user(tutor_app)
    _stage(tutor_app, status)  # reached BEFORE the lesson started: must not count
    db.session.execute(db.text("UPDATE clinic_appointment_status_history SET changed_at = :t"), {"t": datetime.utcnow() - timedelta(days=1)})
    db.session.commit()
    _start(client, lesson)
    verify = lambda: client.post(f"{BASE}/tutorials/{lesson}/verify", json={"validator": validator}).get_json()["verified"]
    assert verify() is False
    assert client.post(f"{BASE}/tutorials/{lesson}/complete").status_code == 422
    _stage(tutor_app, status)
    assert verify() is True
    assert client.post(f"{BASE}/tutorials/{lesson}/complete").status_code == 200


def test_visit_lesson_needs_a_visit_created_from_an_appointment_after_start(tutor_app):
    from modules.clinics.models import ClinicVisit

    _enable(tutor_app)
    client = _user(tutor_app)
    _start(client, "visit.start")
    verify = lambda: client.post(f"{BASE}/tutorials/visit.start/verify", json={"validator": "visit.started_since_start"}).get_json()["verified"]
    assert verify() is False
    appt = _appointment(tutor_app)
    walkin = ClinicVisit(tenant_id=appt.tenant_id, patient_id=appt.patient_id)  # a walk-in visit is NOT this lesson's result
    db.session.add(walkin)
    db.session.commit()
    assert verify() is False
    db.session.add(ClinicVisit(tenant_id=appt.tenant_id, patient_id=appt.patient_id, appointment_id=appt.id))
    db.session.commit()
    assert verify() is True


def test_appointment_stage_dependencies_form_one_chain():
    chain, lesson = [], "visit.start"
    while registry.get(lesson).get("dependencies"):
        dep = registry.get(lesson)["dependencies"][0]
        chain.append((lesson, dep["fact"]["name"], dep["tutorial"]))
        lesson = dep["tutorial"]
    assert chain[:3] == [("visit.start", "appointments_waiting_today", "queue.add"),
                         ("queue.add", "appointments_arrived_today", "appointment.checkin"),
                         ("appointment.checkin", "appointments_scheduled_today", "appointment.create")]


def test_recommended_next_lessons_follow_the_core_journey(monkeypatch):
    monkeypatch.setenv("AI_TUTOR_ALLOW_DRAFT", "1")
    allow = lambda _p: True
    graph = {"patient.create": "appointment.create", "appointment.create": "appointment.checkin",
             "appointment.checkin": "queue.add", "queue.add": "visit.start"}
    for lesson, expected in graph.items():
        assert [i["id"] for i in registry.next_lessons(registry.get(lesson), allow)] == [expected]


# ------------------------------------------- setup + treatment + invoice lessons (server-side proof)

def _after_start(client, lesson):
    """start the lesson, return verify() -> bool for its declared completion validator"""
    _start(client, lesson)
    validator = registry.get(lesson)["completion_validator"]
    return lambda: client.post(f"{BASE}/tutorials/{lesson}/verify", json={"validator": validator}).get_json()["verified"]


def _make_service(app, **extra):
    from modules.clinics.models import ClinicService

    row = ClinicService(tenant_id=app.config["IDS"]["tenant"], name=f"خدمة {ClinicService.query.count()}", **extra)
    db.session.add(row)
    db.session.commit()
    return row


def test_service_lesson_counts_only_services_created_after_start(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    _make_service(tutor_app, created_at=datetime.utcnow() - timedelta(days=1))
    verify = _after_start(client, "service.create")
    assert verify() is False and client.post(f"{BASE}/tutorials/service.create/complete").status_code == 422
    _make_service(tutor_app)
    assert verify() is True


def test_schedule_lesson_counts_only_new_shifts(tutor_app):
    from datetime import time

    from modules.clinics.models import ClinicDoctor, ClinicDoctorSchedule

    _enable(tutor_app)
    client = _user(tutor_app)
    doctor = ClinicDoctor(tenant_id=tutor_app.config["IDS"]["tenant"], full_name="Dr S")
    db.session.add(doctor)
    db.session.commit()

    def shift(created_at=None):
        row = ClinicDoctorSchedule(tenant_id=doctor.tenant_id, doctor_id=doctor.id, weekday=0, start_time=time(9), end_time=time(12))
        if created_at:
            row.created_at = created_at
        db.session.add(row)
        db.session.commit()

    shift(datetime.utcnow() - timedelta(days=1))
    verify = _after_start(client, "doctor.schedule")
    assert verify() is False
    shift()
    assert verify() is True


def test_treatment_plan_lesson_needs_a_plan_and_a_first_item_after_start(tutor_app):
    from modules.clinics.models import ClinicDentalTreatmentPlan, ClinicDentalTreatmentPlanItem

    _enable(tutor_app)
    _dental_specialty(tutor_app)
    client = _user(tutor_app)
    patient = _patient(tutor_app)
    tenant = tutor_app.config["IDS"]["tenant"]
    verify_plan = lambda: client.post(f"{BASE}/tutorials/treatment_plan.create/verify", json={"validator": "treatment_plan.created_since_start"}).get_json()["verified"]
    verify_item = lambda: client.post(f"{BASE}/tutorials/treatment_plan.create/verify", json={"validator": "treatment_plan.item_added_since_start"}).get_json()["verified"]
    _start(client, "treatment_plan.create")
    assert verify_plan() is False and verify_item() is False
    plan = ClinicDentalTreatmentPlan(tenant_id=tenant, patient_id=patient.id, name="خطة")
    db.session.add(plan)
    db.session.commit()
    assert verify_plan() is True and verify_item() is False  # a plan alone does not finish the lesson
    assert client.post(f"{BASE}/tutorials/treatment_plan.create/complete").status_code == 422
    db.session.add(ClinicDentalTreatmentPlanItem(tenant_id=tenant, plan_id=plan.id, title="حشوة"))
    db.session.commit()
    assert verify_item() is True
    assert client.post(f"{BASE}/tutorials/treatment_plan.create/complete").status_code == 200


def test_invoice_lesson_is_verified_by_an_invoice_not_by_a_payment(tutor_app):
    from modules.clinics.models import ClinicInvoice

    _enable(tutor_app)
    client = _user(tutor_app)
    patient = _patient(tutor_app)
    verify = _after_start(client, "invoice.create")
    assert verify() is False
    db.session.add(ClinicInvoice(tenant_id=patient.tenant_id, patient_id=patient.id, invoice_number="INV-T1"))
    db.session.commit()
    assert verify() is True  # created, nothing paid: Phase 7 never records money
    assert registry.get("invoice.create")["completion_validator"] == "invoice.created_since_start"
    # "pay" is legitimate for payment.record itself, "refund" for refund.record itself; every OTHER lesson
    # (including invoice.create) must never touch either, and NOTHING may touch void/posting (not built: no
    # real UI/backend workflow for void-invoice or reverse/delete-payment exists yet).
    always_forbidden = ("void", "posting")
    exempt_word = {"payment.record": "pay", "refund.record": "refund"}
    for lesson in registry.load_all().values():
        forbidden = tuple(w for w in always_forbidden + ("pay", "refund") if w != exempt_word.get(lesson["id"]))
        for step in lesson["steps"]:
            for ref in registry.target_refs(step):
                assert not any(word in next(iter(ref.values())) for word in forbidden), (lesson["id"], step["id"])
            assert not any(word in (step.get("match") or {}).get("url", "") for word in forbidden), (lesson["id"], step["id"])


def test_employee_lesson_rejects_doctor_accounts(tutor_app):
    from models.employee import Employee
    from modules.clinics.models import ClinicDoctor

    _enable(tutor_app)
    client = _user(tutor_app)
    tenant = tutor_app.config["IDS"]["tenant"]
    verify = _after_start(client, "employee.create")
    doctor_account = Employee(tenant_id=tenant, name="Dr", username="dr1", password="x", role="clinic_doctor", is_active=True)
    db.session.add(doctor_account)
    db.session.flush()
    db.session.add(ClinicDoctor(tenant_id=tenant, full_name="Dr", employee_id=doctor_account.id))
    db.session.commit()
    assert verify() is False  # a doctor account is the doctor lesson's result, not this one
    db.session.add(Employee(tenant_id=tenant, name="Reception", username="rec1", password="x", role="clinic_reception", is_active=True))
    db.session.commit()
    assert verify() is True


def test_permissions_lesson_is_proved_by_the_audit_trail_and_never_runs_on_its_own(tutor_app):
    from modules.clinics.models import ClinicAuditLog

    _enable(tutor_app)
    client = _user(tutor_app)
    tenant = tutor_app.config["IDS"]["tenant"]
    old = ClinicAuditLog(tenant_id=tenant, entity_type="clinic_staff", entity_id=1, action="update", summary="قديم",
                         created_at=datetime.utcnow() - timedelta(days=1))
    db.session.add(old)
    db.session.commit()
    verify = _after_start(client, "permissions.manage")
    assert verify() is False
    db.session.add(ClinicAuditLog(tenant_id=tenant, entity_type="clinic_staff", entity_id=2, action="create", summary="x"))
    db.session.commit()
    assert verify() is False  # creating an account is not editing permissions
    db.session.add(ClinicAuditLog(tenant_id=tenant, entity_type="clinic_staff", entity_id=2, action="update", summary="x"))
    db.session.commit()
    assert verify() is True
    steps = registry.get("permissions.manage")["steps"]
    # a teaching lesson: the only API the person triggers is the one save they press (PATCH of ONE staff account)
    assert [s["match"] for s in steps if s["type"] == "wait_api_success"] == [{"method": "PATCH", "url": "^/clinics/api/staff/\\d+$"}]


# ---------------------------------------------------------------- graph, curriculum, roles

def test_the_whole_lesson_graph_matches_the_clinic_journey():
    expected = {
        "doctor.create": ["doctor.schedule"], "patient.create": ["appointment.create"], "appointment.create": ["appointment.checkin"],
        "appointment.checkin": ["queue.add"], "queue.add": ["visit.start"], "visit.start": ["treatment_plan.create"],
        "treatment_plan.create": ["invoice.create"], "employee.create": ["permissions.manage"],
    }
    for lesson, nxt in expected.items():
        assert registry.get(lesson)["next_lessons"] == nxt, lesson
    # every recommendation is a real lesson and never loops back
    for lesson, definition in registry.load_all().items():
        for target in definition.get("next_lessons", []):
            assert registry.get(target) and target != lesson


def test_curriculum_is_generated_from_the_registry_and_only_lists_real_lessons(tutor_app):
    _enable(tutor_app)
    _dental_specialty(tutor_app)
    plan = _user(tutor_app, "owner").get(f"{BASE}/knowledge").get_json()["plan"]
    groups = {g["id"]: [i["id"] for i in g["items"]] for g in plan["groups"]}
    assert groups["setup"] == ["specialty.create", "doctor.create", "doctor.schedule", "employee.create", "permissions.manage", "service.create"]
    assert groups["operations"] == ["patient.create", "appointment.create", "appointment.checkin", "queue.add", "visit.start",
                                    "treatment_plan.create", "invoice.create"]
    assert groups["collections"] == ["payment.record", "refund.record"]
    assert all(registry.get(i) for ids in groups.values() for i in ids)  # nothing "coming later": only lessons that exist
    assert [g["title_ar"] for g in plan["groups"]] == ["إعداد العيادة", "تشغيل العيادة", "التحصيل"]


def _limited_user(app, permissions):
    from models.employee import Employee
    from models.role import Permission, Role

    tenant = app.config["IDS"]["tenant"]
    employee = Employee(tenant_id=tenant, name="Limited", username=f"lim{len(permissions)}", password="x", role="clinic_reception", is_active=True)
    role = Role(name=f"role-{len(permissions)}-{Role.query.count()}")
    for name in permissions:
        role.permissions.append(Permission.query.filter_by(name=name).first() or Permission(name=name, description=name))
    employee.roles.append(role)
    db.session.add_all([employee, role])
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"], sess["tenant_id"], sess["tenant_slug"] = employee.id, tenant, "clinic-a"
    return client


def test_curriculum_follows_permissions_not_role_names(tutor_app):
    _enable(tutor_app)
    _dental_specialty(tutor_app)
    # same role name ("reception"), different permissions -> different curriculum
    desk = _limited_user(tutor_app, ["clinics_patients", "clinics_appointments", "clinics_reception"])
    ids = {i["id"] for g in desk.get(f"{BASE}/knowledge").get_json()["plan"]["groups"] for i in g["items"]}
    assert ids == {"patient.create", "appointment.create", "appointment.checkin", "queue.add"}  # patients, appointments, check-in, queue
    clinician = _limited_user(tutor_app, ["clinics_visits", "clinics_clinical", "clinics_reception", "clinics_appointments"])
    ids = {i["id"] for g in clinician.get(f"{BASE}/knowledge").get_json()["plan"]["groups"] for i in g["items"]}
    assert {"visit.start", "treatment_plan.create", "appointment.checkin", "queue.add"} <= ids
    assert not ids & {"doctor.create", "employee.create", "permissions.manage", "service.create", "doctor.schedule", "invoice.create"}
    admin = _user(tutor_app, "owner").get(f"{BASE}/knowledge").get_json()["plan"]["groups"]
    assert {i["id"] for g in admin for i in g["items"]} == set(registry.load_all())  # admin: setup + every permitted lesson


def test_a_user_without_permission_cannot_start_or_see_the_lesson(tutor_app):
    _enable(tutor_app)
    desk = _limited_user(tutor_app, ["clinics_patients"])
    assert desk.post(f"{BASE}/tutorials/invoice.create/start").status_code in (403, 404)
    assert desk.post(f"{BASE}/tutorials/permissions.manage/start").status_code in (403, 404)
    assert [t["id"] for t in desk.get(f"{BASE}/tutorials").get_json()["tutorials"]] == ["patient.create"]


def test_curriculum_slots_and_groups_are_validated():
    seen = {}
    for definition in registry.load_all().values():
        spec = definition.get("curriculum")
        assert spec, definition["id"]  # every lesson has a place in the curriculum
        assert (spec["group"], spec["order"]) not in seen
        seen[(spec["group"], spec["order"])] = definition["id"]
    assert {g for g, _ in seen} == {"setup", "operations", "collections"}


# ------------------------------------------------------------------------ privacy

def test_logs_keep_only_machine_tokens_never_free_text(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    _start(client, "patient.create")
    for detail in ("field:patient.name", "أحمد علي 07701234567", "name=Ahmed Ali", "x" * 200, ""):
        client.post(f"{BASE}/tutorials/patient.create/progress",
                    json={"event": "target_missing", "step_id": "name", "detail": detail})
        client.post(f"{BASE}/tutorials/patient.create/resume")
    details = [r.detail for r in TrainingActivityLog.query.filter_by(event="target_missing")]
    assert details == ["field:patient.name", None, None, None, None]


# ---------------------------------------------------------------------- lesson graph

def _definition(**extra):
    base = {"id": "x.one", "version": 1, "status": "verified", "title_ar": "واحد", "steps": [{"id": "d", "type": "complete", "message_ar": "ok"}]}
    base.update(extra)
    return base


def test_next_lessons_are_validated_and_filtered(monkeypatch):
    registry.validate_definition(_definition(next_lessons=["patient.create"]))
    for bad in ("patient.create", [1], [""]):
        with pytest.raises(registry.TutorialError, match="next_lessons"):
            registry.validate_definition(_definition(next_lessons=bad))
    monkeypatch.setenv("AI_TUTOR_ALLOW_DRAFT", "1")
    allow = lambda _perm: True
    deny = lambda _perm: False
    lesson = _definition(next_lessons=["patient.create", "doctor.create"])
    ids = [i["id"] for i in registry.next_lessons(lesson, allow)]
    assert ids == ["patient.create", "doctor.create"]
    assert [i["id"] for i in registry.next_lessons(lesson, allow, frozenset({"patient.create"}))] == ["doctor.create"]  # done already
    assert registry.next_lessons(lesson, deny) == []  # never recommend what the user may not do
    assert registry.next_lessons(_definition(next_lessons=["no.such"]), allow) == []


def test_curriculum_metadata_is_validated():
    registry.validate_definition(_definition(curriculum={"group": "setup", "order": 3}))
    for bad in ({"group": "other", "order": 1}, {"group": "setup"}, "setup"):
        with pytest.raises(registry.TutorialError, match="curriculum"):
            registry.validate_definition(_definition(curriculum=bad))


# ================================================================== Phase 8A: availability contract

def test_registry_level_availability_contract():
    plan = registry.get("treatment_plan.create")
    assert plan["availability"] == {"required_specialty": "dentistry"}
    for bad in (
        {"nope": 1}, {"required_pages": "staff"}, {"required_features": [1]}, {"required_specialty": ""},
        {"required_context": []}, {"required_context": [{"name": "nope", "op": "eq", "value": 1}]},
    ):
        with pytest.raises(registry.TutorialError, match="availability"):
            registry.validate_definition(_definition(availability=bad))
    registry.validate_definition(_definition(availability={"required_features": ["billing"]}))
    registry.validate_definition(_definition(availability={"required_context": [{"name": "doctors_count", "op": "gt", "value": 0}]}))


def test_availability_reason_distinguishes_permission_from_tenant_setup():
    plan = registry.get("treatment_plan.create")
    allow = lambda _p: True
    deny = lambda _p: False
    assert registry.availability_reason(plan, deny, {"dentistry_active": 1}) == "permission"
    assert registry.availability_reason(plan, allow, {"dentistry_active": 0}) == "specialty:dentistry"
    assert registry.availability_reason(plan, allow, {"dentistry_active": 1}) is None
    assert registry.availability_reason(plan, allow, None) == "specialty:dentistry"  # fail closed without facts
    assert registry.is_available(plan, allow, {"dentistry_active": 1}) is True
    assert registry.is_available(plan, allow, {"dentistry_active": 0}) is False


def test_treatment_plan_available_only_for_a_dental_tenant(tutor_app):
    _enable(tutor_app)
    client = _user(tutor_app)
    # No dental specialty yet: registered (it is in the registry) but not available, and not runnable by the API.
    assert "treatment_plan.create" not in [t["id"] for t in client.get(f"{BASE}/tutorials").get_json()["tutorials"]]
    assert client.post(f"{BASE}/tutorials/treatment_plan.create/start").status_code == 403
    assert "treatment_plan.create" not in {i["id"] for g in client.get(f"{BASE}/knowledge").get_json()["plan"]["groups"] for i in g["items"]}
    _dental_specialty(tutor_app)
    assert "treatment_plan.create" in [t["id"] for t in client.get(f"{BASE}/tutorials").get_json()["tutorials"]]
    assert client.post(f"{BASE}/tutorials/treatment_plan.create/start").status_code == 200


def test_chat_explains_unavailable_without_target_missing_or_a_fake_suggestion(tutor_app):
    from modules.ai_tutor.chat import context as chat_context

    _enable(tutor_app)
    tenant = tutor_app.config["IDS"]["tenant"]
    ctx = chat_context.build_context(tenant_id=tenant, user_id=tutor_app.config["IDS"]["owner"], role="admin",
                                     page=None, route=None, client_active=None, has_permission=lambda _p: True,
                                     permission_names=())
    assert ctx["unavailable_reasons"].get("treatment_plan.create") == "specialty:dentistry"
    from modules.ai_tutor.chat.service import answer

    non_dental = answer("شلون اسوي خطة علاج", ctx)
    assert non_dental["type"] == "explanation"
    assert "عيادات الأسنان" in non_dental["message"]
    assert not any(a["type"] == "start_tutorial" for a in non_dental["actions"])
    assert non_dental["tutorial_id"] is None  # never a runnable suggestion for an unavailable lesson

    _dental_specialty(tutor_app)
    ctx2 = chat_context.build_context(tenant_id=tenant, user_id=tutor_app.config["IDS"]["owner"], role="admin",
                                      page=None, route=None, client_active=None, has_permission=lambda _p: True,
                                      permission_names=())
    assert ctx2["unavailable_reasons"].get("treatment_plan.create") is None
    dental = answer("شلون اسوي خطة علاج", ctx2)
    assert dental["type"] == "tutorial_suggestion" and dental["tutorial_id"] == "treatment_plan.create"
