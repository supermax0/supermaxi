"""
خدمة الأصول الثابتة — المرحلة الأولى: اقتناء الأصل وقيد الشراء.
"""

from __future__ import annotations

from datetime import date, datetime
import uuid

from extensions import db
from models.account import Account
from models.account_transaction import AccountTransaction
from models.fixed_asset import FixedAsset
from models.fixed_asset_category import FixedAssetCategory
from models.fixed_asset_movement import FixedAssetMovement
from models.fixed_asset_depreciation import FixedAssetDepreciation
from models.fixed_asset_maintenance import FixedAssetMaintenance
from models.journal_entry import JournalEntry
from models.supplier import Supplier
from utils.accounting_logic import ACCOUNT_CODES, get_or_create_account, initialize_accounts
from utils.fixed_assets_schema_guard import ensure_fixed_assets_schema
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_helpers import resolve_treasury_account_id

FIXED_ASSET_GL = {
    "FIXED_ASSETS": "1301",
    "ACCUMULATED_DEPRECIATION": "1302",
    "DEPRECIATION_EXPENSE": "6101",
    "MAINTENANCE_EXPENSE": "6102",
    "BANK": "1002",
}

DEFAULT_CATEGORIES = [
    ("سيارات", "1310", "2310", "6110", 60, 0, True),
    ("حاسبات ولابتوبات", "1311", "2311", "6111", 36, 0, True),
    ("أثاث ومفروشات", "1312", "2312", "6112", 84, 0, True),
    ("أجهزة ومعدات", "1313", "2313", "6113", 60, 0, True),
    ("كاميرات وأنظمة مراقبة", "1314", "2314", "6114", 48, 0, True),
    ("تجهيزات مكتبية", "1315", "2315", "6115", 60, 0, True),
    ("مباني", "1316", "2316", "6116", 240, 0, True),
    ("أراضي", "1317", None, None, 0, 0, False),
    ("أصول تحت التركيب", "1318", "2318", "6118", 60, 0, False),
]


class FixedAssetError(Exception):
    pass


def _safe_int(value, default=0):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def ensure_fixed_asset_gl_accounts():
    initialize_accounts()
    get_or_create_account(
        FIXED_ASSET_GL["FIXED_ASSETS"],
        "الأصول الثابتة",
        "asset",
        "حساب الأصول الثابتة العام",
    )
    get_or_create_account(
        FIXED_ASSET_GL["ACCUMULATED_DEPRECIATION"],
        "مجمع استهلاك الأصول",
        "asset",
        "مجمع استهلاك الأصول الثابتة (حساب مقابل)",
    )
    get_or_create_account(
        FIXED_ASSET_GL["DEPRECIATION_EXPENSE"],
        "مصروف استهلاك الأصول",
        "expense",
        "مصروف استهلاك الأصول الثابتة",
    )
    get_or_create_account(
        FIXED_ASSET_GL["BANK"],
        "البنك",
        "asset",
        "حساب البنك",
    )
    get_or_create_account(
        FIXED_ASSET_GL["MAINTENANCE_EXPENSE"],
        "مصروف صيانة الأصول",
        "expense",
        "مصروف صيانة الأصول الثابتة",
    )
    db.session.commit()


def _create_category_accounts(name, asset_code, accum_code, expense_code, is_depreciable):
    asset_acc = get_or_create_account(
        asset_code, f"أصول ثابتة - {name}", "asset", f"حساب أصل {name}"
    )
    accum_acc = None
    expense_acc = None
    if is_depreciable and accum_code and expense_code:
        accum_acc = get_or_create_account(
            accum_code,
            f"مجمع استهلاك - {name}",
            "asset",
            f"مجمع استهلاك {name}",
        )
        expense_acc = get_or_create_account(
            expense_code,
            f"مصروف استهلاك - {name}",
            "expense",
            f"مصروف استهلاك {name}",
        )
    return asset_acc, accum_acc, expense_acc


