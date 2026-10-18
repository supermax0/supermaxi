# FINORA AI + MCP — Phase 1 implementation and verification

Status: implementation in progress; not yet accepted as production-complete.

## Persistent external MCP connections — 2026-09-17

Settings support a named, per-application key with explicit continuous-access
consent. Keys have no time expiry and remain valid until revoked. They are not
non-expiring JWTs: the existing 15-minute JWT option remains unchanged. The new
fifth additive table, `finora_mcp_connection`, stores only a SHA-256 verifier
of a random 256-bit secret, plus tenant/owner/name/creation/revocation metadata.
It does not change business tables or enable financial write tools.

The owner sees the masked credential only at creation and can copy it into the
external application's Bearer token field. Listing never returns credentials
or hashes; secrets are not retained in browser storage and are cleared on page
exit. Hiding a credential is not revocation. The list offers an idempotent revoke
action, including when the assistant or its permission has been disabled.
Issuance requires settings and assistant permissions, valid input, enabled MCP,
rate limits and a non-default server secret. The limit is ten active keys per
owner. Creation/listing responses use no-store headers.

Both the Flask compatibility endpoint and official SDK transport check the
stored verifier and revocation status on each bearer request, then reload the
active employee and existing permissions. Inactive/expired tenants, disabled
employees, removed assistant permission and disabled AI/MCP settings stop
persistent access. Tokens cannot override account or branch scope. Incoming
cookie identity/branch flags and ORM identity-map objects are discarded before
switching to the verified bearer identity, preventing overlapping employee IDs
from another tenant being reused. Bearer requests do not issue reusable Flask
login cookies that could bypass token expiry or revocation.

This follows the [OWASP REST security guidance](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html)
on HTTPS, access control, protecting API keys and revocation. A copied key grants
ongoing read access within the owner's permissions: use only a trusted app and
revoke immediately if exposed. Revocation blocks new requests; already-running
requests are not retrospectively cancelled. This is manual per-app key linking,
not an OAuth refresh flow or a guarantee of automatic reconnection by clients.

Official SDK production routing and HTTPS remain deployment requirements. No
production key was created, no production database was modified, and these
local changes have not been deployed. Browser acceptance of the new controls
has not been performed. Verification: 79 tests passed and one explicit live
provider test was skipped. This includes both MCP transports, long-lived keys,
owner isolation, explicit consent, verifier-only storage, revocation, disabled
access, malformed keys and cookie/bearer tenant-cache isolation. The full app
against temporary databases verified issuance, fresh-client discovery with all
26 tools, no login-cookie issuance, missing-bearer rejection and immediate
rejection after revocation. Python compilation, settings JavaScript syntax and
Jinja template parsing passed. Existing dependency/configuration warnings remain.
Older sections retain historical results.

After deployment, open AI settings → external app linking, enter the app name,
acknowledge continuous access, and choose **إنشاء مفتاح ربط دائم**. Copy the
credential into the app's Bearer token field without adding the word Bearer;
copy the MCP URL separately. Use **إلغاء الرابط** in the account's connection
list to stop future requests. A key cannot be recovered after leaving the page;
revoke a lost key and create a replacement.

## Language/context and delivery-agent understanding — 2026-09-17

The current question's entity type takes priority over old order/customer IDs.
Context tracks a tool-resolved active entity, unresolved agent questions and
permission-checked lookup candidates. New search results refresh identity context;
multiple/empty/failed lookups do not silently reuse the old identity. Duplicate
normalized names require an ID or ordinal choice. Context is refreshed inside
each tool round so the model sees newly resolved entities immediately.

The bounded builtin fallback now handles common Iraqi phrasing, Arabic digits,
clean named lookups, explicit candidate selection, greetings and clearer missing
tool/permission responses. Arabic name searches normalize common alif/yaa/taa
marbuta and vowel variants on both sides without selecting an ambiguous identity.
Relative periods include yesterday, current/previous month, current/previous
Sunday-based week and trailing days using Baghdad time. Unrecognized periods ask
for date bounds rather than silently querying today. This is still not general
language understanding; no universal understanding is claimed.

