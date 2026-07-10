"""Supplier ledger reconciliation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from extensions import db
from models.fixed_asset import FixedAsset
from models.fixed_asset_maintenance import FixedAssetMaintenance
from models.purchase import Purchase
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _purchase_amount(purchase: Purchase) -> int:
    return _safe_int(purchase.grand_total if purchase.grand_total is not None else purchase.total)


def _purchase_paid(purchase: Purchase) -> int:
    return _safe_int(purchase.paid_total)


def _purchase_is_active(purchase: Purchase) -> bool:
    status = (purchase.status or "confirmed").strip().lower()
    if status in {"cancelled", "canceled"}:
        return False
    if status == "draft":
        return bool(getattr(purchase, "stock_applied", False))
    return True


def _fixed_asset_credit_for_supplier(supplier_id: int) -> int:
    try:
        return _safe_int(
            db.session.query(db.func.coalesce(db.func.sum(FixedAsset.credit_amount), 0))
            .filter(FixedAsset.supplier_id == supplier_id)
            .filter(FixedAsset.acquisition_journal_entry_id.isnot(None))
            .filter(FixedAsset.status != "draft")
            .scalar()
        )
    except Exception:
        db.session.rollback()
        return 0


def _fixed_asset_maintenance_credit_for_supplier(supplier_id: int) -> int:
    try:
        return _safe_int(
            db.session.query(db.func.coalesce(db.func.sum(FixedAssetMaintenance.amount), 0))
            .filter(FixedAssetMaintenance.supplier_id == supplier_id)
            .filter(FixedAssetMaintenance.payment_method == "credit")
            .scalar()
        )
    except Exception:
        db.session.rollback()
        return 0


@dataclass
class SupplierLedgerRepairReport:
    dry_run: bool = True
    suppliers_checked: int = 0
    suppliers_fixed: int = 0
    differences: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "suppliers_checked": self.suppliers_checked,
            "suppliers_fixed": self.suppliers_fixed,
            "differences": self.differences,
        }


def expected_supplier_totals(supplier_id: int) -> tuple[int, int]:
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return 0, 0

    purchases = Purchase.query.filter_by(supplier_id=supplier_id).all()
    active_purchases = [purchase for purchase in purchases if _purchase_is_active(purchase)]
    expected_debt = _safe_int(getattr(supplier, "opening_balance", 0)) + sum(
        _purchase_amount(purchase) for purchase in active_purchases
    )
    expected_debt += _fixed_asset_credit_for_supplier(supplier_id)
    expected_debt += _fixed_asset_maintenance_credit_for_supplier(supplier_id)
    purchase_paid = sum(_purchase_paid(purchase) for purchase in active_purchases)
    later_paid = (
        db.session.query(db.func.coalesce(db.func.sum(SupplierPayment.amount), 0))
        .filter(SupplierPayment.supplier_id == supplier_id)
        .scalar()
        or 0
    )
    expected_paid = purchase_paid + _safe_int(later_paid)
    return expected_debt, expected_paid


def audit_and_repair_supplier_ledgers(*, dry_run: bool = True) -> SupplierLedgerRepairReport:
    try:
        from routes.purchases import _ensure_purchase_schema

        _ensure_purchase_schema()
    except Exception:
        db.session.rollback()

    report = SupplierLedgerRepairReport(dry_run=dry_run)
    suppliers = Supplier.query.order_by(Supplier.id.asc()).all()
    report.suppliers_checked = len(suppliers)

    for supplier in suppliers:
        expected_debt, expected_paid = expected_supplier_totals(supplier.id)
        current_debt = _safe_int(supplier.total_debt)
        current_paid = _safe_int(supplier.total_paid)
        if current_debt == expected_debt and current_paid == expected_paid:
            continue

        report.suppliers_fixed += 1
        report.differences.append(
            {
                "supplier_id": supplier.id,
                "name": supplier.name,
                "current_debt": current_debt,
                "expected_debt": expected_debt,
                "current_paid": current_paid,
                "expected_paid": expected_paid,
                "current_remaining": current_debt - current_paid,
                "expected_remaining": expected_debt - expected_paid,
            }
        )
        if not dry_run:
            supplier.total_debt = expected_debt
            supplier.total_paid = expected_paid

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    return report
