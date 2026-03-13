from functools import wraps

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
    session,
)

from extensions import db
from models.ai_agent import (
    Agent,
    AgentWorkflow,
    AgentExecution,
    AgentExecutionLog,
    AgentComment,
)
from models.employee import Employee
from social_ai.workflow_engine import execute_workflow


autoposter_bp = Blueprint(
    "autoposter",
    __name__,
    url_prefix="/autoposter",
)


def require_autoposter_login(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get("user_id"):
            from flask import url_for, redirect

            return redirect(url_for("index.login") + "?next=" + request.path)
        return f(*args, **kwargs)

    return inner


# ============== صفحات واجهة AI Agent Builder ==============


@autoposter_bp.route("/")
@autoposter_bp.route("/dashboard")
def dashboard_redirect():
    """إبقاء المسار القديم لكن توجيهه مباشرة لواجهة AI Agent Builder."""
    from flask import redirect, url_for

    return redirect(url_for("autoposter.ai_agent_view"))


@autoposter_bp.route("/ai-agent")
def ai_agent_view():
    """واجهة AI Agent / Workflow Builder — بدون أي منطق نشر أو ربط صفحات."""
    return render_template("autoposter/ai_agent.html")


# ============== API: معلومات المستخدم الحالي ==============


@autoposter_bp.route("/api/me", methods=["GET"])
@require_autoposter_login
def api_me():
    emp = Employee.query.get(session.get("user_id"))
    if not emp:
        return jsonify({"error": "المستخدم غير موجود"}), 401
    return jsonify(
        {
            "id": emp.id,
            "email": getattr(emp, "username", None) or "",
            "display_name": emp.name or "مدير",
        }
    )


# ============== API: AI Agents ==============


@autoposter_bp.route("/api/agents", methods=["GET"])
@require_autoposter_login
def api_agents_list():
    tenant_slug = session.get("tenant_slug")
    q = Agent.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    agents = q.order_by(Agent.created_at.desc()).all()
    return jsonify({"agents": [a.to_dict() for a in agents]})


@autoposter_bp.route("/api/agents", methods=["POST"])
@require_autoposter_login
def api_agents_create():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "الاسم مطلوب"}), 400
    tenant_slug = session.get("tenant_slug")
    user_id = session.get("user_id")
    agent = Agent(
        tenant_slug=tenant_slug,
        user_id=user_id,
        name=name,
        description=(data.get("description") or "").strip() or None,
        default_model=(data.get("default_model") or "").strip() or None,
        instructions=(data.get("instructions") or "").strip() or None,
    )
    db.session.add(agent)
    db.session.commit()
    return jsonify({"success": True, "agent": agent.to_dict()})


# ============== API: Workflows ==============


@autoposter_bp.route("/workflows", methods=["GET"])
@autoposter_bp.route("/api/workflows", methods=["GET"])
@require_autoposter_login
def api_workflows_list():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is not None:
        w = AgentWorkflow.query.get(workflow_id)
        if not w:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify({"workflow": w.to_dict()})

    agent_id = request.args.get("agent_id", type=int)
    q = AgentWorkflow.query
    if agent_id:
        q = q.filter_by(agent_id=agent_id)
    workflows = q.order_by(AgentWorkflow.created_at.desc()).all()
    return jsonify({"workflows": [w.to_dict() for w in workflows]})


@autoposter_bp.route("/api/workflows/<int:workflow_id>", methods=["GET"])
@require_autoposter_login
def api_workflows_get(workflow_id: int):
    w = AgentWorkflow.query.get_or_404(workflow_id)
    return jsonify({"workflow": w.to_dict()})


@autoposter_bp.route("/api/workflows", methods=["POST"])
@require_autoposter_login
def api_workflows_create():
    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    name = (data.get("name") or "").strip()
    if not agent_id or not name:
        return jsonify({"success": False, "error": "agent_id والاسم مطلوبان"}), 400
    graph = data.get("graph") or {}
    w = AgentWorkflow(
        agent_id=agent_id,
        name=name,
        description=(data.get("description") or "").strip() or None,
        is_active=bool(data.get("is_active", True)),
        graph_json=graph,
    )
    db.session.add(w)
    db.session.commit()
    return jsonify({"success": True, "workflow": w.to_dict()})


