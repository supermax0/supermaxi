# Finora Mobile App — Architecture

See also the living overview: [`docs/MOBILE_APP_ARCHITECTURE.md`](../MOBILE_APP_ARCHITECTURE.md).

## Boundaries

- Module: `modules/mobile_app/`
- Public API: `/api/mobile/v1/*` with required `X-Tenant-Slug`
- Admin UI: `/mobile-app/` (Jinja) inside Finora web
- Flutter client: `mobile/finora_social/`
- Data: tenant SQLite via `g.tenant` — same `Product` / `Invoice` / `Customer` as Finora

## Request flow

```text
Flutter → Dio (+ Bearer) → Flask mobile_api_v1_bp
  → bind tenant + schema_guard
  → service layer → tenant models
```

## Non-goals

- Do not fork catalog or orders into a parallel ledger
- Do not modify Publisher stable surfaces
