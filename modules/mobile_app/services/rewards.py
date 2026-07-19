"""Points ledger, tiers, and purchase/welcome rewards (Phase 6)."""
from __future__ import annotations

import logging
from datetime import datetime

from extensions import db
from models.invoice import Invoice
from modules.mobile_app.models import (
    MobileCampaign,
    MobileOrderAttribution,
    MobileRewardAccount,
    MobileRewardRedemption,
    MobileRewardRule,
    MobileRewardTier,
    MobileRewardTransaction,
)

logger = logging.getLogger(__name__)


class RewardError(Exception):
    def __init__(self, message: str, code: str = "reward_error"):
        super().__init__(message)
        self.message = message
        self.code = code


DEFAULT_TIERS = (
    ("silver", "Silver", 0, 0),
    ("gold", "Gold", 1000, 1),
    ("vip", "VIP", 5000, 2),
)

DEFAULT_RULES = (
    {
        "key": "welcome_bonus",
        "name": "مكافأة الترحيب",
        "rule_type": "welcome_bonus",
        "points": 50,
        "amount_per_point": 0,
        "multiplier": 1.0,
    },
    {
        "key": "purchase_reward",
        "name": "نقاط الشراء",
        "rule_type": "purchase_reward",
        "points": 1,
        "amount_per_point": 1000,
        "multiplier": 1.0,
        "confirm_statuses": "مكتمل,مسدد,تم التوصيل",
    },
    {
        "key": "first_order_bonus",
        "name": "مكافأة أول طلب",
        "rule_type": "first_order_bonus",
        "points": 100,
        "amount_per_point": 0,
        "multiplier": 1.0,
        "confirm_statuses": "مكتمل,مسدد,تم التوصيل",
    },
    {
        "key": "points_redemption_rate",
        "name": "سعر استبدال النقاط",
        "rule_type": "points_redemption_rate",
        "points": 100,  # points required
        "amount_per_point": 1000,  # IQD discount per `points` block
        "multiplier": 1.0,
    },
)


def ensure_reward_defaults() -> None:
    for key, name, minimum, order in DEFAULT_TIERS:
        if not MobileRewardTier.query.filter_by(key=key).first():
            db.session.add(
                MobileRewardTier(
                    key=key,
                    name=name,
                    min_lifetime_points=minimum,
                    sort_order=order,
                    is_active=True,
                )
            )
    for rule in DEFAULT_RULES:
        if not MobileRewardRule.query.filter_by(key=rule["key"]).first():
            db.session.add(
                MobileRewardRule(
                    key=rule["key"],
                    name=rule["name"],
                    rule_type=rule["rule_type"],
                    points=int(rule.get("points") or 0),
                    amount_per_point=int(rule.get("amount_per_point") or 0),
                    multiplier=float(rule.get("multiplier") or 1.0),
                    confirm_statuses=rule.get("confirm_statuses")
                    or "مكتمل,مسدد,تم التوصيل",
                    is_active=True,
                )
            )
    db.session.commit()


def _get_or_create_account(user_id: int) -> MobileRewardAccount:
    account = MobileRewardAccount.query.filter_by(user_id=user_id).first()
    if account:
        return account
    account = MobileRewardAccount(user_id=user_id, balance=0, tier_key="silver")
    db.session.add(account)
    db.session.flush()
    return account


def _recompute_balance(user_id: int) -> MobileRewardAccount:
    account = _get_or_create_account(user_id)
    txs = MobileRewardTransaction.query.filter_by(user_id=user_id, status="confirmed").all()
    balance = 0
    earned = 0
    redeemed = 0
    for tx in txs:
        pts = int(tx.points or 0)
        if tx.direction == "credit":
            balance += pts
            earned += pts
        else:
            balance -= pts
            redeemed += pts
    account.balance = max(0, balance)
    account.lifetime_earned = earned
    account.lifetime_redeemed = redeemed
    account.tier_key = resolve_tier_key(earned)
    account.updated_at = datetime.utcnow()
    return account


def resolve_tier_key(lifetime_earned: int) -> str:
    tiers = (
        MobileRewardTier.query.filter_by(is_active=True)
        .order_by(MobileRewardTier.min_lifetime_points.desc())
        .all()
    )
    for tier in tiers:
        if lifetime_earned >= int(tier.min_lifetime_points or 0):
            return tier.key
    return "silver"


def get_rule(rule_type: str) -> MobileRewardRule | None:
    return (
        MobileRewardRule.query.filter_by(rule_type=rule_type, is_active=True)
        .order_by(MobileRewardRule.id.asc())
        .first()
    )


def active_campaign_multiplier() -> float:
    now = datetime.utcnow()
    campaigns = MobileCampaign.query.filter_by(is_active=True).all()
    best = 1.0
    for c in campaigns:
        if c.starts_at and c.starts_at > now:
            continue
        if c.ends_at and c.ends_at < now:
            continue
        best = max(best, float(c.bonus_multiplier or 1.0))
    return best


