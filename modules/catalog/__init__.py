"""FINORA Master Catalog (Smart Commerce V2, Sprint 3).

A *model* catalogue that is separate from FINORA Inventory: a catalogue entry is information about a device
(brand, model, barcodes, specs, media, sources). It owns no quantity, no cost and no ledger row, and it never
appears in the POS by itself. A store listing publishes an entry in the shop; it can later be *activated* into an
ordinary inventory product (quantity 0 — stock only ever comes from purchases / transfers).

Enabled per company with ``ui_flags["catalog_layer"]``; companies without the flag are untouched (no tables).
"""
