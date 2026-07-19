# Security

## Tenant isolation
Every mobile request binds `g.tenant` from `X-Tenant-Slug`. Access tokens embed tenant slug; mismatch → `403 tenant_mismatch`.

## Auth
OTP + itsdangerous access tokens + hashed refresh sessions. Deactivated / banned users cannot use tokens (`user_inactive`). Delete-account revokes all sessions.

## Rate limits
In-process limits (`services/rate_limit.py`) on:
- OTP request / verify
- order creation
- AI messages

OTP also has its own persistence-backed throttle in `services/otp.py`.

## Staff gates
Admin APIs require Finora employee session (or `X-Test-Staff-Id` only when `TESTING`). Permissions under `mobile_app.*`.

## Analytics
Allow-listed event names; batch max 50; property JSON capped.

## Providers
Default SMS/Push log providers — production must configure webhook URLs; never enable `MOBILE_OTP_DEBUG_RETURN_CODE` in production.
