"""Real merge of duplicate delivery-agent records (same branch, same name + phone).

Destructive in spirit, so: preview first; only duplicates inside ONE branch (per-branch copies are legitimate
and are never merged); a duplicate that carries payroll (salary / pay type / a linked employee different from
the primary's) is flagged "needs review" and refused; duplicates are deactivated, never deleted; their
invoices, location trail and counters move to the primary; a database copy is taken first where possible.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from extensions import db
from models.delivery_agent import DeliveryAgent
from utils.branch_management import BranchError


def _key(agent: DeliveryAgent) -> tuple[Any, str]:
    name = " ".join(str(agent.name or "").split()).casefold()
    phone = "".join(ch for ch in str(agent.phone or "") if ch.isdigit())[-10:]
    return agent.branch_id, f"{name}|{phone}"


def _primary(members: list[DeliveryAgent]) -> DeliveryAgent:
    # portal login first, then active, then oldest — the same representative the shipping center displays
    return sorted(members, key=lambda a: (not a.username, not a.is_active, a.id))[0]


def _payroll_blocker(primary: DeliveryAgent, dup: DeliveryAgent) -> str:
    if int(dup.salary or 0) > 0 or (dup.pay_type or "none") != "none":
        return "عليه راتب/نظام دفع — يحتاج مراجعة يدوية"
    if dup.employee_id and dup.employee_id != primary.employee_id:
        return "مربوط بموظف مختلف — يحتاج مراجعة يدوية"
    return ""


def duplicates() -> list[dict[str, Any]]:
    from models.invoice import Invoice

    groups: dict[tuple[Any, str], list[DeliveryAgent]] = {}
    for agent in DeliveryAgent.query.execution_options(skip_branch_scope=True).order_by(DeliveryAgent.id).all():
        if not agent.name:
            continue
        groups.setdefault(_key(agent), []).append(agent)
    out = []
    for (branch_id, _), members in groups.items():
        if len(members) < 2:
            continue
        primary = _primary(members)
        dups = [m for m in members if m.id != primary.id and m.is_active]
        if not dups:
            continue
        rows = []
        for d in dups:
            invoices = Invoice.query.execution_options(skip_branch_scope=True).filter_by(delivery_agent_id=d.id).count()
            rows.append({"id": d.id, "invoices": invoices, "has_login": bool(d.username),
                         "blocker": _payroll_blocker(primary, d)})
        out.append({"branch_id": branch_id, "name": primary.name, "phone": primary.phone or "",
                    "primary_id": primary.id, "duplicates": rows,
                    "can_merge": all(not r["blocker"] for r in rows)})
    return out


def merge(primary_id: int, duplicate_ids: list[int]) -> dict[str, Any]:
    from models.agent_location import DeliveryAgentPosition, DeliveryAgentTrail
    from models.invoice import Invoice
    from utils.branch_distribution import snapshot

    ids = sorted({int(i) for i in duplicate_ids if int(i) != int(primary_id)})
    if not ids:
        raise BranchError("اختر سجلاً مكرراً واحداً على الأقل")
    primary = DeliveryAgent.query.execution_options(skip_branch_scope=True).get(int(primary_id))
    dups = DeliveryAgent.query.execution_options(skip_branch_scope=True).filter(DeliveryAgent.id.in_(ids)).all()
    if primary is None or len(dups) != len(ids):
        raise BranchError("مندوب غير موجود", "not_found", 404)
    for d in dups:
        if _key(d) != _key(primary):
            raise BranchError("السجلات ليست نسخاً مكررة لنفس المندوب بنفس الفرع", "conflict", 409)
        blocker = _payroll_blocker(primary, d)
        if blocker:
            raise BranchError(f"{d.name} (#{d.id}): {blocker}", "conflict", 409)

    backup = snapshot(SimpleNamespace(number="AGENT-MERGE"))
    moved = 0
    for d in dups:
        if d.username and not primary.username:
            login = (d.username, d.password)
            d.username = None  # the username is unique: free it before the primary takes it
            db.session.flush()
            primary.username, primary.password = login
        moved += (Invoice.query.execution_options(skip_branch_scope=True)
                  .filter_by(delivery_agent_id=d.id).update({"delivery_agent_id": primary.id}))
        DeliveryAgentTrail.query.filter_by(agent_id=d.id).update({"agent_id": primary.id})
        DeliveryAgentPosition.query.filter_by(agent_id=d.id).delete()
        primary.total_orders = int(primary.total_orders or 0) + int(d.total_orders or 0)
        primary.total_amount = int(primary.total_amount or 0) + int(d.total_amount or 0)
        d.is_active = False
        d.notes = (f"{d.notes or ''}\nدُمج في المندوب #{primary.id}").strip()
    db.session.commit()
    return {"primary_id": primary.id, "merged_ids": ids, "invoices_moved": int(moved), "backup": backup or "unavailable"}
