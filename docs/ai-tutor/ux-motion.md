# Tutor UX + Motion system

Reference tutorial: `doctor.create` ("إضافة طبيب"); dependency tutorial: `specialty.create`.
Everything below is loaded only when `clinic_ai_tutor` is enabled (the server does not even emit the loader otherwise).

## Components (all under `static/ai-tutor/`, replaceable behind the presenter port)
| File | Responsibility |
|---|---|
| `motion/tokens.js` | **All** durations/easings (`fast 160, normal 260, move 480, slow 650`, `easeOut cubic-bezier(.22,1,.36,1)`, spring). `motionFor(win)` collapses movement to 0 and fades to 120 ms under `prefers-reduced-motion`. |
| `ui/positioner.js` | `computePlacement()` – pure geometry (node-tested). |
| `ui/overlay.js` | `TutorOverlay` (root), `TutorSpotlight` (dim + hole + ring + pulse + click ripple + success tick, morphs between targets), `TutorPointer` (1 px connector + glowing dot). Everything `pointer-events:none`. |
| `ui/card.js` | `TutorCard`: ONE persistent element (header orb/counter/minimize/pause, progress line + dots, chip, title, message, notice, footer, states instruction/information/success/warning/loading/question/error/paused, in-card exit question, bottom-sheet mode). |
| `ui/motion-controller.js` | `transitionToStep`: fade content → swap (measured) → smart scroll → placement → morph spotlight + slide card + animate height → fade content in. Follows the target with rAF. |
| `ui/presenter.js` | Port used by the engine + minimize/pause/Escape handling. `createPresenter({parts})` accepts custom parts. |
| `ui/launcher.js`, `ui/home.js`, `ui/onboarding.js` | Unified launcher, Tutor Home, first-login welcome. |
| `ui/tutor.css` | Styling on the Clinics tokens (`--cx-teal`, …), RTL, reduced-motion rules. |

## Smart positioner
Candidates left → right → bottom → top around the target, and also beside the **modal** that contains it (then a connector joins card and target). Score = order preference + clamping shift + overlap with other fields/buttons (`avoid`) + overlap with the modal (heavy) − bonus for the previous side (no flapping). A candidate that touches the target is rejected. If nothing fits, the card docks at the safest viewport spot with a connector. Safe insets come from fixed/sticky chrome (`.cx-topbar`, `.cx-mobile-nav`). ≤ 640 px → bottom sheet (≤ 42 vh) and the target is scrolled above it; 641–1024 px → floating unless the result is poor, then sheet.

## Unified launcher
The existing `#finoraAiFab` stays the only floating button. While the tutor is enabled a capture-phase listener turns its click into a small menu (المساعد / تعلّم النظام). "المساعد" replays the original click (`bypass`), and clicking the FAB while the assistant panel is open still closes it. If the button is absent a single fallback orb is created in the same spot. On `FEATURE_NOT_ENABLED` the listener is removed and the FAB behaves exactly as before.

## Engine contracts added for this phase
* `reconcileTutorialState()` — before showing a step the engine checks the real state. A step may be skipped only if it declares `reconcile`: `{kind:"ui", when:{page|visible}}` (inferable UI state, e.g. page already open, form already visible) or `{kind:"backend", validator}` (server proof, mandatory for anything irreversible such as saving). Steps without `reconcile` (user input) are never skipped. The registry rejects UI-only reconciliation of `wait_api_success/wait_state/complete`.
* **Semantic Back** — returns to the closest earlier *teaching* step (`allow_back !== false`, shown on the current page) in review mode (“مراجعة”, button «فهمت»). It never calls the backend to undo anything; steps before the frontier are review-only.
* **Dependencies + parent resume** — `dependencies:[{fact, tutorial, message_ar, action_label_ar}]`. Facts come from `/facts` (`doctors_count`, `specialties_count`). The user chooses to run the dependency; the server parks the parent (`paused`, child stores `parent_*`), and when the child completes the engine resumes the parent at the saved step. Generic (`appointment.create → patient.create` needs only JSON).
* **Exit keeps the place** (`paused`) and Tutor Home offers «متابعة». Recovery “end” still abandons.
* Titles: lesson title is always «إضافة طبيب»; the onboarding endpoint returns «إضافة أول طبيب» only when `doctors_count == 0`.

## Accessibility
Card is `role=dialog` with `aria-live=polite`, never steals focus (users type in the real fields), Tab order is natural, Escape asks for confirmation (second Escape continues), Enter never advances a click step, buttons have labels, reduced motion respected.

## Known limitations
* The spotlight morph animates `width/height` (as specified) on an isolated fixed layer; the page itself has zero layout shift, but a scale-based morph would be cheaper.
* Cached ES modules: `static/` is cached 5 min in production — bump `?v=` on `loader.js` after UI changes.
* Show-Me virtual cursor, strict mode, inline field hint, decision cards, Tutor chat field, `feature.updated` push and a dev motion lab are not built (disable arrives via the 30 s status poll or the next API call).
