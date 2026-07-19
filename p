أنت مهندس برمجيات Senior وخبير في:

* Flask وPython.
* PostgreSQL وSQLAlchemy.
* REST API.
* Redis وCelery.
* Flutter وDart.
* تطبيقات الفيديو القصير.
* Social Commerce.
* أنظمة التجارة الإلكترونية.
* أنظمة Multi-Tenant.
* تحسين أداء تطبيقات الهاتف.
* الأمن السيبراني.
* تصميم UI/UX احترافي ومتجاوب.
* دمج الذكاء الاصطناعي داخل الأنظمة التجارية.

لدي نظام محاسبي وتشغيلي اسمه **Finora**، وهو نظام قائم ويعمل حالياً، ومبني باستخدام:

* Flask.
* Jinja2.
* Vanilla JavaScript.
* SQLAlchemy.
* قاعدة بيانات النظام الحالية.
* نظام منتجات.
* مخزون.
* طلبات.
* عملاء.
* موظفين وصلاحيات.
* تقارير.
* نظام محاسبي.
* متجر إلكتروني قائم.
* نظام Multi-Tenant أو مخطط للتوسع إليه.

أريد إنشاء تطبيق هاتف احترافي مرتبط مباشرة بنظام Finora، يجمع بين:

* الفيديوهات القصيرة مثل أسلوب TikTok.
* التجارة الإلكترونية.
* المنتجات.
* العربة.
* الطلبات.
* النقاط والجوائز.
* الخصومات والكوبونات.
* الذكاء الاصطناعي.
* الحسابات الشخصية.
* الإعجابات.
* التعليقات.
* الردود داخل التعليقات.
* مشاركة الفيديوهات.
* الإشعارات.
* التحليلات.

اسم التطبيق الحالي:

```text
Finora
```

التطبيق يجب أن يعمل على:

```text
Android
iOS
```

استخدم:

```text
Flutter
```

ولا تستخدم WebView كتطبيق رئيسي.

يجب أن يكون التطبيق Native-like وسريعاً جداً وسلساً ومتجاوباً مع جميع أنواع الهواتف والأجهزة اللوحية والشاشات المختلفة.

---

# الهدف الرئيسي

إنشاء منصة Social Commerce مدموجة بالكامل داخل Finora.

يجب أن يتمكن مدير الشركة من التحكم بكل تفاصيل التطبيق من داخل لوحة تحكم Finora الحالية، بدون الحاجة إلى تعديل الكود أو الدخول إلى السيرفر.

المدير يستطيع من داخل Finora:

* رفع الفيديوهات.
* تعديل الفيديوهات.
* حذف الفيديوهات.
* جدولة نشر الفيديوهات.
* ترتيب الفيديوهات.
* ربط الفيديو بمنتج واحد أو عدة منتجات.
* تحديد سعر خاص داخل الفيديو.
* تحديد خصم خاص.
* تفعيل أو إيقاف التعليقات.
* تفعيل أو إيقاف المشاركة.
* تثبيت التعليقات.
* حذف أو إخفاء التعليقات.
* الرد باسم الشركة.
* حظر المستخدمين.
* إدارة المنتجات.
* إدارة الطلبات.
* إدارة النقاط.
* إدارة الجوائز.
* إدارة الخصومات.
* إدارة الكوبونات.
* إدارة الحملات.
* إدارة الإشعارات.
* التحكم في أقسام التطبيق.
* التحكم في ألوان التطبيق وهويته.
* التحكم بالذكاء الاصطناعي.
* الاطلاع على الإحصائيات.
* معرفة مبيعات كل فيديو.
* معرفة عدد الطلبات التي جاءت من كل فيديو.
* تفعيل وإيقاف الميزات باستخدام Feature Flags.

---

# تعليمات مهمة قبل البدء

قبل كتابة أي كود:

1. افحص المشروع الحالي بالكامل.
2. افهم هيكل Flask الحالي.
3. افحص Models الموجودة.
4. افحص نظام المستخدمين والصلاحيات.
5. افحص نظام المنتجات والمخزون.
6. افحص نظام الطلبات.
7. افحص نظام العملاء.
8. افحص المتجر الإلكتروني الحالي.
9. افحص نظام Multi-Tenant.
10. افحص طريقة التسجيل وتسجيل الدخول.
11. افحص طريقة تخزين الصور والملفات.
12. افحص إعدادات البيئة.
13. افحص طريقة الترحيلات Database Migrations.
14. افحص الاختبارات الموجودة.
15. لا تفترض أسماء الملفات أو الجداول قبل فحص المشروع.

لا تقم بإعادة كتابة نظام Finora من الصفر.

لا تكسر الوظائف الحالية.

لا تغير الـModels الحالية بشكل عشوائي.

لا تنشئ نظام منتجات أو طلبات أو مخزون منفصل إذا كان النظام الحالي يوفرها.

يجب أن يكون نظام Finora الحالي هو مصدر الحقيقة الأساسي:

```text
Single Source of Truth
```

المنتجات والأسعار والمخزون والعملاء والطلبات يجب أن تعتمد على البيانات الحقيقية الموجودة داخل Finora.

---

# المعمارية المطلوبة

أنشئ معمارية مقسمة وواضحة:

```text
Finora Web Application
        │
        ├── Existing Web Interface
        │
        ├── Mobile App Admin Module
        │
        └── Mobile REST API v1
                    │
                    ▼
              Flutter Mobile App
              Android + iOS
```

ويكون النظام الكامل تقريباً:

```text
Flutter Application
        │
        │ HTTPS REST API
        ▼
Flask Mobile API
        │
        ├── PostgreSQL
        ├── Redis
        ├── Celery Workers
        ├── Object Storage
        ├── Video Processing
        ├── CDN
        ├── Notification Service
        └── AI Service
```

---

# تنظيم Backend

أنشئ Module مستقل داخل Finora باسم مناسب مثل:

