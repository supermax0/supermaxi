"""Independent measured net assets versus append-only accounting profit.

Snapshots preserve declared cash/bank measurements and operational balances.
They never seed opening balances, create treasury mappings, or post corrections.
"""
import hashlib
import json
from datetime import datetime

from flask import g
from sqlalchemy import func, inspect
from extensions import db
from models.account import Account
from models.expense import Expense
from models.fixed_asset import FixedAsset
from models.journal_entry import JournalEntry
from models.rotating_savings import RotatingSaving
from utils.branch_mode import independent_branches_enabled
from utils.branch_scope import is_general_admin
from . import ledger, loans, migration, reports
from .common import FinanceError, actor, audit, dumps, money, require, tenant_key, text
from .models import FinanceAllocation, FinanceControlSnapshot, FinanceLoan, FinanceVoucher


def authorize(*, measure=False):
    require("finance.ledger")
    # Shared mode retains a physical branch for writes while reads cover the company.
    selected_branch = independent_branches_enabled() and getattr(g, "branch", None) and not getattr(g, "view_all_branches", False)
    if not is_general_admin(actor()) or selected_branch:
        raise FinanceError("الرقابة المالية تشمل الشركة كلها؛ اختر كل الفروع بحساب مدير الشركة", "forbidden", 403)
    if measure:
        require("finance.reconcile")


def _mapped_row(key, name, kind, target, account_ids):
    ids = sorted(set(int(value) for value in account_ids if value is not None))
    accounts = Account.query.filter(Account.id.in_(ids)).all() if ids else []
    current = sum(int(account.balance) for account in accounts) if ids and len(accounts) == len(ids) else None
    return {"key": key, "name": name, "type": kind, "target": int(target), "current": current,
        "difference": int(target)-current if current is not None else None, "account_ids": ids}


def source_rows():
    rows = migration.targets(read_only=True)
    # Existing migration totals cover treasury, FIFO/in-transit, invoices,
    # supplier/customer credits, HR salaries/advances and loan principal.
    borrowed = FinanceLoan.query.filter_by(direction="borrowed", status="active").all()
    rows.append(_mapped_row("interest_payable", "فوائد قروض مثبتة وغير مسددة", "liability",
        sum(loans.accrued_balance(loan) for loan in borrowed), [ledger.account("interest_payable").id]))
    accrued = Expense.query.join(FinanceVoucher, FinanceVoucher.source_id == Expense.id).filter(
        FinanceVoucher.source_type == "expense", FinanceVoucher.category == "expense_accrual",
        FinanceVoucher.status == "posted").all()
    remaining = 0
    for expense in accrued:
        payments = db.session.query(func.coalesce(func.sum(FinanceAllocation.amount), 0)).join(
            FinanceVoucher, FinanceVoucher.id == FinanceAllocation.voucher_id).filter(
                FinanceAllocation.reference_type == "accrued_expense", FinanceAllocation.reference_id == expense.id,
                FinanceVoucher.status == "posted").scalar() or 0
        remaining += max(0, int(expense.amount or 0)-int(payments))
    rows.append(_mapped_row("expense_payable", "مصاريف مثبتة وغير مسددة", "liability", remaining,
        [ledger.account("expense_payable").id]))
    fixed = FixedAsset.query.filter(FixedAsset.status.in_(("active", "under_installation", "fully_depreciated")),
        FixedAsset.acquisition_journal_entry_id.isnot(None)).all()
    asset_ids = {ledger.account("fixed_asset").id, ledger.account("accumulated_depreciation").id}
    asset_ids.update(asset.asset_account_id for asset in fixed if asset.asset_account_id)
    asset_ids.update(asset.accumulated_depreciation_account_id for asset in fixed if asset.accumulated_depreciation_account_id)
    rows.append(_mapped_row("fixed_assets_net", "صافي الأصول الثابتة بعد الإهلاك", "asset",
        sum(int(asset.book_value or 0) for asset in fixed), asset_ids))
    if inspect(db.session.connection()).has_table(RotatingSaving.__tablename__):
        savings = RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None)).all()
        if savings:
            rows.append(_mapped_row("rotating_assets", "أصول الجمعيات", "asset",
                sum(int(saving.asset_balance or 0) for saving in savings),
                [saving.asset_account_id for saving in savings]))
            rows.append(_mapped_row("rotating_liabilities", "التزامات الجمعيات", "liability",
                sum(int(saving.liability_balance or 0) for saving in savings),
                [saving.liability_account_id for saving in savings]))
    return rows


def _journal_hash(cursor):
    digest = hashlib.sha256()
    for row in JournalEntry.query.filter(JournalEntry.id <= cursor).order_by(JournalEntry.id).yield_per(500):
        digest.update(dumps([row.id, row.debit_account_id, row.credit_account_id, int(row.amount),
            str(row.entry_date), row.reference_type, row.reference_id]).encode("utf-8"))
    return digest.hexdigest()