@autoposter_bp.route("/api/workflows/<int:workflow_id>", methods=["PUT"])
@require_autoposter_login
def api_workflows_update(workflow_id: int):
    data = request.get_json() or {}
    w = AgentWorkflow.query.get_or_404(workflow_id)
    if "name" in data:
        w.name = (data.get("name") or "").strip() or w.name
    if "description" in data:
        w.description = (data.get("description") or "").strip() or None
    if "is_active" in data:
        w.is_active = bool(data.get("is_active"))
    if "graph" in data:
        w.graph_json = data.get("graph") or {}
    db.session.commit()
    return jsonify({"success": True, "workflow": w.to_dict()})


@autoposter_bp.route("/api/workflows/<int:workflow_id>", methods=["DELETE"])
@require_autoposter_login
def api_workflows_delete(workflow_id: int):
    """حذف Workflow واحد وكل ما يتعلّق به من تنفيذات وسجلات وتعليقات."""
    w = AgentWorkflow.query.get_or_404(workflow_id)

    executions = list(w.executions)
    for exe in executions:
        AgentComment.query.filter_by(handled_by_execution_id=exe.id).delete()
        AgentExecutionLog.query.filter_by(execution_id=exe.id).delete()
        db.session.delete(exe)

    db.session.delete(w)
    db.session.commit()
    return jsonify({"success": True})


@autoposter_bp.route("/api/workflows/<int:workflow_id>/run", methods=["POST"])
@require_autoposter_login
def api_workflows_run(workflow_id: int):
    """تشغيل Workflow باستخدام محرّك العقد الأساسي."""
    w = AgentWorkflow.query.get_or_404(workflow_id)
    exe = AgentExecution(workflow_id=w.id, status="running")
    db.session.add(exe)
    db.session.commit()
    execute_workflow(exe)
    db.session.refresh(exe)
    return jsonify({"success": True, "execution": exe.to_dict()})


# ============== API: Webhooks (WhatsApp / Telegram) ==============


@autoposter_bp.route("/api/webhooks/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Webhook مبسّط لرسائل واتساب: يتوقع workflow_id في كويري سترنج ويشغّل الوكيل."""
    data = request.get_json() or {}
    workflow_id = request.args.get("workflow_id", type=int)
    if not workflow_id:
        return (
            jsonify(
                {"success": False, "error": "workflow_id مطلوب في مسار الاستدعاء"}
            ),
            400,
        )

    w = AgentWorkflow.query.get_or_404(workflow_id)

    message_text = (
        data.get("message_text")
        or data.get("text")
        or data.get("body")
        or ""
    )
    from_phone = data.get("from_phone") or data.get("from") or ""
    message_id = data.get("message_id") or data.get("id") or ""

    exe = AgentExecution(workflow_id=w.id, status="running")
    db.session.add(exe)
    db.session.commit()

    ctx = {
        "message_text": message_text,
        "from_phone": from_phone,
        "message_id": message_id,
        "platform": "whatsapp",
    }

    execute_workflow(exe, initial_context=ctx)
    db.session.refresh(exe)
    return jsonify({"success": True, "execution": exe.to_dict()})


@autoposter_bp.route("/api/webhooks/telegram", methods=["POST"])
def telegram_webhook():
    """Webhook مبسّط لرسائل تيليجرام: يتوقع workflow_id في كويري سترنج ويشغّل الوكيل."""
    data = request.get_json() or {}
    workflow_id = request.args.get("workflow_id", type=int)
    if not workflow_id:
        return (
            jsonify(
                {"success": False, "error": "workflow_id مطلوب في مسار الاستدعاء"}
            ),
            400,
        )

    w = AgentWorkflow.query.get_or_404(workflow_id)

    message = data.get("message") or {}
    message_text = message.get("text") or data.get("message_text") or ""
    chat = message.get("chat") or {}
    chat_id = chat.get("id") or data.get("chat_id") or ""
    username = chat.get("username") or data.get("username") or ""

    exe = AgentExecution(workflow_id=w.id, status="running")
    db.session.add(exe)
    db.session.commit()

    ctx = {
        "message_text": message_text,
        "chat_id": chat_id,
        "username": username,
        "platform": "telegram",
    }

    execute_workflow(exe, initial_context=ctx)
    db.session.refresh(exe)
    return jsonify({"success": True, "execution": exe.to_dict()})


# ============== API: تسجيل الخروج من واجهة النشر القديمة ==============


@autoposter_bp.route("/api/logout", methods=["POST"])
@require_autoposter_login
def api_logout():
    session.pop("user_id", None)
    session.pop("tenant_slug", None)
    session.pop("role", None)
    return jsonify({"success": True})

