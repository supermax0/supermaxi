from __future__ import annotations

import json
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from extensions import db
from models.branch import Branch, BranchStock, StockTransfer
from models.inventory_audit import InventoryQuantityAudit, InventoryStockSnapshot
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.stock_movement import StockMovement
from modules.workspace.models.workspace_session import WorkspaceSession
from modules.workspace.services import event_bus
from modules.workspace.services.window_orchestrator import WindowOrchestrator
from utils.inventory_audit_trail import capture_product_snapshot, ensure_inventory_audit_schema


class InventoryForensicsError(Exception):
    pass


MOVEMENT_LABELS = {
    "order_deduct": "خروج مع طلب",
    "order_restore": "إرجاع من طلب",
    "purchase_receive": "استلام شراء",
    "purchase_reverse": "عكس شراء",
    "transfer_send": "نقل صادر",
    "transfer_receive": "نقل وارد",
    "transfer_cancel": "إلغاء نقل",
    "order_branch_move_out": "تحويل طلب من فرع",
    "order_branch_move_in": "تحويل طلب إلى فرع",
    "schedule_branch_move_out": "تغيير فرع تجهيز — صادر",
    "schedule_branch_move_in": "تغيير فرع تجهيز — وارد",
    "unclassified_adjustment": "تغيير مباشر غير مصنف",
}


