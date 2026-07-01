You are working inside the existing Finora codebase.

You have already generated the file:

FINORA_AI_WORKSPACE_IMPLEMENTATION_PLAN.md

Now implement ONLY:

PHASE 1 — Workspace Foundation

Do not implement Phase 2, Phase 3, OCR, document extraction, courier settlement, return workflow, purchase workflow, product matching, accounting posting, inventory posting, or real AI document analysis.

This phase must only create the foundation of the interactive LEON workspace.

============================================================
PHASE 1 OBJECTIVE
============================================================

Build a full-page interactive workspace shell inside Finora.

The page must look and behave like a clean AI accounting workspace:

- white / very light background
- subtle grid canvas
- floating rounded windows
- soft shadows and thin borders
- Arabic-first RTL layout
- central LEON avatar
- avatar can move between workspace areas
- live report text streams gradually
- basic mock workflow events through SSE
- workspace session can be created, loaded, and restored after refresh

This phase is a visual/runtime foundation only.

No real financial data should be changed.
No orders should be updated.
No inventory should be updated.
No purchases should be created.
No accounting entries should be posted.
No shipping reports should be executed.
No OCR should run.
No AI model should be called.

============================================================
STRICT SAFETY RULES
============================================================

1. Do not modify operational business data.
2. Do not call delivery_agent.execute_report.
3. Do not call purchases._create_purchase_from_payload.
4. Do not modify Invoice, Product, Purchase, ShippingReport, AccountTransaction, Expense, or JournalEntry records.
5. Do not add OCR or PDF extraction in this phase.
6. Do not install new heavy dependencies unless absolutely required.
7. Prefer existing project patterns.
8. Do not touch modules/publisher unless absolutely necessary.
9. Keep this feature isolated under modules/workspace.
10. The feature must be easy to disable if it breaks.

============================================================
CURRENT FINORA CONTEXT
============================================================

The project appears to use:

- Flask
- SQLAlchemy
- tenant SQLite databases through DynamicTenantSession
- Jinja templates
- static JavaScript/CSS
- existing assistant avatar code in static/js/assistant-character.js
- existing app.py blueprint registration pattern
- plan limits / feature gates
- existing session auth

Verify these assumptions from the repository before coding.

============================================================
FILES TO CREATE
============================================================

Create the following structure if it does not already exist:

modules/workspace/
  __init__.py
  routes.py
  api/
    __init__.py
    session_api.py
    stream_api.py
  models/
    __init__.py
    workspace_session.py
    workspace_audit_event.py
  services/
    __init__.py
    session_service.py
    event_bus.py
    mock_workflow_service.py

templates/workspace/
  app.html

templates/workspace_dev/
  app.html

static/workspace/
  css/
    workspace.css
  js/
    workspace-app.js
    session-store.js
    event-stream.js
    workspace-canvas.js
    window-manager.js
    leon-avatar.js
    windows/
      live-report-window.js
      document-viewer-window.js
      assistant-notes-window.js

tests/workspace/
  test_workspace_session_service.py
  test_workspace_routes.py

If the current project has a different test convention, adapt to it.

============================================================
FILES TO MODIFY
============================================================

Modify only if needed:

app.py
  - Register workspace blueprint:
    from modules.workspace import workspace_bp, init_workspace
    app.register_blueprint(workspace_bp, url_prefix="/workspace")
    init_workspace(app)

utils/plan_limits.py
  - Add ai_workspace feature flag if project uses feature flags.

extensions_tenant.py or the existing permissions seed file
  - Add workspace permissions only if permission seeding is currently centralized and safe.

templates/base.html or existing navigation template
  - Add a link to /workspace/ only if there is a clear sidebar/nav pattern.
  - If this is risky, skip nav link and keep direct route only.

models/__init__.py
  - Export workspace models only if existing project requires central model imports.

Do not modify core business routes.

============================================================
BACKEND REQUIREMENTS
============================================================

Implement a workspace blueprint.

Routes:

