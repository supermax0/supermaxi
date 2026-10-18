# Finora AI Tutor — Phase 0 Analysis

## Architecture discovered

| Layer | Finding |
|---|---|
| Backend | Flask (Python 3.11), Flask-SQLAlchemy. Entry points `app.py` **and** `app_server.py` register blueprints separately (every new blueprint must be added to both). |
| Frontend | Server-rendered Jinja templates + vanilla JS (`static/js`). No React/TypeScript build. The brief's `useFeature()` therefore maps to the Jinja helper `feature_enabled()` and `GET /api/features/me`. |
| Database | **Core DB** (`tenants`, `super_admins`, `global_settings`, `subscription_plans`, leads…) + **one SQLite DB per tenant** (`tenants/<slug>.db`). `extensions.DynamicTenantSession.get_bind()` picks the engine from `g.tenant`; `g.tenant = None` means Core. |
| Tenant identity (request) | `session["tenant_slug"]` → Core `tenants.slug` (`models/core/tenant.py`). Inside a tenant DB the row is `models/tenant.py::Tenant` (different id space). Clinics code uses `session["tenant_id"]` (tenant-DB id). |
| Super Admin | `routes/superadmin.py` (`/superadmin/*`), session flags `is_superadmin` + `superadmin_id`, guarded by a blueprint `before_request`. Company list = `templates/tenant_list.html` (modal with tabs). |
| RBAC | Per-employee role/permissions (`models/employee.py`, `modules/clinics/guards.py::CLINICS_PERMISSIONS`, `can_use_clinics`). Admin role bypasses. |
| Clinics | `modules/clinics/` (`routes.py` blueprint `/clinics`, ~40 `service_*.py`, schema guard, dental platform). Business type `clinics`. |
| Existing feature system | `Tenant.feature_overrides_json` (tenant DB) + `utils/tenant_feature_flags.py`: page-visibility toggles, **default ON**, edited at `/superadmin/tenants/update-features/<slug>`. Not audited, no expiry, lives in the tenant DB. |
| Tests | pytest (`tests/`, in-memory SQLite Flask apps) + Playwright (`playwright.config.js`, `tests/**/*.spec.js`). |
| Logging | `current_app.logger`, `ActivityLog` per tenant. No platform-level audit table existed. |

## Decision: new generic feature system in the Core DB

The legacy overrides cannot satisfy the brief (default OFF, audit, expiry, Super-Admin-only, global kill switch, listing across tenants without opening every tenant DB). They were left untouched. New tables live in Core:

- `tenant_features` (unique `tenant_id + feature_key`), `feature_audit_logs`.
- Kill switch stored in existing `global_settings` as `<feature_key>_global_enabled` (absent = ON; the tenant flag must still be ON).

All reads/writes use a dedicated `Session(bind=db.engine)`, so results never depend on `g.tenant` and tenant code has no write path.

## Relevant files

- `models/core/feature.py`, `services/feature_service.py` (single source of truth)
- `routes/superadmin_features.py` (admin API), `routes/features_api.py` (tenant API + template helper)
- `routes/superadmin.py::tenants_list`, `templates/tenant_list.html`, `static/js/superadmin_features.js`
- `tests/test_feature_management.py`

## Recommended integration for later phases

1. UI metadata (`data-finora-*`) on `templates/clinics/*` — Phase 2.
2. Load the tutor bundle only when `feature_enabled('clinic_ai_tutor')` is true in `base` clinic template (lazy `<script>` injection).
3. Every tutor endpoint under `/api/clinic/ai-tutor/*` uses `@require_feature(AI_TUTOR)`.
4. Per-user progress keyed by `(tenant_slug, user_id)` in the tenant DB (progress belongs to the tenant's data).

## Risks

- **Per-process cache** (15 s TTL, invalidated immediately in the process that handled the admin write). With several gunicorn workers another worker can serve a stale answer for up to 15 s. Expiry is also bounded by that TTL.
- Two entry points (`app.py`/`app_server.py`) must stay in sync.
- Shared `db.Model.metadata` means `init_tenant_db` also creates empty `tenant_features`/`feature_audit_logs` tables inside tenant DBs (same as `global_settings`); they are never read.
- Unauthenticated tenant API calls are redirected to login by `app.require_login` (302) instead of 401; still denied.
- The working tree already contained many uncommitted changes (including `app.py`, `app_server.py`, `routes/superadmin.py`, `templates/tenant_list.html`) when this work started; Phase work was not committed so those changes are not bundled into a feature commit.
