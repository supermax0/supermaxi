# خطة إعادة بناء واجهة بوابة المندوب

## Current architecture

- تطبيق ويب عربي RTL على Flask + قوالب Jinja، وليس React.
- المسار الوحيد للواجهة: `routes/delivery_agent.py` مع القالبين `templates/delivery_agent/login.html` و `templates/delivery_agent/dashboard.html`.
- الجلسة سيرفرية (`agent_id`, `agent_name`, `agent_tenant_slug`) وترتبط بحساب مراسلة موظف ظل عبر `utils/agent_employee_link.py`.
- الطلبات النشطة تُجمع من كشوف `AGT-*` المفتوحة ومن الطلبات المربوطة مباشرة. حفظ النتيجة لا يغيّر حالة الفاتورة؛ المحاسب ينفّذ الكشف من النظام الرئيسي.
- المحادثة هي نظام `/messages` الحالي. تبويب المحادثة كان يحوّل إلى صفحة الموظفين الكاملة.
- أندرويد `iq.finora.deliveryagent` غلاف WebView مع SharedPreferences للخادم والشركة، وربط أول تشغيل، ورجوع، وسحب للتحديث.

## Existing APIs

| Method | Path | Role |
| --- | --- | --- |
| GET | `/delivery-agent/` | جلسة → لوحة، وإلا تسجيل الدخول |
| GET/POST | `/delivery-agent/login` و `/login/<company>` | صفحة الدخول والتحقق |
| GET | `/delivery-agent/logout` | إنهاء الجلسة ثم العودة لدخول الشركة |
| GET | `/delivery-agent/dashboard` | الطلبات النشطة والمنفذة والإحصاءات |
| POST | `/delivery-agent/update-order-status` | حفظ واصل / ملغي / مؤجل داخل الكشف |
| POST | `/delivery-agent/update-order-note` | ملاحظة بحد 1000 حرف |
| POST | `/delivery-agent/execute-report/<id>` | تنفيذ المحاسب فقط — لا يُعرض للمندوب |
| GET | `/messages/conversations` | قائمة المحادثات |
| GET | `/messages/get/<user_id>` | رسائل الغرفة |
| POST | `/messages/send` | إرسال |
| GET | `/messages/unread-count` | الشارة كل 15 ثانية |

قيم الحالة في الواجهة تبقى العربية كما يتوقع المسار الحالي: `واصل`، `ملغي`، `مؤجل`. حالة الفاتورة المعروضة: `تم الطلب`، `جاري الشحن`، `قيد الشحن`.

## Routes

لا تُضاف مسارات API. تفاصيل الطلب وغرفة المحادثة والحساب تُفتح داخل لوحة التحكم مع `history.pushState` حتى يعمل زر الرجوع في WebView.

## Files to modify

- `templates/delivery_agent/login.html`
- `templates/delivery_agent/dashboard.html`
- `routes/delivery_agent.py` — حقول عرض فقط: تاريخ عربي للكشف، وقائمة الكشوف الجاهزة للمحاسب، وجهات اتصال المحادثة من الموظفين الحاليين
- `mobile/finora_delivery_agent_android` — شريط تقدم محدد، تحقق من عنوان الخادم، وفتح `maps`

## Files to create

- `static/delivery_agent/agent.css` — رموز التصميم والمكوّنات
- `static/delivery_agent/agent.js` — الطلبات، التفاصيل، الملاحظة، المحادثة، الحساب، التوست، عدم الاتصال
- `static/delivery_agent/login.js` — الدخول وإظهار كلمة المرور

## Components

ترويسة، تنقل سفلي، تبويبات سطح المكتب، بطاقة إحصائية، مجموعة كشف، بطاقة طلب، شارة حالة، بحث، حالة فارغة، ورقة ملاحظة، ورقة تفاصيل، توست، شريط تحميل، قائمة حساب، محادثة وغرفة.

## Android changes

الإبقاء على WebView. إضافة تحقق `http/https` لمعرف الشركة، شريط تقدم 0–100، وفتح روابط الخرائط خارج التطبيق. شاشة الربط والخطأ الأصليتان تبقيان.

## Potential risks

- تضمين المحادثة يعتمد على جلسة الموظف الظل الموجودة. إن فشل الربط تبقى شارة غير المقروء فارغة وتظهر حالة خطأ مع إعادة المحاولة.
- `تم الطلب` تبقى ظاهرة كحالة الفاتورة ولا تُرسل للحفظ، لأن المسار يقبل فقط واصل / ملغي / مؤجل.
- لا زر تنفيذ كشف للمندوب.

## Implementation phases

1. نظام التصميم.
2. الدخول وشاشة الافتتاح.
3. اللوحة والطلبات النشطة والتفاصيل والحفظ.
4. المنفذة، المحادثة، الحساب، الفراغ، عدم الاتصال.
5. ضبط WebView.
6. التحقق من تصيير القوالب.
