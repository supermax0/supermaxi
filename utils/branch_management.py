"""Branch management service (multi-branch spec, sprints 1–2).

Everything here is additive and side-effect free for the books: creating a branch creates the branch, one
empty cash account and a profile row — no movements, no balances. Turning the feature on only writes a UI
flag; it never touches data.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, text

from extensions import db
from models.branch import Branch
from models.branch_profile import BRANCH_TYPES, BranchProfile

MULTI_BRANCH_FLAG = "multi_branch_enabled"


class BranchError(ValueError):
    """User-facing validation / policy error."""

    def __init__(self, message: str, code: str = "validation", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


# ───────────────────────────── feature flag ─────────────────────────────


def _settings():
    from models.system_settings import SystemSettings

    return SystemSettings.get_settings()


def multi_branch_state() -> dict[str, Any]:
    """Explicit flag wins; otherwise a company that already has more than one active branch counts as enabled
    (so nothing that exists today is hidden from it), and a single-branch company stays in the simple mode."""
    flags = _settings().get_ui_flags()
    active = int(Branch.query.filter_by(is_active=True).count())
    explicit = flags.get(MULTI_BRANCH_FLAG)
    enabled = bool(explicit) if explicit is not None else active > 1
    return {"enabled": enabled, "explicit": explicit is not None, "active_branches": active}


def operating_branch_must_be_explicit() -> bool:
    """«All branches» is a VIEW scope. With more than one active branch a sale must name its branch — silently
    booking an administrator's sale on the company default branch would put revenue and stock on the wrong one."""
    try:
        return int(Branch.query.filter_by(is_active=True).count()) > 1
    except Exception:
        return False


def set_multi_branch(enabled: bool) -> dict[str, Any]:
    state = multi_branch_state()
    if not enabled and state["active_branches"] > 1:
        raise BranchError("أرشف الفروع الإضافية أولاً — لا يمكن إيقاف تعدد الفروع وفيه أكثر من فرع فعّال",
                          "conflict", 409)
    settings = _settings()
    flags = settings.get_ui_flags()
    flags[MULTI_BRANCH_FLAG] = bool(enabled)
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.add(settings)
    db.session.commit()
    return multi_branch_state()


def primary_branch() -> Branch | None:
    """The company's primary branch: the default one, else the oldest active — never None for a live company."""
    return (Branch.query.filter_by(is_default=True, is_active=True).first()
            or Branch.query.filter_by(is_active=True).order_by(Branch.id).first())


# ───────────────────────────── profile ─────────────────────────────


def ensure_profile_table() -> None:
    BranchProfile.__table__.create(bind=db.session.connection(), checkfirst=True)


def get_profile(branch: Branch) -> BranchProfile:
    ensure_profile_table()
    profile = db.session.get(BranchProfile, branch.id)
    if profile is None:
        profile = BranchProfile(branch_id=branch.id, branch_type="sales")
        db.session.add(profile)
        db.session.flush()
    return profile


def _clean(value: Any, limit: int) -> str | None:
    text_value = str(value or "").strip()
    return text_value[:limit] or None


def _apply_profile(profile: BranchProfile, data: dict[str, Any]) -> None:
    if "branch_type" in data:
        kind = str(data["branch_type"] or "sales")
        if kind not in BRANCH_TYPES:
            raise BranchError("نوع الفرع غير معروف")
        profile.branch_type = kind
    for field, limit in (("short_name", 60), ("governorate", 80), ("city", 80), ("email", 120),
                         ("manager_name", 120), ("currency", 10), ("timezone", 60)):
        if field in data:
            setattr(profile, field, _clean(data[field], limit))
    for field in ("latitude", "longitude"):
        if field in data:
            raw = data[field]
            try:
                profile.__setattr__(field, float(raw) if raw not in (None, "") else None)
            except (TypeError, ValueError):
                raise BranchError("الإحداثيات غير صالحة") from None
    if data.get("latitude") not in (None, "") and not -90 <= float(data["latitude"]) <= 90:
        raise BranchError("خط العرض يجب أن يكون بين -90 و90")
    if data.get("longitude") not in (None, "") and not -180 <= float(data["longitude"]) <= 180:
        raise BranchError("خط الطول يجب أن يكون بين -180 و180")
    if "opened_on" in data:
        raw = data["opened_on"]
        if raw in (None, ""):
            profile.opened_on = None
        else:
            try:
                profile.opened_on = date.fromisoformat(str(raw)[:10])
            except ValueError:
                raise BranchError("تاريخ بدء التشغيل غير صالح") from None
    for field in ("manager_employee_id", "default_warehouse_id", "default_cash_account_id"):
        if field in data:
            raw = data[field]
            setattr(profile, field, int(raw) if str(raw or "").isdigit() else None)
    for field in ("print_settings", "numbering_settings"):
        if field in data:
            value = data[field]
            if value in (None, ""):
                setattr(profile, field, None)
            elif isinstance(value, dict):
                setattr(profile, field, json.dumps(value, ensure_ascii=False))
            else:
                raise BranchError("الإعدادات يجب أن تكون كائناً")


