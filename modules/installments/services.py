from __future__ import annotations

import hashlib
import json
import re
import secrets
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.exc import IntegrityError

from flask import current_app, session

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.journal_entry import JournalEntry
from models.order_item import OrderItem
from models.product import Product
from utils.branch_migration import get_default_branch
from utils.order_stock_lock import apply_stock_actions, check_stock_rows
from modules.installments.models import (
    InstallmentApplication,
    InstallmentApplicationActivity,
    InstallmentApplicationItem,
    InstallmentContract,
    InstallmentContractItem,
    InstallmentPayment,
    InstallmentPaymentAllocation,
    InstallmentPlan,
    InstallmentProduct,
    InstallmentSchedule,
    InstallmentSettings,
)


class InstallmentError(ValueError):
    pass


def _installment_treasury_account_id(invoice: Invoice, payment_method: str) -> int | None:
    """Map installment collection methods to the operational treasury ledger."""
    method = str(payment_method or "cash").strip().lower()
    branch_id = getattr(invoice, "branch_id", None)
    if method in {"bank", "card", "بنك", "بطاقة"}:
        from models.treasury_account import TreasuryAccount

        query = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
            account_type="bank", is_active=True
        )
        if branch_id:
            query = query.filter(TreasuryAccount.branch_id == int(branch_id))
        account = query.order_by(TreasuryAccount.id.asc()).first()
        if not account:
            raise InstallmentError("لا يوجد حساب بنكي فعال لتسجيل دفعة الأقساط")
        return int(account.id)
    # NULL is the ledger's explicit backwards-compatible marker for the
    # default cash account of the invoice branch.  Avoid creating/committing a
    # cash account inside the caller's still-open installment transaction.
    return None


def append_installment_ledger_delta(
    invoice: Invoice,
    delta: int,
    *,
    payment_method: str = "cash",
    recorded_at: datetime | None = None,
    note: str | None = None,
) -> None:
    """Write an installment collection in the caller's existing transaction."""
    delta = int(delta or 0)
    if delta == 0:
        return
    db.session.add(
        InvoicePaymentLedger(
            branch_id=getattr(invoice, "branch_id", None),
            tenant_id=getattr(invoice, "tenant_id", None),
            invoice_id=int(invoice.id),
            amount_delta=delta,
            treasury_account_id=_installment_treasury_account_id(invoice, payment_method),
            recorded_at=recorded_at or datetime.utcnow(),
            source_module="installments",
            payment_method=payment_method,
            note=note,
        )
    )


def allowed_installment_durations(settings: InstallmentSettings | None) -> set[int]:
    """Return the configured month choices; an empty set means no restriction."""
    if not settings:
        return set()
    try:
        values = json.loads(settings.allowed_durations_json or "[]")
        return {int(value) for value in values if 1 <= int(value) <= 120}
    except (ValueError, TypeError, json.JSONDecodeError):
        return set()


def synchronize_allowed_duration_plans(
    tenant_id: int,
    durations,
    installment_product_id: int | None = None,
) -> tuple[int, int]:
    """Create missing duration variants and disable active plans outside the configured list."""
    allowed = sorted({int(value) for value in durations if 1 <= int(value) <= 120})
    if not allowed:
        return 0, 0

    product_query = InstallmentProduct.query.filter_by(tenant_id=tenant_id)
    if installment_product_id is not None:
        product_query = product_query.filter_by(id=installment_product_id)

    created = 0
    deactivated = 0
    for item in product_query.all():
        plans = (
            InstallmentPlan.query.filter_by(
                tenant_id=tenant_id,
                installment_product_id=item.id,
            )
            .order_by(InstallmentPlan.active.desc(), InstallmentPlan.sort_order, InstallmentPlan.months)
            .all()
        )
        if not plans:
            continue

        template = plans[0]
        existing_months = {plan.months for plan in plans}
        for plan in plans:
            if plan.active and plan.months not in allowed:
                plan.active = False
                deactivated += 1

        for months in allowed:
            if months in existing_months:
                continue

            pricing_mode = template.pricing_mode
            fixed_total_price = template.fixed_total_price
            fixed_monthly_amount = template.fixed_monthly_amount
            if pricing_mode == "fixed_monthly":
                pricing_mode = "fixed_total"
                fixed_total_price = money(template.fixed_monthly_amount) * template.months
                fixed_monthly_amount = None

            variant = InstallmentPlan(
                tenant_id=tenant_id,
                installment_product_id=item.id,
                months=months,
                pricing_mode=pricing_mode,
                markup_percentage=template.markup_percentage,
                fixed_total_price=fixed_total_price,
                fixed_monthly_amount=fixed_monthly_amount,
                down_payment_type=template.down_payment_type,
                down_payment_value=template.down_payment_value,
                processing_fee=template.processing_fee,
                active=True,
                sort_order=months,
            )
            InstallmentCalculationService.calculate(item.cash_price, variant)
            db.session.add(variant)
            existing_months.add(months)
            created += 1

    return created, deactivated


