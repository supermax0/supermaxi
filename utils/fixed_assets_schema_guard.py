"""Schema guard for fixed assets tables."""

from extensions import db
from models.fixed_asset_category import FixedAssetCategory
from models.fixed_asset import FixedAsset
from models.fixed_asset_movement import FixedAssetMovement
from models.fixed_asset_depreciation import FixedAssetDepreciation
from models.fixed_asset_maintenance import FixedAssetMaintenance
from models.fixed_asset_disposal import FixedAssetDisposal
from models.fixed_asset_settings import FixedAssetSettings
from models.fixed_asset_audit_log import FixedAssetAuditLog
from models.fixed_asset_attachment import FixedAssetAttachment
from models.fixed_asset_disposal_request import FixedAssetDisposalRequest
from models.financial_period_close import FinancialPeriodClose


def ensure_fixed_assets_schema():
    bind = db.engine
    FixedAssetCategory.__table__.create(bind=bind, checkfirst=True)
    FixedAsset.__table__.create(bind=bind, checkfirst=True)
    FixedAssetMovement.__table__.create(bind=bind, checkfirst=True)
    FixedAssetDepreciation.__table__.create(bind=bind, checkfirst=True)
    FixedAssetMaintenance.__table__.create(bind=bind, checkfirst=True)
    FixedAssetDisposal.__table__.create(bind=bind, checkfirst=True)
    FixedAssetSettings.__table__.create(bind=bind, checkfirst=True)
    FixedAssetAuditLog.__table__.create(bind=bind, checkfirst=True)
    FixedAssetAttachment.__table__.create(bind=bind, checkfirst=True)
    FixedAssetDisposalRequest.__table__.create(bind=bind, checkfirst=True)
    FinancialPeriodClose.__table__.create(bind=bind, checkfirst=True)
