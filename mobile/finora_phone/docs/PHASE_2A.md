# Phase 2A — Timeline + Call Outcomes + Advanced Search + Smart Follow-up

**Version target:** extend Finora Phone beyond 1.0.11  
**Scope:** implemented on existing Companion Overlay architecture (no Telecom changes).

## Delivered

### Feature Flags
- Bootstrap emits Phase 2A flags (`phone_timeline_enabled`, `phone_call_outcomes_enabled`, `phone_advanced_search_enabled`, `phone_smart_followup_enabled` = true; voice/suggestions/supervisor = false).
- Server gates return `403 feature_disabled`.
- Flutter `FeatureFlagsController` caches flags via secure storage.

### Migration v3
- `phone_call_log`: outcome fields + indexes.
- `phone_followup_task`: priority, reason, resolved_by_call_id, snoozed_until.
- Upgrade/downgrade registered in `modules/phone_app/migrations`.

### Call Outcomes
- Catalog + validation rules in `services/call_outcomes.py`.
- `POST /api/phone/v1/calls/<id>/outcome` with idempotency (`outcome_client_id`) + audit.
- `GET /api/phone/v1/calls/unclassified`.
- After-call UI + Unclassified Calls page; offline local save + outbox `set_call_outcome`.

### Smart Follow-up
- Missed coalesce + attempt_count; resolve on answered.
- Outcome-driven callback/complaint tasks.
- Priority heuristic; task filters; snooze.

### Timeline
- Aggregation service (no denormalized table).
- Unified `items[]` + cursor pagination.
- Flutter customer detail timeline with day grouping + load more + offline merge.

### Advanced Search
- `GET /api/phone/v1/search`.
- Flutter Advanced Search page (debounce 300ms, recent searches, typed groups).

## Out of scope (unchanged stubs)
Recording, AI, Voice notes, Heat/Tags, Supervisor, Queue, Default Dialer, Advanced Reports.

## Commands

```bash
flask phone-db upgrade --tenant YOUR_TENANT
pytest modules/phone_app/tests -q
cd mobile/finora_phone && flutter analyze lib
flutter build apk --flavor staging --release --dart-define=FLAVOR=staging --dart-define=API_BASE_URL=https://www.finora.company --dart-define=TENANT_SLUG=super
```

## Known limitations
- Outcome sync requires `server_id` on the local call row; until the call is synced, outcome stays local + unclassified path can classify later.
- Partial unique open-task constraint is enforced in service layer (SQLite-friendly).
- Branch filtering on search depends on invoice.branch_id when provided.
