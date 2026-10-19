# Product editor update — 2026-10-19

The new inventory drawer supports product creation and partial editing while retaining the existing advanced editor and its stock, color, option, media and branch rules.

- Edits load authoritative product details; failed or outdated requests cannot enable an empty editor or overwrite a newly opened drawer.
- Only changed edit fields are posted. Unchanged prices, metadata, gallery, option settings and stock are preserved, including concurrent updates to untouched fields.
- Added sale availability, independent POS/store visibility, and feature-gated trade-in pricing. Price editing follows the existing permission.
- New products support color opening balances with an automatic total. Existing color balances are displayed; added colors use the existing append API and start at zero. Composite option products use the existing advanced editor.
- Whole-number and nonnegative validation, duplicate-color checks, image validation/preview, unsaved-change protection, keyboard navigation and save/add-another reset.
- JSON creation returns structured validation errors before writes or uploads. Inventory grid serialization preserves a zero stock-alert threshold.

## Verification

72 distinct focused Python tests passed: product editor (10), desktop settings (11), desktop colors (6), options (18), color media (9), and merged page features (18). The grid zero-threshold regression also passed in a targeted rerun.

Real Chrome against an isolated Flask/SQLite application verified creation, color balances, edit persistence, concurrent changes, request races, upload, save/add-another, barcode conflicts, failed loading, restricted price inputs, invalid images, unsaved changes and desktop/mobile layout. No JavaScript page errors. Desktop/mobile screenshots were inspected.

Production deployment backs up touched source files, verifies installed hashes and runs authenticated read-only HTTP checks. Customer databases, uploads and runtime files are excluded from the release.