IRAQI_GOVERNORATES = (
    "بغداد", "البصرة", "نينوى", "أربيل", "النجف", "كربلاء", "كركوك",
    "السليمانية", "دهوك", "الأنبار", "بابل", "ديالى", "ذي قار", "صلاح الدين",
    "واسط", "ميسان", "المثنى", "القادسية", "حلبجة",
)


def money(value) -> int:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise InstallmentError("المبلغ غير صالح") from exc
    if not amount.is_finite():
        raise InstallmentError("المبلغ غير صالح")
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tenant_id_for_product(product: Product) -> int:
    tenant_id = getattr(product, "tenant_id", None) or session.get("tenant_id")
    if tenant_id:
        return int(tenant_id)
    from models.tenant import Tenant

    tenant = Tenant.query.order_by(Tenant.id.asc()).first()
    if not tenant:
        raise InstallmentError("تعذر تحديد ملكية المستأجر للمنتج")
    return int(tenant.id)


@dataclass(frozen=True)
class CalculationResult:
    cash_price: int
    installment_total: int
    markup_amount: int
    fees: int
    down_payment: int
    financed_amount: int
    number_of_payments: int
    monthly_payment: int
    final_payment: int
    schedule: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


class InstallmentCalculationService:
    """Single authoritative calculator. All values are integer IQD amounts."""

    @classmethod
    def calculate(cls, cash_price, plan: InstallmentPlan | dict, quantity: int = 1) -> CalculationResult:
        quantity = int(quantity or 0)
        if quantity < 1 or quantity > 999:
            raise InstallmentError("الكمية غير صالحة")
        base = money(cash_price) * quantity
        if base < 0:
            raise InstallmentError("السعر النقدي غير صالح")

        get = (lambda key, default=None: plan.get(key, default)) if isinstance(plan, dict) else (lambda key, default=None: getattr(plan, key, default))
        months = int(get("months", 0) or 0)
        if months < 1 or months > 120:
            raise InstallmentError("مدة الخطة غير صالحة")
        mode = str(get("pricing_mode", ""))
        fee = money(get("processing_fee", 0) or 0) * quantity

        if mode == "percentage":
            percentage = Decimal(str(get("markup_percentage", 0) or 0))
            if percentage < 0 or percentage > 1000:
                raise InstallmentError("نسبة الزيادة غير صالحة")
            total_before_fee = money(Decimal(base) * (Decimal("1") + percentage / Decimal("100")))
        elif mode == "fixed_total":
            total_before_fee = money(get("fixed_total_price", 0)) * quantity
        elif mode == "fixed_monthly":
            total_before_fee = money(get("fixed_monthly_amount", 0)) * months * quantity
        else:
            raise InstallmentError("طريقة التسعير غير مدعومة")
        if total_before_fee < base:
            raise InstallmentError("إجمالي التقسيط لا يمكن أن يقل عن السعر النقدي")

        installment_total = total_before_fee + fee
        down_type = str(get("down_payment_type", "none") or "none")
        down_value = Decimal(str(get("down_payment_value", 0) or 0))
        if down_type == "none":
            down = 0
        elif down_type == "fixed":
            down = money(down_value) * quantity
        elif down_type == "percentage":
            if down_value < 0 or down_value > 100:
                raise InstallmentError("نسبة الدفعة الأولى غير صالحة")
            down = money(Decimal(installment_total) * down_value / Decimal("100"))
        else:
            raise InstallmentError("نوع الدفعة الأولى غير مدعوم")
        if down < 0 or down > installment_total:
            raise InstallmentError("الدفعة الأولى غير صالحة")

        financed = installment_total - down
        regular = financed // months
        remainder = financed - regular * months
        amounts = [regular] * months
        amounts[-1] += remainder
        if financed and regular == 0:
            raise InstallmentError("مدة الخطة أكبر من المبلغ الممول")
        schedule = [
            {"sequence": index + 1, "amount": amount, "type": "final" if index == months - 1 else "installment"}
            for index, amount in enumerate(amounts)
        ]
        if down + sum(item["amount"] for item in schedule) != installment_total:
            raise InstallmentError("تعذر موازنة جدول الأقساط")
        return CalculationResult(
            cash_price=base,
            installment_total=installment_total,
            markup_amount=total_before_fee - base,
            fees=fee,
            down_payment=down,
            financed_amount=financed,
            number_of_payments=months,
            monthly_payment=regular,
            final_payment=amounts[-1],
            schedule=schedule,
        )


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("00964"):
        digits = digits[5:]
    elif digits.startswith("964"):
        digits = digits[3:]
    if digits.startswith("7") and len(digits) == 10:
        digits = "0" + digits
    if len(digits) < 8 or len(digits) > 15:
        raise InstallmentError("رقم الهاتف غير صالح")
    return digits


