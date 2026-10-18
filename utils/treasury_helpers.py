"""Shared helpers for treasury account selection and resolution."""
from __future__ import annotations

from models.treasury_account import TreasuryAccount


def sync_bank_accounts_across_branches() -> int:
    """Make every active bank/card definition available in every active branch.

    Cash boxes remain branch-specific.  Bank/card rows are copied per branch so
    existing same-branch validation and per-branch balance calculations stay
    correct when a card created in one branch is used from another branch.

    The caller owns the transaction.  The return value is the number of rows
    created or reactivated.
    """
    from extensions import db
    from models.branch import Branch

    branches = (
        Branch.query.execution_options(skip_branch_scope=True)
        .filter(Branch.is_active.is_(True))
        .order_by(Branch.id.asc())
        .all()
    )
    if not branches:
        return 0

    bank_accounts = (
        TreasuryAccount.query.execution_options(skip_branch_scope=True)
        .filter(TreasuryAccount.account_type == "bank")
        .order_by(TreasuryAccount.id.asc())
        .all()
    )
    if not bank_accounts:
        return 0

    # A normalized name identifies the same physical card/bank definition in
    # all branches.  Inactive definitions are kept only to detect an existing
    # local row; only active definitions are propagated.
    definitions = {}
    existing = {}
    for account in bank_accounts:
        key = (account.name or "").strip().casefold()
        if not key:
            continue
        if account.is_active and key not in definitions:
            definitions[key] = account
        if account.branch_id:
            existing[(int(account.branch_id), key)] = account

    changed = 0
    for branch in branches:
        branch_id = int(branch.id)
        for key, source in definitions.items():
            local = existing.get((branch_id, key))
            if local is not None:
                if source.is_active and not local.is_active:
                    local.is_active = True
                    changed += 1
                continue
            local = TreasuryAccount(
                branch_id=branch_id,
                name=(source.name or "").strip(),
                account_type="bank",
                is_default=False,
                is_active=bool(source.is_active),
            )
            db.session.add(local)
            existing[(branch_id, key)] = local
            changed += 1
    return changed


def get_default_cash_account(branch_id: int | None = None) -> TreasuryAccount:
    from utils.treasury_schema_guard import ensure_treasury_schema
    from utils.branch_scope import active_branch_id

    from flask import g
    # The request bootstrap has prepared the schema. Re-running migrations here
    # can commit another service's partial financial transaction.
    if not getattr(g,"finance_operation",False):
        ensure_treasury_schema()
    from utils.branch_mode import independent_branches_enabled

    shared_mode = not independent_branches_enabled()
    branch_id = branch_id or active_branch_id()
    query = TreasuryAccount.query
    if shared_mode:
        # Cash is one company-wide treasury in shared-branch mode.  Keep old
        # branch rows for history, but route all new entries to one canonical
        # active cash account.
        query = query.execution_options(skip_branch_scope=True)
        cash = (
            query.filter_by(account_type="cash", is_default=True, is_active=True)
            .order_by(TreasuryAccount.id.asc())
            .first()
        )
        if cash:
            return cash
        cash = (
            query.filter_by(account_type="cash", is_active=True)
            .order_by(TreasuryAccount.id.asc())
            .first()
        )
        if cash:
            cash.is_default = True
            return cash
        branch_id = None
    else:
        query = query
    if branch_id:
        query = query.execution_options(skip_branch_scope=True).filter(TreasuryAccount.branch_id == branch_id)
    cash = (
        query.filter_by(account_type="cash", is_default=True, is_active=True)
        .order_by(TreasuryAccount.id.asc())
        .first()
    )
    if cash:
        return cash
    cash = TreasuryAccount(
        name="الصندوق",
        account_type="cash",
        is_default=True,
        is_active=True,
        branch_id=branch_id,
    )
    from extensions import db

    db.session.add(cash)
    if getattr(g,"finance_operation",False):
        db.session.flush()
    else:
        db.session.commit()
    return cash