```text
modules/mobile_app/
```

ويكون داخله تنظيم مشابه:

```text
modules/mobile_app/
├── __init__.py
├── models/
├── routes/
├── api/
├── services/
├── schemas/
├── repositories/
├── policies/
├── permissions/
├── tasks/
├── events/
├── analytics/
├── ai/
├── serializers/
├── validators/
└── tests/
```

استخدم Flask Blueprints.

لا تضع جميع الوظائف داخل ملف واحد.

افصل:

* Routes.
* Services.
* Repositories.
* Schemas.
* Validation.
* Permissions.
* Background Tasks.
* Analytics.
* AI integration.

أنشئ API versioning:

```http
/api/mobile/v1/
```

---

# تطبيق Flutter

أنشئ تطبيق Flutter داخل مجلد مستقل، مثل:

```text
mobile/
```

ويكون تنظيم المشروع بطريقة Feature-First:

```text
mobile/
├── lib/
│   ├── app/
│   ├── core/
│   │   ├── api/
│   │   ├── config/
│   │   ├── errors/
│   │   ├── storage/
│   │   ├── theme/
│   │   ├── routing/
│   │   ├── widgets/
│   │   ├── utils/
│   │   └── security/
│   ├── features/
│   │   ├── authentication/
│   │   ├── video_feed/
│   │   ├── comments/
│   │   ├── products/
│   │   ├── cart/
│   │   ├── checkout/
│   │   ├── orders/
│   │   ├── rewards/
│   │   ├── discounts/
│   │   ├── notifications/
│   │   ├── profile/
│   │   ├── favorites/
│   │   ├── ai_assistant/
│   │   └── settings/
│   └── main.dart
├── test/
├── integration_test/
└── pubspec.yaml
```

استخدم State Management منظماً وقابلاً للتوسع، ويفضل:

```text
Riverpod
```

استخدم:

```text
Dio
```

للاتصال بالـAPI.

أنشئ طبقات:

```text
Data
Domain
Presentation
```

لكن لا تعقد المشروع بدون حاجة.

استخدم Repository Pattern بالميزات التي تحتاج إليه.

---

# هوية وتصميم التطبيق

أريد تصميماً فخماً ومميزاً، وليس نسخة حرفية من TikTok.

الهوية المقترحة:

```text
Primary Dark: #08090C
Surface Dark: #111318
Soft White: #F7F6F2
Gold Accent: #D9A441
Muted Gold: #B9872F
Text Dark: #121212
Text Light: #F8F8F8
Error: #D94C4C
Success: #2EAD6B
```

يجب وضع الألوان داخل Design Tokens، وعدم نشر Hex Codes عشوائياً داخل الملفات.

استخدم:

* زوايا ناعمة.
* مساحات مريحة.
* Cards بسيطة.
* ظلال خفيفة.
* حركات سلسة.
* خط عربي واضح.
* Dark Mode للفيديوهات والذكاء الاصطناعي.
* Light Premium Mode للمتجر والحساب والجوائز.
* دعم RTL كاملاً.
* دعم اللغة العربية أولاً.
* إمكانية إضافة الإنجليزية مستقبلاً.

يجب أن يعمل التصميم على:

* الهواتف الصغيرة.
* الهواتف الكبيرة.
* أجهزة Android المختلفة.
* iPhone.
* iPhone Pro Max.
* الأجهزة اللوحية.
* الأجهزة القابلة للطي.

لا تستخدم أبعاداً ثابتة تعتمد على جهاز واحد.

استخدم:

* SafeArea.
* LayoutBuilder.
* MediaQuery بحذر.
* Responsive breakpoints.
* Adaptive components.

---

# شريط التنقل الرئيسي

أنشئ Bottom Navigation يحتوي على:

```text
الرئيسية
المتجر
Finora AI
المكافآت
حسابي
```

الأيقونات:

```text
الرئيسية: فيديو
المتجر: متجر أو حقيبة
Finora AI: نجمة أو ذكاء
المكافآت: هدية
حسابي: مستخدم
```

العربة يجب أن تكون متاحة بسرعة من المتجر والفيديو والمنتج.

---

# الصفحة الأولى: Video Feed

أنشئ صفحة فيديوهات عمودية مشابهة من حيث تجربة الاستخدام لتطبيقات الفيديو القصير، ولكن بهوية Finora الخاصة.

المستخدم يستطيع:

* تمرير للأعلى للانتقال للفيديو التالي.
* تمرير للأسفل للفيديو السابق.
* الضغط لإيقاف وتشغيل الفيديو.
* الضغط مرتين لإضافة Like.
* الضغط على زر الإعجاب.
* فتح التعليقات.
* كتابة تعليق.
* الرد على تعليق.
* الإعجاب بالتعليق.
* مشاركة الفيديو.
* حفظ الفيديو.
* فتح المنتج المرتبط.
* إضافة المنتج للعربة.
* الشراء المباشر.
* متابعة الحساب مستقبلاً.

واجهة الفيديو تحتوي على:

* الفيديو بكامل الشاشة.
* صورة الحساب أو الشركة.
* اسم الحساب.
* وصف الفيديو.
* Hashtags اختيارية.
* عدد المشاهدات.
* زر Like.
* عدد الإعجابات.
* زر التعليقات.
* عدد التعليقات.
* زر المشاركة.
* زر الحفظ.
* بطاقة المنتج.
* السعر.
* السعر قبل الخصم.
* السعر بعد الخصم.
* زر إضافة للعربة.
* زر شراء الآن.

يجب أن تكون بطاقة المنتج قابلة للسحب أو الفتح كـBottom Sheet.

---

# أداء الفيديو

هذه نقطة شديدة الأهمية.

لا تقم بإنشاء Video Player لكل فيديو في القائمة.

استخدم استراتيجية إدارة ذاكرة واضحة:

```text
Previous Video
Current Video
Next Video
```

