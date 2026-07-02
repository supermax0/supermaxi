"""Schema guard for fixed assets tables."""

from extensions import db
from models.fixed_asset_category import FixedAssetCategory
from models.fixed_asset import FixedAsset
from models.fixed_asset_movement import FixedAssetMovement
from models.fixed_asset_depreciation import FixedAssetDepreciation
from models.fixed_asset_maintenance import FixedAssetMaintenance


def ensure_fixed_assets_schema():
    bind = db.engine
    FixedAssetCategory.__table__.create(bind=bind, checkfirst=True)
    FixedAsset.__table__.create(bind=bind, checkfirst=True)
    FixedAssetMovement.__table__.create(bind=bind, checkfirst=True)
    FixedAssetDepreciation.__table__.create(bind=bind, checkfirst=True)
    FixedAssetMaintenance.__table__.create(bind=bind, checkfirst=True)