def seed_default_categories():
    ensure_fixed_assets_schema()
    ensure_fixed_asset_gl_accounts()
    if FixedAssetCategory.query.count() > 0:
        return
    for row in DEFAULT_CATEGORIES:
        name, ac, acc, ec, life, salvage, depreciable = row
        asset_acc, accum_acc, expense_acc = _create_category_accounts(
            name, ac, acc, ec, depreciable
        )
        cat = FixedAssetCategory(
            name=name,
            asset_account_id=asset_acc.id,
            accumulated_depreciation_account_id=accum_acc.id if accum_acc else None,
            depreciation_expense_account_id=expense_acc.id if expense_acc else None,
            default_useful_life_months=life,
            default_salvage_value=salvage,
            is_depreciable=depreciable,
            is_active=True,
        )
        db.session.add(cat)
    db.session.commit()


def generate_asset_code():
    year = datetime.utcnow().year
    prefix = f"FA-{year}-"
    last = (
        FixedAsset.query.filter(FixedAsset.asset_code.like(f"{prefix}%"))
        .order_by(FixedAsset.id.desc())
        .first()
    )
    seq = 1
    if last and last.asset_code.startswith(prefix):
        try:
            seq = int(last.asset_code.split("-")[-1]) + 1
        except ValueError:
            seq = FixedAsset.query.count() + 1
    return f"{prefix}{seq:04d}"


def calculate_total_cost(purchase_price, shipping_cost, installation_cost, other_cost, discount_amount):
    total = (
        _safe_int(purchase_price)
        + _safe_int(shipping_cost)
        + _safe_int(installation_cost)
        + _safe_int(other_cost)
        - _safe_int(discount_amount)
    )
    return max(total, 0)


def calculate_monthly_depreciation(total_cost, salvage_value, useful_life_months):
    life = _safe_int(useful_life_months)
    if life <= 0:
        return 0
    base = max(_safe_int(total_cost) - _safe_int(salvage_value), 0)
    if base <= 0:
        return 0
    return int(round(base / life))


def _journal_by_ids(
    debit_account_id,
    credit_account_id,
    amount,
    description,
    reference_type=None,
    reference_id=None,
    created_by=None,
):
    amount = _safe_int(amount)
    if amount <= 0:
        return None
    if debit_account_id == credit_account_id:
        raise FixedAssetError("الحساب المدين والدائن يجب أن يكونا مختلفين")
    entry_number = f"JE-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    entry = JournalEntry(
        entry_number=entry_number,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        debit_account_id=debit_account_id,
        credit_account_id=credit_account_id,
        amount=amount,
        entry_date=datetime.utcnow(),
        created_by=created_by,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def _resolve_payment_accounts(payment_method, treasury_account_id=None):
    if payment_method == "bank":
        bank = Account.query.filter_by(code=FIXED_ASSET_GL["BANK"]).first()
        if not bank:
            ensure_fixed_asset_gl_accounts()
            bank = Account.query.filter_by(code=FIXED_ASSET_GL["BANK"]).first()
        return bank.id if bank else None
    cash = Account.query.filter_by(code=ACCOUNT_CODES["CASH"]).first()
    if not cash:
        initialize_accounts()
        cash = Account.query.filter_by(code=ACCOUNT_CODES["CASH"]).first()
    return cash.id if cash else None


