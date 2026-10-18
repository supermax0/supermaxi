# Clinic pages: third-party scripts (privacy report)

> **Phase 8A update (2026-10-02): fixed.** `templates/base.html` now wraps `{% include "_google_tag.html" %}` in
> `{% if not is_clinics_business %}`. `is_clinics_business` is the tenant's real business type (`"clinics"`), set in
> `session["business_type"]` on login (`app.py`, `inject_business_context`) and true for every authenticated clinic
> workspace page (`templates/clinics/workspace.html` → `base.html`). It is **false** on `/login`, the public site and
> marketing/landing pages, so those keep the tag untouched, exactly as scoped below. Verified with Playwright
> (`tests/ai-tutor/tutor-availability-privacy.spec.js`, tests 5–6): zero requests to `googleadservices.com`,
> `googlesyndication.com`, `doubleclick.net` or `google.com/pagead|ccm` on `/clinics/`, `/clinics/patients`,
> `/clinics/appointments`, `/clinics/visits`, `/clinics/billing`, `/clinics/settings`; `window.gtag` is `undefined`
> there; `/login` still loads `gtag.js` and fires its page view. No other scoping or routing changed.
>
> **Google Analytics vs Google Ads:** confirmed there is only the one tag, `AW-18393144580`
> (`templates/_google_tag.html`) — an **Ads** conversion/remarketing id, not a GA4 property (`G-XXXXXXX`) or
> Universal Analytics (`UA-XXXXXX`). A repo-wide search found no `G-`/`UA-`/`analytics.js`/`gtag/js?id=G-` anywhere, so
> there is no separate Analytics tag to leave alone or touch — sections 4–5 below are entirely about this one Ads tag.
>
> **Consent (documented, not built):** no Consent Mode call (`gtag('consent', ...)`) and no cookie-consent banner exist
> anywhere in the codebase (`_google_tag.html`, `base.html`, `auth_base.html`, `landing_dynamic.html`, no consent JS
> found repo-wide). The tag fires unconditionally wherever it is included. Phase 8A did not add a consent system — the
> task only asked to document this, and there is no existing consent mechanism to wire into.

**الخلاصة بالعربي:** صفحات العيادة بعد تسجيل الدخول تحمّل وسم **Google Ads** (`AW-18393144580`) لأن قالب `base.html` يضمّنه لكل صفحة تمتد منه. الوسم يرسل إلى Google **رابط الصفحة وعنوانها** (وفيها معرّف المريض في المسارات مثل `/clinics/patients/12`) ويبني قوائم إعادة استهداف عبر معرّف كوكيز Google. لم نلاحظ إرسال محتوى النماذج أو أسماء المرضى في الطلبات التي فحصناها، لكن **هذا لا يثبت أن الإعدادات داخل حساب Google Ads آمنة** (انظر «ما لا يمكن معرفته من الكود»). لم يُحذف أو يُعدَّل أي شيء؛ القرار لك. التوصية في آخر الملف.

Status: **documentation only. Nothing was removed, disabled or changed.** Analytics stays until a decision is made.
Method: static reading of the templates + one observation run of the real clinic UI with a **throw-away test tenant and a fake patient** (no real or sensitive data was typed or sent; the run only listed the URLs of requests the browser itself made). Date of the run: 2026-10-02.

## 1. What loads, and from which template

| Script / resource | Template that loads it | Where |
|---|---|---|
| Google tag `gtag.js` (`https://www.googletagmanager.com/gtag/js?id=AW-18393144580`) + inline `gtag('config','AW-18393144580')` | `templates/_google_tag.html`, included by `templates/base.html:7`, `templates/auth_base.html`, `templates/landing_dynamic.html` | login, landing, **and every page that extends `base.html`** |
| Google Fonts CSS (`fonts.googleapis.com`, `fonts.gstatic.com` for the font files) | `templates/base.html:50-52` | every `base.html` page |
| Font Awesome CSS (`cdnjs.cloudflare.com`) | `templates/base.html:54` | every `base.html` page |

Clinic templates: `templates/clinics/workspace.html` (**all authenticated clinic pages**: dashboard, reception, appointments, queue, patients, visits, doctor workspace, billing, cash, expenses, inventory, settings …) extends `base.html`, so it gets all three. The public booking pages (`public_booking.html`, `public_manage.html`), the print templates (`*_print.html`) and `specialty_guide.html` do **not** extend `base.html` and do **not** load the Google tag.

## 2. Does it run inside authenticated clinic pages?

