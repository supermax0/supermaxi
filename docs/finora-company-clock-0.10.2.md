# FINORA 0.10.2 — company display clock

Choose **12 or 24 hours** in website Settings → Appearance → Date and time, or desktop Settings → Appearance and shortcuts. The preference belongs to the company, requires `manage_settings` to change, and is shared by authenticated staff. Existing companies default to 12 hours with Arabic ص/م. All displays use Baghdad time.

The website, desktop order tables and detail windows, financial and employee statements, activity histories, messages, single and batch invoices, inventory counts, report exports, and offline POS receipts use this preference. Dates without a time keep their calendar meaning. Stored UTC timestamps, sorting keys, JSON machine values, HTML time/date inputs, financial amounts and scheduling are unchanged.

Desktop views subscribe to the clock preference without remounting forms or clearing drafts. Preferences refresh on focus and every 30 seconds while signed in. A verified session retains the preference for offline receipts. Website pages render from company settings and their JavaScript formatters use the same setting. Reload an already-open server-rendered page to regenerate its printed/static labels after changing the preference elsewhere.

Regression checks cover tenant isolation, staff permissions, invalid input, shared website/desktop settings, preservation of other UI flags and invoice totals, Baghdad midnight/noon, both clock modes, real single/batch print routes, invalid timestamps, date-only values, local scheduled hours, offline receipts and live desktop updates without losing a draft. Installer variants retain the existing modern and Windows 7/8 runtime configurations.