قم بتهيئة الفيديو الحالي والفيديو التالي مسبقاً.

قم بتحرير Controllers البعيدة مباشرة.

لا تسمح باستمرار تشغيل فيديو خارج الشاشة.

أضف:

* Preloading.
* Caching محدود.
* Thumbnail placeholder.
* Retry عند فشل الفيديو.
* مؤشر تحميل بسيط.
* التعامل مع ضعف الإنترنت.
* التعامل مع انقطاع الإنترنت.
* استكمال الفيديو بعد عودة التطبيق.
* إيقاف الفيديو عند الانتقال للخلفية.
* احترام وضع توفير البيانات.
* احترام وضع توفير البطارية.

استخدم بث فيديو Adaptive Streaming، ويفضل:

```text
HLS
```

يتم إنشاء عدة جودات مثل:

```text
360p
540p
720p
1080p
```

لا ترسل الفيديو الأصلي الكبير مباشرة إلى الهاتف.

---

# رفع ومعالجة الفيديو

عندما يرفع المدير فيديو من Finora:

```text
Upload
→ Validate
→ Save Original
→ Queue Background Processing
→ Generate Thumbnail
→ Generate Video Qualities
→ Generate HLS Playlist
→ Upload Processed Assets
→ Publish or Schedule
```

استخدم:

```text
Redis
Celery
FFmpeg
```

لمعالجة الفيديو في الخلفية.

لا تنفذ FFmpeg داخل HTTP Request مباشرة.

أنشئ حالات للفيديو:

```text
draft
uploaded
processing
ready
scheduled
published
hidden
failed
archived
deleted
```

اعرض للمدير حالة المعالجة ونسبة التقدم والخطأ إن وجد.

---

# الجداول المطلوبة للفيديو

أنشئ Models مناسبة، مع مراعاة `tenant_id` في جميع الجداول التابعة للشركة.

مثال منطقي:

```text
MobileVideo
MobileVideoAsset
MobileVideoProduct
MobileVideoView
MobileVideoLike
MobileVideoShare
MobileVideoSave
MobileFeedEvent
```

بيانات الفيديو الأساسية:

```text
id
tenant_id
creator_id
title
description
status
visibility
thumbnail_url
original_asset_url
hls_master_url
duration_ms
aspect_ratio
processing_status
processing_error
allow_comments
allow_sharing
allow_saving
is_featured
priority
published_at
scheduled_at
created_at
updated_at
deleted_at
```

لا تعتمد على Counters فقط بدون مصادر بيانات.

يمكن تخزين counters محسوبة لتحسين الأداء مثل:

```text
views_count
likes_count
comments_count
shares_count
saves_count
```

لكن يجب تحديثها بطريقة آمنة ومتزامنة.

---

# التعليقات والردود

أنشئ نظام تعليقات يدعم:

* تعليق رئيسي.
* الرد على التعليق.
* إعجاب بالتعليق.
* حذف التعليق من صاحبه.
* إخفاء التعليق من الإدارة.
* تثبيت التعليق.
* الإبلاغ عن التعليق.
* حظر المستخدم.
* منع كلمات محددة.
* فلترة التعليقات المسيئة.
* اقتراح رد باستخدام AI.
* الرد باسم الشركة.

يفضل عرض مستويين فقط في واجهة الهاتف:

```text
Comment
└── Replies
```

حتى لو كان النظام الداخلي يدعم Threading.

الجداول:

```text
MobileComment
MobileCommentLike
MobileCommentReport
MobileBlockedUser
MobileModerationRule
```

حالات التعليق:

```text
visible
hidden
pending_review
reported
deleted
rejected
```

---

# نظام المستخدمين

اربط مستخدم الهاتف مع نظام العملاء الحالي في Finora.

لا تنشئ عميلين لنفس رقم الهاتف.

اعتمد رقم الهاتف كمفتاح مهم، مع دعم البريد الإلكتروني اختيارياً.

التسجيل الحالي المطلوب:

```text
Phone Number
OTP
Name
Optional Email
```

أنشئ:

* Access Token.
* Refresh Token.
* Device Session.
* Secure Token Storage.
* Logout per device.
* Logout all devices.
* Session revocation.

لا تخزن كلمات المرور أو التوكنات بشكل مكشوف.

الجداول المقترحة:

```text
MobileUser
MobileUserDevice
MobileUserSession
MobileOtpRequest
```

لكن إذا كان نظام المستخدمين الحالي يستطيع استيعاب مستخدم الهاتف، قم بتوسيعه بدلاً من التكرار.

---

# المتجر والمنتجات

قسم المتجر يجب أن يعتمد على المنتجات الحقيقية داخل Finora.

يعرض:

* البحث.
* التصنيفات.
* المنتجات الأكثر مبيعاً.
* المنتجات الجديدة.
* العروض.
* المنتجات المقترحة.
* المنتجات المشاهدة مؤخراً.
* المنتجات المحفوظة.
* المنتجات المرتبطة بفيديوهات.
* المنتجات المتوفرة.
* المنتجات النافدة.

صفحة المنتج تحتوي على:

* الصور.
* الفيديوهات.
* الاسم.
* الوصف.
* المواصفات.
* السعر.
* السعر القديم.
* نسبة الخصم.
* المخزون.
* خيارات المنتج.
* التقييم.
* زر إضافة للعربة.
* زر شراء الآن.
* فيديوهات مرتبطة بالمنتج.
* منتجات مشابهة.

لا تعرض كمية المخزون الحقيقية للعميل إلا إذا كانت سياسة Finora تسمح بذلك.

استخدم حالة مثل:

```text
متوفر
كمية محدودة
نفد من المخزون
```

---

# ربط الفيديو بالمنتجات

الفيديو الواحد يستطيع الارتباط:

* بمنتج واحد.
* بعدة منتجات.
* بفئة منتجات.
* بحملة.
* بكوبون.
* بخصم.

