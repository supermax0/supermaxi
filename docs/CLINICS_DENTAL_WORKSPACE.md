# FINORA Clinics — Dental Workspace v29

## Architecture

The dental workspace extends the existing Clinics package. It does not create a second patient, invoice, payment, inventory, or attachment domain.

`ClinicPatient` → `ClinicAppointment` → `ClinicVisit` → dental chart/events → treatment plan/options/items → dental sessions → `ClinicVisitProcedure` → shared inventory consumption → `ClinicInvoice`/payments → next linked appointment.

Execution remains canonical in `ClinicVisitProcedure`. A dental session links to that execution; recipe stock is consumed by the existing execution transition and therefore only once. Billing remains canonical in the shared clinic invoice/payment ledger.

## Database changes

- Appointments now keep treatment plan, item, session, primary tooth, and multiple-tooth context.
- Tooth events support concurrent active findings and append-only resolving events through `supersedes_event_id`.
- Treatment plans support proposed/accepted/in-progress states, patient acceptance metadata, signature attachment, options, discount, and cancellation audit.
- Treatment items support multiple teeth, whole-mouth treatments, quantity, discount, option grouping, completion/cancellation actor, and cancellation reason.
- Sessions support completion actor, cancellation actor/reason, notes, and next-session recommendation.
- Dental image metadata can link to a plan and session while the file remains in the shared attachment store.
- Additive indexes cover appointment dental context, active tooth events, superseded events, option-linked items, and image context.

The tenant-local lazy schema version is `clinics-v29-dental-workspace`. Existing rows remain compatible; all new columns are nullable or have safe defaults.

## APIs

- Chart: visit chart read/update, append a finding, resolve one finding, patient tooth-event timeline.
- Plans: patient plan list/create, plan detail/update/print, option create/update, patient acceptance.
- Items: create/update/archive, link an actual visit procedure.
- Sessions: list/create/update/complete/cancel with linked appointment and visit execution.
- Images: metadata over shared attachments, filterable by visit, tooth, plan item, plan, session, and type.
- Billing: create invoice from full plan, selected items, one session, or a custom amount. Item/session duplication checks are enforced inside a transaction lock.

All routes remain under `/clinics/api/...`; there is no separate dental patient namespace.

## Permissions and safety

- Clinical read/edit, plan, session, image, reports, and billing permissions remain separate.
- Financial values are removed server-side from plan/detail/print responses when billing permission is absent.
- Tenant checks apply to every patient, plan, item, session, appointment, image, and attachment link.
- Completed visits are read-only. Closed plans/items/sessions reject invalid transitions.
- Cancelling a plan item or session requires a reason and records the actor in the audit trail.
- Critical invoice/session operations use database locking and idempotent linkage to avoid duplicate execution, inventory consumption, or billing.

## User workflow

1. Reception books a normal clinic appointment, optionally linked to a dental plan item/session and one or more teeth.
2. The doctor opens the same visit workspace and uses focus mode to collapse the patient and clinical side panels.
3. The interactive chart supports permanent/primary/mixed dentition, multiple findings on one tooth, surface selection, realistic condition layers, and a full tooth timeline.
4. The doctor creates one or more treatment options, adds single-tooth, multi-tooth, or whole-mouth items, and records patient acceptance.
5. Sessions carry planned/completed work, notes, recommendation, linked visit execution, and before/after or radiographic images.
6. Completing a non-final session prepares the next session; booking links the appointment to that same prepared session instead of creating a duplicate.
7. Billing creates shared clinic invoice lines. Reception can see treatment/session/tooth context without seeing clinical notes.

## Regression checklist

- General medicine and non-dental specialties continue to use the existing generic workspace.
- Existing dental chart, plan, platform, browser, invoice, payment, inventory, and attachment flows remain in place.
- Verify Arabic RTL at 1366×768 and wider screens, drawer keyboard escape, focus return, collapsed side panels, and chart fit without horizontal scrolling.
- Verify permanent, primary, and mixed modes; concurrent findings; resolve/history; multi-tooth and whole-mouth items; option acceptance; cancellation reasons; next-session booking; invoice retry; and no-financial-permission responses.

## UX decisions

- The arch is deliberately a wide anatomical U rather than a circle. Tooth size, rotation, and spacing differ by type and quadrant.
- Side panels collapse into persistent edge handles so the chart gains width without navigating away.
- Clinical history is progressive disclosure: latest state first, full append-only timeline on demand.
- Financial fields are omitted, not blurred or visually hidden, when permission is missing.
