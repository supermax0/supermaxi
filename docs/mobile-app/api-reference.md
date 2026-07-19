# API reference (mobile v1)

Base: `/api/mobile/v1`  
Headers: `X-Tenant-Slug` (required), `Authorization: Bearer <access>` (authenticated routes)

## Auth
- `POST /auth/request-otp` · `POST /auth/verify-otp` · `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me`

## Feed / video
- `GET /feed?cursor=&limit=`
- `POST /videos/{id}/view|like|save|share` · `DELETE .../like|save`
- `GET /videos/{id}/comments` · comment CRUD under `/comments`

## Catalog / search
- `GET /categories` · `/products` · `/products/{id}` · `/offers` · `/search` · `/search/unified`
- `GET/POST/DELETE /favorites[/{id}]`

## Cart / orders
- `GET/POST/PATCH/DELETE /cart...` · coupons/points apply
- `POST /checkout/preview` · `POST /orders` · `GET /orders[/{id}]` · `POST /orders/{id}/cancel`

## Rewards / AI / phase 8
- `/rewards*` · `/coupons*` · `/ai/conversations*`
- `/notifications*` · `/devices/register` · `/analytics/events`
- `/profile*` · `/profile/addresses*` · `/profile/liked-videos` · `/profile/delete-account`

## Admin (staff session or test header)
Under `/api/mobile/v1/admin/...` for videos, comments, rewards, flags, design, notifications, analytics.