أنشئ جدول ربط مثل:

```text
MobileVideoProduct
```

ويحتوي على:

```text
id
tenant_id
video_id
product_id
display_order
custom_title
custom_cta
special_price
discount_id
created_at
```

إذا كان `special_price` موجوداً، يجب التحقق من صلاحيات الإدارة ومن تاريخ صلاحيته.

لا تسمح للتطبيق باعتماد سعر غير صالح أو قديم.

---

# العربة

العربة يجب أن تدعم:

* المستخدم المسجل.
* العربة المحلية للضيف.
* دمج عربة الضيف بعد تسجيل الدخول.
* إضافة المنتج.
* تعديل الكمية.
* حذف المنتج.
* تطبيق كوبون.
* تطبيق نقاط.
* حساب التوصيل.
* حساب الخصومات.
* التحقق من المخزون.
* التحقق من الأسعار قبل إنشاء الطلب.

الجداول:

```text
MobileCart
MobileCartItem
```

عند فتح العربة أو تأكيد الطلب:

* أعد التحقق من السعر.
* أعد التحقق من المخزون.
* أعد حساب الخصومات في الخادم.
* لا تثق بالمجموع القادم من تطبيق الهاتف.

---

# Checkout وإنشاء الطلب

صفحة إنهاء الطلب تحتوي على:

* الاسم.
* رقم الهاتف.
* المحافظة.
* المدينة أو المنطقة.
* العنوان.
* أقرب نقطة دالة.
* ملاحظات.
* طريقة الدفع.
* طريقة التوصيل.
* المنتجات.
* الخصومات.
* الكوبونات.
* النقاط.
* المجموع النهائي.

عند تأكيد الطلب:

```text
Mobile App
→ Validate Cart
→ Validate Customer
→ Validate Stock
→ Validate Prices
→ Validate Discounts
→ Create Finora Order
→ Reserve or Deduct Stock according to current Finora policy
→ Record Source
→ Record Video Attribution
→ Send Notification
```

الطلب يجب أن يظهر مباشرة داخل صفحة الطلبات الحالية في Finora.

أضف حقول مصدر الطلب مثل:

```text
source = mobile_app
source_video_id
source_campaign_id
source_coupon_id
device_id
```

لا تنشئ نظام طلبات منفصلاً عن Finora.

---

# النقاط والمكافآت

أنشئ نظام Rewards حقيقياً يعتمد على Ledger.

لا تعتمد فقط على حقل:

```text
points_balance
```

أنشئ:

```text
RewardAccount
RewardTransaction
RewardRule
RewardTier
RewardRedemption
```

كل حركة نقاط تحتوي على:

```text
id
tenant_id
user_id
type
points
direction
reference_type
reference_id
description
expires_at
created_at
created_by
```

أنواع الحركة:

```text
purchase_reward
welcome_bonus
campaign_bonus
referral_bonus
manual_adjustment
redemption
refund_reversal
expiration
```

يجب أن تدعم:

* كسب نقاط عند الشراء.
* نقاط إضافية لأول طلب.
* نقاط على منتجات محددة.
* نقاط على حملات محددة.
* نقاط مضاعفة.
* استبدال النقاط بخصم.
* إلغاء نقاط الطلب المرتجع.
* انتهاء صلاحية النقاط.
* مستويات Silver وGold وVIP.
* سجل كامل للحركات.

لا تضف النقاط نهائياً قبل أن يصل الطلب إلى الحالة المحددة داخل إعدادات Finora، مثل مكتمل أو مسدد.

---

# الخصومات والكوبونات

ادعم:

* نسبة خصم.
* مبلغ ثابت.
* خصم فئة.
* خصم منتج.
* خصم فيديو.
* خصم مستخدم.
* خصم مستوى عضوية.
* Flash Sale.
* كوبون.
* خصم لأول طلب.
* خصم حد أدنى للسلة.
* شحن مجاني.
* خصم حسب المحافظة.
* خصم حسب الحملة.

الجداول:

```text
MobileDiscount
MobileCoupon
MobileCouponRedemption
MobileCampaign
```

تحقق من:

* تاريخ البداية.
* تاريخ النهاية.
* عدد مرات الاستخدام.
* عدد مرات الاستخدام لكل مستخدم.
* الحد الأدنى للسلة.
* المنتجات المشمولة.
* المنتجات المستثناة.
* صلاحية Tenant.
* حالة الخصم.
* تداخل الخصومات.

أنشئ Discount Engine في Backend.

لا تحسب الخصم النهائي داخل Flutter فقط.

---

# Finora AI

أنشئ قسم باسم:

```text
Finora AI
```

الذكاء الاصطناعي داخل التطبيق يجب أن يستطيع، وفق صلاحيات آمنة:

* البحث عن المنتجات.
* مقارنة المنتجات.
* اقتراح منتج حسب الميزانية.
* اقتراح منتج حسب حاجة العميل.
* عرض السعر الحالي.
* عرض الخصومات المتاحة.
* عرض توفر المنتج.
* عرض نقاط العميل.
* عرض كوبونات العميل.
* عرض حالة الطلب.
* إضافة منتج للعربة بعد تأكيد المستخدم.
* فتح صفحة المنتج.
* فتح العربة.
* مساعدة المستخدم في اختيار المنتج.

مثال:

```text
المستخدم:
أريد شاشة حجم كبير وميزانيتي 700 ألف.

Finora AI:
حسب ميزانيتك توجد شاشة 70 إنش بسعر 650 ألف، وشاشة 65 إنش ضد الكسر بسعر 590 ألف.
```

لا تسمح للذكاء باختراع منتجات أو أسعار.

يجب أن يعتمد على Tools أو Functions داخلية، مثل:

```text
search_products
get_product_details
get_current_price
get_stock_status
get_user_rewards
get_active_coupons
get_order_status
add_item_to_cart
```