def _totals(rows):
    assets = sum(row["target"] for row in rows if row["type"] == "asset")
    liabilities = sum(row["target"] for row in rows if row["type"] == "liability")
    return {"assets": assets, "liabilities": liabilities, "net_assets": assets-liabilities}


def _balance_issues(rows):
    return [{"key": row["key"], "message": f"فرق المصدر عن القيود: {row['name']}", "amount": row["difference"]}
        for row in rows if row["difference"] not in (None, 0)]


def _coverage(data):
    """Check the saved whole balance sheet, including older snapshots.

    Individually matching rows cannot certify duplicated/shared GL mappings.
    These diagnostics are derived from saved evidence; the payload is unchanged.
    """
    issues = list(data["coverage_issues"])
    additional = []
    for key, label in (("assets", "الأصول"), ("liabilities", "الالتزامات")):
        difference = data["registered"][key] - data["ledger"][key]
        if difference:
            additional.append({"key": f"balance_sheet:{key}",
                "message": f"فرق إجمالي {label} بين المصادر والميزانية", "amount": difference})
    if not data["ledger"]["balanced"]:
        additional.append({"key": "balance_sheet:equation", "message": "المعادلة المحاسبية للميزانية لا تتوازن",
            "amount": data["ledger"]["net_assets"]-data["ledger"]["equity"]-data["ledger"]["profit"]})
    present = {(item["key"], item["message"], item["amount"]) for item in issues}
    return issues + [item for item in additional if (item["key"], item["message"], item["amount"]) not in present]


def current():
    authorize()
    rows = source_rows()
    trial = reports.trial_balance({})
    covered = {account_id for row in rows for account_id in row["account_ids"]}
    unknown = [row for row in trial["rows"] if row["type"] in {"asset", "liability"}
        and row["balance"] != 0 and row["id"] not in covered]
    issues = [{"key": row["key"], "message": "مصدر بلا ربط محاسبي", "amount": row["target"]}
        for row in rows if not row["account_ids"] and row["target"] != 0]
    issues += [{"key": f"account:{row['id']}", "message": f"حساب يحتاج ربط مصدر: {row['name']}", "amount": row["balance"]}
        for row in unknown]
    if not trial["opening_migration_complete"]:
        issues.append({"key": "opening", "message": "الأرصدة الافتتاحية لم تعتمد بعد", "amount": 0})
    issues += _balance_issues(rows)
    result = {"rows": rows, "registered": _totals(rows), "ledger": {
        "assets": trial["assets"], "liabilities": trial["liabilities"],
        "net_assets": trial["assets"]-trial["liabilities"], "profit": trial["profit"],
        "equity": trial["equity"], "balanced": trial["balanced"]},
        "coverage_issues": issues, "independent_branches": independent_branches_enabled(),
        "generated_at": datetime.utcnow().isoformat(), "basis_version": 1}
    result["coverage_issues"] = _coverage(result)
    return result


def measure(payload):
    authorize(measure=True)
    data = current()
    treasuries = {row["treasury_account_id"]: row for row in data["rows"] if "treasury_account_id" in row}
    values = payload.get("treasury_counts")
    if not isinstance(values, list) or len(values) != len(treasuries):
        raise FinanceError("أدخل العد الفعلي أو رصيد الكشف لكل صندوق ومصرف ظاهر")
    used = set()
    evidence = []
    for value in values:
        if not isinstance(value, dict):
            raise FinanceError("بيانات العد غير صحيحة")
        account_id = money(value.get("id"))
        if account_id not in treasuries or account_id in used:
            raise FinanceError("الصندوق أو المصرف غير مسموح أو مكرر")
        used.add(account_id)
        row = treasuries[account_id]
        actual = money(value.get("actual"), minimum=0 if row["treasury_type"] == "cash" else -9_000_000_000_000_000)
        note = text(value.get("evidence"), 1000, True)
        evidence.append({"id": account_id, "name": row["name"], "registered": row["target"], "actual": actual,
            "difference": actual-row["target"], "evidence": note})
        row["target"] = actual
        row["difference"] = actual-row["current"] if row["current"] is not None else None
    data["measured"] = _totals(data["rows"])
    # A count that happens to agree with the ledger cannot erase a mismatch
    # between the independent operational source and that ledger.
    data["coverage_issues"] += [{"key": f"treasury_count:{item['id']}",
        "message": f"فرق العد أو كشف الحساب عن الرصيد التشغيلي: {item['name']}",
        "amount": item["difference"]} for item in evidence if item["difference"]]
    data["treasury_counts"] = evidence
    cursor = int(db.session.query(func.max(JournalEntry.id)).scalar() or 0)
    data["ledger_cursor"], data["ledger_hash"] = cursor, _journal_hash(cursor)
    data["ledger_accounts"] = [{"id": account.id, "type": account.account_type}
        for account in Account.query.order_by(Account.id).all()]
    data["owner_account_ids"] = {key: ledger.account(key).id
        for key in ("capital", "owner_draw", "opening_equity")}
    row = FinanceControlSnapshot(tenant_key=tenant_key(), name=text(payload.get("name"), 100, True),
        reason=text(payload.get("reason"), 1500, True), created_by=actor().id, payload=dumps(data))
    db.session.add(row)
    db.session.flush()
    audit("measure", "financial_control", row, {"net_assets": data["measured"]["net_assets"],
        "coverage_issues": len(data["coverage_issues"])})
    return serialize(row)


