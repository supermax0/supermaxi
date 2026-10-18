# Clinic core learning journey (Phase 7)

Thirteen lessons teach the real clinic workflow, each one written **after reading the real implementation** (template, JS, modal, API, validation, permission, DB effect) and
completed only when the **server** says the thing exists. Nothing is guessed from page names.

## Lessons, where they start and what proves them

| Lesson | Starts at | Real UI used | Backend proof (`modules/ai_tutor/validators.py`) | Permissions |
|---|---|---|---|---|
| `specialty.create` | Specialties | `clinics.js` modal | specialty created since start | `clinics_admin` |
| `doctor.create` | Doctors & staff | `staff.js` form | doctor created since start | `clinics_admin` |
| `doctor.schedule` | Work schedules | `clinics.js` shift modal | `ClinicDoctorSchedule` created since start | `clinics_admin` |
| `employee.create` | Doctors & staff | same form, **non-doctor** role | `Employee` created since start, role `clinic_*`, not `clinic_doctor`, not linked to a doctor | `clinics_admin` |
| `permissions.manage` | Doctors & staff | edit modal: role + 5 permission groups | audit trail: `clinic_staff` / `update` since start | `clinics_admin` |
| `service.create` | Services | `services.js` form | `ClinicService` created since start (linked to a specialty, or it never shows when booking) | `clinics_admin` |
| `patient.create` | Patients | `patients.js` modal | `ClinicPatient` created since start | `clinics_patients` |
| `appointment.create` | Appointments | form in `clinics.js` (search + pick patient, doctor, date, time) | `ClinicAppointment` created since start | `clinics_appointments` |
| `appointment.checkin` | Appointments → appointment card → drawer | "تسجيل وصول" | status history `to_status = arrived` since start | `clinics_appointments`, `clinics_reception` |
| `queue.add` | same drawer | "إضافة للانتظار" | status history `to_status = waiting` since start | same |
| `visit.start` | same drawer | "إدخال للطبيب" | `ClinicVisit` **from an appointment** created since start | + `clinics_visits` |
| `treatment_plan.create` | Visits → open visit → "العلاج" tab (dentistry) | plan modal, then "+ علاج عام" item form | plan **and** first item created since start | `clinics_clinical`, `clinics_visits` |
| `invoice.create` | same tab, "إنشاء فاتورة" | `dtp` invoice modal (full / selected / custom) | `ClinicInvoice` created since start (nothing is paid) | `clinics_billing`, `clinics_clinical`, `clinics_visits` |

Facts the reading established (and the lessons say):
* **Check-in and the queue are two different steps** in the real system: "وصل" (`arrived`) then "ينتظر" (`waiting`). They are two lessons, never merged.
* The employee form can create a **doctor** if the role is "طبيب"; the employee lesson tells the person not to pick it and the validator rejects doctor accounts.
* The treatment plan exists only for **dentistry** visits (`isDental` in `doctor.js`). The lesson says so ("لزيارات الأسنان"); a clinic without a dental visit gets the honest "target not found" recovery.
* An appointment placed at a time that is not on the slot grid (09:00, 09:30 …) is **not drawn in the desktop day grid** (it is only in the agenda list). The time step says to choose a slot-aligned time.
* The doctor is not required by the appointment API, but check-in/queue/visit need one: the lesson asks for it. A doctor with **no schedule for a weekday is open all day**; the schedule step says so.
* Payment, refund, void and accounting posting are **not taught anywhere**: a test asserts no lesson targets or calls anything containing `pay|refund|void|posting`.

## Dependencies (data-driven, any depth)

`dependencies` in a lesson are *facts* (`modules/ai_tutor/facts.py`) plus the lesson that fixes them. The engine re-checks them every time a lesson (re)starts, so chains of any depth work with no hard-coded order:

