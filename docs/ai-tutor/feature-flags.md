# Feature flags (Finora AI Tutor)

Effective state = **global switch** AND **tenant row enabled** AND **not expired**. No row = DISABLED. Nothing in code or migrations ever creates an enabled row.

## Backend

```python
from services import feature_service as fs

fs.is_enabled_for_slug(slug, fs.AI_TUTOR)       # effective, cached 15 s
fs.set_feature(slug, key, enabled=True, expires_at="2026-11-01", actor="root#1", ip=ip)
fs.bulk_set_feature([slugs], key, enabled=True, actor=..., ip=...)   # atomic
fs.set_global_enabled(key, False, actor=...)    # emergency kill switch

@features_api_bp.get("/api/clinic/ai-tutor/...")
@fs.require_feature(fs.AI_TUTOR)                # 401 AUTH_REQUIRED / 403 {"error":"FEATURE_NOT_ENABLED","feature":...}
```

Adding a feature = one entry in `FEATURE_REGISTRY` (label, description, default configuration keys; all booleans).

## Templates / JS

`{% if feature_enabled('clinic_ai_tutor') %}` hides UI only; `GET /api/features/me` returns `{"features": {key: bool}}` for the logged-in tenant. Backend gate is always authoritative. The helper fails closed.

## Super Admin API (`platform.features.manage`, Super Admin session only; others get 403)

| Method | Path |
|---|---|
| GET | `/superadmin/features/registry` |
| GET | `/superadmin/features/<key>/overview?state=all\|enabled\|disabled\|expired&q=` |
| GET | `/superadmin/features/tenants/<slug>` |
| PATCH | `/superadmin/features/tenants/<slug>/<key>` — `{enabled, expires_at (YYYY-MM-DD\|null), configuration}` |
| POST | `/superadmin/features/<key>/bulk` — `{slugs[], enabled, expires_at}` |
| PUT | `/superadmin/features/<key>/global` — `{enabled}` |
| GET | `/superadmin/features/<key>/audit?slug=&limit=` |

Rules: enabling requires a future expiry (or permanent); re-enabling an expired row needs an explicit new expiry; configuration keys/values are validated; every change writes `feature_audit_logs` (`ENABLED`, `DISABLED`, `EXPIRY_CHANGED`, `CONFIG_CHANGED`, `GLOBAL_ENABLED/DISABLED`) with actor and IP. Repeating a no-op writes nothing.
