"""ربط مندوبي التوصيل بحسابات موظف ظل للمراسلة الموحدة."""

from __future__ import annotations

import secrets

from werkzeug.security import generate_password_hash

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from models.role import Permission, Role

AGENT_MESSAGING_ROLE = "delivery_agent_messaging"


def agent_employee_username(agent_id: int) -> str:
    return f"__da_{agent_id}__"


def _ensure_messaging_role() -> Role:
    perm = Permission.query.filter_by(name="view_messages").first()
    if not perm:
        perm = Permission(name="view_messages", description="رؤية واجهة المراسلة")
        db.session.add(perm)
        db.session.flush()

    role = Role.query.filter_by(name=AGENT_MESSAGING_ROLE).first()
    if not role:
        role = Role(name=AGENT_MESSAGING_ROLE, description="مندوب توصيل — مراسلة")
        db.session.add(role)
        db.session.flush()

    if perm not in role.permissions:
        role.permissions.append(perm)
    return role


def ensure_agent_employee(agent: DeliveryAgent | None) -> Employee | None:
    """ينشئ أو يحدّث موظفاً مرتبطاً بالمندوب لاستخدام نظام المراسلة."""
    if not agent or not agent.username:
        return None

    _ensure_messaging_role()
    messaging_role = Role.query.filter_by(name=AGENT_MESSAGING_ROLE).first()

    emp = None
    if getattr(agent, "employee_id", None):
        emp = Employee.query.get(agent.employee_id)

    if not emp:
        emp = Employee.query.filter_by(username=agent_employee_username(agent.id)).first()

    if not emp:
        emp = Employee(
            name=agent.name,
            username=agent_employee_username(agent.id),
            password=generate_password_hash(secrets.token_urlsafe(32)),
            role="cashier",
            is_active=bool(getattr(agent, "is_active", True)),
            shipping_company_id=getattr(agent, "shipping_company_id", None),
        )
        db.session.add(emp)
        db.session.flush()
    else:
        emp.name = agent.name
        emp.is_active = bool(getattr(agent, "is_active", True))
        if getattr(agent, "shipping_company_id", None) is not None:
            emp.shipping_company_id = agent.shipping_company_id

    if messaging_role and messaging_role not in emp.roles:
        emp.roles.append(messaging_role)

    if getattr(agent, "employee_id", None) != emp.id:
        agent.employee_id = emp.id

    db.session.commit()
    return emp


def bind_agent_messaging_session(session, agent: DeliveryAgent, tenant_slug: str) -> bool:
    """يربط جلسة المندوب بجلسة مراسلة الموظف."""
    emp = ensure_agent_employee(agent)
    if not emp or not emp.is_active:
        return False

    session["user_id"] = emp.id
    session["user_name"] = agent.name
    session["role"] = emp.role or "cashier"
    session["tenant_slug"] = tenant_slug
    session["agent_portal"] = True
    return True


def clear_agent_messaging_session(session) -> None:
    if not session.get("agent_portal"):
        return
    for key in ("user_id", "user_name", "role", "tenant_slug", "agent_portal"):
        session.pop(key, None)
