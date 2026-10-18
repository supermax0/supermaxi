# FINORA CORE — Architecture

Status: Phases 1–9 complete (Phase 9 = production hardening before real customers). Desktop in `desktop/finora_core/`, server in `modules/finora_core/`. Next: the FINORA CORE "brain" (Customer Resolution → Memory → Intent/Business Profiling → Knowledge → Agent Planning → FINORA Tools → Policy/Approvals → Onboarding/Training).

This document is written from repository evidence. Where an existing subsystem already does the job, FINORA CORE reuses it instead of building a parallel one.

---

## 1. Current architecture (what already exists)

| Area | Existing implementation | Evidence |
|---|---|---|
| Web backend | Flask + SQLAlchemy, single process, APScheduler | `app.py`, `app_server.py`, `extensions.py` |
| Core DB | PostgreSQL (`DATABASE_URL`): `Tenant`, `SuperAdmin`, plans, leads CRM | `models/core/*`, `docs/POSTGRES.md` |
| Tenant DBs | One SQLite file per tenant (`tenants/{slug}.db`) bound via `DynamicTenantSession` | `extensions_tenant.py` |
| Super Admin auth | Flask session cookie (`is_superadmin`, `superadmin_id`), `superadmin_bp.before_request` guard | `routes/superadmin.py:220,289` |
| Leads CRM | `BusinessLead` + pipeline, notes, follow-ups, audit (`log_lead_action`), trial/subscribe conversion | `routes/superadmin_leads.py`, `services/leads_crm/*` |
| Trial provisioning | `start_trial_for_lead()` — idempotent per lead (`lead.finora_company_id` short-circuit) | `services/leads_crm/trial_service.py` |
| Meta messaging | Full pipeline: webhook verify + `X-Hub-Signature-256` HMAC, idempotent insert by `external_message_id`, atomic `processing` claim, burst batching, OpenAI Responses structured output, takeover/release, delivery status | `modules/ai_sales/*` (≈14.7k lines) |
| AI provider | `modules/ai_sales/openai_service.py` (server-side key only) | `docs/FINORA_SALES_AI_OPENAI_UPGRADE.md` |
| Feature flags | Core DB `tenant_features`, `services/feature_service.py` | AI tutor phases |
| Existing desktop | `desktop/finora_superadmin/` — PyInstaller + WebView2 wrapper around `/superadmin/` | `desktop/finora_superadmin/README.md` |
| Realtime | None (polling only) | `FINORA_AI_WORKSPACE_IMPLEMENTATION_PLAN.md §2.3` |
| E2E | Playwright (root `package.json`, `playwright.config.js`), pytest for Python | `tests/` |

Key observation: `ai_sales` is **tenant-scoped** (a tenant sells its products to its customers). FINORA CORE is FINORA selling *itself*. The cleanest reuse is to treat FINORA as a **house tenant** that runs `ai_sales` for FINORA's own Instagram / Facebook pages, and add a Super-Admin-scoped layer on top.

### Findings to fix during later phases
1. `routes.py:3291` — `if app_secret and not verify_meta_signature(...)`: signature validation is **skipped when no app secret is configured**. FINORA CORE's house channel must refuse to run without `META_APP_SECRET` (fail closed).
2. Super Admin auth is cookie-only; a desktop client needs a scoped, revocable token (see §6).

---

## 2. Proposed architecture

```text
┌────────────────────────── FINORA CORE DESKTOP (Tauri 2) ──────────────────────────┐
│ React 18 + TS strict · R3F orb · Framer Motion morph · Zustand · TanStack Query   │
│ DataSource port ── HttpDataSource (prod)  |  DevDataSource (development only)      │
│ No Meta tokens, no OpenAI key, no Super Admin password stored. Token in OS keyring │
└───────────────────────────────┬───────────────────────────────────────────────────┘
                                │ HTTPS REST + SSE (/api/v1/finora-core/*)
┌───────────────────────────────▼───────────────────────────────────────────────────┐
│ FLASK  modules/finora_core/  (Super Admin scoped — new)                            │
│ auth (desktop tokens, RBAC) · conversations façade · events (SSE + outbox)         │
│ approvals · audit · memory · knowledge · tool layer · policy · kill switch         │
├──────────────────────────────┬─────────────────────────────┬──────────────────────┤
│ modules/ai_sales (REUSED)     │ services/leads_crm (REUSED) │ superadmin tenant    │
│ webhook, dedupe, claim,       │ BusinessLead, pipeline,     │ provisioning         │
│ OpenAI, Meta send, takeover   │ trial/subscribe, audit      │ (wrapped as tools)   │
└──────────────────────────────┴─────────────────────────────┴──────────────────────┘
          ▲ Meta webhooks (Instagram / Messenger) for the FINORA house tenant
```

