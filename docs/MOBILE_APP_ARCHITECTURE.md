# Finora Mobile Social Commerce — Architecture (Phase 1)

## Current Finora stack

- **Web app:** Flask + Jinja2 + Vanilla JS (`app.py` / `app_server.py`)
- **Core DB:** PostgreSQL (`DATABASE_URL`) — tenants, super-admin, landing
- **Tenant DB:** SQLite `tenants/{slug}.db` — products, invoices, customers, employees
- **Tenant binding:** `g.tenant` via `DynamicTenantSession` (`extensions.py`, `extensions_tenant.py`)
- **Storefront:** guest shop under `/shop/<tenant_slug>/` — session cart, COD checkout → `Invoice`
- **Customers:** phone-keyed `Customer` model — **no password / no shopper login today**
- **Staff auth:** Flask session cookies (also used by Android POS)
- **Existing mobile:** `mobile/finora_pos_android` (Kotlin), `mobile/finora_delivery_agent_android` (WebView) — unchanged
- **Publisher:** stable release — not modified by this module

## Phase 1 decisions

| Topic | Decision |
|-------|----------|
| Module path | `modules/mobile_app/` |
| Public API | `/api/mobile/v1/` |
| Shopper identity | `MobileUser` linked to existing `Customer` by phone (no duplicate customers) |
| Auth | OTP → signed access token (`itsdangerous`, short TTL) + refresh token hashed in DB |
| OTP delivery | Pluggable provider; Phase 1 logs OTP (dev/test). Rate limit + expiry enforced |
| Schema | `create_all` + `schema_guard` on tenant SQLite (Finora pattern) |
| Flutter app | `mobile/finora_social/` — Riverpod + Dio + go_router + secure storage |
| Feature flags | `MobileFeatureFlag` per tenant with safe defaults |

## Why itsdangerous (not PyJWT yet)

Flask already ships `itsdangerous`. Access tokens are URL-safe timed payloads with `SECRET_KEY`. Refresh tokens are opaque random strings stored as SHA-256 hashes. This matches JWT rotation/revocation goals without a new production dependency. PyJWT can replace the access-token encoder later without changing API contracts.

## Request contract

Every mobile API call (except docs) must send:

```http
X-Tenant-Slug: <tenant_slug>
```

Authenticated routes also need:

```http
Authorization: Bearer <access_token>
```

Tenant slug binds `g.tenant` before any ORM query (same isolation model as storefront).

## Phase 1 endpoints

- `GET  /api/mobile/v1/health`
- `GET  /api/mobile/v1/bootstrap`
- `POST /api/mobile/v1/auth/request-otp`
- `POST /api/mobile/v1/auth/verify-otp`
- `POST /api/mobile/v1/auth/refresh`
- `POST /api/mobile/v1/auth/logout`
- `POST /api/mobile/v1/auth/logout-all`
- `GET  /api/mobile/v1/auth/me`

## Phase 2 — Video feed

### Models
`MobileVideo`, `MobileVideoAsset`, `MobileVideoProduct`, `MobileVideoView`, `MobileVideoLike`, `MobileVideoSave`, `MobileVideoShare`, `MobileFeedEvent`

### Processing
Upload → save original under `uploads/mobile_videos/{tenant}/{id}/` → background job (`enqueue_video_processing`):
- Prefer Celery when `CELERY_BROKER_URL` / `REDIS_URL` is set
- Else daemon thread calling the same `process_video_job`
- FFmpeg: thumbnail + best-effort HLS; fallback progressive MP4 if FFmpeg/HLS fails

### Admin (staff session + `mobile_app.manage_videos` or admin role)
- `GET/POST /api/mobile/v1/admin/videos`
- `POST /api/mobile/v1/admin/videos/{id}/publish|hide`
- `DELETE /api/mobile/v1/admin/videos/{id}`

### Mobile feed (Bearer)
- `GET /api/mobile/v1/feed?cursor=&limit=`
- `GET /api/mobile/v1/videos/{id}`
- `POST /api/mobile/v1/videos/{id}/view|like|save|share`
- `DELETE /api/mobile/v1/videos/{id}/like|save`
- Media: `/api/mobile/v1/media/videos/{id}/original|thumbnail|hls`

### Flutter
Vertical `PageView` feed with prev/current/next warm window, double-tap like, save, share, comments bottom sheet.

## Phase 3 — Comments

### Models
`MobileComment`, `MobileCommentLike`, `MobileCommentReport`, `MobileBlockedUser`, `MobileModerationRule`

