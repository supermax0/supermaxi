# routes/assistant.py
from flask import Blueprint, render_template, request, jsonify, session, redirect, g
from extensions import db
from models.system_analytics import SystemAnalytics
from models.system_alert import SystemAlert
from models.assistant_memory import AssistantMemory
from models.employee import Employee
from models.invoice import Invoice
from models.customer import Customer
from models.product import Product
from utils.assistant_analyzer import AssistantAnalyzer
from utils.audit_accounting_integrity import audit_accounting_integrity
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
    return render_template("assistant/chat.html", session=session)

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
            invoice_ids = [inv.id for inv in paid_invoices]
            total_cost = db.session.query(
                func.sum(OrderItem.cost * OrderItem.quantity)
            ).filter(
                OrderItem.invoice_id.in_(invoice_ids)
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
