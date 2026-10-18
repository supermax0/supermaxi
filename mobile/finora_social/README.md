# Finora Social (Flutter) — Phase 1

## Run

```bash
cd mobile/finora_social
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:5000 --dart-define=TENANT_SLUG=super
```

Without overrides the app connects to `https://www.finora.company` and tenant
`super`, so an installed APK works immediately. Use the defines only for local
development or another tenant.

- Android emulator → host machine: `http://10.0.2.2:5000`
- iOS simulator → `http://127.0.0.1:5000`
- Physical device → use your LAN IP

Release builds reject non-HTTPS API URLs and require `android/key.properties`.

## Phase 1 + 2 + 3 + 4 scope

- Theme, RTL, OTP auth
- Video feed + engagement + comments
- Store catalog from Finora products, search, categories, favorites
- Video ↔ product linking sheet
- Cart/checkout placeholders until Phase 5
