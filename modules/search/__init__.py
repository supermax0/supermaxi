"""FINORA Intelligent Product Search (Smart Commerce V2, Sprint 6).

Understands Arabic spelling variants, Iraqi dialect, brand nicknames, units («طن ونص», «55 انج», «12 كيلو») and
budgets («بأقل من 400 ألف»). Exact model / barcode matches always come first. The index is a derived, cached copy
of the shop's own products — never a source of truth — and the shop falls back to the plain search if it fails.
"""