كل عملية تعديل أو إضافة للعربة يجب أن تمر بتأكيد المستخدم.

أنشئ:

```text
AIConversation
AIMessage
AIToolExecution
```

مع مراعاة الخصوصية وعدم إرسال معلومات محاسبية أو إدارية غير مصرح بها إلى مستخدم الهاتف.

---

# الحساب الشخصي

صفحة الحساب تحتوي على:

* الصورة.
* الاسم.
* رقم الهاتف.
* مستوى العضوية.
* رصيد النقاط.
* الطلبات.
* الطلبات الحالية.
* الطلبات السابقة.
* المنتجات المحفوظة.
* الفيديوهات المعجب بها.
* العناوين.
* الكوبونات.
* الجوائز.
* الإشعارات.
* الخصوصية.
* تسجيل الخروج.
* حذف الحساب وفق سياسة النظام.

---

# الإشعارات

ادعم Push Notifications.

أنشئ:

```text
MobileNotification
MobileNotificationDelivery
MobileNotificationPreference
```

أنواع الإشعارات:

* طلب جديد.
* تحديث حالة الطلب.
* خروج الطلب للتوصيل.
* اكتمال الطلب.
* خصم جديد.
* كوبون جديد.
* نقاط مكتسبة.
* نقاط قاربت على الانتهاء.
* فيديو جديد.
* رد على تعليق.
* إعجاب بالرد مستقبلاً.
* حملة مخصصة.

المدير يستطيع إرسال إشعار إلى:

* جميع المستخدمين.
* مستخدم معين.
* محافظة معينة.
* مستخدمين جدد.
* مستخدمين غير نشطين.
* Gold.
* VIP.
* من شاهدوا منتجاً.
* من تركوا منتجات داخل العربة.
* من اشتروا فئة محددة.

لا ترسل الإشعارات الثقيلة داخل HTTP Request.

استخدم Background Jobs.

---

# لوحة التحكم داخل Finora

أنشئ قسم جديد داخل القائمة الجانبية باسم:

```text
تطبيق الهاتف
```

ويحتوي على:

```text
لوحة التطبيق
الفيديوهات
رفع فيديو
إدارة الـFeed
التعليقات
المستخدمون
المنتجات داخل التطبيق
الطلبات
المكافآت
قواعد النقاط
الخصومات
الكوبونات
الحملات
الإشعارات
الذكاء الاصطناعي
تصميم التطبيق
الإعدادات
Feature Flags
التحليلات
سجل العمليات
```

## لوحة التطبيق

تعرض:

* المستخدمين الكليين.
* المستخدمين النشطين اليوم.
* المستخدمين النشطين شهرياً.
* وقت المشاهدة.
* عدد مشاهدات الفيديو.
* عدد الإعجابات.
* عدد التعليقات.
* عدد المشاركات.
* عدد المنتجات المفتوحة.
* عدد الإضافات للعربة.
* عدد الطلبات.
* الإيرادات من التطبيق.
* متوسط قيمة الطلب.
* أفضل فيديو.
* أفضل منتج.
* أفضل حملة.
* معدل التحويل.
* معدل إكمال الفيديو.
* معدل الاحتفاظ.

---

# تحليلات الفيديو والمبيعات

يجب تسجيل أحداث مثل:

```text
video_impression
video_started
video_25_percent
video_50_percent
video_75_percent
video_completed
video_replayed
video_liked
video_unliked
comment_opened
comment_created
video_shared
product_opened
add_to_cart
remove_from_cart
checkout_started
order_created
purchase_completed
```

أنشئ Event Tracking منظماً.

لا ترسل Event لكل Millisecond.

استخدم تجميعاً مناسباً وBatching من تطبيق الهاتف عند الحاجة.

يجب أن يستطيع المدير رؤية:

```text
Video Views
Unique Viewers
Average Watch Time
Completion Rate
Likes
Comments
Shares
Product Clicks
Add To Cart
Orders
Revenue
Conversion Rate
```

يجب ربط الطلب بالمصدر التسويقي:

```text
Video Attribution
Campaign Attribution
Coupon Attribution
```

---

# إدارة ترتيب الـFeed

أضف أوضاعاً لترتيب الفيديوهات:

```text
manual
newest
most_viewed
most_engaged
campaign_priority
personalized
hybrid
```

في المرحلة الأولى استخدم:

```text
hybrid
```

ويعتمد على:

* أولوية الإدارة.
* تاريخ النشر.
* تفاعل المستخدم.
* مشاهدة المستخدم السابقة.
* المنتجات التي فتحها.
* الفيديوهات التي أكملها.
* تنويع المحتوى.
* منع تكرار الفيديو بسرعة.

أنشئ Feed Service منفصلة.

استخدم Cursor Pagination وليس Page Number للفيديوهات.

مثال:

```http
GET /api/mobile/v1/feed?cursor=...&limit=6
```

---

# النشر من المستخدمين مستقبلاً

حالياً لا تسمح للمستخدم العادي برفع الفيديوهات.

أنشئ Feature Flag:

```text
user_generated_content_enabled = false
```

لكن صمم البنية من الآن لتدعم مستقبلاً:

* Creator Profile.
* رفع فيديو.
* المسودات.
* مراجعة الفيديو.
* قبول أو رفض.
* الإبلاغ.
* حقوق النشر.
* تحقيق الأرباح مستقبلاً.
* مكافآت المنشئين.
* حظر المنشئ.

صلاحيات المرحلة الحالية:

```text
Admin: Can Upload
Authorized Employee: Can Upload According To Permission
Normal User: Cannot Upload
```

لا تعرض زر النشر للمستخدم العادي حالياً.

---

# Feature Flags

أنشئ نظام Feature Flags داخل Finora.

أمثلة:

```text
mobile_app_enabled
video_feed_enabled
comments_enabled
video_sharing_enabled
rewards_enabled
coupons_enabled
ai_assistant_enabled
guest_checkout_enabled
user_generated_content_enabled
referrals_enabled
push_notifications_enabled
personalized_feed_enabled
```

يجب أن تكون الإعدادات مرتبطة بالـTenant.

---

# الصلاحيات

أضف صلاحيات واضحة داخل Finora مثل:

```text
mobile_app.view_dashboard
mobile_app.manage_videos
mobile_app.publish_videos
mobile_app.delete_videos
mobile_app.manage_comments
mobile_app.reply_comments
mobile_app.manage_users
mobile_app.block_users
mobile_app.manage_rewards
mobile_app.adjust_points
mobile_app.manage_discounts
mobile_app.manage_coupons
mobile_app.send_notifications
mobile_app.manage_ai
mobile_app.manage_design
mobile_app.view_analytics
mobile_app.manage_settings
```

لا تعتمد على إخفاء الزر فقط.

تحقق من الصلاحية داخل Backend.

---

# الأمن

طبق:

* Rate Limiting.
* Request Validation.
* JWT Rotation أو Session Strategy آمنة.
* Refresh Token Revocation.
* Secure Storage في Flutter.
* HTTPS only.
* حماية من IDOR.
* Tenant Isolation.
* منع الوصول إلى بيانات شركة أخرى.
* منع Mass Assignment.
* File Type Validation.
* File Size Validation.
* Video Malware Scanning إن كان متاحاً.
* Sanitization للتعليقات.
* منع XSS.
* منع SQL Injection.
* Audit Logs.
* Device Tracking.
* Brute Force Protection للـOTP.
* Expiring OTP.
* Limit OTP Requests.
* Signed URLs للملفات الخاصة.
* عدم وضع أسرار داخل تطبيق Flutter.
* عدم وضع API Keys الحساسة داخل التطبيق.
* عدم الوثوق بأي سعر أو خصم أو مجموع قادم من الهاتف.

كل Endpoint يجب أن يتحقق من:

```text
Authentication
Authorization
Tenant
Ownership
Validation
Rate Limit
```

---

# الـAPI المطلوبة

## Authentication

```http
POST /api/mobile/v1/auth/request-otp
POST /api/mobile/v1/auth/verify-otp
POST /api/mobile/v1/auth/refresh
POST /api/mobile/v1/auth/logout
POST /api/mobile/v1/auth/logout-all
GET  /api/mobile/v1/auth/me
```

## Feed

```http
GET  /api/mobile/v1/feed
GET  /api/mobile/v1/videos/{id}
POST /api/mobile/v1/videos/{id}/view
POST /api/mobile/v1/videos/{id}/progress
POST /api/mobile/v1/videos/{id}/like
DELETE /api/mobile/v1/videos/{id}/like
POST /api/mobile/v1/videos/{id}/save
DELETE /api/mobile/v1/videos/{id}/save
POST /api/mobile/v1/videos/{id}/share
```

## Comments

```http
GET    /api/mobile/v1/videos/{id}/comments
POST   /api/mobile/v1/videos/{id}/comments
POST   /api/mobile/v1/comments/{id}/replies
POST   /api/mobile/v1/comments/{id}/like
DELETE /api/mobile/v1/comments/{id}/like
DELETE /api/mobile/v1/comments/{id}
POST   /api/mobile/v1/comments/{id}/report
```

## Products

```http
GET /api/mobile/v1/categories
GET /api/mobile/v1/products
GET /api/mobile/v1/products/{id}
GET /api/mobile/v1/products/{id}/videos
GET /api/mobile/v1/offers
GET /api/mobile/v1/search
```

## Cart

```http
GET    /api/mobile/v1/cart
POST   /api/mobile/v1/cart/items
PATCH  /api/mobile/v1/cart/items/{id}
DELETE /api/mobile/v1/cart/items/{id}
POST   /api/mobile/v1/cart/apply-coupon
DELETE /api/mobile/v1/cart/coupon
POST   /api/mobile/v1/cart/apply-points
DELETE /api/mobile/v1/cart/points
POST   /api/mobile/v1/cart/validate
```

## Checkout and Orders

```http
POST /api/mobile/v1/checkout/preview
POST /api/mobile/v1/orders
GET  /api/mobile/v1/orders
GET  /api/mobile/v1/orders/{id}
POST /api/mobile/v1/orders/{id}/cancel
```

## Rewards

```http
GET  /api/mobile/v1/rewards
GET  /api/mobile/v1/rewards/history
GET  /api/mobile/v1/rewards/rules
GET  /api/mobile/v1/rewards/available-redemptions
POST /api/mobile/v1/rewards/redeem
```

## Coupons and Discounts

```http
GET  /api/mobile/v1/coupons
GET  /api/mobile/v1/discounts
POST /api/mobile/v1/coupons/validate
```

## Profile

```http
GET    /api/mobile/v1/profile
PATCH  /api/mobile/v1/profile
GET    /api/mobile/v1/profile/addresses
POST   /api/mobile/v1/profile/addresses
PATCH  /api/mobile/v1/profile/addresses/{id}
DELETE /api/mobile/v1/profile/addresses/{id}
GET    /api/mobile/v1/profile/favorites
GET    /api/mobile/v1/profile/liked-videos
```

## AI

```http
POST /api/mobile/v1/ai/conversations
GET  /api/mobile/v1/ai/conversations
GET  /api/mobile/v1/ai/conversations/{id}
POST /api/mobile/v1/ai/conversations/{id}/messages
```

## Notifications

```http
GET   /api/mobile/v1/notifications
PATCH /api/mobile/v1/notifications/{id}/read
POST  /api/mobile/v1/devices/register
DELETE /api/mobile/v1/devices/{id}
```

---

# معايير استجابة الـAPI

استخدم شكلاً ثابتاً:

```json
{
  "success": true,
  "data": {},
  "meta": {},
  "error": null
}
```