def ledger_credit(
    *,
    user_id: int,
    points: int,
    tx_type: str,
    description: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
    status: str = "confirmed",
    expires_at: datetime | None = None,
    created_by: int | None = None,
) -> MobileRewardTransaction:
    if points <= 0:
        raise RewardError("النقاط يجب أن تكون موجبة", "invalid_points")
    tx = MobileRewardTransaction(
        user_id=user_id,
        type=tx_type,
        points=int(points),
        direction="credit",
        status=status,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        expires_at=expires_at,
        created_by=created_by,
    )
    db.session.add(tx)
    db.session.flush()
    if status == "confirmed":
        _recompute_balance(user_id)
    return tx


def ledger_debit(
    *,
    user_id: int,
    points: int,
    tx_type: str,
    description: str,
    reference_type: str | None = None,
    reference_id: int | None = None,
    status: str = "confirmed",
    created_by: int | None = None,
) -> MobileRewardTransaction:
    if points <= 0:
        raise RewardError("النقاط يجب أن تكون موجبة", "invalid_points")
    account = _recompute_balance(user_id)
    if status == "confirmed" and account.balance < points:
        raise RewardError("رصيد النقاط غير كافٍ", "insufficient_points")
    tx = MobileRewardTransaction(
        user_id=user_id,
        type=tx_type,
        points=int(points),
        direction="debit",
        status=status,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        created_by=created_by,
    )
    db.session.add(tx)
    db.session.flush()
    if status == "confirmed":
        _recompute_balance(user_id)
    return tx


def grant_welcome_bonus(user_id: int) -> dict | None:
    rule = get_rule("welcome_bonus")
    if not rule or not rule.is_active:
        return None
    existing = MobileRewardTransaction.query.filter_by(
        user_id=user_id, type="welcome_bonus"
    ).first()
    if existing:
        return None
    tx = ledger_credit(
        user_id=user_id,
        points=int(rule.points or 0),
        tx_type="welcome_bonus",
        description=rule.name,
        status="confirmed",
    )
    db.session.commit()
    return {"transaction_id": tx.id, "points": tx.points}


