# Clinics Pilot Onboarding Checklist

**Product:** FINORA Clinics 1.0 RC1  
**Schema:** `clinics-v26-cardiology-clinical-tools`  
**Use:** before each pilot clinic goes live  
**Live tracker:** `docs/CLINICS_LIVE_PILOT_EXECUTION.md`

---

## A. Infrastructure (once per environment)

- [ ] HTTPS terminated correctly
- [ ] Production PostgreSQL (not SQLite)
- [ ] `FLASK_ENV` / DEBUG not development
- [ ] `SECRET_KEY` strong and unique
- [ ] Pool / timezone documented
- [ ] Automated daily backup scheduled (`scripts/backup_database.ps1`)
- [ ] `backups/daily/last_backup_status.json` shows `SUCCESS`
- [ ] Restore drill into disposable DB completed
- [ ] `GET /clinics/api/health` returns `ok: true`
- [ ] Monitoring for 5xx / job failures enabled
- [ ] Preflight: `py scripts/clinics_pilot_preflight.py` → PASS

## B. Tenant provisioning (per clinic)

Use product UI / existing setup flows — avoid manual SQL.

- [ ] Tenant created (`business_type = clinics`)
- [ ] `organization_mode`: solo / multi_doctor / medical_center
- [ ] Clinic name, logo, invoice header
- [ ] Timezone confirmed with owner
- [ ] Specialties enabled for this clinic only
- [ ] Doctors + schedules + rooms (if used)
- [ ] Services + prices
- [ ] Users with real RBAC (Owner / Doctor / Reception / Accountant as needed)
- [ ] Public booking settings (on/off, OTP, notice windows)
- [ ] WhatsApp/communications only if configured
- [ ] Starting inventory quantities (if inventory used)

## C. First-day smoke (clinic staff)

- [ ] Register / find patient
- [ ] Book appointment → check-in → queue
- [ ] Open Doctor Workspace → vitals → Rx → complete → invoice → payment
- [ ] Specialty pack used if enabled (Dental / Ped / Gyn / IM / Cardiology)
- [ ] Print invoice / prescription once on clinic hardware
- [ ] Public booking one real slot (if enabled)

## D. Safety briefing

- [ ] Staff know growth charts are **history**, not WHO percentiles
- [ ] Staff know ECG/Echo fields are **clinician-entered**, not auto-read
- [ ] No admin-for-everyone shortcuts

## E. Support

- [ ] Log issues in `docs/CLINICS_PILOT_ISSUES.md` (no patient identifiers)
- [ ] Classify P0–P4 per Phase I rules