def phone_candidates(value: str) -> set[str]:
    canonical = normalize_phone(value)
    candidates = {canonical}
    if canonical.startswith("07") and len(canonical) == 11:
        candidates.update({"964" + canonical[1:], "+964" + canonical[1:], "00964" + canonical[1:]})
    return candidates


def find_customer_by_phone(tenant_id: int, value: str) -> Customer | None:
    digit_candidates = {re.sub(r"\D+", "", candidate) for candidate in phone_candidates(value)}
    stripped = Customer.phone
    for character in (" ", "-", "(", ")", "+"):
        stripped = db.func.replace(stripped, character, "")
    return Customer.query.filter(Customer.tenant_id == tenant_id, stripped.in_(digit_candidates)).first()


def next_application_number(tenant_id: int, year: int | None = None) -> str:
    year = year or datetime.utcnow().year
    prefix = f"INS-{year}-"
    latest = (
        InstallmentApplication.query
        .filter(InstallmentApplication.tenant_id == tenant_id, InstallmentApplication.application_number.like(f"{prefix}%"))
        .order_by(InstallmentApplication.application_number.desc())
        .first()
    )
    try:
        sequence = int(latest.application_number.rsplit("-", 1)[-1]) + 1 if latest else 1
    except (TypeError, ValueError):
        sequence = 1
    return f"{prefix}{sequence:06d}"


APPLICATION_TRANSITIONS = {
    "new": {"under_review", "cancelled"},
    "under_review": {"documents_required", "waiting_approval", "approved", "rejected", "cancelled"},
    "documents_required": {"under_review", "waiting_approval", "cancelled"},
    "waiting_approval": {"approved", "rejected", "cancelled"},
    "approved": {"contract_pending", "cancelled"},
    "contract_pending": {"contract_signed", "cancelled"},
    "contract_signed": {"ready_for_fulfillment", "cancelled"},
    "ready_for_fulfillment": {"delivered", "cancelled"},
    "delivered": {"active"},
    "active": {"completed"},
    "rejected": set(),
    "cancelled": set(),
    "completed": set(),
}


def validate_application_transition(current: str, target: str) -> None:
    if target not in APPLICATION_TRANSITIONS.get(current, set()):
        raise InstallmentError("انتقال حالة طلب التقسيط غير مسموح")


