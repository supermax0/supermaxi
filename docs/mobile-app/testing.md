# Testing

```bash
.\venv\Scripts\python.exe -m pytest modules/mobile_app/tests/ -q
```

Coverage includes auth/OTP, feed engagement, comments, catalog, cart/orders, rewards, AI, phase8, admin UI, profile/search, security/rate-limit.

Tests wipe dedicated `tenants/test_mobile_*.db` files per process id.
