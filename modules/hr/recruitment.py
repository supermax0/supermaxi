"""Versioned recruitment forms, scoped staff review and isolated public links."""
import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, abort, current_app, g, jsonify, render_template, request
from sqlalchemy import inspect
from werkzeug.security import check_password_hash, generate_password_hash
from extensions import db
from extensions_tenant import get_tenant_engine, is_valid_tenant_slug
from .common import actor, audit, branch, day, fingerprint, integer, json_text, people_query, require, text, timestamp, uuid, version
from .models import HRApplication, HRApplicantFile, HRRecruitAttempt, HRRecruitForm, HRRecruitLink, HRPerson

FIELD_TYPES = {"short_text", "long_text", "number", "phone", "email", "date", "single", "multiple",
               "dropdown", "file", "image", "heading", "description", "consent"}
APPLICATION_STATES = {"new", "reviewing", "interview", "accepted", "rejected", "deferred"}
public_bp = Blueprint("hr_recruit_public", __name__, url_prefix="/careers")


def fields_schema(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 40:
        raise ValueError("أضف من 1 إلى 40 حقلاً")
    result, keys = [], set()
    for index, field in enumerate(value):
        if not isinstance(field, dict):
            raise ValueError("الحقل غير صحيح")
        key = text(field.get("key"), limit=40, required=True)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key) or key in keys:
            raise ValueError("معرّف الحقل يجب أن يكون فريداً بحروف إنكليزية")
        keys.add(key)
        kind = field.get("type")
        if kind not in FIELD_TYPES:
            raise ValueError("نوع الحقل غير متاح")
        options = field.get("options", [])
        if not isinstance(options, list) or len(options) > 30:
            raise ValueError("خيارات الحقل غير صحيحة")
        options = [text(o, limit=100, required=True) for o in options]
        if kind in ("single", "multiple", "dropdown") and (not options or len(set(options)) != len(options)):
            raise ValueError("أضف خيارات مختلفة لحقل الاختيار")
        result.append({"key": key, "type": kind, "label": text(field.get("label"), limit=150, required=True),
            "description": text(field.get("description", ""), limit=1000), "required": field.get("required") is True,
            "options": options, "max_length": integer(field.get("max_length", 2000 if kind == "long_text" else 255), minimum=1, maximum=4000),
            "max_file_kb": integer(field.get("max_file_kb", 1024), minimum=1, maximum=4096), "order": index,
            "minimum": integer(field["minimum"], maximum=2147483647) if field.get("minimum") not in (None, "") else None,
            "maximum": integer(field["maximum"], maximum=2147483647) if field.get("maximum") not in (None, "") else None})
        if result[-1]["minimum"] is not None and result[-1]["maximum"] is not None and result[-1]["minimum"] > result[-1]["maximum"]:
            raise ValueError("حدود الحقل غير صحيحة")
    return result


def scoped_forms():
    from models.branch import Branch
    from utils.branch_scope import allowed_branch_ids
    from utils.branch_mode import independent_branches_enabled
    branches = allowed_branch_ids() if independent_branches_enabled() else [b.id for b in Branch.query.all()]
    return HRRecruitForm.query.filter(HRRecruitForm.branch_id.in_(branches))


def form_for(form_id):
    require("hr.recruitment.manage")
    return scoped_forms().filter(HRRecruitForm.id == integer(form_id, minimum=1)).first_or_404()


def save_form(payload):
    require("hr.recruitment.manage")
    row = form_for(payload["form_id"]) if payload.get("form_id") else HRRecruitForm(branch_id=branch(payload), created_by=actor().id)
    if payload.get("form_id"):
        version(row, payload)
    row.title = text(payload.get("title"), limit=160, required=True)
    row.description = text(payload.get("description", ""), limit=2000)
    row.fields = json_text(fields_schema(payload.get("fields")))
    db.session.add(row)
    db.session.flush()
    audit("recruitment.form", row.id, detail={"version": row.version})
    return {"id": row.id, "version": row.version}


