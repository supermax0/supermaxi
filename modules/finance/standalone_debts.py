"""Reviewed recognition of legacy debts without invoices or historical cash replay."""
import json

from extensions import db
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan
from .common import FinanceError, policy
from .models import FinanceSourceState


def plans():
    return CustomerCreditPlan.query.filter(CustomerCreditPlan.invoice_id.is_(None)).order_by(
        CustomerCreditPlan.id).with_for_update().all()


def review():
    from .customer_installments import standalone_schedule
    from models.branch import Branch
    rows, issues = [], []
    for plan in plans():
        customer = db.session.get(Customer, plan.customer_id)
        branch = db.session.get(Branch, customer.branch_id) if customer and customer.branch_id else None
        try:
            standalone_schedule(plan)
            if not branch:
                raise FinanceError("اربط العميل بفرع قبل اعتماد الدين", "branch_required", 409)
        except FinanceError as error:
            issues.append(f"دين #{plan.id}: {error}")
        rows.append({"id": plan.id, "customer_id": plan.customer_id,
            "branch_id": customer.branch_id if customer else None,
            "total": int(plan.total_amount or 0), "paid": int(plan.paid_amount or 0),
            "remaining": max(0, int(plan.total_amount or 0) - int(plan.paid_amount or 0))})
    return rows, issues


def assert_reviewed(plan):
    if not policy().get("standalone_debts_reviewed"):
        raise FinanceError("اعتمد الديون المستقلة من مراجعة الأرصدة الافتتاحية في إعدادات الحسابات أولاً",
            "opening_review", 409)
    cursor = db.session.get(FinanceSourceState, f"customer_debt:{plan.id}")
    snapshot = json.loads(cursor.snapshot) if cursor else {}
    if snapshot.get("customer_id") != plan.customer_id:
        raise FinanceError("الدين غير معتمد محاسبياً أو تغيّر عميله؛ راجعه قبل التحصيل", "opening_review", 409)
    if snapshot.get("principal") != plan.total_amount or snapshot.get("paid") != int(plan.paid_amount or 0):
        raise FinanceError("رصيد الدين لا يطابق مصدره المحاسبي؛ راجع التعديلات السابقة قبل التحصيل أو العكس",
            "opening_review", 409)
