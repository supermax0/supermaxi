# FINORA 0.10.1 — dated profit and 12-hour time

Reports use Baghdad calendar boundaries over stored UTC timestamps. Plain calendar dates, including expense dates, are not shifted. Default reporting periods also follow Baghdad midnight.

Posted return documents use the existing sales-return evidence: original revenue and cost stay on the sale date, and each credit/cost reversal appears on its return document date. The statement, sales series, breakdowns, product and employee totals, invoice rows and exports share this definition. Branch/employee filters are applied before return activity is aggregated; invoice links retain the real invoice ID.

The sales line chart supports negative values and closes its shaded area at zero, so return-only days remain inside the visible plot.

Scheduled expense comparisons and expense defaults use the Baghdad wall clock instead of the server's UTC clock. Explicit `now` arguments to scheduling functions remain local wall-clock values for compatibility. Existing posting/treasury balance protections remain authoritative.

Gunicorn workers run the existing minute timer, protected by a private per-run process lock on Linux. A graceful reload releases the old run normally and permits subsequent runs in new workers. Tenant sessions are closed between companies, failures are logged, and the existing atomic `cash_posted` claim also prevents double posting alongside page loads. Diagnostic imports and local workspace tests do not start financial jobs.

Report export metadata, report date/time cells, order dates, notifications, stock activity and customer schedule history display a 12-hour clock with an Arabic day period (ص/م). Scheduled times display the same entered local hour. ISO timestamps and HTML time input values remain machine-readable; database timestamps, recorded prices and costs are not rewritten.

Regression coverage includes both sides of Baghdad midnight, partial and full later returns, aggregate/detail agreement, branch and employee exclusions, and midnight/noon/evening formatting. Existing report, expense, financial integrity, treasury and equity regressions are included in release validation.
