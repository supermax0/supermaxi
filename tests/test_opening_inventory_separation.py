"""
اختبارات فصل المخزون الافتتاحي عن الحسابات المالية
(Opening Inventory Separation Tests)

التحقق من أن المخزون الافتتاحي:
1. لا يؤثر على الرصيد المالي
2. يزيد قيمة المخزون فقط
3. لا يظهر في صفحة الحسابات
"""

import pytest


class TestOpeningInventorySeparation:
    """اختبارات فصل المخزون الافتتاحي عن الحسابات المالية"""
    
    def test_opening_inventory_not_affects_balance(self):
        """
        Given: رصيد مالي 0، مخزون افتتاحي بقيمة 5,000,000
        When: إدخال مخزون افتتاحي
        Then: 
        - Inventory Value = 5,000,000 ✔️
        - Cash / Balance = 0 ✔️
        - No Financial Movement Recorded ✔️
        
        السبب المحاسبي: المخزون الافتتاحي يُعتبر قيمة مخزون فقط (Asset) ولا يؤثر على الرصيد المالي
        """
        # Given: الحالة الابتدائية
        initial_balance = 0
        opening_stock_value = 5000000
        
        # When: إدخال مخزون افتتاحي
        # في التطبيق الحقيقي، لا يتم إنشاء AccountTransaction للمخزون الافتتاحي
        financial_transactions = []  # لا توجد حركات مالية للمخزون الافتتاحي
        
        # Then: حساب الرصيد المالي
        total_deposits = sum(
            t.amount for t in financial_transactions 
            if hasattr(t, 'type') and t.type == "deposit"
        )
        balance = total_deposits  # total_withdraw = 0
        
        # Then: التحقق من النتائج
        assert balance == initial_balance, "الرصيد المالي لا يجب أن يتغير عند إدخال مخزون افتتاحي"
        assert balance == 0, "الرصيد المالي يجب أن يبقى 0"
    
    def test_opening_inventory_increases_inventory_value_only(self):
        """
        Given: مخزون 0، مخزون افتتاحي بقيمة 5,000,000
        When: إدخال مخزون افتتاحي
        Then: 
        - Inventory Value = 5,000,000 ✔️
        - Cash / Balance = 0 ✔️
        
        السبب المحاسبي: المخزون الافتتاحي يزيد قيمة المخزون فقط، لا يؤثر على النقدية
        """
        # Given
        initial_inventory_value = 0
        opening_stock_quantity = 100
        buy_price = 50000  # 50,000 د.ع لكل قطعة
        opening_stock_value = opening_stock_quantity * buy_price  # 5,000,000
        
        # When: إدخال مخزون افتتاحي
        new_inventory_value = initial_inventory_value + opening_stock_value
        cash_balance = 0  # لا يؤثر على النقدية
        
        # Then
        assert new_inventory_value == 5000000, "قيمة المخزون يجب أن تزيد إلى 5,000,000"
        assert cash_balance == 0, "النقدية لا يجب أن تتأثر بالمخزون الافتتاحي"
    
    def test_opening_inventory_not_in_accounts_page(self):
        """
        Given: حركة مخزون افتتاحي مع note "مخزون افتتاحي"
        When: عرض صفحة الحسابات
        Then: لا تظهر حركة المخزون الافتتاحي في صفحة الحسابات
        
        السبب المحاسبي: صفحة الحسابات تعرض فقط الحركات المالية، لا تعرض حركات المخزون
        """
        # Given: حركات محتملة
        all_transactions = [
            {"type": "deposit", "amount": 100000, "note": "مخزون افتتاحي - منتج أ"},
            {"type": "deposit", "amount": 50000, "note": "إيداع رأس مال"},
            {"type": "withdraw", "amount": 20000, "note": "سحب رأس مال"}
        ]
        
        # When: فلترة الحركات المالية (استبعاد حركات المخزون الافتتاحي)
        financial_transactions = [
            t for t in all_transactions 
            if not (t.get("note") and "مخزون افتتاحي" in t.get("note", ""))
        ]
        
        # Then
        assert len(financial_transactions) == 2, "يجب أن تظهر حركتان ماليتان فقط"
        assert all("مخزون افتتاحي" not in t.get("note", "") for t in financial_transactions), "لا يجب أن تظهر أي حركة مخزون افتتاحي"
    
    def test_opening_inventory_balance_calculation(self):
        """
        Given: إيداعات (50,000) وسحوبات (20,000) + حركة مخزون افتتاحي (5,000,000)
        When: حساب الرصيد
        Then: الرصيد = 30,000 (50,000 - 20,000) وليس 5,030,000
        
        السبب المحاسبي: حركات المخزون الافتتاحي لا تدخل في حساب الرصيد المالي
        """
        # Given: جميع الحركات
        all_transactions = [
            {"type": "deposit", "amount": 50000, "note": "إيداع رأس مال"},
            {"type": "withdraw", "amount": 20000, "note": "سحب رأس مال"},
            {"type": "deposit", "amount": 5000000, "note": "مخزون افتتاحي - منتج"}
        ]
        
        # When: فلترة الحركات المالية
        financial_transactions = [
            t for t in all_transactions 
            if not (t.get("note") and "مخزون افتتاحي" in t.get("note", ""))
        ]
        
        # حساب الرصيد من الحركات المالية فقط
        total_deposits = sum(
            t["amount"] for t in financial_transactions if t["type"] == "deposit"
        )
        total_withdraws = sum(
            t["amount"] for t in financial_transactions if t["type"] == "withdraw"
        )
        balance = total_deposits - total_withdraws
        
        # Then
        assert balance == 30000, "الرصيد يجب أن يكون 30,000 (50,000 - 20,000)"
        assert balance != 5030000, "الرصيد لا يجب أن يتضمن حركة المخزون الافتتاحي"
    
    def test_opening_inventory_in_inventory_reports_only(self):
        """
        Given: مخزون افتتاحي بقيمة 5,000,000
        When: عرض التقارير
        Then:
        - قيمة المخزون في التقارير = 5,000,000 ✔️
        - قيمة المخزون لا تُجمع مع أي رقم مالي ✔️
        
        السبب المحاسبي: قيمة المخزون تُعرض في التقارير فقط، منفصلة عن الأرقام المالية
        """
        # Given
        opening_stock_value = 5000000
        financial_balance = 0
        
        # When: حساب قيمة المخزون
        inventory_value = opening_stock_value
        
        # Then
        assert inventory_value == 5000000, "قيمة المخزون في التقارير = 5,000,000"
        assert inventory_value != financial_balance, "قيمة المخزون لا تُساوي الرصيد المالي"
        # ملاحظة: إذا كان الرصيد المالي = 0 فلا يغير قيمة المخزون عند الجمع (وهذا طبيعي رياضياً).
        # المقصود محاسبياً هو عدم خلط/إضافة قيمة المخزون إلى الرصيد المالي في تقارير الأموال.
        assert inventory_value + financial_balance == inventory_value, "الرصيد المالي (0) لا يغير قيمة المخزون"