The agent runs server-side (the existing `ai_sales` background worker). Closing the desktop app never stops replies.

### Why not a new Node/Fastify server
The spec allows deviating when equivalent production infrastructure exists. It does: webhook gateway, dedupe, claim locking, structured AI output, Meta adapters, lead CRM, provisioning, and audit already exist in Python. A second backend would duplicate them and split the source of truth. Node/TS is used **only** for the desktop client.

---

## 3. Module boundaries

### Desktop (`desktop/finora_core/`)
```text
src/
  app/            AppWindow, titlebar, routing between orb / workspace / activity / settings
  design/         tokens.css (colors, radii, shadows), motion.ts (durations, easings)
  orb/            OrbCanvas (R3F + GLSL), orbMachine.ts (pure state machine), StatusBubble
  workspace/      ConversationList, ChatPanel, MessageBubble, Composer, CustomerPanel
  activity/       ActivityTimeline
  approvals/      ApprovalCard
  settings/       Settings shell
  data/           schemas.ts (Zod), DataSource port, devSource.ts, httpSource.ts
  state/          Zustand stores (ui, agent)
  ui/             GlassSurface, FinoraButton, FinoraInput, Skeleton, EmptyState, ErrorState, Toast
src-tauri/        Rust shell (custom titlebar, no secrets)
```

### Server (`modules/finora_core/`, Phase 6+)
```text
api.py          Blueprint /api/v1/finora-core
auth.py         desktop token issue/verify/revoke, role → permission map
events.py       outbox table + SSE stream with Last-Event-ID resync
conversations.py façade over ai_sales models of the house tenant
approvals.py    approval lifecycle (pending → approved/rejected → executed/failed)
audit.py        append-only audit_logs
memory.py       structured facts with confidence/source; conflict resolution
knowledge.py    versioned FINORA product knowledge (reuses ai_sales knowledge entries)
tools/          typed tools: find_customer, create_lead, start_trial, enable_module, ...
policy.py       risk classification + feature flags + kill switch
```

---

## 4. Database changes (Core DB, Alembic migrations)

New tables (all with `created_at`, `updated_at` where mutable):

| Table | Purpose | Key indexes / constraints |
|---|---|---|
| `fc_desktop_tokens` | hashed desktop session tokens, role, expiry, revoked_at | unique(token_hash), idx(superadmin_id) |
| `fc_customer_identities` | Instagram ID / PSID / phone / email → `business_leads.id` | unique(kind, value) |
| `fc_memory_facts` | key, value_json, confidence, source, superseded_by | idx(lead_id, key) |
| `fc_lead_transitions` | from_stage, to_stage, actor, actor_type, reason | idx(lead_id, created_at) |
| `fc_agent_runs` | conversation, status, prompt_version, model, tokens, cost, timeout_at | idx(conversation_ref, created_at) |
| `fc_tool_calls` | run, tool, risk, input_summary (redacted), result, idempotency_key | unique(idempotency_key) |
| `fc_approvals` | action, risk, old/new value, reason, status, decided_by | idx(status, created_at) |
| `fc_events` | outbox for realtime: seq (bigserial), type, payload_json | idx(seq) |
| `fc_audit_logs` | actor, actor_type, customer, tenant, action, input_summary, result, correlation_id, approval_id | append-only (no UPDATE/DELETE grants) |
| `fc_internal_notes` | conversation ref, author, body | idx(conversation_ref) |
| `fc_settings` | kill switch, automation flags (AI_AUTO_REPLY, AI_ACCOUNT_CREATION, ...) | single row per key |

Conversations and messages stay in the house tenant's `ai_sales_conversation` / `ai_sales_message` (message idempotency already enforced by `external_message_id`). Leads stay in `business_leads`.

Rollback: every migration has a `downgrade()`; new tables only, no destructive changes to existing ones.

---

## 5. API contracts (`/api/v1/finora-core`, JSON, Zod-mirrored on the client)