### Mobile (Bearer)
- `GET/POST /api/mobile/v1/videos/{id}/comments`
- `POST /api/mobile/v1/comments/{id}/replies`
- `POST/DELETE /api/mobile/v1/comments/{id}/like`
- `DELETE /api/mobile/v1/comments/{id}`
- `POST /api/mobile/v1/comments/{id}/report`

### Admin (staff + `mobile_app.manage_comments`)
- `GET /api/mobile/v1/admin/comments`
- `POST /api/mobile/v1/admin/comments/{id}/hide|pin`
- `POST /api/mobile/v1/admin/comments/reply` (company reply)
- `POST /api/mobile/v1/admin/users/{id}/block`

Moderation: blocked-word rules (`reject` / `pending_review` / `hide`). UI shows two levels only (comment → replies).

## Phase 4 — Store / Products

Reuses Finora `Product` + storefront presenter (no duplicate catalog).

### Mobile (Bearer)
- `GET /api/mobile/v1/categories`
- `GET /api/mobile/v1/products`
- `GET /api/mobile/v1/products/{id}`
- `GET /api/mobile/v1/products/{id}/videos`
- `GET /api/mobile/v1/offers`
- `GET /api/mobile/v1/search`
- `GET/POST/DELETE /api/mobile/v1/favorites[/{product_id}]`
- `GET /api/mobile/v1/videos/{id}/products`

### Admin
- `POST /api/mobile/v1/admin/videos/{id}/products` — link product to video

### Flutter
Store tab with search/categories/grid, product detail, favorites, video products sheet.

## Phase 5 — Cart / Checkout / Orders

Server-side cart per `MobileUser` (not Flask session). Checkout reuses `StorefrontCheckoutService` → Finora `Invoice` + `OrderItem` + stock lock/deduct. Attribution stored in `MobileOrderAttribution` + invoice note (`source=mobile_app`, optional `video_id`).

### Models
`MobileCart`, `MobileCartItem`, `MobileOrderAttribution`

### Mobile (Bearer)
- `GET/DELETE /api/mobile/v1/cart`
- `POST /api/mobile/v1/cart/items`
- `PATCH/DELETE /api/mobile/v1/cart/items/{id}`
- `POST /api/mobile/v1/cart/validate`
- `POST /api/mobile/v1/checkout/preview`
- `POST /api/mobile/v1/orders`
- `GET /api/mobile/v1/orders`
- `GET /api/mobile/v1/orders/{id}`
- `POST /api/mobile/v1/orders/{id}/cancel` (only while status = `تم الطلب`)

### Flutter
Cart page, COD checkout form, orders list + tracking steps, add-from-product/video, profile shortcuts.

## Phase 6 — Rewards / Coupons / Campaigns

Ledger-based points (not balance-only). Purchase rewards stay `pending` until invoice status matches rule (`مكتمل` / `مسدد` / `تم التوصيل`). Welcome bonus on first login. Coupons + points discounts applied server-side at cart/checkout.

### Models
`MobileRewardAccount`, `MobileRewardTransaction`, `MobileRewardRule`, `MobileRewardTier`, `MobileRewardRedemption`, `MobileCampaign`, `MobileDiscount`, `MobileCoupon`, `MobileCouponRedemption`

### Mobile (Bearer)
- `GET /api/mobile/v1/rewards`
- `GET /api/mobile/v1/rewards/history|rules|available-redemptions`
- `POST /api/mobile/v1/rewards/redeem` (applies points to cart)
- `GET /api/mobile/v1/coupons` · `POST /coupons/validate` · `GET /discounts`
- `POST/DELETE /api/mobile/v1/cart/apply-coupon|coupon`
- `POST/DELETE /api/mobile/v1/cart/apply-points|points`

### Admin (staff)
- `POST /api/mobile/v1/admin/coupons`
- `POST /api/mobile/v1/admin/campaigns`
- `POST /api/mobile/v1/admin/rewards/adjust`

### Flutter
Rewards tab (balance, tier, campaigns, redeem, history) + coupon field on cart.

## Phase 7 — Finora AI

Tool-grounded shopping assistant. Never invents products/prices — answers come from catalog/cart/rewards/orders tools. `add_item_to_cart` requires explicit user confirmation.

### Models
`MobileAIConversation`, `MobileAIMessage`, `MobileAIToolExecution`

### Tools
`search_products`, `get_product_details`, `get_current_price`, `get_stock_status`, `suggest_by_budget`, `compare_products`, `get_user_rewards`, `get_active_coupons`, `get_order_status`, `add_item_to_cart`

