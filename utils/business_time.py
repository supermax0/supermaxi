"""Baghdad calendar boundaries over existing UTC timestamps; no data rewriting."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import and_, true
from utils.payment_ledger import BUSINESS_TZ_NAME, calendar_day_bounds_utc


def business_datetime(value):
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(ZoneInfo(BUSINESS_TZ_NAME))


def business_date(value):
    return business_datetime(value).date() if isinstance(value, datetime) else value


def business_today():
    return business_datetime(datetime.utcnow()).date()


def business_now():
    """Naive Baghdad wall clock for local calendar dates and scheduled times."""
    return business_datetime(datetime.utcnow()).replace(tzinfo=None)


def display_datetime(value):
    """Present UTC timestamps in Baghdad, with an explicit Arabic 12-hour clock."""
    if not value:
        return ""
    local = business_datetime(value)
    from utils.time_format import format_timestamp
    return format_timestamp(local, local=True)


def display_time(value):
    """Format an already-local wall clock without shifting its scheduled hour."""
    from utils.time_format import format_clock
    return format_clock(value)


def utc_period_filter(column, date_from=None, date_to=None):
    conditions = []
    if date_from is not None:
        conditions.append(column >= calendar_day_bounds_utc(date_from)[0])
    if date_to is not None:
        conditions.append(column < calendar_day_bounds_utc(date_to)[1])
    return and_(*conditions) if conditions else true()
