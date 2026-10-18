"""Actionable, live HR alerts. Visibility follows the recipient's HR scope."""
from datetime import datetime,timedelta
from extensions import db
from .common import BAGHDAD,can,people_query
from .models import HRPerson,HRLeave,HRAdvance,HRPayrollRun,HRPayrollItem,HRWorkRecord,HRPrivateDocument,HRApplication,HRRecruitLink,HRRecruitForm,HRCorrectionRequest


def alerts():
    now=datetime.utcnow()
    today=datetime.now(BAGHDAD).date()
    ids=people_query().with_entities(HRPerson.id)
    items=[]
    total=0
    def append(query,kind,title,tab,date_value,body=lambda row:row.name,person_id=lambda row:row.person_id,tone="warning",month=None):
        nonlocal total
        total+=query.count()
        model=query.column_descriptions[0]["entity"]
        for row in query.order_by(model.id.desc()).limit(8).all():
            on=date_value(row)
            items.append({"key":f"{kind}:{row.id}","type":kind,"title":title,"body":body(row),
                "date":on.isoformat()+"Z" if isinstance(on,datetime) else on.isoformat() if hasattr(on,"isoformat") else str(on),"tone":tone,"tab":tab,
                "person_id":person_id(row),"month":month(row) if month else None})
    names={p.id:p.name for p in people_query().all()}
    name=lambda row:names.get(row.person_id,"")
    if can("hr.attendance.approve"):
        append(HRCorrectionRequest.query.filter(HRCorrectionRequest.person_id.in_(ids),HRCorrectionRequest.status=="pending"),"correction","طلب تصحيح حضور ينتظر المراجعة","corrections",lambda r:r.created_at,name)
    if can("hr.leave.approve"):
        append(HRLeave.query.filter(HRLeave.person_id.in_(ids),HRLeave.status=="pending"),"leave","طلب إجازة ينتظر الموافقة","leave",lambda r:r.starts,name)
    if can("hr.advance.approve"):
        append(HRAdvance.query.filter(HRAdvance.person_id.in_(ids),HRAdvance.status=="pending"),"advance","سلفة تنتظر الموافقة","advances",lambda r:r.created_at,name)
    if can("hr.attendance.view"):
        append(HRWorkRecord.query.filter(HRWorkRecord.person_id.in_(ids),HRWorkRecord.check_in<now-timedelta(hours=16),HRWorkRecord.check_out.is_(None)),"open_clock","موظف لم يسجل الانصراف","attendance",lambda r:r.work_date,name)
        append(HRWorkRecord.query.filter(HRWorkRecord.person_id.in_(ids),HRWorkRecord.work_date==today,HRWorkRecord.late_minutes>0),"late","تأخر عن الوردية","attendance",lambda r:r.work_date,name,tone="info")
    if can("hr.payroll.pay"):
        payroll_month=lambda row:db.session.get(HRPayrollRun,row.run_id).month
        append(HRPayrollItem.query.join(HRPayrollRun,HRPayrollRun.id==HRPayrollItem.run_id).filter(HRPayrollItem.person_id.in_(ids),HRPayrollRun.status=="approved",HRPayrollItem.paid<HRPayrollItem.net),"salary_due","راتب معتمد لم يكتمل صرفه","payroll",payroll_month,name,month=payroll_month)
    if can("hr.payroll.review") or can("hr.payroll.approve"):
        hidden=db.session.query(HRPayrollItem.run_id).filter(~HRPayrollItem.person_id.in_(ids))
        visible=db.session.query(HRPayrollItem.run_id).filter(HRPayrollItem.person_id.in_(ids))
        statuses=[]
        if can("hr.payroll.review"):statuses.append("draft")
        if can("hr.payroll.approve"):statuses.append("reviewed")
        append(HRPayrollRun.query.filter(HRPayrollRun.id.in_(visible),~HRPayrollRun.id.in_(hidden),HRPayrollRun.status.in_(statuses)),"payroll_review","مسير يحتاج مراجعة أو اعتماد","payroll",lambda r:r.month,lambda r:r.month,lambda r:None,month=lambda r:r.month)
    if can("hr.resources.manage"):
        append(people_query().filter(HRPerson.status!="terminated",HRPerson.contract_end>=today,HRPerson.contract_end<=today+timedelta(days=30)),"contract","عقد يقترب من الانتهاء","resources",lambda r:r.contract_end,person_id=lambda r:r.id)
    if can("hr.documents.view"):
        append(HRPrivateDocument.query.filter(HRPrivateDocument.person_id.in_(ids),HRPrivateDocument.expires_on<=today+timedelta(days=30)),"document","مستند منتهي أو يقترب من الانتهاء","resources",lambda r:r.expires_on,lambda r:name(r)+" · "+r.title)
    if can("hr.recruitment.manage"):
        branches=people_query().with_entities(HRPerson.branch_id)
        append(HRApplication.query.join(HRRecruitLink,HRRecruitLink.id==HRApplication.link_id).join(HRRecruitForm,HRRecruitForm.id==HRRecruitLink.form_id).filter(HRRecruitForm.branch_id.in_(branches),HRApplication.status=="new"),"applicant","طلب توظيف جديد","recruitment",lambda r:r.created_at,lambda r:f"طلب #{r.id}",lambda r:None,tone="info")
    return {"items":items[:50],"total":total}
