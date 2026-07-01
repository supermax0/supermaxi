You are working inside the existing Finora codebase.

The Finora AI Workspace phases 1–5 have been implemented, but the current UX/runtime behavior is wrong.

The workspace currently opens multiple floating windows on top of each other. The approval panel appears too early. LEON overlaps the document viewer. The document viewer is centered instead of being placed on the right. The report window does not stream/position correctly. Old windows remain open across workflows. The result feels like random floating cards, not an intelligent workspace.

Your task is to fix ONLY the Workspace Orchestration, Layout, Window Lifecycle, Event Handling, and UX behavior.

Do not implement new business features.
Do not implement posting.
Do not implement accounting mutation.
Do not implement inventory mutation.
Do not modify Invoice, Product, Purchase, ShippingReport, AccountTransaction, Expense, or JournalEntry.
Do not touch modules/publisher/**.
Do not add AI calls.
Do not change courier analysis logic except UI/window events if needed.

============================================================
PRIMARY OBJECTIVE
============================================================

Make the workspace behave like a true intelligent workspace:

1. Windows must open in controlled zones, not randomly.
2. Only the relevant windows for the current workflow stage should be visible.
3. Old/demo windows must close or minimize when a new workflow starts.
4. Approval panel must not appear during read-only phases.
5. LEON avatar must never overlap important windows.
6. Document viewer must be placed on the right side.
7. Live report must be placed on the left side.
8. Analysis/result windows must appear in planned zones.
9. The workspace must restore cleanly after refresh without duplicating or overlapping windows.
10. Events must update existing windows rather than create duplicates.

============================================================
CURRENT VISIBLE BUGS
============================================================

Fix these visible problems:

1. Approval panel appears even though current phase is read-only.
   - In Phase 5 Courier Settlement Read-Only Analysis, no approval panel should appear.
   - If there is an approval panel from mock workflow, close/minimize it when starting another workflow.
   - If approval panel remains for demo, it must only appear in mock_workspace, not courier read-only.

2. Document viewer is too centered.
   - It should be in the right zone.
   - It should not overlap LEON.
   - It should be large enough for PDF/image preview.

3. Report window is isolated on the left but does not stream clearly.
   - Ensure report.appended events render gradually.
   - Ensure dedup does not block new report lines.
   - Ensure refresh does not duplicate old report lines.

4. LEON avatar overlaps the document viewer.
   - Add collision-safe avatar target positions.
   - LEON should stay in center lane or move near a window without covering it.
   - Speech bubble should not cover document content.

5. Multiple windows are open together.
   - Add window lifecycle rules:
     - keep core windows: document_viewer, live_report
     - close or minimize non-relevant windows when workflow changes
     - never duplicate same window type for same session/analysis
     - stack secondary windows in lower zones

6. Top toolbar is crowded but acceptable for now.
   - Do not redesign toolbar heavily, but improve labels/active state if simple.

============================================================
IMPLEMENT A WORKSPACE LAYOUT DIRECTOR
============================================================

Create a deterministic layout system.

Suggested new file:

static/workspace/js/workspace-layout-director.js

and/or backend helper:

modules/workspace/services/workspace_layout_policy.py

Choose the simplest safe approach based on current implementation.

The Layout Director should define named zones:

desktop zones:

- left_primary:
  x: 32
  y: 130
  width: 440
  height: 600
  purpose: live_report / analysis summary

- right_primary:
  x: calc(viewportWidth - 560)
  y: 130
  width: 520
  height: 620
  purpose: document_viewer

- center_avatar:
  x: 50% viewport
  y: 46% viewport
  purpose: LEON avatar safe area

- bottom_wide:
  x: 520
  y: calc(viewportHeight - 300)
  width: calc(viewportWidth - 1040)
  height: 260
  purpose: rows table / timeline

- left_secondary:
  x: 32
  y: 760 or responsive lower position
  width: 440
  height: 260
  purpose: issues / notes

- right_secondary:
  x: calc(viewportWidth - 560)
  y: 780 or responsive lower position
  width: 520
  height: 260
  purpose: financial preview

For smaller screens, use responsive fallback:
- left_primary: left 24 width 420
- right_primary: right 24 width 520
- bottom_wide: center width remaining
- if viewport too small, stack windows vertically with scroll.

============================================================
WINDOW PLACEMENT RULES
============================================================

Update WindowManager and/or WindowOrchestrator so every window type has a default zone.

Mapping:

document_viewer:
  zone: right_primary
  persistent: true
  never overwritten if it has uploaded document props

live_report:
  zone: left_primary
  persistent: true

assistant_notes:
  zone: left_secondary
  closable/minimizable
  not persistent across workflow changes unless active

document_intelligence:
  zone: left_secondary or center-left
  only visible after فهم المستند

raw_table_preview:
  zone: bottom_wide
  visible only if tables exist
  can be minimized by default if too large

courier_settlement_analysis:
  zone: left_primary
  can replace or become tab inside live_report area if needed

courier_rows:
  zone: bottom_wide

courier_issues:
  zone: left_secondary

financial_preview:
  zone: right_secondary

workflow_selector:
  zone: center modal
  should close after user selects workflow

approval_panel:
  zone: center modal
  only for mock_workspace approval_demo or future posting phase
  must NOT open for courier_settlement read-only analysis

session_timeline:
  zone: bottom or minimized debug panel
  hidden by default unless dev mode

============================================================
WINDOW LIFECYCLE RULES
============================================================

Implement these lifecycle rules:

1. Core windows:
   - document_viewer
   - live_report
   These stay open.

2. Starting a new workflow:
   - preserve document_viewer and uploaded document props
   - preserve live_report but clear or append a new section separator
   - close workflow_selector
   - close approval_panel unless workflow_type == mock_workspace and step requires approval
   - close old analysis windows from previous workflow:
     - courier_settlement_analysis
     - courier_rows
     - courier_issues
     - financial_preview
     - raw_table_preview
     - document_intelligence
     - assistant_notes
   - then open only windows required by the current step

3. Running document intelligence:
   - open document_intelligence
   - open raw_table_preview only if tables exist
   - do not open approval_panel

4. Running courier read-only analysis:
   - open:
     - courier_settlement_analysis
     - courier_rows
     - courier_issues only if issues exist
     - financial_preview
   - do not open approval_panel
   - document_viewer remains right
   - live_report remains left or becomes report tab

5. Completing read-only analysis:
   - avatar success
   - report final line
   - no modal approval

6. Refresh restore:
   - load session state
   - apply layout normalization to all windows
   - remove duplicate window types
   - remove stale approval_panel if session workflow is not mock approval
   - keep latest analysis windows only

============================================================
DEDUPLICATION RULES
============================================================

Fix duplicate windows.

Window identity should be:

- document_viewer: singleton per session
- live_report: singleton per session
- document_intelligence: singleton per document
- raw_table_preview: singleton per document/extraction result
- courier_settlement_analysis: singleton per analysisId
- courier_rows: singleton per analysisId
- courier_issues: singleton per analysisId
- financial_preview: singleton per analysisId
- approval_panel: singleton per active approval step
- workflow_selector: singleton

If openWindow is called for an existing identity:
- update existing window
- focus it if needed
- do not create a second one

============================================================
BACKEND WINDOW ORCHESTRATOR FIXES
============================================================

Inspect:

modules/workspace/services/window_orchestrator.py

Fix it so:

1. It assigns placement/zone based on window type.
2. It preserves document_viewer props:
   - documentId
   - fileName
   - mimeType
   - previewUrl
   - status
3. It supports lifecycle action:
   - close_windows_by_types(session, types)
   - normalize_windows(session)
   - ensure_singleton_window(session, spec)
4. It does not open approval_panel unless recipe step explicitly requires approval.
5. It does not keep stale approval_panel when switching workflow.

Add or update methods:

normalize_window_layout(session)
cleanup_for_workflow_start(session, workflow_type)
ensure_window(session, type, defaults, identity_key=None)
open_or_update_window(session, spec)
close_window_type(session, type)
close_window_types(session, types)

============================================================
WORKFLOW RECIPE FIXES
============================================================

Inspect recipes:

modules/workspace/recipes/mock_workspace_recipe.py
modules/workspace/recipes/unknown_document_recipe.py
modules/workspace/recipes/courier_settlement_recipe.py
modules/workspace/recipes/return_statement_recipe.py
modules/workspace/recipes/purchase_invoice_recipe.py

Fix:

1. courier_settlement_recipe must not include approval_panel.
2. courier_settlement_recipe must not have requires_approval true.
3. courier_settlement_recipe final state should be completed or waiting_review, not waiting_approval.
4. unknown_document_recipe should close workflow_selector after selection.
5. mock_workspace may keep approval_demo, but only in mock workflow.
6. return/purchase skeletons should not open approval_panel.

============================================================
WORKFLOW ENGINE FIXES
============================================================

Inspect:

modules/workspace/services/workflow_engine.py

Fix:

1. On start_workflow:
   - call window_orchestrator.cleanup_for_workflow_start(session, workflow_type)
   - reset current workflow-specific pending actions
   - clear stale approval state unless recipe starts with approval step
   - emit workflow.started
   - do not auto-open all steps at once unless current mode intentionally runs to completion.

2. run_next_step:
   - execute exactly one step unless current API explicitly asks run_all.
   - if a step opens windows, only those windows should open.
   - if step requires approval, approval panel opens.
   - if not, no approval panel.

3. run-mock compatibility:
   - If /run-mock auto-runs all mock steps, that is okay only for mock.
   - But "تشغيل Workflow" should not accidentally run all domain steps and leave all windows.

4. Add workflow mode:
   - step_by_step for dev
   - run_until_waiting_or_complete for normal
   Normal mode can run through non-blocking steps, but lifecycle cleanup must prevent clutter.

============================================================
FRONTEND WINDOW MANAGER FIXES
============================================================

Inspect:

static/workspace/js/window-manager.js

Fix:

1. Apply layout zones on render.
2. If backend position is missing or invalid, assign zone.
3. If windows overlap heavily, normalize positions.
4. Support `hidden`, `minimized`, `closed` states.
5. Do not render closed windows.
6. Do not duplicate same type/identity.
7. Add `data-window-type` and `data-window-id`.
8. Ensure z-index focus works.
9. Ensure document viewer is right side.
10. Ensure live report is left side.
11. Ensure secondary windows do not cover main document viewer.

Add method examples:

registerWindowType(type, renderer)
getWindowIdentity(window)
upsertWindow(windowSpec)
removeWindowByType(type)
removeWindowsByTypes(types)
normalizeLayout()
applyZone(window)
bringToFront(windowId)

============================================================
AVATAR FIXES
============================================================

Inspect:

static/workspace/js/leon-avatar.js

Fix:

1. Add safe target positions:
   - center
   - near_document_right but outside document window
   - near_report_left but outside report window
   - near_bottom_table
   - near_financial_preview
2. Speech bubble must stay within viewport.
3. Avatar must have lower z-index than modal but higher than canvas.
4. Avatar should not cover PDF/image content.
5. For reading_document mode:
   - avatar position should be between center and document viewer, not inside document viewer.
6. For writing_report mode:
   - avatar position should be between center and report, not inside report.
7. For success:
   - avatar returns to center safe lane.

============================================================
REPORT STREAM FIXES
============================================================

Inspect:

static/workspace/js/windows/live-report-window.js
static/workspace/js/event-stream.js

Fix if needed:

1. New report.appended events must always show.
2. Dedup should use event id, not message text.
3. If localStorage lastEventId is ahead incorrectly, provide recovery:
   - after loading session, fetch latest report state or replay from 0 if report is empty.
4. On new workflow start, append separator:
   "— بدأ سير عمل جديد: ... —"
5. Do not clear old report unless user starts new session.
6. But make new workflow section visually clear.

============================================================
FRONTEND BUTTON BEHAVIOR FIXES
============================================================

Current toolbar has many buttons.

Fix behavior:

1. "رفع مستند":
   - upload only

2. "فهم المستند":
   - run document intelligence only
   - no approval panel

3. "تحليل كشف التسديد قراءة فقط":
   - start courier_settlement workflow or directly run courier read-only analysis
   - no approval panel
   - opens courier windows only

4. "تشغيل Workflow":
   - should start selected workflow or mock workspace
   - if no workflow selected, open workflow_selector

5. "تشغيل تجربة":
   - mock only
   - okay to show demo approval

6. "إلغاء":
   - cancels current workflow/session operation
   - closes transient windows
   - does not remove uploaded document

============================================================
CSS / VISUAL FIXES
============================================================

Update:

static/workspace/css/workspace.css

Fix:

1. Main canvas should use full remaining viewport height.
2. Window positions should not rely on random absolute values only.
3. Add CSS variables:
   --workspace-toolbar-height
   --window-radius
   --window-shadow
   --workspace-gap
4. Make document viewer larger and readable.
5. Make report window clear.
6. Add visual hierarchy:
   - primary windows
   - secondary windows
   - modals
7. Ensure approval panel modal does not appear behind other windows.
8. Ensure avatar bubble does not cover primary content.

============================================================
SESSION RESTORE FIXES
============================================================

When loading session with ?session=:

1. Fetch session.
2. Normalize windows.
3. Remove duplicate windows.
4. Remove stale approval panel if current workflow is read-only.
5. Preserve document preview.
6. Restore latest analysis windows only.
7. Connect SSE using correct since id.
8. Avoid duplicate report lines.

============================================================
TESTS TO ADD OR UPDATE
============================================================

Add tests:

tests/workspace/test_workspace_layout_lifecycle.py
tests/workspace/test_window_cleanup_on_workflow_start.py
tests/workspace/test_no_approval_in_readonly_courier.py

Required assertions:

1. Starting courier_settlement workflow closes stale approval_panel.
2. courier_settlement recipe does not require approval.
3. WindowOrchestrator does not duplicate document_viewer.
4. document_viewer props are preserved after workflow start.
5. normalize_windows removes duplicate same-type windows.
6. cleanup_for_workflow_start preserves core windows.
7. cleanup_for_workflow_start removes old analysis windows.
8. read-only courier analysis emits no approval.required event.
9. restoring session normalizes window positions.

Frontend manual tests are acceptable if backend tests are hard for layout.

============================================================
MANUAL TEST CHECKLIST
============================================================

Update modules/workspace/README.md.

Manual test:

1. Open /workspace/.
2. Upload a document.
3. Confirm:
   - document viewer appears on the right.
   - live report appears on the left.
   - LEON is not covering the document.
4. Click "فهم المستند".
5. Confirm:
   - document_intelligence window opens cleanly.
   - no approval panel appears.
6. Click "تحليل كشف التسديد قراءة فقط".
7. Confirm:
   - approval panel does NOT appear.
   - courier summary opens.
   - rows window opens in bottom zone.
   - issues window opens only if issues exist.
   - financial preview opens in secondary zone.
   - old document intelligence/raw table windows close or minimize if not needed.
8. Refresh with ?session=<id>.
9. Confirm:
   - same clean layout restored.
   - no duplicate report lines.
   - no duplicate windows.
10. Click "تشغيل تجربة".
11. Confirm:
   - demo approval may appear only in mock workflow.
12. Start courier analysis again.
13. Confirm:
   - demo approval is removed.

============================================================
ACCEPTANCE CRITERIA
============================================================

This fix is complete only when:

1. Workspace no longer opens all windows on top of each other.
2. Document viewer is consistently on the right.
3. Live report is consistently on the left.
4. LEON does not cover the document viewer.
5. Approval panel does not appear in read-only courier analysis.
6. Starting a new workflow cleans stale windows.
7. Core windows are preserved.
8. Document preview is preserved after workflow changes.
9. Windows are singleton by identity.
10. Refresh restores clean layout.
11. Report streaming works and does not duplicate.
12. All existing Phase 1–5 tests pass.
13. New layout/lifecycle tests pass.
14. No business data mutation is introduced.
15. modules/publisher/** remains untouched.

============================================================
OUTPUT REQUIRED
============================================================

After fixing, report:

1. What files were changed.
2. What caused the overlapping windows.
3. What caused approval panel to appear.
4. How layout zones now work.
5. How workflow cleanup now works.
6. How LEON avoids overlapping windows.
7. Test results.
8. Manual test steps.
9. Safety confirmation:
   - no posting
   - no settlement
   - no accounting mutation
   - no inventory mutation
   - no business data mutation
   - no AI calls
10. Remaining known limitations.

Start with inspection, then implement this UX/runtime fix only.