def get_snapshot(row_id):
    authorize()
    row = FinanceControlSnapshot.query.filter_by(id=money(row_id), tenant_key=tenant_key()).first()
    if row is None:
        raise FinanceError("المعاينة غير موجودة في الشركة الحالية", "not_found", 404)
    return row


def serialize(row, *, details=False):
    data = json.loads(row.payload)
    data["coverage_issues"] = _coverage(data)
    result = {"id": row.id, "name": row.name, "created_at": row.created_at.isoformat(),
        "created_by": row.creator.name if row.creator else f"موظف #{row.created_by}", "reason": row.reason,
        "net_assets": data["measured"]["net_assets"], "ledger_profit": data["ledger"]["profit"],
        "coverage_issues_count": len(data["coverage_issues"])}
    if details:
        result["data"] = data
    return result


def listing(args):
    authorize()
    page = money(args.get("page", 1))
    size = min(100, money(args.get("page_size", 25)))
    query = FinanceControlSnapshot.query.filter_by(tenant_key=tenant_key())
    return {"items": [serialize(row) for row in query.order_by(FinanceControlSnapshot.id.desc()).offset((page-1)*size).limit(size)],
        "total": query.count(), "page": page, "page_size": size}


def compare(start_id, end_id):
    start, end = get_snapshot(start_id), get_snapshot(end_id)
    if end.id <= start.id:
        raise FinanceError("اختر معاينتين مختلفتين بالترتيب الزمني الصحيح")
    before, after = json.loads(start.payload), json.loads(end.payload)
    if before["basis_version"] != after["basis_version"] or before["independent_branches"] != after["independent_branches"]:
        raise FinanceError("تغير أساس القياس أو نمط الفروع؛ ابدأ مقارنة على أساس موحد", "conflict", 409)
    for data in (before, after):
        if _journal_hash(data["ledger_cursor"]) != data["ledger_hash"]:
            raise FinanceError("تغيرت قيود محفوظة قبل المعاينة؛ راجع التاريخ قبل اعتماد المطابقة", "history_changed", 409)
    accounts = {row.id: row for row in Account.query.all()}
    for data in (before, after):
        if any(item["id"] not in accounts or accounts[item["id"]].account_type != item["type"]
                for item in data["ledger_accounts"]):
            raise FinanceError("تغير تصنيف حساب بعد المعاينة؛ راجع أساس المطابقة", "history_changed", 409)
        if data["owner_account_ids"] != {key: ledger.account(key).id
                for key in ("capital", "owner_draw", "opening_equity")}:
            raise FinanceError("تغير ربط حسابات حقوق الملكية بعد المعاينة", "history_changed", 409)
    owner_ids = {ledger.account(key).id for key in ("capital", "owner_draw", "opening_equity")}
    profit, contributions, withdrawals, opening, other_equity = 0, 0, 0, 0, 0
    roles = {ledger.account(key).id: key for key in ("capital", "owner_draw", "opening_equity")}
    for entry in JournalEntry.query.filter(JournalEntry.id > before["ledger_cursor"], JournalEntry.id <= after["ledger_cursor"]):
        for account_id, sign in ((entry.credit_account_id, 1), (entry.debit_account_id, -1)):
            account = accounts.get(account_id)
            if account is None:
                raise FinanceError("قيد يشير لحساب مفقود؛ راجع سجل الحسابات", "history_changed", 409)
            if account.account_type in {"revenue", "expense"}:
                profit += sign*int(entry.amount)
            if account_id in owner_ids:
                if roles[account_id] == "capital": contributions += sign*int(entry.amount)
                elif roles[account_id] == "owner_draw": withdrawals -= sign*int(entry.amount)
                else: opening += sign*int(entry.amount)
            elif account.account_type == "equity":
                other_equity += sign*int(entry.amount)
    change = after["measured"]["net_assets"]-before["measured"]["net_assets"]
    derived = change-contributions+withdrawals-opening-other_equity
    issues = _coverage(before)+_coverage(after)
    return {"start": serialize(start), "end": serialize(end), "net_assets_change": change,
        "capital": contributions, "owner_drawings": withdrawals, "opening_adjustments": opening,
        "other_equity": other_equity, "accounting_profit": profit, "derived_profit": derived,
        "difference": derived-profit, "matched": derived == profit and not issues,
        "coverage_issues": issues, "note": "القياس بين معاينتين محفوظتين حسب القيود المضافة بينهما، ويشمل التصحيحات المؤرخة قديماً التي أضيفت لاحقاً؛ لا يخترع أرصدة تاريخية."}
