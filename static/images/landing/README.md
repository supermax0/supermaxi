# FINORA landing screenshots

These are unaltered captures of the actual application running with demonstration/test data.
They are not AI-generated UI mockups. The website labels their data as illustrative.

| Public asset | Original capture |
| --- | --- |
| suppliers.png | desktop/finora_management/screenshots/suppliers-desktop.png |
| inventory.png | tests/_artifacts/erp-inventory-activity/stock-1536.png |
| customers.png | tests/_artifacts/erp-customers/1536-details.png |
| purchases.png | tests/_artifacts/purchase-list-desktop.png |
| offline.png | desktop/finora_management/screenshots/offline-synchronized.png |

Supplier demo names and numbers are defined in `desktop/finora_management/e2e/supplierFixture.ts`;
customer examples are used by the desktop customer E2E tests. Inventory and purchase screenshots
are development verification artifacts. Refresh screenshots against the current application when
releasing UI changes; keep demonstration data and never publish live customer records.

`finora-mark.svg` reproduces the existing desktop `src/components/FinoraLogo.tsx` vector mark.
The local Arabic font is IBM Plex Sans Arabic; its license accompanies it in `static/fonts/landing/`.