# ───────────────────────────── create / update / archive ─────────────────────────────


def _validate_code_name(code: str, name: str, *, exclude_id: int | None = None) -> None:
    if not code or not name:
        raise BranchError("الكود والاسم مطلوبان")
    query = Branch.query.filter(func.upper(Branch.code) == code.upper())
    if exclude_id:
        query = query.filter(Branch.id != exclude_id)
    if query.first():
        raise BranchError("كود الفرع مستخدم", "conflict", 409)


def create_branch(data: dict[str, Any], *, actor_id: int | None = None) -> Branch:
    """New branch: branch row + ONE empty cash account + profile. No movements, no balances, no stock."""
    code = str(data.get("code") or "").strip().upper()[:60]
    name = str(data.get("name") or "").strip()[:150]
    _validate_code_name(code, name)
    is_default = bool(data.get("is_default", False))
    if is_default:
        for other in Branch.query.all():
            other.is_default = False
    branch = Branch(code=code, name=name, address=_clean(data.get("address"), 255),
                    phone=_clean(data.get("phone"), 60), is_active=bool(data.get("is_active", True)),
                    is_default=is_default)
    db.session.add(branch)
    db.session.flush()

    from models.treasury_account import TreasuryAccount
    from utils.treasury_helpers import sync_bank_accounts_across_branches

    cash = TreasuryAccount(branch_id=branch.id, name=f"صندوق {branch.name}", account_type="cash",
                           is_default=True, is_active=True)
    db.session.add(cash)
    db.session.flush()
    sync_bank_accounts_across_branches()  # card / bank definitions only — balances stay per branch
    profile = get_profile(branch)
    profile.created_by_id = actor_id
    profile.default_cash_account_id = cash.id
    _apply_profile(profile, data)
    return branch


def update_branch(branch: Branch, data: dict[str, Any]) -> Branch:
    if "code" in data or "name" in data:
        code = str(data.get("code", branch.code) or "").strip().upper()[:60]
        name = str(data.get("name", branch.name) or "").strip()[:150]
        _validate_code_name(code, name, exclude_id=branch.id)
        branch.code, branch.name = code, name
    if "address" in data:
        branch.address = _clean(data["address"], 255)
    if "phone" in data:
        branch.phone = _clean(data["phone"], 60)
    if data.get("is_default") and not branch.is_default:
        if not branch.is_active:
            raise BranchError("لا يمكن جعل فرع مؤرشف هو الأساسي")
        for other in Branch.query.all():
            other.is_default = False
        branch.is_default = True
    _apply_profile(get_profile(branch), data)
    return branch


def archive_branch(branch: Branch, *, actor_id: int | None, reason: str = "") -> Branch:
    if branch.is_default:
        raise BranchError("لا يمكن أرشفة الفرع الأساسي — اجعل فرعاً آخر أساسياً أولاً", "conflict", 409)
    if not branch.is_active:
        return branch
    blockers = branch_blockers(branch.id)
    if blockers:
        raise BranchError("لا يمكن أرشفة الفرع: " + "، ".join(blockers), "conflict", 409)
    branch.is_active = False
    profile = get_profile(branch)
    profile.archived_at, profile.archived_by_id = datetime.utcnow(), actor_id
    profile.archive_reason = _clean(reason, 255)
    return branch


def restore_branch(branch: Branch) -> Branch:
    branch.is_active = True
    profile = get_profile(branch)
    profile.archived_at = profile.archived_by_id = profile.archive_reason = None
    return branch


def branch_blockers(branch_id: int) -> list[str]:
    """What still lives in the branch and would be orphaned by archiving it."""
    from models.branch import BranchStock, StockTransfer
    from models.invoice import Invoice

    out: list[str] = []
    stock = (db.session.query(func.coalesce(func.sum(BranchStock.quantity), 0))
             .filter(BranchStock.branch_id == branch_id).scalar() or 0)
    if int(stock) > 0:
        out.append(f"فيه مخزون ({int(stock)} قطعة) — حوّله أولاً")
    open_orders = (Invoice.query.execution_options(skip_branch_scope=True)
                   .filter(Invoice.branch_id == branch_id, Invoice.status.in_(("تم الطلب", "معباة", "جاري الشحن")))
                   .count())
    if open_orders:
        out.append(f"{open_orders} طلب مفتوح")
    pending = StockTransfer.query.filter(
        db.or_(StockTransfer.from_branch_id == branch_id, StockTransfer.to_branch_id == branch_id),
        StockTransfer.status.in_(("draft", "approved", "sent"))).count()
    if pending:
        out.append(f"{pending} تحويل مخزني معلق")
    return out


# ───────────────────────────── serialization ─────────────────────────────


