# Desktop-inspired system home — 2026-10-19

The authenticated system home adopts the FINORA desktop palette and workspace layout: soft violet background, white surfaces, compact line icons, a greeting and Baghdad date, a period selector and permission-aware shortcuts. Financial and order cards, quick summary, charts and overdue table have consistent spacing and hierarchy. The mobile layout uses two columns and fixes a flex min-width issue that otherwise clipped content.

Existing metric IDs, APIs, role handling, privacy controls, dialogs, branch scope, financial calculations and data-loading flow are retained. The new period label mirrors the original response. Decorative hardcoded sparklines were removed; actual chart canvases remain. The cashier welcome screen retains its role-specific content.

Verification: three focused tests cover retained controls/read-only balances, cashier welcome and restricted shortcuts. Real Chrome against the isolated app checked actual data endpoints, privacy reveal/hide, period synchronization, search/profit/expense/alert dialogs, charts and the overdue section, and five viewport widths (1536,1280,1024,768,390). Screenshots were visually inspected and the final run had no JavaScript page errors.

The change is limited to the dashboard template and scoped CSS. Production deployment backs up touched source, verifies installed hashes and checks the authenticated home, dashboard APIs and existing primary pages.
