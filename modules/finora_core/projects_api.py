"""Operator review/edit of project offers and read-only future execution handoff."""
import jsonschema
from flask import jsonify

from .api import _actor, _conv_id, _customer_for, _json, finora_core_bp
from .auth import current_operator, require
from .errors import CoreApiError, conflict, not_found, validation_error
from .store import audit, core_session, use_house
from .brain import approvals, project_consultation as project
from .brain.models import FcApproval, FcCustomer
from .brain.tools import ToolError


@finora_core_bp.patch("/approvals/<approval_id>/project")
@require("settings.manage")
def revise_project(approval_id):
    if "approvals.decide" not in current_operator().permissions:
        raise CoreApiError("FORBIDDEN", "تحتاج صلاحية مراجعة الموافقات", 403)
    if not approval_id.isdigit():
        raise not_found("طلب الموافقة غير موجود")
    payload = _json()
    if set(payload) - {"planHash", "terms", "paymentReference", "paymentVerified"}:
        raise validation_error("حقول مراجعة غير معروفة")
    with core_session() as s:
        approval = s.get(FcApproval, int(approval_id))
        if not approval or approval.status != "pending" or approval.action not in {"publish_project_quote", "confirm_project_deposit"}:
            raise conflict("هذا العرض ليس بانتظار المراجعة")
        if payload.get("planHash") != approval.plan_hash:
            raise conflict("الخطة التي راجعتها تغيّرت")
        customer = s.get(FcCustomer, approval.customer_id)
        from .brain.channel_roles import require as require_channel
        try:
            require_channel(s, customer, approval.conversation_ref, approval.action)
        except ToolError as exc:
            raise conflict(str(exc)) from exc
        draft = project.load(s, customer, approval.conversation_ref, lock=True)
        s.refresh(approval)
        if approval.status != "pending" or payload.get("planHash") != approval.plan_hash:
            raise conflict("هذا العرض تغيّر أثناء المراجعة")
        try:
            stored = approvals._stored_plan(approval)
            current = project.approval_args(s, customer, {"type": approval.action, **stored["args"]})
            if current != stored["args"]:
                raise conflict("خطة العميل تغيّرت؛ حدّث العرض أولاً")
            if approval.action == "publish_project_quote":
                if set(payload) != {"planHash", "terms"}:
                    raise validation_error("أدخل السعر والعملة والمدة وموعد النسخة الأولية")
                draft["terms"] = project.validate_terms(payload["terms"])
            else:
                reference = str(payload.get("paymentReference") or "").strip()
                if set(payload) != {"planHash", "paymentReference", "paymentVerified"} or payload.get("paymentVerified") is not True or not 3 <= len(reference) <= 200:
                    raise validation_error("أكد التحقق من وصول الدفعة وأدخل مرجعاً لها")
                draft["paymentReference"] = reference
            draft["revision"] += 1
            project.save(s, customer, approval.conversation_ref, draft, _actor())
            updated = approvals.request(s, customer=customer, conversation_ref=approval.conversation_ref, run_id=approval.run_id,
                                        action={"type": approval.action, "conversation_ref": approval.conversation_ref,
                                                "revision": draft["revision"], "reason": "مراجعة المشرف لخطة المشروع"},
                                        risk="high", agent_limit=None)
        except (jsonschema.ValidationError, ValueError, TypeError):
            raise validation_error("بيانات العرض غير صالحة؛ راجع السعر والعملة والمدد") from None
        except ToolError as exc:
            raise conflict(str(exc)) from exc
        audit(s, actor=_actor(), actor_type="human", category="approvals", action="project.review", title="تحديث مراجعة المشروع",
              customer=customer.display_name, conversation_ref=approval.conversation_ref, approval_id=str(updated.id))
        s.commit()
        return jsonify({"approval": approvals.approval_dto(updated, customer.display_name)})


@finora_core_bp.get("/conversations/<conversation_id>/project/manifest")
@require("settings.manage")
def project_manifest(conversation_id):
    cid = _conv_id(conversation_id)
    from .conversations import get_conversation
    with use_house():
        if not get_conversation(cid):
            raise not_found("المحادثة غير موجودة")
    with core_session() as s:
        customer = _customer_for(s, cid)
        draft = project.load(s, customer, str(cid)) if customer else None
        if not draft:
            raise not_found("لا توجد استشارة برمجية لهذه المحادثة")
        return jsonify(project.manifest(draft))


@finora_core_bp.post("/conversations/<conversation_id>/project/send-offer")
@require("settings.manage")
def resend_offer(conversation_id):
    if "messages.send" not in current_operator().permissions:
        raise CoreApiError("FORBIDDEN", "تحتاج صلاحية إرسال الرسائل", 403)
    cid = _conv_id(conversation_id)
    with core_session() as s:
        customer = _customer_for(s, cid)
        from .brain.channel_roles import require as require_channel
        try:
            require_channel(s, customer, str(cid), "publish_project_quote")
        except ToolError as exc:
            raise conflict(str(exc)) from exc
        draft = project.load(s, customer, str(cid), lock=True) if customer else None
        if not draft or draft["phase"] != "quote_ready":
            raise conflict("لا يوجد عرض معتمد يحتاج إعادة تسليم")
        notice, revision, customer_id = project.quote_text(draft), draft["revision"], customer.id
        s.commit()
    from .api import _notify_customer
    deliveries = [_notify_customer(str(cid), part) for part in project.chunks(notice)]
    with core_session() as s:
        customer = s.get(FcCustomer, customer_id)
        draft = project.load(s, customer, str(cid), lock=True)
        if draft["phase"] != "quote_ready" or draft["revision"] != revision:
            raise conflict("الخطة تغيّرت أثناء التسليم")
        draft["quoteMessages"] = [item["id"] for item in deliveries if item]
        draft["quoteExpectedParts"] = len(deliveries)
        if all(deliveries) and all(item["status"] == "sent" for item in deliveries):
            draft["phase"] = "quote_sent"
        project.save(s, customer, str(cid), draft, _actor())
        s.commit()
        return jsonify({"project": project.dto(draft)})
