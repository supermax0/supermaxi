from sqlalchemy import update
from extensions import db


def transition(document,allowed,target):
    """Claim lifecycle before physical mutations, including receive/cancel races."""
    from modules.finance.common import today
    from utils.financial_period_guard import assert_date_period_open,PeriodClosedError
    try:assert_date_period_open(today(),'تحويل المخزون')
    except PeriodClosedError as error:raise ValueError(str(error)) from None
    model=type(document)
    previous=document.status
    if previous not in allowed:raise ValueError("حالة التحويل تغيرت؛ حدّث السند قبل التسجيل")
    result=db.session.execute(update(model).where(model.id==document.id,model.status==previous).values(
        status=target).execution_options(synchronize_session=False))
    if result.rowcount!=1:raise ValueError("تمت معالجة التحويل من جهاز آخر؛ حدّث السند")
    db.session.expire(document,['status'])

