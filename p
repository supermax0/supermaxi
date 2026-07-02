أريد تطوير صفحة هبوط احترافية لمنصة Finora Cloud بنظام SaaS، مع لوحة تحكم Super Admin كاملة تسمح بتعديل محتوى الصفحة بدون تعديل الكود.

المطلوب ليس صفحة ثابتة فقط، بل Landing Page ديناميكية قابلة للإدارة من لوحة تحكم. يجب أن يستطيع Super Admin تغيير النصوص، العناوين، الصور، الفيديو، الخطط، الأسعار، الأزرار، الأسئلة الشائعة، الأقسام، ترتيب الأقسام، حالة الظهور والإخفاء، وألوان الصفحة من داخل النظام.

========================
الهدف العام
========================

بناء صفحة هبوط احترافية لفينورا تعرض المنصة بطريقة تسويقية قوية ومناسبة لشركات التجارة الإلكترونية، المتاجر، شركات التوصيل، والمحاسبين.

الصفحة يجب أن تكون:
- احترافية جداً.
- سريعة.
- متجاوبة مع الهاتف والتابلت والديسكتوب.
- عربية RTL بالكامل.
- مناسبة للسوق العراقي والعربي.
- بنَفَس Presentation Landing Page، أي أن الزائر يشعر كأنه يشاهد عرضاً تفاعلياً مرتباً.
- تحتوي أنميشن خفيف وحركات ناعمة بدون مبالغة.
- قابلة للتعديل من لوحة Super Admin.
- تدعم SEO.
- تدعم إدارة المحتوى بدون الحاجة لمبرمج.

========================
المفهوم التسويقي
========================

Finora Cloud هو نظام إدارة ومحاسبة ذكي للشركات والمتاجر يساعدهم على إدارة:

- المبيعات.
- POS.
- الطلبات.
- المخزون.
- العملاء.
- الموردين.
- شركات التوصيل.
- التسويات.
- المصاريف.
- الأرباح والخسائر.
- صلاحيات الموظفين.
- التقارير.
- المساعد الذكي LEON.

الرسالة الأساسية للصفحة:

"فينورا يجمع كل عمليات شركتك من الطلب إلى التسوية والربح الحقيقي في مكان واحد، مع مساعد ذكي يساعدك تكتشف الأخطاء وتسيطر على شغلك."

========================
المطلوب التقني
========================

أريد تنفيذ النظام بطريقة نظيفة وقابلة للتوسعة.

إذا كان المشروع Flask:
- استخدم Flask Blueprints.
- استخدم SQLAlchemy models.
- استخدم Jinja templates أو frontend منفصل حسب هيكل المشروع الحالي.
- أضف routes للصفحة العامة.
- أضف routes خاصة بلوحة Super Admin.
- أضف APIs لإدارة محتوى الصفحة.
- أضف صلاحيات بحيث لا يدخل لوحة إدارة المحتوى إلا Super Admin فقط.

إذا كان المشروع React / Next:
- أنشئ Landing Page ديناميكية.
- أنشئ Admin Content Manager.
- استخدم API واضح.
- استخدم Components قابلة لإعادة الاستخدام.
- اجعل المحتوى يأتي من قاعدة البيانات وليس hardcoded.

المهم: لا تجعل نصوص الصفحة ثابتة داخل الكود. كل النصوص والصور والفيديو والخطط والأسعار والأسئلة يجب أن تكون قابلة للتعديل من قاعدة البيانات ولوحة التحكم.

========================
الصلاحيات
========================

يجب أن يكون الوصول لإدارة صفحة الهبوط مخصصاً فقط إلى:

role = super_admin

لا يحق لأي tenant admin أو user عادي تعديل محتوى الصفحة العامة.

أضف حماية كاملة للـ routes والـ APIs.

مثال:
- /super-admin/landing
- /super-admin/landing/sections
- /super-admin/landing/media
- /super-admin/landing/pricing
- /super-admin/landing/faq
- /super-admin/landing/seo
- /super-admin/landing/theme

