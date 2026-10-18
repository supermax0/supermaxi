# Finora Phone — Phase 1.5 Field Validation Checklist

**Status:** READY FOR FIELD VALIDATION  
Phase 1.5 code hardening is accepted; **not complete** until a full company-phone workday passes the metrics below.

## Correct acceptance phrasing

> لا يفقد التطبيق أي حدث مكالمة يسمح Android والجهاز للتطبيق بالوصول إليه، ويتم اكتشاف الفروقات عبر المصالحة مع Android CallLog.

Do **not** guarantee “never miss any call” absolutely.

## Backend migrations (no `db.create_all` for phone schema)

```bash
# From project root with venv activated
set FLASK_APP=app.py

flask phone-db upgrade --tenant YOUR_TENANT
flask phone-db upgrade-all
flask phone-db current --tenant YOUR_TENANT
flask phone-db downgrade --tenant YOUR_TENANT --to 1
flask phone-db downgrade --tenant YOUR_TENANT --to 0

# Tests
./venv/Scripts/python.exe -m pytest modules/phone_app/tests -q
```

Schema includes: `phone_app_devices`, call `call_status` + `sync_status`, `local_call_uuid`, `idempotency_key`, `device_id`, `sim_slot`, indexes/unique constraints, `phone_order_draft` (draft→confirmed).

## Field Test APK build (staging — not production)

```bash
cd mobile/finora_phone
flutter pub get

# Debug Field Test
flutter build apk --flavor staging --debug ^
  --dart-define=FLAVOR=staging ^
  --dart-define=API_BASE_URL=https://YOUR_STAGING_HOST ^
  --dart-define=TENANT_SLUG=YOUR_TENANT

# Release Field Test (still staging API)
flutter build apk --flavor staging --release ^
  --dart-define=FLAVOR=staging ^
  --dart-define=API_BASE_URL=https://YOUR_STAGING_HOST ^
  --dart-define=TENANT_SLUG=YOUR_TENANT

# Output typically:
# build/app/outputs/flutter-apk/app-staging-debug.apk
# build/app/outputs/flutter-apk/app-staging-release.apk
```

App label: **Finora Phone Field Test** (`iq.finora.phone.staging`).

Diagnostics (dev/staging only): Sync / API / Overlay / Customer Lookup / Local Notification / Force Stop warning / **Field Day Report** / Export report. **No mock data on production call paths.**

## Flutter checks

```bash
cd mobile/finora_phone
flutter test
dart analyze lib
```

## Call architecture (single create path)

```text
CallEventSource (Telephony | Receiver | CallLog | ActiveSession)
      ↓
CallEventCoordinator
      ↓
CallStateMachine   (call_status only)
      ↓
LocalCallRepository
```

Idempotency primary: `device_uuid:local_call_uuid` (UUID persisted at first detected).  
Secondary reconciliation fingerprint only: phone|direction|bucket|device|sim.

### Kill vs Force Stop

| Case | Expected |
|------|----------|
| Swipe from Recents | Process may die; service/receivers can restart; CallLog reconcile on open |
| System process kill | Same as above |
| **Settings Force Stop** | Android blocks receivers until user opens app manually — **no delivery guarantee** |

## Day-one field scenarios

### Setup
- [ ] Clean install / login / grant permissions / deny then grant
- [ ] Reboot / Battery Saver on+off / Wi-Fi / Mobile Data / offline

### Calls
- [ ] 10 inbound known / 10 inbound new / 5 missed / 5 rejected / 5 outbound
- [ ] 2 consecutive same number / 2 within <1 min
- [ ] Lock screen / Finora open / other app / offline / during outbox sync
- [ ] After Recents swipe / after reboot / Dual SIM if available
- [ ] **Separately document Force Stop** (expect no events until manual open)

### Data
- [ ] Note during call / task / **Draft Order only** / close before sync / cut network / reboot / reconnect → **once**

## Acceptance metrics (export from Diagnostics)

| Metric | Target |
|--------|--------|
| Missing vs Android CallLog (reachable cases) | 0 |
| Duplicate calls | 0 |
| Duplicate orders/invoices | 0 |
| Lost notes / tasks | 0 |
| Permanently failed (normal day) | 0 |
| Overlay covers answer/reject | never |
| P95 number_shown_ms | < 500 |
| P95 local_crm_ms | < 800 |
| Crash blocking service | 0 |
| Battery | acceptable workday |

Also track: total detected, CallLog count, local/server counts, overlay shown/failed, sync success rate, outbox retries, service restarts.

## Constraints report (final day report must separate)

1. App-fixable bugs  
2. General Android limits  
3. OEM limits  
4. Permission limits  
5. Test-device-specific limits  

## Out of scope (do not start)

Recording · AI · Queue · Advanced Reports
