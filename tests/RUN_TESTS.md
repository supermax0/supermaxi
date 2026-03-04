# 🚀 دليل تشغيل الاختبارات (How to Run Tests)

## 📋 الخطوات السريعة

### 1️⃣ تثبيت المتطلبات

```bash
pip install -r requirements-test.txt
```

أو تثبيت pytest فقط:

```bash
pip install pytest pytest-cov
```

### 2️⃣ تشغيل جميع الاختبارات

```bash
pytest
```

أو مع تفاصيل أكثر:

```bash
pytest -v
```

### 3️⃣ تشغيل اختبار محدد

```bash
pytest tests/test_accounting_calculations.py::TestRevenueCalculations
```

أو اختبار محدد:

```bash
pytest tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_excludes_returns
```

---

## 📊 خيارات التشغيل

### تشغيل مع تفاصيل كاملة

```bash
pytest -v -s
```

### تشغيل مع تغطية الكود

```bash
pytest --cov=utils.accounting_calculations --cov-report=html
```

بعد التشغيل، افتح `htmlcov/index.html` لرؤية التغطية.

### تشغيل اختبارات محددة فقط

```bash
# اختبارات الإيرادات فقط
pytest -k "revenue"

# اختبارات الربح فقط
pytest -k "profit"

# اختبارات المخزون فقط
pytest -k "inventory"
```

### تشغيل مع توقف عند أول فشل

```bash
pytest -x
```

### تشغيل مع إظهار جميع المخرجات

```bash
pytest -v -s --tb=long
```

---

## 🎯 أمثلة التشغيل

### مثال 1: تشغيل سريع

```bash
pytest tests/ -v
```

**النتيجة المتوقعة:**
```
tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_excludes_returns PASSED
tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_not_affected_by_cogs PASSED
...
```

### مثال 2: تشغيل مع تغطية

```bash
pytest --cov=utils.accounting_calculations --cov-report=term
```

**النتيجة المتوقعة:**
```
Name                              Stmts   Miss  Cover
-----------------------------------------------------
utils/accounting_calculations.py    200     50    75%
```

### مثال 3: تشغيل اختبار محدد

```bash
pytest tests/test_accounting_calculations.py::TestProfitCalculations::test_profit_formula_correct -v
```

---

## ✅ التحقق من نجاح الاختبارات

### النتيجة الناجحة

```
========================= test session starts =========================
platform win32 -- Python 3.10.0
collected 20 items

tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_excludes_returns PASSED
tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_not_affected_by_cogs PASSED
...
========================= 20 passed in 0.50s =========================
```

### النتيجة مع فشل

```
========================= test session starts =========================
platform win32 -- Python 3.10.0
collected 20 items

tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_excludes_returns PASSED
tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_not_affected_by_cogs FAILED
...

FAILED tests/test_accounting_calculations.py::TestRevenueCalculations::test_revenue_not_affected_by_cogs - AssertionError: الإيرادات لا يجب أن تتأثر بـ COGS

========================= 1 failed, 19 passed in 0.50s =========================
```

---

## 🔧 Troubleshooting

### خطأ: No module named 'pytest'

**الحل:**
```bash
pip install pytest
```

### خطأ: ModuleNotFoundError

**الحل:** تأكد من وجود الملفات:
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_accounting_calculations.py`

### خطأ: ImportError

**الحل:** تأكد من:
- وجود `pytest.ini` في المجلد الرئيسي
- تشغيل الاختبارات من المجلد الرئيسي للمشروع

---

## 📈 الإحصائيات المتوقعة

- **عدد الاختبارات:** ~20+ اختبار
- **الوقت المتوقع:** < 1 ثانية
- **التغطية المتوقعة:** 100% للقواعد المحاسبية (لأنها اختبارات منطقية)

---

## 📝 ملاحظات

- ✅ جميع الاختبارات **معزولة** ولا تؤثر على النظام الحالي
- ✅ الاختبارات **لا تتطلب قاعدة بيانات** - تستخدم بيانات وهمية
- ✅ الاختبارات **قراءة وتحليل فقط** - لا تغير أي كود إنتاجي

---

**✅ جاهز للتشغيل بعد تثبيت pytest!**
