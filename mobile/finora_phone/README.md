# Finora Phone (Phase 1) — Companion CRM Overlay

Enterprise business phone companion for Finora ERP.

## Role

- Stock Android Phone app answers/rejects calls.
- Finora Phone shows CRM overlay + offline-first tools.
- Architecture is ready to swap in `InCallService` later via `CallEventSource`.

## Run Flutter

```bash
cd mobile/finora_phone
flutter pub get
flutter run --dart-define=API_BASE_URL=https://www.finora.company --dart-define=TENANT_SLUG=your_tenant
```

## Backend

Registered at `/api/phone/v1/*` (see `modules/phone_app/`).

```bash
flask phone-db upgrade --tenant YOUR_TENANT
flask phone-db upgrade-all
flask phone-db current --tenant YOUR_TENANT
flask phone-db downgrade --tenant YOUR_TENANT --to 1
```

Open routes are exempt from staff session login in `app.py`.

## Field Test APK (staging)

```bash
flutter build apk --flavor staging --release ^
  --dart-define=FLAVOR=staging ^
  --dart-define=API_BASE_URL=https://YOUR_STAGING_HOST ^
  --dart-define=TENANT_SLUG=YOUR_TENANT
```

See `PHASE_1_5_FIELD_CHECKLIST.md` and `docs/CALL_RECOVERY.md`.

## Permissions

Phone state, call log, overlay, notifications — guided by in-app wizard.