========================
نظام إدارة المحتوى CMS
========================

أريد بناء Mini CMS خاص بصفحة الهبوط داخل لوحة Super Admin.

يجب أن يحتوي على الأقسام التالية:

1. إدارة معلومات الصفحة العامة
2. إدارة أقسام الصفحة
3. إدارة Hero Section
4. إدارة المشاكل Pain Points
5. إدارة الحلول Solution
6. إدارة المميزات Features
7. إدارة سير العمل Workflow
8. إدارة الموديلات Modules
9. إدارة قسم LEON AI
10. إدارة الفيديو التعليمي
11. إدارة الصور والسكرينشوتات
12. إدارة الخطط والأسعار
13. إدارة الأسئلة الشائعة FAQ
14. إدارة آراء العملاء Testimonials
15. إدارة الأزرار CTA
16. إدارة SEO
17. إدارة الثيم والألوان
18. إدارة السوشيال والروابط
19. معاينة الصفحة قبل النشر
20. نظام Draft / Published

========================
قاعدة البيانات المقترحة
========================

أنشئ الجداول أو الموديلات التالية حسب بنية المشروع:

1. LandingPageSettings

الغرض:
إعدادات عامة للصفحة.

الحقول:
- id
- site_name
- page_title
- page_subtitle
- default_language
- logo_url
- favicon_url
- primary_color
- secondary_color
- accent_color
- background_color
- text_color
- font_family
- whatsapp_number
- contact_email
- login_url
- trial_url
- demo_booking_url
- is_active
- created_at
- updated_at

2. LandingSection

الغرض:
إدارة أقسام الصفحة وترتيبها.

الحقول:
- id
- section_key
- section_type
- title
- subtitle
- description
- content_json
- image_url
- video_url
- button_primary_text
- button_primary_url
- button_secondary_text
- button_secondary_url
- sort_order
- is_visible
- animation_type
- background_style
- created_at
- updated_at

section_type أمثلة:
- hero
- pain_points
- solution
- workflow
- features
- modules
- ai_assistant
- demo_video
- pricing
- testimonials
- faq
- final_cta

3. LandingMedia

الغرض:
مكتبة صور وفيديوهات الصفحة.

الحقول:
- id
- title
- media_type
- file_url
- thumbnail_url
- alt_text
- caption
- usage_key
- file_size
- mime_type
- is_active
- created_at
- updated_at

media_type:
- image
- video
- icon
- logo
- screenshot

4. LandingFeature

الغرض:
إدارة مميزات فينورا.

الحقول:
- id
- title
- description
- icon
- image_url
- feature_key
- sort_order
- is_visible
- created_at
- updated_at

أمثلة Features:
- إدارة المبيعات.
- POS سريع.
- متابعة الطلبات.
- إدارة المخزون.
- حساب الأرباح.
- تسويات شركات التوصيل.
- صلاحيات الموظفين.
- تقارير ذكية.
- LEON AI.

5. LandingModule

الغرض:
إدارة موديلات النظام المعروضة بالصفحة.

الحقول:
- id
- name
- short_description
- long_description
- icon
- screenshot_url
- sort_order
- is_visible
- created_at
- updated_at

الموديلات:
- POS
- Orders
- Inventory
- Customers
- Suppliers
- Accounting
- Courier Settlement
- Reports
- Employees
- Settings
- LEON AI

6. LandingPricingPlan

الغرض:
إدارة الخطط والأسعار من لوحة التحكم.

الحقول:
- id
- name
- slug
- price
- currency
- billing_period
- description
- features_json
- limits_json
- cta_text
- cta_url
- badge_text
- is_popular
- is_visible
- sort_order
- created_at
- updated_at

الخطط الافتراضية:

Starter:
- السعر: 20$
- مناسب للمتاجر الصغيرة.
- يحتوي أساسيات فينورا.
- بدون LEON كامل.

