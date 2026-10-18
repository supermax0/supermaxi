"""Initial distribution wizard backend (spec phase 5): eligibility, draft, preview, approve, resumable execute.

Rules enforced here:
* nothing is selected by default and nothing runs without an explicit admin approval;
* a session executes at most once at a time (committed ``executing`` claim) and finished items are never
  repeated — a failed session can be resumed and only the pending/failed items are retried;
* stock moves as a real StockTransfer (send + receive, FIFO cost carried), cash as a real branch cash transfer,
  staff through the branch-assignment service. Nothing here writes a balance or a ledger row directly;
* invoice re-classification is NOT offered: historical documents are not rewritten.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from extensions import db
from models.branch import Branch
from models.branch_distribution import BranchDistribution
from utils.branch_management import BranchError, multi_branch_state

ITEM_TYPES = ("stock", "cash", "staff")
MAX_ITEMS = 500


def ensure_table() -> None:
    conn = db.session.connection()
    BranchDistribution.__table__.create(bind=conn, checkfirst=True)
    from sqlalchemy import inspect, text

    if "backup_path" not in {c["name"] for c in inspect(conn).get_columns("branch_distribution")}:
        conn.execute(text("ALTER TABLE branch_distribution ADD COLUMN backup_path VARCHAR(500)"))


def snapshot(doc: BranchDistribution) -> str | None:
    """Consistent copy of the tenant database taken before the first execution (SQLite tenants). Returns the
    path, or None when this database kind cannot be copied from here (PostgreSQL: take a server backup)."""
    import sqlite3
    from pathlib import Path

    from flask import current_app, g

    engine = db.session.get_bind()
    if engine.dialect.name != "sqlite":
        return None
    source = Path(str(engine.url.database or "")).resolve()
    if not source.is_file():
        return None
    if current_app.config.get("TESTING"):
        return "testing:no-copy"  # disposable test databases are not copied
    slug = str(getattr(g, "tenant", None) or source.stem)
    root = (Path(current_app.root_path) / "backups" / "branch-distribution").resolve()
    target_dir = (root / slug).resolve()
    if root not in target_dir.parents:
        raise BranchError("مسار نسخة الاستعادة غير صالح")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{doc.number}-{datetime.utcnow():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(str(source), timeout=30), sqlite3.connect(str(target), timeout=30)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return str(target)


def eligibility() -> dict[str, Any]:
    """Eligible only when branches are on, there are 2+ active branches, and the company already HAS operating
    data (invoices or stock layers) — a reliable data signal, not the creation date."""
    from models.inventory_lot import InventoryLot
    from models.invoice import Invoice

    state = multi_branch_state()
    active = Branch.query.filter(Branch.is_active.is_(True)).count()
    has_data = bool(Invoice.query.execution_options(skip_branch_scope=True).first()
                    or InventoryLot.query.first())
    reasons = []
    if not state["enabled"]:
        reasons.append("فعّل تعدد الفروع أولاً")
    if active < 2:
        reasons.append("أنشئ فرعاً ثانياً أولاً")
    if not has_data:
        reasons.append("شركة جديدة بلا بيانات تشغيلية — لا حاجة للتوزيع الأولي")
    return {"eligible": not reasons, "reasons": reasons}


def _load(doc: BranchDistribution) -> list[dict[str, Any]]:
    return json.loads(doc.items or "[]")


def _store(doc: BranchDistribution, items: list[dict[str, Any]]) -> None:
    doc.items = json.dumps(items, ensure_ascii=False)


def _clean(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ITEMS:
        raise BranchError(f"أضف من 1 إلى {MAX_ITEMS} عنصراً")
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict) or entry.get("type") not in ITEM_TYPES:
            raise BranchError("عنصر توزيع غير معروف")
        kind = entry["type"]
        try:
            if kind == "stock":
                item = {"type": kind, "product_id": int(entry["product_id"]),
                        "variant_color": (str(entry.get("variant_color") or "").strip() or None),
                        "quantity": int(entry["quantity"]), "from_branch_id": int(entry["from_branch_id"]),
                        "to_branch_id": int(entry["to_branch_id"])}
                if item["quantity"] < 1 or item["from_branch_id"] == item["to_branch_id"]:
                    raise ValueError
                key = (kind, item["product_id"], item["variant_color"], item["from_branch_id"], item["to_branch_id"])
            elif kind == "cash":
                item = {"type": kind, "from_account_id": int(entry["from_account_id"]),
                        "to_account_id": int(entry["to_account_id"]), "amount": int(entry["amount"])}
                if item["amount"] < 1 or item["from_account_id"] == item["to_account_id"]:
                    raise ValueError
                key = (kind, item["from_account_id"], item["to_account_id"])
            else:
                mode = str(entry.get("mode") or "extra")
                if mode not in ("extra", "move"):
                    raise ValueError
                item = {"type": kind, "employee_id": int(entry["employee_id"]),
                        "branch_id": int(entry["branch_id"]), "mode": mode}
                key = (kind, item["employee_id"], item["branch_id"])
        except (KeyError, TypeError, ValueError):
            raise BranchError("بيانات عنصر التوزيع غير صحيحة") from None
        if key in seen:
            raise BranchError("عنصر مكرر في الجلسة — جمّع الكميات في عنصر واحد")
        seen.add(key)
        out.append({**item, "state": "pending", "ref": None, "error": None})
    return out


def _number() -> str:
    return f"DST-{datetime.utcnow():%y%m%d}-{secrets.token_hex(3).upper()}"


def create(title: str, items: Any, *, by: int | None) -> BranchDistribution:
    ensure_table()
    if not eligibility()["eligible"]:
        raise BranchError("الشركة غير مؤهلة للتوزيع الأولي", "conflict", 409)
    title = (title or "").strip()
    if len(title) < 3:
        raise BranchError("اكتب عنواناً للجلسة")
    doc = BranchDistribution(number=_number(), title=title[:150], status="draft", created_by_id=by)
    _store(doc, _clean(items))
    db.session.add(doc)
    return doc


def replace_items(doc: BranchDistribution, items: Any) -> None:
    if doc.status not in ("draft", "ready"):
        raise BranchError("لا يمكن تعديل جلسة بدأ تنفيذها أو أُغلقت", "conflict", 409)
    _store(doc, _clean(items))
    doc.status = "draft"  # any change needs a fresh review/approval


def _fifo_value(branch_id: int, product_id: int, quantity: int) -> int:
    from models.inventory_lot import InventoryLot

    left, value = quantity, 0
    for lot in (InventoryLot.query.filter(InventoryLot.branch_id == branch_id, InventoryLot.product_id == product_id,
                                          InventoryLot.remaining_quantity > 0).order_by(InventoryLot.id).all()):
        take = min(left, int(lot.remaining_quantity))
        value += take * int(lot.unit_cost or 0)
        left -= take
        if not left:
            break
    return value


def _check(item: dict[str, Any]) -> tuple[str, str]:
    """('ready'|'blocked', reason) from the live data."""
    from models.employee import Employee
    from models.treasury_account import TreasuryAccount

    if item["type"] == "stock":
        from utils.branch_stock_service import get_available_branch_stock

        for key in ("from_branch_id", "to_branch_id"):
            if not Branch.query.filter_by(id=item[key], is_active=True).first():
                return "blocked", "فرع غير موجود أو مؤرشف"
        have = int(get_available_branch_stock(item["from_branch_id"], item["product_id"]) or 0)
        if have < item["quantity"]:
            return "blocked", f"المتاح بالفرع المصدر {have} فقط"
    elif item["type"] == "cash":
        from utils.branch_cash_transfers import _balance

        src = TreasuryAccount.query.execution_options(skip_branch_scope=True).get(item["from_account_id"])
        dst = TreasuryAccount.query.execution_options(skip_branch_scope=True).get(item["to_account_id"])
        if not src or not dst or not src.is_active or not dst.is_active:
            return "blocked", "صندوق غير فعّال"
        if not src.branch_id or not dst.branch_id or src.branch_id == dst.branch_id:
            return "blocked", "يلزم صندوقان بفرعين مختلفين"
        if _balance(src.id) < item["amount"]:
            return "blocked", "رصيد الصندوق المصدر لا يكفي"
    else:
        emp = Employee.query.execution_options(skip_branch_scope=True).get(item["employee_id"])
        if not emp or not emp.is_active or emp.role == "admin":
            return "blocked", "موظف غير صالح للتعيين"
        if not Branch.query.filter_by(id=item["branch_id"], is_active=True).first():
            return "blocked", "فرع غير موجود أو مؤرشف"
        if emp.branch_id == item["branch_id"]:
            return "blocked", "الموظف في هذا الفرع أصلاً"
    return "ready", ""


def preview(doc: BranchDistribution) -> dict[str, Any]:
    """Per-item verdict plus totals, from live data. Nothing is changed."""
    rows, units, value, cash, staff, blocked = [], 0, 0, 0, 0, 0
    for index, item in enumerate(_load(doc)):
        verdict, reason = ("done", "") if item["state"] == "done" else _check(item)
        if verdict == "blocked":
            blocked += 1
        row = {**item, "index": index, "verdict": verdict, "reason": reason}
        if item["type"] == "stock":
            units += item["quantity"]
            row["value"] = _fifo_value(item["from_branch_id"], item["product_id"], item["quantity"])
            value += row["value"]
        elif item["type"] == "cash":
            cash += item["amount"]
        else:
            staff += 1
        rows.append(row)
    return {"items": rows, "summary": {"stock_units": units, "stock_value": value, "cash": cash,
                                       "staff": staff, "blocked": blocked, "items": len(rows)},
            "can_execute": blocked == 0 and bool(rows)}


def approve(doc: BranchDistribution, by: int | None) -> None:
    if doc.status != "draft":
        raise BranchError("الجلسة ليست مسودة", "conflict", 409)
    if not preview(doc)["can_execute"]:
        raise BranchError("توجد عناصر غير مسموحة — عالجها قبل الاعتماد", "conflict", 409)
    doc.status, doc.approved_by_id, doc.approved_at = "ready", by, datetime.utcnow()


def cancel(doc: BranchDistribution) -> None:
    if doc.status not in ("draft", "ready"):
        raise BranchError("لا يُلغى بعد بدء التنفيذ", "conflict", 409)
    doc.status = "cancelled"


def _claim(doc: BranchDistribution, allowed: tuple[str, ...], target: str) -> None:
    from sqlalchemy import update

    res = db.session.execute(update(BranchDistribution).where(
        BranchDistribution.id == doc.id, BranchDistribution.status.in_(allowed)).values(status=target)
        .execution_options(synchronize_session=False))
    if res.rowcount != 1:
        db.session.rollback()
        raise BranchError("الجلسة قيد التنفيذ أو غير جاهزة", "conflict", 409)
    db.session.commit()
    db.session.refresh(doc)


def _do_stock(doc: BranchDistribution, index: int, item: dict[str, Any], user) -> str:
    from models.branch import StockTransfer, StockTransferLine
    from routes.stock_transfers import _apply_transfer_movements
    from utils.stock_transfer_state import transition

    tag = f"{doc.number}#{index}"
    row = StockTransfer.query.filter_by(note=tag).first()
    if row is None:
        row = StockTransfer(transfer_no=f"TR-{secrets.token_hex(6).upper()}", from_branch_id=item["from_branch_id"],
                            to_branch_id=item["to_branch_id"], status="draft", note=tag, created_by_id=user.id)
        db.session.add(row)
        db.session.flush()
        db.session.add(StockTransferLine(transfer_id=row.id, product_id=item["product_id"],
                                         variant_color=item["variant_color"], quantity=item["quantity"]))
        db.session.commit()
    if row.status == "draft":
        transition(row, {"draft"}, "sent")
        _apply_transfer_movements(row, "send")
        row.sent_at = datetime.utcnow()
        db.session.commit()
    if row.status == "sent":
        transition(row, {"sent"}, "received")
        _apply_transfer_movements(row, "receive")
        row.received_at, row.received_by_id = datetime.utcnow(), user.id
        for line in row.lines:
            line.quantity_received = line.quantity
        db.session.commit()
    return row.transfer_no or str(row.id)


def _started(doc: BranchDistribution, index: int, item: dict[str, Any]) -> bool:
    """A previous run already created this item's document: resume it, don't re-validate against the
    already-reduced live balance."""
    if item["type"] == "stock":
        from models.branch import StockTransfer

        return StockTransfer.query.filter_by(note=f"{doc.number}#{index}").first() is not None
    if item["type"] == "cash":
        from models.branch_cash_transfer import BranchCashTransfer

        return BranchCashTransfer.query.filter_by(operation_id=f"{doc.number}:{index}").first() is not None
    return False


def _do_item(doc: BranchDistribution, index: int, item: dict[str, Any], user) -> str:
    if item["type"] == "stock":
        return _do_stock(doc, index, item, user)
    if item["type"] == "cash":
        from utils import branch_cash_transfers as cash

        row = cash.create({"operation_id": f"{doc.number}:{index}", "from_account_id": item["from_account_id"],
                           "to_account_id": item["to_account_id"], "amount": item["amount"],
                           "reason": f"توزيع أولي {doc.number}"}, user, execute_now=True)
        db.session.refresh(row)
        if row.status != "completed":
            raise BranchError(f"التحويل النقدي لم يكتمل ({row.status})")
        return row.number
    from utils import branch_assignments

    if item["mode"] == "move":
        branch_assignments.move_home(item["employee_id"], item["branch_id"], by=user.id,
                                     note=f"توزيع أولي {doc.number}")
    else:
        branch_assignments.add_extra(item["employee_id"], item["branch_id"], by=user.id,
                                     note=f"توزيع أولي {doc.number}")
    db.session.commit()
    return f"employee:{item['employee_id']}"


def execute(doc: BranchDistribution, user) -> dict[str, Any]:
    """Runs pending/failed items one by one, each committed on its own. Safe to call again after a failure."""
    _claim(doc, ("ready", "failed"), "executing")
    if not doc.backup_path:
        try:
            doc.backup_path = snapshot(doc) or "unavailable"
            db.session.commit()
        except Exception as exc:  # noqa: BLE001 — never run without the restore copy where one can be made
            db.session.rollback()
            fresh = BranchDistribution.query.get(doc.id)
            fresh.status = "ready"
            db.session.commit()
            raise BranchError(f"تعذّر أخذ نسخة الاستعادة قبل التنفيذ: {exc}", "conflict", 409) from None
    items = _load(doc)
    for index, item in enumerate(items):
        if item["state"] == "done":
            continue
        try:
            if not _started(doc, index, item):
                verdict, reason = _check(item)
                if verdict == "blocked":
                    raise BranchError(reason)
            item["ref"] = _do_item(doc, index, item, user)
            item["state"], item["error"] = "done", None
        except Exception as exc:  # noqa: BLE001 — recorded per item, the session becomes resumable
            db.session.rollback()
            item["state"], item["error"] = "failed", str(exc)[:200]
        fresh = BranchDistribution.query.get(doc.id)
        _store(fresh, items)
        db.session.commit()
    doc = BranchDistribution.query.get(doc.id)
    done = all(i["state"] == "done" for i in items)
    doc.status = "completed" if done else "failed"
    doc.finished_at = datetime.utcnow() if done else None
    db.session.commit()
    return report(doc)


def report(doc: BranchDistribution) -> dict[str, Any]:
    items = _load(doc)
    return {"id": doc.id, "number": doc.number, "title": doc.title, "status": doc.status,
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "finished_at": doc.finished_at.isoformat() if doc.finished_at else "",
            "done": sum(1 for i in items if i["state"] == "done"),
            "failed": sum(1 for i in items if i["state"] == "failed"), "total": len(items), "items": items,
            "backup_path": doc.backup_path or ""}


def listing() -> list[dict[str, Any]]:
    ensure_table()
    return [report(d) | {"items": []} for d in BranchDistribution.query.order_by(BranchDistribution.id.desc()).all()]
