"""Operational centers for labs, imaging, follow-ups and procedures."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy import func, or_

from extensions import db
from modules.clinics.models import (
    ClinicDoctor, ClinicFollowUp, ClinicFollowUpAttempt, ClinicInventoryItem,
    ClinicInventoryMovement, ClinicLabOrder, ClinicLabOrderItem, ClinicLabTest,
    ClinicPatient, ClinicProcedure, ClinicProcedureRecipeItem, ClinicRadiologyOrder,
    ClinicVisit, ClinicVisitBillLine, ClinicVisitProcedure,
)
from modules.clinics.service import _audit, _money, _parse_date, _today
from modules.clinics.service_ops import procedure_dict, set_procedure_specialties, stock_out_fefo

LAB_STATES = ("requested", "waiting_sample", "sample_collected", "processing", "result_ready", "reviewed", "completed", "cancelled", "invalid_sample", "repeat_required")
RAD_STATES = ("requested", "waiting_imaging", "imaging_done", "waiting_report", "report_ready", "reviewed", "completed", "cancelled", "repeat_required")
FOLLOW_STATES = ("scheduled", "due", "overdue", "contacted", "no_answer", "callback", "action_required", "completed", "cancelled")
PROCEDURE_STATES = ("requested", "scheduled", "in_progress", "completed", "cancelled", "not_done")


class StateConflict(ValueError):
    pass


def _person(tenant_id, patient_id):
    p = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=patient_id).first()
    return {"patient_name": p.full_name if p else "", "patient_file": p.file_number if p else "", "patient_phone": p.phone if p else "", "patient_age": (date.today().year - p.date_of_birth.year if p and p.date_of_birth else None), "patient_gender": p.gender if p else ""}


def _doctor(tenant_id, doctor_id):
    d = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=doctor_id).first() if doctor_id else None
    return d.full_name if d else ""


def _page(query, params):
    page = max(1, int(params.get("page") or 1)); per = min(100, max(1, int(params.get("per_page") or 25)))
    total = query.count(); return query.offset((page - 1) * per).limit(per).all(), {"page": page, "per_page": per, "total": total, "pages": max(1, (total + per - 1) // per)}


def _day_filter(query, column, value):
    if not value or value == "all": return query
    target = _today() if value == "today" else _parse_date(value)
    return query.filter(func.date(column) == target)


def lab_dict(row, tenant_id):
    items=[]
    for x in ClinicLabOrderItem.query.filter_by(tenant_id=tenant_id, order_id=row.id).all():
        t=ClinicLabTest.query.filter_by(tenant_id=tenant_id,id=x.test_id).first()
        items.append({"id":x.id,"test_id":x.test_id,"name":t.name if t else "","value":x.value or "","unit":x.unit or "","reference_range":x.reference_range or "","flag":x.abnormal_flag or "pending","status":x.status,"notes":x.notes or "","result_at":x.result_at.isoformat() if x.result_at else ""})
    flags=[x["flag"] for x in items]
    data={"id":row.id,"order_number":f"LAB-{row.id:05d}","patient_id":row.patient_id,"visit_id":row.visit_id,"doctor_id":row.doctor_id,"doctor_name":_doctor(tenant_id,row.doctor_id),"ordered_at":row.ordered_at.isoformat(),"priority":row.priority,"status":"requested" if row.status=="ordered" else row.status,"notes":row.notes or "","reviewed_at":row.reviewed_at.isoformat() if row.reviewed_at else "","items":items,"result_summary":"critical" if "critical" in flags else "abnormal" if any(x in flags for x in ("high","low","abnormal")) else "normal" if items and all(x not in ("pending","") for x in flags) else "pending"}
    data.update(_person(tenant_id,row.patient_id)); return data


def lab_center(tenant_id, params):
    q=ClinicLabOrder.query.filter_by(tenant_id=tenant_id).join(ClinicPatient,ClinicPatient.id==ClinicLabOrder.patient_id)
    term=str(params.get("q") or "").strip()
    if term:
        like=f"%{term}%"; q=q.outerjoin(ClinicDoctor,ClinicDoctor.id==ClinicLabOrder.doctor_id).filter(or_(ClinicPatient.full_name.ilike(like),ClinicPatient.file_number.ilike(like),ClinicPatient.phone.ilike(like),ClinicDoctor.full_name.ilike(like),func.printf("LAB-%05d",ClinicLabOrder.id).ilike(like)))
    if params.get("status"):
        q=q.filter(ClinicLabOrder.status.in_(("requested","ordered")) if params["status"]=="requested" else ClinicLabOrder.status==params["status"])
    if params.get("doctor_id"): q=q.filter(ClinicLabOrder.doctor_id==int(params["doctor_id"]))
    if params.get("priority"): q=q.filter(ClinicLabOrder.priority==params["priority"])
    q=_day_filter(q,ClinicLabOrder.ordered_at,params.get("date"))
    rows,meta=_page(q.order_by(ClinicLabOrder.ordered_at.desc()),params)
    today=func.date(ClinicLabOrder.ordered_at)==_today(); base=ClinicLabOrder.query.filter_by(tenant_id=tenant_id)
    stats={"today":base.filter(today).count(),"waiting_sample":base.filter(ClinicLabOrder.status.in_(("requested","ordered","waiting_sample"))).count(),"processing":base.filter(ClinicLabOrder.status.in_(("sample_collected","processing"))).count(),"result_ready":base.filter_by(status="result_ready").count(),"reviewed":base.filter_by(status="reviewed").count(),"completed":base.filter_by(status="completed").count()}
    return {"items":[lab_dict(x,tenant_id) for x in rows],"stats":stats,**meta}


def transition_lab(tenant_id, order_id, payload, actor_id=None):
    row=ClinicLabOrder.query.filter_by(tenant_id=tenant_id,id=order_id).first()
    if not row: raise ValueError("طلب التحليل غير موجود")
    expected=payload.get("expected_status"); current="requested" if row.status=="ordered" else row.status
    if expected and expected!=current: raise StateConflict("تم تحديث هذا السجل بواسطة مستخدم آخر")
    new=str(payload.get("status") or "")
    if new not in LAB_STATES: raise ValueError("حالة التحليل غير صالحة")
    old=current; row.status=new; row.updated_at=datetime.utcnow()
    if new=="reviewed": row.reviewed_at=datetime.utcnow()
    if new in ("result_ready","reviewed","completed"):
        for item in ClinicLabOrderItem.query.filter_by(tenant_id=tenant_id,order_id=row.id).all():
            if not item.value: raise ValueError("أدخل جميع النتائج قبل اعتماد الطلب")
    _audit(tenant_id,actor_id,"lab_order",row.id,"status",f"تحديث حالة التحليل: {old} → {new}",{"patient_id":row.patient_id,"visit_id":row.visit_id,"old_status":old,"new_status":new})
    return lab_dict(row,tenant_id)


def radiology_dict(row,tenant_id):
    data={"id":row.id,"order_number":f"RAD-{row.id:05d}","patient_id":row.patient_id,"visit_id":row.visit_id,"doctor_id":row.doctor_id,"doctor_name":_doctor(tenant_id,row.doctor_id),"modality":row.modality,"body_part":row.body_part or "","priority":row.priority,"status":"requested" if row.status=="ordered" else row.status,"price":row.price,"report":row.report or "","impression":row.impression or "","recommendations":row.recommendations or "","notes":row.notes or "","ordered_at":row.ordered_at.isoformat(),"performed_at":row.performed_at.isoformat() if row.performed_at else "","reported_at":row.reported_at.isoformat() if row.reported_at else "","reviewed_at":row.reviewed_at.isoformat() if row.reviewed_at else ""};data.update(_person(tenant_id,row.patient_id));return data


def radiology_center(tenant_id,params):
    q=ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id).join(ClinicPatient,ClinicPatient.id==ClinicRadiologyOrder.patient_id);term=str(params.get("q") or "").strip()
    if term:
        like=f"%{term}%";q=q.outerjoin(ClinicDoctor,ClinicDoctor.id==ClinicRadiologyOrder.doctor_id).filter(or_(ClinicPatient.full_name.ilike(like),ClinicPatient.file_number.ilike(like),ClinicPatient.phone.ilike(like),ClinicDoctor.full_name.ilike(like),ClinicRadiologyOrder.modality.ilike(like),ClinicRadiologyOrder.body_part.ilike(like)))
    for key,col in (("status",ClinicRadiologyOrder.status),("modality",ClinicRadiologyOrder.modality),("priority",ClinicRadiologyOrder.priority)):
        if params.get(key):q=q.filter(col.in_(("requested","ordered")) if key=="status" and params[key]=="requested" else col==params[key])
    if params.get("doctor_id"):q=q.filter(ClinicRadiologyOrder.doctor_id==int(params["doctor_id"]))
    q=_day_filter(q,ClinicRadiologyOrder.ordered_at,params.get("date"));rows,meta=_page(q.order_by(ClinicRadiologyOrder.ordered_at.desc()),params);base=ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id)
    stats={"today":base.filter(func.date(ClinicRadiologyOrder.ordered_at)==_today()).count(),"waiting_imaging":base.filter(ClinicRadiologyOrder.status.in_(("ordered","requested","waiting_imaging"))).count(),"imaging_done":base.filter_by(status="imaging_done").count(),"waiting_report":base.filter_by(status="waiting_report").count(),"report_ready":base.filter_by(status="report_ready").count(),"reviewed":base.filter(ClinicRadiologyOrder.status.in_(("reviewed","completed"))).count()}
    return {"items":[radiology_dict(x,tenant_id) for x in rows],"stats":stats,**meta}


def update_radiology_workflow(tenant_id,order_id,payload,actor_id=None):
    row=ClinicRadiologyOrder.query.filter_by(tenant_id=tenant_id,id=order_id).first()
    if not row:raise ValueError("طلب الأشعة غير موجود")
    current="requested" if row.status=="ordered" else row.status;expected=payload.get("expected_status")
    if expected and expected!=current:raise StateConflict("تم تحديث هذا السجل بواسطة مستخدم آخر")
    for field in ("report","impression","recommendations","notes"):
        if field in payload:setattr(row,field,str(payload.get(field) or "").strip() or None)
    new=str(payload.get("status") or current)
    if new not in RAD_STATES:raise ValueError("حالة الأشعة غير صالحة")
    if new in ("report_ready","reviewed","completed") and not row.report:raise ValueError("أضف التقرير قبل اعتماد الحالة")
    old=current;row.status=new;row.updated_at=datetime.utcnow()
    if new in ("imaging_done","waiting_report") and not row.performed_at:row.performed_at=datetime.utcnow()
    if new=="report_ready":row.reported_at=datetime.utcnow()
    if new=="reviewed":row.reviewed_at=datetime.utcnow()
    _audit(tenant_id,actor_id,"radiology_order",row.id,"status",f"تحديث الأشعة: {old} → {new}",{"patient_id":row.patient_id,"visit_id":row.visit_id,"old_status":old,"new_status":new})
    return radiology_dict(row,tenant_id)


FOLLOW_TYPES={"treatment_review":"مراجعة علاج","lab_result":"نتيجة تحليل","radiology_result":"نتيجة أشعة","post_procedure":"بعد إجراء طبي","post_operation":"بعد عملية","appointment_confirm":"تأكيد موعد","condition_check":"استفسار عن الحالة","administrative":"اتصال إداري","other":"أخرى"}


def followup_dict(row,tenant_id,with_attempts=False):
    state="overdue" if row.status in ("due","scheduled") and row.due_date<_today() else row.status
    data={"id":row.id,"patient_id":row.patient_id,"visit_id":row.visit_id,"doctor_id":row.doctor_id,"doctor_name":_doctor(tenant_id,row.doctor_id),"followup_type":row.followup_type,"followup_type_label":FOLLOW_TYPES.get(row.followup_type,"أخرى"),"due_date":row.due_date.isoformat(),"status":state,"notes":row.notes or "","outcome":row.outcome or "","last_attempt_at":row.last_attempt_at.isoformat() if row.last_attempt_at else "","contacted_at":row.contacted_at.isoformat() if row.contacted_at else ""};data.update(_person(tenant_id,row.patient_id))
    if with_attempts:data["attempts"]=[{"id":x.id,"contact_result":x.contact_result,"outcome":x.outcome or "","notes":x.notes or "","next_due_date":x.next_due_date.isoformat() if x.next_due_date else "","attempted_at":x.attempted_at.isoformat(),"created_by":x.created_by} for x in ClinicFollowUpAttempt.query.filter_by(tenant_id=tenant_id,followup_id=row.id).order_by(ClinicFollowUpAttempt.attempted_at.desc()).all()]
    return data


def followups_center(tenant_id,params):
    q=ClinicFollowUp.query.filter_by(tenant_id=tenant_id).join(ClinicPatient,ClinicPatient.id==ClinicFollowUp.patient_id);term=str(params.get("q") or "").strip()
    if term:
        like=f"%{term}%";q=q.filter(or_(ClinicPatient.full_name.ilike(like),ClinicPatient.file_number.ilike(like),ClinicPatient.phone.ilike(like),ClinicFollowUp.notes.ilike(like)))
    if params.get("status"):
        if params["status"]=="overdue":q=q.filter(ClinicFollowUp.due_date<_today(),ClinicFollowUp.status.in_(("due","scheduled")))
        else:q=q.filter(ClinicFollowUp.status==params["status"])
    if params.get("doctor_id"):q=q.filter(ClinicFollowUp.doctor_id==int(params["doctor_id"]))
    if params.get("followup_type"):q=q.filter(ClinicFollowUp.followup_type==params["followup_type"])
    rows,meta=_page(q.order_by(ClinicFollowUp.due_date.asc()),params);base=ClinicFollowUp.query.filter_by(tenant_id=tenant_id)
    stats={"due_today":base.filter(ClinicFollowUp.due_date==_today(),ClinicFollowUp.status.in_(("due","scheduled"))).count(),"overdue":base.filter(ClinicFollowUp.due_date<_today(),ClinicFollowUp.status.in_(("due","scheduled"))).count(),"upcoming":base.filter(ClinicFollowUp.due_date>_today(),ClinicFollowUp.status=="scheduled").count(),"contacted":base.filter_by(status="contacted").count(),"no_answer":base.filter_by(status="no_answer").count(),"action_required":base.filter_by(status="action_required").count()}
    return {"items":[followup_dict(x,tenant_id) for x in rows],"stats":stats,"types":FOLLOW_TYPES,**meta}


def create_followup(tenant_id,payload,actor_id=None):
    patient_id=int(payload.get("patient_id") or 0);visit_id=int(payload.get("visit_id") or 0) or None;doctor_id=int(payload.get("doctor_id") or 0) or None;due=_parse_date(payload.get("due_date"),"تاريخ الاستحقاق");kind=str(payload.get("followup_type") or "treatment_review")
    if not ClinicPatient.query.filter_by(tenant_id=tenant_id,id=patient_id).first():raise ValueError("المريض غير موجود")
    duplicate=ClinicFollowUp.query.filter_by(tenant_id=tenant_id,patient_id=patient_id,visit_id=visit_id,doctor_id=doctor_id,due_date=due,followup_type=kind).filter(ClinicFollowUp.status.notin_(("completed","cancelled"))).first()
    if duplicate:raise StateConflict(f"توجد متابعة مشابهة لهذا المريض|{duplicate.id}")
    row=ClinicFollowUp(tenant_id=tenant_id,patient_id=patient_id,visit_id=visit_id,doctor_id=doctor_id,due_date=due,followup_type=kind,status="scheduled" if due>_today() else "due",notes=str(payload.get("notes") or "").strip() or None,created_by=actor_id);db.session.add(row);db.session.flush();_audit(tenant_id,actor_id,"follow_up",row.id,"create","إنشاء متابعة",{"patient_id":patient_id,"visit_id":visit_id});return followup_dict(row,tenant_id)


def contact_followup(tenant_id,followup_id,payload,actor_id=None):
    row=ClinicFollowUp.query.filter_by(tenant_id=tenant_id,id=followup_id).first()
    if not row:raise ValueError("المتابعة غير موجودة")
    result=str(payload.get("contact_result") or "");outcome=str(payload.get("outcome") or "").strip() or None
    if not result:raise ValueError("نتيجة التواصل مطلوبة")
    next_due=_parse_date(payload.get("next_due_date"),"المتابعة القادمة") if payload.get("next_due_date") else None
    attempt=ClinicFollowUpAttempt(tenant_id=tenant_id,followup_id=row.id,patient_id=row.patient_id,contact_result=result,outcome=outcome,notes=str(payload.get("notes") or "").strip() or None,next_due_date=next_due,created_by=actor_id);db.session.add(attempt);row.last_attempt_at=datetime.utcnow();row.outcome=outcome
    if result=="answered":row.status="action_required" if outcome in ("needs_review","needs_appointment","needs_doctor","needs_lab","needs_radiology") else "contacted";row.contacted_at=datetime.utcnow()
    elif result in ("no_answer","closed","busy"):row.status="callback" if next_due else "no_answer"
    elif result=="invalid_number":row.status="action_required"
    if next_due:row.due_date=next_due
    _audit(tenant_id,actor_id,"follow_up",row.id,"contact","تسجيل محاولة تواصل",{"patient_id":row.patient_id,"visit_id":row.visit_id,"contact_result":result,"outcome":outcome});return followup_dict(row,tenant_id,True)


def execution_dict(row,tenant_id):
    proc=ClinicProcedure.query.filter_by(tenant_id=tenant_id,id=row.procedure_id).first();visit=ClinicVisit.query.filter_by(tenant_id=tenant_id,id=row.visit_id).first();data={"id":row.id,"visit_id":row.visit_id,"patient_id":row.patient_id,"doctor_id":row.doctor_id,"doctor_name":_doctor(tenant_id,row.doctor_id),"procedure_id":row.procedure_id,"procedure_name":proc.name if proc else "","status":row.status or "requested","quantity":float(row.quantity or 1),"price":row.price,"notes":row.notes or "","result":row.result or "","performed_at":row.performed_at.isoformat(),"started_at":row.started_at.isoformat() if row.started_at else "","completed_at":row.completed_at.isoformat() if row.completed_at else "","inventory_deducted":bool(row.inventory_deducted),"recipe":procedure_dict(proc,tenant_id)["recipe"] if proc else []};data.update(_person(tenant_id,row.patient_id));return data


def procedures_center(tenant_id,params,include_financial=False):
    tab=params.get("tab") or "catalog"
    if tab=="performed":
        q=ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id).join(ClinicPatient,ClinicPatient.id==ClinicVisitProcedure.patient_id);term=str(params.get("q") or "").strip()
        if term:
            like=f"%{term}%";q=q.join(ClinicProcedure,ClinicProcedure.id==ClinicVisitProcedure.procedure_id).filter(or_(ClinicPatient.full_name.ilike(like),ClinicPatient.file_number.ilike(like),ClinicProcedure.name.ilike(like)))
        if params.get("status"):q=q.filter(ClinicVisitProcedure.status==params["status"])
        rows,meta=_page(q.order_by(ClinicVisitProcedure.performed_at.desc()),params);items=[execution_dict(x,tenant_id) for x in rows]
    else:
        q=ClinicProcedure.query.filter_by(tenant_id=tenant_id);term=str(params.get("q") or "").strip()
        if term:q=q.filter(ClinicProcedure.name.ilike(f"%{term}%"))
        if params.get("active") in ("0","1"):q=q.filter(ClinicProcedure.active==(params["active"]=="1"))
        if params.get("category"):q=q.filter(ClinicProcedure.category==params["category"])
        if params.get("consumes_inventory") in ("0","1"):q=q.filter(ClinicProcedure.consumes_inventory==(params["consumes_inventory"]=="1"))
        rows,meta=_page(q.order_by(ClinicProcedure.name.asc()),params);items=[procedure_dict(x,tenant_id) for x in rows]
    today_exec=ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id).filter(func.date(ClinicVisitProcedure.performed_at)==_today())
    stats={"total":ClinicProcedure.query.filter_by(tenant_id=tenant_id).count(),"active":ClinicProcedure.query.filter_by(tenant_id=tenant_id,active=True).count(),"performed_today":today_exec.count(),"inventory":ClinicProcedure.query.filter_by(tenant_id=tenant_id,consumes_inventory=True).count()}
    if include_financial:
        stats["revenue_today"]=sum(x.price for x in today_exec.filter_by(status="completed").all())
    return {"items":items,"stats":stats,"tab":tab,**meta}


def save_procedure(tenant_id,payload,actor_id=None,procedure_id=None):
    row=ClinicProcedure.query.filter_by(tenant_id=tenant_id,id=procedure_id).first() if procedure_id else ClinicProcedure(tenant_id=tenant_id,created_by=actor_id)
    if procedure_id and not row:raise ValueError("الإجراء غير موجود")
    name=str(payload.get("name") or row.name or "").strip()
    if not name:raise ValueError("اسم الإجراء مطلوب")
    row.name=name;row.category=str(payload.get("category") or "").strip() or None;row.price=_money(payload.get("price"));row.duration_minutes=max(1,int(payload.get("duration_minutes") or 15));row.description=str(payload.get("description") or "").strip() or None;row.available_for_booking=bool(payload.get("available_for_booking"));row.creates_charge=bool(payload.get("creates_charge",True));row.active=bool(payload.get("active",True));row.consumes_inventory=bool(payload.get("recipe"));row.updated_by=actor_id;db.session.add(row);db.session.flush();set_procedure_specialties(tenant_id,row.id,payload.get("specialty_ids") or []);ClinicProcedureRecipeItem.query.filter_by(tenant_id=tenant_id,procedure_id=row.id).delete()
    for x in payload.get("recipe") or []:
        db.session.add(ClinicProcedureRecipeItem(tenant_id=tenant_id,procedure_id=row.id,item_id=int(x["item_id"]),quantity=Decimal(str(x.get("quantity") or 1))))
    _audit(tenant_id,actor_id,"procedure",row.id,"update" if procedure_id else "create",f"حفظ إجراء {row.name}");db.session.flush();return procedure_dict(row,tenant_id)


def add_execution(tenant_id,payload,actor_id=None):
    visit=ClinicVisit.query.filter_by(tenant_id=tenant_id,id=int(payload.get("visit_id") or 0)).first();proc=ClinicProcedure.query.filter_by(tenant_id=tenant_id,id=int(payload.get("procedure_id") or 0),active=True).first()
    if not visit or not proc:raise ValueError("الزيارة أو الإجراء غير موجود")
    qty=Decimal(str(payload.get("quantity") or 1));price=_money(payload.get("price") if payload.get("price") not in (None,"") else proc.price)*int(qty)
    row=ClinicVisitProcedure(tenant_id=tenant_id,visit_id=visit.id,patient_id=visit.patient_id,doctor_id=int(payload.get("doctor_id") or visit.doctor_id or 0) or None,procedure_id=proc.id,status="requested",quantity=qty,notes=str(payload.get("notes") or "").strip() or None,price=price,created_by=actor_id);db.session.add(row);db.session.flush()
    _audit(tenant_id,actor_id,"visit_procedure",row.id,"create","إضافة إجراء للزيارة",{"patient_id":visit.patient_id,"visit_id":visit.id});return execution_dict(row,tenant_id)


def transition_execution(tenant_id,execution_id,payload,actor_id=None):
    row=ClinicVisitProcedure.query.filter_by(tenant_id=tenant_id,id=execution_id).with_for_update().first()
    if not row:raise ValueError("الإجراء المنفذ غير موجود")
    expected=payload.get("expected_status")
    if expected and expected!=row.status:raise StateConflict("تم تحديث هذا السجل بواسطة مستخدم آخر")
    new=str(payload.get("status") or "")
    if new not in PROCEDURE_STATES:raise ValueError("حالة الإجراء غير صالحة")
    old=row.status
    if new=="completed" and not row.inventory_deducted:
        existing=ClinicInventoryMovement.query.filter_by(tenant_id=tenant_id,reference_type="visit_procedure",reference_id=row.id).first()
        if not existing:
            for line in ClinicProcedureRecipeItem.query.filter_by(tenant_id=tenant_id,procedure_id=row.procedure_id).all():stock_out_fefo(tenant_id,line.item_id,Decimal(str(line.quantity))*Decimal(str(row.quantity or 1)),reference_type="visit_procedure",reference_id=row.id,actor_id=actor_id,notes="استهلاك إجراء طبي")
        row.inventory_deducted=True;row.inventory_consumed_at=datetime.utcnow()
    row.status=new;row.updated_at=datetime.utcnow()
    if new=="in_progress" and not row.started_at:row.started_at=datetime.utcnow()
    if new=="completed":row.completed_at=datetime.utcnow()
    if new in ("cancelled","not_done"):row.cancelled_at=datetime.utcnow()
    _audit(tenant_id,actor_id,"visit_procedure",row.id,"status",f"تحديث الإجراء: {old} → {new}",{"patient_id":row.patient_id,"visit_id":row.visit_id,"old_status":old,"new_status":new,"inventory_consumed":bool(row.inventory_deducted)});return execution_dict(row,tenant_id)
