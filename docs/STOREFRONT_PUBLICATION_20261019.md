# Inventory storefront publication — 2026-10-19

A product with `active=1` and `store_visible=1` could still return 404 in a store using the shared installment catalogue: inventory updated the flag, while the catalogue required a published `InstallmentProduct`. The reported Xiaomi product (280) had no catalogue entry.

Explicitly enabling storefront visibility through the inventory API, new editor creation or visibility toggle now publishes through the existing catalogue write path in the same transaction. Existing catalogue descriptions, titles, prices, media and installment plans are preserved. Hiding the cash-store flag leaves independently published installment entries intact. Unrelated edits do not publish drafts or other products.

Product details now return the effective storefront state. The drawer explains inactive, hidden, other-branch and unpublished states and provides an explicit publish action for an enabled but unpublished product. The public default-branch policy is preserved.

Verification: 48 focused Python cases, including publication, rollback, preservation of balances and catalogue fields, public listing/detail/cart, existing storefront visibility and reservation behavior, paging, API contracts and product editor settings. Real Chrome reproduced a missing product, published it from the drawer and verified the public detail, search result and persisted publication state without JavaScript page errors.

Deployment backs up changed source, verifies hashes and checks authenticated HTTP routes. The specifically reported product is published through the audited inventory endpoint after a consistent SQLite backup; prices, balances and channel flags must be unchanged. No bulk publication or draft migration is performed.