| Method | Path | Permission |
|---|---|---|
| POST | `/auth/token` (Super Admin credentials → desktop token) | — |
| POST | `/auth/revoke` | self |
| GET | `/me` | any |
| GET | `/status` (channels health, kill switch, agent state) | any |
| GET | `/conversations?filter=&channel=&q=&cursor=` | conversations.view |
| GET | `/conversations/{id}/messages?before=&limit=` | conversations.view |
| POST | `/conversations/{id}/messages` (idempotency key header) | messages.send |
| POST | `/conversations/{id}/takeover` · `/resume` | ai.takeover |
| GET/PATCH | `/customers/{id}` | conversations.view / customers.edit |
| POST | `/customers/{id}/notes` | notes.write |
| GET | `/approvals?status=pending` · POST `/approvals/{id}/decision` | approvals.decide |
| GET | `/activity?category=&cursor=` | audit.view |
| POST | `/automation/pause-all` · `/automation/resume` (reason required) | settings.manage |
| GET | `/events/stream` (SSE, `Last-Event-ID`) | any |

Shapes are defined once in `desktop/finora_core/src/data/schemas.ts` and mirrored by Python dataclasses/marshmallow-free validators server-side. Contract tests compare both.

---

## 6. Security model
- Desktop stores **only** a short-lived desktop token (OS keyring via Tauri in production builds). No Meta tokens, no AI keys, no Super Admin password persisted.
- Roles: `super_admin`, `admin`, `support`, `sales`, `read_only` → explicit permission sets (view, send, takeover, create tenant, approve, audit, settings).
- AI never sees Super Admin tokens; tools run with server-side service credentials after policy check.
- No model-generated SQL or URLs. Tools take validated typed arguments only.
- Meta signature validation fails closed for the house channel.
- Logs pass through the existing `_redact_log_value` pattern; audit stores input *summaries*, not secrets.
- CSP in Tauri: `default-src 'self'; connect-src` limited to the configured API origin.

## 7. Realtime architecture
- Server writes every state change to `fc_events` (outbox) in the same transaction as the change.
- `/events/stream` (SSE) replays from `Last-Event-ID`, then tails. On reconnect the client resyncs with REST (the DB is the source of truth; SSE is only a hint).
- Typed events: `message.received`, `message.sent`, `agent.started`, `agent.status`, `tool.started|completed|failed`, `customer.updated`, `approval.required|resolved`, `conversation.updated`.
- SSE chosen over WebSocket: server→client only, works through Nginx and Flask without a new async runtime.

## 8. Meta integration
Reuse `ai_sales` webhook (`/api/v1/ai-sales/webhooks/meta/<house_slug>/<key>`), dedupe, ordering, claim, retries and `MetaGraphClient`. FINORA CORE adds: house-tenant configuration (`FINORA_CORE_HOUSE_TENANT`), fail-closed signature check, channel health surfaced in `/status` (drives "Instagram غير متصل").

## 9. FINORA integration
`FinoraClient` (server-side adapter) wraps existing services: `start_trial_for_lead`, tenant feature flags (`feature_service`), clinic specialty setup, user creation. Each tool: validate → authorize → tenant check → execute → verify → audit → typed result. Idempotency keys stored in `fc_tool_calls`.

## 10. Agent architecture
Existing `ai_sales` engine becomes the runtime. FINORA CORE adds a FINORA-specific profile (knowledge about FINORA modules/pricing from versioned knowledge entries), a business profiler that writes `fc_memory_facts`, and a policy gate in front of tools (low → auto, medium → flag-dependent, high → approval). Prompt version + model recorded per run.

## 11. Test strategy
- Desktop: Vitest (orb state machine, lead transitions, schema parsing, stores), React Testing Library (components), Playwright against the Vite web shell (orb → workspace morph, selection, takeover, approvals) + screenshot regression at 1280×720 … 2560×1440.
- Server: pytest (tools, policy, approvals, SSE resync, auth/RBAC, webhook signature fail-closed, duplicate events).
- `npm run verify` in `desktop/finora_core`: format check, lint, typecheck, unit tests, build.

## 12. Milestones
| Phase | Scope | State |
|---|---|---|
| 1 | Architecture (this doc) | done |
| 2 | Desktop shell: Tauri window, titlebar, tokens, fonts, RTL, settings shell | done |
| 3 | Orb: R3F shader orb, state machine, status bubble, reduced-motion + WebGL fallback | done |
| 4 | Orb ↔ workspace morph, state preservation | done |
| 5 | Conversations UI on development data | done |
| 6 | Server foundation: tokens, RBAC, conversations façade, SSE outbox | done |
| 7 | Meta house channel (production) | done |
| 8 | FinoraClient read → write tools | pending |
| 9–10 | Agent profile, memory, policy, automation | pending |
| 11 | Takeover, approvals, notes, kill switch | pending |
| 12 | Onboarding + training | pending |
| 13 | Security & audit hardening | pending |
| 14–15 | Full testing, Windows installer | pending |

---

## 13. Phase 6 — as built