Business:
- السعر: 49$
- مناسب للشركات النامية.
- يحتوي كامل مميزات فينورا.
- LEON بنصف الإمكانيات.

Pro AI:
- السعر: 99$
- مناسب للشركات التي تريد ذكاء وتحليل كامل.
- Finora كامل.
- LEON كامل.

يجب أن يستطيع Super Admin:
- إضافة خطة.
- تعديل خطة.
- حذف أو إخفاء خطة.
- تغيير السعر.
- تغيير العملة.
- تغيير المميزات.
- تحديد الخطة الأكثر شيوعاً.
- تغيير زر الاشتراك.
- ترتيب الخطط بالسحب والإفلات إن أمكن.

7. LandingFAQ

الغرض:
إدارة الأسئلة الشائعة.

الحقول:
- id
- question
- answer
- category
- sort_order
- is_visible
- created_at
- updated_at

أسئلة افتراضية:
- هل فينورا يدعم شركات التوصيل؟
- هل أستطيع استخدامه من الهاتف؟
- هل يحسب الربح الصافي؟
- هل يدعم أكثر من موظف؟
- هل يوجد صلاحيات؟
- هل توجد تجربة مجانية؟
- هل أحتاج محاسب؟
- هل البيانات آمنة؟
- هل يدعم المخزون؟
- هل يمكن ربطه بالذكاء الاصطناعي LEON؟

8. LandingTestimonial

الغرض:
إدارة آراء العملاء.

الحقول:
- id
- customer_name
- customer_title
- company_name
- quote
- avatar_url
- rating
- is_visible
- sort_order
- created_at
- updated_at

9. LandingCTA

الغرض:
إدارة أزرار الدعوة للإجراء.

الحقول:
- id
- label
- url
- cta_type
- placement_key
- is_visible
- sort_order
- created_at
- updated_at

cta_type:
- trial
- whatsapp
- demo
- login
- pricing
- video

10. LandingSEO

الغرض:
إدارة SEO.

الحقول:
- id
- meta_title
- meta_description
- meta_keywords
- og_title
- og_description
- og_image_url
- twitter_title
- twitter_description
- twitter_image_url
- canonical_url
- robots
- schema_json
- created_at
- updated_at

========================
واجهة Super Admin
========================

أريد صفحة إدارة احترافية داخل لوحة Super Admin باسم:

"إدارة صفحة الهبوط"

يجب أن تحتوي على Sidebar أو Tabs داخلية:

1. نظرة عامة
2. الأقسام
3. Hero
4. المميزات
5. الموديلات
6. الفيديو والصور
7. الخطط والأسعار
8. الأسئلة الشائعة
9. آراء العملاء
10. الأزرار والروابط
11. SEO
12. الثيم
13. المعاينة والنشر

========================
متطلبات واجهة الإدارة
========================

كل قسم يجب أن يحتوي على:

- عرض البيانات الحالية.
- زر تعديل.
- زر حفظ.
- زر إلغاء.
- زر إخفاء/إظهار.
- ترتيب العناصر.
- رفع صورة.
- حذف صورة.
- تغيير فيديو.
- حفظ تلقائي اختياري.
- تنبيه عند الحفظ.
- Validation واضح.
- حالة Draft.
- زر Preview.
- زر Publish.

لازم تكون واجهة Super Admin سهلة، لأن صاحب النظام يريد يغير محتوى الصفحة بسرعة بدون دخول للكود.

========================
نظام Draft / Publish
========================

أريد نظام يسمح بالتعديل بدون نشر مباشر.

الآلية:
- أي تعديل يتم حفظه كـ draft.
- Super Admin يستطيع مشاهدة Preview.
- إذا كل شيء صحيح يضغط Publish.
- الصفحة العامة لا تتغير إلا بعد Publish.
- أضف published_at.
- أضف published_by.
- أضف last_edited_by.

إذا صعب تنفيذ draft كامل حالياً، نفذ نسخة أولى بسيطة:
- is_published
- published_version
- draft_version

