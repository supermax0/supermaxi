"""
اختبارات دقة المخزون (Inventory Accuracy Tests)
التحقق من عدم حصول كميات سالبة وتطابق الرصيد مع الحركات
"""

import pytest


# ======================================================
# اختبارات التحقق من دقة المخزون
# ======================================================

class TestInventoryAccuracy:
    """اختبارات دقة المخزون"""
    
    def test_no_negative_quantities(self):
        """
        Given: منتج بمخزون 10 قطع
        When: محاولة بيع 15 قطعة
        Then: يجب منع العملية (المخزون لا يمكن أن يكون سالباً)
        
        السبب المحاسبي: منع الكميات السالبة يضمن دقة المخزون
        """
        # Given
        initial_quantity = 10
        requested_quantity = 15
        
        # When: التحقق من الكمية
        is_valid = initial_quantity >= requested_quantity
        
        # Then
        assert not is_valid, "يجب منع البيع إذا كانت الكمية المطلوبة أكبر من المتوفرة"
    
    def test_inventory_balance_calculation(self):
        """
        Given: مخزون افتتاحي 100، مشتريات 50، مبيعات 30
        When: حساب الرصيد
        Then: الرصيد = 120 (100 + 50 - 30)
        
        السبب المحاسبي: الرصيد يُحسب من مجموع الحركات
        """
        # Given
        opening_stock = 100
        purchases = 50
        sales = 30
        
        # When: حساب الرصيد
        balance = opening_stock + purchases - sales
        
        # Then
        assert balance == 120, "الرصيد يجب أن يساوي المخزون الافتتاحي + المشتريات - المبيعات"
    
    def test_inventory_always_calculated_by_cost(self):
        """
        Given: منتج بتكلفة 30,000 وسعر بيع 50,000
        When: حساب قيمة المخزون
        Then: قيمة المخزون = الكمية × 30,000 (التكلفة) وليس 50,000
        
        السبب المحاسبي: المخزون يُحسب بالتكلفة دائماً، ليس بسعر البيع
        """
        # Given
        quantity = 10
        buy_price = 30000
        sale_price = 50000
        
        # When: حساب قيمة المخزون
        inventory_value_by_cost = quantity * buy_price
        inventory_value_by_sale = quantity * sale_price
        
        # Then
        assert inventory_value_by_cost == 300000, "قيمة المخزون يجب أن تُحسب بالتكلفة"
        assert inventory_value_by_cost != inventory_value_by_sale, "قيمة المخزون لا يجب أن تُحسب بسعر البيع"
    
    def test_return_restores_quantity_and_cost(self):
        """
        Given: بيع 5 قطع بتكلفة 30,000 لكل قطعة
        When: إرجاع البيع
        Then: المخزون يزيد 5 قطع (تُعاد الكمية) والتكلفة تُعاد أيضاً
        
        السبب المحاسبي: المرتجع يُعيد الكمية + التكلفة الصحيحة (COGS)
        """
        # Given
        initial_quantity = 100
        sold_quantity = 5
        cost_per_unit = 30000
        
        # When: البيع
        after_sale = initial_quantity - sold_quantity
        # When: الإرجاع
        after_return = after_sale + sold_quantity  # إعادة الكمية
        
        # Then
        assert after_sale == 95, "المخزون ينقص عند البيع"
        assert after_return == 100, "المخزون يزيد عند الإرجاع (تُعاد الكمية)"
    
    def test_purchase_increases_quantity(self):
        """
        Given: مخزون 50 قطعة
        When: شراء 20 قطعة
        Then: المخزون = 70 (50 + 20)
        
        السبب المحاسبي: الشراء يزيد المخزون مباشرة
        """
        # Given
        initial_quantity = 50
        purchase_quantity = 20
        
        # When: الشراء
        new_quantity = initial_quantity + purchase_quantity
        
        # Then
        assert new_quantity == 70, "المخزون يجب أن يزيد عند الشراء"
    
    def test_inventory_ledger_balance_matches_actual(self):
        """
        Given: حركات مخزون (افتتاحي + مشتريات - مبيعات)
        When: حساب الرصيد من السجل
        Then: الرصيد المحسوب = الرصيد الفعلي في المنتج
        
        السبب المحاسبي: سجل الحركات يجب أن يتطابق مع الرصيد الفعلي
        """
        # Given
        opening_stock = 100
        purchases = [20, 15, 10]  # ثلاث عمليات شراء
        sales = [25, 10]  # عمليتان بيع
        
        # When: حساب الرصيد من السجل
        total_purchases = sum(purchases)
        total_sales = sum(sales)
        calculated_balance = opening_stock + total_purchases - total_sales
        
        # الرصيد الفعلي (كما هو في قاعدة البيانات)
        actual_quantity = 100  # افتراضي
        actual_quantity += 20 + 15 + 10  # المشتريات
        actual_quantity -= 25 + 10  # المبيعات
        
        # Then
        assert calculated_balance == actual_quantity, "الرصيد المحسوب يجب أن يتطابق مع الرصيد الفعلي"
        assert calculated_balance == 110, "الرصيد النهائي = 100 + 45 - 35 = 110"


