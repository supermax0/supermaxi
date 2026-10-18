"""Read-only general-retail quote from saved evidence; never execute a refund."""
from extensions import db
from .allocation import (
    AllocationError, OriginalCostLayer, SaleLine, credit_breakdown,
    discounted_line_values, original_fifo_return, partial_line_credit,
)
from .evidence import capture, encoded


class ReturnPreviewError(ValueError):
    pass


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ReturnPreviewError(f"بيانات {name} غير صحيحة في دليل البيع")
    return value


def quote(invoice, selections, *, original=None, returned_quantities=None):
    """The eventual command supplies quantities from locked posted documents.

    These parameters are internal evidence, never client-provided balances.
    Provider adapters for food, financed sales and trade-ins remain required.
    """
    if db.session.is_modified(invoice, include_collections=True):
        raise ReturnPreviewError("احفظ أو تراجع عن تعديل الفاتورة قبل معاينة المرتجع")
    with db.session.no_autoflush:
        return _quote(invoice, selections, original, returned_quantities)


def _quote(invoice, selections, original, returned_quantities):
    original = original if original is not None else capture(invoice)
    header = original["invoice"]
    if header["id"] != invoice.id:
        raise ReturnPreviewError("دليل الأصل يخص فاتورة أخرى")
    if header.get("source_module") not in (None, "", "pos", "branch_sales"):
        raise ReturnPreviewError("مصدر البيع يحتاج مسار المرتجع الخاص به")
    if header.get("currency") not in (None, "", "IQD") or header.get("exchange_rate") not in (None, 1, 1.0):
        raise ReturnPreviewError("البيع بعملة أخرى يحتاج حفظ كلفته وتسديداته بعملته الأصلية")
    if any(not row["physical"] and (row["value"] or 0) > 0 for row in original["lines"]):
        raise ReturnPreviewError("أجور الخدمة المنفصلة تحتاج تحديد سياسة ردها قبل المعاينة")
    physical = {row["id"]: row for row in original["lines"] if row["physical"]}
    if any(row["sale_mode"] not in (None, "normal") for row in physical.values()):
        raise ReturnPreviewError("البيع الذي استلم جهازاً من الزبون يحتاج تتبع ذلك الجهاز أيضاً")
    previous = dict(returned_quantities or {})
    if not set(previous) <= set(physical):
        raise ReturnPreviewError("الكميات المرتجعة السابقة لا تخص بنود الأصل")
    try:
        values = discounted_line_values(_integer(header["total"], "إجمالي الأصل"),
            [SaleLine(row["id"], row["quantity"], row["value"]) for row in physical.values()])
        credited = 0
        for row_id, row in physical.items():
            count = _integer(previous.get(row_id, 0), "المرتجع السابق")
            if count > row["quantity"]:
                raise ReturnPreviewError("سجل المرتجع السابق تجاوز الكمية الأصلية")
            credited += values[row_id] * count // row["quantity"]
        remaining = header["total"] - credited
        if int(invoice.total or 0) != remaining:
            raise ReturnPreviewError("صافي الفاتورة لا يطابق أصل البيع والمرتجعات؛ راجع الدليل")
        if not isinstance(selections, list) or not selections:
            raise ReturnPreviewError("اختر كمية من بند واحد على الأقل")
        seen, lines = set(), []
        for selected in selections:
            if not isinstance(selected, dict):
                raise ReturnPreviewError("بند المرتجع غير صحيح")
            row_id = _integer(selected.get("id"), "رقم البند", 1)
            quantity = _integer(selected.get("quantity"), "الكمية", 1)
            if row_id not in physical or row_id in seen:
                raise ReturnPreviewError("البند غير موجود في أصل البيع أو مكرر")
            seen.add(row_id)
            row, before = physical[row_id], previous.get(row_id, 0)
            credit = partial_line_credit(values[row_id], row["quantity"], before, quantity)
            layers = row["cost_layers"]
            if layers:
                if sum(layer["quantity"] for layer in layers) != row["quantity"]:
                    raise ReturnPreviewError("طبقات كلفة الأصل لا تغطي كامل الكمية؛ راجع دليل السحب")
                portions = original_fifo_return([OriginalCostLayer(layer["id"], layer["lot_id"],
                    layer["quantity"], layer["unit_cost"]) for layer in layers], before, quantity)
                cost = sum(part.amount for part in portions)
            else:
                portions = []
                cost = _integer(row["saved_unit_cost"], "الكلفة القديمة المحفوظة") * quantity
            lines.append({"id": row_id, "quantity": quantity, "credit": credit, "cost": cost,
                "cost_basis": row["cost_basis"], "portions": [vars(part) for part in portions]})
        credit = sum(row["credit"] for row in lines)
        breakdown = credit_breakdown(remaining, _integer(invoice.paid_amount, "التحصيل الحالي"), credit)
    except AllocationError as error:
        raise ReturnPreviewError(str(error)) from error
    return {"invoice_id": invoice.id, "original_hash": encoded(original)[1], "lines": lines,
        "credit": credit, "cost": sum(row["cost"] for row in lines), **breakdown,
        "note": "هذه معاينة قيمة وكلفة فقط. فائض التحصيل يحتاج اختيار مصدر الرد أو الرصيد؛ لم يتغير مال أو مخزون."}