class ApplicationService:
    @classmethod
    def create(cls, installment_product: InstallmentProduct, plan: InstallmentPlan, form: dict, idempotency_key: str) -> tuple[InstallmentApplication, str]:
        return cls.create_many([(installment_product, plan, int(form.get("quantity") or 1))], form, idempotency_key)

    @classmethod
    def create_many(cls, selections: list[tuple[InstallmentProduct, InstallmentPlan, int]], form: dict, idempotency_key: str) -> tuple[InstallmentApplication, str]:
        if not selections or len(selections) > 25:
            raise InstallmentError("سلة الأقساط فارغة أو تتجاوز الحد المسموح")
        tenant_id = selections[0][0].tenant_id
        settings = InstallmentSettings.query.filter_by(tenant_id=tenant_id).first()
        allowed_durations = allowed_installment_durations(settings)
        calculated: list[tuple[InstallmentProduct, InstallmentPlan, Product, int, CalculationResult]] = []
        for installment_product, plan, raw_quantity in selections:
            if installment_product.tenant_id != tenant_id or plan.tenant_id != tenant_id:
                raise InstallmentError("تحتوي السلة على بيانات مستأجر آخر")
            if installment_product.status != "published" or not plan.active:
                raise InstallmentError("أحد المنتجات أو الخطط غير متاح حاليًا")
            product = installment_product.product
            quantity = max(1, min(int(raw_quantity or 1), 99))
            if not product or not product.active:
                raise InstallmentError("أحد المنتجات غير متوفر حاليًا")
            if plan.installment_product_id != installment_product.id:
                raise InstallmentError("إحدى الخطط لا تخص المنتج المحدد")
            if allowed_durations and plan.months not in allowed_durations:
                raise InstallmentError("مدة إحدى الخطط غير مسموحة في إعدادات المتجر")
            calculation = InstallmentCalculationService.calculate(installment_product.cash_price, plan, quantity)
            minimum_down = Decimal(str(settings.minimum_down_payment_percentage or 0)) if settings else Decimal("0")
            actual_down = (Decimal(calculation.down_payment) * 100 / Decimal(calculation.installment_total)) if calculation.installment_total else Decimal("0")
            if actual_down < minimum_down:
                raise InstallmentError("الدفعة الأولى أقل من الحد الأدنى المسموح")
            calculated.append((installment_product, plan, product, quantity, calculation))
        key = str(idempotency_key or "").strip()[:80]
        if len(key) < 12:
            raise InstallmentError("مفتاح منع التكرار غير صالح")
        existing = InstallmentApplication.query.filter_by(tenant_id=tenant_id, idempotency_key=key).first()
        if existing:
            return existing, ""

        name = str(form.get("customer_name") or "").strip()
        phone = normalize_phone(form.get("phone"))
        city = str(form.get("city") or "").strip()
        address = str(form.get("address") or "").strip()
        if len(name.split()) < 4:
            raise InstallmentError("يرجى إدخال الاسم الرباعي كاملاً")
        if city not in IRAQI_GOVERNORATES or len(address) < 5:
            raise InstallmentError("يرجى اختيار محافظة عراقية وإدخال العنوان بصورة صحيحة")
        phone2 = str(form.get("phone2") or "").strip()
        if phone2:
            phone2 = normalize_phone(phone2)
        if settings and settings.second_phone_required and not phone2:
            raise InstallmentError("رقم الهاتف الثاني مطلوب")
        if settings and settings.employment_required and not str(form.get("employer") or "").strip():
            raise InstallmentError("جهة العمل مطلوبة")
        token = secrets.token_urlsafe(32)
        application = InstallmentApplication(
            tenant_id=tenant_id,
            application_number=next_application_number(tenant_id),
            idempotency_key=key,
            tracking_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            customer_name=name[:150],
            phone=phone,
            phone2=phone2[:30] or None,
            city=city[:100],
            area=str(form.get("area") or "").strip()[:150] or None,
            address=address[:300],
            nearest_landmark=str(form.get("nearest_landmark") or "").strip()[:250] or None,
            employer=str(form.get("employer") or "").strip()[:200] or None,
            monthly_income=money(form.get("monthly_income") or 0) or None,
            notes=str(form.get("notes") or "").strip()[:4000] or None,
            status="new",
        )
        forced_customer_id = form.get("_customer_id")
        matched_customer = None
        if forced_customer_id:
            try:
                matched_customer = Customer.query.filter_by(id=int(forced_customer_id), tenant_id=tenant_id).first()
            except (TypeError, ValueError):
                matched_customer = None
            if not matched_customer:
                raise InstallmentError("حساب الزبون غير صالح لهذا المتجر")
        if not matched_customer:
            matched_customer = find_customer_by_phone(tenant_id, phone)
        if not matched_customer:
            matched_customer = Customer(tenant_id=tenant_id, name=name[:150], phone=phone)
            db.session.add(matched_customer)

        # Keep the central customer record current as soon as the request is
        # submitted, so the Customers page and the storefront share one profile.
        matched_customer.name = name[:150]
        matched_customer.phone = phone
        matched_customer.phone2 = phone2[:20] or None
        matched_customer.city = city[:100]
        matched_customer.address = address[:255]
        db.session.flush()
        application.customer_id = matched_customer.id
        db.session.add(application)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            duplicate = InstallmentApplication.query.filter_by(tenant_id=tenant_id, idempotency_key=key).first()
            if duplicate:
                return duplicate, ""
            raise InstallmentError("تعذر حجز رقم الطلب؛ يرجى إعادة المحاولة")
        for installment_product, plan, product, quantity, calculation in calculated:
            main_media = next((media for media in installment_product.media if media.is_main), None)
            db.session.add(InstallmentApplicationItem(
                tenant_id=tenant_id,
                application_id=application.id,
                installment_product_id=installment_product.id,
                product_id=product.id,
                plan_id=plan.id,
                quantity=quantity,
                product_name_snapshot=product.name,
                sku_snapshot=product.sku,
                main_image_snapshot=main_media.file_path if main_media else product.image_url,
                months_snapshot=plan.months,
                pricing_mode_snapshot=plan.pricing_mode,
                markup_snapshot=plan.markup_percentage,
                cash_price=calculation.cash_price,
                installment_total=calculation.installment_total,
                down_payment=calculation.down_payment,
                financed_amount=calculation.financed_amount,
                monthly_payment=calculation.monthly_payment,
                final_payment=calculation.final_payment,
                processing_fee=calculation.fees,
                calculation_json=json.dumps(calculation.to_dict(), ensure_ascii=False),
            ))
        db.session.add(InstallmentApplicationActivity(tenant_id=tenant_id, application_id=application.id, action="submitted", to_status="new"))
        db.session.commit()
        return application, token

    @staticmethod
    def tracked(token: str, phone: str, tenant_id: int | None = None) -> InstallmentApplication | None:
        token_hash = hashlib.sha256(str(token or "").encode()).hexdigest()
        digits = normalize_phone(phone)
        query = InstallmentApplication.query.filter_by(tracking_token_hash=token_hash, phone=digits)
        if tenant_id is not None:
            query = query.filter_by(tenant_id=tenant_id)
        return query.first()


