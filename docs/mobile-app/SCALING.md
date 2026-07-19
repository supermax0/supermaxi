# Finora Mobile — production scaling contract

The mobile code is designed to stay responsive under horizontal scaling, but
"millions of simultaneous users" is an infrastructure target, not a single
Flutter or Flask switch. It must be demonstrated by load tests against the
production topology below.

## Changes already enforced in application code

- Feed uses bounded keyset pagination over the full ranking tuple and a
  composite feed index; it does not use growing SQL offsets.
- Catalog returns bounded pages (`limit`, `next_offset`, `has_more`) and Flutter
  requests the next 24 products only near the end of the grid.
- Flutter keeps at most the current and adjacent video players warm and disposes
  players outside that window.
- Mobile rate limits use Redis atomically when `REDIS_URL` is configured. The
  in-process limiter is a development fallback only.
- Analytics are ingested in batches of at most 50 events.
- Video processing can run in Celery when Redis/Celery is configured, keeping
  FFmpeg work out of API workers.
- OpenAI calls and checkout mutations stay server-side and have explicit rate
  limits/confirmation boundaries.

## Required production topology

1. Global load balancer/WAF -> multiple stateless Flask API instances.
2. PostgreSQL primary plus read replicas and PgBouncer. Tenant SQLite files are
   acceptable for small tenants only; high-volume tenants must be migrated to
   PostgreSQL before claiming large concurrency.
3. Redis cluster for shared rate limits, short-lived cache, Celery broker, and
   idempotency locks.
4. Object storage for originals, thumbnails and HLS renditions, fronted by a
   CDN. API workers must not stream every video byte from local disks.
5. Celery worker pools dedicated to FFmpeg, notifications and analytics.
6. Autoscaling from request latency, queue depth, DB saturation and error rate;
   not CPU alone.
7. Central logs, traces and metrics with tenant-safe cardinality controls.

## Release gates

- Run k6/Locust tests for guest feed, authenticated engagement, catalog search,
  comments, cart and AI independently.
- Validate p95 API latency, video start time, error rate, DB connections, Redis
  saturation and queue depth at every target stage.
- Test progressively (1k -> 10k -> 100k concurrent sessions). A million-user
  claim is allowed only after the real CDN, database and autoscaling topology
  passes the target workload and a regional failure drill.
- Verify that API instances can be added/removed without losing rate-limit,
  cart, session, analytics or background-job state.

## Reproducible public-API probe

Run the bounded probe against an isolated staging environment. It warms the
health, feed, catalog and category endpoints, starts all workers together, and
fails with exit code `2` when the error-rate or p95 gate is missed.

```bash
python scripts/load_test_mobile_api.py \
  --base-url https://staging.example.com \
  --tenant super \
  --concurrency 100 \
  --requests 5000 \
  --max-p95-ms 500 \
  --max-error-rate 0.005 \
  --json-output artifacts/load/mobile-api-100.json
```

Use separate result files for `100`, `1k`, `10k`, and larger stages. Above 500
local worker threads the command requires `--allow-high-concurrency`; at that
point distributed k6/Locust generators are preferred so the load generator does
not become the bottleneck. Never run a high-concurrency stage against the live
single-server deployment.

The catalog category projection is normalized into the indexed
`product.catalog_category` column and automatically backfilled from legacy
`meta_json`. This makes category filtering happen before pagination instead of
discarding non-matching products after a page has already been selected.

## Immediate deployment settings

```dotenv
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
CELERY_BROKER_URL=redis://...
MOBILE_VIDEO_ROOT=/shared-or-object-storage-mount
```

The current single-server deployment remains suitable for validation and early
traffic, but it is not evidence of million-user capacity.