def resolve_treasury_account_id(raw_value) -> int:
    """Resolve form/API value to a valid treasury account id (default cash)."""
    from flask import has_request_context, request
    from utils.branch_mode import independent_branches_enabled
    from utils.branch_scope import resolve_write_branch_id

    write_branch_id = None
    if has_request_context() and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        source = (request.get_json(silent=True) or {}) if request.is_json else request.form
        write_branch_id = resolve_write_branch_id(source, required=True)
    default_id = get_default_cash_account(write_branch_id).id
    if raw_value is None or str(raw_value).strip() == "":
        return default_id
    try:
        account_id = int(raw_value)
    except (TypeError, ValueError):
        from flask import abort
        abort(400, description="حساب الخزينة غير صالح")
    query = TreasuryAccount.query
    # Legacy/shared companies historically used the same cash and bank choices
    # from either branch.  Keep strict same-branch validation only for tenants
    # that opted into the independent-branches system.
    if write_branch_id and independent_branches_enabled():
        query = query.execution_options(skip_branch_scope=True).filter(TreasuryAccount.branch_id == write_branch_id)
    account = query.filter_by(id=account_id, is_active=True).first()
    if not account:
        from flask import abort
        abort(403, description="حساب الخزينة لا يتبع الفرع المختار")
    # In legacy/shared mode the explicitly selected historical branch account
    # remains valid.  Normalizing it to the default account changes old forms
    # and breaks their audit trail; only an empty selection uses the default.
    return account.id


def treasury_choices_for_form(include_cash: bool = True, banks_only: bool = False):
    """Return active treasury accounts for form dropdowns."""
    from utils.treasury_schema_guard import ensure_treasury_schema

    ensure_treasury_schema()
    query = TreasuryAccount.query.filter_by(is_active=True).order_by(
        TreasuryAccount.is_default.desc(),
        TreasuryAccount.account_type.asc(),
        TreasuryAccount.name.asc(),
    )
    if banks_only:
        query = query.filter(TreasuryAccount.account_type == "bank")
    elif not include_cash:
        query = query.filter(TreasuryAccount.account_type != "cash")
    accounts = query.all()
    if accounts:
        from models.branch import Branch
        from utils.branch_mode import independent_branches_enabled

        if not independent_branches_enabled():
            # Legacy shared companies use one logical treasury.  Older data
            # may still contain duplicate cash/card rows created per branch;
            # expose one canonical choice for each account definition while
            # keeping the historical rows intact.
            canonical = {}
            for account in accounts:
                key = ((account.account_type or "bank").strip().lower(), (account.name or "").strip().casefold())
                current = canonical.get(key)
                if current is None or (bool(account.is_default), -int(account.id)) > (bool(current.is_default), -int(current.id)):
                    canonical[key] = account
            accounts = sorted(canonical.values(), key=lambda item: (
                not bool(item.is_default), (item.account_type or "").strip().lower(), (item.name or "").casefold(), int(item.id)
            ))

        branch_ids = {int(account.branch_id) for account in accounts if account.branch_id}
        branch_names = {
            int(branch.id): branch.name
            for branch in (
                Branch.query.execution_options(skip_branch_scope=True)
                .filter(Branch.id.in_(branch_ids or [-1]))
                .all()
            )
        }
        for account in accounts:
            account.branch_name = "مشترك" if not independent_branches_enabled() else branch_names.get(
                int(account.branch_id or 0), "فرع غير محدد"
            )
    return accounts


def account_matches_treasury(
    column,
    account_id: int,
    default_cash_id: int,
    *,
    branch_column=None,
    account_branch_id: int | None = None,
    include_unassigned_branch: bool = False,
):
    """Match an account without counting legacy NULL rows in every branch."""
    from sqlalchemy import and_, or_

    from utils.branch_mode import independent_branches_enabled

    if account_id == default_cash_id:
        if not independent_branches_enabled():
            cash_ids = TreasuryAccount.query.execution_options(skip_branch_scope=True).with_entities(
                TreasuryAccount.id
            ).filter(
                TreasuryAccount.account_type == "cash",
                TreasuryAccount.is_active.is_(True),
            ).subquery()
            return or_(column.is_(None), column.in_(cash_ids))
        if branch_column is not None and account_branch_id is not None:
            branch_match = branch_column == int(account_branch_id)
            if include_unassigned_branch:
                branch_match = or_(branch_match, branch_column.is_(None))
            return or_(
                column == account_id,
                and_(column.is_(None), branch_match),
            )
        return or_(column.is_(None), column == account_id)
    return column == account_id