========================
نظام المعاينة Preview
========================

أضف زر:

"معاينة الصفحة"

يفتح الصفحة كما ستظهر للزائر قبل النشر.

الرابط المقترح:
- /landing/preview

ويجب أن يكون محمياً ولا يظهر إلا للـ Super Admin.

========================
صفحة الهبوط العامة
========================

الرابط:
- /
أو:
- /landing

حسب هيكل المشروع.

الصفحة يجب أن تقرأ المحتوى المنشور من قاعدة البيانات.

لا تستخدم نصوص hardcoded إلا كـ fallback إذا لم توجد بيانات.

========================
أقسام صفحة الهبوط بالتفصيل
========================

1. Header

يحتوي:
- شعار Finora.
- روابط تنقل:
  - المميزات.
  - طريقة العمل.
  - الأسعار.
  - الأسئلة الشائعة.
  - تواصل.
- زر تسجيل الدخول.
- زر جرّب مجاناً.

يجب أن يكون Sticky Header خفيف.
في الموبايل يتحول إلى Menu.

كل الروابط والنصوص قابلة للتعديل من Super Admin.

2. Hero Section

يحتوي:
- عنوان رئيسي قوي.
- وصف مختصر.
- زر CTA أول.
- زر CTA ثاني.
- زر مشاهدة الفيديو.
- صورة أو فيديو للداشبورد.
- شارة صغيرة مثل:
  "مصمم للشركات والمتاجر العراقية"

نص افتراضي:
العنوان:
"فينورا — نظام إدارة ومحاسبة ذكي لشركتك"

الوصف:
"تابع المبيعات، الطلبات، المخزون، شركات التوصيل، المصاريف، الأرباح، والتسويات من مكان واحد، مع مساعد ذكي يساعدك تكتشف الأخطاء قبل ما تتحول إلى خسائر."

الأزرار:
- جرّب مجاناً.
- احجز عرض مباشر.
- شاهد الفيديو.

3. Pain Points Section

يعرض مشاكل الزبون قبل استخدام فينورا.

بطاقات:
- طلبات غير محسوبة.
- تسويات توصيل معقدة.
- مخزون غير مضبوط.
- أرباح غير واضحة.
- مصاريف غير مرتبطة.
- موظفين بدون متابعة دقيقة.

كل بطاقة قابلة للتعديل.

4. Solution Section

يوضح أن فينورا يجمع العمليات بمكان واحد.

نص افتراضي:
"فينورا يحوّل شغل شركتك اليومي إلى أرقام واضحة، قرارات أسرع، وتقارير تفهم منها الربح الحقيقي."

5. Workflow Section

يعرض دورة العمل:

طلب → تجهيز → شحن → تسليم → تسوية → ربح صافي

يجب أن يكون القسم بصري وتفاعلي مع أنميشن خفيف.

كل خطوة قابلة للتعديل من Super Admin.

6. Features Section

يعرض مميزات فينورا كبطاقات.

أمثلة:
- POS سريع.
- إدارة الطلبات.
- إدارة المخزون.
- إدارة العملاء.
- الموردين والمشتريات.
- المصاريف.
- الحسابات.
- تقارير الأرباح.
- تسويات شركات التوصيل.
- صلاحيات الموظفين.
- تنبيهات ذكية.
- مساعد LEON.

7. Modules Section

يعرض نوافذ أو موديلات النظام.

كل Module يحتوي:
- اسم.
- وصف.
- أيقونة.
- صورة.
- زر تفاصيل اختياري.

8. LEON AI Section

قسم خاص بالمساعد الذكي.

نص افتراضي:
"LEON هو مساعدك الذكي داخل فينورا. يراجع الأرقام، يكتشف الأخطاء، يحلل التسويات، ينبهك للطلبات المتأخرة، ويجاوبك على أسئلة مثل: شكد ربحنا هذا الشهر؟ شنو الطلبات غير المسددة؟ وين الخلل بالمخزون؟"