def serialize(branch: Branch, *, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = get_profile(branch)

    def loads(raw: str | None) -> dict:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    return {
        **branch.to_dict(),
        "short_name": profile.short_name or "", "branch_type": profile.branch_type or "sales",
        "branch_type_label": BRANCH_TYPES.get(profile.branch_type or "sales", ""),
        "governorate": profile.governorate or "", "city": profile.city or "",
        "latitude": profile.latitude, "longitude": profile.longitude, "email": profile.email or "",
        "manager_name": profile.manager_name or "", "manager_employee_id": profile.manager_employee_id,
        "currency": profile.currency or "", "timezone": profile.timezone or "",
        "default_warehouse_id": profile.default_warehouse_id,
        "default_cash_account_id": profile.default_cash_account_id,
        "opened_on": profile.opened_on.isoformat() if profile.opened_on else "",
        "print_settings": loads(profile.print_settings), "numbering_settings": loads(profile.numbering_settings),
        "archived_at": profile.archived_at.strftime("%Y-%m-%d %H:%M") if profile.archived_at else "",
        "archive_reason": profile.archive_reason or "",
        "created_at": branch.created_at.strftime("%Y-%m-%d %H:%M") if branch.created_at else "",
        "stats": stats,
    }


def pending_transfers(branch_ids: list[int] | None = None) -> dict[str, int]:
    """Open transfers that still need a human: stock documents not yet settled and cash documents not posted.
    ``branch_ids`` None = the whole company; otherwise those touching one of the branches."""
    from models.branch import StockTransfer
    from models.branch_cash_transfer import BranchCashTransfer

    stock = StockTransfer.query.filter(StockTransfer.status.in_(("draft", "approved", "sent", "partially_received")))
    cash = BranchCashTransfer.query.filter(BranchCashTransfer.status.in_(("pending", "approved", "posting")))
    if branch_ids is not None:
        stock = stock.filter(db.or_(StockTransfer.from_branch_id.in_(branch_ids),
                                    StockTransfer.to_branch_id.in_(branch_ids)))
        cash = cash.filter(db.or_(BranchCashTransfer.from_branch_id.in_(branch_ids),
                                  BranchCashTransfer.to_branch_id.in_(branch_ids)))
    ensure = BranchCashTransfer.__table__.create(bind=db.session.connection(), checkfirst=True)  # noqa: F841
    return {"stock": int(stock.count()),
            "cash": int(cash.count()),
            "cash_amount": int(cash.with_entities(func.coalesce(func.sum(BranchCashTransfer.amount), 0)).scalar() or 0)}


@contextmanager
def all_branches_view():
    """Admin-only: lift the per-branch ORM scope for read-only aggregation (what the reports engine does)."""
    from flask import g, has_request_context, session

    if not has_request_context() or session.get("role") != "admin":
        yield
        return
    previous = getattr(g, "view_all_branches", False)
    g.view_all_branches = True
    try:
        yield
    finally:
        g.view_all_branches = previous


def branch_stats(branch_id: int) -> dict[str, Any]:
    """Live figures from the books' own sources. Nothing is estimated: a figure we cannot compute is None."""
    from models.inventory_lot import InventoryLot
    from models.invoice import Invoice
    from models.treasury_account import TreasuryAccount
    from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
    from utils.treasury_calculations import calculate_treasury_balance

    dead = list(CANCELED_STATUSES | RETURN_STATUSES)
    base = Invoice.query.execution_options(skip_branch_scope=True).filter(Invoice.branch_id == branch_id)
    sales_total, orders = base.filter(Invoice.status.notin_(dead)).with_entities(
        func.coalesce(func.sum(Invoice.total), 0), func.count(Invoice.id)).one()
    open_orders = base.filter(Invoice.status.in_(("تم الطلب", "معباة", "جاري الشحن"))).count()
    last = base.with_entities(func.max(Invoice.created_at)).scalar()
    stock_value = (db.session.query(func.coalesce(func.sum(InventoryLot.remaining_quantity * InventoryLot.unit_cost), 0))
                   .filter(InventoryLot.branch_id == branch_id).scalar() or 0)
    from utils.inventory_transfer_valuation import in_transit_by_sender

    with all_branches_view():
        in_transit = int(in_transit_by_sender([branch_id]).get(branch_id, 0))
    cash: int | None = 0
    accounts = (TreasuryAccount.query.execution_options(skip_branch_scope=True)
                .filter(TreasuryAccount.branch_id == branch_id, TreasuryAccount.is_active.is_(True)).all())
    with all_branches_view():
        for account in accounts:
            try:
                cash += int(calculate_treasury_balance(account.id) or 0)
            except Exception:
                cash = None  # never present a partial balance as the real one
                break
    return {"sales_total": int(sales_total or 0), "orders": int(orders or 0), "open_orders": open_orders,
            "stock_value": int(stock_value), "in_transit_value": in_transit, "cash": cash,
            "last_activity": last.strftime("%Y-%m-%d %H:%M") if last else ""}