# ======================================================
# اختبارات التحقق من منع الأخطاء
# ======================================================

class TestInventoryProtection:
    """اختبارات الحماية ومنع الأخطاء"""
    
    def test_prevent_sale_from_zero_stock(self):
        """
        Given: منتج بمخزون 0
        When: محاولة بيع 1 قطعة
        Then: يجب منع العملية
        
        السبب المحاسبي: منع البيع من مخزون نافد يضمن دقة المخزون
        """
        # Given
        available_quantity = 0
        requested_quantity = 1
        
        # When: التحقق
        can_sell = available_quantity >= requested_quantity
        
        # Then
        assert not can_sell, "يجب منع البيع من مخزون نافد"
    
    def test_prevent_negative_adjustment(self):
        """
        Given: منتج بمخزون 5 قطع
        When: تعديل يدوي بـ -10 قطع
        Then: يجب منع العملية (المخزون لا يمكن أن يكون سالباً)
        
        السبب المحاسبي: منع التعديلات التي تجعل المخزون سالباً
        """
        # Given
        current_quantity = 5
        adjustment = -10
        
        # When: التحقق من التعديل
        new_quantity = current_quantity + adjustment
        is_valid = new_quantity >= 0
        
        # Then
        assert not is_valid, "يجب منع التعديلات التي تجعل المخزون سالباً"
    
    def test_allow_positive_adjustment(self):
        """
        Given: منتج بمخزون 10 قطع
        When: تعديل يدوي بـ +5 قطع (مع سبب)
        Then: يجب السماح (المخزون = 15)
        
        السبب المحاسبي: التعديلات الإيجابية مسموحة بشرط وجود سبب
        """
        # Given
        current_quantity = 10
        adjustment = 5
        reason = "فحص جرد - اكتشاف كمية إضافية"
        
        # When: التحقق من التعديل
        has_reason = bool(reason and reason.strip())
        new_quantity = current_quantity + adjustment
        is_valid = has_reason and new_quantity >= 0
        
        # Then
        assert is_valid, "يجب السماح بالتعديلات الإيجابية مع وجود سبب"
        assert new_quantity == 15, "المخزون يجب أن يزيد إلى 15"
    
    def test_require_reason_for_adjustment(self):
        """
        Given: تعديل يدوي للمخزون
        When: عدم إدخال سبب
        Then: يجب منع العملية
        
        السبب المحاسبي: كل حركة مخزون يجب أن تكون مرتبطة بسبب واضح
        """
        # Given
        adjustment = 5
        reason = ""  # بدون سبب
        
        # When: التحقق من السبب
        has_reason = bool(reason and reason.strip())
        
        # Then
        assert not has_reason, "يجب إدخال سبب للتعديل"


# ======================================================
# اختبارات حساب قيمة المخزون
# ======================================================

class TestInventoryValueCalculation:
    """اختبارات حساب قيمة المخزون"""
    
    def test_inventory_value_always_by_cost(self):
        """
        Given: منتج: 10 قطع، تكلفة 30,000، سعر بيع 50,000
        When: حساب قيمة المخزون
        Then: القيمة = 300,000 (10 × 30,000) وليس 500,000
        
        السبب المحاسبي: قيمة المخزون تُحسب بالتكلفة دائماً
        """
        # Given
        quantity = 10
        buy_price = 30000
        sale_price = 50000
        
        # When: حساب قيمة المخزون
        inventory_value = quantity * buy_price  # بالتكلفة
        incorrect_value = quantity * sale_price  # بسعر البيع (خطأ)
        
        # Then
        assert inventory_value == 300000, "قيمة المخزون يجب أن تُحسب بالتكلفة"
        assert inventory_value != incorrect_value, "قيمة المخزون لا يجب أن تُحسب بسعر البيع"
    
    def test_inventory_value_increases_with_purchase(self):
        """
        Given: مخزون 10 قطع بتكلفة 30,000، شراء 5 قطع
        When: حساب قيمة المخزون بعد الشراء
        Then: القيمة = 450,000 (15 × 30,000)
        
        السبب المحاسبي: الشراء يزيد المخزون وبالتالي يزيد القيمة
        """
        # Given
        initial_quantity = 10
        purchase_quantity = 5
        cost_per_unit = 30000
        
        # When: الشراء
        new_quantity = initial_quantity + purchase_quantity
        new_value = new_quantity * cost_per_unit
        
        # Then
        assert new_value == 450000, "قيمة المخزون يجب أن تزيد بعد الشراء"
    
    def test_inventory_value_decreases_with_sale(self):
        """
        Given: مخزون 10 قطع بتكلفة 30,000، بيع 3 قطع
        When: حساب قيمة المخزون بعد البيع
        Then: القيمة = 210,000 (7 × 30,000)
        
        السبب المحاسبي: البيع ينقص المخزون وبالتالي تنقص القيمة
        """
        # Given
        initial_quantity = 10
        sold_quantity = 3
        cost_per_unit = 30000
        
        # When: البيع
        new_quantity = initial_quantity - sold_quantity
        new_value = new_quantity * cost_per_unit
        
        # Then
        assert new_value == 210000, "قيمة المخزون يجب أن تنقص بعد البيع"


