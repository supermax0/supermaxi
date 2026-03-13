1) تصميم قاعدة بيانات جديدة للنشر
إنشاء جداول بسيطة وواضحة، مثلاً:
publish_channels:
id, tenant_slug, type (facebook_page, whatsapp_number, telegram_bot …), name, external_id, access_token أو مفاتيح الربط.
publish_jobs:
id, tenant_slug, content, media_url, media_type (image/video), status (pending, processing, published, failed), scheduled_at, published_at, channel_type, channel_id, error_message, retry_count.
لا نستخدم autoposter_posts القديمة؛ هذا نظام جديد.
2) طبقة خدمات موحدة لكل القنوات
ملف خدمة واحد مثلاً services/publisher_service.py يحتوي:
create_job(channels, content, media, scheduled_at) لإنشاء publish_jobs فقط.
process_pending_jobs_for_tenant(tenant_slug):
يحمّل كل jobs pending أو scheduled الجاهزة،
يستدعي دوال قناة محددة:
publish_to_facebook(job, channel)
publish_to_whatsapp(job, channel)
publish_to_telegram(job, channel)
يحدّث status, published_at, error_message, retry_count بنفس نمط إعادة المحاولة.
3) مسارات API بسيطة وثابتة
تحت routes/publisher.py (جديد):
GET /publisher/channels لإرجاع القنوات المربوطة (فيسبوك/واتساب/تيليجرام).
POST /publisher/jobs:
يستقبل:
text, media (ملف واحد اختياري), channel_ids[], scheduled_at.
يحفظ الميديا في مجلد ثابت واحد (مثلاً uploads/publisher باستخدام secure_filename واسم فريد).
ينشئ سجلات publish_jobs باستخدام publisher_service.create_job.
يرجع دائمًا:
200 { success: true, jobs: [...] } أو
400 { success: false, error: 'رسالة واضحة' }.
(لاحقًا) GET /publisher/jobs لعرض الحالة (Published / Pending / Failed).
4) واجهة فرونتند جديدة وبسيطة
صفحة واحدة جديدة في templates/publisher/dashboard.html + static/publisher/app.js:
اختيار القنوات (Checkboxes).
إدخال النص + رفع صورة/فيديو بواجهة drag & drop.
زر “إنشاء مهمة نشر”:
يرسل FormData إلى /publisher/jobs.
يعرض رسالة:
نجاح: “تم إنشاء مهمة النشر، سيتم التنفيذ تلقائياً.”
فشل: يعرض error من الـ API.
جدول لعرض jobs مع الأعمدة: القناة، النوع، الحالة، الوقت، رسالة الخطأ.
5) مجدول واحد موثوق
استخدام الدالة process_pending_jobs_for_tenant من publisher_service:
مربوطة بـ:
أمر كرون أو systemd timer يشغّل سكربت صغير (كما شرحت لك سابقًا) كل دقيقة.
كل شيء عن النشر الفعلي (فيسبوك/واتساب/تيليجرام) يصبح محصوراً في هذه الخدمة وحدها:
أي خطأ في API أو الفيديو لا يكسر /publisher/jobs؛ فقط يحدّث status وerror_message.
6) سلوك خالٍ من الأخطاء للـ API
جميع Endpoints الجديدة:
لا ترجع 500 إلا لو كان هناك استثناء غير متوقَّع جدًا، مع logger.exception.
تتعامل مع كل أخطاء المستخدم (حجم/صيغة فيديو، قنوات غير مربوطة، تاريخ خاطئ) برسائل 400 واضحة.
حتى لو غيرنا طريقة النشر الداخلية لاحقًا أو أضفنا قنوات جديدة، واجهة /publisher/jobs تبقى ثابتة.