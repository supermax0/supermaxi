# Discount / coupon engine

Models: `MobileCoupon`, `MobileDiscount`, `MobileCampaign`, redemptions.

Validation is server-side only (`services/discounts.py`). Cart stores applied coupon code + points; checkout preview recomputes totals before `StorefrontCheckoutService` creates the Finora invoice.