### Mobile (Bearer)
- `POST /api/mobile/v1/ai/conversations`
- `GET /api/mobile/v1/ai/conversations`
- `GET /api/mobile/v1/ai/conversations/{id}`
- `POST /api/mobile/v1/ai/conversations/{id}/messages`
- `POST /api/mobile/v1/ai/conversations/{id}/confirm-action`

Fallback rule-based path when OpenAI is unavailable / `TESTING=True`. With OpenAI key, wording can be polished while tools stay the source of truth.

### Flutter
Finora AI chat tab: messages, product chips, confirm-add-to-cart, suggestion chips.

## Phase 8 — Notifications / Analytics / Flags / Design

In-app notification inbox + queued push delivery records. Broadcasts run in a background thread (sync under `TESTING`). Batched analytics with event allow-list. Admin can toggle feature flags and app branding; bootstrap returns design + maintenance.

### Models
`MobileNotification`, `MobileNotificationDelivery`, `MobileNotificationPreference`, `MobileAnalyticsEvent`, `MobileAppDesign`

### Mobile (Bearer)
- `GET /api/mobile/v1/notifications`
- `PATCH /api/mobile/v1/notifications/{id}/read`
- `GET/PATCH /api/mobile/v1/notifications/preferences`
- `POST /api/mobile/v1/devices/register`
- `DELETE /api/mobile/v1/devices/{id}`
- `POST /api/mobile/v1/analytics/events`

### Admin (staff)
- `POST /api/mobile/v1/admin/notifications/send`
- `GET /api/mobile/v1/admin/analytics/summary`
- `GET/PATCH /api/mobile/v1/admin/feature-flags`
- `GET/PATCH /api/mobile/v1/admin/design`

### Bootstrap
Returns `feature_flags`, `branding`, `maintenance`.

### Flutter
Notifications page under profile, device register after OTP, analytics tracker helper.

### Security / perf notes
- Analytics rejects unknown event names and caps batch size (50).
- Heavy notification fan-out is not done inline in HTTP (thread/job).
- Orders create an in-app notification after checkout.
- Finora Jinja admin at `/mobile-app/` (sidebar: تطبيق الهاتف).

## Production hardening (post Phase 8)

### Finora admin UI
`/mobile-app/` — dashboard, videos, users, comments, rewards, coupons, flags, notifications, design, analytics.

### Pluggable providers
- SMS OTP: `LogSmsProvider` (default) or `HttpSmsProvider` via `MOBILE_SMS_WEBHOOK_URL`
- Push: `LogPushProvider` (default) or `HttpPushProvider` via `MOBILE_PUSH_WEBHOOK_URL`

## Gap-fill — Profile / Addresses / Unified search

### Models
`MobileUserAddress`

### Mobile (Bearer)
- `GET/PATCH /api/mobile/v1/profile`
- `GET/POST /api/mobile/v1/profile/addresses`
- `PATCH/DELETE /api/mobile/v1/profile/addresses/{id}`
- `GET /api/mobile/v1/profile/favorites`
- `GET /api/mobile/v1/profile/liked-videos`
- `POST /api/mobile/v1/profile/delete-account` (deactivates + revokes sessions)
- `GET /api/mobile/v1/search/unified?q=` — products + categories + offers + videos

### Flutter
Profile tab: edit profile, addresses, liked/saved videos, rewards snapshot, delete account. Store search uses unified endpoint. App bootstrap gates maintenance mode.

## Acceptance snapshot (Phases 1–8 + hardening + gap-fill)

| Capability | Status |
|------------|--------|
| OTP auth + tenant header | Done |
| Video upload/process/feed | Done |
| Comments + moderation | Done |
| Store / favorites | Done |
| Cart / checkout → Invoice | Done |
| Rewards + coupons | Done |
| Finora AI tools | Done |
| Notifications + analytics + flags | Done |
| Finora admin console (Jinja) | Done |
| SMS/Push provider hooks | Done |
| Profile + addresses + unified search | Done |

## Remaining optional integrations

Wire real FCM/APNs or SMS vendor credentials into the HTTP webhooks; production SMS should not rely on log-only delivery.

Detailed docs live under [`docs/mobile-app/`](mobile-app/) (architecture, setup, API, security, testing, …).

## Single source of truth

Products, prices, stock, and orders remain Finora tenant models. Mobile never invents a parallel catalog or order ledger.