Four tools bring the catalog to 26: `search_delivery_agents`,
`get_delivery_agent_reports`, `get_agent_report`, `get_pending_agent_reports`.
They reuse `serialize_pending_report` and existing `view_agents` permission,
tenant and automatic branch isolation. Reports referencing inaccessible invoices
are excluded rather than falling back to financial snapshot data. Results show
delivered/returned/postponed/pending amounts and execution status, explicitly
not a consolidated agent debt or proof of cash received. Results are limited,
not summed into an agent balance. No report execution, payment or business save
helper is called.

The language-model system policy clarifies entity switches, Iraqi terms, relative
dates, fresh-tool grounding, report-vs-order identifiers and financial scope.
Tool descriptions explain when to use the agent tools. This follows the
[official function-calling guidance](https://developers.openai.com/api/docs/guides/function-calling)
on explicit tool descriptions and application-side tool execution.

The chat exposes its actual language-model vs limited mode through an authenticated
no-store runtime endpoint and streamed mode event. OpenAI without a configured
key gives a setup response without sending an external request. A settings preset
prepares OpenAI fields but requires normal explicit saving; saved builtin settings
are not silently switched. The preset preserves a specified model and otherwise
uses the existing project default, not a claimed latest/best model. Disclosure
mentions external processing and separate API costs. No key was changed/exposed.

Verification includes the real full-app temporary-database sequence: customer
search/balance → latest order → unnamed agent clarification → named agent report.
The server discovered all 26 read-only tools and rejected unauthenticated MCP.
HTTP smoke covers all 26 envelopes. Regression checks cover dialect routing,
candidate ambiguity, active supplier vs stale customer, missing credentials,
RBAC, hidden-branch snapshot filtering and unchanged business report snapshots.
This increment did not run a paid/live language-model request or browser acceptance
of the new mode/preset controls. These remain separate checks; local changes are
not a production deployment. Earlier sections below are historical snapshots.
Latest automated result: 60 passed, one explicit live-provider test skipped.
Python compilation, both chat/settings JavaScript syntax checks and scoped diff
whitespace checks passed. Existing dependency/configuration warnings remain.

## Chat redesign and expanded read tools — 2026-09-17

The RTL floating chat now has a wider reading area, an expand/collapse control,
four starter questions, differentiated user/assistant messages, and horizontally
scrollable Markdown tables. Completed replies support copying, requesting the
answer again and asking for clarification. Restored history also retains the
preceding user prompt for the repeat-answer action. Rendering uses DOM text
nodes rather than inserting model-provided HTML.

Four tools were added, bringing discovery to 22 read-only tools:
`get_latest_order`, `get_expenses`, `get_top_products`, `get_shipping_dues`.
They reuse existing FINORA read helpers and backend permissions. Top-products
data requires profit permission, shipping dues require financial permission,
and expense data requires expense permission. Latest orders exclude drafts and
deleted invoices and retain order-status/branch policy and cost filtering.
Order IDs returned by trusted tools are remembered for subsequent questions
about dates, employees and status; each follow-up refetches the order.

The builtin provider now presents these results as readable tables and supports
the corresponding narrow Arabic questions. It remains a limited deterministic
assistant, not a language model. Unknown employee data is labeled as unrecorded.

Verification: 31 automated tests passed, with one default live-provider skip.
The synthetic HTTP smoke covers all 22 tools and their output envelopes; a
regression verifies latest-order → employee follow-up and persisted tool audit.
The full temporary-database runtime discovers 22 tools. The redesigned welcome
screen was checked interactively. Reply-action and responsive browser acceptance
remain unverified: after restarting the runtime, the browser could not attach a
new test tab through either documented creation API. A long-running temporary
browser runtime exhausted its database connection pool and was restarted; this
is not claimed resolved by the chat design changes. No production deployment or paid provider request was made
for this increment. Earlier verification results below are historical snapshots.

## Easy external MCP connection

Settings now include an external-app connection card: FINORA server name,
Streamable HTTP transport, copyable URL, on-demand 15-minute JWT generation,
masked token and copy/clear controls. No token is persisted in browser storage;
it is cleared on page exit and after its expiry. Clearing the field is not
server-side revocation. Tokens inherit the authenticated account scope; users
must trust the external application before entering them. Token responses use
no-store headers, issuance is rate-limited, disabled MCP returns a safe failure,
and weak signing configuration returns a safe 503 instead of an internal error.

The URL comes from server config `FINORA_MCP_PUBLIC_URL` when supplied, otherwise
the current origin plus `/mcp`. This is a connection address, not a verified
official-transport deployment. The UI explicitly warns that official SDK
routing must still be configured and that localhost is machine-local.
The token must be regenerated after expiry; automatic client refresh is not
implemented. Tests cover the connection metadata, scoped expiry, no-store,
disabled/weak-signing guards and template controls. No live token was generated
or entered into a third-party app during implementation.

## Advanced settings redesign — 2026-09-17

The settings page now uses responsive RTL cards, section navigation, compact
accessible switches, provider-specific help, loading/error/retry states,
unsaved-change feedback and reset-to-saved controls. Scoped styles are in
`static/css/finora-ai-settings.css`; existing application layouts are preserved.
MCP/accounting/local-provider flags are editable, financial writes stay locked,
and encrypted tenant keys can be cleared without revealing them. Clearing a
tenant key does not clear the server environment key. Empty model/endpoint
values can now be saved intentionally. Invalid flag types and credential-bearing
or malformed endpoints are rejected. Disabling AI does not block settings access.

Local-provider selection enforces its feature flag at save and execution time.
Automatic selection uses OpenAI when a key is available and otherwise the builtin
assistant; it is not error failover. Context size now bounds prior message history
using an approximate three-characters-per-unit budget, preserving system policy
and latest input. System/tool definitions/results are outside this history budget.

Verification: 26 automated tests passed, one default live test skipped; full-app
temporary-database smoke passed. Browser checks verified the card layout, saving
90-second timeout, reset after changing to 120, and persistence after reload.
At a 390px viewport, the page had no horizontal overflow. Theme tokens support
both themes; this interactive pass used the dark theme. No production deployment
or paid provider request was made for this redesign.

## Architecture and reusable logic

Flask/Jinja UI → FinoraAIOrchestrator → ModelRouter/AIProvider → MCPClient →
read-only registry → FINORA read service → existing tenant-bound SQLAlchemy
session, RBAC helpers, accounting and inventory helpers.

`DynamicTenantSession` selects a separate database per authenticated tenant.
The MCP facade and model providers do not query the database. New read adapters
live in `modules/finora_ai/services.py`; existing helpers in
`utils/ai_assistant_tools.py`, `utils/cash_calculations.py` and the existing order
permission policy are reused. No business writes or accounting-entry creation
are exposed.

## Files created

- `modules/finora_ai/{__init__,context,models,schema,services,tools,mcp,sdk_server,tokens,providers,settings,security,orchestrator,routes}.py`
- `templates/finora_ai_settings.html`
- `static/css/finora-ai.css`
- `static/js/finora-ai.js`, `static/js/finora-ai-settings.js`
- `tests/test_finora_ai_phase1.py`, `tests/test_finora_ai_integration.py`
- `tests/test_finora_ai_tenant_isolation.py`, `tests/test_finora_mcp_sdk.py`, `tests/test_finora_ai_customer_balance.py`
- `scripts/verify_finora_ai_provider.py`, `scripts/verify_finora_ai_runtime.py`

## Files modified

`app.py`, `app_server.py`, `models/__init__.py`, `templates/base.html`,
`requirements.txt`, `.env.example`. Existing unrelated working-tree edits were
preserved. No commit or production deployment has been made.

## Schema changes

Four additive indexed tables: `finora_ai_conversation`, `finora_ai_message`,
`finora_ai_tool_call`, `finora_ai_settings`. Bootstrap creates only these new
tables in the authenticated tenant database. No existing columns are changed
and no tables are removed. Formal versioned migration/rollback tooling remains
to be integrated; bootstrap is not represented as a completed Alembic migration.

## MCP endpoints and tools

- Additive Flask JSON-RPC endpoint: `/mcp`; `/mcp/health`, `/mcp/ready`.
- Official Python MCP SDK Streamable HTTP ASGI application:
  `modules.finora_ai.sdk_server.create_mcp_asgi(flask_app)`.
  Deployment must explicitly route `/mcp` to this application to use the official
  SDK transport. The existing Flask endpoint is not the official SDK transport.
- JWT issuance for authenticated users: `/finora-ai/api/mcp/token`, 15-minute
  expiry, explicit `finora-mcp` audience and `finora` issuer.

Implemented read-only names: `search_customer`, `get_customer`,
`get_customer_balance`, `get_customer_statement`, `search_orders`, `get_order`,
`search_products`, `get_product`, `get_product_stock`, `get_low_stock`,
`search_supplier`, `get_supplier_balance`, `get_supplier_statement`,
`get_daily_sales`, `get_sales_summary`, `get_cash_balance`,
`get_receivables_summary`, `get_payables_summary`, `get_latest_order`,
`get_expenses`, `get_top_products`, `get_shipping_dues`, `search_delivery_agents`,
`get_delivery_agent_reports`, `get_agent_report`, `get_pending_agent_reports`.

## Authentication, tenancy and RBAC

Signed FINORA session or validated short-lived JWT → tenant slug and employee
ID → active employee loaded from that tenant DB → existing backend permission
helpers. Roles and permissions never come from model arguments or JWT role
claims. Tool arguments cannot set tenant/user/role/permissions. Execution
rejects a mismatched current tenant, and conversation reads require both owner
and tenant. Tool discovery is permission-filtered and permissions are checked
again during execution. The existing admin policy is reused, not redefined by
MCP. Order details additionally enforce FINORA order-status permissions.

## Providers, UI and persistence

OpenAI-compatible adapter supports OpenAI and compatible local endpoints
(Ollama/LM Studio/vLLM). A deliberately narrow builtin non-LLM read assistant
is also available and is clearly distinguished from local language models.
Native Anthropic/Gemini adapters and failover are not implemented.

OpenAI-compatible responses use upstream SSE streaming, tool argument
assembly and a bounded multi-tool loop. The RTL floating side panel includes
loading/tool states, stop, new conversation, safe DOM-only Markdown/table
rendering, conversation history selection and restoration of the last conversation.
Failed/stopped responses include an explicit retry control. Settings at `/finora-ai/settings`
require backend settings permissions; API keys are encrypted server-side and
never returned. Existing `OPENAI_API_KEY` may be used in memory without copying
the secret into tenant databases. Page context includes only minimal entity
hints, not full page contents.

Messages retain provider/model and usage metadata. Tool audit rows retain
tenant/user/conversation, sanitized arguments, tool, status, safe error code,
timestamps and latency. Secrets are excluded from the supported argument
schemas and scrubbed from audit arguments. `/finora-ai/api/metrics` provides
tenant-scoped basic request/tool/failure/latency counts. Cost estimation and
broader observability remain incomplete.

## Security measures and remaining hardening

JSON Schema validation, bounded inputs/search results, safe error responses,
backend RBAC, tenant context checks, Origin checks, request-size limits,
in-process rate limits and SDK DNS-rebinding/Host controls. Strong token-signing
configuration is required; the known default application secret cannot issue
MCP bearer tokens. Production requires HTTPS at the reverse proxy.

Remaining: shared Redis rate limiting, complete Host enforcement for the Flask
transport, dedicated schema deployment, tool-specific data output schemas, cancellation
verification, and broader branch/financial authorization tests. Customer
balance now reuses the receipts service invoice eligibility filter (excluding
draft/deleted/canceled/returned/wholesale invoices), existing effective-paid
logic, and unlinked credit-plan remaining balances. Linked plans are not added
twice. Results explicitly identify this retail/credit scope; wholesale and
cross-module consolidated ledger parity remain outside this verified scope.
The new regression test verifies these cases and that no business entity is
mutated. No write tools, approvals, idempotent financial operations or
autonomous financial agent are enabled.

## Tests executed so far

- 15 automated tests passed (one explicit live-provider test skipped by default).
- All 18 read-only tools succeeded against synthetic ORM records through the
  HTTP MCP endpoint; response envelopes were checked against the published
  output schema. Detailed per-tool data schemas remain a follow-up.
- Separately opted-in OpenAI live acceptance test passed: synthetic customer
  search → balance → today's sales, maintaining one conversation and three
  audited tool calls. These results are against synthetic ORM data, not a live
  company's production records.
- Two isolated tenant databases with overlapping IDs were verified.
- Official SDK initialization, unauthenticated requests, JWT expiry, permission
  filtering, identity overrides, audit persistence and prompt-injection handling
  were exercised.
- Small OpenAI connectivity request succeeded, using 19 total tokens and no
  business data.
- Full FINORA startup against temporary databases passed, including the actual
  existing login route, authenticated discovery of 18 tools, rejection of
  unauthenticated MCP, settings/floating-chat template rendering, streamed
  customer search and a contextual follow-up balance of 300,000 IQD.
- This full-app check discovered detached branch ORM objects after streaming
  request teardown. The streaming route now snapshots only backend-authorized
  branch identifiers/default flags, retaining branch isolation without keeping
  detached ORM objects. The full-app verification passed after this fix.
- Official SDK requests now reject inactive/expired tenant subscriptions for
  cookie authentication as well as bearer authentication; a negative SDK test
  covers the transport guard.
- Interactive browser verification passed against the full temporary-database
  FINORA runtime: existing login, settings page, floating panel, customer search,
  contextual 300,000 IQD balance, history list and persisted-message restoration.
  The provider in this browser check was the explicitly labeled builtin assistant,
  not OpenAI. Browser timings were slow and some navigation calls timed out;
  successful states were verified after re-observation. Responsive/light-mode,
  cancellation/retry and live-provider browser checks remain pending.
- Python compilation and JavaScript syntax checks passed. This report does not
  claim the complete Definition of Done.

## Requested 18-item delivery checklist

1. Architecture implemented: layered UI/orchestrator/provider/MCP/service flow.
2. Files created: listed above, including four isolated test modules and two verification scripts.
3. Files modified: listed above; unrelated work preserved.
4. Database migrations: four additive tables bootstrapped; versioned deployment/rollback pending.
5. MCP endpoint: Flask compatibility endpoint plus official SDK ASGI factory; production routing pending.
6. MCP tools implemented: all 26 read-only tools listed above; no write tool exposed.
7. Authentication flow: existing FINORA sessions or short-lived scoped JWT, active backend employee and subscription checks.
8. Tenant isolation implementation: authenticated tenant DB selection, forbidden identity overrides, owner-scoped conversations.
9. RBAC implementation: existing backend helpers for discovery and execution, including order status policy and cost filtering.
10. AI providers implemented: OpenAI and local OpenAI-compatible adapters, narrow builtin fallback; native Claude/Gemini deferred.
11. Chatbot UI implementation: RTL floating panel, streaming, tool states, history, stop/new/retry and safe Markdown.
12. Conversation storage: tenant-local conversations/messages/context and provider/usage metadata.
13. Audit logging: tenant/user/tool/sanitized arguments/status/error/latency; no secret exposure.
14. Security measures: input/output envelope schemas, bounds, Origin controls, rate limits, JWT expiry, SDK Host guards.
15. Tests executed: dialect/context regression, unit, ORM integration, 26-tool HTTP smoke, two-tenant isolation, SDK auth/expiry/subscription, earlier live OpenAI acceptance, full-app runtime.
16. Test results: latest suite 60 passed/1 default live skip; full-app temporary-database sequence passed; earlier opted-in live acceptance passed; see increment-specific live/browser limitations above.
17. Remaining limitations: broader browser coverage, cross-module consolidated ledger parity, formal migrations, SDK deployment routing and distributed hardening.
18. Recommended Phase 2: finish read-only acceptance/hardening first; only then explicit-confirmation, idempotent audited writes through existing services.

## Phase 2 recommendation

Do not enable write tools yet. First finish browser/real-service read acceptance,
ledger parity, complete tool authorization and deployment hardening. Then add
prepare/preview/explicit confirmation/execute/verify workflows through existing
business services, atomic transactions, durable idempotency and audit trails.
