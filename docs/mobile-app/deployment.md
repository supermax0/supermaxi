# Deployment notes

1. Deploy Finora web with `modules/mobile_app` registered.
2. Ensure media write path for video uploads is writable per tenant.
3. Optional: Celery worker for video processing (`modules/mobile_app/tasks`).
4. Configure SMS/Push webhooks.
5. Ship Flutter APK/IPA pointing at production API + tenant slug.
6. Do not enable OTP debug code return in production.