**Server (`modules/finora_core/`)**
- `auth.py` — `POST /auth/login|refresh|logout`. Access token: itsdangerous-signed, 15 min, audience `finora_core`, bound to a
  `fc_desktop_sessions` row (revocation is checked on every request). Refresh token: random, stored only as SHA-256, rotated
  on every refresh; presenting a rotated-out token revokes the whole session (theft detection). Login throttled to
  5 failures / 10 min per IP+username.
- `permissions.py` — roles `super_admin | admin | sales | support | read_only`; Super Admins without a `fc_operator_roles`
  row are `super_admin`; unknown roles get nothing.
- `store.py` — explicit Core-DB session (`core_session()`) and house-tenant context (`use_house()`), because Finora routes
  `db.session` by `g.tenant`. The house tenant is `FINORA_CORE_HOUSE_TENANT`; it must be an existing, provisioned tenant
  (never created implicitly).
- `conversations.py` — façade over the house tenant's `ai_sales` tables (Instagram + Messenger only), mapped to the desktop
  contract. Per-operator unread markers (`fc_conversation_reads`). Business facts are `null` until the memory system
  (Phase 9) — never guessed.
- `sync.py` + `GET /events/stream` — SSE with `Last-Event-ID` replay from the durable `fc_events` outbox. Webhook/worker
  activity in `ai_sales` is converted into events and audit rows idempotently (dedupe keys). Streams end after 5 minutes;
  clients reconnect and resync from REST.
- `transport.py` — manual replies go through the existing `ai_sales` Meta client. `FINORA_CORE_DEV_LOOPBACK=1` skips Meta
  only when `FINORA_ENV=development`, and `/status.devLoopback` exposes it. Provider failures return `502 META_SEND_FAILED`
  with the message stored as `failed`.
- Kill switch: `POST /automation` (reason required, audited). `ai_sales.engine.process_inbound_message` checks
  `killswitch.automation_paused_for_current_tenant()` — only for the house tenant, fail-closed; inbound messages stay
  `received`.
- Schema: `migrations.py` (versioned, upgrade + downgrade; `flask finora-core-db upgrade|downgrade --to N|current`),
  applied at startup.
- CORS allow-list: `FINORA_CORE_ALLOWED_ORIGINS` (default: Tauri origins + `http://localhost:5174`).

**Desktop** — `HttpDataSource` (Zod-validated responses, single-flight refresh, SSE over `fetch` with backoff +
`Last-Event-ID` + resync), first-run server setup, sign-in, account/sign-out in Settings, permission-aware UI (`useCan`).

**Tests** — `tests/test_finora_core_api.py` (21, isolated SQLite app), desktop unit/component (49), mocked E2E (23),
live E2E against a real server (`npm run e2e:live`, provisioned by `scripts/provision_finora_core_e2e.py`).

---

## 14. Phase 7 — Meta house channel (as built)

Everything runs through the existing `modules/ai_sales` pipeline — no second Meta pipeline.

**House tenant.** Internal tenant `finora_house` (`business_type = "finora_internal"`), never a customer tenant.
`flask finora-house init` refuses a slug that belongs to a customer.

**Production activation (operator steps)**
```bash
FINORA_CORE_HOUSE_TENANT=finora_house flask finora-house init
# secrets via environment only (never argv / shell history):
META_APP_ID=... META_APP_SECRET=... META_USER_TOKEN=... flask finora-house meta-connect
flask finora-house health
```
`meta-connect` fails closed: the app secret must be 32 hex AND accepted by Meta (`GET /{app_id}` with the app token)
before anything is stored. It then registers the app webhooks (messages, postbacks, referrals, **message_deliveries,
message_reads**), imports every page + linked Instagram Business account as channels (Page ID / IG account ID →
`external_account_id`, parent connector → `parent_channel_id`) with `reply_mode=ai`, and subscribes them.
Correction (Phase 8): `AI_SALES_AUTOREPLY_ENABLED` has no configuration path in the codebase (always off). The house
tenant is therefore governed by FINORA CORE's own `AI_AUTO_REPLY` flag + kill switch; customer tenants keep the global
gate. Required: `FINORA_ENV=production`.

**Webhook security** (`modules/ai_sales/meta_policy.py`, `security.verify_meta_signature_strict`). House tenant: every
POST needs a usable app secret and a valid `X-Hub-Signature-256`. Missing / malformed / undecryptable secret → `503` +
connector `webhook_invalid` (events rejected; Meta retries later). Bad signature → `403`; 3 failures in 10 min →
`webhook_invalid` (one forged request cannot flip health); a valid event clears it. Customer tenants keep their previous
behaviour unless `META_REQUIRE_SIGNATURE=1` (recommended once every connector has a secret). The verification challenge
(`GET hub.challenge`) requires the stored verify token.

