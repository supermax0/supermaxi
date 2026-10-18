"""Display formatting for the Facebook monitor."""
from __future__ import annotations

from datetime import datetime, timedelta


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    return f"{minutes:02d}:{secs:02d}"


def format_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def format_iqd(amount: int | float | None, *, compact: bool = False) -> str:
    value = int(amount or 0)
    if compact and abs(value) >= 1_000_000:
        millions = value / 1_000_000
        text = f"{millions:.1f}".rstrip("0").rstrip(".")
        return f"{text}M د.ع"
    return f"{value:,} د.ع"


def format_usd(amount: float | None) -> str:
    if amount is None:
        return "—"
    return f"${amount:,.2f}"


def format_ago(moment: datetime | None, now: datetime | None = None) -> str:
    """Short Arabic age for «آخر ظهور منذ …»."""
    if not moment:
        return ""
    now = now or datetime.utcnow()
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 60:
        return "أقل من دقيقة"
    minutes = seconds // 60
    if minutes < 60:
        if minutes == 1:
            return "دقيقة"
        if minutes == 2:
            return "دقيقتين"
        if minutes <= 10:
            return f"{minutes} دقائق"
        return f"{minutes} دقيقة"
    hours = minutes // 60
    if hours < 24:
        if hours == 1:
            return "ساعة"
        if hours == 2:
            return "ساعتين"
        if hours <= 10:
            return f"{hours} ساعات"
        return f"{hours} ساعة"
    days = hours // 24
    if days == 1:
        return "يوم"
    if days == 2:
        return "يومين"
    if days <= 10:
        return f"{days} أيام"
    return f"{days} يوم"


def format_relative(moment: datetime | None, now: datetime | None = None) -> str:
    if not moment:
        return "—"
    now = now or datetime.utcnow()
    delta = now - moment
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"قبل {seconds} ثانية"
    if seconds < 3600:
        return f"قبل {seconds // 60} دقيقة" if seconds >= 120 else "قبل دقيقة"
    if seconds < 86400:
        return moment.strftime("%I:%M %p")
    return moment.strftime("%Y-%m-%d %H:%M")


def parse_date_range(preset: str | None, date_from: str | None, date_to: str | None, now: datetime | None = None):
    # Business day for Iraq (UTC+3) so "today" matches local messages/orders.
    now = now or datetime.utcnow()
    local_now = now + timedelta(hours=3)
    today = local_now.date()
    key = (preset or "last_30").strip() or "last_30"
    if key == "yesterday":
        start_day = today - timedelta(days=1)
        end_day = today
    elif key == "today":
        start_day = today
        end_day = today + timedelta(days=1)
    elif key == "last_7":
        start_day = today - timedelta(days=6)
        end_day = today + timedelta(days=1)
    elif key == "last_30":
        start_day = today - timedelta(days=29)
        end_day = today + timedelta(days=1)
    elif key == "this_month":
        start_day = today.replace(day=1)
        end_day = today + timedelta(days=1)
    elif key in {"all", "all_time"}:
        key = "all"
        start_day = today - timedelta(days=364)
        end_day = today + timedelta(days=1)
    elif key == "custom":
        start_day = _parse_day(date_from) or today
        end_day = (_parse_day(date_to) or today) + timedelta(days=1)
        if end_day <= start_day:
            end_day = start_day + timedelta(days=1)
    else:
        key = "last_30"
        start_day = today - timedelta(days=29)
        end_day = today + timedelta(days=1)
    # Convert Iraq local day bounds back to UTC naive datetimes used elsewhere.
    start = datetime.combine(start_day, datetime.min.time()) - timedelta(hours=3)
    end = datetime.combine(end_day, datetime.min.time()) - timedelta(hours=3)
    return key, start, end


def _parse_day(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
