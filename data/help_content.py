"""Curated help content — merged into translations/*.json by fill_help_content.py"""

HELP_PAGES_AR = {
    "index.dashboard": {
        "title": "لوحة التحكم",
        "body": "نظرة عامة على أداء عملك: المبيعات، الطلبات، المخزون، والتنبيهات. استخدم البطاقات والرسوم البيانية لمتابعة الأرقام اليومية.",
    },
    "index.index": {
        "title": "لوحة التحكم",
        "body": "نظرة عامة على أداء عملك: المبيعات، الطلبات، المخزون، والتنبيهات.",
    },
    "inventory.index": {
        "title": "المخزون",
        "body": "إدارة المنتجات والكميات. ابحث بالاسم أو الباركود، عدّل الكميات، واطبع تقارير الجرد.",
    },
    "inventory.add_product": {
        "title": "إضافة منتج",
        "body": "أدخل بيانات المنتج الجديد: الاسم، السعر، الكمية، والباركود. يُحدَّث المخزون تلقائياً.",
    },
    "orders.index": {
        "title": "الطلبات",
        "body": "متابعة طلبات العملاء من الإنشاء حتى التسليم. استخدم الفلاتر للبحث بالحالة أو التاريخ.",
    },
    "pos.index": {
        "title": "نقطة البيع",
        "body": "بيع سريع من الكاشير. امسح الباركود أو ابحث عن المنتج، ثم أكمل الدفع واطبع الفاتورة.",
    },
    "purchases.index": {
        "title": "المشتريات",
        "body": "تسجيل فواتير الشراء من الموردين. تُحدَّث الكميات والتكلفة في المخزون تلقائياً.",
    },
    "suppliers.index": {
        "title": "الموردين",
        "body": "إدارة بيانات الموردين وأرصدتهم. يمكنك عرض كشف الحساب ومتابعة المستحقات.",
    },
    "customers.index": {
        "title": "الزبائن",
        "body": "قاعدة بيانات العملاء: الأسماء، الهواتف، والعناوين. تُستخدم عند إنشاء الطلبات والفواتير.",
    },
    "shipping.index": {
        "title": "الشحن",
        "body": "إدارة شركات الشحن وتقارير التسليم. تتبع الطرود وحالة الشحنات.",
    },
    "expenses.index": {
        "title": "المصاريف",
        "body": "تسجيل مصاريف الشركة اليومية. صنّف المصروف واربطه بالحساب المحاسبي المناسب.",
    },
    "cash.index": {
        "title": "الصندوق",
        "body": "حركة النقدية: الإيرادات والمصروفات النقدية. راقب رصيد الصندوق لحظياً.",
    },
    "accounts.index": {
        "title": "الحسابات",
        "body": "دليل الحسابات والقيود المحاسبية. تتبع الأرصدة والتقارير المالية.",
    },
    "reports.index": {
        "title": "التقارير",
        "body": "تقارير المبيعات والمخزون والأرباح. اختر الفترة والفرع ثم صدّر النتائج.",
    },
    "reports.financial": {
        "title": "التقارير المالية",
        "body": "ملخص مالي شامل: الإيرادات، المصاريف، وصافي الربح مع رسوم بيانية.",
    },
    "settings.index": {
        "title": "الإعدادات",
        "body": "ضبط إعدادات الشركة: المظهر، الفروع، الفواتير، والمتجر الإلكتروني.",
    },
    "employees.index": {
        "title": "الموظفين",
        "body": "إدارة حسابات الموظفين وصلاحياتهم. أضف موظفاً وحدد دوره في النظام.",
    },
    "permissions.index": {
        "title": "الصلاحيات",
        "body": "تحكم بمن يرى ماذا في النظام. أنشئ أدواراً وخصص الصلاحيات لكل دور.",
    },
    "fixed_assets.index": {
        "title": "الأصول الثابتة",
        "body": "إدارة الأصول والإهلاك والصيانة. تتبع قيمة الأصول عبر الزمن.",
    },
    "pos.pos": {
        "title": "نقطة البيع",
        "body": "واجهة البيع السريع. أضف المنتجات للسلة واختر طريقة الدفع.",
    },
    "maintenance.index": {
        "title": "صيانة المنتجات",
        "body": "تتبع المنتجات المرسلة للصيانة والورش. سجّل العودة للمخزون عند الاكتمال.",
    },
    "superadmin.index": {
        "title": "لوحة السوبر أدمن",
        "body": "إدارة مركزية للشركات والاشتراكات وخطط النظام.",
    },
}

