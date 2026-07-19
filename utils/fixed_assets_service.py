"""
خدمة الأصول الثابتة — المرحلة الأولى: اقتناء الأصل وقيد الشراء.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
import uuid

from extensions import db
from models.account import Account
from models.account_transaction import AccountTransaction
from models.fixed_asset import FixedAsset
from models.fixed_asset_category import FixedAssetCategory
from models.fixed_asset_movement import FixedAssetMovement
from models.fixed_asset_depreciation import FixedAssetDepreciation
from models.fixed_asset_maintenance import FixedAssetMaintenance
from models.fixed_asset_disposal import FixedAssetDisposal
from models.fixed_asset_settings import FixedAssetSettings, DEPRECIATION_START_MODES
from models.fixed_asset_disposal_request import FixedAssetDisposalRequest
from models.journal_entry import JournalEntry
from utils.fixed_assets_audit import asset_snapshot, log_fixed_asset_audit
from utils.financial_period_guard import (
    PeriodClosedError,
    assert_date_period_open,
    assert_period_open,
    close_financial_period,
    is_period_closed,
    list_closed_periods,
    reopen_financial_period,
)
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
    "GAIN_ON_SALE": "4202",
    "LOSS_ON_SALE": "6202",
    "LOSS_ON_SCRAP": "6203",
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


def _enforce_period_date(operation_date, action_label: str):
    settings = get_fixed_asset_settings()
    if not settings.enforce_period_close:
        return
    try:
        assert_date_period_open(operation_date, action_label)
    except PeriodClosedError as exc:
        raise FixedAssetError(str(exc)) from exc


def _enforce_period_ym(year: int, month: int, action_label: str):
    settings = get_fixed_asset_settings()
    if not settings.enforce_period_close:
        return
    try:
        assert_period_open(year, month, action_label)
    except PeriodClosedError as exc:
        raise FixedAssetError(str(exc)) from exc


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
    get_or_create_account(
        FIXED_ASSET_GL["GAIN_ON_SALE"],
        "أرباح بيع الأصول",
        "revenue",
        "إيراد أرباح بيع الأصول الثابتة",
    )
    get_or_create_account(
        FIXED_ASSET_GL["LOSS_ON_SALE"],
        "خسائر بيع الأصول",
        "expense",
        "مصروف خسائر بيع الأصول الثابتة",
    )
    get_or_create_account(
        FIXED_ASSET_GL["LOSS_ON_SCRAP"],
        "خسائر إتلاف الأصول",
        "expense",
        "مصروف خسائر إتلاف الأصول الثابتة",
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


def get_fixed_asset_settings() -> FixedAssetSettings:
    ensure_fixed_assets_schema()
    row = FixedAssetSettings.query.first()
    if not row:
        row = FixedAssetSettings(id=1)
        db.session.add(row)
        db.session.commit()
    return row


def save_fixed_asset_settings(data, user_id=None) -> FixedAssetSettings:
    settings = get_fixed_asset_settings()
    old = settings.to_dict()

    def _bool(key, default=None):
        if key in data:
            return str(data.get(key)).lower() in ("1", "true", "yes", "on")
        return default if default is not None else getattr(settings, key)

    settings.enabled = _bool("enabled")
    settings.auto_numbering = _bool("auto_numbering")
    settings.code_prefix = (data.get("code_prefix") or settings.code_prefix or "FA").strip()[:20] or "FA"
    settings.allow_code_edit = _bool("allow_code_edit")
    settings.prevent_delete_posted = _bool("prevent_delete_posted")
    settings.allow_without_invoice = _bool("allow_without_invoice")
    settings.require_invoice_attachment = _bool("require_invoice_attachment")
    settings.require_location = _bool("require_location")
    settings.require_responsible = _bool("require_responsible")
    settings.default_depreciation_method = (
        data.get("default_depreciation_method") or settings.default_depreciation_method or "straight_line"
    )
    mode = (data.get("depreciation_start_mode") or settings.depreciation_start_mode or "purchase").strip()
    settings.depreciation_start_mode = mode if mode in DEPRECIATION_START_MODES else "purchase"
    settings.allow_manual_depreciation = _bool("allow_manual_depreciation")
    settings.allow_batch_depreciation = _bool("allow_batch_depreciation")
    settings.prevent_duplicate_depreciation = _bool("prevent_duplicate_depreciation")
    settings.require_disposal_approval = _bool("require_disposal_approval")
    settings.enforce_period_close = _bool("enforce_period_close")
    settings.gain_on_sale_account_id = _safe_int(data.get("gain_on_sale_account_id")) or None
    settings.loss_on_sale_account_id = _safe_int(data.get("loss_on_sale_account_id")) or None
    settings.loss_on_scrap_account_id = _safe_int(data.get("loss_on_scrap_account_id")) or None
    settings.maintenance_expense_account_id = _safe_int(data.get("maintenance_expense_account_id")) or None
    settings.default_journal_description = (data.get("default_journal_description") or "").strip() or None
    settings.updated_at = datetime.utcnow()

    log_fixed_asset_audit(
        "settings_update",
        "fixed_asset_settings",
        entity_id=settings.id,
        old_values=old,
        new_values=settings.to_dict(),
        summary="تحديث إعدادات الأصول الثابتة",
        user_id=user_id,
    )
    return settings


def _account_from_settings_or_code(settings_attr, code_key):
    settings = get_fixed_asset_settings()
    account_id = getattr(settings, settings_attr, None)
    if account_id:
        from models.account import Account

        acc = Account.query.get(account_id)
        if acc:
            return acc
    return Account.query.filter_by(code=FIXED_ASSET_GL[code_key]).first()


def resolve_depreciation_start(mode, purchase_date, ready_date):
    """تاريخ بداية الاستهلاك حسب الإعدادات (دالة خالصة للاختبار)."""
    if mode == "ready":
        return ready_date or purchase_date
    if mode == "next_month":
        base = ready_date or purchase_date
        if base:
            if base.month == 12:
                return date(base.year + 1, 1, 1)
            return date(base.year, base.month + 1, 1)
        return None
    return purchase_date


def generate_asset_code():
    settings = get_fixed_asset_settings()
    prefix_base = (settings.code_prefix or "FA").strip().upper() or "FA"
    year = datetime.utcnow().year
    prefix = f"{prefix_base}-{year}-"
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
    settings = get_fixed_asset_settings()
    if not settings.enabled:
        raise FixedAssetError("نظام الأصول الثابتة معطّل من الإعدادات")

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

    asset_code = (data.get("asset_code") or "").strip()
    if not settings.allow_code_edit or not asset_code:
        asset_code = generate_asset_code()
    if FixedAsset.query.filter_by(asset_code=asset_code).first():
        raise FixedAssetError("كود الأصل مستخدم مسبقاً")

    location_text = (data.get("location_text") or "").strip() or None
    responsible_user_id = _safe_int(data.get("responsible_user_id")) or None
    if settings.require_location and not location_text:
        raise FixedAssetError("الموقع مطلوب حسب إعدادات الأصول")
    if settings.require_responsible and not responsible_user_id:
        raise FixedAssetError("المسؤول مطلوب حسب إعدادات الأصول")
    if settings.require_invoice_attachment and not (data.get("supplier_invoice_no") or "").strip():
        raise FixedAssetError("رقم فاتورة المورد مطلوب حسب الإعدادات")

    # عند الترحيل يجب أن تكون الحالة قابلة للترحيل (مسودة / تحت التركيب).
    # اختيار "نشط" من النموذج كان يمنع الترحيل ويلغي حفظ الأصل بالكامل.
    requested_status = (data.get("status") or "").strip()
    if requested_status == "under_installation":
        status = "under_installation"
    else:
        status = "draft"
    payment_method = (data.get("payment_method") or "cash").strip()
    paid_amount = _safe_int(data.get("paid_amount"))
    credit_amount = _safe_int(data.get("credit_amount"))

    if payment_method == "cash" or payment_method == "bank":
        paid_amount = total_cost
        credit_amount = 0
    elif payment_method == "credit":
        paid_amount = 0
        credit_amount = total_cost
    elif payment_method == "capital":
        paid_amount = 0
        credit_amount = 0
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
        location_text=location_text,
        responsible_user_id=responsible_user_id,
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
    log_fixed_asset_audit(
        "create",
        "fixed_asset",
        entity_id=asset.id,
        asset_id=asset.id,
        new_values=asset_snapshot(asset),
        summary=f"إنشاء أصل {asset.asset_code} — {asset.name}",
        user_id=user_id,
    )
    return asset


def delete_fixed_asset(asset: FixedAsset, user_id=None):
    """حذف أصل غير مُرحّل (مسودة أو بدون قيد شراء)."""
    ensure_fixed_assets_schema()
    settings = get_fixed_asset_settings()
    if asset.acquisition_journal_entry_id:
        if settings.prevent_delete_posted:
            raise FixedAssetError("لا يمكن حذف أصل مُرحّل محاسبياً")
        raise FixedAssetError("لا يمكن حذف أصل له قيد شراء — استخدم البيع أو الإتلاف")
    if asset.status not in ("draft", "under_installation"):
        raise FixedAssetError("يمكن حذف المسودات والأصول تحت التركيب غير المرحّلة فقط")

    from models.fixed_asset_audit_log import FixedAssetAuditLog
    from models.fixed_asset_attachment import FixedAssetAttachment
    from models.fixed_asset_disposal_request import FixedAssetDisposalRequest
    from models.fixed_asset_depreciation import FixedAssetDepreciation
    from models.fixed_asset_maintenance import FixedAssetMaintenance
    from utils.fixed_assets_attachments import delete_asset_attachment

    snapshot = asset_snapshot(asset)
    code = asset.asset_code
    name = asset.name
    asset_id = asset.id

    for att in FixedAssetAttachment.query.filter_by(asset_id=asset_id).all():
        delete_asset_attachment(att)

    FixedAssetMovement.query.filter_by(asset_id=asset_id).delete(synchronize_session=False)
    FixedAssetDepreciation.query.filter_by(asset_id=asset_id).delete(synchronize_session=False)
    FixedAssetMaintenance.query.filter_by(asset_id=asset_id).delete(synchronize_session=False)
    FixedAssetDisposalRequest.query.filter_by(asset_id=asset_id).delete(synchronize_session=False)
    FixedAssetDisposal.query.filter_by(asset_id=asset_id).delete(synchronize_session=False)
    FixedAssetAuditLog.query.filter_by(asset_id=asset_id).update(
        {"asset_id": None}, synchronize_session=False
    )

    db.session.delete(asset)
    db.session.flush()
    log_fixed_asset_audit(
        "delete",
        "fixed_asset",
        entity_id=asset_id,
        asset_id=None,
        old_values=snapshot,
        summary=f"حذف أصل {code} — {name}",
        user_id=user_id,
    )
    return code


def post_asset_acquisition(asset: FixedAsset, user_id=None):
    if asset.acquisition_journal_entry_id:
        raise FixedAssetError("تم ترحيل قيد شراء هذا الأصل مسبقاً")
    if asset.status in ("sold", "scrapped", "fully_depreciated"):
        raise FixedAssetError("لا يمكن ترحيل هذا الأصل في حالته الحالية")
    _enforce_period_date(asset.purchase_date or date.today(), "ترحيل شراء أصل")
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
    elif payment_method == "capital":
        paid = 0
        credit = 0
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

    if payment_method == "capital":
        capital_account = Account.query.filter_by(code=ACCOUNT_CODES["CAPITAL"]).first()
        if not capital_account:
            initialize_accounts()
            capital_account = Account.query.filter_by(code=ACCOUNT_CODES["CAPITAL"]).first()
        if not capital_account:
            raise FixedAssetError("حساب رأس المال غير متوفر")
        entry = _journal_by_ids(
            asset_account_id,
            capital_account.id,
            total,
            f"{desc_base} (إضافة مالك / رصيد افتتاحي)",
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

    log_fixed_asset_audit(
        "post_acquisition",
        "fixed_asset",
        entity_id=asset.id,
        asset_id=asset.id,
        old_values={"status": "draft"},
        new_values=asset_snapshot(asset),
        summary=f"ترحيل شراء الأصل {asset.asset_code}",
        user_id=user_id,
    )
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
    settings = get_fixed_asset_settings()
    return resolve_depreciation_start(
        settings.depreciation_start_mode or "purchase",
        asset.purchase_date,
        asset.ready_date,
    )


def _period_not_before_start(asset: FixedAsset, year: int, month: int) -> bool:
    start = _depreciation_start_date(asset)
    if not start:
        return True
    return (year, month) >= (start.year, start.month)


def _already_depreciated(asset: FixedAsset, year: int, month: int) -> bool:
    return FixedAssetDepreciation.query.filter_by(
        asset_id=asset.id, period_year=year, period_month=month
    ).first() is not None


def _depreciation_skip_reason(asset: FixedAsset, year: int, month: int) -> Optional[str]:
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
    settings = get_fixed_asset_settings()
    if not settings.allow_batch_depreciation:
        raise FixedAssetError("ترحيل الاستهلاك المجمع معطّل من الإعدادات")
    _enforce_period_ym(year, month, "ترحيل الاستهلاك")
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

    log_fixed_asset_audit(
        "post_depreciation",
        "fixed_asset_depreciation",
        new_values={
            "period": f"{year}-{month:02d}",
            "posted_count": len(posted_records),
            "total_amount": sum(r["amount"] for r in eligible),
            "journal_count": len(journal_map),
        },
        summary=f"ترحيل استهلاك {len(posted_records)} أصل للفترة {year}-{month:02d}",
        user_id=user_id,
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
    _enforce_period_date(maintenance_date, "تسجيل صيانة أصل")
    payment_method = (data.get("payment_method") or "cash").strip()
    treasury_id = resolve_treasury_account_id(data.get("treasury_account_id"))
    is_capitalized = mtype == "improvement"

    if payment_method in ("cash", "bank"):
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
        pay_account_id = _resolve_payment_accounts(payment_method, treasury_id)
    elif payment_method == "credit":
        ap_account = Account.query.filter_by(code=ACCOUNT_CODES["ACCOUNTS_PAYABLE"]).first()
        if not ap_account:
            initialize_accounts()
            ap_account = Account.query.filter_by(code=ACCOUNT_CODES["ACCOUNTS_PAYABLE"]).first()
        pay_account_id = ap_account.id if ap_account else None
        supplier_id = _safe_int(data.get("supplier_id"))
        if supplier_id:
            supplier = Supplier.query.get(supplier_id)
            if supplier:
                supplier.total_debt = _safe_int(supplier.total_debt) + amount
    else:
        pay_account_id = _resolve_payment_accounts(payment_method, treasury_id)

    if not pay_account_id:
        raise FixedAssetError("حساب الدفع غير متوفر")

    old_book = _safe_int(asset.book_value)
    if is_capitalized:
        debit_account_id = asset.asset_account_id
        if not debit_account_id:
            raise FixedAssetError("حساب الأصل غير محدد")
        desc = f"تحسين رأسمالي — {asset.asset_code} - {asset.name}"
        movement_type = "improvement"
    else:
        maint_acc = _account_from_settings_or_code("maintenance_expense_account_id", "MAINTENANCE_EXPENSE")
        if not maint_acc:
            ensure_fixed_asset_gl_accounts()
            maint_acc = _account_from_settings_or_code("maintenance_expense_account_id", "MAINTENANCE_EXPENSE")
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
    log_fixed_asset_audit(
        "capital_improvement" if is_capitalized else "maintenance",
        "fixed_asset_maintenance",
        entity_id=record.id,
        asset_id=asset.id,
        old_values={"book_value": old_book},
        new_values={"book_value": new_book, "amount": amount, "type": mtype},
        summary=f"{'تحسين رأسمالي' if is_capitalized else 'صيانة'} — {asset.asset_code}",
        user_id=user_id,
    )
    return record


# ─── المرحلة 4: بيع / إتلاف ───

def _get_receipt_account_id(payment_method, treasury_id=None):
    if payment_method == "credit":
        ap = Account.query.filter_by(code=ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"]).first()
        if not ap:
            initialize_accounts()
            ap = Account.query.filter_by(code=ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"]).first()
        return ap.id if ap else None
    return _resolve_payment_accounts(payment_method, treasury_id)


def _validate_disposable_asset(asset: FixedAsset):
    if asset.status in ("sold", "scrapped", "draft"):
        raise FixedAssetError("لا يمكن بيع أو إتلاف أصل في هذه الحالة")
    if not asset.acquisition_journal_entry_id:
        raise FixedAssetError("يجب ترحيل قيد شراء الأصل أولاً")
    if FixedAssetDisposal.query.filter_by(asset_id=asset.id).first():
        raise FixedAssetError("تم تسجيل بيع/إتلاف لهذا الأصل مسبقاً")
    pending = FixedAssetDisposalRequest.query.filter_by(
        asset_id=asset.id, status="pending"
    ).first()
    if pending:
        raise FixedAssetError("يوجد طلب بيع/إتلاف بانتظار الموافقة لهذا الأصل")


def post_asset_sale(data, user_id=None):
    ensure_fixed_assets_schema()
    ensure_fixed_asset_gl_accounts()

    asset = FixedAsset.query.get(_safe_int(data.get("asset_id")))
    if not asset:
        raise FixedAssetError("الأصل غير موجود")
    _validate_disposable_asset(asset)

    sale_amount = _safe_int(data.get("sale_amount"))
    if sale_amount < 0:
        raise FixedAssetError("سعر البيع غير صالح")

    disposal_date = _parse_date(data.get("disposal_date")) or date.today()
    _enforce_period_date(disposal_date, "بيع أصل")
    payment_method = (data.get("payment_method") or "cash").strip()
    treasury_id = resolve_treasury_account_id(data.get("treasury_account_id"))

    total_cost = _safe_int(asset.total_cost)
    accum = _safe_int(asset.accumulated_depreciation)
    book_value = _safe_int(asset.book_value)
    gain = max(sale_amount - book_value, 0)
    loss = max(book_value - sale_amount, 0)

    asset_account_id = asset.asset_account_id
    accum_account_id = asset.accumulated_depreciation_account_id
    if not asset_account_id or not accum_account_id:
        raise FixedAssetError("حسابات الأصل أو مجمع الاستهلاك غير مكتملة")

    receipt_account_id = _get_receipt_account_id(payment_method, treasury_id)
    if sale_amount > 0 and not receipt_account_id:
        raise FixedAssetError("حساب القبض غير متوفر")

    gain_acc = _account_from_settings_or_code("gain_on_sale_account_id", "GAIN_ON_SALE")
    loss_acc = _account_from_settings_or_code("loss_on_sale_account_id", "LOSS_ON_SALE")
    if not gain_acc or not loss_acc:
        ensure_fixed_asset_gl_accounts()
        gain_acc = _account_from_settings_or_code("gain_on_sale_account_id", "GAIN_ON_SALE")
        loss_acc = _account_from_settings_or_code("loss_on_sale_account_id", "LOSS_ON_SALE")

    desc_base = f"بيع أصل {asset.asset_code} - {asset.name}"
    first_entry = None

    if accum > 0:
        e1 = _journal_by_ids(
            accum_account_id,
            asset_account_id,
            accum,
            f"{desc_base} — إقفال مجمع الاستهلاك",
            reference_type="fixed_asset_sale",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or e1

    if gain > 0:
        if book_value > 0:
            e2 = _journal_by_ids(
                receipt_account_id,
                asset_account_id,
                book_value,
                f"{desc_base} — مقبوضات مقابل القيمة الدفترية",
                reference_type="fixed_asset_sale",
                reference_id=asset.id,
                created_by=user_id,
            )
            first_entry = first_entry or e2
        e3 = _journal_by_ids(
            receipt_account_id,
            gain_acc.id,
            gain,
            f"{desc_base} — ربح البيع",
            reference_type="fixed_asset_sale",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or e3
    elif loss > 0:
        if sale_amount > 0:
            e2 = _journal_by_ids(
                receipt_account_id,
                asset_account_id,
                sale_amount,
                f"{desc_base} — مقبوضات البيع",
                reference_type="fixed_asset_sale",
                reference_id=asset.id,
                created_by=user_id,
            )
            first_entry = first_entry or e2
        e4 = _journal_by_ids(
            loss_acc.id,
            asset_account_id,
            loss,
            f"{desc_base} — خسارة البيع",
            reference_type="fixed_asset_sale",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or e4
    elif book_value > 0 and sale_amount > 0:
        e2 = _journal_by_ids(
            receipt_account_id,
            asset_account_id,
            book_value,
            f"{desc_base} — بيع بسعر القيمة الدفترية",
            reference_type="fixed_asset_sale",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or e2

    if sale_amount > 0 and payment_method in ("cash", "bank"):
        db.session.add(
            AccountTransaction(
                type="deposit",
                amount=sale_amount,
                note=f"بيع أصل: {asset.asset_code}",
                treasury_account_id=treasury_id,
            )
        )

    disposal = FixedAssetDisposal(
        asset_id=asset.id,
        disposal_type="sale",
        disposal_date=disposal_date,
        sale_amount=sale_amount,
        payment_method=payment_method,
        treasury_account_id=treasury_id,
        buyer_name=(data.get("buyer_name") or "").strip() or None,
        cost_amount=total_cost,
        accumulated_depreciation_amount=accum,
        book_value=book_value,
        gain_amount=gain,
        loss_amount=loss,
        journal_entry_id=first_entry.id if first_entry else None,
        notes=(data.get("notes") or "").strip() or None,
        created_by=user_id,
    )
    db.session.add(disposal)
    db.session.flush()

    old_status = asset.status
    asset.status = "sold"
    asset.book_value = 0
    asset.is_depreciable = False
    asset.updated_by = user_id
    asset.updated_at = datetime.utcnow()

    db.session.add(
        FixedAssetMovement(
            asset_id=asset.id,
            movement_type="disposal",
            movement_date=disposal_date,
            amount=sale_amount,
            old_book_value=book_value,
            new_book_value=0,
            journal_entry_id=first_entry.id if first_entry else None,
            source_type="fixed_asset_disposal",
            source_id=disposal.id,
            notes=f"بيع — ربح {gain:,} / خسارة {loss:,}",
            created_by=user_id,
        )
    )
    log_fixed_asset_audit(
        "sale",
        "fixed_asset_disposal",
        entity_id=disposal.id,
        asset_id=asset.id,
        old_values={"status": old_status, "book_value": book_value},
        new_values={"status": "sold", "sale_amount": sale_amount, "gain": gain, "loss": loss},
        summary=f"بيع الأصل {asset.asset_code}",
        user_id=user_id,
    )
    return disposal


def post_asset_scrap(data, user_id=None):
    ensure_fixed_assets_schema()
    ensure_fixed_asset_gl_accounts()

    asset = FixedAsset.query.get(_safe_int(data.get("asset_id")))
    if not asset:
        raise FixedAssetError("الأصل غير موجود")
    _validate_disposable_asset(asset)

    disposal_date = _parse_date(data.get("disposal_date")) or date.today()
    _enforce_period_date(disposal_date, "إتلاف أصل")
    total_cost = _safe_int(asset.total_cost)
    accum = _safe_int(asset.accumulated_depreciation)
    book_value = _safe_int(asset.book_value)

    asset_account_id = asset.asset_account_id
    accum_account_id = asset.accumulated_depreciation_account_id
    if not asset_account_id:
        raise FixedAssetError("حساب الأصل غير محدد")

    scrap_loss_acc = _account_from_settings_or_code("loss_on_scrap_account_id", "LOSS_ON_SCRAP")
    if not scrap_loss_acc:
        ensure_fixed_asset_gl_accounts()
        scrap_loss_acc = _account_from_settings_or_code("loss_on_scrap_account_id", "LOSS_ON_SCRAP")

    desc = f"إتلاف أصل {asset.asset_code} - {asset.name}"
    first_entry = None

    if accum > 0 and accum_account_id:
        e1 = _journal_by_ids(
            accum_account_id,
            asset_account_id,
            accum,
            f"{desc} — إقفال مجمع الاستهلاك",
            reference_type="fixed_asset_scrap",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or e1

    if book_value > 0:
        e2 = _journal_by_ids(
            scrap_loss_acc.id,
            asset_account_id,
            book_value,
            f"{desc} — خسارة الإتلاف",
            reference_type="fixed_asset_scrap",
            reference_id=asset.id,
            created_by=user_id,
        )
        first_entry = first_entry or e2

    disposal = FixedAssetDisposal(
        asset_id=asset.id,
        disposal_type="scrap",
        disposal_date=disposal_date,
        sale_amount=0,
        cost_amount=total_cost,
        accumulated_depreciation_amount=accum,
        book_value=book_value,
        gain_amount=0,
        loss_amount=book_value,
        journal_entry_id=first_entry.id if first_entry else None,
        scrap_reason=(data.get("scrap_reason") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        created_by=user_id,
    )
    db.session.add(disposal)
    db.session.flush()

    old_status = asset.status
    asset.status = "scrapped"
    asset.book_value = 0
    asset.is_depreciable = False
    asset.updated_by = user_id
    asset.updated_at = datetime.utcnow()

    db.session.add(
        FixedAssetMovement(
            asset_id=asset.id,
            movement_type="scrap",
            movement_date=disposal_date,
            amount=book_value,
            old_book_value=book_value,
            new_book_value=0,
            journal_entry_id=first_entry.id if first_entry else None,
            source_type="fixed_asset_disposal",
            source_id=disposal.id,
            notes=disposal.scrap_reason or "إتلاف الأصل",
            created_by=user_id,
        )
    )
    log_fixed_asset_audit(
        "scrap",
        "fixed_asset_disposal",
        entity_id=disposal.id,
        asset_id=asset.id,
        old_values={"status": old_status, "book_value": book_value},
        new_values={"status": "scrapped", "loss": book_value},
        summary=f"إتلاف الأصل {asset.asset_code}",
        user_id=user_id,
    )
    return disposal


# ─── نقل الأصول (بدون قيد إلا عند وجود تكلفة) ───

def post_asset_transfer(data, user_id=None):
    ensure_fixed_assets_schema()
    asset = FixedAsset.query.get(_safe_int(data.get("asset_id")))
    if not asset:
        raise FixedAssetError("الأصل غير موجود")
    if asset.status in ("sold", "scrapped", "draft"):
        raise FixedAssetError("لا يمكن نقل أصل في هذه الحالة")

    transfer_date = _parse_date(data.get("transfer_date")) or date.today()
    _enforce_period_date(transfer_date, "نقل أصل")
    old_location = asset.location_text or "—"
    new_location = (data.get("new_location") or "").strip()
    new_branch_id = _safe_int(data.get("new_branch_id")) or None
    new_responsible_id = _safe_int(data.get("new_responsible_user_id")) or None
    transfer_cost = _safe_int(data.get("transfer_cost"))

    if new_location:
        asset.location_text = new_location
    if new_branch_id:
        asset.branch_id = new_branch_id
    if new_responsible_id:
        asset.responsible_user_id = new_responsible_id
    asset.updated_by = user_id
    asset.updated_at = datetime.utcnow()

    entry = None
    if transfer_cost > 0:
        maint = post_asset_maintenance(
            {
                "asset_id": asset.id,
                "maintenance_type": "regular",
                "maintenance_date": transfer_date.isoformat(),
                "amount": transfer_cost,
                "payment_method": data.get("payment_method") or "cash",
                "treasury_account_id": data.get("treasury_account_id"),
                "description": f"أجور نقل أصل {asset.asset_code}",
            },
            user_id=user_id,
        )
        entry = maint.journal_entry

    db.session.add(
        FixedAssetMovement(
            asset_id=asset.id,
            movement_type="transfer",
            movement_date=transfer_date,
            amount=transfer_cost,
            old_book_value=_safe_int(asset.book_value),
            new_book_value=_safe_int(asset.book_value),
            journal_entry_id=entry.id if entry else None,
            source_type="fixed_asset_transfer",
            source_id=asset.id,
            notes=f"نقل من {old_location} إلى {new_location or '—'} — {(data.get('reason') or '')}",
            created_by=user_id,
        )
    )
    log_fixed_asset_audit(
        "transfer",
        "fixed_asset",
        entity_id=asset.id,
        asset_id=asset.id,
        old_values={"location": old_location},
        new_values={"location": new_location or asset.location_text, "branch_id": new_branch_id},
        summary=f"نقل الأصل {asset.asset_code}",
        user_id=user_id,
    )
    return asset


# ─── المرحلة 5: تقارير الأصول ───

def build_asset_reports(report_type="register", year_from=None, month_from=None, year_to=None, month_to=None):
    assets = FixedAsset.query.order_by(FixedAsset.asset_code).all()

    if report_type == "register":
        return {
            "title": "سجل الأصول",
            "rows": [
                {
                    "code": a.asset_code,
                    "name": a.name,
                    "category": a.category.name if a.category else "—",
                    "total_cost": _safe_int(a.total_cost),
                    "accumulated": _safe_int(a.accumulated_depreciation),
                    "book_value": _safe_int(a.book_value),
                    "status": a.status_label(),
                    "location": a.location_text or "—",
                    "responsible": a.responsible_user.name if a.responsible_user else "—",
                }
                for a in assets
            ],
        }

    if report_type == "by_category":
        from collections import defaultdict
        groups = defaultdict(lambda: {"count": 0, "cost": 0, "accum": 0, "book": 0, "name": ""})
        for a in assets:
            if a.status in ("sold", "scrapped"):
                continue
            key = a.category_id or 0
            g = groups[key]
            g["name"] = a.category.name if a.category else "غير مصنف"
            g["count"] += 1
            g["cost"] += _safe_int(a.total_cost)
            g["accum"] += _safe_int(a.accumulated_depreciation)
            g["book"] += _safe_int(a.book_value)
        return {"title": "الأصول حسب التصنيف", "rows": list(groups.values())}

    if report_type == "by_location":
        from collections import defaultdict
        groups = defaultdict(lambda: {"count": 0, "cost": 0, "book": 0, "location": ""})
        for a in assets:
            if a.status in ("sold", "scrapped"):
                continue
            loc = a.location_text or "بدون موقع"
            g = groups[loc]
            g["location"] = loc
            g["count"] += 1
            g["cost"] += _safe_int(a.total_cost)
            g["book"] += _safe_int(a.book_value)
        return {"title": "الأصول حسب الموقع", "rows": list(groups.values())}

    if report_type == "sold":
        disposals = FixedAssetDisposal.query.filter_by(disposal_type="sale").order_by(
            FixedAssetDisposal.disposal_date.desc()
        ).all()
        return {
            "title": "الأصول المباعة",
            "rows": [
                {
                    "asset": d.asset.asset_code if d.asset else d.asset_id,
                    "name": d.asset.name if d.asset else "—",
                    "date": d.disposal_date,
                    "sale_amount": d.sale_amount,
                    "book_value": d.book_value,
                    "gain": d.gain_amount,
                    "loss": d.loss_amount,
                }
                for d in disposals
            ],
        }

    if report_type == "scrapped":
        disposals = FixedAssetDisposal.query.filter_by(disposal_type="scrap").order_by(
            FixedAssetDisposal.disposal_date.desc()
        ).all()
        return {
            "title": "الأصول التالفة",
            "rows": [
                {
                    "asset": d.asset.asset_code if d.asset else d.asset_id,
                    "name": d.asset.name if d.asset else "—",
                    "date": d.disposal_date,
                    "cost": d.cost_amount,
                    "accumulated": d.accumulated_depreciation_amount,
                    "loss": d.loss_amount,
                    "reason": d.scrap_reason or "—",
                }
                for d in disposals
            ],
        }

    if report_type == "depreciation":
        q = FixedAssetDepreciation.query
        if year_from and month_from:
            q = q.filter(
                db.or_(
                    FixedAssetDepreciation.period_year > year_from,
                    db.and_(
                        FixedAssetDepreciation.period_year == year_from,
                        FixedAssetDepreciation.period_month >= month_from,
                    ),
                )
            )
        if year_to and month_to:
            q = q.filter(
                db.or_(
                    FixedAssetDepreciation.period_year < year_to,
                    db.and_(
                        FixedAssetDepreciation.period_year == year_to,
                        FixedAssetDepreciation.period_month <= month_to,
                    ),
                )
            )
        deps = q.order_by(
            FixedAssetDepreciation.period_year.desc(),
            FixedAssetDepreciation.period_month.desc(),
        ).all()
        return {
            "title": "تقرير الاستهلاك",
            "rows": [
                {
                    "period": f"{d.period_year}-{d.period_month:02d}",
                    "asset": d.asset.asset_code if d.asset else d.asset_id,
                    "name": d.asset.name if d.asset else "—",
                    "amount": d.depreciation_amount,
                    "journal_id": d.journal_entry_id,
                }
                for d in deps
            ],
        }

    if report_type == "review":
        issues = []
        for a in assets:
            if a.status in ("sold", "scrapped"):
                continue
            if not a.asset_account_id:
                issues.append({"asset": a.asset_code, "issue": "بدون حساب أصل"})
            if a.is_depreciable and not a.accumulated_depreciation_account_id:
                issues.append({"asset": a.asset_code, "issue": "بدون حساب مجمع استهلاك"})
            if not a.location_text:
                issues.append({"asset": a.asset_code, "issue": "بدون موقع"})
            if not a.responsible_user_id:
                issues.append({"asset": a.asset_code, "issue": "بدون مسؤول"})
            if a.total_cost <= 0 and a.status != "draft":
                issues.append({"asset": a.asset_code, "issue": "تكلفة صفر"})
            if _safe_int(a.accumulated_depreciation) > _safe_int(a.total_cost):
                issues.append({"asset": a.asset_code, "issue": "مجمع استهلاك أكبر من التكلفة"})
        return {"title": "أصول تحتاج مراجعة", "rows": issues}

    return {"title": "تقرير", "rows": []}


# ─── طلبات موافقة البيع / الإتلاف ───

def _disposal_form_to_dict(data) -> dict:
    return {
        "asset_id": _safe_int(data.get("asset_id")),
        "disposal_date": (_parse_date(data.get("disposal_date")) or date.today()).isoformat(),
        "sale_amount": _safe_int(data.get("sale_amount")),
        "payment_method": (data.get("payment_method") or "cash").strip(),
        "treasury_account_id": data.get("treasury_account_id"),
        "buyer_name": (data.get("buyer_name") or "").strip() or None,
        "scrap_reason": (data.get("scrap_reason") or "").strip() or None,
        "notes": (data.get("notes") or "").strip() or None,
    }


def create_disposal_request(data, user_id=None, disposal_type="sale"):
    ensure_fixed_assets_schema()
    asset = FixedAsset.query.get(_safe_int(data.get("asset_id")))
    if not asset:
        raise FixedAssetError("الأصل غير موجود")
    _validate_disposable_asset(asset)

    disposal_date = _parse_date(data.get("disposal_date")) or date.today()
    _enforce_period_date(disposal_date, "طلب بيع/إتلاف أصل")

    if disposal_type == "scrap" and not (data.get("scrap_reason") or "").strip():
        raise FixedAssetError("سبب الإتلاف مطلوب")

    req = FixedAssetDisposalRequest(
        asset_id=asset.id,
        disposal_type=disposal_type,
        status="pending",
        disposal_date=disposal_date,
        sale_amount=_safe_int(data.get("sale_amount")),
        payment_method=(data.get("payment_method") or "cash").strip(),
        treasury_account_id=_safe_int(data.get("treasury_account_id")) or None,
        buyer_name=(data.get("buyer_name") or "").strip() or None,
        scrap_reason=(data.get("scrap_reason") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        requested_by=user_id,
    )
    db.session.add(req)
    db.session.flush()
    log_fixed_asset_audit(
        "disposal_request",
        "fixed_asset_disposal_request",
        entity_id=req.id,
        asset_id=asset.id,
        new_values={"type": disposal_type, "status": "pending"},
        summary=f"طلب {req.type_label()} للأصل {asset.asset_code} بانتظار الموافقة",
        user_id=user_id,
    )
    return req


def submit_disposal_or_request(data, user_id=None):
    """يرسل طلب موافقة أو ينفّذ مباشرة حسب الإعدادات."""
    action = (data.get("action") or "sale").strip()
    disposal_type = "scrap" if action == "scrap" else "sale"
    settings = get_fixed_asset_settings()
    if settings.require_disposal_approval:
        return create_disposal_request(data, user_id=user_id, disposal_type=disposal_type)
    if disposal_type == "scrap":
        return post_asset_scrap(data, user_id=user_id)
    return post_asset_sale(data, user_id=user_id)


def approve_disposal_request(request_id: int, user_id=None):
    req = FixedAssetDisposalRequest.query.get(request_id)
    if not req:
        raise FixedAssetError("الطلب غير موجود")
    if req.status != "pending":
        raise FixedAssetError("الطلب ليس بانتظار الموافقة")

    payload = {
        "asset_id": req.asset_id,
        "disposal_date": req.disposal_date.isoformat() if req.disposal_date else None,
        "sale_amount": req.sale_amount,
        "payment_method": req.payment_method,
        "treasury_account_id": req.treasury_account_id,
        "buyer_name": req.buyer_name,
        "scrap_reason": req.scrap_reason,
        "notes": req.notes,
        "action": req.disposal_type,
    }
    if req.disposal_type == "scrap":
        disposal = post_asset_scrap(payload, user_id=user_id)
    else:
        disposal = post_asset_sale(payload, user_id=user_id)

    req.status = "completed"
    req.approved_by = user_id
    req.approved_at = datetime.utcnow()
    req.completed_disposal_id = disposal.id
    log_fixed_asset_audit(
        "disposal_approved",
        "fixed_asset_disposal_request",
        entity_id=req.id,
        asset_id=req.asset_id,
        old_values={"status": "pending"},
        new_values={"status": "completed", "disposal_id": disposal.id},
        summary=f"موافقة على {req.type_label()} للأصل {req.asset.asset_code if req.asset else req.asset_id}",
        user_id=user_id,
    )
    return disposal


def reject_disposal_request(request_id: int, user_id=None, reason: str = ""):
    req = FixedAssetDisposalRequest.query.get(request_id)
    if not req:
        raise FixedAssetError("الطلب غير موجود")
    if req.status != "pending":
        raise FixedAssetError("الطلب ليس بانتظار الموافقة")
    req.status = "rejected"
    req.approved_by = user_id
    req.approved_at = datetime.utcnow()
    req.rejection_reason = (reason or "").strip() or "مرفوض"
    log_fixed_asset_audit(
        "disposal_rejected",
        "fixed_asset_disposal_request",
        entity_id=req.id,
        asset_id=req.asset_id,
        old_values={"status": "pending"},
        new_values={"status": "rejected", "reason": req.rejection_reason},
        summary=f"رفض طلب {req.type_label()} للأصل {req.asset.asset_code if req.asset else req.asset_id}",
        user_id=user_id,
    )
    return req


def list_pending_disposal_requests():
    return (
        FixedAssetDisposalRequest.query.filter_by(status="pending")
        .order_by(FixedAssetDisposalRequest.created_at.desc())
        .all()
    )


# ─── إغلاق الفترات المحاسبية ───

def close_accounting_period(year: int, month: int, user_id=None, notes: str | None = None):
    settings = get_fixed_asset_settings()
    if not settings.enforce_period_close:
        raise FixedAssetError("التحقق من الإغلاق المحاسبي معطّل من الإعدادات")
    try:
        row = close_financial_period(year, month, user_id=user_id, notes=notes)
    except PeriodClosedError as exc:
        raise FixedAssetError(str(exc)) from exc
    log_fixed_asset_audit(
        "period_close",
        "financial_period",
        entity_id=row.id,
        new_values={"year": year, "month": month},
        summary=f"إغلاق الفترة المحاسبية {year}-{month:02d}",
        user_id=user_id,
    )
    return row


def reopen_accounting_period(year: int, month: int, user_id=None):
    try:
        reopen_financial_period(year, month)
    except PeriodClosedError as exc:
        raise FixedAssetError(str(exc)) from exc
    log_fixed_asset_audit(
        "period_reopen",
        "financial_period",
        new_values={"year": year, "month": month},
        summary=f"إعادة فتح الفترة المحاسبية {year}-{month:02d}",
        user_id=user_id,
    )
    return True