يجب عرض أمثلة رسائل مثل:
- "عندك 3 طلبات تم تسليمها ولم تدخل بالتسوية."
- "المصاريف زادت 18% مقارنة بالأسبوع السابق."
- "هذا المنتج عليه مبيعات عالية لكن المخزون قرب يخلص."
- "كشف شركة التوصيل يحتوي فرق 25,000 دينار."

9. Demo Video Section

يعرض فيديو تعليمي قصير.

يجب أن يستطيع Super Admin:
- تغيير رابط الفيديو.
- رفع فيديو أو وضع YouTube/Vimeo/MP4 URL.
- تغيير صورة الغلاف Thumbnail.
- تغيير عنوان الفيديو.
- تغيير وصف الفيديو.
- تفعيل/إخفاء القسم.

الفيديو يفتح داخل Modal وليس تشغيل إجباري.

10. Pricing Section

يعرض الخطط من قاعدة البيانات.

الخطط قابلة للتعديل بالكامل.

يجب أن يظهر:
- اسم الخطة.
- السعر.
- العملة.
- الفترة.
- وصف.
- المميزات.
- الزر.
- شارة Popular إذا موجودة.

11. Testimonials Section

آراء العملاء.

قابل للإخفاء إذا لا توجد آراء بعد.

12. FAQ Section

أسئلة شائعة بنظام Accordion.

13. Final CTA Section

آخر الصفحة.

نص افتراضي:
"ابدأ بتنظيم شركتك اليوم"
"جرّب فينورا مجاناً أو احجز عرض مباشر وشوف شلون النظام يسيطر على عملياتك."

أزرار:
- جرّب مجاناً.
- تواصل واتساب.

14. Footer

يحتوي:
- شعار.
- وصف مختصر.
- روابط مهمة.
- روابط السوشيال.
- البريد.
- واتساب.
- الحقوق.

كلها قابلة للتعديل.

========================
التصميم المطلوب
========================

اعتمد تصميم SaaS حديث:

- خلفية بيضاء أو رمادي فاتح جداً.
- بطاقات ناعمة.
- زوايا مدورة.
- ظل خفيف.
- تدرجات بسيطة.
- أزرق / بنفسجي / تركوازي كلون أساسي.
- خط عربي واضح.
- دعم RTL ممتاز.
- مسافات مريحة.
- لا تستخدم زحمة بصرية.
- الصفحة يجب أن تشعر بالثقة والدقة، لأن المنتج محاسبي وإداري.

يفضل استخدام:
- Cards.
- Glass effect خفيف جداً.
- Animated counters.
- Smooth reveal on scroll.
- Workflow line animation.
- Hover effects.
- Sticky CTA on mobile اختياري.

ممنوع:
- أنميشن ثقيل.
- خلفيات فيديو ثقيلة.
- ألوان صارخة.
- صفحة بطيئة.
- نصوص صغيرة جداً.
- تصميم لا يناسب الموبايل.

========================
الأنميشن
========================

أضف أنميشن خفيف:

- Fade up عند ظهور الأقسام.
- Slide بسيط للبطاقات.
- Hover ناعم.
- Counters للأرقام.
- Workflow animation خفيف.
- Modal للفيديو.

استخدم CSS animations أو Framer Motion إذا المشروع React.
إذا Flask/Jinja، استخدم CSS + IntersectionObserver بسيط.

لا تجعل الأنميشن يضر الأداء.

========================
الأداء
========================

يجب مراعاة:

- ضغط الصور.
- دعم WebP.
- Lazy loading للصور.
- Lazy loading للفيديو.
- عدم تحميل الفيديو إلا عند الضغط.
- تقليل JS.
- Cache للمحتوى المنشور.
- تحسين سرعة الموبايل.
- عدم كسر الصفحة إذا صورة ناقصة أو فيديو ناقص.

========================
SEO
========================

أضف:

- Dynamic meta title.
- Dynamic meta description.
- Open Graph tags.
- Twitter cards.
- Canonical URL.
- Schema.org JSON-LD.
- alt text للصور.
- heading structure صحيح:
  - H1 واحد.
  - H2 للأقسام.
  - H3 للبطاقات.

كل إعدادات SEO قابلة للتعديل من Super Admin.

========================
Media Library
========================

أريد مكتبة وسائط بسيطة داخل Super Admin:

- رفع صورة.
- رفع فيديو إذا النظام يدعم.
- إدخال رابط خارجي للفيديو.
- عرض الصور المرفوعة.
- نسخ رابط الصورة.
- اختيار صورة لأي قسم.
- alt text لكل صورة.
- حذف أو تعطيل وسائط غير مستخدمة.
- منع رفع ملفات خطرة.
- تحديد أنواع الملفات المسموحة:
  - jpg
  - jpeg
  - png
  - webp
  - svg بحذر
  - mp4 إن كان مدعوماً

========================
Validation
========================

أضف تحقق للبيانات:

- العنوان لا يكون فارغ.
- السعر رقم.
- روابط الفيديو صحيحة.
- روابط CTA صحيحة.
- sort_order رقم.
- لا يسمح برفع ملفات غير مدعومة.
- لا يسمح للمستخدم غير Super Admin بالوصول.

========================
Fallback Content
========================

إذا قاعدة البيانات فارغة، أضف seeder ينشئ محتوى افتراضي للصفحة.

المحتوى الافتراضي يجب أن يشمل:
- إعدادات الصفحة.
- Hero.
- Pain Points.
- Workflow.
- Features.
- Modules.
- Pricing Plans.
- FAQ.
- CTA.
- Footer.
- SEO.

أضف أمر أو migration أو seed function حسب المشروع.

مثال:
flask seed_landing_page
أو:
python manage.py seed_landing_page
أو:
npm run seed:landing

حسب التقنية المستخدمة.

========================
APIs مقترحة
========================

أنشئ APIs واضحة:

Public:
GET /api/landing/published

Super Admin:
GET /api/super-admin/landing/settings
PUT /api/super-admin/landing/settings

GET /api/super-admin/landing/sections
POST /api/super-admin/landing/sections
PUT /api/super-admin/landing/sections/:id
DELETE /api/super-admin/landing/sections/:id

GET /api/super-admin/landing/features
POST /api/super-admin/landing/features
PUT /api/super-admin/landing/features/:id
DELETE /api/super-admin/landing/features/:id

GET /api/super-admin/landing/modules
POST /api/super-admin/landing/modules
PUT /api/super-admin/landing/modules/:id
DELETE /api/super-admin/landing/modules/:id

GET /api/super-admin/landing/pricing
POST /api/super-admin/landing/pricing
PUT /api/super-admin/landing/pricing/:id
DELETE /api/super-admin/landing/pricing/:id

GET /api/super-admin/landing/faq
POST /api/super-admin/landing/faq
PUT /api/super-admin/landing/faq/:id
DELETE /api/super-admin/landing/faq/:id

GET /api/super-admin/landing/seo
PUT /api/super-admin/landing/seo

POST /api/super-admin/landing/media/upload
GET /api/super-admin/landing/media
DELETE /api/super-admin/landing/media/:id

POST /api/super-admin/landing/publish
GET /api/super-admin/landing/preview

========================
Audit Log
========================

أضف تسجيل للتغييرات المهمة:

- من عدل.
- شنو عدل.
- قبل وبعد.
- وقت التعديل.
- وقت النشر.

مثال:
LandingAuditLog

الحقول:
- id
- admin_id
- action
- entity_type
- entity_id
- old_value_json
- new_value_json
- ip_address
- created_at

الأحداث:
- update_settings
- update_section
- upload_media
- update_pricing
- update_faq
- publish_landing_page

========================
الأمان
========================

