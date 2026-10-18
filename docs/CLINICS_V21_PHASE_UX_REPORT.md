# Phase UX Report — Clinics Simplification

Date: 2026-09-04
Base: clinics-v23-pediatric-clinical-tools (post Phase D)
Schema: unchanged (`clinics-v23-pediatric-clinical-tools`)

## Routes Audited
Dashboard, reception, appointments, queue, display, patients, patient_detail, visits, doctor, clinical, labs, radiology, followups, procedures, billing, expenses, cash, settlements, inventory (+movements/batches/expiry), suppliers, purchases, doctors, specialties, schedules, services, rooms, communications, reports, settings, attachments.

## Routes Reclassified
- Inventory movements / batches: removed from sidebar; remain deep-linkable and inside Inventory UI.
- Attachments / suppliers / communications / reports / settings: moved under «المزيد».
- Clinical registry moved under «الطبي» with labs/radiology/procedures/followups.
- Specialty tools (dental / pediatrics): remain contextual only (Doctor Workspace + Patient Profile). No new sidebar items.

## Sidebar Before
~28 flat links including inventory movements/batches, mixed admin into daily ops.

## Sidebar After
Grouped IA: التشغيل اليومي · المرضى · الطبي · المالية · المخزون · الإدارة · المزيد.  
Role-filtered via `bootstrap.nav` + `static/clinics/nav.js`. Collapsible groups with persona-default collapse for admin/more/inventory.

## Role Navigation
Owner: full grouped nav; inventory subpages hidden; admin/more collapsed by default.  
Doctor (linked doctor, even with clinics_admin): visits/patients/clinical focus; hides reception, inventory, purchases, admin, cash/settlements.  
Reception: ops + patients + billing; hides clinical registry, inventory, admin, rooms/settlements in solo.  
Other Roles: staff fallback — permission-only visibility.

## Patient Profile Changes
Hub tabs: نظرة عامة · المواعيد والزيارات · السجل السريري · العلاج والمتابعة · الملفات · المالية.  
Sub-tabs for clinical sections (timeline, Rx, labs, radiology, dental, pediatrics) and treatment (procedures, followups). Specialty tools remain subsections, not top-level peers.

## Doctor Workspace Changes
Renamed primary tabs (الزيارة / الفحص / العلاج / الوصفة / الفاتورة). Quick-action strip jumps to tabs + patient prior record. Specialty panels unchanged.

## Dashboard Changes
No dashboard rewrite; topbar chips are role-aware (reception/display/patient/visit).

## Tables / Filters
Deferred depth cleanup; no table API changes. Empty loading copy retained.

## Mobile Navigation
≤4 persona-driven primary items + menu; rebuilt from `nav.mobile` after bootstrap.

## RTL
Workspace remains `dir="rtl"`; no LTR regressions introduced in shell IA.

## Performance
One bootstrap field (`nav`) added; no extra round-trips.

## Browser E2E
Automated role matrix covered in `tests/test_clinics_nav_ux.py` (persona + markup). Live browser role login not automated in this pass — verify manually for owner/doctor/reception if needed.

## Modified Files
- `docs/CLINICS_UX_AUDIT.md`
- `docs/CLINICS_V21_PHASE_UX_REPORT.md` (this report)
- `modules/clinics/service_dashboard.py` (`build_nav_matrix`)
- `modules/clinics/routes.py` (bootstrap `nav`)
- `templates/clinics/workspace.html`
- `static/clinics/nav.js` (new)
- `static/clinics/clinics.js`
- `static/clinics/clinics.css`
- `static/clinics/patient-profile.js`
- `tests/test_clinics_nav_ux.py`

## Database Changes
None.

## Tests
`tests/test_clinics_nav_ux.py` — owner/doctor/reception/solo/markup/hub assertions.

## Regression
`pytest tests -k "test_clinics_"` → **174 passed**, 1 failed (`test_live_scenario10_manage_reschedule_and_cancel` — booking live E2E time slot `09:00` vs `09:30`, unrelated to UX nav).

## Known Limitations
- Dashboard content cards not yet persona-sliced beyond existing API scopes.
- Advanced table filter drawers not rolled out globally.
- Inventory movements remain URL-addressable (intentional).
- UI hide ≠ security: route guards unchanged.

## UX Before/After Summary
Before: dense equal-weight sidebar, role-blind top/mobile nav, patient profile with 12+ peer tabs.  
After: grouped IA, persona presets, Patient Hub + Doctor quick actions, specialty tools stay contextual, zero schema churn.
