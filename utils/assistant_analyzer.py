# utils/assistant_analyzer.py
"""
نظام تحليل ذكي متقدم للنظام
يقوم بفحص الأخطاء الحسابية والتنبيهات والأنماط
"""
from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.customer import Customer
from models.employee import Employee
from models.system_analytics import SystemAnalytics
from models.system_alert import SystemAlert
from models.assistant_memory import AssistantMemory
from sqlalchemy import func, and_, or_, extract
from datetime import datetime, timedelta
import json
import statistics

class AssistantAnalyzer:
    """محلل النظام الذكي المتقدم"""
    
    @staticmethod
    def analyze_financial_errors():
        """فحص الأخطاء الحسابية في الفواتير (محسّن)"""
        errors = []
        
        # 1. فحص الفواتير التي مجموع عناصرها لا يساوي الإجمالي
        invoices = Invoice.query.all()
        for invoice in invoices:
            items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
            
            if not items:
                # فاتورة بدون عناصر
                errors.append({
                    "type": "empty_invoice",
                    "invoice_id": invoice.id,
                    "invoice_total": invoice.total,
                    "calculated_total": 0,
                    "difference": invoice.total,
                    "customer": invoice.customer_name,
                    "date": invoice.created_at.isoformat() if invoice.created_at else None,
                    "severity": "critical"
                })
                continue
            
            calculated_total = sum(item.price * item.quantity for item in items)
            difference = abs(calculated_total - invoice.total)
            
            if difference > 1:  # تفاوت أكثر من 1 دينار
                # تحديد مستوى الخطورة
                severity = "critical" if difference > 1000 else "warning"
                
                errors.append({
                    "type": "total_mismatch",
                    "invoice_id": invoice.id,
                    "invoice_total": invoice.total,
                    "calculated_total": calculated_total,
                    "difference": difference,
                    "customer": invoice.customer_name,
                    "date": invoice.created_at.isoformat() if invoice.created_at else None,
                    "severity": severity,
                    "items_count": len(items)
                })
        
        return errors
    
    @staticmethod
    def analyze_inventory_alerts():
        """فحص تنبيهات المخزون (محسّن)"""
        alerts = []
        
        # 1. منتجات نفدت من المخزون
        out_of_stock = Product.query.filter(Product.quantity <= 0).all()
        for product in out_of_stock:
            # فحص المبيعات الأخيرة لهذا المنتج
            recent_sales = db.session.query(func.sum(OrderItem.quantity)).join(
                Invoice
            ).filter(
                OrderItem.product_id == product.id,
                Invoice.created_at >= datetime.utcnow() - timedelta(days=30)
            ).scalar() or 0
            
            alerts.append({
                "type": "out_of_stock",
                "product_id": product.id,
                "product_name": product.name,
                "quantity": product.quantity,
                "recent_sales": recent_sales,
                "severity": "critical",
                "recommendation": f"نفد المخزون. المبيعات الشهرية: {recent_sales} - يُنصح بإعادة التخزين"
            })
        
        # 2. منتجات قليلة المخزون (أقل من 10)
        low_stock = Product.query.filter(
            and_(Product.quantity > 0, Product.quantity < 10)
        ).all()
        for product in low_stock:
            # حساب معدل الاستهلاك
            monthly_sales = db.session.query(func.sum(OrderItem.quantity)).join(
                Invoice
            ).filter(
                OrderItem.product_id == product.id,
                Invoice.created_at >= datetime.utcnow() - timedelta(days=30)
            ).scalar() or 0
            
            days_remaining = (product.quantity / (monthly_sales / 30)) if monthly_sales > 0 else 999
            
            alerts.append({
                "type": "low_stock",
                "product_id": product.id,
                "product_name": product.name,
                "quantity": product.quantity,
                "monthly_sales": monthly_sales,
                "days_remaining": int(days_remaining),
                "severity": "warning" if days_remaining < 7 else "info",
                "recommendation": f"مخزون منخفض. متبقي {int(days_remaining)} يوم تقريباً"
            })
        
        return alerts
    
    @staticmethod
    def analyze_sales_trends():
        """تحليل اتجاهات المبيعات (محسّن)"""
        trends = []
        
        # حساب المبيعات اليومية للأسبوع الماضي
        week_ago = datetime.utcnow() - timedelta(days=7)
        daily_sales = db.session.query(
            func.date(Invoice.created_at).label('date'),
            func.sum(Invoice.total).label('total'),
            func.count(Invoice.id).label('count')
        ).filter(
            Invoice.created_at >= week_ago,
            Invoice.payment_status == "مسدد"
        ).group_by(
            func.date(Invoice.created_at)
        ).all()
        
        if len(daily_sales) >= 2:
            # حساب الاتجاه
            recent_avg = sum([s.total for s in daily_sales[-3:]]) / min(3, len(daily_sales[-3:]))
            older_avg = sum([s.total for s in daily_sales[:-3]]) / max(1, len(daily_sales[:-3]))
            
            if recent_avg < older_avg * 0.8:  # انخفاض أكثر من 20%
                trends.append({
                    "type": "sales_decline",
                    "message": f"انخفاض في المبيعات: {((recent_avg - older_avg) / older_avg * 100):.1f}%",
                    "recent_avg": recent_avg,
                    "older_avg": older_avg,
                    "severity": "warning"
                })
            elif recent_avg > older_avg * 1.2:  # زيادة أكثر من 20%
                trends.append({
                    "type": "sales_increase",
                    "message": f"زيادة في المبيعات: {((recent_avg - older_avg) / older_avg * 100):.1f}%",
                    "recent_avg": recent_avg,
                    "older_avg": older_avg,
                    "severity": "success"
                })
        
        return trends
    
    @staticmethod
    def analyze_payment_issues():
        """فحص مشاكل الدفع (محسّن)"""
        issues = []
        
        # فواتير غير مسددة لأكثر من 30 يوم
        month_ago = datetime.utcnow() - timedelta(days=30)
        overdue_invoices = Invoice.query.filter(
            and_(
                Invoice.payment_status != "مسدد",
                Invoice.payment_status != "ملغي",
                Invoice.created_at < month_ago
            )
        ).all()
        
        total_overdue = sum(inv.total for inv in overdue_invoices)
        
        if overdue_invoices:
            issues.append({
                "type": "overdue_payments",
                "count": len(overdue_invoices),
                "total_amount": total_overdue,
                "severity": "critical" if total_overdue > 100000 else "warning",
                "invoices": [{
                    "id": inv.id,
                    "customer": inv.customer_name,
                    "amount": inv.total,
                    "days_overdue": (datetime.utcnow() - inv.created_at).days if inv.created_at else 0
                } for inv in overdue_invoices[:10]]  # أول 10 فقط
            })
        
        return issues
    
    @staticmethod
    def analyze_customer_behavior():
        """تحليل سلوك العملاء (محسّن)"""
        insights = []
        
        # عملاء نشطون (أكثر من 5 طلبات)
        active_customers = db.session.query(
            Customer.id,
            Customer.name,
            func.count(Invoice.id).label('order_count'),
            func.sum(Invoice.total).label('total_spent')
        ).join(Invoice).group_by(Customer.id).having(
            func.count(Invoice.id) >= 5
        ).all()
        
        if active_customers:
            insights.append({
                "type": "active_customers",
                "count": len(active_customers),
                "customers": [{
                    "id": c.id,
                    "name": c.name,
                    "order_count": c.order_count,
                    "total_spent": c.total_spent or 0
                } for c in active_customers[:10]]
            })
        
        # عملاء لم يشتروا منذ 90 يوم
        three_months_ago = datetime.utcnow() - timedelta(days=90)
        inactive_customers = db.session.query(Customer).filter(
            ~Customer.invoices.any(Invoice.created_at >= three_months_ago)
        ).limit(10).all()
        
        if inactive_customers:
            insights.append({
                "type": "inactive_customers",
                "count": len(inactive_customers),
                "message": f"{len(inactive_customers)} عميل لم يشتروا منذ 90 يوم"
            })
        
        return insights
    
    @staticmethod
    def analyze_patterns():
        """تحليل أنماط متقدم - يتعلم من البيانات"""
        patterns = []
        
        # نمط 1: أوقات الذروة في المبيعات
        hourly_sales = db.session.query(
            extract('hour', Invoice.created_at).label('hour'),
            func.count(Invoice.id).label('count'),
            func.sum(Invoice.total).label('total')
        ).filter(
            Invoice.created_at >= datetime.utcnow() - timedelta(days=30),
            Invoice.payment_status == "مسدد"
        ).group_by(
            extract('hour', Invoice.created_at)
        ).all()
        
        if hourly_sales:
            max_hour = max(hourly_sales, key=lambda x: x.total or 0)
            min_hour = min(hourly_sales, key=lambda x: x.total or 0)
            
            if max_hour.total and min_hour.total and max_hour.total > min_hour.total * 2:
                patterns.append({
                    "type": "sales_pattern",
                    "title": f"ساعة الذروة: {int(max_hour.hour)}:00",
                    "description": f"أعلى مبيعات في الساعة {int(max_hour.hour)}:00 ({max_hour.total:,.0f} د.ع). يُنصح بزيادة الموظفين في هذا الوقت.",
                    "severity": "info",
                    "related_data": {
                        "peak_hour": int(max_hour.hour),
                        "peak_sales": max_hour.total,
                        "low_hour": int(min_hour.hour),
                        "low_sales": min_hour.total
                    }
                })
        
        # نمط 2: أيام الأسبوع الأكثر مبيعاً
        weekday_sales = db.session.query(
            extract('dow', Invoice.created_at).label('weekday'),
            func.count(Invoice.id).label('count'),
            func.sum(Invoice.total).label('total')
        ).filter(
            Invoice.created_at >= datetime.utcnow() - timedelta(days=90),
            Invoice.payment_status == "مسدد"
        ).group_by(
            extract('dow', Invoice.created_at)
        ).all()
        
        if weekday_sales:
            weekday_names = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
            best_day = max(weekday_sales, key=lambda x: x.total or 0)
            if best_day.total:
                patterns.append({
                    "type": "sales_pattern",
                    "title": f"أفضل يوم مبيعات: {weekday_names[int(best_day.weekday)]}",
                    "description": f"متوسط المبيعات في {weekday_names[int(best_day.weekday)]}: {best_day.total / (best_day.count or 1):,.0f} د.ع لكل فاتورة",
                    "severity": "success",
                    "related_data": {
                        "best_day": weekday_names[int(best_day.weekday)],
                        "avg_per_invoice": best_day.total / (best_day.count or 1)
                    }
                })
        
        # نمط 3: منتجات مبيعها معاً (Basket Analysis)
        product_pairs = {}
        invoices_with_items = db.session.query(Invoice.id).join(OrderItem).filter(
            Invoice.created_at >= datetime.utcnow() - timedelta(days=60)
        ).distinct().all()
        
        for invoice_id in invoices_with_items[:100]:  # أول 100 فاتورة
            items = OrderItem.query.filter_by(invoice_id=invoice_id[0]).all()
            product_ids = [item.product_id for item in items if item.product_id]
            
            for i, pid1 in enumerate(product_ids):
                for pid2 in product_ids[i+1:]:
                    pair_key = f"{min(pid1, pid2)}_{max(pid1, pid2)}"
                    product_pairs[pair_key] = product_pairs.get(pair_key, 0) + 1
        
        # العثور على أزواج مبيعها معاً كثيراً
        frequent_pairs = [(k, v) for k, v in product_pairs.items() if v >= 5]
        if frequent_pairs:
            frequent_pairs.sort(key=lambda x: x[1], reverse=True)
            top_pair = frequent_pairs[0]
            pid1, pid2 = map(int, top_pair[0].split('_'))
            p1 = Product.query.get(pid1)
            p2 = Product.query.get(pid2)
            
            if p1 and p2:
                patterns.append({
                    "type": "product_pattern",
                    "title": f"منتجات مبيعها معاً: {p1.name} و {p2.name}",
                    "description": f"تم بيع هذين المنتجين معاً {top_pair[1]} مرة. يُنصح بوضعهما قريبين من بعض.",
                    "severity": "info",
                    "related_data": {
                        "product1": p1.name,
                        "product2": p2.name,
                        "co_occurrence": top_pair[1]
                    }
                })
        
        return patterns
    
    @staticmethod
    def generate_predictions():
        """تنبؤات ذكية بناءً على البيانات التاريخية"""
        predictions = []
        
        # تنبؤ 1: متى سينفد المخزون
        products = Product.query.filter(Product.quantity > 0, Product.quantity < 20).all()
        for product in products:
            # حساب معدل الاستهلاك الشهري
            monthly_sales = db.session.query(func.sum(OrderItem.quantity)).join(
                Invoice
            ).filter(
                OrderItem.product_id == product.id,
                Invoice.created_at >= datetime.utcnow() - timedelta(days=30)
            ).scalar() or 0
            
            if monthly_sales > 0:
                daily_consumption = monthly_sales / 30
                days_until_out = product.quantity / daily_consumption if daily_consumption > 0 else 999
                
                if days_until_out < 14:  # أقل من أسبوعين
                    predictions.append({
                        "type": "inventory_prediction",
                        "title": f"تنبؤ: {product.name} سينفد خلال {int(days_until_out)} يوم",
                        "description": f"بناءً على معدل المبيعات الحالي ({monthly_sales} شهرياً)، يُنصح بإعادة التخزين قريباً.",
                        "severity": "warning" if days_until_out < 7 else "info",
                        "related_data": {
                            "product_id": product.id,
                            "product_name": product.name,
                            "current_stock": product.quantity,
                            "predicted_days": int(days_until_out),
                            "monthly_sales": monthly_sales
                        }
                    })
        
        # تنبؤ 2: توقعات المبيعات للأسبوع القادم
        last_week_sales = db.session.query(func.sum(Invoice.total)).filter(
            Invoice.created_at >= datetime.utcnow() - timedelta(days=7),
            Invoice.payment_status == "مسدد"
        ).scalar() or 0
        
        week_before_sales = db.session.query(func.sum(Invoice.total)).filter(
            Invoice.created_at >= datetime.utcnow() - timedelta(days=14),
            Invoice.created_at < datetime.utcnow() - timedelta(days=7),
            Invoice.payment_status == "مسدد"
        ).scalar() or 0
        
        if last_week_sales > 0 and week_before_sales > 0:
            growth_rate = ((last_week_sales - week_before_sales) / week_before_sales) * 100
            predicted_next_week = last_week_sales * (1 + growth_rate / 100)
            
            predictions.append({
                "type": "sales_prediction",
                "title": f"توقع المبيعات للأسبوع القادم: {predicted_next_week:,.0f} د.ع",
                "description": f"بناءً على النمو الحالي ({growth_rate:.1f}%)، المتوقع أن تكون المبيعات {predicted_next_week:,.0f} د.ع",
                "severity": "success" if growth_rate > 0 else "warning",
                "related_data": {
                    "predicted_amount": predicted_next_week,
                    "growth_rate": growth_rate,
                    "last_week": last_week_sales
                }
            })
        
        # تنبؤ 3: عملاء محتملون للخسارة
        customers_at_risk = []
        all_customers = Customer.query.all()
        
        for customer in all_customers:
            # آخر طلب
            last_order = Invoice.query.filter_by(customer_id=customer.id).order_by(
                Invoice.created_at.desc()
            ).first()
            
            if last_order and last_order.created_at:
                days_since_last = (datetime.utcnow() - last_order.created_at).days
                
                # حساب متوسط الفترة بين الطلبات
                orders = Invoice.query.filter_by(customer_id=customer.id).order_by(
                    Invoice.created_at
                ).all()
                
                if len(orders) >= 2:
                    intervals = []
                    for i in range(1, len(orders)):
                        if orders[i].created_at and orders[i-1].created_at:
                            interval = (orders[i].created_at - orders[i-1].created_at).days
                            intervals.append(interval)
                    
                    if intervals:
                        avg_interval = statistics.mean(intervals)
                        
                        # إذا تجاوز الفترة المتوسطة بمرتين
                        if days_since_last > avg_interval * 2 and days_since_last > 30:
                            customers_at_risk.append({
                                "customer_id": customer.id,
                                "customer_name": customer.name,
                                "days_since_last": days_since_last,
                                "avg_interval": avg_interval
                            })
        
        if customers_at_risk:
            predictions.append({
                "type": "customer_prediction",
                "title": f"{len(customers_at_risk)} عميل في خطر الخسارة",
                "description": f"هؤلاء العملاء لم يشتروا منذ فترة طويلة. يُنصح بالتواصل معهم.",
                "severity": "warning",
                "affected_count": len(customers_at_risk),
                "related_data": customers_at_risk[:10]
            })
        
        return predictions
    
    @staticmethod
    def analyze_employee_performance():
        """تحليل أداء الموظفين (محسّن)"""
        insights = []
        
        employees = Employee.query.filter_by(is_active=True).all()
        for employee in employees:
            # إحصائيات الموظف
            employee_invoices = Invoice.query.filter_by(employee_id=employee.id).filter(
                Invoice.created_at >= datetime.utcnow() - timedelta(days=30)
            ).all()
            
            if employee_invoices:
                total_sales = sum(inv.total for inv in employee_invoices)
                avg_per_invoice = total_sales / len(employee_invoices)
                paid_count = sum(1 for inv in employee_invoices if inv.payment_status == "مسدد")
                payment_rate = (paid_count / len(employee_invoices)) * 100
                
                # مقارنة مع المتوسط
                all_avg = db.session.query(func.avg(Invoice.total)).filter(
                    Invoice.created_at >= datetime.utcnow() - timedelta(days=30)
                ).scalar() or 0
                
                if avg_per_invoice < all_avg * 0.7:
                    insights.append({
                        "type": "employee_insight",
                        "title": f"أداء {employee.name}: يحتاج تحسين",
                        "description": f"متوسط الفاتورة: {avg_per_invoice:,.0f} د.ع (أقل من المتوسط). معدل الدفع: {payment_rate:.1f}%",
                        "severity": "warning",
                        "related_data": {
                            "employee_id": employee.id,
                            "employee_name": employee.name,
                            "avg_per_invoice": avg_per_invoice,
                            "payment_rate": payment_rate
                        }
                    })
                elif avg_per_invoice > all_avg * 1.3:
                    insights.append({
                        "type": "employee_insight",
                        "title": f"أداء ممتاز: {employee.name}",
                        "description": f"متوسط الفاتورة: {avg_per_invoice:,.0f} د.ع (أعلى من المتوسط). معدل الدفع: {payment_rate:.1f}%",
                        "severity": "success",
                        "related_data": {
                            "employee_id": employee.id,
                            "employee_name": employee.name,
                            "avg_per_invoice": avg_per_invoice,
                            "payment_rate": payment_rate
                        }
                    })
        
        return insights
    
    @staticmethod
    def analyze_page_for_errors(page_url=None):
        """تحليل الصفحة الحالية للأخطاء (محسّن)"""
        issues = []
        
        # 1. فحص الأخطاء الحسابية
        financial_errors = AssistantAnalyzer.analyze_financial_errors()
        for error in financial_errors[:5]:  # أول 5 فقط
            issues.append({
                "type": "financial",
                "severity": error.get("severity", "warning"),
                "message": f"فاتورة #{error['invoice_id']}: تفاوت {error['difference']:,.0f} د.ع",
                "selector": f"[data-invoice-id='{error['invoice_id']}']",
                "invoice_id": error['invoice_id']
            })
        
        # 2. فحص المخزون
        inventory_alerts = AssistantAnalyzer.analyze_inventory_alerts()
        for alert in inventory_alerts[:5]:  # أول 5 فقط
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
        
        return issues
    
    @staticmethod
    def learn_from_error(error_type, error_data, solution=None):
        """تعلم من الأخطاء - حفظ في الذاكرة"""
        memory_key = f"{error_type}_{error_data.get('invoice_id') or error_data.get('product_id')}"
        
        existing = AssistantMemory.query.filter_by(
            memory_type=error_type,
            memory_key=memory_key
        ).first()
        
        if existing:
            # تحديث الذاكرة الموجودة
            existing.occurrence_count += 1
            existing.last_occurrence = datetime.utcnow()
            existing.confidence = min(100, existing.confidence + 5)  # زيادة الثقة
            
            if solution:
                memory_value = json.loads(existing.memory_value) if existing.memory_value else {}
                memory_value['solutions'] = memory_value.get('solutions', [])
                if solution not in memory_value['solutions']:
                    memory_value['solutions'].append(solution)
                existing.memory_value = json.dumps(memory_value)
        else:
            # إنشاء ذاكرة جديدة
            memory_value = {
                "error_data": error_data,
                "solutions": [solution] if solution else [],
                "first_seen": datetime.utcnow().isoformat()
            }
            
            new_memory = AssistantMemory(
                memory_type=error_type,
                memory_key=memory_key,
                memory_value=json.dumps(memory_value),
                confidence=30.0
            )
            db.session.add(new_memory)
        
        db.session.commit()
    
    @staticmethod
    def get_suggested_solutions(error_type, error_data):
        """الحصول على حلول مقترحة من الذاكرة"""
        similar_errors = AssistantMemory.query.filter_by(
            memory_type=error_type
        ).filter(
            AssistantMemory.is_verified == True,
            AssistantMemory.confidence >= 50
        ).order_by(
            AssistantMemory.confidence.desc()
        ).limit(5).all()
        
        solutions = []
        for memory in similar_errors:
            memory_data = json.loads(memory.memory_value) if memory.memory_value else {}
            solutions.extend(memory_data.get('solutions', []))
        
        return list(set(solutions))  # إزالة التكرار
    
    @staticmethod
    def run_full_analysis():
        """تشغيل تحليل شامل للنظام"""
        all_analytics = []
        
        # 1. فحص الأخطاء الحسابية
        financial_errors = AssistantAnalyzer.analyze_financial_errors()
        if financial_errors:
            total_impact = sum(e["difference"] for e in financial_errors)
            all_analytics.append({
                "type": "financial_error",
                "title": f"أخطاء حسابية في {len(financial_errors)} فاتورة",
                "description": f"تم اكتشاف {len(financial_errors)} فاتورة بمجموع لا يتطابق مع عناصرها. إجمالي الفرق: {total_impact:,.0f} د.ع",
                "severity": "critical" if total_impact > 10000 else "warning",
                "affected_count": len(financial_errors),
                "estimated_impact": total_impact,
                "related_data": financial_errors
            })
        
        # 2. تنبيهات المخزون
        inventory_alerts = AssistantAnalyzer.analyze_inventory_alerts()
        out_of_stock = [a for a in inventory_alerts if a["type"] == "out_of_stock"]
        low_stock = [a for a in inventory_alerts if a["type"] == "low_stock"]
        
        if out_of_stock:
            all_analytics.append({
                "type": "inventory_alert",
                "title": f"{len(out_of_stock)} منتج نفد من المخزون",
                "description": f"المنتجات: {', '.join([a['product_name'] for a in out_of_stock[:5]])}",
                "severity": "warning",
                "affected_count": len(out_of_stock),
                "related_data": out_of_stock
            })
        
        if low_stock:
            all_analytics.append({
                "type": "inventory_alert",
                "title": f"{len(low_stock)} منتج بقليل من المخزون",
                "description": f"يُنصح بإعادة التخزين",
                "severity": "info",
                "affected_count": len(low_stock),
                "related_data": low_stock
            })
        
        # 3. اتجاهات المبيعات
        sales_trends = AssistantAnalyzer.analyze_sales_trends()
        for trend in sales_trends:
            all_analytics.append({
                "type": "sales_trend",
                "title": trend["message"],
                "description": f"متوسط المبيعات الأخيرة: {trend['recent_avg']:,.0f} د.ع",
                "severity": trend.get("severity", "warning" if trend["type"] == "sales_decline" else "success"),
                "related_data": trend
            })
        
        # 4. مشاكل الدفع
        payment_issues = AssistantAnalyzer.analyze_payment_issues()
        for issue in payment_issues:
            all_analytics.append({
                "type": "payment_issue",
                "title": f"{issue['count']} فاتورة متأخرة الدفع",
                "description": f"إجمالي المبلغ المتأخر: {issue['total_amount']:,.0f} د.ع",
                "severity": issue.get("severity", "warning"),
                "affected_count": issue["count"],
                "estimated_impact": issue["total_amount"],
                "related_data": issue
            })
        
        # 5. رؤى العملاء
        customer_insights = AssistantAnalyzer.analyze_customer_behavior()
        for insight in customer_insights:
            if insight["type"] == "active_customers":
                all_analytics.append({
                    "type": "customer_insight",
                    "title": f"{insight['count']} عميل نشط",
                    "description": "عملاء قاموا بـ 5 طلبات أو أكثر",
                    "severity": "success",
                    "affected_count": insight["count"],
                    "related_data": insight
                })
        
        # 6. تحليل أداء الموظفين
        employee_insights = AssistantAnalyzer.analyze_employee_performance()
        for insight in employee_insights:
            all_analytics.append(insight)
        
        # 7. تحليل أنماط متقدم
        patterns = AssistantAnalyzer.analyze_patterns()
        for pattern in patterns:
            all_analytics.append(pattern)
        
        # 8. تنبؤات ذكية
        predictions = AssistantAnalyzer.generate_predictions()
        for prediction in predictions:
            all_analytics.append(prediction)
        
        return all_analytics
    
    @staticmethod
    def save_analytics(analytics_list):
        """حفظ التحليلات في قاعدة البيانات"""
        saved = []
        for analytics in analytics_list:
            # التحقق من عدم وجود تحليل مشابه نشط
            existing = SystemAnalytics.query.filter_by(
                analysis_type=analytics["type"],
                status="active"
            ).first()
            
            if existing:
                # تحديث التحليل الموجود
                existing.title = analytics["title"]
                existing.description = analytics["description"]
                existing.severity = analytics["severity"]
                existing.affected_count = analytics.get("affected_count", 0)
                existing.estimated_impact = analytics.get("estimated_impact", 0)
                existing.related_data = json.dumps(analytics.get("related_data", {}))
                existing.updated_at = datetime.utcnow()
                saved.append(existing)
            else:
                # إنشاء تحليل جديد
                new_analytics = SystemAnalytics(
                    analysis_type=analytics["type"],
                    title=analytics["title"],
                    description=analytics["description"],
                    severity=analytics["severity"],
                    affected_count=analytics.get("affected_count", 0),
                    estimated_impact=analytics.get("estimated_impact", 0),
                    related_data=json.dumps(analytics.get("related_data", {}))
                )
                db.session.add(new_analytics)
                saved.append(new_analytics)
        
        db.session.commit()
        return saved
    
    @staticmethod
    def auto_fix_errors():
        """إصلاح تلقائي للأخطاء المكتشفة"""
        fixes_applied = []
        
        # 1. إصلاح الأخطاء الحسابية في الفواتير
        financial_errors = AssistantAnalyzer.analyze_financial_errors()
        for error in financial_errors:
            if error["type"] == "total_mismatch":
                invoice = Invoice.query.get(error["invoice_id"])
                if invoice:
                    # تحديث المجموع بناءً على العناصر
                    items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
                    calculated_total = sum(item.price * item.quantity for item in items)
                    
                    if calculated_total > 0:
                        invoice.total = calculated_total
                        fixes_applied.append({
                            "type": "financial_fix",
                            "invoice_id": invoice.id,
                            "old_total": error["invoice_total"],
                            "new_total": calculated_total,
                            "difference": error["difference"]
                        })
        
        # 2. إصلاح الفواتير الفارغة
        for error in financial_errors:
            if error["type"] == "empty_invoice":
                invoice = Invoice.query.get(error["invoice_id"])
                if invoice and invoice.total > 0:
                    # إذا كانت الفاتورة فارغة ولكن لها مجموع، إما حذفها أو تصفير المجموع
                    items = OrderItem.query.filter_by(invoice_id=invoice.id).all()
                    if not items:
                        invoice.total = 0
                        fixes_applied.append({
                            "type": "empty_invoice_fix",
                            "invoice_id": invoice.id,
                            "action": "zeroed_total"
                        })
        
        if fixes_applied:
            db.session.commit()
        
        return fixes_applied
    
    @staticmethod
    def suggest_auto_fixes():
        """اقتراح إصلاحات تلقائية ممكنة"""
        suggestions = []
        
        # 1. اقتراح إصلاح الأخطاء الحسابية
        financial_errors = AssistantAnalyzer.analyze_financial_errors()
        fixable_errors = [e for e in financial_errors if e["type"] == "total_mismatch" and e["difference"] < 10000]
        
        if fixable_errors:
            suggestions.append({
                "type": "auto_fix_financial",
                "title": f"إصلاح تلقائي لـ {len(fixable_errors)} خطأ حسابي",
                "description": f"يمكن إصلاح {len(fixable_errors)} فاتورة تلقائياً بتحديث المجموع بناءً على العناصر",
                "count": len(fixable_errors),
                "severity": "info"
            })
        
        return suggestions
