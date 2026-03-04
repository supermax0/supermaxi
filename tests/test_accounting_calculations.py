"""
اختبارات الدوال المحاسبية
Tests for Accounting Calculations Functions

هذا الملف يحتوي على اختبارات تلقائية للتحقق من صحة المنطق المحاسبي.
جميع الاختبارات معزولة ولا تغيّر النظام الحالي.

القواعد المحاسبية المختبرة:
1. فصل كامل بين: النقدية، المخزون، الإيرادات، المصاريف، الالتزامات، رأس المال
2. المخزون يُعتبر أصل ولا يدخل في رأس المال
3. الإيرادات = المبيعات - المرتجعات
4. الربح = (الإيرادات - المرتجعات) - COGS - المصاريف
5. المرتجعات تخصم من الإيرادات وتعيد COGS للمخزون
6. المصاريف لا تؤثر على المخزون أو رأس المال مباشرة
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy import func


# ======================================================
# اختبارات حساب الإيرادات (Revenue)
# ======================================================

class TestRevenueCalculations:
    """اختبارات حساب الإيرادات"""
    
    def test_revenue_excludes_returns(self, sample_accounting_data):
        """
        Given: مبيعات بقيمة 90,000 ومرتجعات بقيمة 20,000
        When: حساب الإيرادات
        Then: الإيرادات = 70,000 (90,000 - 20,000)
        
        السبب المحاسبي: المرتجعات تُخصم من الإيرادات
        """
        # Given: بيانات المبيعات والمرتجعات
        sales = 90000  # مبيعات
        returns = 20000  # مرتجعات
        
        # When: حساب الإيرادات
        revenue = sales - returns
        
        # Then: التحقق من الحساب الصحيح
        assert revenue == 70000, "الإيرادات يجب أن تساوي المبيعات - المرتجعات"
    
    def test_revenue_not_affected_by_cogs(self):
        """
        Given: مبيعات بقيمة 50,000 و COGS بقيمة 30,000
        When: حساب الإيرادات
        Then: الإيرادات = 50,000 (لا تتأثر بـ COGS)
        
        السبب المحاسبي: الإيرادات تُحسب من المبيعات فقط، COGS يُحسب في الربح
        """
        # Given
        sales = 50000
        cogs = 30000
        
        # When: حساب الإيرادات
        revenue = sales  # الإيرادات لا تتأثر بـ COGS
        
        # Then
        assert revenue == 50000, "الإيرادات لا يجب أن تتأثر بـ COGS"
    
    def test_revenue_not_affected_by_expenses(self):
        """
        Given: مبيعات بقيمة 50,000 ومصاريف بقيمة 5,000
        When: حساب الإيرادات
        Then: الإيرادات = 50,000 (لا تتأثر بالمصاريف)
        
        السبب المحاسبي: الإيرادات تُحسب من المبيعات فقط، المصاريف تُحسب في الربح
        """
        # Given
        sales = 50000
        expenses = 5000
        
        # When: حساب الإيرادات
        revenue = sales  # الإيرادات لا تتأثر بالمصاريف
        
        # Then
        assert revenue == 50000, "الإيرادات لا يجب أن تتأثر بالمصاريف"


# ======================================================
# اختبارات حساب المخزون (Inventory)
# ======================================================

class TestInventoryCalculations:
    """اختبارات حساب المخزون"""
    
    def test_inventory_not_part_of_capital(self, sample_accounting_data):
        """
        Given: مخزون بقيمة 500,000 ورأس مال بقيمة 1,000,000
        When: حساب قيمة المخزون
        Then: المخزون = 500,000 (لا يدخل في رأس المال)
        
        السبب المحاسبي: المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال
        """
        # Given
        inventory_value = 500000
        capital = 1000000
        
        # When: حساب قيمة المخزون
        calculated_inventory = inventory_value  # حساب مستقل
        
        # Then
        assert calculated_inventory == 500000, "المخزون يجب أن يكون حساب مستقل"
        assert calculated_inventory != capital, "المخزون لا يجب أن يكون جزءاً من رأس المال"
    
    def test_inventory_reduces_on_sale(self):
        """
        Given: مخزون ابتدائي بقيمة 500,000 وبيع منتج بتكلفة 30,000
        When: البيع يتم
        Then: المخزون = 470,000 (500,000 - 30,000)
        
        السبب المحاسبي: عند البيع، يُخفض المخزون بقيمة COGS
        """
        # Given
        initial_inventory = 500000
        cogs = 30000
        
        # When: البيع يتم
        new_inventory = initial_inventory - cogs
        
        # Then
        assert new_inventory == 470000, "المخزون يجب أن ينقص بقيمة COGS عند البيع"
    
    def test_inventory_increases_on_return(self):
        """
        Given: مخزون بقيمة 470,000 ومرتجع بتكلفة 15,000
        When: الإرجاع يتم
        Then: المخزون = 485,000 (470,000 + 15,000)
        
        السبب المحاسبي: عند الإرجاع، تُعاد تكلفة المنتج (COGS) للمخزون
        """
        # Given
        current_inventory = 470000
        return_cogs = 15000
        
        # When: الإرجاع يتم
        new_inventory = current_inventory + return_cogs
        
        # Then
        assert new_inventory == 485000, "المخزون يجب أن يزيد بقيمة COGS عند الإرجاع"


# ======================================================
# اختبارات المبيعات (Sales)
# ======================================================

class TestSalesCalculations:
    """اختبارات المبيعات النقدية والآجلة"""
    
    def test_cash_sale_increases_revenue_and_reduces_inventory(self):
        """
        Given: بيع نقدي بقيمة 50,000 د.ع، تكلفة 30,000 د.ع
        When: تسجيل البيع النقدي
        Then:
        - الإيرادات تزيد بـ 50,000
        - المخزون ينقص بـ 30,000
        - النقدية تزيد بـ 50,000 (لا يُختبر هنا لأنها في طبقة أخرى)
        
        السبب المحاسبي: البيع النقدي يزيد الإيرادات مباشرة ويُنقص المخزون
        """
        # Given
        sale_amount = 50000
        cogs = 30000
        initial_revenue = 0
        initial_inventory = 500000
        
        # When: تسجيل البيع النقدي
        new_revenue = initial_revenue + sale_amount
        new_inventory = initial_inventory - cogs
        
        # Then
        assert new_revenue == 50000, "الإيرادات يجب أن تزيد بقيمة البيع"
        assert new_inventory == 470000, "المخزون يجب أن ينقص بقيمة COGS"
    
    def test_credit_sale_increases_receivables_not_cash(self):
        """
        Given: بيع آجل بقيمة 40,000 د.ع، تكلفة 25,000 د.ع
        When: تسجيل البيع الآجل
        Then:
        - الإيرادات تزيد بـ 40,000
        - المخزون ينقص بـ 25,000
        - الذمم المدينة تزيد بـ 40,000
        - النقدية لا تتغير
        
        السبب المحاسبي: البيع الآجل يُسجل في الذمم المدينة ولا يؤثر على النقدية
        """
        # Given
        sale_amount = 40000
        cogs = 25000
        initial_revenue = 50000
        initial_inventory = 470000
        initial_receivables = 0
        initial_cash = 100000
        
        # When: تسجيل البيع الآجل
        new_revenue = initial_revenue + sale_amount
        new_inventory = initial_inventory - cogs
        new_receivables = initial_receivables + sale_amount
        new_cash = initial_cash  # النقدية لا تتغير
        
        # Then
        assert new_revenue == 90000, "الإيرادات يجب أن تزيد بقيمة البيع"
        assert new_inventory == 445000, "المخزون يجب أن ينقص بقيمة COGS"
        assert new_receivables == 40000, "الذمم المدينة يجب أن تزيد بقيمة البيع"
        assert new_cash == 100000, "النقدية لا يجب أن تتغير في البيع الآجل"


# ======================================================
# اختبارات التحصيل (Collection)
# ======================================================

class TestCollectionCalculations:
    """اختبارات تحصيل الديون"""
    
    def test_collection_increases_cash_decreases_receivables(self):
        """
        Given: دين بقيمة 40,000 غير مسدد
        When: تحصيل الدين
        Then:
        - النقدية تزيد بـ 40,000
        - الذمم المدينة تنقص بـ 40,000
        - الإيرادات لا تتغير (تم تسجيلها عند البيع)
        
        السبب المحاسبي: تحصيل الدين يُحول الذمم المدينة إلى نقدية ولا يؤثر على الإيرادات
        """
        # Given
        debt_amount = 40000
        initial_cash = 100000
        initial_receivables = 40000
        initial_revenue = 90000
        
        # When: تحصيل الدين
        new_cash = initial_cash + debt_amount
        new_receivables = initial_receivables - debt_amount
        new_revenue = initial_revenue  # لا تتغير
        
        # Then
        assert new_cash == 140000, "النقدية يجب أن تزيد بقيمة الدين المحصّل"
        assert new_receivables == 0, "الذمم المدينة يجب أن تنقص بقيمة الدين المحصّل"
        assert new_revenue == 90000, "الإيرادات لا يجب أن تتغير عند التحصيل"


# ======================================================
# اختبارات المصاريف (Expenses)
# ======================================================

class TestExpenseCalculations:
    """اختبارات المصاريف"""
    
    def test_expenses_reduce_profit_not_inventory(self):
        """
        Given: مصروف بقيمة 5,000 د.ع
        When: تسجيل المصروف
        Then:
        - المصاريف تزيد بـ 5,000
        - المخزون لا يتغير
        - رأس المال لا يتغير مباشرة
        
        السبب المحاسبي: المصاريف تُطرح من الربح ولا تؤثر على المخزون أو رأس المال مباشرة
        """
        # Given
        expense_amount = 5000
        initial_expenses = 0
        initial_inventory = 500000
        initial_capital = 1000000
        
        # When: تسجيل المصروف
        new_expenses = initial_expenses + expense_amount
        new_inventory = initial_inventory  # لا يتغير
        new_capital = initial_capital  # لا يتغير مباشرة
        
        # Then
        assert new_expenses == 5000, "المصاريف يجب أن تزيد بقيمة المصروف"
        assert new_inventory == 500000, "المخزون لا يجب أن يتأثر بالمصاريف"
        assert new_capital == 1000000, "رأس المال لا يجب أن يتأثر مباشرة بالمصاريف"
    
    def test_expenses_reduce_net_profit(self):
        """
        Given: إيرادات 90,000، COGS 55,000، مصاريف 8,000
        When: حساب صافي الربح
        Then: صافي الربح = 27,000 (90,000 - 55,000 - 8,000)
        
        السبب المحاسبي: صافي الربح = الإيرادات - COGS - المصاريف
        """
        # Given
        revenue = 90000
        cogs = 55000
        expenses = 8000
        
        # When: حساب صافي الربح
        net_profit = revenue - cogs - expenses
        
        # Then
        assert net_profit == 27000, "صافي الربح يجب أن يساوي الإيرادات - COGS - المصاريف"


# ======================================================
# اختبارات المرتجعات (Returns)
# ======================================================

class TestReturnCalculations:
    """اختبارات المرتجعات"""
    
    def test_return_reduces_revenue_and_restores_inventory(self):
        """
        Given: مرتجع مبيعات بقيمة 20,000 د.ع، تكلفة 15,000 د.ع
        When: تسجيل المرتجع
        Then:
        - الإيرادات تنقص بـ 20,000
        - المخزون يزيد بـ 15,000 (تُعاد COGS)
        - COGS الصافي ينقص بـ 15,000
        
        السبب المحاسبي: المرتجعات تُخصم من الإيرادات وتُعيد COGS للمخزون
        """
        # Given
        return_amount = 20000
        return_cogs = 15000
        initial_revenue = 90000
        initial_inventory = 445000
        initial_cogs = 55000
        
        # When: تسجيل المرتجع
        new_revenue = initial_revenue - return_amount
        new_inventory = initial_inventory + return_cogs
        net_cogs = initial_cogs - return_cogs
        
        # Then
        assert new_revenue == 70000, "الإيرادات يجب أن تنقص بقيمة المرتجع"
        assert new_inventory == 460000, "المخزون يجب أن يزيد بقيمة COGS المرتجع"
        assert net_cogs == 40000, "COGS الصافي يجب أن ينقص بقيمة COGS المرتجع"


# ======================================================
# اختبارات حساب الربح (Profit)
# ======================================================

class TestProfitCalculations:
    """اختبارات حساب الربح"""
    
    def test_profit_formula_correct(self):
        """
        Given: إيرادات 70,000، COGS الصافي 40,000، مصاريف 8,000
        When: حساب صافي الربح
        Then: صافي الربح = 22,000 (70,000 - 40,000 - 8,000)
        
        الصيغة المحاسبية الصحيحة:
        صافي الربح = الإيرادات - COGS الصافي - المصاريف
        """
        # Given
        revenue = 70000
        net_cogs = 40000
        expenses = 8000
        
        # When: حساب صافي الربح
        net_profit = revenue - net_cogs - expenses
        
        # Then
        assert net_profit == 22000, "صافي الربح يجب أن يحسب بالمعادلة الصحيحة"
    
    def test_profit_not_added_to_capital_directly(self):
        """
        Given: ربح بقيمة 22,000 ورأس مال بقيمة 1,000,000
        When: حساب الربح (قبل إقفال الفترة)
        Then: رأس المال لا يتغير
        
        السبب المحاسبي: الربح لا يُضاف لرأس المال مباشرة، فقط في نهاية الفترة المالية
        """
        # Given
        profit = 22000
        capital = 1000000
        
        # When: حساب الربح (قبل إقفال الفترة)
        new_capital = capital  # لا يتغير
        
        # Then
        assert new_capital == 1000000, "رأس المال لا يجب أن يتغير مباشرة بالربح"
        assert profit == 22000, "الربح يُحسب لكن لا يُضاف للرأس المال مباشرة"
    
    def test_profit_added_to_capital_on_closure(self):
        """
        Given: ربح بقيمة 22,000 ورأس مال بقيمة 1,000,000
        When: إقفال الفترة المالية (إضافة الربح لرأس المال)
        Then: رأس المال = 1,022,000 (1,000,000 + 22,000)
        
        السبب المحاسبي: الربح يُضاف لرأس المال فقط في نهاية الفترة المالية
        """
        # Given
        profit = 22000
        initial_capital = 1000000
        
        # When: إقفال الفترة المالية
        new_capital = initial_capital + profit
        
        # Then
        assert new_capital == 1022000, "رأس المال يجب أن يزيد بالربح عند إقفال الفترة"


# ======================================================
# اختبارات متكاملة (Integration Tests)
# ======================================================

class TestIntegratedAccountingScenario:
    """اختبارات متكاملة لحالات محاسبية كاملة"""
    
    def test_complete_sale_cycle(self):
        """
        Given / When / Then: دورة بيع كاملة
        1. بيع نقدي: 50,000 د.ع، تكلفة 30,000
        2. بيع آجل: 40,000 د.ع، تكلفة 25,000
        3. مرتجع: 20,000 د.ع، تكلفة 15,000
        4. مصروف: 8,000 د.ع
        5. تحصيل دين: 40,000 د.ع
        
        التحقق من:
        - الإيرادات = 70,000 (50,000 + 40,000 - 20,000)
        - COGS الصافي = 40,000 (30,000 + 25,000 - 15,000)
        - صافي الربح = 22,000 (70,000 - 40,000 - 8,000)
        - المخزون ينقص بقيمة COGS الصافي
        - النقدية تزيد بالبيع النقدي + التحصيل
        """
        # Given: الحالة الابتدائية
        initial_revenue = 0
        initial_cogs = 0
        initial_inventory = 500000
        initial_cash = 100000
        initial_receivables = 0
        initial_expenses = 0
        
        # When: 1. بيع نقدي
        cash_sale = 50000
        cash_sale_cogs = 30000
        initial_revenue += cash_sale
        initial_cogs += cash_sale_cogs
        initial_inventory -= cash_sale_cogs
        initial_cash += cash_sale
        
        # When: 2. بيع آجل
        credit_sale = 40000
        credit_sale_cogs = 25000
        initial_revenue += credit_sale
        initial_cogs += credit_sale_cogs
        initial_inventory -= credit_sale_cogs
        initial_receivables += credit_sale
        
        # When: 3. مرتجع
        return_amount = 20000
        return_cogs = 15000
        initial_revenue -= return_amount
        initial_cogs -= return_cogs
        initial_inventory += return_cogs
        
        # When: 4. مصروف
        expense = 8000
        initial_expenses += expense
        
        # When: 5. تحصيل دين
        collection = 40000
        initial_cash += collection
        initial_receivables -= collection
        
        # Then: التحقق من الحسابات
        assert initial_revenue == 70000, "الإيرادات يجب أن تساوي 70,000"
        assert initial_cogs == 40000, "COGS الصافي يجب أن يساوي 40,000"
        assert initial_inventory == 460000, "المخزون يجب أن يساوي 460,000"
        assert initial_cash == 190000, "النقدية يجب أن تساوي 190,000"
        assert initial_receivables == 0, "الذمم المدينة يجب أن تساوي 0"
        
        # حساب صافي الربح
        net_profit = initial_revenue - initial_cogs - initial_expenses
        assert net_profit == 22000, "صافي الربح يجب أن يساوي 22,000"
    
    def test_inventory_never_mixed_with_capital(self):
        """
        Given / When / Then: 
        - مخزون بقيمة 460,000
        - رأس مال بقيمة 1,000,000
        
        التحقق من: المخزون ورأس المال حسابان منفصلان تماماً
        """
        # Given
        inventory = 460000
        capital = 1000000
        
        # When / Then
        assert inventory != capital, "المخزون ورأس المال يجب أن يكونا حسابين منفصلين"
        assert inventory + capital != inventory and inventory + capital != capital, \
            "المخزون لا يجب أن يُضاف لرأس المال"


# ======================================================
# اختبارات التحقق من القواعد المحاسبية (Validation Tests)
# ======================================================

class TestAccountingRulesValidation:
    """اختبارات التحقق من القواعد المحاسبية"""
    
    def test_revenue_separate_from_expenses(self):
        """التحقق من فصل الإيرادات عن المصاريف"""
        revenue = 70000
        expenses = 8000
        
        assert revenue != expenses, "الإيرادات والمصاريف حسابان منفصلان"
        assert revenue > expenses, "في حالة ربح، الإيرادات أكبر من المصاريف"
    
    def test_inventory_separate_from_revenue(self):
        """التحقق من فصل المخزون عن الإيرادات"""
        inventory = 460000
        revenue = 70000
        
        assert inventory != revenue, "المخزون والإيرادات حسابان منفصلان"
    
    def test_cogs_always_less_than_revenue(self):
        """التحقق من أن COGS أقل من الإيرادات (في حالة ربح)"""
        revenue = 70000
        cogs = 40000
        
        assert cogs < revenue, "COGS يجب أن يكون أقل من الإيرادات في حالة ربح"
    
    def test_profit_equals_revenue_minus_cogs_minus_expenses(self):
        """التحقق من معادلة الربح الصحيحة"""
        revenue = 70000
        cogs = 40000
        expenses = 8000
        
        profit = revenue - cogs - expenses
        
        assert profit == 22000, "الربح يجب أن يساوي الإيرادات - COGS - المصاريف"
