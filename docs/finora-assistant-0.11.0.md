# FINORA Desktop 0.11.0 — FINORA assistant

The local assistant (Ollama / LM Studio) gains streaming answers, page awareness, report-backed tools, visual results, more reviewed drafts, proactive alerts and an optional server fallback.

## Desktop

- Answers stream as they are written; the selected model is loaded when the panel opens and kept loaded for 30 minutes.
- The assistant knows what the open window shows (tab, search, filters, opened record, checked rows) and offers questions for that window and record.
- Tool selection is scored (Arabic normalization, page and follow-up context) instead of fixed keywords; draft preparation is offered only for creation requests.
- Tool results render as KPI cards with previous-period change, ranked bars and a record table with open links, with CSV (Excel) export and single-card printing.
- New reviewed drafts: supplier, supplier payment, order return (opens the order), stock transfer; purchase drafts accept unit cost and supplier invoice number, including from an invoice photo.
- "Today's alerts": low stock, overdue installments, pending agent reports, unpaid purchases, unusual expenses and duplicate customers, from permission-filtered tool calls.
- "Explain the error" uses the real error text, window and time of recent error notifications.
- New lessons for suppliers, supplier payments and stock transfers with on-screen targets; dictation uses an Iraqi-vocabulary prompt and ASCII digits.
- Optional, off by default: text questions go to FINORA's server assistant when the local model is off or unreachable.

## Server (modules/finora_ai)

Ten read-only tools over the reports engine (`services/reports_service.py`) and existing helpers: period comparison, sales breakdown, purchases, receivables aging, sales returns, overdue installments, stagnant products, product movements, expense anomalies and duplicate customers. They use the reports page permissions and branch scope; `tests/test_reports_v2.py` checks their figures against the reports API.

The desktop features that use these tools need the server update; without it the tools are absent from the catalog and the related alerts and answers are skipped.
