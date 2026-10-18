# System Analyzer + Knowledge Coverage (Phase 6)

The analyzer **discovers, compares and reports**. It never edits the knowledge registry, tutorials or any user data.

```
static scan ──┐
runtime scan ─┼─▶ catalog ─▶ validation ─▶ snapshot (system_map JSON) ─▶ diff ─▶ Super Admin System Map
registry ─────┘     │                                   │
tutorials ──────────┘                                   └─▶ chat (read-only: discovered features, withheld tutorials)
```

## Static scan (`modules/ai_tutor/analyzer/static_scan.py`)
Reads `templates/clinics/*.html` and `static/clinics/*.js` and extracts `data-finora-page|section|action|field`, plus actions that JS sets at runtime through the `finoraAction:` modal option. Template placeholders (`${fp}`, `${staffType}`, `{{ clinics_page }}`) are expanded to the values the UI really renders; unresolved ones are reported, not guessed. It also records the best literal label of each action, and reads (without importing the app) `PAGE_CONFIG` (pages, routes, permissions), `CLINICS_PERMISSIONS` and every `@clinics_bp` backend endpoint with the permission its `@require_clinics(...)` demands. Categories: `feature`, `navigation`, `chrome`, `submit` (save buttons), `structure`.

## Runtime scan (`scripts/ai_tutor_runtime_scan.mjs`, dev/CI only)
Playwright crawler for a **test** clinic account: visits every page reachable from the sidebar, records element, page, route, visible state, modal state, label, whether the page was accessible to that account. It may click only an explicit allow-list of form openers (`appointment.create`, `doctor.create`, `employee.create`, `patient.create`, `specialty.create`) and closes the modal with Cancel. Anything that changes state (`appointment.checkin`, `queue.add`, `visit.start`, `invoice.create`, every `*.save`) is never on the list. Anything classified `destructive`, `financial` or `irreversible` (including every save button) is listed as skipped and never clicked, and the crawl counts same-origin write requests (must be 0; third-party beacons are reported separately).
```
AI_TUTOR_SCAN_URL=http://127.0.0.1:5008 AI_TUTOR_SCAN_TENANT=<slug> AI_TUTOR_SCAN_USER=<u> AI_TUTOR_SCAN_PASSWORD=<p> \
  node scripts/ai_tutor_runtime_scan.mjs --out runtime.json
python scripts/analyze_ai_tutor.py --runtime runtime.json --write
```
Runtime results can also be uploaded to `POST /superadmin/ai-tutor/system-map/runtime` (validated: schema, id syntax, ≤ 6000 elements, ≤ 1.5 MB).

## Catalog, statuses, coverage
Every id becomes an item with: discovered (static/runtime), knowledge registered, tutorial registered, verified, permission mapped. Statuses: `verified` · `discovered` · `knowledge_missing` · `tutorial_missing` · `broken` · `stale` · `disabled`.
* not discovered but referenced by a tutorial → `broken`; referenced only by the knowledge registry → `stale` (never deleted);
* discovered, no knowledge → `knowledge_missing`; feature without a tutorial → `tutorial_missing`; plumbing (chrome/submit/navigation) is `discovered` unless a verified tutorial uses it.

Four separate measures (never merged): **System Discovery** (pages with `data-finora` metadata; actions confirmed at runtime), **Knowledge**, **Tutorial**, **Verified Tutorial** — each as `n / discovered` for all actions and for feature actions alone, plus tutorial counts.

## Tutorial validation
Per tutorial: every target/reveal/watch/branch id exists, page ids and navigate routes exist, `wait_api_success` matches a real backend rule, validators and permissions exist, dependencies exist and are runnable, page permission is declared. Errors make the tutorial `broken`; "not seen at runtime" is only a warning. A tutorial the analyzer finds broken is **withheld from users** (`registry.is_runnable`) as long as the snapshot still matches the sources (fingerprint).

## Snapshot + diff
`instance/ai_tutor/system_map/` (override `AI_TUTOR_SYSTEM_MAP_DIR`): `latest.json`, `runtime.json`, `history/` (last 10). Meta: `app_version`, `git_commit`, `created_at`, `pages/actions/fields/sections_count`, `runtime`, `fingerprint` (a snapshot is **stale** when sources or registries changed). Each scan diffs against the previous snapshot: new / removed actions, changed pages or targets, newly broken / fixed tutorials, status changes; new items are flagged `new`. Nothing runs during normal requests (the chat reads the cached snapshot, 30 s).

## Super Admin page
`/superadmin/ai-tutor/system-map` (Super Admin only, 403/redirect for everyone else): cards, the four coverage blocks, diff, tabs (Actions / Fields / Sections / Pages / Tutorials incl. dependencies), filters (All, Missing Knowledge, Missing Tutorial, Broken, Verified, Newly Discovered, Stale), search, category filter, "Run scan". In test environments only (`AI_TUTOR_ANALYZER_SIMULATION=1` or `TESTING`) a simulation box pretends an element vanished; simulated scans are never saved.

## CI
`python scripts/analyze_ai_tutor.py` (`npm run analyze-ai-tutor`): static scan + registry validation + verified-tutorial validation. Exit 1 only when a tutorial declared `verified` is broken (or a runtime scan wrote data); missing knowledge/tutorials are warnings. `--write` saves a snapshot, `--runtime FILE` merges a crawl, `--json` prints everything. Runtime scan is a separate job.

## Chat integration
Three honest answers: *feature does not exist* → "ما لقيت هذه الميزة ضمن النسخة الحالية."; *exists without a lesson* → "الميزة موجودة بالنظام، لكن الشرح التفاعلي الخاص بها بعده غير متوفر." (+ where it is, Show Me only); *has a lesson* → suggestion. Discovered-but-unregistered features need a label to be findable and never get steps. Show Me falls back to the sidebar when the scan no longer finds a target, and users never get suggestions for pages they lack permission for ("ما عندك صلاحية تنفيذ هذه العملية.").

## Phase 7 additions
* **Page ownership**: an element belongs to the page named after its source file (`patients.js` → `patients`, `appointments.js` → `appointments`) or to its id prefix (`appointment.*`, `schedule.*`, `specialty.*`, `doctor.*`/`staff.*` → their pages). `nav.*`/`modal.*` are global.
* **Dynamic ids** are declared in `static_scan.EXPANSIONS` (`${fp}`, `${staffType}`, `${group.key}` → the 5 permission groups, `${openAction(a.status)}` → the 4 appointment-card actions) so the scan stays honest and `unresolved` stays empty.
* **Plumbing is not a feature**: ids ending `.open`, `.select`, `.apply`, `_pick`, or containing `.open.` / `.tab.` are `chrome`; they appear as steps of lessons, never as "feature without a lesson".
* The scan cache for `PAGE_CONFIG`/`CLINICS_PERMISSIONS` is keyed by file mtime (the routes file is large).
* A test-only `POST /superadmin/ai-tutor/system-map/reset` (needs `AI_TUTOR_ANALYZER_SIMULATION=1` or `TESTING`) lets a browser spec own its snapshot state.
