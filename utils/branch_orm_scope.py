"""Automatic read isolation for branch-owned ORM models."""
from __future__ import annotations

from flask import abort, g, has_request_context, request, session
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

_INSTALLED = False
_SCOPE_OPTIONS: dict[int, tuple] = {}


def install_branch_orm_scope() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    @event.listens_for(Session, "do_orm_execute")
    def _apply_scope(execute_state):
        if not execute_state.is_select or execute_state.is_column_load:
            return
        if execute_state.execution_options.get("skip_branch_scope"):
            return
        if not has_request_context():
            return
        # Context existence is the readiness flag. Login/core queries run
        # before init_branch_context and must remain untouched.
        if not getattr(g, "branch_scope_ready", False):
            return
        if not getattr(g, "independent_branches_enabled", True):
            return
        public_branch_id = getattr(g, "public_branch_id", None)
        if not public_branch_id and not session.get("user_id"):
            return
        if not public_branch_id and session.get("role") == "admin" and bool(getattr(g, "view_all_branches", False)):
            return
        branch = getattr(g, "branch", None)
        branch_id = public_branch_id or (int(branch.id) if branch is not None else session.get("branch_id"))
        if not branch_id:
            return
        branch_id = int(branch_id)
        # The same 21 criteria for a branch are built once and applied in ONE options() call (building them and
        # copying the statement 21 times on every query cost ~1.7 ms per query on store pages).
        options = _SCOPE_OPTIONS.get(branch_id)
        if options is None:
            options = _SCOPE_OPTIONS[branch_id] = _scope_options(branch_id)
        execute_state.statement = execute_state.statement.options(*options)

    def _scope_options(branch_id: int) -> tuple:
        from models.account_transaction import AccountTransaction
        from models.activity_log import ActivityLog
        from models.customer import Customer
        from models.delivery_agent import DeliveryAgent
        from models.employee_payment import EmployeePayment
        from models.expense import Expense
        from models.fixed_asset import FixedAsset
        from models.invoice import Invoice
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from models.product import Product
        from models.purchase import Purchase
        from models.purchase_payment import PurchasePayment
        from models.shipping import ShippingCompany
        from models.shipping_report import ShippingReport
        from models.shipping_payment import ShippingPayment
        from models.stock_movement import StockMovement
        from models.supplier import Supplier
        from models.supplier_payment import SupplierPayment
        from models.treasury_account import TreasuryAccount
        from models.treasury_transfer import TreasuryTransfer
        from models.trade_in_receipt import TradeInReceipt

        branch_models = (
            AccountTransaction,
            ActivityLog,
            Customer,
            DeliveryAgent,
            EmployeePayment,
            Expense,
            FixedAsset,
            Invoice,
            InvoicePaymentLedger,
            Product,
            Purchase,
            PurchasePayment,
            ShippingCompany,
            ShippingReport,
            ShippingPayment,
            StockMovement,
            Supplier,
            SupplierPayment,
            TreasuryAccount,
            TreasuryTransfer,
            TradeInReceipt,
        )
        return tuple(
            with_loader_criteria(
                model,
                lambda row: row.branch_id == branch_id,
                include_aliases=True,
            )
            for model in branch_models
        )

    @event.listens_for(Session, "before_flush")
    def _propagate_write_branch(orm_session, _flush_context, _instances):
        if not has_request_context():
            return
        public_branch_id = getattr(g, "public_branch_id", None)
        if not public_branch_id and not session.get("user_id"):
            return
        if not getattr(g, "branch_scope_ready", False):
            return
        if not getattr(g, "independent_branches_enabled", True):
            return

        from models.account_transaction import AccountTransaction
        from models.customer import Customer
        from models.delivery_agent import DeliveryAgent
        from models.employee_payment import EmployeePayment
        from models.expense import Expense
        from models.fixed_asset import FixedAsset
        from models.invoice import Invoice
        from models.invoice_payment_ledger import InvoicePaymentLedger
        from models.product import Product
        from models.purchase import Purchase
        from models.purchase_payment import PurchasePayment
        from models.shipping import ShippingCompany
        from models.shipping_report import ShippingReport
        from models.shipping_payment import ShippingPayment
        from models.supplier import Supplier
        from models.supplier_payment import SupplierPayment
        from models.treasury_account import TreasuryAccount
        from models.treasury_transfer import TreasuryTransfer
        from models.trade_in_receipt import TradeInReceipt

        branch_owned = (
            AccountTransaction,
            Customer,
            DeliveryAgent,
            EmployeePayment,
            Expense,
            FixedAsset,
            Invoice,
            InvoicePaymentLedger,
            Product,
            Purchase,
            PurchasePayment,
            ShippingCompany,
            ShippingReport,
            ShippingPayment,
            Supplier,
            SupplierPayment,
            TreasuryAccount,
            TreasuryTransfer,
            TradeInReceipt,
        )
        current = getattr(g, "branch", None)
        current_id = int(current.id) if current is not None else (
            int(public_branch_id) if public_branch_id else None
        )
        if not current_id and session.get("role") == "admin" and getattr(g, "view_all_branches", False):
            payload = request.get_json(silent=True) if request.is_json else request.form
            raw_branch_id = (payload or {}).get("branch_id")
            try:
                requested_id = int(raw_branch_id)
            except (TypeError, ValueError):
                requested_id = 0
            allowed_ids = {int(branch.id) for branch in (getattr(g, "branches", []) or [])}
            if requested_id in allowed_ids:
                current_id = requested_id
            else:
                default_branch = next(
                    (
                        branch
                        for branch in (getattr(g, "branches", []) or [])
                        if getattr(branch, "is_default", False)
                    ),
                    None,
                )
                if default_branch is not None:
                    current_id = int(default_branch.id)

        def parent_branch(obj):
            for relation_name in (
                "invoice", "purchase", "supplier", "shipping_company",
                "treasury_account", "expense",
            ):
                parent = getattr(obj, relation_name, None)
                value = getattr(parent, "branch_id", None) if parent is not None else None
                if value:
                    return int(value)
            return None

        for obj in list(orm_session.new):
            if not isinstance(obj, branch_owned) or getattr(obj, "branch_id", None):
                continue
            derived = parent_branch(obj)
            if not derived and isinstance(obj, TreasuryTransfer):
                account = getattr(obj, "from_account", None)
                derived = getattr(account, "branch_id", None) if account else None
            if derived or current_id:
                obj.branch_id = int(derived or current_id)
            else:
                abort(400, description="يجب اختيار الفرع قبل الحفظ")