**Yes.** Observed on `/clinics/`, `/clinics/patients`, `/clinics/patients/<id>`, `/clinics/appointments`, `/clinics/billing`, `/clinics/settings` while signed in as a clinic user: `window.gtag` exists and every page navigation fires the requests below. The tag is not conditional on login, role, tenant or consent.

## 3. What is sent (observed per page view)

| Request | Host | Carries |
|---|---|---|
| `POST /ccm/collect` event `page_view` | `www.google.com` | `dl` = full page URL, `dt` = page title, `dr` = referrer, screen/language/consent flags, Google Ads id (`tid`), Google client id (`auid`) |
| `GET /pagead/viewthroughconversion/18393144580/` | `googleads.g.doubleclick.net` | page URL (`url`), Google client id |
| `POST /rmkt/collect/18393144580/` | `www.google.com` | page URL, client id (remarketing) |
| `GET /pagead/1p-user-list/18393144580/` | `www.google.com`, `www.google.iq` | page URL, client id **`cid`** (first-party audience / remarketing list) |
| `POST /ccm/s/collect` | `ad.doubleclick.net` | empty parameters |

Concretely for a patient profile the URL sent is `…/clinics/patients/1` and the title is `ملف المريض — Finora Clinics`. Page titles on the clinic pages are generic (page name + product), they do **not** contain the patient's name. Request bodies of the observed calls were empty (parameters are in the query string).

## 4. Sensitive data: what can and cannot reach Google

Observed to reach Google:
* The **URL path**, including record ids (`/clinics/patients/12`, `/clinics/doctor/<visit id>`): an id alone is not a name, but it is a stable identifier that exists only because the person is a patient of that clinic, and the domain/tenant context can be inferred from the host.
* The **page title** (generic), the **referrer**, language, screen size, a Google **client id** (cookie), and the fact that this browser visited a **medical-clinic application** on a given page at a given time. The tag also builds **remarketing audiences** (`1p-user-list`, `rmkt`) from these visits.

Not observed:
* No field values, no patient names, phones, diagnoses, notes, invoice amounts or file contents were present in the requests examined. The tag does not read form fields by default.

Cannot be known from this repository (check in the Google Ads account):
* Whether **Enhanced conversions / automatic data collection** (hashed email/phone scraped from forms) or **enhanced measurement** is enabled for `AW-18393144580`. If it is, form values such as phone numbers could be collected **without any code in this repo**.
* Whether Google Signals / remarketing / ads personalization is enabled for this tag, the data-sharing and retention settings, and whether a data-processing agreement covers health-related browsing.
* Consent: the template sets **no Consent Mode defaults** and the application shows **no consent banner** for it (no `gtag('consent', …)` call, no cookie banner in `base.html`).

## 5. Other third parties on the same pages
* **Google Fonts**: every page view sends the visitor's IP address and `Referer` (the page URL, same path-with-id concern) to Google. Can be self-hosted.
* **cdnjs / Cloudflare** (Font Awesome): IP + `Referer` to Cloudflare. Can be self-hosted.
* The AI Tutor itself makes **no** third-party request (verified by the Phase 5/6 runtime scan: zero third-party calls originate from the tutor; the only ones listed are the above).

## 6. Risk assessment (short)
* Medical-context + advertising tag on authenticated pages is the main concern: **visit pages of a medical application are shared with an ad platform and used for audience building.** Identifiers (client id + URL with record id) are present, content is not (as observed).
* The tag cannot be assumed harmless without verifying the Google Ads account settings in section 4.

## 7. Options (decision needed on 1/3/4; option 2 is now done)
1. **Fix the account settings**: confirm enhanced conversions / auto data collection are **off**, disable personalization/remarketing for this tag, document the legal basis. *Not done — needs the Google Ads account, not code.*
2. ~~**Scope the tag to marketing pages only**~~ — **done in Phase 8A**: `base.html` only includes `_google_tag.html` when `not is_clinics_business`, so every authenticated clinic workspace page is excluded; login, the public site and landing pages are unchanged.
3. **Gate it behind consent** (Consent Mode default `denied`, banner) for the pages that still carry it (login, marketing). *Not built — no consent system exists yet (see the Phase 8A note above).*
4. **Self-host fonts and icons** to stop sending IP/Referer to Google/Cloudflare from the app. *Not done.*

Remaining recommended order: **1, then 3, then 4.**

## 8. How to re-check
```bash
# against a local server and a throw-away test tenant (never real patient data)
node scripts/ai_tutor_runtime_scan.mjs --out runtime.json   # also lists third-party hosts per page
```
Open DevTools → Network → filter by host on `/clinics/patients/<id>` and look at `ccm/collect` (`dl`, `dt`).