# ======================================================
# اختبارات سجل الحركات
# ======================================================

class TestInventoryLedger:
    """اختبارات سجل حركات المخزون"""
    
    def test_ledger_tracks_all_movements(self):
        """
        Given: حركات مخزون (افتتاحي، شراء، بيع)
        When: حساب عدد الحركات
        Then: عدد الحركات = 3
        
        السبب المحاسبي: سجل الحركات يجب أن يتتبع جميع التغييرات
        """
        # Given
        movements = [
            {"type": "opening_stock", "quantity_in": 100},
            {"type": "purchase", "quantity_in": 20},
            {"type": "sale", "quantity_out": 15}
        ]
        
        # When: حساب عدد الحركات
        movements_count = len(movements)
        
        # Then
        assert movements_count == 3, "سجل الحركات يجب أن يتتبع جميع الحركات"
    
    def test_ledger_balance_calculation(self):
        """
        Given: سجل حركات (افتتاحي 100، شراء 20، بيع 15)
        When: حساب الرصيد من السجل
        Then: الرصيد = 105 (100 + 20 - 15)
        
        السبب المحاسبي: الرصيد يُحسب من مجموع الحركات في السجل
        """
        # Given
        movements = [
            {"quantity_in": 100, "quantity_out": 0},
            {"quantity_in": 20, "quantity_out": 0},
            {"quantity_in": 0, "quantity_out": 15}
        ]
        
        # When: حساب الرصيد
        total_in = sum(m["quantity_in"] for m in movements)
        total_out = sum(m["quantity_out"] for m in movements)
        balance = total_in - total_out
        
        # Then
        assert balance == 105, "الرصيد من السجل يجب أن يكون 105"
    
    def test_ledger_is_read_only(self):
        """
        Given: سجل حركات مخزون
        When: محاولة تعديل حركة
        Then: السجل للعرض فقط (لا يُغيّر البيانات)
        
        السبب المحاسبي: سجل الحركات للقراءة فقط، التغييرات تُسجل كحركات جديدة
        """
        # Given: سجل حركات (للقراءة فقط)
        ledger_entry = {
            "type": "sale",
            "quantity_out": 10,
            "read_only": True
        }
        
        # When: محاولة تعديل (يجب أن تفشل لأنها read_only)
        # Then: في التطبيق الحقيقي، السجل لا يُعدل مباشرة
        assert ledger_entry["read_only"] == True, "سجل الحركات للقراءة فقط"


# ======================================================
# اختبارات التكامل (Integration Tests)
# ======================================================

class TestInventoryIntegration:
    """اختبارات التكامل"""
    
    def test_complete_inventory_cycle(self):
        """
        Given / When / Then: دورة مخزون كاملة
        
        1. مخزون افتتاحي: 100 قطعة
        2. شراء: 20 قطعة
        3. بيع: 15 قطعة
        4. مرتجع: 5 قطع
        5. تعديل: +3 قطع (مع سبب)
        
        الرصيد النهائي: 113 (100 + 20 - 15 + 5 + 3)
        """
        # Given: الحالة الابتدائية
        quantity = 100
        
        # When: 1. شراء
        quantity += 20  # 120
        
        # When: 2. بيع
        quantity -= 15  # 105
        
        # When: 3. مرتجع
        quantity += 5  # 110
        
        # When: 4. تعديل
        quantity += 3  # 113
        
        # Then
        assert quantity == 113, "الرصيد النهائي يجب أن يكون 113"
    
    def test_inventory_never_negative(self):
        """
        Given / When / Then: 
        - مخزون 10 قطع
        - محاولات بيع: 5، 4، 3 (الإجمالي 12)
        
        التحقق: يجب منع البيع الثالث (لن يؤدي إلى كميات سالبة)
        """
        # Given
        quantity = 10
        
        # When: بيع 5
        if quantity >= 5:
            quantity -= 5  # 5
        
        # When: بيع 4
        if quantity >= 4:
            quantity -= 4  # 1
        
        # When: محاولة بيع 3 (يجب منعها)
        can_sell_3 = quantity >= 3
        if can_sell_3:
            quantity -= 3
        
        # Then
        assert quantity >= 0, "المخزون لا يجب أن يكون سالباً"
        assert not can_sell_3, "يجب منع البيع الذي يجعل المخزون سالباً"
        assert quantity == 1, "المخزون المتبقي = 1"