**Dedupe / retries / ordering.** Unique index `(channel_account_id, external_message_id)` (built by the schema guard;
skipped + logged on legacy DBs that already contain duplicates) + a per-message SAVEPOINT, so a Meta retry racing the
original is skipped alone. Only the dedupe constraint counts as a duplicate — any other integrity error is raised.
Messages are stored with Meta's event time and listed by it; delayed / out-of-order events never move
`last_customer_message_at` (or the 24 h window) backwards, and a message older than our latest reply is stored but never
auto-answered. Delete notifications are ignored.

**Receipts.** Messenger `delivery` (mids) / `read` (watermark) and Instagram `read` (mid) move outbound messages
sent → delivered → read, forward only; a receipt never resurrects a failed message.

**Outbound reliability** (`meta_reliability.py`, `meta_retry.py`), shared by AI replies on Meta channels, FINORA CORE
manual replies and retries. `sent` only after Meta returns a message id. Classification: token expired (190 with
463/467) · token invalid (190, 102) · permission missing (3, 10, 200–299, HTTP 403) · rate limited (4, 17, 32, 613,
800xx, HTTP 429) · transient (1, 2, 5xx, network) · policy (24 h window etc. — never marks the channel unhealthy).
Rate-limit / transient → `retry_scheduled` with exponential backoff + jitter, never shorter than Meta's `Retry-After` /
business-use-case estimate, max 5 attempts; claimed atomically (`retry_scheduled → sending`); per-conversation order is
preserved (later reply parts wait; they fail with an earlier permanent failure). AI retries obey the kill switch; human
replies are always delivered. Desktop: `201` sent · `202` queued for retry (shown as "sending") · `502` failed.

**Channel health** (`/status.channels`, worst state per platform): connected · token_expired · permission_missing ·
webhook_invalid · disconnected. Updated by send failures, webhook signature results and the live check
(`POST /channels/health-check`, `flask finora-house health`: token valid for the account + app still subscribed).

**Tokens.** Page tokens stay Fernet-encrypted in the house tenant DB; the Graph client sends them only in the
`Authorization` header. No API response, SSE event or desktop payload contains tokens, app secrets, verify tokens or
Meta CDN URLs (asserted by tests). Nothing from Meta credentials is placed in LLM prompts.

**Attachments** (`modules/ai_sales/attachments.py`). Every attachment of a message (not only the first) is normalized
to image / audio / video / document / sticker / unsupported with safe metadata (sanitized name, mime, status). Supported
ones are downloaded in the background from Meta's CDN (host allow-list; caps 15 / 25 / 50 / 25 MB) to
`uploads/ai_sales_media/<tenant>/` with a SHA-256; failures are recorded per attachment and never break the
conversation. The desktop receives only `{kind, mimeType, name, sizeBytes, status}`. Content analysis is a later phase.

**Kill switch.** Unchanged: inbound messages are always stored; automatic replies and AI retries are held.

**Loopback.** `FINORA_CORE_DEV_LOOPBACK` works only with `FINORA_ENV=development`; elsewhere it is ignored and logged as
an error at startup (tested: production with the variable set still calls Meta).

**Bugs found and fixed while building Phase 7**
- `mark_customer_activity` moved activity backwards on delayed events (shortened the 24 h reply window).
- Phase 6 sync dropped the very first message when the house started empty (cursor anchoring).
- Desktop dropped a live message that raced the initial REST load; streams now resync on every connect, and a racing
  event triggers a refetch after the in-flight load settles.
- `ensure_facebook_routing_schema` ALTERs + commits mid-request on a brand-new tenant, which broke the first message's
  insert (pre-existing ai_sales behaviour) — the house tenant is now provisioned with it up front.

**Tests.** `tests/test_finora_core_meta.py` (37, fake Graph API, no network) covers: valid / invalid / missing signature;
missing / malformed / undecryptable secret in production; verification challenge; duplicate event; duplicate message;
DB uniqueness; delayed event; out-of-order events; token expired; invalid token; missing permission (10 / 200); policy
error; 429 with Retry-After; 5xx retry then give up; success without message id; failed outbound; successful Facebook
+ delivery/read receipts; successful Instagram + read receipt; receipt vs failed message; ordered reply parts;
attachment metadata, storage and unsupported types; kill switch while messages arrive; live SSE event from a real
normalized Meta event; fail-closed activation; live health check (missing subscription, expired token); no secrets
reach the desktop. Live E2E (`e2e-live/meta.spec.ts`): Meta-signed webhook → real server → desktop; forged signature
rejected; Meta retry not duplicated.

