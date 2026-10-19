# Responsive dashboard charts — 2026-10-19

Charts use compact Arabic axis units, full-precision IQD tooltips, upright adaptive date ticks, touch-friendly point hit areas, stable responsive canvas boxes and consistent FINORA colors. The status doughnut has an accessible HTML legend with keyboard-operable visibility toggles, counts/percentages without an erroneous currency suffix, and a total in its center. Yearly profit/expense colors have a visible key. Empty data and failed loading have explicit UI states and retry.

Existing chart APIs, labels, source arrays, financial calculations and the current seven-day/year scopes are retained. The scopes are now stated beside the charts. Component containers do not surround fixed dialogs.

Verification: 4 JavaScript unit checks and 3 existing dashboard role/read-safety regressions passed. Real Chrome/Flask checks at 13 sizes from 320 to 1920px verified canvas bounds, plot space, tick density, legend overflow, exact agreement with API values, large positive/negative presentation-only datasets, legend toggles, empty data, failure/retry and the profit modal. No JavaScript page errors. Laptop/tablet/phone screenshots were inspected.

The production release verifies source hashes and authenticated page/assets before completing. It does not change business records or uploaded media.
