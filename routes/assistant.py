# routes/assistant.py
from flask import Blueprint, render_template, request, jsonify, session, redirect, g
from extensions import db
from models.system_analytics import SystemAnalytics
from models.system_alert import SystemAlert
from models.assistant_memory import AssistantMemory
from models.ai_assistant_control import AIActionPlan, AIAuditRun, AIToolCallLog, AIUploadedFile
from models.employee import Employee
from models.invoice import Invoice
from models.customer import Customer
from models.product import Product
from utils.assistant_analyzer import AssistantAnalyzer
from utils.audit_accounting_integrity import audit_accounting_integrity
from utils.ai_assistant_service import (
    approve_action_plan,
    create_or_update_schedule,
    execute_action_plan,
    ensure_ai_assistant_schema,
    handle_chat_send,
    list_schedules,
    reject_action_plan,
    run_ai_audit,
    save_uploaded_file,
    validate_action_plan,
)
from utils.permission_checks import check_permission, guard_permission
from utils.plan_limits import get_plan, has_feature
from datetime import datetime, timedelta
from sqlalchemy import func
import json

assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")


@assistant_bp.before_request
def require_ai_assistant_plan():
    """المساعد الذكي متاح فقط لخطة الشركات (Enterprise)."""
    plan_key = session.get("plan_key", "basic")
    if getattr(g, "tenant", None):
        try:
            from models.tenant import Tenant as TenantModel
            t = TenantModel.query.first()
            if t and getattr(t, "plan_key", None):
                plan_key = t.plan_key
        except Exception:
            pass
    if not has_feature(plan_key, "ai_assistant"):
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"error": "upgrade_required", "message": "المساعد الذكي متاح في خطة الشركات فقط."}), 403
        plan = get_plan(plan_key)
        return render_template("upgrade_required.html", feature="ai_assistant", plan=plan), 403

# =====================================================
# AI Chat (Financial Consultant)
# =====================================================
@assistant_bp.route("/chat")
def chat():
    """صفحة محادثة المساعد المالي (متاحة لأي مستخدم مسجل)"""
    if "user_id" not in session:
        return redirect("/pos")
    ensure_ai_assistant_schema()
    denied = guard_permission("use_ai_assistant")
    if denied:
        return denied
    is_admin = session.get("role") == "admin"
    assistant_permissions = {
        "approve_ai_actions": is_admin or check_permission("approve_ai_actions"),
        "manage_ai_schedules": is_admin or check_permission("manage_ai_schedules"),
        "view_ai_audit_logs": is_admin or check_permission("view_ai_audit_logs"),
    }
    return render_template("assistant/chat.html", session=session, assistant_permissions=assistant_permissions)


def _require_assistant_json(permission_name: str = "use_ai_assistant"):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    ensure_ai_assistant_schema()
    denied = guard_permission(permission_name, json=True)
    if denied:
        return denied
    return None


def _require_ai_action_approval():
    denied = _require_assistant_json("approve_ai_actions")
    if denied:
        return denied
    if session.get("role") == "admin" or check_permission("approve_ai_actions"):
        return None
    return jsonify({"success": False, "error": "الموافقة والتنفيذ للأدمن فقط"}), 403


@assistant_bp.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    denied = _require_assistant_json("use_ai_assistant")
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "اكتب رسالة للمساعد"}), 400
    upload_ids = data.get("upload_ids") or []
    try:
        result = handle_chat_send(
            employee_id=session.get("user_id"),
            message=message,
            session_id=data.get("session_id"),
            upload_ids=upload_ids,
        )
        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@assistant_bp.route("/api/files/upload", methods=["POST"])
def api_file_upload():
    denied = _require_assistant_json("use_ai_assistant")
    if denied:
        return denied
    file = request.files.get("file")
    try:
        uploaded = save_uploaded_file(
            file,
            employee_id=session.get("user_id"),
            session_id=request.form.get("session_id", type=int),
        )
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "file": {
                    "id": uploaded.id,
                    "original_name": uploaded.original_name,
                    "status": uploaded.status,
                    "error_message": uploaded.error_message or "",
                    "preview": uploaded.get_preview(),
                },
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/action-plans/<int:plan_id>", methods=["GET"])
def api_get_action_plan(plan_id):
    denied = _require_assistant_json("use_ai_assistant")
    if denied:
        return denied
    plan = AIActionPlan.query.get_or_404(plan_id)
    return jsonify({"success": True, "plan": plan.to_dict()})