## 15. Known pre-existing test debt (not caused by FINORA CORE)

Tracked as its own task: `docs/tasks/ai-sales-preexisting-failures.md`. Verified by re-running with the FINORA CORE /
Phase 7 changes reverted — they fail identically:
- `tests/test_ai_sales_foundation.py`: `test_meta_webhook_routes_page_to_configured_employee`,
  `test_meta_multi_page_management_keeps_tokens_private_and_scales_past_thirty_pages`,
  `test_inbox_read_close_reopen_and_incremental_messages`, `test_message_actions_and_manual_media_delivery`
- `tests/test_ai_sales_employee_page_scope.py::test_employee_only_sees_conversations_from_registered_pages`
- `tests/test_ai_sales_intelligence.py`: `test_product_knowledge_api_persists_grounded_sales_data`,
  `test_price_objection_uses_remembered_product_and_offers_cheaper_live_alternative`
- `tests/test_ai_sales_meta_ad_context.py::test_messenger_regular_sticker_is_not_treated_as_image`
- `tests/test_ai_sales_nearest_selection.py::test_nearest_appliance_size_cheapest_screen_and_product_details`

**Security finding (pre-existing, out of scope):** `ai_sales.routes._webhook_channel` accepts any slug matching its regex
and opens (creates) `tenants/<slug>.db` for it, so webhook URLs can create empty SQLite files for non-existent tenants.
It should verify the slug against the Core DB `tenants` table first.

---

## 16. Phase 8 — the FINORA CORE brain (as built)

Code: `modules/finora_core/brain/`. Entry: `ai_sales.engine.process_inbound_message` → (house tenant only, after
dedupe, claim, kill switch and takeover checks) → `brain.runtime.handle_house_message`. Customer tenants keep the
existing product-sales agent. Schema: migration v2 (11 `fc_*` tables, upgrade + downgrade).

| Step | Module | Behaviour |
|---|---|---|
| Customer resolution | `customers.py` | Channel identity → one customer; phone/email attached; same phone/email on another customer → merge **suggestion** only; merge is a human action (`/merge-suggestions`) |
| Memory | `memory.py` | Whitelisted, validated facts with value/confidence/source/timestamps; newer evidence supersedes (history kept); weaker → `conflict`; AI never overwrites a human fact; < 0.6 confidence never shown or acted on |
| Intent + profiling | `extract.py` | Iraqi-Arabic rules extractor (numbers incl. words and duals, business type/specialty, phones, emails, discount %, 14 intents). Grounding: a model number is trusted only if the customer's words contain it |
| Knowledge | `knowledge.py` | Prices only from `subscription_plans` (د.ع); verticals from `BUSINESS_TYPES`; how-to from verified AI-Tutor lessons; human-authored docs versioned (`flask finora-knowledge draft/publish/list`), drafts never used |
| Planning | `planner.py`, `provider.py` | Strict JSON-schema plan (`PROMPT_VERSION`), one retry, then the rules planner. `FINORA_CORE_AI_PROVIDER=off` forces rules only. Guards: invented prices, uncited factual answers, claims of unexecuted actions, links, unknown plans, ungrounded facts |
| Policy | `policy.py` | Risk per action + flags (`AI_AUTO_REPLY`, `AI_AUTO_LEAD`, `AI_ACCOUNT_CREATION`, `AI_TENANT_CONFIGURATION`, `AI_AUTOMATIC_ONBOARDING`, `AGENT_DISCOUNT_LIMIT`) via `/automation/flags` |
| Tools | `tools.py` | `create_lead` (leads CRM, links duplicates), `recommend_plan`, `handoff_human`, `start_trial`, `grant_discount`. Validated, idempotent, audited; AI may run only the low-risk three |
| Approvals | `approvals.py` | Trial accounts and every discount need a human. Approve → tool runs server-side → result verified → customer notified. Trial credentials returned **once** to the approver (desktop dialog), never stored, logged, sent in chat or to a model |
| Onboarding / training | `onboarding.py` | Checklist from evidence only (profile, offer, tenant, training answer, real tenant data). Training answers only for the customer's vertical / account |
| Runtime | `runtime.py` | Agent runs recorded (prompt version, model, tokens, outcome — no reasoning); live orb labels; response safety before send (human takeover, newer customer message, kill switch, 45 s timeout); reply via the shared transport (sent only with a Meta message id) |

