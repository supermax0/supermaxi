"""Conversation-bound account linking, configuration previews and the private owner inbox."""
from datetime import datetime

from flask import jsonify
from sqlalchemy.exc import IntegrityError

from .api import finora_core_bp, _conv_id, _json, _customer_for
from .auth import require, current_operator
from .errors import conflict, not_found, validation_error
from .store import core_session, use_house, audit, emit, house_slug
from .brain.models import FcCustomer, FcCustomerIdentity
from .brain.customers import resolve_for_conversation
from .brain.tools import ToolError
from .brain.tenant_setup import inspect_account, PROFILES, PRESETS
from .brain.support import FcSupportIssue, dto, report
from .brain.observability import redact


def customer_for(s, cid):
    from . import conversations as convs
    with use_house():
        conv = convs.get_conversation(cid)
        if conv is None:
            raise not_found("المحادثة غير موجودة")
        customer = _customer_for(s, cid)
        if customer is None:
            customer = resolve_for_conversation(s, conversation_ref=str(cid), channel_type=conv.channel.channel_type,
                                              contact_id=conv.external_contact_id, display_name=conv.contact_name)
    return customer


def view(s, customer):
    state = None
    failure = None
    if customer.tenant_slug:
        try:
            state = inspect_account(s, customer)
            state.pop("overrides", None)
        except ToolError as exc:
            failure = str(exc)
    return {"customerId": str(customer.id), "tenantSlug": customer.tenant_slug, "linked": bool(state), "error": failure, "account": state,
            "profiles": [{"key": key, "label": row["label"], "needs": row["needs"]} for key, row in PROFILES.items()],
            "permissionPresets": [{"key": key, "label": row["label"]} for key, row in PRESETS.items()]}


@finora_core_bp.get("/conversations/<raw_id>/account")
@require("settings.manage")
def account(raw_id):
    with core_session() as s:
        customer = customer_for(s, _conv_id(raw_id))
        result = view(s, customer)
        s.commit()
        return jsonify(result)


@finora_core_bp.post("/conversations/<raw_id>/account/link")
@require("settings.manage")
def link_account(raw_id):
    from models.core.tenant import Tenant
    from extensions_tenant import is_valid_tenant_slug
    data = _json()
    slug, reason = str(data.get("tenantSlug") or "").strip().lower(), str(data.get("reason") or "").strip()
    if data.get("ownershipVerified") is not True or len(reason) < 8 or len(reason) > 300 or not is_valid_tenant_slug(slug):
        raise validation_error("تأكد من ملكية العميل للحساب واكتب سبب التحقق؛ الاسم وحده لا يكفي")
    if slug == house_slug():
        raise conflict("حساب فينورا الداخلي محمي")
    with core_session() as s:
        customer = customer_for(s, _conv_id(raw_id))
        if customer.tenant_slug and customer.tenant_slug != slug:
            raise conflict("العميل مرتبط بحساب آخر؛ لا يُعاد ربطه تلقائياً")
        tenant = s.query(Tenant).filter_by(slug=slug, is_active=True).first()
        if tenant is None:
            raise not_found("حساب الشركة غير موجود أو متوقف")
        duplicate = s.query(FcCustomer).filter(FcCustomer.tenant_slug == slug, FcCustomer.id != customer.id, FcCustomer.merged_into_id.is_(None)).first()
        identity = s.query(FcCustomerIdentity).filter_by(kind="finora_tenant", value=slug).first()
        if duplicate or (identity and identity.customer_id != customer.id):
            raise conflict("الحساب مرتبط بعميل آخر؛ راجع هوية العميلين")
        customer.tenant_slug = slug
        try:
            inspect_account(s, customer)  # Verify a real database exists before persisting the link.
        except ToolError as exc:
            raise validation_error(str(exc)) from exc
        if not identity:
            s.add(FcCustomerIdentity(customer_id=customer.id, kind="finora_tenant", value=slug, verified=True, source="operator"))
        audit(s, actor=current_operator().username, actor_type="human", category="finora", action="account.link", title="ربط حساب العميل بعد التحقق",
              customer=customer.display_name, conversation_ref=str(raw_id), input_summary=f"{slug}: {redact(reason)}")
        emit(s, "customer.updated", {"customerId": str(customer.id)})
        try:
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            raise conflict("ربط الحساب تغيّر أثناء التحقق؛ حدّث المحادثة وراجع الهوية") from exc
        return jsonify(view(s, customer))


@finora_core_bp.post("/conversations/<raw_id>/account/propose")
@require("settings.manage")
def propose_setup(raw_id):
    from .brain import approvals, policy
    data, cid = _json(), _conv_id(raw_id)
    allowed = {"operation", "profile", "feature", "enabled", "employee_id", "permission_preset", "role_ids", "reason"}
    if set(data) - allowed:
        raise validation_error("إعدادات غير مسموحة؛ الحساب المستهدف يُحدد من المحادثة")
    with core_session() as s:
        customer = customer_for(s, cid)
        action = {**data, "type": "configure_tenant"}
        if data.get("operation") == "advisory":
            action["advice_ref"] = str(cid)
        decision = policy.decide(s, action, facts={})
        if decision.verdict != "approval":
            raise conflict("إعداد حسابات العملاء معطل من إعدادات الأتمتة")
        try:
            row = approvals.request(s, customer=customer, conversation_ref=str(cid), run_id=None, action=action, risk=decision.risk, agent_limit=None)
        except ToolError as exc:
            unknown_profile = exc.code == "UNKNOWN_PROFILE"
            report(s, customer, str(cid), kind="missing_template" if unknown_profile else "missing_feature" if exc.code in {"PLAN_LIMIT", "UNSUPPORTED_FEATURE"} else "configuration_error",
                   details=f"القالب المطلوب: {data.get('profile')}\n{exc}" if unknown_profile else str(exc),
                   source=f"manual:{exc.code}:{data.get('profile') if unknown_profile else data.get('feature', '')}", verified=unknown_profile)
            s.commit()
            raise validation_error(str(exc)) from exc
        s.commit()
        return jsonify({"approval": approvals.approval_dto(row, customer.display_name)}), 201


@finora_core_bp.get("/support/issues")
@require("settings.manage")
def issues():
    with core_session() as s:
        rows = s.query(FcSupportIssue).filter_by(status="open").order_by(FcSupportIssue.id.desc()).limit(100).all()
        return jsonify({"items": [dto(row, s.get(FcCustomer, row.customer_id).display_name) for row in rows]})


@finora_core_bp.post("/support/issues/<raw_id>/resolve")
@require("settings.manage")
def resolve_issue(raw_id):
    with core_session() as s:
        row = s.get(FcSupportIssue, _conv_id(raw_id))
        if row is None:
            raise not_found()
        row.status, row.resolved_at, row.resolved_by = "resolved", datetime.utcnow(), current_operator().username
        audit(s, actor=row.resolved_by, actor_type="human", category="finora", action="support.resolve", title="تمت معالجة تنبيه العميل", conversation_ref=row.conversation_ref)
        result = dto(row, s.get(FcCustomer, row.customer_id).display_name)
        emit(s, "support.issue", {"issue": result})
        s.commit()
        return jsonify({"issue": result})
