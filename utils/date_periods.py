"""
حساب الفترات الزمنية للداشبورد (Date Periods Calculator)
هذا الملف يحتوي على دوال لحساب تاريخ البداية والنهاية للفترات المختلفة
"""

from datetime import date, timedelta, datetime
from calendar import monthrange


def get_period_dates(period_type, custom_date_from=None, custom_date_to=None):
    """
    حساب تاريخ البداية والنهاية للفترة الزمنية
    
    Args:
        period_type: نوع الفترة (today, yesterday, last_7_days, this_week, last_30_days, this_month, last_month, this_year, last_year, custom)
        custom_date_from: تاريخ البداية المخصص (إذا كان period_type == 'custom')
        custom_date_to: تاريخ النهاية المخصص (إذا كان period_type == 'custom')
    
    Returns:
        tuple: (date_from, date_to) - تاريخ البداية وتاريخ النهاية
    """
    today = date.today()
    
    if period_type == "today":
        # اليوم فقط
        return today, today
    
    elif period_type == "yesterday":
        # أمس فقط
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    
    elif period_type == "last_7_days":
        # آخر 7 أيام (من اليوم)
        date_from = today - timedelta(days=6)  # اليوم + 6 أيام سابقة = 7 أيام
        return date_from, today

    elif period_type == "this_week":
        # من بداية الأسبوع (الاثنين) حتى اليوم
        weekday = today.weekday()  # اثنين=0 ... أحد=6
        date_from = today - timedelta(days=weekday)
        return date_from, today

    elif period_type == "last_30_days":
        # آخر 30 يوم (من اليوم) لكن ضمن السنة الحالية فقط
        # إذا رجعنا للخلف قبل 1/1 من السنة الحالية، نثبّت البداية على 1/1
        date_from = today - timedelta(days=29)  # اليوم + 29 يوم سابق = 30 يوم
        year_start = date(today.year, 1, 1)
        if date_from < year_start:
            date_from = year_start
        return date_from, today
    
    elif period_type == "this_month":
        # هذا الشهر
        date_from = today.replace(day=1)  # أول يوم في الشهر الحالي
        return date_from, today
    
    elif period_type == "last_month":
        # الشهر الماضي
        # أول يوم من الشهر الحالي - 1 يوم = آخر يوم من الشهر الماضي
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        return first_day_last_month, last_day_last_month
    
    elif period_type == "this_year":
        # السنة الحالية
        date_from = today.replace(month=1, day=1)  # 1 يناير من السنة الحالية
        return date_from, today
    
    elif period_type == "last_year":
        # السنة الماضية
        last_year = today.year - 1
        date_from = date(last_year, 1, 1)  # 1 يناير من السنة الماضية
        date_to = date(last_year, 12, 31)  # 31 ديسمبر من السنة الماضية
        return date_from, date_to
    
    elif period_type == "custom":
        # نطاق مخصص
        if custom_date_from and custom_date_to:
            # تحويل string إلى date إذا لزم الأمر
            if isinstance(custom_date_from, str):
                custom_date_from = datetime.strptime(custom_date_from, "%Y-%m-%d").date()
            if isinstance(custom_date_to, str):
                custom_date_to = datetime.strptime(custom_date_to, "%Y-%m-%d").date()
            return custom_date_from, custom_date_to
        else:
            # إذا لم يتم تحديد نطاق مخصص، نستخدم اليوم كافتراضي
            return today, today
    
    else:
        # افتراضي: اليوم
        return today, today


def get_period_label(period_type, custom_date_from=None, custom_date_to=None):
    """
    الحصول على اسم الفترة بالعربية للعرض
    
    Args:
        period_type: نوع الفترة
        custom_date_from: تاريخ البداية المخصص
        custom_date_to: تاريخ النهاية المخصص
    
    Returns:
        str: اسم الفترة بالعربية
    """
    period_labels = {
        "today": "اليوم",
        "yesterday": "أمس",
        "last_7_days": "آخر 7 أيام",
        "this_week": "هذا الأسبوع (من الاثنين)",
        "last_30_days": "آخر 30 يوم",
        "this_month": "هذا الشهر",
        "last_month": "الشهر الماضي",
        "this_year": "السنة الحالية",
        "last_year": "السنة الماضية",
        "custom": "نطاق مخصص"
    }
    
    if period_type == "custom" and custom_date_from and custom_date_to:
        # عرض التاريخين في حالة النطاق المخصص
        if isinstance(custom_date_from, str):
            custom_date_from = datetime.strptime(custom_date_from, "%Y-%m-%d").date()
        if isinstance(custom_date_to, str):
            custom_date_to = datetime.strptime(custom_date_to, "%Y-%m-%d").date()
        return f"{custom_date_from.strftime('%Y-%m-%d')} إلى {custom_date_to.strftime('%Y-%m-%d')}"
    
    return period_labels.get(period_type, "اليوم")
