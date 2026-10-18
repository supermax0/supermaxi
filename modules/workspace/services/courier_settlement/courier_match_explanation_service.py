from __future__ import annotations

import re
from typing import Any, Dict, List

from modules.workspace.services.courier_settlement.courier_price_adjustment_policy import (
    CourierPriceAdjustmentPolicy,
)


class CourierMatchExplanationService:
    """Turn matcher internals into a short Arabic explanation for the UI."""

    STATUS_LABELS = {
        "matched": "مطابق تلقائياً",
        "review": "تحتاج مراجعة",
        "unmatched": "غير موجود بالنظام",
        "duplicate": "مكرر في الكشف",
    }

    @staticmethod
    def _value(row: Any, key: str, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _digits(value: Any) -> str:
        return re.sub(r"\D", "", str(value or ""))

    @staticmethod
    def _phone_matches(left: Any, right: Any) -> bool:
        a = CourierMatchExplanationService._digits(left)
        b = CourierMatchExplanationService._digits(right)
        if not a or not b:
            return False
        return a[-8:] == b[-8:] if len(a) >= 8 and len(b) >= 8 else a == b

    @staticmethod
    def _single_extra_digit_match(observed: Any, expected: Any) -> bool:
        left = CourierMatchExplanationService._digits(observed)
        right = CourierMatchExplanationService._digits(expected)
        if not left or not right or len(left) != len(right) + 1:
            return False
        return any(
            left[:index] + left[index + 1 :] == right
            for index in range(len(left))
        )

    @staticmethod
    def _fmt(value: Any) -> str:
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "غير مقروء"

    @staticmethod
    def explain(row: Any) -> Dict[str, Any]:
        status = CourierMatchExplanationService._value(row, "match_status", "unmatched")
        reasons = set(
            row.get_match_reasons()
            if hasattr(row, "get_match_reasons")
            else CourierMatchExplanationService._value(row, "match_reasons", [])
            or []
        )
        snapshot = (
            row.get_invoice_snapshot()
            if hasattr(row, "get_invoice_snapshot")
            else CourierMatchExplanationService._value(row, "invoice_snapshot")
        ) or {}

        statement_order = str(
            CourierMatchExplanationService._value(row, "normalized_order_number")
            or CourierMatchExplanationService._value(row, "raw_order_number")
            or ""
        )
        shipping_barcodes = list(snapshot.get("shipping_barcodes") or [])
        if snapshot.get("shipping_barcode") and snapshot.get("shipping_barcode") not in shipping_barcodes:
            shipping_barcodes.append(snapshot.get("shipping_barcode"))
        order_candidates = [
            *shipping_barcodes,
            snapshot.get("barcode"),
            snapshot.get("order_number"),
            snapshot.get("id"),
        ]
        order_candidates = [
            str(value).strip()
            for value in order_candidates
            if value not in (None, "")
        ]
        exact_order = next(
            (
                value
                for value in order_candidates
                if CourierMatchExplanationService._digits(value)
                == CourierMatchExplanationService._digits(statement_order)
            ),
            None,
        )
        near_order = next(
            (
                value
                for value in order_candidates
                if CourierMatchExplanationService._single_extra_digit_match(
                    statement_order,
                    value,
                )
            ),
            None,
        )
        system_order = str(
            exact_order
            or near_order
            or (shipping_barcodes[0] if shipping_barcodes else None)
            or snapshot.get("barcode")
            or snapshot.get("order_number")
            or snapshot.get("id")
            or ""
        )
        statement_phone = CourierMatchExplanationService._value(row, "customer_phone")
        system_phones = list(snapshot.get("customer_phones") or [])
        for phone in (snapshot.get("customer_phone"), snapshot.get("customer_phone2")):
            if phone and phone not in system_phones:
                system_phones.append(phone)
        system_phone = next(
            (
                phone
                for phone in system_phones
                if CourierMatchExplanationService._phone_matches(statement_phone, phone)
            ),
            system_phones[0] if system_phones else None,
        )
        statement_amount = CourierMatchExplanationService._value(row, "collected_amount")
        system_amount = snapshot.get("total")
        paid_amount = max(int(snapshot.get("paid_amount") or 0), 0)
        remaining_amount = max(
            int(snapshot.get("remaining_amount"))
            if snapshot.get("remaining_amount") is not None
            else int(system_amount or 0) - paid_amount,
            0,
        )
        is_partial = 0 < paid_amount < int(system_amount or 0)
        is_settled = bool(system_amount and paid_amount >= int(system_amount or 0))
        expected_amount = remaining_amount if paid_amount > 0 else system_amount
        normalized_shipping_barcodes = {
            CourierMatchExplanationService._digits(value)
            for value in shipping_barcodes
            if CourierMatchExplanationService._digits(value)
        }
        is_piece_settlement = bool(
            len(normalized_shipping_barcodes) > 1
            and CourierMatchExplanationService._digits(statement_order)
            in normalized_shipping_barcodes
            and int(statement_amount or 0) > 0
            and int(statement_amount or 0) <= int(expected_amount or 0)
        )
        remaining_after_piece = (
            max(int(expected_amount or 0) - int(statement_amount or 0), 0)
            if is_piece_settlement
            else remaining_amount
        )
        price_adjustment_plan = snapshot.get("price_adjustment_plan") or (
            CourierPriceAdjustmentPolicy.build_plan(
                snapshot,
                statement_amount,
                statement_order,
            )
            if snapshot
            else None
        )
        if (
            not price_adjustment_plan
            and snapshot.get("id")
            and not (snapshot.get("note") or snapshot.get("agent_note"))
        ):
            try:
                from flask import has_app_context
                from models.invoice import Invoice
                from modules.workspace.services.courier_settlement.invoice_snapshot_adapter import (
                    InvoiceSnapshotAdapter,
                )

                if has_app_context():
                    live_invoice = Invoice.query.get(int(snapshot["id"]))
                    live_snapshot = InvoiceSnapshotAdapter.from_invoice(live_invoice)
                    price_adjustment_plan = CourierPriceAdjustmentPolicy.build_plan(
                        live_snapshot,
                        statement_amount,
                        statement_order,
                    )
            except Exception:
                price_adjustment_plan = None

        order_state = "unknown"
        if "order_number_exact" in reasons:
            order_state = "match"
        elif "order_number_single_extra_digit" in reasons:
            order_state = "near"
        elif statement_order and system_order:
            order_state = "mismatch"

        phone_state = "unknown"
        if statement_phone and system_phones:
            phone_state = (
                "match"
                if any(
                    CourierMatchExplanationService._phone_matches(statement_phone, phone)
                    for phone in system_phones
                )
                else "mismatch"
            )

        amount_state = "unknown"
        if is_piece_settlement:
            amount_state = "match"
        elif price_adjustment_plan:
            amount_state = "near"
        elif statement_amount is not None and expected_amount is not None:
            amount_state = (
                "match"
                if abs(int(statement_amount) - int(expected_amount)) <= 1000
                else "mismatch"
            )

        checks: List[Dict[str, Any]] = [
            {
                "key": "order",
                "label": "رقم الطلب",
                "state": order_state,
                "statement": statement_order or None,
                "system": system_order or None,
            },
            {
                "key": "phone",
                "label": "الهاتف",
                "state": phone_state,
                "statement": statement_phone,
                "system": system_phone,
            },
            {
                "key": "amount",
                "label": (
                    "تحصيل القطعة"
                    if is_piece_settlement
                    else ("الرصيد المتبقي" if paid_amount > 0 else "المبلغ")
                ),
                "state": amount_state,
                "statement": statement_amount,
                "system": expected_amount,
            },
        ]

        manually_corrected = bool(
            {"manual_order_override", "manual_candidate_approval"} & reasons
        )
        manually_approved = "manual_candidate_approval" in reasons
        if status == "duplicate":
            message = "رقم الطلب مكرر داخل الكشف؛ لا يُنفّذ مرتين."
            action = "راجع النسختين وحدد الصف الصحيح."
        elif price_adjustment_plan and status == "matched":
            old_total = CourierMatchExplanationService._fmt(
                price_adjustment_plan.get("original_total")
            )
            new_total = CourierMatchExplanationService._fmt(
                price_adjustment_plan.get("target_total")
            )
            if price_adjustment_plan.get("kind") == "replacement":
                message = (
                    f"ملاحظة الطلب تشير إلى تبديل/استبدال. عند التنفيذ سيتغير سعر الطلب "
                    f"من {old_total} إلى {new_total} وتصبح حالته استبدال."
                )
                action = (
                    "راجع التغيير الظاهر؛ لا يُعدّل الطلب إلا بعد موافقتك على تنفيذ الكشف."
                )
            else:
                message = (
                    f"فرق السعر {CourierMatchExplanationService._fmt(price_adjustment_plan.get('absolute_difference'))} "
                    f"لا يتجاوز 5,000 د.ع. عند التنفيذ سيتغير سعر الطلب من "
                    f"{old_total} إلى {new_total}."
                )
                action = (
                    "راجع السعر الجديد؛ لا يُعدّل الطلب إلا بعد موافقتك على تنفيذ الكشف."
                )
        elif manually_corrected and status == "matched":
            message = (
                f"تم ربط الصف يدوياً بالطلب "
                f"{system_order or snapshot.get('id')}، وبيانات المطابقة كافية."
            )
            action = "راجع الهاتف والمبلغ الظاهرين قبل تنفيذ الكشف."
        elif manually_corrected:
            message = (
                f"تم ربط الصف يدوياً بالطلب "
                f"{system_order or snapshot.get('id')}، لكن توجد بيانات مختلفة."
            )
            action = "راجع علامات الاختلاف؛ لن يُنفّذ الصف ما دام تحت المراجعة."
        elif status == "matched":
            matched_parts = []
            if order_state == "match":
                matched_parts.append("رقم الطلب")
            elif order_state == "near":
                matched_parts.append("رقم الطلب بعد تصحيح رقم OCR زائد")
            if phone_state == "match":
                matched_parts.append("الهاتف")
            if amount_state == "match":
                matched_parts.append("المبلغ")
            evidence = " و".join(matched_parts) or "بيانات الطلب"
            message = f"اعتمد تلقائياً لأن {evidence} مطابق للنظام."
            if is_piece_settlement:
                message += (
                    f" الباركود {system_order} يعود لقطعة من طلب متعدد القطع؛ "
                    f"سيُسدد {CourierMatchExplanationService._fmt(statement_amount)} فقط "
                    f"ويبقى {CourierMatchExplanationService._fmt(remaining_after_piece)} على الطلب."
                )
                action = "عند التنفيذ ستُسجل دفعة جزئية وأجرة توصيل هذه القطعة فقط."
            elif (
                is_settled
                and int(statement_amount or 0) == 0
                and int(CourierMatchExplanationService._value(row, "delivery_fee") or 0) > 0
                and amount_state == "match"
            ):
                message += (
                    " الطلب مسدد بالكامل ورصيده المتبقي صفر؛ "
                    "هذا الصف يمثل أجور توصيل فقط وليس تحصيلاً جديداً."
                )
                action = "عند التنفيذ لن تُضاف دفعة ثانية؛ ستُسجل أجرة التوصيل فقط."
            elif is_partial and amount_state == "match":
                message += (
                    f" الطلب مسدد جزئياً: المدفوع سابقاً "
                    f"{CourierMatchExplanationService._fmt(paid_amount)} والمتبقي "
                    f"{CourierMatchExplanationService._fmt(remaining_amount)}، وهو يطابق مبلغ الكشف."
                )
                action = "عند التنفيذ سيُسدد الرصيد المتبقي فقط ويصبح الطلب مسدداً بالكامل."
            else:
                action = "لا يحتاج تدخلاً ما لم تكن هناك مشكلة مالية أخرى."
        elif snapshot:
            if phone_state == "match" and amount_state == "match" and order_state == "mismatch":
                message = (
                    f"يوجد طلب محتمل رقم {system_order or snapshot.get('id')}: الهاتف والمبلغ "
                    f"متطابقان، لكن رقم الكشف {statement_order or 'غير مقروء'} مختلف."
                )
                action = "راجع رقم الطلب في الصورة؛ غالباً الرقم مقروء خطأ."
            elif order_state in ("match", "near") and (
                phone_state == "mismatch" or amount_state == "mismatch"
            ):
                differences = []
                if phone_state == "mismatch":
                    differences.append("الهاتف")
                if amount_state == "mismatch":
                    differences.append(
                        "المبلغ "
                        f"({CourierMatchExplanationService._fmt(statement_amount)} بالكشف مقابل "
                        f"{CourierMatchExplanationService._fmt(expected_amount)} بالنظام)"
                    )
                message = (
                    f"رقم الطلب قريب من {system_order or snapshot.get('id')}، لكن "
                    f"{' و'.join(differences)} مختلف؛ لذلك لم يُعتمد تلقائياً."
                )
                action = "تأكد أن بيانات صف مجاور لم تنتقل إلى هذا الصف أثناء قراءة الصورة."
            elif phone_state == "match" and amount_state == "mismatch":
                message = (
                    f"وجدنا طلباً بنفس الهاتف، لكن رقم الطلب والمبلغ مختلفان "
                    f"({CourierMatchExplanationService._fmt(statement_amount)} بالكشف مقابل "
                    f"{CourierMatchExplanationService._fmt(expected_amount)} بالنظام)."
                )
                action = "راجع رقم الطلب والمبلغ في الكشف قبل التسديد."
            elif amount_state == "match" and phone_state != "match":
                message = (
                    "التشابه بالمبلغ والتاريخ فقط، بينما رقم الطلب والهاتف لا يثبتان "
                    "أنهما نفس الطلب."
                )
                action = "لا تعتمد الصف قبل مطابقة رقم الطلب أو الهاتف."
            else:
                message = "يوجد طلب محتمل، لكن أدلة المطابقة غير كافية لاعتماده بأمان."
                action = "قارن رقم الطلب والهاتف والمبلغ مع الصورة."
        else:
            message = "لم يُعثر على طلب يحمل رقماً أو هاتفاً أو مبلغاً مطابقاً بشكل كافٍ."
            action = "صحّح رقم الطلب المقروء أو تأكد أن الطلب مسجل في النظام."

        return {
            "status": status,
            "status_label": (
                ("مرتبط يدوياً" if status == "matched" else "مرتبط يدوياً — مراجعة")
                if manually_corrected and status != "duplicate"
                else CourierMatchExplanationService.STATUS_LABELS.get(
                    status, status or "غير معروف"
                )
            ),
            "message": message,
            "suggested_action": action,
            "manually_corrected": manually_corrected,
            "manually_approved": manually_approved,
            "candidate": {
                "invoice_id": snapshot.get("id"),
                "order_number": system_order or None,
                "matched_shipping_barcode": (
                    system_order if system_order in shipping_barcodes else None
                ),
                "shipping_barcodes": shipping_barcodes,
                "customer_name": snapshot.get("customer_name"),
                "customer_phone": system_phone,
                "customer_phones": system_phones,
                "total": system_amount,
                "paid_amount": paid_amount,
                "remaining_amount": remaining_amount,
                "allocated_paid_amount": snapshot.get("allocated_paid_amount"),
                "payment_verified_in_accounts": bool(
                    snapshot.get("payment_verified_in_accounts")
                ),
                "piece_settlement": is_piece_settlement,
                "piece_barcode": system_order if is_piece_settlement else None,
                "remaining_after_piece": remaining_after_piece,
                "status": snapshot.get("status"),
                "payment_status": snapshot.get("payment_status"),
                "payment_allocations": snapshot.get("payment_allocations") or [],
                "price_adjustment_plan": price_adjustment_plan,
            }
            if snapshot
            else None,
            "checks": checks,
        }
