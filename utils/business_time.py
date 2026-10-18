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


def utc_period_filter(column, date_from=None, date_to=None):
    conditions = []
    if date_from is not None:
        conditions.append(column >= calendar_day_bounds_utc(date_from)[0])
    if date_to is not None:
        conditions.append(column < calendar_day_bounds_utc(date_to)[1])
    return and_(*conditions) if conditions else true()
