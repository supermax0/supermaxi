"""Group and edit recurring/scheduled expense series."""
from __future__ import annotations

import re
import uuid
from datetime import time

from extensions import db
from models.expense import Expense

REPEAT_NOTE_RE = re.compile(
    r"^(?P<base>.*?)\s*\|\s*تكرار\s+(?P<idx>\d+)\s*/\s*(?P<total>\d+)\s*$",
    re.UNICODE,
)


def new_series_id() -> str:
    return str(uuid.uuid4())


def parse_repeat_note(note: str | None) -> dict | None:
    text = (note or "").strip()
    match = REPEAT_NOTE_RE.match(text)
    if not match:
        return None
    return {
        "base": (match.group("base") or "").strip(),
        "index": int(match.group("idx")),
        "total": int(match.group("total")),
    }


def strip_repeat_suffix(note: str | None) -> str:
    parsed = parse_repeat_note(note)
    if parsed is not None:
        return parsed["base"]
    return (note or "").strip()


def build_repeat_note(base_note: str | None, index: int, total: int) -> str:
    base = (base_note or "").strip()
    suffix = f"تكرار {index}/{total}"
    return f"{base} | {suffix}" if base else f" | {suffix}"


def _legacy_series_members(expense: Expense) -> list[Expense]:
    parsed = parse_repeat_note(expense.note)
    if not parsed or parsed["total"] < 2:
        return [expense]

    total = parsed["total"]
    base = parsed["base"]
    title = expense.title
    category = expense.category
    amount = int(expense.amount or 0)

    candidates = (
        Expense.query.filter(
            Expense.title == title,
            Expense.category == category,
            Expense.amount == amount,
            Expense.note.isnot(None),
            Expense.note.like(f"%تكرار %/{total}%"),
        )
        .order_by(Expense.expense_date.asc(), Expense.id.asc())
        .all()
    )
    members = []
    for row in candidates:
        row_parsed = parse_repeat_note(row.note)
        if not row_parsed:
            continue
        if row_parsed["total"] != total:
            continue
        if row_parsed["base"] != base:
            continue
        if expense.branch_id and row.branch_id and int(row.branch_id) != int(expense.branch_id):
            continue
        members.append(row)
    return members or [expense]


def find_series_members(expense: Expense) -> list[Expense]:
    series_id = (getattr(expense, "repeat_series_id", None) or "").strip()
    if series_id:
        members = (
            Expense.query.filter(Expense.repeat_series_id == series_id)
            .order_by(Expense.expense_date.asc(), Expense.id.asc())
            .all()
        )
        if members:
            return members
    return _legacy_series_members(expense)


def ensure_series_id(members: list[Expense]) -> str | None:
    """Attach a shared series id to members that lack one (legacy rows)."""
    if len(members) < 2:
        existing = (getattr(members[0], "repeat_series_id", None) or "").strip() if members else ""
        return existing or None
    existing_ids = {
        (getattr(row, "repeat_series_id", None) or "").strip()
        for row in members
        if (getattr(row, "repeat_series_id", None) or "").strip()
    }
    series_id = next(iter(existing_ids)) if len(existing_ids) == 1 else new_series_id()
    for row in members:
        if (getattr(row, "repeat_series_id", None) or "").strip() != series_id:
            row.repeat_series_id = series_id
    return series_id


def series_edit_anchor_id(members: list[Expense]) -> int | None:
    """First scheduled row in the series — owns the edit button."""
    scheduled = [row for row in members if not bool(getattr(row, "cash_posted", True))]
    if not scheduled:
        return None
    if len(members) < 2 and not parse_repeat_note(scheduled[0].note):
        # Single non-series scheduled expense: still editable alone
        return int(scheduled[0].id)
    scheduled.sort(key=lambda row: (row.expense_date or row.created_at, row.id))
    return int(scheduled[0].id)


def serialize_expense_row(expense: Expense) -> dict:
    parsed = parse_repeat_note(expense.note)
    return {
        "id": int(expense.id),
        "title": expense.title,
        "category": expense.category,
        "amount": int(expense.amount or 0),
        "note": expense.note or "",
        "base_note": strip_repeat_suffix(expense.note),
        "expense_date": expense.expense_date.strftime("%Y-%m-%d") if expense.expense_date else None,
        "post_time": expense.post_time.strftime("%H:%M") if expense.post_time else "",
        "treasury_account_id": expense.treasury_account_id,
        "cash_posted": bool(expense.cash_posted),
        "repeat_index": parsed["index"] if parsed else None,
        "repeat_total": parsed["total"] if parsed else None,
        "repeat_series_id": getattr(expense, "repeat_series_id", None),
    }


def build_series_payload(expense: Expense) -> dict:
    members = find_series_members(expense)
    series_id = ensure_series_id(members)
    scheduled = [row for row in members if not bool(row.cash_posted)]
    posted = [row for row in members if bool(row.cash_posted)]
    anchor = series_edit_anchor_id(members)
    sample = scheduled[0] if scheduled else members[0]
    return {
        "series_id": series_id,
        "anchor_id": anchor,
        "can_edit": len(scheduled) > 0,
        "title": sample.title,
        "category": sample.category,
        "amount": int(sample.amount or 0),
        "base_note": strip_repeat_suffix(sample.note),
        "post_time": sample.post_time.strftime("%H:%M") if sample.post_time else "",
        "treasury_account_id": sample.treasury_account_id,
        "scheduled_count": len(scheduled),
        "posted_count": len(posted),
        "total_count": len(members),
        "members": [serialize_expense_row(row) for row in members],
        "scheduled_members": [serialize_expense_row(row) for row in scheduled],
    }


def _parse_post_time(raw) -> time | None:
    value = (raw or "").strip()
    if not value:
        return None
    from datetime import datetime

    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise ValueError("ساعة الصرف غير صالحة")


def update_scheduled_series(expense: Expense, payload: dict) -> dict:
    """Update shared fields on all unposted members of the series."""
    members = find_series_members(expense)
    ensure_series_id(members)
    scheduled = [row for row in members if not bool(row.cash_posted)]
    if not scheduled:
        raise ValueError("لا توجد مصاريف مجدولة قابلة للتعديل في هذه السلسلة")

    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("عنوان المصروف مطلوب")
    category = (payload.get("category") or "").strip()
    if not category:
        raise ValueError("فئة المصروف مطلوبة")
    try:
        amount = int(float(payload.get("amount")))
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        raise ValueError("مبلغ المصروف يجب أن يكون أكبر من صفر")

    from utils.treasury_helpers import resolve_treasury_account_id

    treasury_account_id = resolve_treasury_account_id(payload.get("treasury_account_id"))
    post_time = _parse_post_time(payload.get("post_time"))
    base_note = (payload.get("base_note") if "base_note" in payload else payload.get("note") or "")
    base_note = (base_note or "").strip()

    total = len(members)
    for row in scheduled:
        parsed = parse_repeat_note(row.note)
        index = parsed["index"] if parsed else 1
        row_total = parsed["total"] if parsed else total
        row.title = title
        row.category = category
        row.amount = amount
        row.treasury_account_id = treasury_account_id
        row.post_time = post_time
        if parsed or total > 1:
            row.note = build_repeat_note(base_note, index, row_total)
        else:
            row.note = base_note

    db.session.flush()
    return build_series_payload(expense)
