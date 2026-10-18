from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

from extensions import db
from flask import has_app_context


class CourierProfitPreviewService:
    """Build an order-profit preview without changing any accounting records."""

    @staticmethod
    def _row_val(row: Any, key: str, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _snapshot(row: Any) -> Dict[str, Any]:
        if hasattr(row, "get_invoice_snapshot"):
            return row.get_invoice_snapshot() or {}
        return CourierProfitPreviewService._row_val(row, "invoice_snapshot") or {}

    @staticmethod
    def _invoice_financials(invoice_ids: Iterable[int]) -> Dict[int, Dict[str, int]]:
        ids = sorted({int(value) for value in invoice_ids if value})
        if not ids or not has_app_context():
            return {}

        from models.invoice import Invoice
        from models.inventory_lot import OrderItemCostLayer
        from models.order_item import OrderItem
        from sqlalchemy import func
        from utils.inventory_lots import ensure_inventory_lot_schema
        from utils.order_item_costs import exclude_delivery_fee_items

        invoices = {
            int(invoice_id): int(total or 0)
            for invoice_id, total in (
                db.session.query(Invoice.id, Invoice.total)
                .filter(Invoice.id.in_(ids))
                .all()
            )
        }
        if not invoices:
            return {}

        try:
            ensure_inventory_lot_schema()
            layer_costs = (
                db.session.query(
                    OrderItemCostLayer.order_item_id.label("order_item_id"),
                    func.sum(
                        OrderItemCostLayer.quantity * OrderItemCostLayer.unit_cost
                    ).label("layer_cogs"),
                )
                .group_by(OrderItemCostLayer.order_item_id)
                .subquery()
            )
            rows = (
                db.session.query(
                    OrderItem.invoice_id,
                    func.count(OrderItem.id),
                    func.sum(
                        func.coalesce(
                            layer_costs.c.layer_cogs,
                            OrderItem.cost * OrderItem.quantity,
                        )
                    ),
                )
                .select_from(OrderItem)
                .outerjoin(
                    layer_costs,
                    layer_costs.c.order_item_id == OrderItem.id,
                )
                .filter(
                    OrderItem.invoice_id.in_(ids),
                    exclude_delivery_fee_items(OrderItem),
                )
                .group_by(OrderItem.invoice_id)
                .all()
            )
        except Exception:
            # Older tenants may not have lot layers yet. The stored item cost is
            # still the same fallback used by the payment ledger.
            rows = (
                db.session.query(
                    OrderItem.invoice_id,
                    func.count(OrderItem.id),
                    func.sum(OrderItem.cost * OrderItem.quantity),
                )
                .filter(
                    OrderItem.invoice_id.in_(ids),
                    exclude_delivery_fee_items(OrderItem),
                )
                .group_by(OrderItem.invoice_id)
                .all()
            )

        item_totals = {
            int(invoice_id): {
                "item_count": int(item_count or 0),
                "cogs": int(cogs or 0),
            }
            for invoice_id, item_count, cogs in rows
        }
        return {
            invoice_id: {
                "revenue": total,
                "item_count": item_totals.get(invoice_id, {}).get("item_count", 0),
                "cogs": item_totals.get(invoice_id, {}).get("cogs", 0),
            }
            for invoice_id, total in invoices.items()
        }

    @staticmethod
    def compute(analysis_rows: List[Any]) -> Dict[str, Any]:
        candidate_ids = {
            int(CourierProfitPreviewService._row_val(row, "matched_invoice_id"))
            for row in analysis_rows
            if CourierProfitPreviewService._row_val(row, "match_status") == "matched"
            and CourierProfitPreviewService._row_val(row, "matched_invoice_id")
        }
        financials = CourierProfitPreviewService._invoice_financials(candidate_ids)

        total_revenue = 0
        total_cogs = 0
        total_delivery_fees = 0
        total_profit = 0
        total_loss = 0
        net_profit = 0
        eligible_rows = 0
        skipped_rows = 0
        duplicate_invoice_rows = 0
        missing_cost_rows = 0
        seen_invoice_ids: Set[int] = set()
        order_profits: List[Dict[str, int]] = []

        for row in analysis_rows:
            status = CourierProfitPreviewService._row_val(row, "match_status")
            invoice_id = CourierProfitPreviewService._row_val(
                row, "matched_invoice_id"
            )
            if status != "matched" or not invoice_id:
                skipped_rows += 1
                continue

            invoice_id = int(invoice_id)
            if invoice_id in seen_invoice_ids:
                duplicate_invoice_rows += 1
                skipped_rows += 1
                continue
            seen_invoice_ids.add(invoice_id)

            data = financials.get(invoice_id)
            if not data:
                skipped_rows += 1
                continue

            # A missing product row is not treated as zero cost. Skipping it is
            # safer than overstating profit.
            if int(data.get("item_count") or 0) <= 0:
                missing_cost_rows += 1
                skipped_rows += 1
                continue

            revenue = int(data.get("revenue") or 0)
            cogs = int(data.get("cogs") or 0)
            delivery_fee = int(
                CourierProfitPreviewService._row_val(row, "delivery_fee") or 0
            )
            profit = revenue - cogs - delivery_fee

            eligible_rows += 1
            total_revenue += revenue
            total_cogs += cogs
            total_delivery_fees += delivery_fee
            net_profit += profit
            if profit >= 0:
                total_profit += profit
            else:
                total_loss += abs(profit)
            order_profits.append(
                {
                    "invoice_id": invoice_id,
                    "revenue": revenue,
                    "cogs": cogs,
                    "delivery_fee": delivery_fee,
                    "profit": profit,
                }
            )

        average_profit = (
            int(round(net_profit / eligible_rows)) if eligible_rows else None
        )
        margin_pct = (
            round((net_profit / total_revenue) * 100, 2)
            if total_revenue
            else None
        )
        return {
            "calculation": "invoice_total - product_cogs - courier_delivery_fee",
            "eligible_rows": eligible_rows,
            "skipped_rows": skipped_rows,
            "duplicate_invoice_rows": duplicate_invoice_rows,
            "missing_cost_rows": missing_cost_rows,
            "total_revenue": total_revenue if eligible_rows else None,
            "total_cogs": total_cogs if eligible_rows else None,
            "total_delivery_fees": (
                total_delivery_fees if eligible_rows else None
            ),
            "total_profit": total_profit if eligible_rows else None,
            "total_loss": total_loss if eligible_rows else None,
            "net_profit": net_profit if eligible_rows else None,
            "avg_profit": average_profit,
            "margin_pct": margin_pct,
            "orders": order_profits,
        }