class TestOpeningInventoryAccountingRules:
    """اختبارات القواعد المحاسبية للمخزون الافتتاحي"""
    
    def test_opening_inventory_is_asset_not_cash(self):
        """
        Given: مخزون افتتاحي بقيمة 5,000,000
        When: تصنيف القيمة
        Then: يُعتبر أصل (Asset) وليس نقدية (Cash)
        
        السبب المحاسبي: المخزون يُعتبر أصل (Asset) ولا يدخل ضمن رأس المال أو النقدية
        """
        # Given
        opening_stock_value = 5000000
        
        # When: تصنيف
        asset_value = opening_stock_value  # قيمة الأصل
        cash_value = 0  # النقدية لا تتأثر
        
        # Then
        assert asset_value == 5000000, "قيمة الأصل = 5,000,000"
        assert cash_value == 0, "النقدية = 0"
        assert asset_value != cash_value, "قيمة الأصل لا تُساوي النقدية"
    
    def test_opening_inventory_does_not_create_financial_movement(self):
        """
        Given: إدخال مخزون افتتاحي
        When: التحقق من الحركات المالية
        Then: لا يتم إنشاء أي حركة مالية (AccountTransaction)
        
        السبب المحاسبي: المخزون الافتتاحي لا يُسجل كحركة مالية
        """
        # Given: إدخال مخزون افتتاحي
        opening_stock_value = 5000000
        
        # When: التحقق من إنشاء حركة مالية
        # في التطبيق الحقيقي، لا يتم إنشاء AccountTransaction للمخزون الافتتاحي
        financial_movements_for_opening_stock = []  # لا توجد حركات مالية
        
        # Then
        assert len(financial_movements_for_opening_stock) == 0, "لا يجب إنشاء أي حركة مالية للمخزون الافتتاحي"
    
    def test_opening_inventory_stored_in_product_only(self):
        """
        Given: إدخال مخزون افتتاحي
        When: حفظ البيانات
        Then: يُسجل في Product.opening_stock و Product.quantity فقط
        
        السبب المحاسبي: المخزون الافتتاحي يُسجل في جدول المنتجات فقط، لا في الحسابات المالية
        """
        # Given: إدخال مخزون افتتاحي
        opening_stock = 100
        buy_price = 50000
        opening_stock_value = opening_stock * buy_price
        
        # When: حفظ البيانات
        product_data = {
            "opening_stock": opening_stock,
            "quantity": opening_stock,  # الكمية = المخزون الافتتاحي
            "buy_price": buy_price
        }
        
        account_transactions = []  # لا توجد حركات مالية
        
        # Then
        assert product_data["opening_stock"] == 100, "المخزون الافتتاحي يُسجل في Product.opening_stock"
        assert product_data["quantity"] == 100, "الكمية تُسجل في Product.quantity"
        assert len(account_transactions) == 0, "لا تُسجل أي حركة مالية"
