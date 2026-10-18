# Tutor chat (Phase 5)

```
User message ─▶ Context builder ─▶ Intent resolver ─▶ Knowledge registry ─▶ Response (validated) ─▶ Tutorial engine
                  (ids/counts)      exact→alias→fuzzy     (features/pages/        structured JSON       (existing, unchanged)
                                    →[optional LLM]        tutorials/plan)
```
The model never touches the DOM: it can only choose an id that already exists in the registry. Show Me and "start tutorial" are executed by the existing client code.

## Modules (`modules/ai_tutor/chat/`)
| File | Role |
|---|---|
| `normalize.py` | Arabic normalisation (diacritics, hamza, ى/ي, ة/ه, Arabic digits), definite-article/clitic stripping, Iraqi synonyms → concept tokens (`شلون/شلوت`, `اسوي/اضيف/ادخل`, `دكتور/دكتر/طبيب`, `تخصص/اختصاص`, `زبون/مريض`…), typo snapping to the registry vocabulary. |
| `knowledge.py` | Registry loaded from `modules/ai_tutor/knowledge/{features,pages,plan}.json` and validated against the tutorial registry (a feature may only reference tutorials that exist). |
| `intent.py` | Deterministic resolver. Score = 0.7·recall + 0.3·precision over alias token sets, × a penalty for words that appear in no alias. ≥ 0.85 resolve · 0.60–0.84 clarify · < 0.60 not found (a near-miss hint only if ≥ 0.50 and clearly ahead). Ambiguity (two different answers within 0.10) always clarifies. Meta intents: page explanation, "what now", "why stuck", medical request, greeting. |
| `provider.py` | `TutorAIProvider` (`classify_intent`, `generate_explanation`, `clarify`), `NullProvider` (default), `OpenAIProvider` (JSON mode, 8 s, no retries). Enabled only with `AI_TUTOR_PROVIDER=openai` + `OPENAI_API_KEY`. A local model only has to implement the same three methods. |
| `privacy.py` | `redact` (emails, URLs, digit runs, 300-char cap), `allow_llm` (messages mentioning patients/clinical matters never leave the server), `build_llm_payload` (sanitised text + registry ids/titles/aliases + page and step ids). |
| `context.py` | Small context: validated page id, sanitised route (no query/ids), role, permission names, available tutorial ids, the server-side active tutorial/step (never trusted from the client), an issue label from a fixed enum. |
| `service.py` | Builds the response and `validate_response()`: plain text only (tags stripped), allowed types/actions only, tutorial ids must be available to the user, Show Me targets must be known UI ids, `choose` intents must exist. |
| `ratelimit.py` | Sliding window: 20/min per user and 120/min per tenant (`AI_TUTOR_ASK_PER_USER`, `AI_TUTOR_ASK_PER_TENANT`), per process. |

## Response contract
`{type: explanation | tutorial_suggestion | tutorial_started | clarification | not_found | error, message, tutorial_id, actions[], meta}`; actions: `start_tutorial`, `show_me`, `show_current`, `choose`, `resume_dependency`, `dismiss`. `tutorial_started` is produced by the client after a lesson starts.

## Fallback
Without a provider (or when it fails/times out) aliases, fuzzy matching, clarification, page explanations, quick actions and tutorial launch behave identically; the provider is only consulted for unclear, non-clinical messages and its answer is accepted only if it names a registry id with confidence ≥ 0.60.

## APIs (all gated: login + tenant + `clinic_ai_tutor`, 403 `FEATURE_NOT_ENABLED` when off)
`POST /api/clinic/ai-tutor/ask` `{message?, intent?, page, route, active:{issue}}` · `GET /api/clinic/ai-tutor/knowledge` (quick actions, suggested prompts, setup plan: completed / available / coming later).

## Show Me V1 (`static/ai-tutor/ui/showme.js`)
Scroll + spotlight + virtual pointer on a registry target (sidebar entry when on another page, on-page control when there). It never dispatches a click, types, or saves; during a running lesson only `show_current` (pointer on the current step's target) is available.

## Not built / Phase 6 candidates
`feature.updated` push (needs SSE/WebSocket; disable currently arrives through the 30 s poll or the next API call), persistent chat history (session-scoped by design), provider-written explanations (contract exists, off), dev motion lab, shared rate-limit store across workers, more lessons so more questions get an interactive answer, automated registry-vs-live-DOM verification (system analyzer).

## Known limitation: the rate limit is per process (documented, not changed in Phase 7)

`modules/ai_tutor/chat/ratelimit.py` is an in-memory sliding window (per user 20/min, per tenant 120/min; `AI_TUTOR_ASK_PER_USER` / `AI_TUTOR_ASK_PER_TENANT`).
Production runs `gunicorn -w 4` (`deploy/finora.service`), and each worker keeps its own counters, so the real ceiling is up to **4 x** the configured limit and
a restart resets it. The chat is deterministic and cheap (no LLM call unless a provider is configured), so this is acceptable today; it matters once an AI
provider is enabled because the limit is also the cost guard.

Why it was not moved to Redis now: Redis is **not** a general dependency of the clinics app. `redis` is in `requirements.txt` and `REDIS_URL` is only a commented
option in `.env.example`; the only code using it is the optional mobile-app module (`modules/mobile_app/services/rate_limit.py`, `shared_cache.py`).
Making the tutor depend on it would add a hard infrastructure requirement to a feature that is OFF by default.

When a provider is enabled, either (a) set `REDIS_URL` and reuse the mobile module's shared limiter behind `check_ask` (a ~20 line change; keep the in-memory
limiter as the fallback), or (b) lower the per-process limits to `limit / workers`.