وفي الخطأ:

```json
{
  "success": false,
  "data": null,
  "meta": {},
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "البيانات المدخلة غير صحيحة",
    "fields": {}
  }
}
```

لا ترسل Stack Trace للمستخدم.

استخدم HTTP Status Codes الصحيحة.

---

# حالات التطبيق

كل شاشة يجب أن تدعم:

* Loading.
* Empty State.
* Error State.
* Offline State.
* Retry.
* Partial Data.
* Unauthorized.
* Maintenance Mode.
* Feature Disabled.

لا تعرض شاشة بيضاء عند الخطأ.

---

# Offline وCaching

التطبيق لا يحتاج أن يعمل كاملاً Offline، لكن يجب أن يوفر تجربة جيدة.

خزن محلياً بشكل آمن:

* إعدادات المستخدم.
* Access data غير الحساسة.
* آخر Feed metadata.
* الصور المصغرة.
* العربة المحلية.
* الطلبات الأخيرة.
* المنتجات المحفوظة.
* تفضيلات الإشعارات.

لا تخزن بيانات حساسة بدون تشفير.

عند عودة الاتصال:

* مزامنة العربة.
* إعادة إرسال Analytics المعلقة.
* تحديث الأسعار.
* تحديث المخزون.
* تحديث حالة الطلبات.

---

# الأداء

الأهداف:

```text
App launch سريع.
Feed first frame سريع.
انتقال الفيديو بدون تقطيع واضح.
Scrolling ثابت.
تقليل استهلاك الذاكرة.
تقليل استهلاك البطارية.
تقليل استهلاك الإنترنت.
```

استخدم:

* Pagination.
* Cursor Pagination.
* Lazy Loading.
* Image Caching.
* Video Preloading محدود.
* Request Deduplication.
* API Response Caching.
* Redis Cache.
* Database Indexes.
* Select only required columns.
* Avoid N+1 Queries.
* Background Aggregation.
* Debounced Search.
* Optimistic UI للإعجاب والحفظ.
* Batched Analytics Events.

أضف Indexes مناسبة على:

```text
tenant_id
user_id
video_id
product_id
status
published_at
created_at
parent_comment_id
campaign_id
order_id
```

قم بقياس الأداء ولا تعتمد على التخمين.

---

# البحث

أنشئ بحثاً موحداً داخل التطبيق يدعم:

* المنتجات.
* التصنيفات.
* الفيديوهات.
* العروض.
* الكلمات المفتاحية.

في البداية استخدم بحث قاعدة البيانات الحالي بشكل محسّن.

صمم Search Service بحيث يمكن استبدالها مستقبلاً بمحرك بحث متقدم.

---

# روابط المشاركة وDeep Linking

عند مشاركة فيديو استخدم رابطاً مثل:

```text
https://app.finora.company/v/{video_id}
```

إذا كان التطبيق مثبتاً:

```text
افتح الفيديو داخل التطبيق.
```

إذا لم يكن مثبتاً:

```text
افتح Landing Page تحتوي على الفيديو والمنتج وزر تحميل التطبيق.
```

ادعم Deep Links للآتي:

```text
/video/{id}
/product/{id}
/order/{id}
/coupon/{code}
/campaign/{id}
```

---

# إعدادات تصميم التطبيق من Finora

أضف صفحة تسمح بتعديل:

* اسم التطبيق المعروض.
* الشعار.
* اللون الرئيسي.
* اللون الثانوي.
* لون الجوائز.
* صورة Splash.
* Banner المتجر.
* أقسام المتجر.
* ترتيب Bottom Navigation.
* إظهار أو إخفاء الأقسام.
* نصوص الترحيب.
* روابط الدعم.
* سياسة الخصوصية.
* شروط الاستخدام.
* روابط التواصل.
* أرقام واتساب.
* حالة الصيانة.
* أقل إصدار مدعوم.
* Force Update.
* Optional Update.

لا تسمح بإعدادات تكسر قابلية القراءة أو الـContrast.

---

# Multi-Tenant

كل البيانات يجب أن تكون معزولة بين الشركات.

كل جدول جديد يجب أن يحتوي على:

```text
tenant_id
```

حيث يكون ذلك مناسباً.

كل استعلام يجب أن يمر عبر Tenant Scope.

لا تسمح لمستخدم شركة برؤية:

* فيديوهات شركة أخرى.
* منتجات شركة أخرى.
* تعليقات شركة أخرى.
* مستخدمي شركة أخرى.
* حملات شركة أخرى.
* تحليلات شركة أخرى.

إعدادات التطبيق تكون لكل Tenant.

صمم النظام بحيث يمكن مستقبلاً لكل شركة امتلاك تطبيق أو هوية خاصة بها.

---

# السجلات والتدقيق

أنشئ Audit Log لكل عملية إدارية حساسة:

* نشر فيديو.
* حذف فيديو.
* تغيير سعر خاص.
* إنشاء خصم.
* تعديل نقاط.
* إرسال إشعار.
* حظر مستخدم.
* حذف تعليق.
* تغيير إعدادات AI.
* تفعيل Feature Flag.

يحتوي السجل على:

```text
tenant_id
actor_id
action
entity_type
entity_id
old_values
new_values
ip_address
user_agent
created_at
```

---

# الاختبارات

أنشئ اختبارات Backend:

* Unit Tests.
* Service Tests.
* API Tests.
* Permission Tests.
* Tenant Isolation Tests.
* Discount Tests.
* Reward Ledger Tests.
* Cart Tests.
* Checkout Tests.
* Comment Tests.
* Video Permission Tests.
* AI Tool Permission Tests.

أنشئ اختبارات Flutter:

* Widget Tests.
* State Tests.
* Repository Tests.
* API Parsing Tests.
* Navigation Tests.
* Integration Tests للرحلة الأساسية.

الرحلة الأساسية المطلوبة للاختبار:

