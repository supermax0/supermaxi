# Task: make the full backend suite green — 9 pre-existing `ai_sales` failures

Status: **open** · Owner: unassigned · Created: 2026-10-03 (Phase 9 of FINORA CORE)

## Why

These nine tests fail on `main` independently of FINORA CORE. That was verified in Phase 7 by re-running them with
the FINORA CORE / Phase 7 changes reverted, and they fail the same way. Each phase since then has checked that the
failing set is unchanged ("no new `ai_sales` regressions"). They hide real regressions behind a red suite, so the
repository can never reach a fully green run until they are fixed. Do this in its own change set, not inside a
FINORA CORE phase.

## The failing tests

| # | Test | Area |
|---|---|---|
| 1 | `tests/test_ai_sales_foundation.py::test_meta_webhook_routes_page_to_configured_employee` | Meta webhook → employee routing |
| 2 | `tests/test_ai_sales_foundation.py::test_meta_multi_page_management_keeps_tokens_private_and_scales_past_thirty_pages` | Meta page management |
| 3 | `tests/test_ai_sales_foundation.py::test_inbox_read_close_reopen_and_incremental_messages` | Inbox |
| 4 | `tests/test_ai_sales_foundation.py::test_message_actions_and_manual_media_delivery` | Inbox actions / media |
| 5 | `tests/test_ai_sales_employee_page_scope.py::test_employee_only_sees_conversations_from_registered_pages` | Employee page scope |
| 6 | `tests/test_ai_sales_intelligence.py::test_product_knowledge_api_persists_grounded_sales_data` | Product knowledge API |
| 7 | `tests/test_ai_sales_intelligence.py::test_price_objection_uses_remembered_product_and_offers_cheaper_live_alternative` | Sales agent reasoning |
| 8 | `tests/test_ai_sales_meta_ad_context.py::test_messenger_regular_sticker_is_not_treated_as_image` | Messenger stickers |
| 9 | `tests/test_ai_sales_nearest_selection.py::test_nearest_appliance_size_cheapest_screen_and_product_details` | Product selection |

Reproduce:

```bash
python -m pytest -q tests/test_ai_sales*.py -p no:cacheprovider
```

## How to approach it

1. Classify each failure first:
   - **(a) Stale test.** The behaviour changed on purpose, so update the assertion and record why in the commit.
   - **(b) Real product bug.** Fix the code, and keep or strengthen the test.
   - **(c) Environment or fixture problem.** Examples: a missing seed, test ordering, or a real network/AI call. Fix
     the fixture so the test is hermetic, with no real Meta or OpenAI calls.
2. Never delete or `skip` a test to get green. If a test's premise is obsolete, replace it with one that covers the
   current behaviour.
3. Groups 1–5 all touch Meta routing, page tokens, and inbox flows that Phase 7 also hardened. Check them against the
   Phase 7 contracts (fail-closed signatures, dedupe index, receipts) before changing any assertion.
4. Make sure no FINORA CORE test regresses:

   ```bash
   python -m pytest -q tests/test_finora_core_*.py tests/test_credential_security.py
   ```

## Done when

- `python -m pytest -q tests/test_ai_sales*.py` has 0 failures.
- The full backend suite is green.
- `docs/finora-core-architecture.md` §15 is updated to say the debt is resolved, with the commit reference.
