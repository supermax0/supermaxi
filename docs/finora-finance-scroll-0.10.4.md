# FINORA Desktop 0.10.4 — finance table scrolling

Financial control sources and snapshots, vouchers, loans, treasury accounts, journals and accounting reports now pass the available height through their table containers. Their existing scroll regions keep overflow inside the table, retain sticky headers and leave pagination outside the rows.

Short windows additionally allow the finance workspace to scroll around the controls while retaining a usable table viewport, instead of collapsing the table to zero height.

Finance pagination reserves space for the assistant launcher so it cannot cover the page-size selector; the desktop regression clicks the selector to verify it remains usable.

The regression opens the real desktop workbench with 21 sources, 67 journal records, 67 snapshots and long descriptions. It checks wheel scrolling, reaching the last visible page row and pagination access at 1920×1080, 1366×768, 1024×768 and 960×600.

Release provenance: installers are built in an isolated source snapshot of deployed commit `d7976877b40fbdce90e639bd525f7cbe6774d20b`, applying only the finance layout fix and version 0.10.4. Pending assistant development in the shared working directory is excluded. This desktop-only release publishes installer files and their download manifests; it does not advance the backend server checkout or overwrite backend source.
