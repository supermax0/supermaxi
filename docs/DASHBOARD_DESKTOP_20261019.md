# FINORA system home — responsive cards, 2026-10-19

The authenticated home uses a desktop-style violet workspace, permission-aware shortcuts and a unified financial grid. Sales are highlighted; purchases, inventory, receivables, expenses and returns remain connected to their original IDs and APIs.

The card groups measure their actual available width, including the sidebar: four columns on wide workspaces, three on tablets/narrow laptops and two on phones (one on very narrow screens). Featured sales span the appropriate columns so the remaining six cards fill every row. Order cards likewise fill complete rows. Shortcut, quick-summary and chart groups adapt independently. Container boundaries are restricted to components and never enclose fixed dialogs.

Typography and values remain legible without truncating long amounts. Financial cards do not animate their dimensions during sidebar transitions. Compact headers, consistent padding, touch targets and section spacing reduce wasted space. Existing privacy reveal/hide, roles, branch scope, charts, modals and data-loading behavior are retained.

Verification: the three existing focused regressions passed (read-only balances/retained controls, cashier welcome and restricted shortcuts). Actual Chrome/Flask checks passed at 16 viewport sizes from 320 to 1920 pixels, including tablet portrait/landscape, laptop sizes and sidebar expansion/collapse across a column breakpoint. Presentation-only stress values of 999,999,999,999 IQD fit without clipping; financial and order rows filled the grid. Period, privacy, search, profit, expense and alert controls were checked through the real isolated application APIs. Screenshots for laptop, tablet and phone were inspected; the final browser runs had no JavaScript page errors.

Production release backs up touched source, verifies hashes, and checks the authenticated home, dashboard APIs and existing primary pages. No financial calculation, database record, stock balance or customer upload is changed by this design release.