Trial provisioning reuses the Super Admin steps (core tenant, tenant DB, tenant row, admin) with a random password and
compensation (tenant row + DB file removed) if verification fails. Unlike the Super Admin route it never stores the
password in plaintext.

**Bugs found and fixed in Phase 8:** late-arrival check broke on Meta's whole-second timestamps (fast customer replies
went unanswered); `use_house()` was not reentrant; Arabic patterns written with ى/ئ never matched normalized text;
handoff state lost before the safety re-read; interleaved Core-DB write transactions (deadlock on SQLite).

**Pre-existing issue noted in Phase 8 — fixed in Phase 9 (§17.1):** `routes/superadmin.tenants_create` defaulted the
admin password to `password123` and stored it in plaintext in the registration record.

**Tests:** `tests/test_finora_core_brain.py` (23, full pipeline through the real webhook: the 5 scenarios of §61,
guards, memory, resolution/merge, training, response safety, flags, permissions, idempotency),
`tests/test_finora_core_brain_units.py` (19), live E2E `e2e-live/brain.spec.ts`.

---

## 17. Phase 9 — production hardening (as built)

Schema: migration **v3** (additive, upgrade + downgrade, idempotent on fresh and upgraded databases): tables
`fc_shadow_proposals`, `fc_customer_merges`, `fc_knowledge_events`; new columns on memory facts, knowledge docs,
agent runs, tool calls, approvals and merge suggestions.

### 17.1 Credential security

| Path | Before | Now |
|---|---|---|
| Super Admin → create tenant | operator-typed or `password123`; plaintext in registration JSON; e-mailed; flashed | `services/tenant_provisioning.provision_tenant`: 16-char CSPRNG password, hash only, `must_change_password`, rollback on failure; shown **once** on a `no-store` page (no flash) |
| Payment request → approve | `password123`, same leaks | same shared service |
| Reset admin password | operator-typed; plaintext saved to registration | server-generated, returned once (`no-store` JSON), `must_change_password`; client-supplied passwords ignored |
| Reset tenant DB | `password123`, shown in the response; deleted the DB file relative to CWD (bug) | random once-only password; path resolved from the app root (+WAL/SHM) |
| FINORA CORE trial | already random | same shared service |
| Registration read APIs / tenant list | returned / displayed the stored password | no password field; legacy plaintext is scrubbed from the JSON file on first read; every save strips credential keys |
| Welcome e-mail | contained the password | never contains it |
| First login | — | `must_change_password` → forced `/account/change-password` (every page redirects, APIs 403 `password_change_required`) |

`employee.must_change_password` is a deferred column added by the schema guard, so legacy tenant DBs keep working.
Tests: `tests/test_credential_security.py` scans every DB / registration file, logs, e-mails, API responses and
activity payloads for the plaintext; `test_finora_core_phase9.py::test_trial_password_never_reaches_…` adds agent
prompts, traces, events and Meta sends.

### 17.2 Shadow Mode (`AI_SHADOW_MODE`, independent of the kill switch)

`ai_sales.engine` → `brain.shadow.shadow_house_message` → `runtime.handle_house_message(mode="shadow")`. It runs the
full pipeline (resolve customer, safe memory, intents, knowledge, plan, policy verdicts, the approvals it *would*
request with their previews) and stores an `FcShadowProposal`. It never sends, never runs a tool (`SHADOW_RUN`
context blocks every non-READ_ONLY tool in the executor too), never creates approvals, tenants or discounts, and
never moves lead stages. Messages keep their status, so humans see them as unanswered. Shadow runs even when the kill
switch is on or the thread is human-controlled, and it overrides live replies while it is on. Human replies are
linked through the desktop (`proposalId`, `usedProposal` → accepted / edited / own reply + similarity) or reconciled
from replies sent elsewhere. Operators review the escalation call (`/shadow/proposals/<id>/review`). The desktop
shows the proposal beside the composer, with a "Shadow" status pill.

### 17.3 Memory

Every row keeps value, normalized value, confidence, certainty (`tentative | stated | verified`), source, source
message, observed / created / superseded timestamps, status (`active | superseded | conflict | retracted`) and the
operator who changed it. Newer evidence supersedes the old row, which stays as history (`doctors=3` → `6`: 6 active,
3 superseded). Weaker evidence becomes a `conflict`. Evidence observed before the current fact (late delivery) is
stored as history only. A human fact always wins. Operators can correct (reason required), verify, or retract (the
key becomes unknown, with no silent fallback). API: `/customers/<id>/memory[...]`.

### 17.4 Tool risk registry — `brain/registry.py`