GET /workspace/
  - Renders templates/workspace/app.html
  - Requires login
  - If feature gate exists, require ai_workspace
  - If feature gate is not ready, use admin-only or logged-in only temporarily, but write a clear TODO.

GET /workspace/?dev=1
  - Renders templates/workspace_dev/app.html
  - Use dev shell only if useful.

API prefix:

/workspace/api

Endpoints:

POST /workspace/api/sessions
  - Creates a WorkspaceSession.
  - Default workflow_type: "mock_workspace"
  - Initial status: "created"
  - Initial current_step_id: "session_created"
  - Initial windows_json should include:
    1. document_viewer window on right
    2. live_report window on left
    3. assistant_notes window optional
  - Initial avatar_state_json:
    mode: "idle"
    position: center
    speech: "أهلاً، جاهز لتحليل المستندات."

GET /workspace/api/sessions/<session_id>
  - Returns session state.
  - Must verify the session belongs to the current tenant/user if applicable.

GET /workspace/api/sessions
  - Returns recent workspace sessions for current user/tenant.

POST /workspace/api/sessions/<session_id>/run-mock
  - Starts or advances a mock workflow.
  - It should emit events to the event bus:
    workflow.step.started
    window.opened
    avatar.updated
    report.appended
    document.scan.updated
    workflow.step.completed
    session.completed
  - This is mock only.

GET /workspace/api/sessions/<session_id>/stream
  - Server-Sent Events endpoint.
  - Streams events as text/event-stream.
  - Must support reconnect as much as practical.
  - For Phase 1, in-memory queues are acceptable.
  - Also persist events as WorkspaceAuditEvent.

POST /workspace/api/sessions/<session_id>/cancel
  - Marks session as cancelled.
  - Emits session.cancelled event.

============================================================
DATABASE MODELS
============================================================

Create minimal models only.

WorkspaceSession:

- id: string UUID primary key
- tenant_slug: string nullable or required depending on current tenant system
- user_id: integer nullable or current user id type
- workflow_type: string
- status: string
- current_step_id: string nullable
- windows_json: JSON/text depending on current DB compatibility
- avatar_state_json: JSON/text
- metadata_json: JSON/text
- created_at
- updated_at

WorkspaceAuditEvent:

- id: integer primary key autoincrement OR UUID depending on project style
- session_id
- event_type
- message
- payload_json
- user_id nullable
- created_at

Use the project’s existing SQLAlchemy conventions.

Since tenant databases are SQLite, ensure JSON fields are compatible.
If the project does not use native JSON consistently, store JSON as Text and serialize/deserialize safely.

============================================================
EVENT BUS REQUIREMENTS
============================================================

Implement modules/workspace/services/event_bus.py

Phase 1 can use:

- in-memory queue per session
- persistent audit events in DB
- helper emit_event(session_id, event_type, payload, message=None)

Each emitted event must:

1. Be appended to the in-memory queue.
2. Be persisted as WorkspaceAuditEvent.
3. Include:
   - event_id
   - type
   - payload
   - message
   - created_at

SSE format:

event: report.appended
id: <event_id>
data: {"type":"report.appended","payload":{...}}

Do not overcomplicate with Redis in Phase 1.

============================================================
MOCK WORKFLOW REQUIREMENTS
============================================================

Implement MockWorkflowService.

When run-mock is called, it should simulate this sequence:

Step 1:
- avatar moves toward right document viewer
- report: "تم إنشاء جلسة LEON Workspace."
- report: "تم فتح نافذة معاينة المستند."

Step 2:
- open/update document_viewer
- document scan overlay active
- report: "جاري تجهيز معاينة المستند التجريبية..."
- avatar mode: "reading_document"

Step 3:
- avatar moves toward left report window
- report: "جاري كتابة تقرير التحليل التجريبي..."
- report: "هذه المرحلة لا تقوم بأي ترحيل مالي أو مخزني."
- avatar mode: "writing_report"

Step 4:
- open assistant_notes window
- report: "تم اختبار فتح النوافذ التلقائي بنجاح."
- avatar mode: "success"
- session status: "completed"

