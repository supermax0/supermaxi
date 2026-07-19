"""Ensure mobile_app tables and default feature flags exist on the tenant DB."""
from __future__ import annotations

import threading

from flask import current_app, has_app_context
from sqlalchemy import inspect, or_, text

from extensions import db
from models.product import Product, catalog_category_from_meta
from modules.mobile_app.models import (
    MobileAIConversation,
    MobileAIMessage,
    MobileAIToolExecution,
    MobileAnalyticsEvent,
    MobileAppDesign,
    MobileBlockedUser,
    MobileCampaign,
    MobileCart,
    MobileCartItem,
    MobileComment,
    MobileCommentLike,
    MobileCommentReport,
    MobileCoupon,
    MobileCouponRedemption,
    MobileDiscount,
    MobileFavorite,
    MobileFeatureFlag,
    MobileFeedEvent,
    MobileModerationRule,
    MobileNotification,
    MobileNotificationDelivery,
    MobileNotificationPreference,
    MobileOrderAttribution,
    MobileOtpRequest,
    MobileRewardAccount,
    MobileRewardRedemption,
    MobileRewardRule,
    MobileRewardTier,
    MobileRewardTransaction,
    MobileUser,
    MobileUserAddress,
    MobileUserDevice,
    MobileUserSession,
    MobileVideo,
    MobileVideoAsset,
    MobileVideoLike,
    MobileVideoProduct,
    MobileVideoSave,
    MobileVideoShare,
    MobileVideoView,
)
from modules.mobile_app.permissions import DEFAULT_FEATURE_FLAGS, MOBILE_APP_PERMISSIONS

TABLES = (
    Product.__table__,
    MobileUser.__table__,
    MobileUserDevice.__table__,
    MobileUserSession.__table__,
    MobileOtpRequest.__table__,
    MobileFeatureFlag.__table__,
    MobileVideo.__table__,
    MobileVideoAsset.__table__,
    MobileVideoProduct.__table__,
    MobileVideoView.__table__,
    MobileVideoLike.__table__,
    MobileVideoSave.__table__,
    MobileVideoShare.__table__,
    MobileFeedEvent.__table__,
    MobileComment.__table__,
    MobileCommentLike.__table__,
    MobileCommentReport.__table__,
    MobileBlockedUser.__table__,
    MobileModerationRule.__table__,
    MobileFavorite.__table__,
    MobileCart.__table__,
    MobileCartItem.__table__,
    MobileOrderAttribution.__table__,
    MobileRewardAccount.__table__,
    MobileRewardTransaction.__table__,
    MobileRewardRule.__table__,
    MobileRewardTier.__table__,
    MobileRewardRedemption.__table__,
    MobileCampaign.__table__,
    MobileDiscount.__table__,
    MobileCoupon.__table__,
    MobileCouponRedemption.__table__,
    MobileAIConversation.__table__,
    MobileAIMessage.__table__,
    MobileAIToolExecution.__table__,
    MobileNotification.__table__,
    MobileNotificationDelivery.__table__,
    MobileNotificationPreference.__table__,
    MobileAnalyticsEvent.__table__,
    MobileAppDesign.__table__,
    MobileUserAddress.__table__,
)

_schema_lock = threading.RLock()
_ensured_bindings: set[str] = set()


def _ensure_columns() -> None:
    bind = db.session.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    alters: list[tuple[str, str, str]] = []
    if "mobile_cart" in tables:
        cols = {c["name"] for c in inspector.get_columns("mobile_cart")}
        if "points_to_redeem" not in cols:
            alters.append(("mobile_cart", "points_to_redeem", "INTEGER NOT NULL DEFAULT 0"))
    if "mobile_order_attribution" in tables:
        cols = {c["name"] for c in inspector.get_columns("mobile_order_attribution")}
        if "campaign_id" not in cols:
            alters.append(("mobile_order_attribution", "campaign_id", "INTEGER"))
        if "coupon_id" not in cols:
            alters.append(("mobile_order_attribution", "coupon_id", "INTEGER"))
    if "product" in tables:
        cols = {c["name"] for c in inspector.get_columns("product")}
        if "catalog_category" not in cols:
            alters.append(("product", "catalog_category", "VARCHAR(120)"))
    for table, col, ddl in alters:
        db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
    if alters:
        db.session.commit()


def _backfill_product_categories() -> None:
    rows = (
        Product.query.filter(
            Product.meta_json.isnot(None),
            or_(
                Product.catalog_category.is_(None),
                Product.catalog_category == "",
            ),
        )
        .yield_per(500)
    )
    changed = False
    for product in rows:
        category = catalog_category_from_meta(product.meta_json)
        if category:
            product.catalog_category = category
            changed = True
    if changed:
        db.session.commit()


def _seed_reward_defaults() -> None:
    from modules.mobile_app.services.rewards import ensure_reward_defaults

    ensure_reward_defaults()


def _seed_permissions() -> None:
    try:
        from models.role import Permission
    except Exception:
        return
    existing = {row.name for row in db.session.query(Permission.name).all()}
    added = False
    for name, description in MOBILE_APP_PERMISSIONS:
        if name in existing:
            continue
        # permissions.name is String(50)
        db.session.add(
            Permission(name=name[:50], description=(description or "")[:200])
        )
        added = True
    if added:
        db.session.commit()


def ensure_mobile_app_schema() -> None:
    bind = db.session.get_bind()
    cache_key = str(bind.url)
    use_cache = not (has_app_context() and current_app.config.get("TESTING"))
    if use_cache and cache_key in _ensured_bindings:
        return

    with _schema_lock:
        if use_cache and cache_key in _ensured_bindings:
            return
        for table in TABLES:
            table.create(bind=bind, checkfirst=True)

        _ensure_columns()

        # create_all does not add newly declared indexes to an existing table.
        # Columns must be added first so indexes can safely reference them.
        for table in TABLES:
            for index in table.indexes:
                index.create(bind=bind, checkfirst=True)
        _backfill_product_categories()

        inspector = inspect(bind)
        if "mobile_feature_flag" not in inspector.get_table_names():
            return

        existing = {row.key for row in db.session.query(MobileFeatureFlag.key).all()}
        for key, enabled in DEFAULT_FEATURE_FLAGS.items():
            if key not in existing:
                db.session.add(MobileFeatureFlag(key=key, enabled=enabled))
        db.session.commit()
        _seed_reward_defaults()
        _seed_permissions()
        if use_cache:
            _ensured_bindings.add(cache_key)