@assistant_bp.route("/api/action-plans/<int:plan_id>/approve", methods=["POST"])
def api_approve_action_plan(plan_id):
    denied = _require_ai_action_approval()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        plan = approve_action_plan(plan_id, employee_id=session.get("user_id"), note=data.get("note"))
        return jsonify({"success": True, "plan": plan.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/action-plans/<int:plan_id>/validate", methods=["POST"])
def api_validate_action_plan(plan_id):
    denied = _require_ai_action_approval()
    if denied:
        return denied
    try:
        validation = validate_action_plan(plan_id)
        return jsonify({"success": True, "validation": validation})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/action-plans/<int:plan_id>/execute", methods=["POST"])
def api_execute_action_plan(plan_id):
    denied = _require_ai_action_approval()
    if denied:
        return denied
    try:
        plan = execute_action_plan(plan_id, employee_id=session.get("user_id"))
        return jsonify({"success": True, "plan": plan.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/action-plans/<int:plan_id>/reject", methods=["POST"])
def api_reject_action_plan(plan_id):
    denied = _require_ai_action_approval()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        plan = reject_action_plan(plan_id, employee_id=session.get("user_id"), reason=data.get("reason"))
        return jsonify({"success": True, "plan": plan.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/schedules", methods=["GET", "POST"])
def api_schedules():
    permission = "manage_ai_schedules" if request.method == "POST" else "view_ai_audit_logs"
    denied = _require_assistant_json(permission)
    if denied:
        return denied
    if request.method == "GET":
        return jsonify({"success": True, "schedules": list_schedules()})
    data = request.get_json(silent=True) or {}
    try:
        schedule = create_or_update_schedule(data, employee_id=session.get("user_id"))
        return jsonify({"success": True, "schedule": schedule.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/schedules/<int:schedule_id>/run", methods=["POST"])
def api_run_schedule(schedule_id):
    denied = _require_assistant_json("manage_ai_schedules")
    if denied:
        return denied
    try:
        from models.ai_assistant_control import AIScheduledAudit

        schedule = AIScheduledAudit.query.get_or_404(schedule_id)
        run = run_ai_audit(audit_type=schedule.audit_type, schedule_id=schedule.id, employee_id=session.get("user_id"))
        return jsonify({"success": True, "run_id": run.id, "summary": run.summary, "result": run.get_result()})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@assistant_bp.route("/api/tool-logs", methods=["GET"])
def api_tool_logs():
    denied = _require_assistant_json("view_ai_audit_logs")
    if denied:
        return denied
    limit = request.args.get("limit", 80, type=int)
    limit = max(10, min(limit or 80, 300))
    rows = AIToolCallLog.query.order_by(AIToolCallLog.created_at.desc()).limit(limit).all()

    def loads(raw):
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    return jsonify(
        {
            "success": True,
            "logs": [
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "plan_id": row.plan_id,
                    "employee_id": row.employee_id,
                    "tool_name": row.tool_name,
                    "mode": row.mode,
                    "status": row.status,
                    "error_message": row.error_message or "",
                    "input": loads(row.input_json),
                    "output": loads(row.output_json),
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ],
        }
    )


@assistant_bp.route("/api/overview", methods=["GET"])
def api_ai_overview():
    denied = _require_assistant_json("view_ai_audit_logs")
    if denied:
        return denied
    plans = AIActionPlan.query.order_by(AIActionPlan.created_at.desc()).limit(8).all()
    runs = AIAuditRun.query.order_by(AIAuditRun.started_at.desc()).limit(8).all()
    logs = AIToolCallLog.query.order_by(AIToolCallLog.created_at.desc()).limit(12).all()
    alerts = (
        SystemAlert.query.filter_by(is_dismissed=False)
        .filter(SystemAlert.alert_type == "ai_audit")
        .order_by(SystemAlert.created_at.desc())
        .limit(8)
        .all()
    )
    return jsonify(
        {
            "success": True,
            "plans": [plan.to_dict(include_items=False) for plan in plans],
            "runs": [
                {
                    "id": run.id,
                    "run_type": run.run_type,
                    "status": run.status,
                    "summary": run.summary or "",
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                    "action_plan_id": run.action_plan_id,
                }
                for run in runs
            ],
            "logs": [
                {
                    "id": row.id,
                    "tool_name": row.tool_name,
                    "mode": row.mode,
                    "status": row.status,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "plan_id": row.plan_id,
                }
                for row in logs
            ],
            "alerts": [
                {
                    "id": alert.id,
                    "title": alert.title,
                    "message": alert.message,
                    "priority": alert.priority,
                    "created_at": alert.created_at.isoformat() if alert.created_at else None,
                }
                for alert in alerts
            ],
        }
    )

# =====================================================
# Assistant Dashboard
# =====================================================
@assistant_bp.route("/")
def dashboard():
    """لوحة تحكم المساعد - جاري التطوير"""
    # صفحة مقفلة - جاري التطوير
    return render_template("assistant/under_development.html", session=session)
    
    # جلب التحليلات النشطة
    active_analytics = SystemAnalytics.query.filter_by(
        status="active"
    ).order_by(
        SystemAnalytics.created_at.desc()
    ).limit(50).all()
    
    # جلب التنبيهات غير المقروءة
    unread_alerts = SystemAlert.query.filter_by(
        is_read=False,
        is_dismissed=False
    ).order_by(
        SystemAlert.created_at.desc()
    ).limit(20).all()
    
    # إحصائيات سريعة
    stats = {
        "total_analytics": SystemAnalytics.query.filter_by(status="active").count(),
        "critical_issues": SystemAnalytics.query.filter_by(
            status="active",
            severity="critical"
        ).count(),
        "warnings": SystemAnalytics.query.filter_by(
            status="active",
            severity="warning"
        ).count(),
        "unread_alerts": SystemAlert.query.filter_by(is_read=False).count()
    }
    
    return render_template(
        "assistant/dashboard.html",
        analytics=active_analytics,
        alerts=unread_alerts,
        stats=stats,
        session=session
    )

# =====================================================
# Run Analysis
# =====================================================
@assistant_bp.route("/analyze", methods=["POST"])
def run_analysis():
    """تشغيل تحليل شامل"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_role = session.get("role", "cashier")
    if current_role != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    try:
        # تشغيل التحليل
        analytics = AssistantAnalyzer.run_full_analysis()
        
        # حفظ النتائج
        saved = AssistantAnalyzer.save_analytics(analytics)
        
        return jsonify({
            "success": True,
            "message": f"تم تحليل {len(saved)} عنصر",
            "count": len(saved),
            "analytics": [a.to_dict() for a in saved]
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# Accounting Integrity Audit (JSON)
# =====================================================
@assistant_bp.route("/audit/accounting")
def audit_accounting():
    """تدقيق سلامة النظام المحاسبي وإرجاع تقرير JSON مفصل"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    if session.get("role", "cashier") != "admin":
        return jsonify({"error": "غير مصرح"}), 403

    limit = request.args.get("limit", 200, type=int)
    limit = max(10, min(limit, 2000))
    return jsonify(audit_accounting_integrity(limit=limit))

# =====================================================
# Get Analytics
# =====================================================
@assistant_bp.route("/analytics")
def get_analytics():
    """جلب التحليلات"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    status = request.args.get("status", "active")
    severity = request.args.get("severity")
    
    query = SystemAnalytics.query
    if status:
        query = query.filter_by(status=status)
    if severity:
        query = query.filter_by(severity=severity)
    
    analytics = query.order_by(
        SystemAnalytics.created_at.desc()
    ).limit(100).all()
    
    return jsonify({
        "success": True,
        "analytics": [a.to_dict() for a in analytics]
    })

# =====================================================
# Resolve Analytics
# =====================================================
@assistant_bp.route("/analytics/<int:analytics_id>/resolve", methods=["POST"])
def resolve_analytics(analytics_id):
    """حل/إغلاق تحليل"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    analytics = SystemAnalytics.query.get_or_404(analytics_id)
    analytics.status = "resolved"
    analytics.is_resolved = True
    analytics.resolved_at = datetime.utcnow()
    analytics.resolved_by = session.get("user_id")
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم حل التحليل"
    })

# =====================================================
# Dismiss Analytics
# =====================================================
@assistant_bp.route("/analytics/<int:analytics_id>/dismiss", methods=["POST"])
def dismiss_analytics(analytics_id):
    """تجاهل تحليل"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    analytics = SystemAnalytics.query.get_or_404(analytics_id)
    analytics.status = "dismissed"
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم تجاهل التحليل"
    })

# =====================================================
# Get Alerts
# =====================================================
@assistant_bp.route("/alerts")
def get_alerts():
    """جلب التنبيهات"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    is_read = request.args.get("is_read")
    query = SystemAlert.query.filter_by(is_dismissed=False)
    
    if is_read is not None:
        query = query.filter_by(is_read=is_read == "true")
    
    alerts = query.order_by(
        SystemAlert.created_at.desc()
    ).limit(50).all()
    
    return jsonify({
        "success": True,
        "alerts": [{
            "id": a.id,
            "alert_type": a.alert_type,
            "title": a.title,
            "message": a.message,
            "priority": a.priority,
            "is_read": a.is_read,
            "related_id": a.related_id,
            "related_type": a.related_type,
            "created_at": a.created_at.isoformat() if a.created_at else None
        } for a in alerts]
    })

# =====================================================
# Mark Alert as Read
# =====================================================
@assistant_bp.route("/alerts/<int:alert_id>/read", methods=["POST"])
def mark_alert_read(alert_id):
    """تحديد التنبيه كمقروء"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    alert = SystemAlert.query.get_or_404(alert_id)
    alert.is_read = True
    alert.read_at = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم تحديد التنبيه كمقروء"
    })

# =====================================================
# Dismiss Alert
# =====================================================
@assistant_bp.route("/alerts/<int:alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    """تجاهل تنبيه"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    alert = SystemAlert.query.get_or_404(alert_id)
    alert.is_dismissed = True
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم تجاهل التنبيه"
    })

# =====================================================
# Analyze Current Page
# =====================================================
@assistant_bp.route("/analyze-page", methods=["POST", "GET"])
def analyze_page():
    """تحليل الصفحة الحالية للبحث عن أخطاء"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    issues = []
    
    try:
        # 1. فحص الأخطاء الحسابية في الفواتير المرئية
        from utils.assistant_analyzer import AssistantAnalyzer
        financial_errors = AssistantAnalyzer.analyze_financial_errors()
        for error in financial_errors[:5]:  # أول 5 فقط
            issues.append({
                "type": "financial_error",
                "severity": "critical",
                "message": f"خطأ حسابي في الفاتورة #{error['invoice_id']}: الفرق {error['difference']} د.ع",
                "selector": f"[data-invoice-id='{error['invoice_id']}']",
                "invoice_id": error['invoice_id']
            })
        
        # 2. فحص المنتجات قليلة المخزون
        inventory_alerts = AssistantAnalyzer.analyze_inventory_alerts()
        for alert in inventory_alerts[:3]:  # أول 3 فقط
            if alert['type'] == 'out_of_stock':
                issues.append({
                    "type": "inventory",
                    "severity": "critical",
                    "message": f"المنتج '{alert['product_name']}' نفد من المخزون",
                    "selector": f"[data-product-id='{alert['product_id']}']",
                    "product_id": alert['product_id']
                })
            elif alert['type'] == 'low_stock':
                issues.append({
                    "type": "inventory",
                    "severity": "warning",
                    "message": f"المنتج '{alert['product_name']}' قليل المخزون ({alert['quantity']})",
                    "selector": f"[data-product-id='{alert['product_id']}']",
                    "product_id": alert['product_id']
                })
        
        # 3. فحص الفواتير المتأخرة
        payment_issues = AssistantAnalyzer.analyze_payment_issues()
        for issue in payment_issues:
            if issue.get('invoices'):
                for inv in issue['invoices'][:3]:  # أول 3 فقط
                    issues.append({
                        "type": "payment",
                        "severity": "warning",
                        "message": f"فاتورة #{inv['id']} متأخرة {inv['days_overdue']} يوم",
                        "selector": f"[data-invoice-id='{inv['id']}']",
                        "invoice_id": inv['id']
                    })
        
        return jsonify({
            "success": True,
            "issues": issues,
            "count": len(issues)
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "issues": []
        }), 500

# =====================================================
# Generate Report
# =====================================================
@assistant_bp.route("/report", methods=["POST"])
def generate_report():
    """إنشاء تقرير تلقائي"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    report_type = request.json.get("type", "daily")  # daily, weekly, monthly
    
    try:
        # تشغيل التحليل
        analytics = AssistantAnalyzer.run_full_analysis()
        
        # إحصائيات إضافية
        stats = {
            "total_invoices": db.session.query(func.count(Invoice.id)).scalar(),
            "total_customers": db.session.query(func.count(Customer.id)).scalar(),
            "total_products": db.session.query(func.count(Product.id)).scalar(),
        }
        
        # حساب المبيعات
        if report_type == "daily":
            start_date = datetime.utcnow().replace(hour=0, minute=0, second=0)
        elif report_type == "weekly":
            start_date = datetime.utcnow() - timedelta(days=7)
        else:  # monthly
            start_date = datetime.utcnow() - timedelta(days=30)
        
        sales = db.session.query(
            func.sum(Invoice.total).label('total'),
            func.count(Invoice.id).label('count')
        ).filter(
            Invoice.created_at >= start_date,
            Invoice.payment_status == "مسدد"
        ).first()
        
        stats["sales_total"] = sales.total or 0
        stats["sales_count"] = sales.count or 0
        
        # إحصائيات إضافية محسّنة
        stats["total_errors"] = len(AssistantAnalyzer.analyze_financial_errors())
        stats["total_alerts"] = len(AssistantAnalyzer.analyze_inventory_alerts())
        stats["total_predictions"] = len(AssistantAnalyzer.generate_predictions())
        
        # حساب الربح
        paid_invoices = Invoice.query.filter(
            Invoice.created_at >= start_date,
            Invoice.payment_status == "مسدد"
        ).all()
        
        total_cost = 0
        if paid_invoices:
            from utils.order_item_costs import exclude_delivery_fee_items

            invoice_ids = [inv.id for inv in paid_invoices]
            total_cost = db.session.query(
                func.sum(OrderItem.cost * OrderItem.quantity)
            ).filter(
                OrderItem.invoice_id.in_(invoice_ids),
                exclude_delivery_fee_items(OrderItem),
            ).scalar() or 0
        
        stats["total_cost"] = total_cost
        stats["profit"] = stats["sales_total"] - total_cost
        stats["profit_margin"] = (stats["profit"] / stats["sales_total"] * 100) if stats["sales_total"] > 0 else 0
        
        return jsonify({
            "success": True,
            "report": {
                "type": report_type,
                "generated_at": datetime.utcnow().isoformat(),
                "analytics": analytics,
                "stats": stats
            }
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# Auto Fix Errors
# =====================================================
@assistant_bp.route("/auto-fix", methods=["POST"])
def auto_fix_errors():
    """إصلاح تلقائي للأخطاء"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    current_role = session.get("role", "cashier")
    if current_role != "admin":
        return jsonify({"error": "غير مصرح - يجب أن تكون أدمن"}), 403
    
    try:
        fixes = AssistantAnalyzer.auto_fix_errors()
        
        return jsonify({
            "success": True,
            "fixes_applied": fixes,
            "count": len(fixes)
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# Get Auto Fix Suggestions
# =====================================================
@assistant_bp.route("/auto-fix-suggestions")
def get_auto_fix_suggestions():
    """الحصول على اقتراحات الإصلاح التلقائي"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    try:
        suggestions = AssistantAnalyzer.suggest_auto_fixes()
        
        return jsonify({
            "success": True,
            "suggestions": suggestions,
            "count": len(suggestions)
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# =====================================================
# Get Memory / Learning
# =====================================================
@assistant_bp.route("/memory")
def get_memory():
    """جلب ذاكرة المساعد"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    memory_type = request.args.get("type")
    query = AssistantMemory.query
    
    if memory_type:
        query = query.filter_by(memory_type=memory_type)
    
    memories = query.order_by(
        AssistantMemory.confidence.desc(),
        AssistantMemory.occurrence_count.desc()
    ).limit(50).all()
    
    return jsonify({
        "success": True,
        "memories": [m.to_dict() for m in memories]
    })

# =====================================================
# Verify Memory
# =====================================================
@assistant_bp.route("/memory/<int:memory_id>/verify", methods=["POST"])
def verify_memory(memory_id):
    """التحقق من ذاكرة (زيادة الثقة)"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    memory = AssistantMemory.query.get_or_404(memory_id)
    memory.is_verified = True
    memory.verified_by = session.get("user_id")
    memory.verified_at = datetime.utcnow()
    memory.confidence = min(100, memory.confidence + 20)
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "تم التحقق من الذاكرة"
    })

# =====================================================
# Get Intelligent Suggestions
# =====================================================
@assistant_bp.route("/suggestions")
def get_suggestions():
    """الحصول على اقتراحات ذكية"""
    if "user_id" not in session:
        return jsonify({"error": "غير مصرح"}), 403
    
    error_type = request.args.get("error_type")
    error_data_str = request.args.get("error_data")
    
    if not error_type or not error_data_str:
        return jsonify({"error": "نوع الخطأ والبيانات مطلوبة"}), 400
    
    try:
        error_data = json.loads(error_data_str)
        solutions = AssistantAnalyzer.get_suggested_solutions(error_type, error_data)
        
        return jsonify({
            "success": True,
            "solutions": solutions,
            "count": len(solutions)
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