def create_link(payload):
    form = form_for(payload["form_id"])
    expires = timestamp(payload["expires_at"])
    if not datetime.utcnow() < expires <= datetime.utcnow() + timedelta(days=366):
        raise ValueError("اختر انتهاء الرابط خلال السنة القادمة")
    pin = text(payload.get("pin", ""), limit=50)
    if payload.get("private") is True and len(pin) < 4:
        raise ValueError("الرابط الخاص يحتاج رمزاً من 4 أحرف على الأقل")
    if pin and len(pin) < 4:
        raise ValueError("الرمز قصير")
    token = secrets.token_urlsafe(32)
    row = HRRecruitLink(form_id=form.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
        snapshot=json_text({"title": form.title, "description": form.description, "fields": json.loads(form.fields), "version": form.version}),
        pin_hash=generate_password_hash(pin) if pin else None, expires_at=expires,
        max_submissions=integer(payload.get("max_submissions", 100), minimum=1, maximum=10000), created_by=actor().id)
    db.session.add(row)
    db.session.flush()
    audit("recruitment.link", row.id, detail={"expires_at": expires.isoformat(), "private": bool(pin)})
    return {"id": row.id, "version": row.version, "url": f"/careers/{g.tenant}/{token}"}


def toggle_link(payload):
    row = db.session.get(HRRecruitLink, integer(payload["link_id"], minimum=1))
    if not row:
        abort(404)
    form_for(row.form_id)
    version(row, payload)
    if not isinstance(payload.get("active"), bool):
        raise ValueError("حالة الرابط غير صحيحة")
    row.active = payload["active"]
    audit("recruitment.link_state", row.id, detail={"active": row.active})
    return {"id": row.id, "version": row.version}


def application_for(application_id):
    require("hr.recruitment.manage")
    row = db.session.get(HRApplication, integer(application_id, minimum=1))
    if not row:
        abort(404)
    form_for(db.session.get(HRRecruitLink, row.link_id).form_id)
    return row


def decide_application(payload):
    row = application_for(payload["application_id"])
    version(row, payload)
    if row.person_id or payload.get("status") not in APPLICATION_STATES:
        raise ValueError("حالة الطلب غير صحيحة أو سبق تحويله إلى موظف")
    row.status = payload["status"]
    row.note = text(payload.get("note", ""), limit=2000)
    audit("recruitment.decision", row.id, detail={"status": row.status})
    return {"id": row.id, "version": row.version}


def convert_application(payload):
    row = application_for(payload["application_id"])
    version(row, payload)
    if row.status != "accepted" or row.person_id:
        raise ValueError("يجب قبول الطلب أولاً ولم يسبق تحويله")
    profile = payload.get("employee")
    if not isinstance(profile, dict):
        raise ValueError("أكمل بيانات الموظف الوظيفية والمالية")
    link = db.session.get(HRRecruitLink, row.link_id)
    form = form_for(link.form_id)
    if integer(profile.get("branch_id"), minimum=1) != form.branch_id:
        raise ValueError("الموظف يتبع فرع الاستمارة")
    from .employees import save_person
    result = save_person(profile)
    row.person_id = result["id"]
    # Accepted attachments become private employee documents, never public URLs.
    from .models import HRPrivateDocument
    for attachment in HRApplicantFile.query.filter_by(application_id=row.id).all():
        db.session.add(HRPrivateDocument(person_id=row.person_id, title=f"مرفق طلب التوظيف: {attachment.field_key}", kind="other",
            filename=attachment.filename, mime=attachment.mime, content=attachment.content, sha256=attachment.sha256, created_by=actor().id))
    audit("recruitment.convert", row.id, person_id=row.person_id)
    return {"id": row.person_id}