```text
Register
→ Open Feed
→ Watch Video
→ Like
→ Open Comments
→ Add Comment
→ Open Product
→ Add To Cart
→ Apply Coupon
→ Checkout
→ Create Order
→ View Order
→ Receive Reward Points
```

---

# الترحيلات

استخدم نظام Migration الموجود في المشروع.

لا تعدل قاعدة الإنتاج مباشرة.

أنشئ Migrations واضحة وقابلة للتراجع.

لا تحذف أي عمود قائم بدون خطة Migration آمنة.

---

# التوثيق

أنشئ:

```text
docs/mobile-app/
```

ويحتوي على:

```text
architecture.md
backend-setup.md
flutter-setup.md
api-reference.md
video-processing.md
rewards-engine.md
discount-engine.md
ai-tools.md
security.md
deployment.md
testing.md
feature-flags.md
```

أضف ملف:

```text
.env.example
```

بدون أسرار حقيقية.

---

# Docker والتشغيل

حدّث Docker Compose عند الحاجة ليشمل:

```text
web
postgres
redis
celery-worker
celery-beat
video-worker
```

لكن لا تكرر Services موجودة مسبقاً.

أنشئ Health Checks.

اجعل معالجة الفيديو قابلة للتوسع بعدة Workers.

---

# مراحل التنفيذ

نفذ المشروع على مراحل، لكن ابدأ مباشرة ولا تكتفِ بكتابة خطة.

## المرحلة الأولى

* فحص المشروع.
* توثيق المعمارية الحالية.
* إنشاء Mobile App Module.
* إعداد Models الأساسية.
* إعداد API v1.
* إعداد Flutter project.
* إعداد Theme.
* إعداد Routing.
* إعداد Authentication.
* إعداد API client.
* إعداد Error Handling.

## المرحلة الثانية

* Video Admin.
* رفع الفيديو.
* Celery video processing.
* HLS assets.
* Video Feed.
* Vertical swipe.
* Preloading.
* Likes.
* Views.
* Saves.
* Shares.

## المرحلة الثالثة

* Comments.
* Replies.
* Comment likes.
* Moderation.
* Admin comment management.

## المرحلة الرابعة

* Store.
* Categories.
* Products.
* Product details.
* Video-product linking.
* Favorites.
* Search.

## المرحلة الخامسة

* Cart.
* Checkout.
* Finora order integration.
* Inventory validation.
* Order tracking.
* Attribution.

## المرحلة السادسة

* Rewards.
* Tiers.
* Points Ledger.
* Coupons.
* Discount Engine.
* Campaigns.

## المرحلة السابعة

* Finora AI.
* AI tools.
* Product recommendation.
* Order status.
* Cart actions with confirmation.

## المرحلة الثامنة

* Notifications.
* Analytics.
* Conversion tracking.
* App design settings.
* Feature Flags.
* Performance optimization.
* Security review.
* Full tests.

---

# طريقة العمل المطلوبة منك

لا تقم بإنشاء ملفات وهمية أو TODOs كثيرة بدون تنفيذ.

في كل مرحلة:

1. افحص الكود المرتبط.
2. اذكر الملفات التي ستتغير.
3. نفذ التعديل.
4. أضف Migration إذا لزم.
5. أضف الاختبارات.
6. شغّل الاختبارات.
7. أصلح الأخطاء.
8. افحص التوافق مع النظام القديم.
9. حدث التوثيق.
10. اعرض ملخصاً لما تم.

لا تحذف كوداً قائماً إلا عند الضرورة.

لا تغير Contracts حالية بدون Compatibility Layer.

استخدم أسماء واضحة.

اكتب Type Hints في Python.

اكتب Dart code منظماً.

لا تستخدم `dynamic` إلا للضرورة.

لا تتجاهل Exceptions.

لا تستخدم `print` للتسجيل في الإنتاج.

استخدم Logging منظم.

---

# معايير القبول النهائية

يعتبر المشروع ناجحاً عندما:

* يستطيع المدير رفع فيديو من Finora.
* تتم معالجة الفيديو بالخلفية.
* يظهر الفيديو داخل تطبيق Flutter.
* يستطيع المستخدم التمرير بين الفيديوهات بسلاسة.
* يعمل Preloading بدون استهلاك مفرط للذاكرة.
* يستطيع المستخدم الإعجاب.
* يستطيع التعليق والرد.
* يستطيع مشاركة الفيديو.
* يستطيع فتح المنتج من الفيديو.
* يستطيع إضافة المنتج للعربة.
* يستطيع إنشاء طلب.
* يظهر الطلب داخل Finora.
* يتم التحقق من السعر والمخزون في الخادم.
* يتم تسجيل مصدر الطلب والفيديو.
* تعمل النقاط والجوائز.
* تعمل الخصومات والكوبونات.
* يستطيع Finora AI اقتراح منتجات حقيقية.
* تعمل الإشعارات.
* يستطيع المدير التحكم بكل شيء من Finora.
* يعمل التطبيق على Android وiOS.
* يدعم RTL.
* يعمل على أحجام شاشات مختلفة.
* لا توجد مشاكل Tenant Isolation.
* جميع العمليات الحساسة محمية بالصلاحيات.
* الاختبارات الأساسية ناجحة.
* لا تتأثر صفحات Finora الحالية.

ابدأ الآن بفحص المشروع الحالي، ثم أنشئ تقريراً قصيراً عن المعمارية الموجودة، وبعدها نفذ المرحلة الأولى فعلياً داخل المشروع.

لا تسألني أسئلة عامة يمكن معرفتها من الكود.

عند وجود قرار تقني غير واضح، اختر الحل الأكثر أماناً وقابلية للتوسع والمتوافق مع بنية Finora الحالية، وسجل القرار داخل التوثيق.

لا تكتفِ بشرح ما يجب فعله؛ قم بكتابة وتنفيذ الكود الفعلي.
