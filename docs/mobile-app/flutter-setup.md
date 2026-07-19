# Flutter setup

Project: `mobile/finora_social/`

```bash
cd mobile/finora_social
flutter pub get
flutter run
```

Configure `lib/core/config/app_config.dart`:

- `apiBaseUrl` — Finora origin
- `tenantSlug` — target tenant

Stack: Riverpod, Dio, go_router, video_player, share_plus. Locale forced RTL (`ar`).

Feed preloads current ±1 players; inactive neighbors stay muted/paused and dispose outside the warm window.
