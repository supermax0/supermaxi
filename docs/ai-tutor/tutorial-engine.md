# Tutorial engine (vertical slice: `doctor.create`)

## Layout
- Backend `modules/ai_tutor/`: `registry.py` (strict JSON validation), `tutorials/*.json`, `routes.py` (`/api/clinic/ai-tutor/*`, gated), `validators.py` (server-side real-state checks), `models.py` (`user_training_progress`, `training_activity_logs` in the tenant DB, created lazily).
- Frontend `static/ai-tutor/` (ES modules, emitted only when `feature_enabled('clinic_ai_tutor')`):
  `engine/core.js` (pure logic) · `machine.js` (state machine) · `targets.js` (discovery/recovery) · `waiters.js` (click/input/fetch/state) · `api.js` · `engine.js` · `ui/` (replaceable parts) · `loader.js`.

## State machine
`IDLE → STARTING → RUNNING ⇄ WAITING_FOR_USER ⇄ VALIDATING`, plus `PAUSED`, and terminal `COMPLETED / FAILED / CANCELLED` (`reset` → `IDLE`). Illegal transitions throw. Unit-tested.

## Targets
Only `data-finora-page|section|action|field` identifiers (`{"action": "doctor.create"}` in JSON → `[data-finora-action="doctor.create"]`). Ids are validated against `^[a-z0-9][a-z0-9_.-]*$`; text/nth-child selectors are impossible. Recovery: wait for render (2.5 s) → click declared non-destructive `reveal` controls (sidebar button, collapsed nav group) → wait again → diagnostic (`target_missing` event, tutorial paused) and a card offering rewind/end. A step whose target disappears for ~1.6 s while active is treated the same way.

## Waiting
`wait_click` (document capture listener) · `wait_input` / `wait_select` (condition re-evaluated on input/change/click/DOM mutation; "next" enabled only when valid) · `wait_modal` (target visible) · `wait_api_success` (passive `fetch` observer: method + URL regex, success = HTTP ok **and** `body.ok !== false`; failures show the backend error and keep waiting) · `wait_state` (polls `POST …/verify`, server checks the DB).

## Progress
`POST …/start` creates/resets the row; each finished step sends `step_completed` with `next_step_id` (forward-only server-side; `rewind` is the only way back). A `sessionStorage` marker covers page navigations that race the save (click steps save with `keepalive`). `GET …/active` resumes on every page load; a tutorial whose version changed is discarded. `POST …/complete` re-runs the validator (422 if the result is not real). Logs hold tutorial/step ids, events and timestamps only.

## Status gate
`verified` runs for users; `draft/needs_review/broken/disabled` do not (authors may set `AI_TUTOR_ALLOW_DRAFT=1` locally).

## Presenter port
`ui/presenter.js` documents the contract; `createPresenter({parts})` composes overlay, spotlight, pointer, card and motion controller. The Phase-2 UX/motion layer (smart positioner, spotlight morph, bottom sheet, unified launcher, onboarding) is described in [ux-motion.md](ux-motion.md); reconcile/back/dependency/exit contracts are described there too.

## Running the tests
```
python -m pytest tests/test_feature_management.py tests/test_ai_tutor_backend.py
node --test tests/ai-tutor/engine-core.unit.mjs tests/ai-tutor/positioner.unit.mjs
python scripts/provision_tutor_e2e.py setup <creds.json>   # throwaway tenants + Super Admin
set PW_HEADLESS=1 && set PLAYWRIGHT_BASE_URL=http://127.0.0.1:<port> && set E2E_TUTOR_CREDS=<creds.json>
npx playwright test tests/ai-tutor --workers=1               # uses the installed Microsoft Edge
python scripts/provision_tutor_e2e.py cleanup
```