def staff_page(args):
    require("hr.recruitment.manage")
    forms = scoped_forms().order_by(HRRecruitForm.id.desc()).all()
    links = HRRecruitLink.query.filter(HRRecruitLink.form_id.in_([f.id for f in forms])).all()
    selected = [l.id for l in links if not args.get("form_id") or l.form_id == integer(args["form_id"], minimum=1)]
    query = HRApplication.query.filter(HRApplication.link_id.in_(selected))
    if args.get("status"):
        query = query.filter(HRApplication.status == text(args["status"], limit=20))
    page, size = integer(args.get("page", 1), minimum=1, maximum=100000), integer(args.get("page_size", 25), minimum=1, maximum=100)
    total = query.count()
    rows = query.order_by(HRApplication.id.desc()).offset((page - 1) * size).limit(size).all()
    files = HRApplicantFile.query.filter(HRApplicantFile.application_id.in_([r.id for r in rows])).all()
    return {"forms": [{"id": f.id, "branch_id": f.branch_id, "title": f.title, "description": f.description,
            "fields": json.loads(f.fields), "version": f.version} for f in forms],
        "links": [{"id": l.id, "form_id": l.form_id, "expires_at": l.expires_at.isoformat() + "Z", "received": l.received,
            "max_submissions": l.max_submissions, "active": l.active, "version": l.version, "private": bool(l.pin_hash)} for l in links],
        "rows": [{"id": r.id, "link_id": r.link_id, "status": r.status, "note": r.note, "version": r.version,
            "person_id": r.person_id, "answers": json.loads(r.answers), "date": r.created_at.isoformat() + "Z",
            "fields": json.loads(next(l for l in links if l.id == r.link_id).snapshot)["fields"],
            "files": [{"id": f.id, "filename": f.filename, "field_key": f.field_key} for f in files if f.application_id == r.id]} for r in rows],
        "total": total, "page": page, "page_size": size, "total_pages": max(1, (total + size - 1) // size)}


def lookup_company(tenant):
    from models.core.tenant import Tenant
    return Tenant.query.filter_by(slug=tenant, is_active=True).first()


def public_link(tenant, token):
    if not is_valid_tenant_slug(tenant) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        abort(404)
    # A public token never inherits another company's signed-in session.
    db.session.remove()
    g.tenant = None
    company = lookup_company(tenant)
    if not company or not company.is_subscription_valid():
        abort(404)
    company_name = company.name
    db.session.remove()
    g.tenant = tenant
    if not inspect(get_tenant_engine(tenant)).has_table("hr_recruit_link"):
        abort(404)
    link = HRRecruitLink.query.filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not link or not link.active or link.expires_at <= datetime.utcnow():
        abort(404)
    return link, company_name


def public_file(value, field):
    if not isinstance(value, dict) or set(value) != {"content", "mime", "filename"}:
        raise ValueError("مرفق غير صحيح")
    mime = text(value["mime"], limit=80)
    signatures = {"application/pdf": b"%PDF-", "image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
    if mime not in signatures or field["type"] == "image" and not mime.startswith("image/"):
        raise ValueError("نوع المرفق غير مسموح")
    if not isinstance(value["content"], str) or len(value["content"]) > 5592408:
        raise ValueError("المرفق أكبر من الحد المسموح")
    try:
        content = base64.b64decode(value["content"], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("مرفق غير صحيح") from None
    if not content.startswith(signatures[mime]) or len(content) > field["max_file_kb"] * 1024:
        raise ValueError("محتوى أو حجم المرفق غير صحيح")
    name = text(value["filename"], limit=160, required=True)
    if "/" in name or "\\" in name:
        raise ValueError("اسم المرفق غير صحيح")
    return {"content": content, "filename": name, "mime": mime, "sha256": hashlib.sha256(content).hexdigest()}


def validate_answers(snapshot, answers):
    if not isinstance(answers, dict):
        raise ValueError("بيانات التقديم غير صحيحة")
    fields = snapshot["fields"]
    if set(answers) - {f["key"] for f in fields}:
        raise ValueError("حقول التقديم غير معروفة")
    result, files = {}, {}
    for field in fields:
        key, kind = field["key"], field["type"]
        if kind in ("heading", "description"):
            continue
        value = answers.get(key)
        if value is None or value == "" or value == [] or value is False:
            if field["required"]:
                raise ValueError(f"أكمل حقل {field['label']}")
            continue
        if kind in ("file", "image"):
            files[key] = public_file(value, field)
            result[key] = {"filename": files[key]["filename"], "mime": files[key]["mime"], "sha256": files[key]["sha256"]}
        elif kind == "number":
            result[key] = integer(value, minimum=field.get("minimum") or 0, maximum=field.get("maximum") if field.get("maximum") is not None else 2147483647)
        elif kind == "multiple":
            if not isinstance(value, list) or len(value) > len(field["options"]) or any(v not in field["options"] for v in value) or len(set(value)) != len(value):
                raise ValueError(f"راجع خيارات {field['label']}")
            result[key] = value
        elif kind == "consent":
            if value is not True:
                raise ValueError("تحقق من الموافقة")
            result[key] = True
        else:
            value = text(value, limit=field["max_length"])
            if kind == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                raise ValueError("البريد الإلكتروني غير صحيح")
            if kind == "phone" and not re.fullmatch(r"[+0-9 ()-]{6,30}", value):
                raise ValueError("رقم الهاتف غير صحيح")
            if kind == "date":
                day(value)
            if kind in ("single", "dropdown") and value not in field["options"]:
                raise ValueError("الاختيار غير صحيح")
            result[key] = value
    if sum(len(f["content"]) for f in files.values()) > 4 * 1024 * 1024:
        raise ValueError("إجمالي المرفقات أكبر من 4 ميغابايت")
    return result, files


@public_bp.get("/<tenant>/<token>")
def public_form(tenant, token):
    link, company = public_link(tenant, token)
    if link.received >= link.max_submissions:
        abort(410, description="اكتمل العدد المسموح من الطلبات")
    response = render_template("hr/recruit_public.html", company=company, form=json.loads(link.snapshot), pin_required=bool(link.pin_hash))
    return response, 200, {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


@public_bp.post("/<tenant>/<token>")
def public_submit(tenant, token):
    link, _ = public_link(tenant, token)
    if request.content_length and request.content_length > 6 * 1024 * 1024:
        abort(413)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("website"):
        raise ValueError("بيانات الطلب غير صحيحة")
    ip_hash = hmac.new(str(current_app.secret_key).encode(), (request.remote_addr or "unknown").encode(), hashlib.sha256).hexdigest()
    attempts = HRRecruitAttempt.query.filter(HRRecruitAttempt.link_id == link.id, HRRecruitAttempt.ip_hash == ip_hash,
                                             HRRecruitAttempt.created_at >= datetime.utcnow() - timedelta(minutes=10)).count()
    if attempts >= 10:
        abort(429, description="محاولات كثيرة؛ انتظر عشر دقائق")
    HRRecruitAttempt.query.filter(HRRecruitAttempt.created_at < datetime.utcnow() - timedelta(days=1)).delete(synchronize_session=False)
    db.session.add(HRRecruitAttempt(link_id=link.id, ip_hash=ip_hash))
    db.session.commit()
    if link.pin_hash and not check_password_hash(link.pin_hash, text(body.get("pin", ""), limit=50)):
        abort(403, description="رمز الدخول غير صحيح")
    if body.get("action") == "unlock":
        return jsonify(html=render_template("hr/recruit_fields.html", form=json.loads(link.snapshot)))
    submission_id = uuid(body.get("id"))
    answers, files = validate_answers(json.loads(link.snapshot), body.get("answers"))
    digest = fingerprint(answers)
    previous = HRApplication.query.filter_by(link_id=link.id, submission_id=submission_id).first()
    if previous:
        if previous.fingerprint != digest:
            abort(409, description="معرّف الطلب مستخدم لبيانات مختلفة")
        return jsonify(success=True, receipt=submission_id)
    changed = db.session.query(HRRecruitLink).filter(HRRecruitLink.id == link.id, HRRecruitLink.active.is_(True),
        HRRecruitLink.expires_at > datetime.utcnow(), HRRecruitLink.received < HRRecruitLink.max_submissions).update(
            {HRRecruitLink.received: HRRecruitLink.received + 1}, synchronize_session=False)
    if not changed:
        abort(410, description="انتهى استقبال الطلبات لهذا الرابط")
    row = HRApplication(link_id=link.id, submission_id=submission_id, fingerprint=digest, answers=json_text(answers))
    db.session.add(row)
    db.session.flush()
    for key, file in files.items():
        db.session.add(HRApplicantFile(application_id=row.id, field_key=key, **file))
    db.session.commit()
    return jsonify(success=True, receipt=submission_id)


@public_bp.errorhandler(ValueError)
@public_bp.errorhandler(TypeError)
def public_validation(error):
    db.session.rollback()
    return jsonify(success=False, error=str(error) if isinstance(error, ValueError) else "بيانات الطلب غير صحيحة"), 400


@public_bp.errorhandler(Exception)
def public_error(error):
    from werkzeug.exceptions import HTTPException
    from sqlalchemy.exc import IntegrityError
    db.session.rollback()
    if isinstance(error, HTTPException):
        return jsonify(success=False, error=error.description), error.code
    if isinstance(error, IntegrityError):
        return jsonify(success=False, error="سبق استقبال الطلب؛ أعد المحاولة بنفس معرّف الطلب"), 409
    current_app.logger.exception("Public recruitment failed")
    return jsonify(success=False, error="تعذّر إرسال الطلب؛ أعد المحاولة بنفس المعرّف"), 500