```
appointment.create ─ patients_count>0 → patient.create
                   └ doctors_count>0 → doctor.create ─ specialties_count>0 → specialty.create
appointment.checkin ─ appointments_scheduled_today>0 → appointment.create
queue.add           ─ appointments_arrived_today>0   → appointment.checkin
visit.start         ─ appointments_waiting_today>0   → queue.add
treatment_plan.create ─ open_visits_count>0          → visit.start
invoice.create      ─ treatment_items_count>0        → treatment_plan.create
permissions.manage  ─ staff_accounts_count>0         → employee.create
doctor.schedule     ─ doctors_count>0                → doctor.create
service.create      ─ specialties_count>0            → specialty.create
```
When a dependency finishes the parent resumes from its saved step and `reconcileTutorialState()` skips the steps the real screen already proves (page open, form visible, backend result). Verified in the browser: `appointment → doctor → specialty → doctor → appointment` on an empty clinic, and a four-level stack `visit.start → queue.add → appointment.checkin → appointment.create` (no lost progress, no duplicate records).

## Next-lesson graph (recommendation only)

`next_lessons` in the lesson JSON: `doctor.create → doctor.schedule`, `patient.create → appointment.create`, `appointment.create → appointment.checkin`, `appointment.checkin → queue.add`, `queue.add → visit.start`, `visit.start → treatment_plan.create`, `treatment_plan.create → invoice.create`, `employee.create → permissions.manage`.
The completion card shows "ابدأ: <lesson>" buttons built from `/tutorials/<id>/complete` (`registry.next_lessons`: only lessons that are runnable, permitted and not completed). The next lesson **never starts by itself**.

## Curriculum (generated from the registry)

`curriculum: {group, order}` in each lesson and the group titles in `knowledge/plan.json`:

* **إعداد العيادة**: إضافة اختصاص، إضافة طبيب، جدول الدوام، إضافة موظف، إدارة الصلاحيات، إضافة خدمة
* **تشغيل العيادة**: إضافة مريض، حجز موعد، تسجيل الحضور، قائمة الانتظار، بدء الزيارة، خطة العلاج، إنشاء فاتورة

`GET /knowledge` returns only lessons that **exist and that this user may run** (permissions, never the role name): reception sees patients/appointments/check-in/queue; a clinician sees visits and treatment plan; an admin sees everything. A group with no lessons is not shown; there is no "coming later" list.

## Chat

Every lesson is reachable from the chat through `knowledge/features.json` (no chat code per lesson). Iraqi aliases are in the registry; ambiguity is tested (`اضيف`, `اضيف حساب`, `زيارة`, `وصل` ask which lesson). Two fixes found while doing this: "خطة علاج" used to be refused as medical advice (the medical guard now yields to a clearly matching feature), and tie-breaking prefers the lesson's own entry.

## Privacy

Training logs store only `tutorial_id`, `step_id`, `event`, timestamps and **short machine tokens** in `detail` (`[A-Za-z0-9_.:-]{1,80}`; anything else is dropped server-side). A browser test types a patient name and phone and then greps the whole progress/log tables for them.

## Target resolution speed (mobile start)

`static/ai-tutor/engine/targets.js › acquireTarget` is now: immediate query → known reveal strategy at once when the target is in the DOM but hidden (closed drawer / collapsed group) → next animation frame → short observer wait (reveals re-tried when the target appears hidden) → final timeout recovery. Per-frame checks for the first 40 frames, then every 200 ms (no aggressive polling).
Measured start → first card on mobile (390x800): **4 893 ms before, about 920 ms after** (`doctor.create`: 1 015 / 977 / 965 ms; `patient.create` 916-930 ms). The 2.5 s fixed wait only remains for targets that genuinely have to render.

## Phone layout fixes found by the mobile E2E
* The bottom sheet covered a modal's fixed **Save** button. The sheet now docks to the **top** when the target sits under the bottom edge and cannot scroll away (`sheetEdge` in `positioner.js`, unit-tested); tall targets that are still half visible keep the bottom sheet.
* The floating assistant button covered **Save** too; while a form modal is open on a phone it is hidden (`tutor.css`, only when the tutor is on).