class InventoryForensicsService:
    """Read-only reconstruction of product stock, sources and unit lifecycles."""

    @staticmethod
    def _dt(value: Optional[str], *, end: bool = False) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo:
                parsed = parsed.replace(tzinfo=None)
            if len(str(value)) <= 10:
                return datetime.combine(parsed.date(), time.max if end else time.min)
            return parsed
        except (TypeError, ValueError):
            raise InventoryForensicsError("صيغة التاريخ غير صحيحة.")

    @staticmethod
    def _json(raw: Optional[str]) -> Dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def catalog(query: str = "", limit: int = 200) -> Dict[str, Any]:
        q = Product.query
        text = str(query or "").strip()
        if text:
            like = f"%{text}%"
            q = q.filter(db.or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)))
        products = q.order_by(Product.active.desc(), Product.name.asc()).limit(max(1, min(int(limit), 500))).all()
        branches = Branch.query.order_by(Branch.is_default.desc(), Branch.name.asc()).all()
        stock_rows = BranchStock.query.filter(BranchStock.product_id.in_([p.id for p in products])).all() if products else []
        totals = defaultdict(int)
        by_branch = defaultdict(dict)
        for row in stock_rows:
            totals[int(row.product_id)] += int(row.quantity or 0)
            by_branch[int(row.product_id)][str(row.branch_id)] = int(row.quantity or 0)
        return {
            "products": [{
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "barcode": p.barcode,
                "active": bool(p.active),
                "quantity": totals.get(p.id, int(p.quantity or 0)),
                "branch_quantities": by_branch.get(p.id, {}),
            } for p in products],
            "branches": [b.to_dict() for b in branches],
        }

    @staticmethod
    def open_window(session: WorkspaceSession, analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        catalog = InventoryForensicsService.catalog(limit=500)
        props = {
            "catalog": catalog,
            "analysis": analysis,
            "analysisId": (analysis or {}).get("id") or "inventory-forensics",
        }
        window = WindowOrchestrator.ensure_window(session, {
            "id": "win_inventory_forensics",
            "type": "inventory_forensics",
            "title": "المحقق الذكي لحركات المخزون",
            "status": "ready" if analysis else "select_product",
            "placement": "left",
            "props": props,
            "interactive": True,
        }, "inventory_forensics")
        db.session.commit()
        return window

    @staticmethod
    def _branch_rows(product: Product, branch_id: Optional[int]) -> List[Dict[str, Any]]:
        query = BranchStock.query.filter_by(product_id=product.id)
        if branch_id:
            query = query.filter_by(branch_id=int(branch_id))
        rows = query.all()
        if rows:
            return [{
                "branch_id": row.branch_id,
                "branch_name": row.branch.name if row.branch else f"فرع #{row.branch_id}",
                "opening": int(row.opening_stock or 0),
                "actual": int(row.quantity or 0),
            } for row in rows]
        return [{
            "branch_id": None,
            "branch_name": "المخزون العام القديم",
            "opening": int(product.opening_stock or 0),
            "actual": int(product.quantity or 0),
        }]

    @staticmethod
    def _movement_query(product_id: int, branch_id: Optional[int] = None):
        query = StockMovement.query.filter_by(product_id=int(product_id))
        if branch_id:
            query = query.filter_by(branch_id=int(branch_id))
        return query.order_by(StockMovement.created_at.asc(), StockMovement.id.asc())

    @staticmethod
    def _load_sources(movements: Iterable[StockMovement]) -> Dict[str, Dict[int, Any]]:
        source_ids = defaultdict(set)
        for movement in movements:
            source_ids[movement.source_type].add(int(movement.source_id))
        invoices = {
            row.id: row
            for row in Invoice.query.filter(Invoice.id.in_(source_ids.get("invoice", set()))).all()
        } if source_ids.get("invoice") else {}
        purchases = {
            row.id: row
            for row in Purchase.query.filter(Purchase.id.in_(source_ids.get("purchase", set()))).all()
        } if source_ids.get("purchase") else {}
        transfers = {
            row.id: row
            for row in StockTransfer.query.filter(StockTransfer.id.in_(source_ids.get("stock_transfer", set()))).all()
        } if source_ids.get("stock_transfer") else {}
        return {"invoice": invoices, "purchase": purchases, "stock_transfer": transfers}

    @staticmethod
    def _invoice_detail(invoice: Invoice, line_id: Optional[int]) -> Dict[str, Any]:
        items = OrderItem.query.filter_by(invoice_id=invoice.id).order_by(OrderItem.id.asc()).all()
        line = next((item for item in items if item.id == line_id), None)
        return {
            "kind": "invoice",
            "id": invoice.id,
            "number": invoice.barcode or invoice.shipping_barcode or str(invoice.id),
            "customer": invoice.customer_name,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "employee_id": invoice.employee_id,
            "employee_name": invoice.employee_name,
            "branch_id": getattr(invoice, "branch_id", None),
            "line": ({"id": line.id, "name": line.product_name, "quantity": line.quantity, "price": line.price, "color": line.variant_color} if line else None),
            "related_items": [{"id": item.id, "product_id": item.product_id, "name": item.product_name, "quantity": item.quantity, "price": item.price, "color": item.variant_color} for item in items],
            "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        }

    @staticmethod
    def _purchase_detail(purchase: Purchase, line_id: Optional[int]) -> Dict[str, Any]:
        items = PurchaseItem.query.filter_by(purchase_id=purchase.id).order_by(PurchaseItem.id.asc()).all()
        line = next((item for item in items if item.id == line_id), None)
        return {
            "kind": "purchase",
            "id": purchase.id,
            "number": purchase.invoice_no or purchase.supplier_invoice_no or str(purchase.id),
            "supplier": purchase.supplier.name if purchase.supplier else f"مورد #{purchase.supplier_id}",
            "status": purchase.status,
            "branch_id": purchase.branch_id,
            "line": ({"id": line.id, "product_id": line.product_id, "quantity": line.quantity, "unit_cost": line.final_unit_cost, "total": line.line_total} if line else None),
            "related_items": [{"id": item.id, "product_id": item.product_id, "quantity": item.quantity, "unit_cost": item.final_unit_cost, "total": item.line_total} for item in items],
            "created_at": purchase.created_at.isoformat() if purchase.created_at else None,
        }

    @staticmethod
    def _transfer_detail(transfer: StockTransfer, line_id: Optional[int]) -> Dict[str, Any]:
        line = next((item for item in transfer.lines if item.id == line_id), None)
        return {
            "kind": "stock_transfer",
            "id": transfer.id,
            "number": transfer.transfer_no or str(transfer.id),
            "status": transfer.status,
            "from_branch": transfer.from_branch.name if transfer.from_branch else f"فرع #{transfer.from_branch_id}",
            "to_branch": transfer.to_branch.name if transfer.to_branch else f"فرع #{transfer.to_branch_id}",
            "created_by": transfer.created_by.name if transfer.created_by else None,
            "received_by": transfer.received_by.name if transfer.received_by else None,
            "line": ({"id": line.id, "product_id": line.product_id, "quantity": line.quantity, "quantity_received": line.quantity_received} if line else None),
            "related_items": [{"id": item.id, "product_id": item.product_id, "name": item.product.name if item.product else f"منتج #{item.product_id}", "quantity": item.quantity, "quantity_received": item.quantity_received} for item in transfer.lines],
            "created_at": transfer.created_at.isoformat() if transfer.created_at else None,
            "sent_at": transfer.sent_at.isoformat() if transfer.sent_at else None,
            "received_at": transfer.received_at.isoformat() if transfer.received_at else None,
        }

    @staticmethod
    def _source_detail(movement: StockMovement, sources: Dict[str, Dict[int, Any]]) -> Dict[str, Any]:
        source = sources.get(movement.source_type, {}).get(int(movement.source_id))
        if movement.source_type == "invoice" and source:
            return InventoryForensicsService._invoice_detail(source, movement.source_line_id)
        if movement.source_type == "purchase" and source:
            return InventoryForensicsService._purchase_detail(source, movement.source_line_id)
        if movement.source_type == "stock_transfer" and source:
            return InventoryForensicsService._transfer_detail(source, movement.source_line_id)
        return {"kind": movement.source_type, "id": movement.source_id, "number": str(movement.source_id), "related_items": []}

    @staticmethod
    def _audit_map(product_id: int, branch_id: Optional[int]) -> Dict[int, InventoryQuantityAudit]:
        query = InventoryQuantityAudit.query.filter_by(product_id=int(product_id))
        if branch_id:
            query = query.filter_by(branch_id=int(branch_id))
        return {row.movement_id: row for row in query.order_by(InventoryQuantityAudit.created_at.asc()).all() if row.movement_id}

    @staticmethod
    def _orphan_audits(product_id: int, branch_id: Optional[int]) -> List[InventoryQuantityAudit]:
        query = InventoryQuantityAudit.query.filter_by(product_id=int(product_id), movement_id=None)
        if branch_id:
            query = query.filter_by(branch_id=int(branch_id))
        return query.order_by(InventoryQuantityAudit.created_at.asc(), InventoryQuantityAudit.id.asc()).all()

    @staticmethod
    def _orphan_audit_rows(audits: List[InventoryQuantityAudit]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        rows, issues = [], []
        for audit in audits:
            branch_name = audit.branch.name if audit.branch else "بطاقة المنتج / المخزون العام"
            row = {
                "id": f"audit-{audit.id}",
                "movement_key": audit.event_key,
                "movement_type": "unclassified_adjustment",
                "label": "تغيير مباشر التقطه حارس قاعدة البيانات",
                "direction": "in" if int(audit.delta_quantity or 0) > 0 else "out",
                "quantity": abs(int(audit.delta_quantity or 0)),
                "delta": int(audit.delta_quantity or 0),
                "before": int(audit.before_quantity or 0),
                "after": int(audit.after_quantity or 0),
                "calculated_before": int(audit.before_quantity or 0),
                "calculated_after": int(audit.after_quantity or 0),
                "branch_id": audit.branch_id,
                "branch_name": branch_name,
                "unit_cost": 0,
                "total_cost": 0,
                "source_type": audit.source_type or "database_trigger",
                "source_id": audit.source_id or audit.product_id,
                "source_line_id": audit.source_line_id,
                "source": {"kind": "database_trigger", "id": audit.id, "number": audit.event_key, "related_items": []},
                "actor": audit.employee_name or "كتابة مباشرة / مسار قديم",
                "employee_id": audit.employee_id,
                "reason": audit.reason,
                "request_path": audit.request_path,
                "details": audit.get_metadata(),
                "risk": "critical",
                "risk_reason": "تغيرت الكمية من دون حركة بيع أو شراء أو راجع أو نقل مرتبطة بها.",
                "created_at": audit.created_at.isoformat() if audit.created_at else None,
            }
            rows.append(row)
            issues.append({"severity": "critical", "movement_id": row["id"], "title": row["label"], "message": row["risk_reason"], "created_at": row["created_at"]})
        return rows, issues

    @staticmethod
    def _movement_rows(
        movements: List[StockMovement],
        branch_opening: Dict[Optional[int], int],
        audits: Dict[int, InventoryQuantityAudit],
        sources: Dict[str, Dict[int, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        balances = dict(branch_opening)
        rows = []
        issues = []
        for movement in movements:
            branch_key = int(movement.branch_id) if movement.branch_id else None
            before = balances.get(branch_key, 0)
            delta = int(movement.quantity) if movement.direction == "in" else -int(movement.quantity)
            after = before + delta
            balances[branch_key] = after
            audit = audits.get(movement.id)
            source = InventoryForensicsService._source_detail(movement, sources)
            details = InventoryForensicsService._json(movement.details_json)
            risk = "normal"
            risk_reason = None
            if movement.movement_type == "unclassified_adjustment":
                risk, risk_reason = "critical", "تغيير مباشر التقطه نظام التدقيق لكنه غير مرتبط بمسار بيع/شراء/نقل معروف."
            elif after < 0:
                risk, risk_reason = "critical", "الرصيد المحسوب أصبح سالباً بعد هذه الحركة."
            elif audit and audit.before_quantity != before:
                risk, risk_reason = "warning", "رصيد قبل الحركة في سجل التدقيق لا يطابق الرصيد المعاد احتسابه."
            actor = (audit.employee_name if audit else None) or source.get("employee_name") or source.get("created_by") or source.get("received_by")
            row = {
                "id": movement.id,
                "movement_key": movement.movement_key,
                "movement_type": movement.movement_type,
                "label": MOVEMENT_LABELS.get(movement.movement_type, movement.movement_type.replace("_", " ")),
                "direction": movement.direction,
                "quantity": int(movement.quantity),
                "delta": delta,
                "before": audit.before_quantity if audit else before,
                "after": audit.after_quantity if audit else after,
                "calculated_before": before,
                "calculated_after": after,
                "branch_id": movement.branch_id,
                "branch_name": movement.branch.name if movement.branch else "المخزون العام",
                "unit_cost": int(movement.unit_cost or 0),
                "total_cost": int(movement.total_cost or 0),
                "source_type": movement.source_type,
                "source_id": movement.source_id,
                "source_line_id": movement.source_line_id,
                "source": source,
                "actor": actor,
                "employee_id": audit.employee_id if audit else source.get("employee_id"),
                "reason": (audit.reason if audit else None) or details.get("reason"),
                "request_path": audit.request_path if audit else details.get("request_path"),
                "details": details,
                "risk": risk,
                "risk_reason": risk_reason,
                "created_at": movement.created_at.isoformat() if movement.created_at else None,
            }
            rows.append(row)
            if risk != "normal":
                issues.append({"severity": risk, "movement_id": movement.id, "title": row["label"], "message": risk_reason, "created_at": row["created_at"]})
        return rows, issues

    @staticmethod
    def _source_expected(product_id: int, branch_id: Optional[int]) -> int:
        try:
            from utils.inventory_movements import get_product_inventory_movements

            movements = get_product_inventory_movements(product_id, branch_id=branch_id)
            return sum(int(item.get("quantity_in") or 0) - int(item.get("quantity_out") or 0) for item in movements if item.get("type") != "stock_reconciliation")
        except Exception:
            db.session.rollback()
            return 0

    @staticmethod
    def _snapshot_comparisons(product_id: int, branch_rows: List[Dict[str, Any]], movements: List[StockMovement]) -> List[Dict[str, Any]]:
        comparisons = []
        for branch in branch_rows:
            branch_id = branch["branch_id"]
            query = InventoryStockSnapshot.query.filter_by(product_id=product_id, branch_id=branch_id)
            snapshot = query.order_by(InventoryStockSnapshot.captured_at.desc()).first()
            if not snapshot:
                comparisons.append({"branch_id": branch_id, "branch_name": branch["branch_name"], "has_baseline": False, "actual": branch["actual"]})
                continue
            delta = sum(
                (int(m.quantity) if m.direction == "in" else -int(m.quantity))
                for m in movements
                if (int(m.branch_id) if m.branch_id else None) == branch_id
                and m.created_at and m.created_at > snapshot.captured_at
            )
            expected = int(snapshot.quantity) + delta
            comparisons.append({
                "branch_id": branch_id,
                "branch_name": branch["branch_name"],
                "has_baseline": True,
                "baseline_at": snapshot.captured_at.isoformat(),
                "baseline_quantity": int(snapshot.quantity),
                "documented_delta": delta,
                "expected": expected,
                "actual": branch["actual"],
                "difference": int(branch["actual"]) - expected,
                "is_balanced": expected == int(branch["actual"]),
            })
        return comparisons

    @staticmethod
    def _unit_traces(product: Product, branch_rows: List[Dict[str, Any]], movements: List[StockMovement], actual_by_branch: Dict[Optional[int], int]) -> Dict[str, Any]:
        units: Dict[str, Dict[str, Any]] = {}
        available: Dict[Optional[int], deque] = defaultdict(deque)
        transfer_buffer: Dict[Tuple[int, Optional[int]], List[str]] = defaultdict(list)
        order_buffer: Dict[Tuple[int, Optional[int]], List[str]] = defaultdict(list)

        def make_unit(trace_id: str, branch_id: Optional[int], origin: str, at: Optional[datetime], movement_id: Optional[int] = None):
            unit = {
                "trace_id": trace_id,
                "product_id": product.id,
                "product_name": product.name,
                "barcode": product.barcode,
                "origin": origin,
                "origin_movement_id": movement_id,
                "current_branch_id": branch_id,
                "status": "in_stock",
                "entered_at": at.isoformat() if at else None,
                "exited_at": None,
                "events": [],
            }
            units[trace_id] = unit
            available[branch_id].append(trace_id)
            return unit

        for branch in branch_rows:
            for index in range(max(0, int(branch["opening"]))):
                make_unit(f"P{product.id}-B{branch['branch_id'] or 0}-OPEN-U{index + 1:05d}", branch["branch_id"], "opening_stock", product.created_at)

        anomalies = []
        for movement in movements:
            branch_id = int(movement.branch_id) if movement.branch_id else None
            qty = int(movement.quantity)
            source_key = (int(movement.source_id), int(movement.source_line_id) if movement.source_line_id else None)
            if movement.direction == "in":
                reused = []
                if movement.movement_type == "transfer_receive":
                    reused = transfer_buffer.pop(source_key, [])[:qty]
                elif movement.movement_type == "order_restore":
                    reused = order_buffer.pop(source_key, [])[:qty]
                for trace_id in reused:
                    unit = units[trace_id]
                    unit["status"] = "in_stock"
                    unit["current_branch_id"] = branch_id
                    unit["exited_at"] = None
                    unit["events"].append({"movement_id": movement.id, "type": movement.movement_type, "direction": "in", "branch_id": branch_id, "at": movement.created_at.isoformat() if movement.created_at else None})
                    available[branch_id].append(trace_id)
                for index in range(qty - len(reused)):
                    trace_id = f"P{product.id}-M{movement.id}-U{index + 1:05d}"
                    unit = make_unit(trace_id, branch_id, movement.movement_type, movement.created_at, movement.id)
                    unit["events"].append({"movement_id": movement.id, "type": movement.movement_type, "direction": "in", "branch_id": branch_id, "at": movement.created_at.isoformat() if movement.created_at else None})
                continue

            consumed = []
            for _ in range(qty):
                if available[branch_id]:
                    consumed.append(available[branch_id].popleft())
                else:
                    trace_id = f"P{product.id}-M{movement.id}-UNKNOWN-OUT-U{len(consumed) + 1:05d}"
                    units[trace_id] = {
                        "trace_id": trace_id, "product_id": product.id, "product_name": product.name,
                        "barcode": product.barcode, "origin": "unknown", "origin_movement_id": None,
                        "current_branch_id": branch_id, "status": "unknown_out", "entered_at": None,
                        "exited_at": movement.created_at.isoformat() if movement.created_at else None, "events": [],
                    }
                    consumed.append(trace_id)
                    anomalies.append({"severity": "critical", "movement_id": movement.id, "message": "خرجت قطعة لا يملك سجل التتبع لها دخولاً سابقاً."})
            for trace_id in consumed:
                unit = units[trace_id]
                unit["status"] = "transferred" if movement.movement_type == "transfer_send" else "sold_or_out"
                unit["current_branch_id"] = branch_id
                unit["exited_at"] = movement.created_at.isoformat() if movement.created_at else None
                unit["events"].append({"movement_id": movement.id, "type": movement.movement_type, "direction": "out", "branch_id": branch_id, "at": movement.created_at.isoformat() if movement.created_at else None, "source_type": movement.source_type, "source_id": movement.source_id})
            if movement.movement_type == "transfer_send":
                transfer_buffer[source_key].extend(consumed)
            elif movement.movement_type == "order_deduct":
                order_buffer[source_key].extend(consumed)

        for branch_id, actual in actual_by_branch.items():
            tracked = len(available[branch_id])
            difference = int(actual) - tracked
            if difference > 0:
                for index in range(difference):
                    trace_id = f"P{product.id}-B{branch_id or 0}-UNEXPLAINED-IN-U{index + 1:05d}"
                    unit = make_unit(trace_id, branch_id, "unexplained_balance", datetime.utcnow())
                    unit["status"] = "unverified_extra"
                anomalies.append({"severity": "critical", "branch_id": branch_id, "message": f"توجد {difference} قطعة فعلية بلا حركة دخول موثقة."})
            elif difference < 0:
                missing = min(abs(difference), len(available[branch_id]))
                for _ in range(missing):
                    trace_id = available[branch_id].pop()
                    units[trace_id]["status"] = "missing_unexplained"
                    units[trace_id]["exited_at"] = datetime.utcnow().isoformat()
                anomalies.append({"severity": "critical", "branch_id": branch_id, "message": f"هناك {abs(difference)} قطعة مفقودة مقارنة بسجل التتبع."})

        ordered = sorted(units.values(), key=lambda item: (item["status"] != "in_stock", item["trace_id"]))
        return {
            "total": len(ordered),
            "in_stock": sum(item["status"] in {"in_stock", "unverified_extra"} for item in ordered),
            "out": sum(item["status"] in {"sold_or_out", "transferred"} for item in ordered),
            "missing": sum(item["status"] in {"missing_unexplained", "unknown_out"} for item in ordered),
            "items": ordered[:2000],
            "truncated": len(ordered) > 2000,
            "anomalies": anomalies,
        }

    @staticmethod
    def _root_cause_analysis(
        *,
        movement_rows: List[Dict[str, Any]],
        snapshot_comparisons: List[Dict[str, Any]],
        reconciliations: List[Dict[str, Any]],
        unit_traces: Dict[str, Any],
        product_quantity: int,
        all_branch_total: int,
    ) -> Dict[str, Any]:
        """Explain the most likely cause, evidence and next safe action."""
        diagnoses: List[Dict[str, Any]] = []

        def add(code, title, explanation, *, severity="warning", confidence=75, evidence=None, action=""):
            diagnoses.append({
                "code": code,
                "title": title,
                "explanation": explanation,
                "severity": severity,
                "confidence": int(confidence),
                "evidence": list(evidence or []),
                "recommended_action": action,
            })

        direct = [
            row for row in movement_rows
            if row.get("source", {}).get("kind") == "database_trigger"
            or str(row.get("id", "")).startswith("audit-")
        ]
        if direct:
            latest = direct[-1]
            delta = int(latest.get("delta") or 0)
            direction = "نقصت" if delta < 0 else "زادت"
            path = latest.get("request_path")
            evidence = [
                f"الكمية {direction} من {latest.get('before')} إلى {latest.get('after')} ({delta:+d}).",
                f"وقت الالتقاط: {latest.get('created_at') or 'غير متوفر'}.",
                "لا توجد حركة بيع أو شراء أو راجع أو نقل مرتبطة بهذا التغيير.",
            ]
            if path:
                evidence.append(f"المسار الذي نفّذ التغيير: {path}.")
            add(
                "direct_database_write",
                "تغيير مباشر تجاوز مسار المخزون الطبيعي",
                "السبب الأقوى هو أن جزءاً قديماً من البرنامج أو تعديلاً يدوياً كتب الكمية مباشرة. لذلك تغير الرصيد من دون إنشاء حركة تشرح من أخذ القطعة أو إلى أين ذهبت.",
                severity="critical",
                confidence=99,
                evidence=evidence,
                action="راجع الحركة المبينة واسم المنفذ أو مسار الشاشة، ثم صحح الرصيد بمحضر جرد. لا تحذف السجل لأنه دليل الخلل.",
            )

        broken_snapshots = [row for row in snapshot_comparisons if row.get("has_baseline") and not row.get("is_balanced")]
        for row in broken_snapshots:
            diff = int(row.get("difference") or 0)
            if diff < 0:
                title = "فقد فعلي بين فحصين بلا حركة خروج"
                explanation = "الكمية انخفضت، لكن لا يوجد بيع أو نقل أو راجع أو تعديل موثق يفسر الانخفاض. هذا يستبعد البيع المسجل ويشير إلى تعديل مباشر، مسار قديم، أو حذف/استبدال رصيد خارج السجل."
            else:
                title = "زيادة فعلية بين فحصين بلا حركة دخول"
                explanation = "الكمية زادت من دون شراء أو راجع أو نقل وارد موثق. الاحتمال الأقوى إضافة مباشرة أو تكرار مزامنة قديمة."
            add(
                "snapshot_unexplained_change",
                title,
                explanation,
                severity="critical",
                confidence=97,
                evidence=[
                    f"الفرع: {row.get('branch_name')}",
                    f"خط الأساس {row.get('baseline_quantity')}، والحركات الموثقة {int(row.get('documented_delta') or 0):+d}، والمفروض {row.get('expected')}، والفعلي {row.get('actual')}.",
                    f"الفرق غير المفسر: {diff:+d} قطعة.",
                ],
                action="نفّذ جرداً للمنتج في هذا الفرع وراجع المستخدمين والشاشات التي عدلت المخزون بعد وقت خط الأساس.",
            )

        transfers: Dict[Tuple[Any, Any], Dict[str, Any]] = defaultdict(lambda: {"sent": 0, "received": 0, "cancelled": 0, "rows": []})
        for row in movement_rows:
            mtype = row.get("movement_type")
            if mtype not in {"transfer_send", "transfer_receive", "transfer_cancel"}:
                continue
            key = (row.get("source_id"), row.get("source_line_id"))
            entry = transfers[key]
            entry["rows"].append(row)
            if mtype == "transfer_send":
                entry["sent"] += int(row.get("quantity") or 0)
            elif mtype == "transfer_receive":
                entry["received"] += int(row.get("quantity") or 0)
            else:
                entry["cancelled"] += int(row.get("quantity") or 0)
        for (transfer_id, line_id), entry in transfers.items():
            gap = entry["sent"] - entry["received"] - entry["cancelled"]
            if gap <= 0:
                continue
            first = entry["rows"][0]
            source = first.get("source") or {}
            add(
                "transfer_not_completed",
                "قطع خرجت بتحويل ولم يُسجل استلامها أو إلغاؤها",
                "هذه القطع خرجت من الفرع المصدر، لكن الطرف الآخر لم يسجل استلام كامل الكمية ولم يرجعها الإلغاء؛ لذلك تظهر وكأنها ضاعت بين الفرعين.",
                severity="critical",
                confidence=98,
                evidence=[
                    f"رقم النقل: {source.get('number') or transfer_id}، سطر {line_id or 'غير محدد'}.",
                    f"المرسل {entry['sent']}، المستلم {entry['received']}، الملغى/المعاد {entry['cancelled']}، العالق {gap}.",
                    f"المسار: {source.get('from_branch') or 'الفرع المصدر'} ← {source.get('to_branch') or 'الفرع المستلم'}.",
                ],
                action="افتح عملية النقل نفسها وراجع الاستلام. إذا وصلت البضاعة سجّل الاستلام، وإذا لم تصل ألغِ النقل بمحضر واضح.",
            )

        if int(product_quantity) != int(all_branch_total):
            difference = int(product_quantity) - int(all_branch_total)
            add(
                "product_branch_sync_mismatch",
                "بطاقة المنتج غير متزامنة مع أرصدة الفروع",
                "الرقم العام للمنتج لا يساوي مجموع المخزون الموجود فعلياً في الفروع. هذا يحصل عادةً عند تعديل بطاقة المنتج مباشرة أو توقف الحفظ قبل اكتمال مزامنة الفروع.",
                severity="critical",
                confidence=96,
                evidence=[
                    f"بطاقة المنتج: {int(product_quantity)} قطعة.",
                    f"مجموع الفروع: {int(all_branch_total)} قطعة.",
                    f"فرق المزامنة: {difference:+d} قطعة.",
                ],
                action="اعتبر مجموع الفروع هو المرجع بعد الجرد، ثم نفّذ مزامنة بطاقة المنتج ولا تعدّل الرقم العام يدوياً.",
            )

        broken_reconciliations = [row for row in reconciliations if not row.get("is_balanced")]
        if broken_reconciliations and not direct and not broken_snapshots:
            row = max(broken_reconciliations, key=lambda item: abs(int(item.get("ledger_difference") or 0)))
            diff = int(row.get("ledger_difference") or 0)
            add(
                "historical_ledger_gap",
                "حركة تاريخية ناقصة من سجل المنتج",
                "الرصيد الحالي لا يمكن إعادة تكوينه من المخزون الافتتاحي والحركات المتوفرة. غالباً حدث التغيير قبل تفعيل سجل التدقيق، أو نفذه مسار قديم لم يكن ينشئ حركة مخزون.",
                severity="warning",
                confidence=82,
                evidence=[
                    f"الفرع: {row.get('branch_name')}.",
                    f"الفعلي {row.get('actual')}، المتوقع من السجل {row.get('ledger_expected')}، الفرق {diff:+d}.",
                ],
                action="راجع آخر جرد قديم والفواتير والتحويلات السابقة، ثم اعتمد رصيد افتتاح تدقيقي مرة واحدة بعد الجرد.",
            )

        if int(unit_traces.get("missing") or 0) and not diagnoses:
            add(
                "unit_history_incomplete",
                "قطع بلا مصدر دخول مكتمل",
                "ظهر خروج لقطع لا يملك السجل لها عملية دخول أو رصيد افتتاحي كافٍ. الاحتمال الأقرب أن تاريخ المنتج القديم غير مكتمل.",
                confidence=80,
                evidence=[f"عدد القطع المفقودة أو الغامضة: {int(unit_traces.get('missing') or 0)}."],
                action="راجع المخزون الافتتاحي وأقدم عمليات الشراء، ثم ثبّت جرداً افتتاحياً موثقاً.",
            )

        severity_rank = {"critical": 2, "warning": 1, "info": 0}
        diagnoses.sort(key=lambda item: (severity_rank.get(item["severity"], 0), item["confidence"]), reverse=True)
        if not diagnoses:
            return {
                "status": "explained_healthy",
                "primary": {
                    "code": "no_unexplained_loss",
                    "title": "لا يوجد فقد غير مفسر ضمن الأدلة الحالية",
                    "explanation": "الرصيد الحالي متوافق مع الحركات المسجلة، ولم يظهر نقل ناقص أو تعديل مباشر أو فرق بين بطاقة المنتج والفروع.",
                    "severity": "info",
                    "confidence": 95,
                    "evidence": ["تطابقت الحركات مع الرصيد المتاح وقت الفحص."],
                    "recommended_action": "لا يلزم تصحيح. أعد الفحص لاحقاً للحفاظ على خط المقارنة الزمني.",
                },
                "alternatives": [],
            }
        return {"status": "cause_found", "primary": diagnoses[0], "alternatives": diagnoses[1:4]}

    @staticmethod
    def analyze(
        session: WorkspaceSession,
        product_id: int,
        *,
        branch_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        ensure_inventory_audit_schema()
        product = Product.query.get(int(product_id))
        if not product:
            raise InventoryForensicsError("المنتج المطلوب غير موجود.")
        selected_branch = Branch.query.get(int(branch_id)) if branch_id else None
        if branch_id and not selected_branch:
            raise InventoryForensicsError("الفرع المطلوب غير موجود.")
        start = InventoryForensicsService._dt(date_from)
        end = InventoryForensicsService._dt(date_to, end=True)

        branch_rows = InventoryForensicsService._branch_rows(product, branch_id)
        all_movements = InventoryForensicsService._movement_query(product.id, branch_id).all()
        audit_map = InventoryForensicsService._audit_map(product.id, branch_id)
        orphan_audits = InventoryForensicsService._orphan_audits(product.id, branch_id)
        sources = InventoryForensicsService._load_sources(all_movements)
        opening_map = {row["branch_id"]: row["opening"] for row in branch_rows}
        movement_rows, issues = InventoryForensicsService._movement_rows(all_movements, opening_map, audit_map, sources)
        orphan_rows, orphan_issues = InventoryForensicsService._orphan_audit_rows(orphan_audits)
        movement_rows.extend(orphan_rows)
        movement_rows.sort(key=lambda row: (row.get("created_at") or "", str(row.get("id") or "")))
        issues.extend(orphan_issues)
        snapshot_comparisons = InventoryForensicsService._snapshot_comparisons(product.id, branch_rows, all_movements)

        reconciliations = []
        for branch in branch_rows:
            bid = branch["branch_id"]
            ledger_delta = sum(row["delta"] for row in movement_rows if row["branch_id"] == bid)
            ledger_expected = int(branch["opening"]) + ledger_delta
            source_expected = InventoryForensicsService._source_expected(product.id, bid)
            actual = int(branch["actual"])
            rec = {
                **branch,
                "ledger_expected": ledger_expected,
                "ledger_difference": actual - ledger_expected,
                "source_expected": source_expected,
                "source_difference": actual - source_expected,
                "is_balanced": actual in {ledger_expected, source_expected},
            }
            reconciliations.append(rec)
            if actual != ledger_expected and actual != source_expected:
                issues.append({"severity": "critical", "branch_id": bid, "title": "فرق غير مبرر في الرصيد", "message": f"الفعلي {actual}، حسب سجل الحركات {ledger_expected}، وحسب مصادر الطلبات والشراء {source_expected}. الفرق يحتاج مراجعة.", "created_at": None})
            elif actual != ledger_expected:
                issues.append({"severity": "warning", "branch_id": bid, "title": "السجل غير المكتمل تاريخياً", "message": "الرصيد يطابق المصادر التشغيلية لكن سجل الحركات غير المتغير لا يغطي كل التاريخ القديم.", "created_at": None})

        branch_total = sum(int(row["actual"]) for row in branch_rows) if branch_rows and branch_rows[0]["branch_id"] is not None else int(product.quantity or 0)
        all_branch_total = int(db.session.query(db.func.coalesce(db.func.sum(BranchStock.quantity), 0)).filter(BranchStock.product_id == product.id).scalar() or 0)
        branch_stock_count = BranchStock.query.filter_by(product_id=product.id).count()
        if branch_stock_count and int(product.quantity or 0) != all_branch_total:
            issues.append({"severity": "critical", "title": "مجموع الفروع لا يطابق بطاقة المنتج", "message": f"بطاقة المنتج تعرض {int(product.quantity or 0)} بينما مجموع الفروع {all_branch_total}. قد توجد كتابة مباشرة أو مزامنة ناقصة.", "created_at": None})

        for comparison in snapshot_comparisons:
            if comparison.get("has_baseline") and not comparison.get("is_balanced"):
                issues.append({"severity": "critical", "branch_id": comparison.get("branch_id"), "title": "تغير بين فحصين بلا حركة", "message": f"منذ فحص {comparison.get('baseline_at')} كان المتوقع {comparison.get('expected')} لكن الفعلي {comparison.get('actual')} (فرق {comparison.get('difference'):+d}).", "created_at": comparison.get("baseline_at")})

        actual_by_branch = {row["branch_id"]: int(row["actual"]) for row in branch_rows}
        unit_traces = InventoryForensicsService._unit_traces(product, branch_rows, all_movements, actual_by_branch)
        issues.extend(unit_traces["anomalies"])

        diagnosis = InventoryForensicsService._root_cause_analysis(
            movement_rows=movement_rows,
            snapshot_comparisons=snapshot_comparisons,
            reconciliations=reconciliations,
            unit_traces=unit_traces,
            product_quantity=int(product.quantity or 0),
            all_branch_total=(all_branch_total if branch_stock_count else int(product.quantity or 0)),
        )

        filtered_rows = [
            row for row in movement_rows
            if (not start or (row["created_at"] and datetime.fromisoformat(row["created_at"]) >= start))
            and (not end or (row["created_at"] and datetime.fromisoformat(row["created_at"]) <= end))
        ]
        critical_count = sum(item.get("severity") == "critical" for item in issues)
        warning_count = sum(item.get("severity") == "warning" for item in issues)
        analysis = {
            "id": str(uuid.uuid4()),
            "session_id": session.id,
            "created_at": datetime.utcnow().isoformat(),
            "filters": {"product_id": product.id, "branch_id": branch_id, "date_from": date_from, "date_to": date_to},
            "product": {"id": product.id, "name": product.name, "sku": product.sku, "barcode": product.barcode, "active": bool(product.active), "product_quantity": int(product.quantity or 0), "all_branches_quantity": all_branch_total or branch_total, "buy_price": int(product.buy_price or 0)},
            "selected_branch": selected_branch.to_dict() if selected_branch else None,
            "summary": {
                "health": "critical" if critical_count else "warning" if warning_count else "healthy",
                "actual_quantity": sum(int(row["actual"]) for row in branch_rows),
                "movements_count": len(filtered_rows),
                "total_in": sum(row["quantity"] for row in filtered_rows if row["direction"] == "in"),
                "total_out": sum(row["quantity"] for row in filtered_rows if row["direction"] == "out"),
                "critical_issues": critical_count,
                "warnings": warning_count,
                "unclassified_movements": sum(row["movement_type"] == "unclassified_adjustment" for row in movement_rows),
            },
            "reconciliations": reconciliations,
            "snapshot_comparisons": snapshot_comparisons,
            "movements": list(reversed(filtered_rows)),
            "issues": issues,
            "diagnosis": diagnosis,
            "units": unit_traces,
            "coverage": {
                "first_immutable_movement_at": all_movements[0].created_at.isoformat() if all_movements else None,
                "last_immutable_movement_at": all_movements[-1].created_at.isoformat() if all_movements else None,
                "has_before_after_audit": bool(audit_map),
                "has_previous_snapshot": any(item.get("has_baseline") for item in snapshot_comparisons),
                "note": "معرّفات القطع التاريخية معرّفات تتبع محاسبية أعاد النظام بناءها؛ ليست أرقاماً تسلسلية مطبوعة على القطعة إلا إذا كان الباركود مسجلاً.",
            },
        }

        meta = session.get_metadata() or {}
        meta["inventory_forensics_analysis"] = analysis
        session.set_metadata(meta)
        InventoryForensicsService.open_window(session, analysis)
        capture_product_snapshot(product.id, session_id=session.id)
        db.session.commit()
        event_bus.emit_event(session.id, "inventory.forensics.completed", {"analysis": analysis}, message=f"اكتمل تدقيق مخزون {product.name}", user_id=user_id)
        event_bus.emit_event(session.id, "window.updated", {"windows": session.get_windows()}, user_id=user_id)
        return analysis
