# Workspace design and responsive audit — 2026-10-19

Reviewed 82 accessible pages in an isolated general-accounting tenant using real Flask routes, data APIs and Chrome. The initial pass found content clipped by intrinsic table widths, compressed action labels, narrow-screen card grids and overlapping toast positioning. Smaller secondary pages also retained dark or blue headers that differed from the desktop-inspired home.

## Changes

- Constrain flex children to the available workspace. Keep all columns in keyboard-accessible horizontal scrollers across asset tables and financial report tables, including conditional detail sections.
- Size financial report chart tracks from available space so resizing from a laptop to a phone does not retain an oversized canvas. Wrap date-range controls and reflow form and KPI grids.
- Keep order action labels from shrinking. Fit warning cards, invoice template cards and Facebook navigation into 320px screens, and allow sound preset labels to wrap.
- Center feedback notifications on phones. Reserve tablet header space for page titles, branch selection, account identity and compact quick actions; preserve the home's two labeled actions.
- Match installment and receipt headers to the home's violet surfaces. Use the shared card borders, spacing and shadows on older maintenance and asset pages.
- Remove horizontal clipping when printing reports. Existing fields, forms, template conditions and data bindings were compared against the previous release after removing only the newly added wrappers; they are unchanged.

## Verification

- 82 pages × 5 viewport widths: 1366, 1024, 768, 390 and 320px, with 900px viewport height. Final checks found no unresolved page overflow, clipped button text or JavaScript page errors. Offscreen controls within intentional horizontal scrollers remain reachable.
- Affected routes were rechecked after fixes. Tablet header layouts were also checked at 901, 1024 and 1199px.
- Real order data loads in phone cards; mobile sidebar opens and closes; 18-digit KPI amounts fit all five sizes; asset tables scroll with keyboard arrows; report scrollers remain unclipped when printing.
- 31 isolated regression tests passed: workspace responsive design (10), recovered feature/design integration (18), dashboard privacy/permissions/read safety (3).
- All 12 changed Jinja templates parsed successfully. The production preflight returned HTTP 200 for all 13 affected legacy page routes.

Browser backgrounds for notification polling and workspace event streams were isolated from the layout run. Application data endpoints were not mocked; cached static responses used the sandbox's exact files or original CDN response bytes. Production checks use transient authenticated read-only HTTP requests. Feature-restricted pages and record variants outside this tenant's accessible navigation are outside the 82-page count.

## Reviewed routes

- `/`
- `/pos`
- `/quick-sale`
- `/customers`
- `/customers/blacklist`
- `/customers/credit`
- `/orders`
- `/installments`
- `/installments/products`
- `/installments/applications`
- `/installments/contracts`
- `/installments/overdue`
- `/installments/reports`
- `/installments/settings`
- `/inventory`
- `/inventory/ledger`
- `/inventory/products/duplicates`
- `/inventory/audit`
- `/maintenance`
- `/purchases`
- `/purchases/lists`
- `/suppliers`
- `/agents`
- `/agents/pending-execution`
- `/shipping`
- `/expenses`
- `/receipts`
- `/cash`
- `/accounts`
- `/accounts/finance`
- `/assets/dashboard`
- `/finance/rotating-savings`
- `/executive-dashboard`
- `/reports`
- `/reports/daily`
- `/reports/monitors`
- `/employee-desk`
- `/employees`
- `/payroll`
- `/notes`
- `/facebook-monitor`
- `/employees/page-warnings`
- `/pages`
- `/investments`
- `/assistant/chat`
- `/ai-sales/inbox`
- `/messages`
- `/workspace`
- `/mobile-app`
- `/customers/provinces`
- `/admin/permissions/roles`
- `/activity`
- `/settings`
- `/admin/invoice-templates`
- `/inventory/transfers`
- `/inventory/add`
- `/inventory/videos`
- `/reports/daily/archive`
- `/reports/financial`
- `/settings/appearance`
- `/settings/system`
- `/assets/create`
- `/assets/categories`
- `/assets/depreciation`
- `/assets/maintenance`
- `/assets/transfers`
- `/assets/disposal`
- `/assets/approvals`
- `/assets/reports`
- `/assets/audit`
- `/assets/settings`
- `/settings/invoice`
- `/settings/branches`
- `/settings/storefront`
- `/settings/pos-api`
- `/finance/rotating-savings/settings`
- `/settings/database-repair`
- `/settings/facebook-routing`
- `/purchases/new`
- `/reports/detailed/sales`
- `/inventory/report/<product_id>`
- `/customers/credit/<customer_id>`
