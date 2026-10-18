# Finora Phone — Call Recovery & Kill Semantics

## Single create path

```text
CallEventSource
      ↓
CallEventCoordinator
      ↓
CallStateMachine   ← call_status only
      ↓
LocalCallRepository
```

| Source | Role |
|--------|------|
| Telephony monitor | Primary live transitions |
| BroadcastReceiver | Secondary live events → **same** coordinator (no parallel row) |
| Android CallLog | Recovery/reconcile via secondary fingerprint + `local_call_uuid` |
| Active session | Restores note + `local_call_uuid` after process death |

Only the coordinator creates/updates the authoritative local call row.

## call_status vs sync_status

```text
Inbound:  detected → ringing → answered → ended
                       ↘ missed | rejected | failed

Outbound: detected → dialing → answered → ended
                       ↘ failed | cancelled

sync_status: pending | syncing | synced | failed | permanently_failed
```

`synced` is **not** a call_status.

## Idempotency

- Primary: `device_uuid:local_call_uuid` (UUID written to SQLite at first `detected`)
- Secondary (reconcile only): `normalized_phone|direction|started_bucket|device|sim`

## Kill / Force Stop

1. **Remove from Recents** — process may die; FG service / receivers may restart; CallLog reconcile on next open.
2. **System process kill** — same recovery path.
3. **Settings Force Stop** — Android typically blocks app components until the user opens the app manually. Diagnostics must warn; **do not claim** event delivery after Force Stop.