def build_asset_from_form(data, user_id=None, as_draft=True):
    ensure_fixed_assets_schema()
    seed_default_categories()

    category_id = _safe_int(data.get("category_id"))
    category = FixedAssetCategory.query.get(category_id)
    if not category:
        raise FixedAssetError("التصنيف مطلوب")

    purchase_price = _safe_int(data.get("purchase_price"))
    shipping_cost = _safe_int(data.get("shipping_cost"))
    installation_cost = _safe_int(data.get("installation_cost"))
    other_cost = _safe_int(data.get("other_cost"))
    discount_amount = _safe_int(data.get("discount_amount"))
    total_cost = calculate_total_cost(
        purchase_price, shipping_cost, installation_cost, other_cost, discount_amount
    )

    salvage_value = _safe_int(data.get("salvage_value"), category.default_salvage_value or 0)
    useful_life_months = _safe_int(
        data.get("useful_life_months"), category.default_useful_life_months or 0
    )
    is_depreciable = str(data.get("is_depreciable", category.is_depreciable)).lower() in (
        "1", "true", "yes", "on"
    )
    monthly_dep = (
        calculate_monthly_depreciation(total_cost, salvage_value, useful_life_months)
        if is_depreciable
        else 0
    )

    asset_code = (data.get("asset_code") or "").strip() or generate_asset_code()
    if FixedAsset.query.filter_by(asset_code=asset_code).first():
        raise FixedAssetError("كود الأصل مستخدم مسبقاً")

    status = (data.get("status") or ("draft" if as_draft else "active")).strip()
    payment_method = (data.get("payment_method") or "cash").strip()
    paid_amount = _safe_int(data.get("paid_amount"))
    credit_amount = _safe_int(data.get("credit_amount"))

    if payment_method == "cash" or payment_method == "bank":
        paid_amount = total_cost
        credit_amount = 0
    elif payment_method == "credit":
        paid_amount = 0
        credit_amount = total_cost
    elif payment_method == "mixed":
        if paid_amount + credit_amount != total_cost:
            raise FixedAssetError("مجموع المدفوع والآجل يجب أن يساوي تكلفة الأصل")

    asset = FixedAsset(
        asset_code=asset_code,
        name=(data.get("name") or "").strip(),
        category_id=category.id,
        description=(data.get("description") or "").strip() or None,
        serial_number=(data.get("serial_number") or "").strip() or None,
        barcode=(data.get("barcode") or "").strip() or asset_code,
        purchase_date=_parse_date(data.get("purchase_date")),
        ready_date=_parse_date(data.get("ready_date")),
        supplier_id=_safe_int(data.get("supplier_id")) or None,
        supplier_invoice_no=(data.get("supplier_invoice_no") or "").strip() or None,
        purchase_price=purchase_price,
        shipping_cost=shipping_cost,
        installation_cost=installation_cost,
        other_cost=other_cost,
        discount_amount=discount_amount,
        total_cost=total_cost,
        salvage_value=salvage_value,
        useful_life_months=useful_life_months,
        depreciation_method="straight_line",
        monthly_depreciation=monthly_dep,
        accumulated_depreciation=0,
        book_value=total_cost,
        is_depreciable=is_depreciable,
        asset_account_id=category.asset_account_id,
        accumulated_depreciation_account_id=category.accumulated_depreciation_account_id,
        depreciation_expense_account_id=category.depreciation_expense_account_id,
        branch_id=_safe_int(data.get("branch_id")) or None,
        location_text=(data.get("location_text") or "").strip() or None,
        responsible_user_id=_safe_int(data.get("responsible_user_id")) or None,
        status=status,
        payment_method=payment_method,
        treasury_account_id=_safe_int(data.get("treasury_account_id")) or None,
        paid_amount=paid_amount,
        credit_amount=credit_amount,
        created_by=user_id,
        updated_by=user_id,
    )
    if not asset.name:
        raise FixedAssetError("اسم الأصل مطلوب")
    if total_cost <= 0 and not as_draft:
        raise FixedAssetError("تكلفة الأصل يجب أن تكون أكبر من صفر للترحيل")
    if not asset.asset_account_id:
        raise FixedAssetError("التصنيف لا يحتوي حساب أصل محاسبي")

    db.session.add(asset)
    db.session.flush()
    return asset