HELP_FIELDS_AR = {
    # Dashboard
    "dashboard.sales_today": "إجمالي مبيعات اليوم من جميع القنوات (POS والطلبات).",
    "dashboard.orders_pending": "عدد الطلبات التي لم تُسلَّم بعد وتحتاج متابعة.",
    "dashboard.low_stock": "منتجات وصلت لحد التنبيه وتحتاج إعادة توريد.",
    "dashboard.branch_filter": "اختر فرعاً محدداً أو اعرض بيانات كل الفروع معاً.",
    # Inventory
    "inventory.product_name": "اسم المنتج كما يظهر في الفواتير والمتجر والتقارير.",
    "inventory.sku": "رمز تعريف فريد للمنتج. يُستخدم في البحث والجرد.",
    "inventory.barcode": "الباركود للمسح السريع في نقطة البيع والمخزون.",
    "inventory.price": "سعر البيع للعميل. يُطبَّق تلقائياً في الفواتير.",
    "inventory.cost": "تكلفة الشراء. تُستخدم لحساب الربح وهامش الربح.",
    "inventory.quantity": "الكمية الحالية في المخزون. تتغير مع البيع والشراء والجرد.",
    "inventory.opening_stock": "الرصيد الافتتاحي عند إضافة منتج جديد. يُحدَّث المخزون ورأس المال.",
    "inventory.category": "تصنيف المنتج لتنظيم القائمة والتقارير.",
    "inventory.min_stock": "عند وصول الكمية لهذا الحد يظهر تنبيه نقص المخزون.",
    "inventory.adjust_reason": "كل حركة مخزون يجب أن تكون مرتبطة بسبب واضح للمراجعة.",
    "inventory.search": "ابحث بالاسم أو SKU أو الباركود للوصول السريع للمنتج.",
    # Orders
    "orders.status": "حالة الطلب: جديد، قيد التجهيز، شُحن، أو مُسلَّم.",
    "orders.customer": "العميل صاحب الطلب. يُسحب بياناته تلقائياً للفاتورة.",
    "orders.total": "المبلغ الإجمالي شامل الخصومات والشحن إن وُجد.",
    "orders.shipping_company": "شركة الشحن المكلَّفة بتوصيل الطلب.",
    "orders.tracking_number": "رقم التتبع من شركة الشحن لمتابعة الطرد.",
    "orders.payment_method": "طريقة الدفع: نقدي، تحويل، أو عند الاستلام.",
    "orders.notes": "ملاحظات داخلية للفريق لا تظهر للعميل.",
    "orders.filter_date": "فلترة الطلبات حسب تاريخ الإنشاء أو التسليم.",
    # POS
    "pos.product_search": "ابحث بالاسم أو امسح الباركود لإضافة المنتج للسلة.",
    "pos.quantity": "عدد الوحدات المباعة. يمكن تعديله قبل إتمام البيع.",
    "pos.discount": "خصم على الفاتورة أو منتج محدد. يُخصم من الإجمالي.",
    "pos.payment": "اختر طريقة الدفع: نقدي، بطاقة، أو آجل.",
    "pos.customer": "ربط البيع بعميل مسجَّل (اختياري للمبيعات النقدية).",
    # Purchases
    "purchases.supplier": "المورد الذي اشتريت منه. يُحدَّث رصيده تلقائياً.",
    "purchases.invoice_number": "رقم فاتورة المورد للمرجعية والمطابقة.",
    "purchases.items": "المنتجات المشتراة مع الكمية وسعر الشراء لكل وحدة.",
    "purchases.total": "إجمالي فاتورة الشراء. يُسجَّل كمصروف أو دين للمورد.",
    # Suppliers
    "suppliers.name": "اسم المورد أو الشركة المورِّدة.",
    "suppliers.phone": "رقم التواصل مع المورد.",
    "suppliers.balance": "الرصيد المستحق للمورد (دين عليك).",
    # Customers
    "customers.name": "اسم العميل كما يظهر في الطلبات والفواتير.",
    "customers.phone": "رقم الهاتف للتواصل وتأكيد الطلبات.",
    "customers.address": "عنوان التوصيل الافتراضي للعميل.",
    # Shipping
    "shipping.company": "شركة الشحن المسجَّلة في النظام.",
    "shipping.rate": "تعرفة الشحن حسب المحافظة أو الوزن.",
    "shipping.tracking": "رقم تتبع الشحنة من شركة النقل.",
    # Expenses
    "expenses.category": "تصنيف المصروف (إيجار، رواتب، مشتريات، إلخ).",
    "expenses.amount": "مبلغ المصروف بالدينار العراقي.",
    "expenses.date": "تاريخ حدوث المصروف للتقارير المالية.",
    "expenses.account": "الحساب المحاسبي الذي يُخصم منه المبلغ.",
    "expenses.recurring": "مصروف متكرر: يُسجّل عدة فترات دفعة واحدة ويُخصم المبلغ كاملاً من الصندوق فوراً.",
    # Cash
    "cash.balance": "الرصيد الحالي في الصندوق النقدي.",
    "cash.income": "إيراد نقدي وارد للصندوق.",
    "cash.expense": "مصروف نقدي صادر من الصندوق.",
    # Accounts
    "accounts.code": "رمز الحساب في دليل الحسابات.",
    "accounts.name": "اسم الحساب (أصول، خصوم، إيرادات، مصاريف).",
    "accounts.balance": "الرصيد الحالي للحساب.",
    "accounts.journal": "قيد محاسبي يُسجَّل الحركة بين حسابين.",
    # Reports
    "reports.date_from": "بداية الفترة الزمنية للتقرير.",
    "reports.date_to": "نهاية الفترة الزمنية للتقرير.",
    "reports.branch": "تصفية التقرير حسب فرع محدد.",
    "reports.export": "تصدير النتائج إلى Excel أو PDF.",
    # Settings
    "settings.theme": "مظهر الواجهة: فاتح أو داكن.",
    "settings.font_size": "حجم النصوص في أغلب صفحات النظام.",
    "settings.currency": "رمز العملة الافتراضي في التقارير والفواتير.",
    "settings.company_name": "اسم الشركة الظاهر في الفواتير والتقارير.",
    "settings.logo": "شعار الشركة على الفواتير والمتجر.",
    "settings.branches": "فروع الشركة. كل فرع له مخزون ومبيعات منفصلة.",
    # Employees
    "employees.name": "اسم الموظف في النظام.",
    "employees.role": "دور الموظف يحدد صلاحياته (مدير، كاشير، إلخ).",
    "employees.username": "اسم المستخدم لتسجيل الدخول.",
    # Permissions
    "permissions.role": "مجموعة صلاحيات تُعطى لعدة موظفين.",
    "permissions.permission": "صلاحية محددة (عرض الطلبات، إدارة المخزون، إلخ).",
    # Fixed assets
    "fixed_assets.name": "اسم الأصل الثابت (معدات، مركبات، أثاث).",
    "fixed_assets.value": "القيمة الأصلية عند الشراء.",
    "fixed_assets.depreciation": "الإهلاك الشهري أو السنوي المخصوم من قيمة الأصل.",
    "fixed_assets.disposal": "طلب استبعاد أو بيع أصل ثابت.",
    # Beauty
    "beauty.service": "خدمة صالون التجميل المقدَّمة للعميل.",
    "beauty.appointment": "موعد حجز العميل لجلسة خدمة.",
    # Maintenance
    "maintenance.product": "المنتج المرسل للصيانة من المخزون.",
    "maintenance.workshop": "ورشة أو مركز الصيانة الخارجي.",
    "maintenance.quantity": "عدد القطع المرسلة للصيانة.",
    # Superadmin
    "superadmin.tenant": "شركة مسجَّلة في المنصة ولها قاعدة بيانات منفصلة.",
    "superadmin.plan": "خطة الاشتراك تحدد الميزات المتاحة للشركة.",
    # General
    "general.search": "ابحث في السجلات بالاسم أو الرقم أو التاريخ.",
    "general.filter": "تصفية النتائج حسب معايير محددة.",
    "general.export": "تصدير البيانات المعروضة إلى ملف.",
    "general.print": "طباعة التقرير أو الفاتورة الحالية.",
    "general.save": "حفظ التغييرات. تأكد من صحة البيانات قبل الحفظ.",
    "general.delete": "حذف السجل نهائياً. لا يمكن التراجع عن هذا الإجراء.",
}

# English translations for help_fields (key pages get English in en.json via script)
HELP_PAGES_EN = {
    k: {
        "title": v["title"],
        "body": v["body"].replace("نظرة عامة", "Overview").replace("إدارة", "Manage"),
    }
    for k, v in HELP_PAGES_AR.items()
}

HELP_FIELDS_EN = {
    "inventory.product_name": "Product name as shown on invoices and in the store.",
    "inventory.price": "Selling price applied automatically on invoices.",
    "inventory.quantity": "Current stock quantity. Changes with sales and purchases.",
    "orders.status": "Order status: new, processing, shipped, or delivered.",
    "pos.product_search": "Search by name or scan barcode to add to cart.",
    "dashboard.sales_today": "Total sales today from all channels.",
    "general.search": "Search records by name, number, or date.",
    "general.save": "Save changes. Verify data before saving.",
}