Every tool declares an input/output schema, a permission, a risk class (`READ_ONLY`, `LOW_RISK`, `MEDIUM_RISK`,
`HIGH_RISK`, `NEVER_AUTOMATIC`), idempotency (`per_customer | per_approval | natural`), a verification function
that checks the post-condition in the system of record, and audit fields.

- The Policy Engine (`policy.decide`) authorizes from the registry plus flags only.
- The executor (`tools.authorize`) re-checks every call:
  - The agent may run only READ_ONLY/LOW_RISK tools, and only when their flag allows.
  - MEDIUM/HIGH tools run only from an approved, unchanged plan.
  - NEVER_AUTOMATIC tools never run.
- Output is schema-validated and verified. `GET /tools/registry` exposes the registry.

### 17.5 Approval preview and plan hash

`approvals.build_plan` produces the exact plan:

- **Account creation:** customer, business type, specialty, plan, size, modules (from the real feature catalogue),
  tenant actions, users (admin, one-time password, must change), trial/billing, and contact presence (no raw data).
- **Discounts:** percent, agent limit, and "billing unchanged".

`plan_hash` = HMAC-SHA256(SECRET_KEY, canonical plan), with a `plan_version`. A decision must quote the hash the
operator saw. Missing, forged or old hashes, a tampered stored plan, and a replayed decision are all refused (409).
If the plan changed since review, the old approval is superseded, a new version is created, and nothing executes.
Execution uses exactly the stored arguments. On the desktop, a plan with a preview can only be approved from the
full card ("مراجعة الخطة" on the orb bar).

### 17.6 Merge suggestions

`GET /merge-suggestions` returns masked identifiers for both sides (`+964*******567`, `s***@g***.com`, `…1234`) plus
the matched identifier. The decisions are **Merge**, **Keep separate** (remembered: the pair is never suggested
again) and **Dismiss**. A merge writes an `FcCustomerMerge` ledger of the moved rows, and `POST /merges/<id>/revert`
restores them exactly. Everything is audited. Merges are never automatic.

### 17.7 Knowledge workflow

Docs carry: version, business type, module, feature, supported plans, effective from/until, author, revision note
and reviewer.

- Workflow: `draft → in_review → published → retired`, plus `reject`.
- Every transition is an `FcKnowledgeEvent`. Publishing or retiring bumps the global `knowledge_version`, which each
  agent run records.
- Customer-facing means: published, inside the effective window, and matching the customer's business type (and
  plan, when known).
- A verified source is mandatory. FINORA CORE writes no content.
- Access is through the API (`/knowledge…`) and the CLI (`flask finora-knowledge draft … --business-type --plans
  --effective-from`).

### 17.8 Observability

`fc_agent_runs` records:

- mode, model, prompt version, knowledge version, intents and top confidence;
- latency and tokens;
- estimated cost (USD; prices are configurable via `FINORA_CORE_MODEL_PRICES`, and unknown models get no guess);
- a redacted trace: proposed actions, policy verdicts with risk class, executed tools with verification, approvals,
  guards and the result.

Phones, emails, tokens and secret-named fields are masked. Model reasoning is never stored.
API: `/agent-runs`, `/agent-runs/<id>`.

### 17.9 Security tests (`tests/test_finora_core_phase9.py`)

The suite covers:

- prompt injection;
- AI replies exposing keys or tokens (new reply guard: secret-like content blocked);
- a customer asking for another customer's data (new reply guard: contact data that is not the customer's own is
  blocked);
- an invalid tenant id in conversation text;
- unauthorized roles and forged tokens;
- cross-tenant access (other tenants' conversations are unreachable);
- forged, replayed, modified-after-review and tampered approvals;
- hostile model plans and forbidden executor calls;
- password leakage end to end;
- the v3 upgrade/downgrade.

### 17.10 Completion gate (2026-10-03)

| Gate | Result |
|---|---|
| FINORA CORE + credential backend tests | 153 passed |
| Desktop `npm run verify` (format, lint, typecheck, 56 vitest, build) | pass |
| Browser regression (mocked Playwright, incl. visual baselines) | 23 / 23 |
| Live integration (real server, incl. new `shadow.spec.ts`) | 12 / 12 |
| Credential leak tests | pass (`test_credential_security.py`, 11) |
| Tenant isolation tests | pass |
| Shadow Mode E2E | pass (backend + live desktop) |
| `ai_sales` regressions | none — 66 passed, exactly the 9 known failures (§15, own task) |

Out of scope, flagged as a separate task: shipping-company portal passwords are stored and compared in plaintext
(`routes/shipping.py`, `routes/delivery.py`).
