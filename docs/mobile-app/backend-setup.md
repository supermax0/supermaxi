# Backend setup

1. Ensure tenant DB exists (`tenants/<slug>.db`).
2. Register module via `init_mobile_app` in `app.py` / `app_server.py`.
3. Schema auto-creates on first mobile API / admin hit (`schema_guard`).
4. Optional env (see `.env.example`):

```text
MOBILE_SMS_WEBHOOK_URL=
MOBILE_SMS_API_KEY=
MOBILE_PUSH_WEBHOOK_URL=
MOBILE_PUSH_API_KEY=
MOBILE_OTP_DEBUG_RETURN_CODE=True   # local/testing only
```

5. Admin: login as Finora staff → sidebar «تطبيق الهاتف» → `/mobile-app/`.

## Health

`GET /api/mobile/v1/health` with `X-Tenant-Slug`.
