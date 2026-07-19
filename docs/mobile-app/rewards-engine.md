# Rewards engine

Ledger-based (`MobileRewardTransaction`), not balance-only.

- Welcome bonus on first login
- Purchase points stay `pending` until invoice status equals a confirm status (`مكتمل` / `مسدد` / `تم التوصيل`) — equality match avoids matching `غير مسدد`
- Redeem points / coupons applied server-side on cart before checkout
- Manual adjust via admin UI `/mobile-app/rewards` or admin API
