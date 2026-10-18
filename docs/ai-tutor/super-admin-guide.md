# Super Admin guide — Finora AI Tutor

## Enable for one account
1. Super Admin → الشركات.
2. Open the company (👁) → tab **ميزات المنصة**.
3. Choose **دائم** or **حتى تاريخ محدد**, press **تفعيل / حفظ المدة**, confirm.
4. The company's users see the feature on next request (≤ 15 s in other workers).

## Disable
Same tab → **إيقاف** → confirm. User progress is kept; access stops immediately.

## Several accounts
Tick companies in the list → **تفعيل AI Tutor** / **إيقاف AI Tutor**. The operation is all-or-nothing. Use the search box and the AI Tutor filter (الكل / مفعّل / غير مفعّل / منتهي).

## Emergency stop
**إيقاف طارئ عام** disables the feature for every account at once without touching per-account settings; **إعادة التشغيل العام** restores them.

## Notes
- New and existing accounts are OFF by default. Tenant admins cannot change this.
- Search matches company name, slug and numeric tenant id (manager-name search is not available: it lives in each tenant DB).