def post_asset_acquisition(asset: FixedAsset, user_id=None):
    if asset.status not in ("draft", "under_installation"):
        raise FixedAssetError("لا يمكن ترحيل هذا الأصل في حالته الحالية")
    if asset.acquisition_journal_entry_id:
        raise FixedAssetError("تم ترحيل قيد شراء هذا الأصل مسبقاً")
    if asset.total_cost <= 0:
        raise FixedAssetError("تكلفة الأصل يجب أن تكون أكبر من صفر")

    ensure_fixed_asset_gl_accounts()
    asset_account_id = asset.asset_account_id
    if not asset_account_id:
        raise FixedAssetError("حساب الأصل غير محدد")

    payment_method = asset.payment_method or "cash"
    paid = _safe_int(asset.paid_amount)
    credit = _safe_int(asset.credit_amount)
    total = _safe_int(asset.total_cost)

    if payment_method in ("cash", "bank"):
        paid = total
        credit = 0
    elif payment_method == "credit":
        paid = 0
        credit = total
    else:
        if paid + credit != total:
            raise FixedAssetError("مجموع المدفوع والآجل لا يساوي تكلفة الأصل")

    pay_account_id = _resolve_payment_accounts(payment_method, asset.treasury_account_id)
    ap_account = Account.query.filter_by(code=ACCOUNT_CODES["ACCOUNTS_PAYABLE"]).first()
    if not ap_account:
        initialize_accounts()
        ap_account = Account.query.filter_by(code=ACCOUNT_CODES["ACCOUNTS_PAYABLE"]).first()

    first_entry = None
    desc_base = f"شراء أصل ثابت {asset.asset_code} - {asset.name}"

    if paid > 0:
        if not pay_account_id:
            raise FixedAssetError("حساب الدفع غير متوفر")
        if payment_method in ("cash", "bank", "mixed"):
            asset.treasury_account_id = resolve_treasury_account_id(asset.treasury_account_id)
        if asset.treasury_account_id and payment_method in ("cash", "bank", "mixed"):
            try:
                assert_sufficient_balance(asset.treasury_account_id, paid)
            except InsufficientTreasuryBalance as exc:
                raise FixedAssetError(str(exc)) from exc
            db.session.add(
                AccountTransaction(
                    type="withdraw",
                    amount=paid,
                    note=f"شراء أصل: {asset.asset_code} - {asset.name}",
                    treasury_account_id=asset.treasury_account_id,
                )
            )
        entry = _journal_by_ids(
            asset_account_id,
            pay_account_id,
            paid,
            f"{desc_base} (جزء نقدي/بنكي)",
            reference_type="fixed_asset_acquisition",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or entry

    if credit > 0:
        if not ap_account:
            raise FixedAssetError("حساب الموردين غير متوفر")
        if asset.supplier_id:
            supplier = Supplier.query.get(asset.supplier_id)
            if supplier:
                supplier.total_debt = _safe_int(supplier.total_debt) + credit
        entry = _journal_by_ids(
            asset_account_id,
            ap_account.id,
            credit,
            f"{desc_base} (جزء آجل)",
            reference_type="fixed_asset_acquisition",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or entry

    if not first_entry:
        raise FixedAssetError("لا يوجد قيد محاسبي للترحيل")

    movement = FixedAssetMovement(
        asset_id=asset.id,
        movement_type="acquisition",
        movement_date=asset.purchase_date or date.today(),
        amount=total,
        old_book_value=0,
        new_book_value=total,
        journal_entry_id=first_entry.id,
        source_type="fixed_asset",
        source_id=asset.id,
        notes="ترحيل شراء الأصل",
        created_by=user_id,
    )
    db.session.add(movement)

    asset.acquisition_journal_entry_id = first_entry.id
    asset.status = "active" if asset.status == "draft" else asset.status
    asset.book_value = total
    asset.paid_amount = paid
    asset.credit_amount = credit
    asset.updated_by = user_id
    asset.updated_at = datetime.utcnow()

    return first_entry


def dashboard_stats():
    assets = FixedAsset.query.all()
    active = [a for a in assets if a.status == "active"]
    today = date.today()
    not_depreciated_this_month = sum(
        1
        for a in active
        if a.is_depreciable
        and a.acquisition_journal_entry_id
        and not (
            a.last_depreciation_year == today.year
            and a.last_depreciation_month == today.month
        )
        and _safe_int(a.book_value) > _safe_int(a.salvage_value)
    )
    return {
        "total_cost": sum(_safe_int(a.total_cost) for a in assets if a.status not in ("sold", "scrapped")),
        "accumulated_depreciation": sum(_safe_int(a.accumulated_depreciation) for a in assets),
        "book_value": sum(_safe_int(a.book_value) for a in assets if a.status not in ("sold", "scrapped")),
        "active_count": len(active),
        "under_installation_count": sum(1 for a in assets if a.status == "under_installation"),
        "fully_depreciated_count": sum(1 for a in assets if a.status == "fully_depreciated"),
        "sold_count": sum(1 for a in assets if a.status == "sold"),
        "scrapped_count": sum(1 for a in assets if a.status == "scrapped"),
        "draft_count": sum(1 for a in assets if a.status == "draft"),
        "not_depreciated_this_month": not_depreciated_this_month,
    }


# ─── المرحلة 2: الاستهلاك الشهري ───

def _depreciation_start_date(asset: FixedAsset):
    return asset.ready_date or asset.purchase_date


def _period_not_before_start(asset: FixedAsset, year: int, month: int) -> bool:
    start = _depreciation_start_date(asset)
    if not start:
        return True
    return (year, month) >= (start.year, start.month)


def _already_depreciated(asset: FixedAsset, year: int, month: int) -> bool:
    return FixedAssetDepreciation.query.filter_by(
        asset_id=asset.id, period_year=year, period_month=month
    ).first() is not None


def _depreciation_skip_reason(asset: FixedAsset, year: int, month: int) -> str | None:
    if asset.status in ("sold", "scrapped", "under_installation", "draft"):
        return f"الحالة: {asset.status_label()}"
    if not asset.is_depreciable:
        return "غير قابل للاستهلاك"
    if not asset.acquisition_journal_entry_id:
        return "لم يُرحّل قيد الشراء"
    if not asset.depreciation_expense_account_id or not asset.accumulated_depreciation_account_id:
        return "حسابات الاستهلاك غير مكتملة"
    if _already_depreciated(asset, year, month):
        return "مستهلك مسبقاً لهذا الشهر"
    if not _period_not_before_start(asset, year, month):
        return "قبل تاريخ الجاهزية"
    book = _safe_int(asset.book_value)
    salvage = _safe_int(asset.salvage_value)
    if book <= salvage:
        return "وصل لقيمة الخردة"
    if _safe_int(asset.monthly_depreciation) <= 0 and book - salvage <= 0:
        return "لا يوجد استهلاك شهري"
    return None


def compute_depreciation_amount(asset: FixedAsset) -> int:
    book = _safe_int(asset.book_value)
    salvage = _safe_int(asset.salvage_value)
    if book <= salvage:
        return 0
    monthly = _safe_int(asset.monthly_depreciation)
    if monthly <= 0:
        monthly = calculate_monthly_depreciation(
            asset.total_cost, asset.salvage_value, asset.useful_life_months
        )
    return min(monthly, book - salvage)


def preview_monthly_depreciation(year: int, month: int):
    ensure_fixed_assets_schema()
    rows = []
    for asset in FixedAsset.query.order_by(FixedAsset.asset_code).all():
        reason = _depreciation_skip_reason(asset, year, month)
        amount = 0 if reason else compute_depreciation_amount(asset)
        book = _safe_int(asset.book_value)
        salvage = _safe_int(asset.salvage_value)
        last = "—"
        if asset.last_depreciation_year and asset.last_depreciation_month:
            last = f"{asset.last_depreciation_year}-{asset.last_depreciation_month:02d}"
        rows.append({
            "asset": asset,
            "eligible": reason is None and amount > 0,
            "amount": amount,
            "book_after": book - amount if amount else book,
            "skip_reason": reason,
            "last_period": last,
        })
    eligible = [r for r in rows if r["eligible"]]
    return {
        "year": year,
        "month": month,
        "rows": rows,
        "eligible_count": len(eligible),
        "total_amount": sum(r["amount"] for r in eligible),
    }


def post_monthly_depreciation(year: int, month: int, user_id=None):
    preview = preview_monthly_depreciation(year, month)
    eligible = [r for r in preview["rows"] if r["eligible"]]
    if not eligible:
        raise FixedAssetError("لا توجد أصول جاهزة للاستهلاك في هذه الفترة")

    ensure_fixed_asset_gl_accounts()
    grouped: dict[tuple[int, int], int] = {}
    posted_records = []

    for row in eligible:
        asset = row["asset"]
        amount = row["amount"]
        if amount <= 0:
            continue

        exp_id = asset.depreciation_expense_account_id
        accum_id = asset.accumulated_depreciation_account_id
        key = (exp_id, accum_id)
        grouped[key] = grouped.get(key, 0) + amount

        accum_before = _safe_int(asset.accumulated_depreciation)
        book_before = _safe_int(asset.book_value)
        accum_after = accum_before + amount
        book_after = book_before - amount

        dep = FixedAssetDepreciation(
            asset_id=asset.id,
            period_year=year,
            period_month=month,
            depreciation_amount=amount,
            accumulated_before=accum_before,
            accumulated_after=accum_after,
            book_value_before=book_before,
            book_value_after=book_after,
            status="posted",
            posted_by=user_id,
        )
        db.session.add(dep)
        db.session.flush()

        asset.accumulated_depreciation = accum_after
        asset.book_value = book_after
        asset.last_depreciation_year = year
        asset.last_depreciation_month = month
        asset.updated_by = user_id
        asset.updated_at = datetime.utcnow()
        if book_after <= _safe_int(asset.salvage_value):
            asset.status = "fully_depreciated"

        posted_records.append((dep, asset, amount))

    journal_map: dict[tuple[int, int], int] = {}
    period_label = f"{year}-{month:02d}"
    for (exp_id, accum_id), total_amt in grouped.items():
        entry = _journal_by_ids(
            exp_id,
            accum_id,
            total_amt,
            f"استهلاك أصول ثابتة — {period_label}",
            reference_type="fixed_asset_depreciation",
            reference_id=None,
            created_by=user_id,
        )
        journal_map[(exp_id, accum_id)] = entry.id

    for dep, asset, amount in posted_records:
        key = (asset.depreciation_expense_account_id, asset.accumulated_depreciation_account_id)
        dep.journal_entry_id = journal_map.get(key)
        db.session.add(
            FixedAssetMovement(
                asset_id=asset.id,
                movement_type="depreciation",
                movement_date=date(year, month, 1),
                amount=amount,
                old_book_value=dep.book_value_before,
                new_book_value=dep.book_value_after,
                journal_entry_id=dep.journal_entry_id,
                source_type="fixed_asset_depreciation",
                source_id=dep.id,
                notes=f"استهلاك {period_label}",
                created_by=user_id,
            )
        )

    return {
        "posted_count": len(posted_records),
        "total_amount": sum(r["amount"] for r in eligible),
        "journal_count": len(journal_map),
    }


def get_asset_depreciation_schedule(asset_id: int):
    return (
        FixedAssetDepreciation.query.filter_by(asset_id=asset_id)
        .order_by(
            FixedAssetDepreciation.period_year.desc(),
            FixedAssetDepreciation.period_month.desc(),
        )
        .all()
    )


# ─── المرحلة 3: الصيانة والتحسينات ───

def post_asset_maintenance(data, user_id=None):
    ensure_fixed_assets_schema()
    ensure_fixed_asset_gl_accounts()

    asset_id = _safe_int(data.get("asset_id"))
    asset = FixedAsset.query.get(asset_id)
    if not asset:
        raise FixedAssetError("الأصل غير موجود")
    if asset.status in ("sold", "scrapped", "draft"):
        raise FixedAssetError("لا يمكن تسجيل صيانة على أصل في هذه الحالة")

    mtype = (data.get("maintenance_type") or "regular").strip()
    amount = _safe_int(data.get("amount"))
    if amount <= 0:
        raise FixedAssetError("المبلغ يجب أن يكون أكبر من صفر")

    maintenance_date = _parse_date(data.get("maintenance_date")) or date.today()
    payment_method = (data.get("payment_method") or "cash").strip()
    treasury_id = resolve_treasury_account_id(data.get("treasury_account_id"))
    is_capitalized = mtype == "improvement"

    pay_account_id = _resolve_payment_accounts(payment_method, treasury_id)
    if not pay_account_id:
        raise FixedAssetError("حساب الدفع غير متوفر")

    if payment_method in ("cash", "bank", "mixed"):
        try:
            assert_sufficient_balance(treasury_id, amount)
        except InsufficientTreasuryBalance as exc:
            raise FixedAssetError(str(exc)) from exc
        db.session.add(
            AccountTransaction(
                type="withdraw",
                amount=amount,
                note=f"{'تحسين' if is_capitalized else 'صيانة'} أصل: {asset.asset_code}",
                treasury_account_id=treasury_id,
            )
        )

    old_book = _safe_int(asset.book_value)
    if is_capitalized:
        debit_account_id = asset.asset_account_id
        if not debit_account_id:
            raise FixedAssetError("حساب الأصل غير محدد")
        desc = f"تحسين رأسمالي — {asset.asset_code} - {asset.name}"
        movement_type = "improvement"
    else:
        maint_acc = Account.query.filter_by(code=FIXED_ASSET_GL["MAINTENANCE_EXPENSE"]).first()
        if not maint_acc:
            ensure_fixed_asset_gl_accounts()
            maint_acc = Account.query.filter_by(code=FIXED_ASSET_GL["MAINTENANCE_EXPENSE"]).first()
        debit_account_id = maint_acc.id if maint_acc else None
        if not debit_account_id:
            raise FixedAssetError("حساب مصروف الصيانة غير متوفر")
        desc = f"صيانة أصل — {asset.asset_code} - {asset.name}"
        movement_type = "maintenance"

    entry = _journal_by_ids(
        debit_account_id,
        pay_account_id,
        amount,
        desc,
        reference_type="fixed_asset_maintenance",
        reference_id=asset.id,
        created_by=user_id,
    )

    record = FixedAssetMaintenance(
        asset_id=asset.id,
        maintenance_date=maintenance_date,
        maintenance_type=mtype,
        supplier_id=_safe_int(data.get("supplier_id")) or None,
        amount=amount,
        payment_method=payment_method,
        treasury_account_id=treasury_id,
        is_capitalized=is_capitalized,
        journal_entry_id=entry.id if entry else None,
        description=(data.get("description") or "").strip() or None,
        created_by=user_id,
    )
    db.session.add(record)
    db.session.flush()

    new_book = old_book
    if is_capitalized:
        asset.total_cost = _safe_int(asset.total_cost) + amount
        new_book = old_book + amount
        asset.book_value = new_book
        if asset.is_depreciable and asset.useful_life_months:
            asset.monthly_depreciation = calculate_monthly_depreciation(
                asset.total_cost, asset.salvage_value, asset.useful_life_months
            )
        asset.updated_by = user_id
        asset.updated_at = datetime.utcnow()

    db.session.add(
        FixedAssetMovement(
            asset_id=asset.id,
            movement_type=movement_type,
            movement_date=maintenance_date,
            amount=amount,
            old_book_value=old_book,
            new_book_value=new_book,
            journal_entry_id=entry.id if entry else None,
            source_type="fixed_asset_maintenance",
            source_id=record.id,
            notes=record.description or desc,
            created_by=user_id,
        )
    )
    return record

