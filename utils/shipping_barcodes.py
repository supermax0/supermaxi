"""Helpers for multiple shipping-company barcodes per order."""

from __future__ import annotations

import json


def get_shipping_barcodes_list(invoice) -> list[str]:
    """Return saved shipping barcodes (one per piece when multi-qty)."""
    if invoice is None:
        return []
    raw = getattr(invoice, "shipping_barcodes_json", None)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
    single = (getattr(invoice, "shipping_barcode", None) or "").strip()
    return [single] if single else []


def set_shipping_barcodes(invoice, barcodes: list[str]) -> None:
    """Persist barcodes; keep legacy shipping_barcode as first value."""
    cleaned = [str(b).strip() for b in (barcodes or []) if str(b).strip()]
    invoice.shipping_barcodes_json = (
        json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    )
    invoice.shipping_barcode = cleaned[0] if cleaned else None


def shipping_barcodes_match_code(invoice, code: str) -> bool:
    code = (code or "").strip()
    if not code:
        return False
    return code in get_shipping_barcodes_list(invoice)


def shipping_barcodes_display(invoice) -> str:
    barcodes = get_shipping_barcodes_list(invoice)
    if not barcodes:
        return ""
    if len(barcodes) == 1:
        return barcodes[0]
    return " | ".join(barcodes)
