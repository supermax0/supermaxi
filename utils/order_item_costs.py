"""Helpers for stock-product cost calculations."""

from sqlalchemy import and_, func, not_, or_


def exclude_delivery_fee_items(item_model):
    """Return a SQLAlchemy filter that keeps stock items and excludes delivery-fee rows."""
    name = func.coalesce(item_model.product_name, "")
    return not_(
        and_(
            func.coalesce(item_model.total, 0) == 0,
            func.coalesce(item_model.price, 0) == 0,
            or_(
                name.like("%شحن%"),
                name.like("%توصيل%"),
                name.like("%نقل%"),
            ),
        )
    )