## Test data and isolation
`scripts/tutor_e2e_fixture.py` (`reset [--features]`, `enable`, `strip`, `clear-patients`, `logs`) only touches the provisioned E2E tenants and refuses any other slug. Specs create their own fixtures through the real clinic API, switch the feature through the Super Admin API (which also invalidates the server's feature cache) and clean what they made. The system-map spec resets its own snapshot directory through a test-only endpoint (`POST /superadmin/ai-tutor/system-map/reset`, only when `AI_TUTOR_ANALYZER_SIMULATION=1` or `TESTING`). No spec depends on running order or on a pre-emptied directory.

## Running it
```bash
python scripts/provision_tutor_e2e.py setup <creds.json>      # tenants a, b (seeded) and c (stripped by its spec)
FLASK_PORT=5059 AI_TUTOR_ASK_PER_USER=30 AI_TUTOR_ANALYZER_SIMULATION=1 AI_TUTOR_SYSTEM_MAP_DIR=<tmp> python app.py
E2E_TUTOR_CREDS=<creds.json> PLAYWRIGHT_BASE_URL=http://127.0.0.1:5059 PW_HEADLESS=1 npx playwright test tests/ai-tutor --workers=1
python -m pytest tests/test_ai_tutor_journey.py tests/test_ai_tutor_chat.py tests/test_ai_tutor_backend.py tests/test_system_analyzer.py
python scripts/analyze_ai_tutor.py           # CI: fails only when a verified lesson is broken
```
Lessons start as `draft` (visible only with `AI_TUTOR_ALLOW_DRAFT=1`) and are switched to `verified` only after unit validation, backend verification, a real browser run and a successful full flow.

## Phase 8A: availability contract (registered / available / verified)

Three distinct concepts, never conflated:

* **registered** — a tutorial JSON exists in `modules/ai_tutor/tutorials/` and passed `registry.validate_definition`. `registry.get(id)` returns it. Says nothing about whether anyone can run it.
* **available** — `registry.is_available(definition, has_permission, facts)`: `is_runnable` (status `verified`, and not withheld as analyzer-broken) **and** `requires_permissions` **and** the `availability` contract below, evaluated for *this* tenant and *this* user.
* **verified** — the lesson's declared `status` (set by hand, only after a real browser run); independent of availability.

A lesson can declare, under `"availability"` (separate from `requires_permissions`, which is about the *user*):
```json
"availability": {
  "required_specialty": "dentistry",
  "required_permissions": ["..."],
  "required_features": ["billing"],
  "required_pages": ["billing"],
  "required_context": [{"name": "open_visits_count", "op": "gt", "value": 0}]
}
```
`registry.availability_reason(definition, has_permission, facts)` returns `None` when available, else the single reason the chat trusts verbatim: `"permission"`, `"specialty:<code>"`, `"feature"`, `"page"`, `"context"`, or `"unavailable"` (not runnable at all). **Nothing is hardcoded in the chat** — it only ever asks the registry for this reason and picks a message:
* `"permission"` → "ما عندك صلاحية تنفيذ هذه العملية." (unchanged from Phase 6/7).
* any other reason → the lesson's own `unavailable_ar` text from `knowledge/features.json` (e.g. treatment_plan.create: "خطة العلاج الحالية متاحة لعيادات الأسنان في هذه النسخة."), or a generic fallback. Never a `start_tutorial` action, never `target_missing`.

`treatment_plan.create` is the first (and currently only) lesson with `availability.required_specialty: "dentistry"`, checked against the new fact `dentistry_active` (`collect_facts`: an active `ClinicSpecialty` with code `dentistry`/`dental`). Every entry point that lists or starts tutorials now threads the tenant's `facts` through `is_available`/`availability_reason`: `/tutorials`, `/active`, `/knowledge`, `/onboarding`, `start`/`progress`/`verify`/`complete`/`resume` (via `_definition_or_error`), and the next-lesson recommendation on the completion card. `required_features`/`required_pages` exist as real, generically-checked mechanisms (`AVAILABLE_FEATURES`, the static page list) for future lessons — not dead parameters — even though every known feature/page is available today.