The frontend should show this as live progressive updates.

============================================================
FRONTEND REQUIREMENTS
============================================================

Build a full-page workspace UI.

templates/workspace/app.html:

- Full page, no heavy dashboard layout if possible.
- Load static/workspace/css/workspace.css.
- Load JS modules/files:
  - session-store.js
  - event-stream.js
  - workspace-canvas.js
  - window-manager.js
  - leon-avatar.js
  - windows/live-report-window.js
  - windows/document-viewer-window.js
  - windows/assistant-notes-window.js
  - workspace-app.js

UI layout:

- Top small toolbar:
  - title: "Finora AI Workspace"
  - status pill
  - button: "جلسة جديدة"
  - button: "تشغيل تجربة"
  - button: "إلغاء"

- Main canvas:
  - white/light background
  - subtle grid
  - floating windows
  - central avatar

Floating windows:

1. Document Viewer Window
   - title: "معاينة المستند"
   - placeholder paper preview
   - fake scan-line overlay when document.scan.updated active

2. Live Report Window
   - title: "تقرير التحليل"
   - receives report.appended events
   - writes text gradually, not all at once
   - Arabic RTL

3. Assistant Notes Window
   - title: "ملاحظات LEON"
   - receives assistant notes / success messages

Avatar:

- Use existing assistant-character.js if compatible.
- If existing avatar is hard to reuse safely, create a temporary lightweight CSS avatar for Phase 1:
  - glowing circular face
  - eyes
  - small speech bubble
  - smooth transform movement
- Wrap it in LeonAvatarAdapter with:
  - setMode(mode)
  - moveTo(x, y)
  - speak(text)
  - setProgress(progress)

The adapter must be written so it can later be connected to the real Three.js avatar.

Window Manager:

- openWindow(windowSpec)
- updateWindow(windowId, patch)
- focusWindow(windowId)
- closeWindow(windowId)
- renderWindows(session.windows)
- applyEvent(event)

No need for full drag/resize in Phase 1 if it risks delay.
But window positions must be controlled by state.

State restore:

- On page load:
  - if URL has ?session=<id>, load that session.
  - else create a new session.
  - render windows from session state.
  - connect SSE.

============================================================
CSS REQUIREMENTS
============================================================

The visual style should match the target design:

- clean white SaaS workspace
- light blue/purple accent
- thin borders
- border-radius 18px or similar
- box-shadow subtle
- smooth transitions
- RTL text
- responsive enough for 1366px width minimum

Do not use dark theme for this workspace.

============================================================
TESTING REQUIREMENTS
============================================================

Add tests if the project supports pytest.

Test:

1. Creating a WorkspaceSession.
2. Getting a session.
3. Emitting an event persists WorkspaceAuditEvent.
4. run-mock changes session status eventually.
5. Unauthenticated user cannot access /workspace/ if auth tests are feasible.

If tests are hard due to the current app setup, write a manual test checklist in:

modules/workspace/README.md

============================================================
ACCEPTANCE CRITERIA
============================================================

Phase 1 is complete only when:

1. /workspace/ opens without crashing.
2. A new workspace session can be created.
3. The workspace displays a white canvas with subtle grid.
4. At least two floating windows appear:
   - document viewer
   - live report
5. LEON avatar appears and can move based on events.
6. Clicking "تشغيل تجربة" starts a mock workflow.
7. The live report receives streaming lines gradually.
8. The document viewer shows a fake scan-line overlay.
9. Refreshing the page can restore the session state when session id is present.
10. Events are persisted as WorkspaceAuditEvent.
11. No operational business records are modified.
12. No OCR/AI/accounting/inventory/shipping posting is implemented in this phase.

============================================================
OUTPUT REQUIRED
============================================================

After implementation, provide:

1. Summary of created files.
2. Summary of modified files.
3. How to open the workspace.
4. How to test the mock workflow.
5. Any errors or limitations.
6. Confirmation that no business data posting was added.
7. Next recommended task: Phase 2 — Document Upload + Viewer.

Start implementing Phase 1 only.