# FINORA Clinics — Known Limitations (canonical)

**Product:** FINORA Clinics 1.0 RC1  
**Schema (internal):** `clinics-v26-cardiology-clinical-tools`  
**Updated:** 2026-09-05

This is the single registry of **non-blocking** limitations. They are **not bugs**.

---

## Dentistry

- Advanced per-surface SVG odontogram rendering beyond current chart
- Full graphical treatment simulation

## Pediatrics

- WHO/CDC growth percentiles (raw growth history only)
- National vaccine schedule engine
- Automatic developmental scoring / screening tools

## Gynecology / Obstetrics

- Pregnancy risk scoring
- Fetal growth percentiles / ultrasound interpretation
- Drug-in-pregnancy safety checker

## Internal Medicine

- Clinical decision support
- Automatic CKD staging / diabetes or hypertension control classification
- Drug interaction engine / dose calculators

## Cardiology

- ASCVD / Framingham / CHA2DS2-VASc / HAS-BLED / HEART / TIMI / GRACE
- Automatic ECG or Echo interpretation / EF auto-classification
- Holter analytics / device interrogation

## Infrastructure / Integrations

- WhatsApp delivery depends on configured provider; clinical saves must not roll back on notify failure
- Large-tenant performance targets assume proper PostgreSQL sizing/pooling
- Advanced multi-branch analytics beyond current branch model
- Long full-suite Playwright + SQLite specialty browser smoke can intermittently time out on patient-profile specialty mounts under machine load; re-run `tests/test_clinics_specialty_browser_smoke.py` in isolation when that happens (pilot/production use PostgreSQL)

---

## Language rule

UI and docs must **not** advertise unavailable features (e.g. do not label raw growth history as “WHO Growth Chart”).