class ApprovalService:
    @classmethod
    def approve(cls, application: InstallmentApplication, employee_id: int | None, start_date: date | None = None) -> InstallmentContract:
        if application.status not in {"new", "under_review"}:
            raise InstallmentError("لا يمكن الموافقة على الطلب في حالته الحالية")
        if application.contract:
            return application.contract
        if not application.items:
            raise InstallmentError("الطلب لا يحتوي منتجات")
        settings = InstallmentSettings.query.filter_by(tenant_id=application.tenant_id).first()
        try:
            required_documents = set(json.loads(settings.documents_config_json or "[]")) if settings else set()
        except (ValueError, TypeError):
            required_documents = set()
        if settings and settings.guarantor_required:
            required_documents.add("guarantor")
        uploaded_documents = {document.document_type for document in application.documents}
        missing_documents = required_documents - uploaded_documents
        if missing_documents:
            raise InstallmentError("المستندات المطلوبة غير مكتملة: " + "، ".join(sorted(missing_documents)))
        item_products = [(item, Product.query.get(item.product_id)) for item in application.items]
        if any(not product or not product.active for item, product in item_products):
            raise InstallmentError("أحد المنتجات لم يعد متاحًا")

        try:
            customer = find_customer_by_phone(application.tenant_id, application.phone)
            if not customer:
                customer = Customer(tenant_id=application.tenant_id, name=application.customer_name, phone=application.phone, city=application.city, address=application.address)
                db.session.add(customer)
                db.session.flush()
            else:
                customer.name = application.customer_name
                customer.city = application.city
                customer.address = application.address
            application.customer_id = customer.id
            application.assigned_employee_id = employee_id

            default_branch = get_default_branch()
            preferred_branch_id = default_branch.id if default_branch else None
            stock_check = check_stock_rows(
                [{"product": product, "product_id": product.id, "quantity": item.quantity, "variant_color": None} for item, product in item_products],
                preferred_branch_id=preferred_branch_id,
            )
            if not stock_check.can_fulfill:
                raise InstallmentError(stock_check.reason_text or "المخزون غير كافٍ لإتمام الموافقة")
            fulfillment_branch_id = stock_check.actions[0].fulfillment_branch_id if stock_check.actions else preferred_branch_id
            total_amount = sum(item.installment_total for item, _ in item_products)
            down_payment = sum(item.down_payment for item, _ in item_products)
            financed_amount = sum(item.financed_amount for item, _ in item_products)
            deduct_now = not settings or settings.reservation_policy != "on_delivery"
            invoice = Invoice(
                tenant_id=application.tenant_id,
                customer_id=customer.id,
                customer_name=customer.name,
                employee_id=employee_id,
                total=total_amount,
                paid_amount=down_payment,
                status="تم الطلب",
                payment_status="جزئي" if down_payment else "غير مسدد",
                source_module="installments",
                note=f"طلب أقساط {application.application_number}",
                branch_id=fulfillment_branch_id,
                stock_is_deducted=deduct_now,
                stock_deducted_at=datetime.utcnow() if deduct_now else None,
            )
            db.session.add(invoice)
            db.session.flush()
            for index, (item, product) in enumerate(item_products):
                line_branch = stock_check.actions[index].fulfillment_branch_id if index < len(stock_check.actions) else fulfillment_branch_id
                db.session.add(OrderItem(invoice_id=invoice.id, product_id=product.id, product_name=product.name, price=item.installment_total // item.quantity, quantity=item.quantity, cost=int(product.buy_price or 0), total=item.installment_total, fulfillment_branch_id=line_branch))
            if deduct_now:
                apply_stock_actions(stock_check.actions, invoice=invoice)

            start = start_date or date.today()
            first_due = add_months(start, 1)
            if settings:
                first_due = first_due.replace(day=min(settings.payment_day, monthrange(first_due.year, first_due.month)[1]))
            contract = InstallmentContract(
                tenant_id=application.tenant_id,
                application_id=application.id,
                customer_id=customer.id,
                invoice_id=invoice.id,
                contract_number=f"IC-{datetime.utcnow():%Y%m%d%H%M%S}-{application.id}",
                total_amount=total_amount,
                down_payment=down_payment,
                paid_amount=down_payment,
                remaining_amount=financed_amount,
                start_date=start,
                first_due_date=first_due,
                financed_amount=financed_amount,
                number_of_installments=max(len(json.loads(item.calculation_json)["schedule"]) for item, _ in item_products),
                created_by_id=employee_id,
                approved_by_id=employee_id,
                status="active" if financed_amount else "completed",
            )
            db.session.add(contract)
            db.session.flush()
            for item, product in item_products:
                db.session.add(InstallmentContractItem(
                    tenant_id=application.tenant_id,
                    contract_id=contract.id,
                    application_item_id=item.id,
                    product_id=product.id,
                    product_name=item.product_name_snapshot or product.name,
                    sku=item.sku_snapshot,
                    main_image=item.main_image_snapshot,
                    quantity=item.quantity,
                    months=item.months_snapshot,
                    pricing_mode=item.pricing_mode_snapshot,
                    cash_price=item.cash_price,
                    installment_total=item.installment_total,
                    fees=item.processing_fee,
                    down_payment=item.down_payment,
                    financed_amount=item.financed_amount,
                    calculation_json=item.calculation_json,
                ))
            schedule_totals: dict[int, int] = {}
            for item, _ in item_products:
                for row in json.loads(item.calculation_json)["schedule"]:
                    schedule_totals[int(row["sequence"])] = schedule_totals.get(int(row["sequence"]), 0) + int(row["amount"])
            for sequence, amount in sorted(schedule_totals.items()):
                db.session.add(InstallmentSchedule(tenant_id=application.tenant_id, contract_id=contract.id, sequence=sequence, due_date=add_months(first_due, sequence - 1), amount=amount, paid_amount=0, remaining_amount=amount, status="pending"))
            previous_status = application.status
            application.status = "approved"
            application.reviewed_by_id = employee_id
            application.reviewed_at = datetime.utcnow()
            db.session.add(InstallmentApplicationActivity(tenant_id=application.tenant_id, application_id=application.id, actor_id=employee_id, action="approved", from_status=previous_status, to_status="approved"))
            cls._post_receivable(contract, employee_id)
            if down_payment > 0:
                append_installment_ledger_delta(
                    invoice,
                    down_payment,
                    payment_method="cash",
                    note=f"دفعة أولى لعقد {contract.contract_number}",
                )
            db.session.commit()
            return contract
        except Exception:
            db.session.rollback()
            current_app.logger.exception("installment approval failed application=%s", application.id)
            raise

    @staticmethod
    def _post_receivable(contract: InstallmentContract, employee_id: int | None) -> None:
        settings = InstallmentSettings.query.filter_by(tenant_id=contract.tenant_id).first()
        if not settings or not settings.receivable_account_id or not settings.sales_account_id:
            return
        amount = contract.remaining_amount
        if amount <= 0:
            return
        db.session.add(JournalEntry(entry_number=f"JE-IC-{contract.id}", description=f"ذمم عقد الأقساط {contract.contract_number}", reference_type="installment_contract", reference_id=contract.id, debit_account_id=settings.receivable_account_id, credit_account_id=settings.sales_account_id, amount=amount, created_by=employee_id))
        if contract.down_payment > 0 and settings.cash_account_id:
            db.session.add(JournalEntry(entry_number=f"JE-IC-DP-{contract.id}", description=f"دفعة أولى لعقد الأقساط {contract.contract_number}", reference_type="installment_down_payment", reference_id=contract.id, debit_account_id=settings.cash_account_id, credit_account_id=settings.sales_account_id, amount=contract.down_payment, created_by=employee_id))
        fees = sum(item.processing_fee for item in contract.application.items)
        if fees > 0 and settings.fee_account_id:
            db.session.add(JournalEntry(
                entry_number=f"JE-IC-FEE-{contract.id}",
                description=f"إعادة تصنيف رسوم عقد الأقساط {contract.contract_number}",
                reference_type="installment_contract_fee",
                reference_id=contract.id,
                debit_account_id=settings.sales_account_id,
                credit_account_id=settings.fee_account_id,
                amount=fees,
                created_by=employee_id,
            ))

    @classmethod
    def fulfill(cls, contract: InstallmentContract, employee_id: int | None) -> Invoice:
        invoice = Invoice.query.get(contract.invoice_id)
        if not invoice:
            raise InstallmentError("الطلب المرتبط بالعقد غير موجود")
        if invoice.stock_is_deducted:
            return invoice
        rows = []
        for order_item in invoice.items:
            product = Product.query.get(order_item.product_id)
            if not product or not product.active:
                raise InstallmentError("أحد منتجات العقد لم يعد متاحاً")
            rows.append({"product": product, "product_id": product.id, "quantity": order_item.quantity, "variant_color": None})
        default_branch = get_default_branch()
        stock_check = check_stock_rows(rows, preferred_branch_id=invoice.branch_id or (default_branch.id if default_branch else None))
        if not stock_check.can_fulfill:
            raise InstallmentError(stock_check.reason_text or "المخزون غير كافٍ للتسليم")
        try:
            apply_stock_actions(stock_check.actions, invoice=invoice)
            invoice.stock_is_deducted = True
            invoice.stock_deducted_at = datetime.utcnow()
            invoice.status = "تم التوصيل"
            previous_status = contract.application.status
            contract.application.status = "delivered"
            db.session.add(InstallmentApplicationActivity(
                tenant_id=contract.tenant_id, application_id=contract.application_id,
                actor_id=employee_id, action="delivered", from_status=previous_status,
                to_status="delivered",
            ))
            db.session.commit()
            return invoice
        except Exception:
            db.session.rollback()
            current_app.logger.exception("installment fulfillment failed contract=%s", contract.id)
            raise


class CancellationService:
    """Synchronize a cancelled sales invoice with its installment records."""

    @classmethod
    def cancel_from_invoice(
        cls,
        invoice: Invoice,
        employee_id: int | None = None,
        reason: str | None = None,
    ) -> InstallmentContract | None:
        contract = InstallmentContract.query.filter_by(invoice_id=invoice.id).first()
        if not contract:
            return None

        posted_payments = [payment for payment in contract.payments if payment.status == "posted"]
        if posted_payments:
            raise InstallmentError("لا يمكن إلغاء طلب الأقساط قبل عكس الدفعات المسجلة على العقد")

        application = contract.application
        old_application_status = application.status
        already_cancelled = contract.status == "cancelled" and application.status == "cancelled"

        contract.status = "cancelled"
        contract.paid_amount = 0
        contract.remaining_amount = 0
        contract.updated_at = datetime.utcnow()
        for schedule in contract.schedules:
            schedule.status = "cancelled"
            schedule.paid_amount = 0
            schedule.remaining_amount = 0
            schedule.paid_at = None

        application.status = "cancelled"
        if not already_cancelled:
            db.session.add(InstallmentApplicationActivity(
                tenant_id=application.tenant_id,
                application_id=application.id,
                actor_id=employee_id,
                action="cancelled_from_order",
                from_status=old_application_status,
                to_status="cancelled",
                note=(str(reason or "").strip()[:2000] or "تم إلغاء الطلب المرتبط بعقد الأقساط"),
            ))

        # Reverse only accounting entries created by installment approval.
        # The generic order payment ledger is reversed by the order lifecycle.
        original_entries = JournalEntry.query.filter(
            JournalEntry.reference_id == contract.id,
            JournalEntry.reference_type.in_([
                "installment_contract",
                "installment_down_payment",
                "installment_contract_fee",
            ]),
        ).all()
        for original in original_entries:
            reversal_number = f"JE-IC-CANCEL-{contract.id}-{original.id}"
            if JournalEntry.query.filter_by(entry_number=reversal_number).first():
                continue
            db.session.add(JournalEntry(
                entry_number=reversal_number,
                description=f"عكس قيد عقد الأقساط الملغي {contract.contract_number}",
                reference_type="installment_contract_cancellation",
                reference_id=contract.id,
                debit_account_id=original.credit_account_id,
                credit_account_id=original.debit_account_id,
                amount=original.amount,
                created_by=employee_id,
            ))
        return contract


class PaymentService:
    @classmethod
    def post(cls, contract: InstallmentContract, amount, method: str, employee_id: int | None, reference: str = "", notes: str = "", paid_at: str | date | datetime | None = None) -> InstallmentPayment:
        value = money(amount)
        if contract.status != "active":
            raise InstallmentError("العقد غير نشط")
        if value <= 0 or value > contract.remaining_amount:
            raise InstallmentError("مبلغ الدفعة أكبر من الرصيد أو غير صالح")
        try:
            settings = InstallmentSettings.query.filter_by(tenant_id=contract.tenant_id).first()
            if settings and not settings.allow_advance_payment:
                due_amount = sum(
                    max(0, row.amount - row.paid_amount)
                    for row in contract.schedules
                    if row.due_date <= date.today() and row.status != "paid"
                )
                if value > due_amount:
                    raise InstallmentError("الدفع المقدم غير مسموح؛ المبلغ يتجاوز الأقساط المستحقة")
            method_value = str(method or "cash")[:30]
            if isinstance(paid_at, datetime):
                payment_date = paid_at
            elif isinstance(paid_at, date):
                payment_date = datetime.combine(paid_at, datetime.min.time())
            elif paid_at:
                try:
                    payment_date = datetime.strptime(str(paid_at), "%Y-%m-%d")
                except ValueError as exc:
                    raise InstallmentError("تاريخ الدفعة غير صالح") from exc
            else:
                payment_date = datetime.utcnow()
            if payment_date.date() > date.today():
                raise InstallmentError("لا يمكن تسجيل دفعة بتاريخ مستقبلي")
            account_id = settings.bank_account_id if settings and method_value == "bank" else (settings.cash_account_id if settings else None)
            payment = InstallmentPayment(tenant_id=contract.tenant_id, contract_id=contract.id, customer_id=contract.customer_id, payment_number=f"IP-{datetime.utcnow():%Y%m%d%H%M%S}-{secrets.randbelow(1000):03d}", amount=value, payment_method=method_value, account_id=account_id, reference=str(reference or "")[:120] or None, notes=str(notes or "")[:2000] or None, received_by_id=employee_id, paid_at=payment_date)
            db.session.add(payment)
            db.session.flush()
            remaining = value
            schedules = InstallmentSchedule.query.filter_by(contract_id=contract.id).filter(InstallmentSchedule.status != "paid").order_by(InstallmentSchedule.due_date, InstallmentSchedule.sequence).all()
            for schedule in schedules:
                if remaining <= 0:
                    break
                outstanding = schedule.amount - schedule.paid_amount
                allocated = min(remaining, outstanding)
                if allocated <= 0:
                    continue
                schedule.paid_amount += allocated
                schedule.remaining_amount = schedule.amount - schedule.paid_amount
                schedule.status = "paid" if schedule.paid_amount == schedule.amount else "partial"
                schedule.paid_at = datetime.utcnow() if schedule.status == "paid" else None
                db.session.add(InstallmentPaymentAllocation(tenant_id=contract.tenant_id, payment_id=payment.id, schedule_id=schedule.id, amount=allocated))
                remaining -= allocated
            if remaining:
                raise InstallmentError("تعذر تخصيص الدفعة بالكامل")
            contract.paid_amount += value
            contract.remaining_amount -= value
            if contract.remaining_amount == 0:
                contract.status = "completed"
                contract.completed_at = datetime.utcnow()
            invoice = Invoice.query.get(contract.invoice_id)
            if invoice:
                invoice.paid_amount = contract.paid_amount
                invoice.payment_status = "مسدد" if contract.remaining_amount == 0 else "جزئي"
                append_installment_ledger_delta(
                    invoice,
                    value,
                    payment_method=method_value,
                    recorded_at=payment_date,
                    note=f"تحصيل قسط {payment.payment_number}",
                )
            cls._post_accounting(payment, contract, employee_id)
            db.session.commit()
            return payment
        except Exception:
            db.session.rollback()
            current_app.logger.exception("installment payment failed contract=%s", contract.id)
            raise

    @staticmethod
    def _post_accounting(payment: InstallmentPayment, contract: InstallmentContract, employee_id: int | None) -> None:
        settings = InstallmentSettings.query.filter_by(tenant_id=contract.tenant_id).first()
        if not settings or not payment.account_id or not settings.receivable_account_id:
            return
        entry = JournalEntry(entry_number=f"JE-IP-{payment.id}", description=f"تحصيل أقساط {contract.contract_number}", reference_type="installment_payment", reference_id=payment.id, debit_account_id=payment.account_id, credit_account_id=settings.receivable_account_id, amount=payment.amount, created_by=employee_id)
        db.session.add(entry)
        db.session.flush()
        payment.journal_entry_id = entry.id

    @classmethod
    def reverse(cls, payment: InstallmentPayment, employee_id: int | None, reason: str) -> InstallmentPayment:
        if payment.status != "posted":
            raise InstallmentError("لا يمكن عكس هذه الدفعة")
        reason = str(reason or "").strip()
        if len(reason) < 3:
            raise InstallmentError("سبب العكس مطلوب")
        contract = payment.contract
        try:
            reversal = InstallmentPayment(
                tenant_id=payment.tenant_id,
                contract_id=contract.id,
                customer_id=contract.customer_id,
                payment_number=f"IR-{datetime.utcnow():%Y%m%d%H%M%S}-{secrets.randbelow(1000):03d}",
                amount=payment.amount,
                payment_method=payment.payment_method,
                account_id=payment.account_id,
                reference=payment.payment_number,
                notes=reason[:2000],
                status="reversal",
                reversal_of_id=payment.id,
                received_by_id=employee_id,
            )
            db.session.add(reversal)
            for allocation in payment.allocations:
                schedule = allocation.schedule
                schedule.paid_amount -= allocation.amount
                schedule.remaining_amount = schedule.amount - schedule.paid_amount
                if schedule.paid_amount <= 0:
                    schedule.paid_amount = 0
                    schedule.status = "overdue" if schedule.due_date < date.today() else "pending"
                    schedule.paid_at = None
                elif schedule.paid_amount < schedule.amount:
                    schedule.status = "partial"
                    schedule.paid_at = None
            payment.status = "reversed"
            contract.paid_amount -= payment.amount
            contract.remaining_amount += payment.amount
            contract.status = "active"
            contract.completed_at = None
            invoice = Invoice.query.get(contract.invoice_id)
            if invoice:
                invoice.paid_amount = contract.paid_amount
                invoice.payment_status = "جزئي" if contract.paid_amount else "غير مسدد"
                append_installment_ledger_delta(
                    invoice,
                    -int(payment.amount or 0),
                    payment_method=payment.payment_method,
                    note=f"عكس قسط {payment.payment_number}",
                )
            settings = InstallmentSettings.query.filter_by(tenant_id=contract.tenant_id).first()
            if settings and payment.account_id and settings.receivable_account_id:
                db.session.add(JournalEntry(
                    entry_number=f"JE-IR-{payment.id}",
                    description=f"عكس دفعة {payment.payment_number}: {reason[:300]}",
                    reference_type="installment_payment_reversal",
                    reference_id=payment.id,
                    debit_account_id=settings.receivable_account_id,
                    credit_account_id=payment.account_id,
                    amount=payment.amount,
                    created_by=employee_id,
                ))
            db.session.commit()
            return reversal
        except Exception:
            db.session.rollback()
            current_app.logger.exception("installment payment reversal failed payment=%s", payment.id)
            raise