- حماية كل routes الخاصة بالإدارة.
- CSRF إذا النظام يستخدم Forms.
- Sanitization للنصوص.
- منع XSS خصوصاً لأن المحتوى يظهر للعامة.
- تحقق من روابط الفيديو.
- تحقق من رفع الملفات.
- لا تسمح برفع ملفات تنفيذية.
- لا تعرض أخطاء تقنية للمستخدم العام.
- سجل أخطاء الإدارة في logs.

========================
التجاوب مع الموبايل
========================

الصفحة يجب أن تكون ممتازة على iPhone و Android.

المطلوب:
- Header يتحول إلى قائمة.
- Hero يكون عمودي.
- البطاقات تصير عمود واحد.
- Pricing cards تصير عمودية.
- الفيديو يفتح بمودال مناسب.
- CTA واضح.
- زر واتساب يظهر بشكل مناسب.
- الخطوط واضحة.
- لا يوجد horizontal scroll.

========================
زر واتساب
========================

أضف زر واتساب عائم اختياري.

Super Admin يستطيع:
- تفعيله أو إخفاءه.
- تغيير الرقم.
- تغيير الرسالة الافتراضية.

مثال رسالة:
"مرحبا، أريد أعرف أكثر عن نظام فينورا."

========================
النتيجة النهائية المتوقعة
========================

بعد التنفيذ يجب أن أستطيع:

1. فتح صفحة Finora Landing Page للزوار.
2. مشاهدة صفحة احترافية كاملة.
3. الدخول كـ Super Admin.
4. تعديل عنوان Hero.
5. تغيير وصف الصفحة.
6. تغيير صورة الداشبورد.
7. تغيير الفيديو التعليمي.
8. إضافة أو حذف ميزة.
9. تعديل خطط الأسعار.
10. تغيير زر التجربة المجانية.
11. تعديل الأسئلة الشائعة.
12. تغيير SEO.
13. معاينة التغييرات قبل النشر.
14. نشر التغييرات.
15. رؤية التغييرات في الصفحة العامة بدون تعديل الكود.

========================
معايير القبول
========================

لا تعتبر المهمة مكتملة إلا إذا تحقق التالي:

- لا توجد نصوص Landing Page ثابتة داخل الكود إلا fallback.
- Super Admin يستطيع تعديل أغلب محتوى الصفحة.
- الخطط والأسعار تأتي من قاعدة البيانات.
- الفيديو قابل للتغيير من لوحة التحكم.
- الصور قابلة للتغيير من لوحة التحكم.
- FAQ قابل للإدارة.
- SEO قابل للإدارة.
- الصفحة Responsive.
- الصفحة RTL.
- الصفحة سريعة.
- يوجد Preview.
- يوجد Publish.
- يوجد حماية صلاحيات.
- يوجد Seed للمحتوى الافتراضي.
- لا توجد أخطاء Console.
- لا توجد أخطاء في السيرفر.
- التصميم احترافي ومناسب SaaS.
- الكود منظم وقابل للتوسعة.

========================
ملاحظات مهمة
========================

نفذها كميزة إنتاجية حقيقية، وليس Prototype بسيط.

اهتم بالبنية أكثر من الشكل فقط، لأن صفحة الهبوط ستتغير باستمرار حسب العروض والحملات والأسعار والفيديوهات.

يجب أن يكون Super Admin قادر على إدارة الصفحة بالكامل من النظام، لأننا نحتاج نغير الكلام والعروض والخطط والصور والفيديو بدون الرجوع للمطور.

ابدأ بفحص هيكل المشروع الحالي أولاً، ثم أضف الملفات والموديلات والـ routes والواجهات بطريقة لا تكسر النظام الحالي.

بعد التنفيذ، اكتب تقرير واضح يحتوي:
- الملفات التي تم إنشاؤها.
- الملفات التي تم تعديلها.
- الجداول التي تمت إضافتها.
- روابط لوحة التحكم.
- روابط APIs.
- طريقة تشغيل migration/seed.
- طريقة اختبار الصفحة.
- أي ملاحظات أو قيود.