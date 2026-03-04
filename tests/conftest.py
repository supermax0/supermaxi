"""
إعدادات pytest و Fixtures المشتركة
pytest Configuration and Shared Fixtures

هذا الملف يحتوي على:
- Fixtures مشتركة لجميع الاختبارات
- Mock objects للبيانات
- إعدادات الاختبار
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime


# ======================================================
# Fixtures للبيانات الوهمية (Mock Data)
# ======================================================

@pytest.fixture
def mock_invoice_cash_sale():
    """Mock Invoice object for cash sale"""
    invoice = Mock()
    invoice.id = 1
    invoice.total = 50000  # 50,000 د.ع
    invoice.status = "مسدد"
    invoice.payment_status = "مسدد"
    invoice.status_history = ["تم الطلب", "مسدد"]
    invoice.created_at = datetime(2024, 1, 15, 10, 0, 0)
    invoice.customer_name = "زبون اختبار"
    return invoice


@pytest.fixture
def mock_invoice_credit_sale():
    """Mock Invoice object for credit sale"""
    invoice = Mock()
    invoice.id = 2
    invoice.total = 40000  # 40,000 د.ع
    invoice.status = "تم التوصيل"
    invoice.payment_status = "غير مسدد"
    invoice.created_at = datetime(2024, 1, 16, 11, 0, 0)
    invoice.customer_name = "زبون آجل"
    return invoice


@pytest.fixture
def mock_invoice_returned():
    """Mock Invoice object for returned sale"""
    invoice = Mock()
    invoice.id = 3
    invoice.total = 20000  # 20,000 د.ع (مرتجع)
    invoice.status = "مرتجع"
    invoice.payment_status = "مرتجع"
    invoice.created_at = datetime(2024, 1, 17, 12, 0, 0)
    invoice.customer_name = "زبون مرتجع"
    return invoice


@pytest.fixture
def mock_order_items():
    """Mock OrderItem objects for testing"""
    items = []
    
    # OrderItem 1: للمبيعات النقدية
    item1 = Mock()
    item1.id = 1
    item1.invoice_id = 1
    item1.cost = 30000  # تكلفة 30,000
    item1.quantity = 1
    item1.price = 50000  # سعر البيع 50,000
    item1.product_name = "منتج اختبار 1"
    items.append(item1)
    
    # OrderItem 2: للمبيعات الآجلة
    item2 = Mock()
    item2.id = 2
    item2.invoice_id = 2
    item2.cost = 25000  # تكلفة 25,000
    item2.quantity = 1
    item2.price = 40000  # سعر البيع 40,000
    item2.product_name = "منتج اختبار 2"
    items.append(item2)
    
    # OrderItem 3: للمرتجعات
    item3 = Mock()
    item3.id = 3
    item3.invoice_id = 3
    item3.cost = 15000  # تكلفة 15,000
    item3.quantity = 1
    item3.price = 20000  # سعر البيع 20,000
    item3.product_name = "منتج مرتجع"
    items.append(item3)
    
    return items


@pytest.fixture
def mock_products():
    """Mock Product objects for testing"""
    products = []
    
    # Product 1
    product1 = Mock()
    product1.id = 1
    product1.name = "منتج 1"
    product1.quantity = 10
    product1.buy_price = 30000
    product1.sale_price = 50000
    product1.active = True
    products.append(product1)
    
    # Product 2
    product2 = Mock()
    product2.id = 2
    product2.name = "منتج 2"
    product2.quantity = 5
    product2.buy_price = 25000
    product2.sale_price = 40000
    product2.active = True
    products.append(product2)
    
    return products


@pytest.fixture
def mock_expenses():
    """Mock Expense objects for testing"""
    expenses = []
    
    expense1 = Mock()
    expense1.id = 1
    expense1.amount = 5000  # 5,000 د.ع
    expense1.title = "إيجار المحل"
    expense1.category = "تشغيلية"
    expense1.expense_date = datetime(2024, 1, 10).date()
    expenses.append(expense1)
    
    expense2 = Mock()
    expense2.id = 2
    expense2.amount = 3000  # 3,000 د.ع
    expense2.title = "مصروفات كهرباء"
    expense2.category = "تشغيلية"
    expense2.expense_date = datetime(2024, 1, 12).date()
    expenses.append(expense2)
    
    return expenses


@pytest.fixture
def mock_suppliers():
    """Mock Supplier objects for testing"""
    suppliers = []
    
    supplier1 = Mock()
    supplier1.id = 1
    supplier1.name = "مورد اختبار"
    supplier1.total_debt = 100000  # دين 100,000
    supplier1.total_paid = 70000   # مدفوع 70,000
    suppliers.append(supplier1)
    
    return suppliers


# ======================================================
# Fixtures للـ Database Session Mock
# ======================================================

@pytest.fixture
def mock_db_session():
    """Mock database session for testing"""
    session = Mock()
    return session


@pytest.fixture
def sample_accounting_data():
    """
    Sample accounting data for testing calculations
    
    Returns dict with:
    - invoices: list of mock invoices
    - order_items: list of mock order items
    - products: list of mock products
    - expenses: list of mock expenses
    - suppliers: list of mock suppliers
    """
    return {
        "invoices": [
            {"id": 1, "total": 50000, "status": "مسدد", "payment_status": "مسدد"},
            {"id": 2, "total": 40000, "status": "تم التوصيل", "payment_status": "غير مسدد"},
            {"id": 3, "total": 20000, "status": "مرتجع", "payment_status": "مرتجع"},
        ],
        "order_items": [
            {"id": 1, "invoice_id": 1, "cost": 30000, "quantity": 1, "price": 50000},
            {"id": 2, "invoice_id": 2, "cost": 25000, "quantity": 1, "price": 40000},
            {"id": 3, "invoice_id": 3, "cost": 15000, "quantity": 1, "price": 20000},
        ],
        "products": [
            {"id": 1, "quantity": 10, "buy_price": 30000, "active": True},
            {"id": 2, "quantity": 5, "buy_price": 25000, "active": True},
        ],
        "expenses": [
            {"id": 1, "amount": 5000},
            {"id": 2, "amount": 3000},
        ],
        "suppliers": [
            {"id": 1, "total_debt": 100000, "total_paid": 70000},
        ],
    }