def queue_purchase_rewards(*, user_id: int, invoice: Invoice, subtotal: int) -> None:
    """Create pending purchase (+ optional first-order) rewards; confirm later."""
    purchase_rule = get_rule("purchase_reward")
    mult = active_campaign_multiplier()
    if purchase_rule and purchase_rule.is_active and subtotal > 0:
        amount_per = max(1, int(purchase_rule.amount_per_point or 1000))
        base = (int(subtotal) // amount_per) * int(purchase_rule.points or 1)
        points = int(base * float(purchase_rule.multiplier or 1.0) * mult)
        if points > 0:
            existing = MobileRewardTransaction.query.filter_by(
                user_id=user_id,
                type="purchase_reward",
                reference_type="invoice",
                reference_id=invoice.id,
            ).first()
            if not existing:
                ledger_credit(
                    user_id=user_id,
                    points=points,
                    tx_type="purchase_reward",
                    description=f"نقاط شراء للطلب #{invoice.id}",
                    reference_type="invoice",
                    reference_id=invoice.id,
                    status="pending",
                )

    first_rule = get_rule("first_order_bonus")
    if first_rule and first_rule.is_active:
        prior = MobileRewardTransaction.query.filter_by(
            user_id=user_id, type="first_order_bonus"
        ).first()
        if not prior:
            ledger_credit(
                user_id=user_id,
                points=int(first_rule.points or 0),
                tx_type="first_order_bonus",
                description=f"مكافأة أول طلب #{invoice.id}",
                reference_type="invoice",
                reference_id=invoice.id,
                status="pending",
            )
    db.session.commit()


def _status_matches(invoice: Invoice, confirm_statuses: str) -> bool:
    status = str(invoice.status or "").strip()
    payment = str(invoice.payment_status or "").strip()
    tokens = [t.strip() for t in (confirm_statuses or "").split(",") if t.strip()]
    for token in tokens:
        if status == token or payment == token:
            return True
        # Allow contained match only for multi-word statuses like "تم التوصيل"
        if " " in token and (token in status or token in payment):
            return True
    return False


def sync_pending_rewards_for_user(user_id: int) -> int:
    """Confirm or cancel pending purchase rewards based on invoice status."""
    pending = MobileRewardTransaction.query.filter_by(
        user_id=user_id, status="pending"
    ).all()
    confirmed = 0
    for tx in pending:
        if tx.reference_type != "invoice" or not tx.reference_id:
            continue
        invoice = db.session.get(Invoice, tx.reference_id)
        if invoice is None:
            tx.status = "cancelled"
            continue
        status = str(invoice.status or "")
        if any(w in status for w in ("ملغي", "إلغاء", "مرتجع")):
            tx.status = "cancelled"
            continue
        rule = get_rule(tx.type) or get_rule("purchase_reward")
        confirm = (rule.confirm_statuses if rule else None) or "مكتمل,مسدد,تم التوصيل"
        if _status_matches(invoice, confirm):
            tx.status = "confirmed"
            confirmed += 1
    if pending:
        _recompute_balance(user_id)
        db.session.commit()
    return confirmed


def cancel_rewards_for_invoice(invoice_id: int) -> None:
    rows = MobileRewardTransaction.query.filter_by(
        reference_type="invoice", reference_id=invoice_id, status="pending"
    ).all()
    for tx in rows:
        tx.status = "cancelled"
    if rows:
        user_ids = {tx.user_id for tx in rows}
        for uid in user_ids:
            _recompute_balance(uid)
        db.session.commit()


def points_to_discount(points: int) -> int:
    rule = get_rule("points_redemption_rate")
    if not rule or points <= 0:
        return 0
    block = max(1, int(rule.points or 100))
    value = max(0, int(rule.amount_per_point or 0))
    return (int(points) // block) * value


def discount_to_points(discount_amount: int) -> int:
    rule = get_rule("points_redemption_rate")
    if not rule or discount_amount <= 0:
        return 0
    block = max(1, int(rule.points or 100))
    value = max(1, int(rule.amount_per_point or 1))
    blocks = int(discount_amount) // value
    return blocks * block


def available_redemptions(user_id: int) -> list[dict]:
    account = get_rewards_summary(user_id)
    balance = int(account["balance"])
    rule = get_rule("points_redemption_rate")
    if not rule:
        return []
    block = max(1, int(rule.points or 100))
    value = max(0, int(rule.amount_per_point or 0))
    options = []
    for n in (1, 2, 5, 10):
        pts = block * n
        if pts <= balance:
            options.append(
                {
                    "points": pts,
                    "discount_amount": value * n,
                    "label": f"{pts} نقطة = {value * n} د.ع",
                }
            )
    return options


def redeem_points_for_checkout(
    *,
    user_id: int,
    points: int,
    invoice_id: int,
    discount_amount: int,
) -> MobileRewardRedemption:
    tx = ledger_debit(
        user_id=user_id,
        points=points,
        tx_type="redemption",
        description=f"استبدال نقاط للطلب #{invoice_id}",
        reference_type="invoice",
        reference_id=invoice_id,
        status="confirmed",
    )
    row = MobileRewardRedemption(
        user_id=user_id,
        points_spent=points,
        discount_amount=discount_amount,
        invoice_id=invoice_id,
        transaction_id=tx.id,
        status="applied",
    )
    db.session.add(row)
    db.session.commit()
    return row


def get_rewards_summary(user_id: int) -> dict:
    sync_pending_rewards_for_user(user_id)
    account = _recompute_balance(user_id)
    db.session.commit()
    tier = MobileRewardTier.query.filter_by(key=account.tier_key).first()
    pending = (
        db.session.query(db.func.coalesce(db.func.sum(MobileRewardTransaction.points), 0))
        .filter_by(user_id=user_id, status="pending", direction="credit")
        .scalar()
    )
    return {
        "balance": int(account.balance or 0),
        "pending_points": int(pending or 0),
        "lifetime_earned": int(account.lifetime_earned or 0),
        "lifetime_redeemed": int(account.lifetime_redeemed or 0),
        "tier": {
            "key": account.tier_key,
            "name": tier.name if tier else account.tier_key,
        },
    }


def history(user_id: int, *, limit: int = 50) -> list[dict]:
    sync_pending_rewards_for_user(user_id)
    rows = (
        MobileRewardTransaction.query.filter_by(user_id=user_id)
        .order_by(MobileRewardTransaction.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "type": r.type,
            "points": r.points,
            "direction": r.direction,
            "status": r.status,
            "description": r.description,
            "reference_type": r.reference_type,
            "reference_id": r.reference_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def list_rules() -> list[dict]:
    rows = MobileRewardRule.query.filter_by(is_active=True).all()
    return [
        {
            "key": r.key,
            "name": r.name,
            "rule_type": r.rule_type,
            "points": r.points,
            "amount_per_point": r.amount_per_point,
            "multiplier": r.multiplier,
            "confirm_statuses": r.confirm_statuses,
        }
        for r in rows
    ]


def list_tiers() -> list[dict]:
    rows = (
        MobileRewardTier.query.filter_by(is_active=True)
        .order_by(MobileRewardTier.sort_order.asc())
        .all()
    )
    return [
        {
            "key": t.key,
            "name": t.name,
            "min_lifetime_points": t.min_lifetime_points,
        }
        for t in rows
    ]


def adjust_points(
    *,
    user_id: int,
    points: int,
    direction: str,
    description: str,
    staff_id: int | None = None,
) -> dict:
    if direction == "credit":
        tx = ledger_credit(
            user_id=user_id,
            points=abs(points),
            tx_type="manual_adjustment",
            description=description or "تعديل يدوي",
            created_by=staff_id,
            status="confirmed",
        )
    else:
        tx = ledger_debit(
            user_id=user_id,
            points=abs(points),
            tx_type="manual_adjustment",
            description=description or "تعديل يدوي",
            created_by=staff_id,
            status="confirmed",
        )
    db.session.commit()
    return {"transaction_id": tx.id, "summary": get_rewards_summary(user_id)}
