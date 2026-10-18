# تقرير صفحات إدارة العيادات — FINORA Clinics 1.0

**المنتج:** FINORA Clinics 1.0 RC1  
**المخطط الداخلي:** `clinics-v26-cardiology-clinical-tools`  
**التاريخ:** 2026-09-05  

هذا التقرير يصف **كل صفحات إدارة العيادة**، ميزاتها، أهم الحقول، و**بما ترتبط كل ميزة** (جداول / APIs / صفحات أخرى / أدوار).

---

## 0. كيف يعمل النظام

| عنصر | التفاصيل |
|------|----------|
| القشرة | صفحة واحدة SPA: `templates/clinics/workspace.html` تحت المسار `/clinics/...` |
| التوجيه | Flask يمرّر `clinics_page` + عنوان عربي → `clinics.js` يحمّل الوحدة المناسبة |
| القائمة | `static/clinics/nav.js` + صلاحيات من `/clinics/api/bootstrap` (`build_nav_matrix`) |
| الشخصيات | مالك / طبيب / استقبال / موظف — تظهر وتُخفى عناصر القائمة حسب الدور |
| الحجز العام | خارج الشريط الجانبي: `/c/<slug>` و `/c/<slug>/manage/<token>` |

### مجموعات الشريط الجانبي

| المجموعة | بالعربية |
|----------|----------|
| daily | التشغيل اليومي |
| patients | المرضى |
| clinical | الطبي |
| finance | المالية |
| inventory | المخزون |
| admin | الإدارة |
| more | المزيد |

---

## 1. فهرس الصفحات السريع

| الصفحة | المسار | الصلاحية | ملف JS الرئيسي |
|--------|--------|----------|----------------|
| لوحة العيادة | `/clinics/` | `clinics_dashboard` | `dashboard.js` |
| الاستقبال | `/clinics/reception` | `clinics_reception` | `reception.js` |
| المواعيد | `/clinics/appointments` | `clinics_appointments` | `appointments.js` |
| قائمة الانتظار | `/clinics/queue` | `clinics_reception` | `queue.js` |
| شاشة الانتظار | `/clinics/display` | `clinics_reception` | `display.js` |
| المرضى | `/clinics/patients` | `clinics_patients` | `patients.js` |
| ملف المريض | `/clinics/patients/<id>` | `clinics_patients` | `patient-profile.js` |
| الزيارات | `/clinics/visits` | `clinics_visits` | `visits.js` |
| مساحة الطبيب | `/clinics/doctor/<visit_id>` | `clinics_clinical` | `clinics.js` + أدوات الاختصاص |
| السجل الطبي | `/clinics/clinical` | `clinics_clinical` | `clinical.js` |
| التحاليل | `/clinics/labs` | `clinics_clinical` | `clinical_ops.js` |
| الأشعة | `/clinics/radiology` | `clinics_clinical` | `clinical_ops.js` |
| الإجراءات | `/clinics/procedures` | `clinics_clinical` | `clinical_ops.js` |
| المتابعات | `/clinics/followups` | `clinics_clinical` | `clinical_ops.js` |
| الفواتير والمدفوعات | `/clinics/billing` | `clinics_billing` | `finance.js` |
| المصروفات | `/clinics/expenses` | `clinics_billing` | `finance.js` |
| الصندوق | `/clinics/cash` | `clinics_billing` | `finance.js` |
| تسوية الأطباء | `/clinics/settlements` | `clinics_billing` | `finance.js` |
| مخزون العيادة | `/clinics/inventory` | `clinics_inventory` | `inventory.js` |
| المشتريات | `/clinics/purchases` | `purchases.view` | `purchases.js` |
| الموردون | `/clinics/suppliers` | `clinics_inventory` | `inventory.js` / purchases |
| الأطباء | `/clinics/doctors` | `clinics_admin` | `clinics.js` |
| ملف الطبيب | `/clinics/doctors/<id>` | `clinics_admin` | `clinics.js` |
| الاختصاصات | `/clinics/specialties` | `clinics_admin` | `specialty-builder.js` |
| جداول الدوام | `/clinics/schedules` | `clinics_admin` | `clinics.js` |
| الخدمات | `/clinics/services` | `clinics_admin` | `services.js` |
| الغرف | `/clinics/rooms` | `clinics_admin` | `clinics.js` |
| المرفقات | `/clinics/attachments` | `clinics_patients` | `attachments.js` |
| التواصل والحجوزات | `/clinics/communications` | `clinics_communications_view` | `communications.js` |
| التقارير | `/clinics/reports` | `clinics_reports` | `reports.js` |
| إعدادات العيادة | `/clinics/settings` | `clinics_settings` | `clinics.js` |
| حجز عام | `/c/<slug>` | عام | `public_booking.html` |
| إدارة موعد عام | `/c/<slug>/manage/<token>` | عام | `public_manage.html` |

---

## 2. التشغيل اليومي

### 2.1 لوحة العيادة — `/clinics/`

| | |
|--|--|
| **الغرض** | نظرة يومية للمالك/المدير: أرقام، نبض التشغيل، اختصارات |
| **JS** | `dashboard.js` |
| **API** | `/clinics/api/dashboard`, `/clinics/api/dashboard/pulse` |
| **جداول** | تجميعات من مواعيد/زيارات/فواتير/متابعات |

**الميزات وارتباطها**

| ميزة | ترتبط بـ |
|------|----------|
| مؤشرات اليوم (مواعيد، زيارات، إيرادات…) | صفحات المواعيد / الزيارات / الفواتير |
| نبض التشغيل / تنبيهات | المتابعات، الطابور، الحجوزات العامة |
| اختصارات سريعة | الاستقبال، مريض جديد، زيارة |

---

### 2.2 الاستقبال — `/clinics/reception`

| | |
|--|--|
| **الغرض** | لوحة يوم الاستقبال: حضور، walk-in، تسليم للطبيب، مدفوعات سريعة |
| **JS** | `reception.js` |
| **API** | `/clinics/api/reception`, مواعيد، طابور، مدفوعات |
| **جداول** | `clinic_appointment`, `clinic_visit`, `clinic_payment` |

**حقول / فلاتر شائعة**

| حقل | الوظيفة | ارتباط |
|-----|---------|--------|
| بحث مريض/هاتف | إيجاد موعد أو مريض | `clinic_patient` |
| فلتر طبيب / فرع | تصفية لوحة اليوم | `clinic_doctor` / فروع |
| تاريخ/وقت إعادة جدولة | تعديل الموعد | `clinic_appointment` |
| مبلغ + طريقة دفع | قبض سريع | `clinic_invoice` / `clinic_payment` |

**الميزات وارتباطها**

| ميزة | ترتبط بـ |
|------|----------|
| تأكيد / وصول / انتظار | حالات الموعد → الطابور → مساحة الطبيب |
| زيارة فورية (walk-in) | إنشاء `clinic_visit` مباشرة |
| فتح مساحة الطبيب | `/clinics/doctor/<visit_id>` |
| قبض جزئي/كامل | الفواتير والمدفوعات |

---

### 2.3 المواعيد — `/clinics/appointments`

| | |
|--|--|
| **الغرض** | جدولة وإدارة المواعيد (لوحة / أجندة / تقويم) |
| **JS** | `appointments.js` |
| **API** | `/clinics/api/appointments/*` (حالة، إعادة جدولة،slots…) |
| **جداول** | `clinic_appointment`, `clinic_appointment_status_history` |

**حقول حجز موعد**

| حقل | مطلوب؟ | ارتباط |
|-----|--------|--------|
| بحث مريض / اختيار مريض | نعم | `clinic_patient` |
| اختصاص | نعم | `clinic_specialty` |
| طبيب | نعم | `clinic_doctor` + جدول دوام |
| خدمة | غالباً | `clinic_service` (سعر/مدة) |
| التاريخ + الوقت | نعم | slots من الجدول |
| ملاحظات | لا | نص على الموعد |

**حالات شائعة:** pending / confirmed / scheduled / arrived / waiting / completed / cancelled / no_show

**الميزات وارتباطها**

| ميزة | ترتبط بـ |
|------|----------|
| سحب وإفلات / إعادة جدولة | نفس الموعد + slots الطبيب |
| أولوية / طوارئ | عرض الاستقبال والطابور |
| تقويم متعدد أطباء | جداول الدوام + الألوان |
| فتح ملف المريض | `/clinics/patients/<id>` |

---

### 2.4 قائمة الانتظار — `/clinics/queue`

| | |
|--|--|
| **الغرض** | ترتيب المرضى الحاضرين واستدعاء التالي |
| **JS** | `queue.js` |
| **API** | `/clinics/api/queue/*` |
| **ارتباط** | مواعيد بحالة waiting/arrived → زيارات → مساحة الطبيب / شاشة الانتظار |

---

### 2.5 شاشة الانتظار — `/clinics/display`

| | |
|--|--|
| **الغرض** | شاشة TV للقاعة (اسم/رقم الاستدعاء) |
| **JS** | `display.js` |
| **API** | `/clinics/api/public-queue` |
| **ارتباط** | الطابور والاستقبال فقط — بدون إدخال سريري |

---

## 3. المرضى والزيارات

### 3.1 سجل المرضى — `/clinics/patients`

| | |
|--|--|
| **JS** | `patients.js` |
| **API** | `/clinics/api/patients*`, check-phone, check-similar, export, registry |
| **جدول أساسي** | `clinic_patient` |

**حقول إنشاء/تعديل مريض**

| الحقل | مطلوب | ملاحظات / ارتباط |
|-------|-------|------------------|
| الاسم الكامل | نعم | هوية العرض |
| رقم الهاتف | نعم | فحص تكرار → يمنع الملفات المكررة |
| الجنس | لا | ذكر/أنثى |
| تاريخ الميلاد | لا | عمر، أطفال، حمل |
| العنوان | لا | — |
| فصيلة الدم | لا | تظهر في الملف السريري |
| هاتف طوارئ | لا | — |
| الحساسية | لا | تحذير في مساحة الطبيب / القلب |
| ملاحظات | لا | — |
| رقم الملف | تلقائي غالباً | بحث وبطاقة مريض |

**فلاتر:** مريض جديد · عليه رصيد · متابعة  

**الميزات وارتباطها**

| ميزة | ترتبط بـ |
|------|----------|
| بطاقة طباعة | بيانات المريض فقط |
| اتصال هاتفي | `tel:` |
| فتح الملف | ملف المريض الكامل |
| تصدير | تقارير/عمليات |
| حجز من السجل | المواعيد |

---

### 3.2 ملف المريض — `/clinics/patients/<id>`

| | |
|--|--|
| **JS** | `patient-profile.js` + أدوات الاختصاص عند الحاجة |
| **API** | `/clinics/api/patients/<id>`, `/api/clinical/patients/<id>?section=…`, APIs الاختصاص |

**المحاور (Hubs)**

| المحور | بالعربية | الأقسام الفرعية |
|--------|----------|-----------------|
| overview | نظرة عامة | ملخص + مواعيد قادمة |
| schedule | المواعيد والزيارات | مواعيد، زيارات |
| clinical | السجل السريري | خط زمني، وصفات، تحاليل، أشعة، أسنان، أطفال، نسائية، باطنية، قلب |
| treatment | العلاج والمتابعة | إجراءات، متابعات |
| files | الملفات | مرفقات |
| finance | المالية | فواتير وكشف حساب |

**ارتباط أقسام الاختصاص**

| قسم | أداة JS | جداول / APIs |
|-----|---------|--------------|
| الأسنان | مخطط + خطة علاج | `clinic_dental_*`, dental-history / treatment-plans |
| طب الأطفال | `pediatric-tools.js` | profile / growth / vaccinations / development |
| النسائية | `gynecology-tools.js` | profile / pregnancies / observations |
| الباطنية | `internal-medicine-tools.js` | chronic-conditions / medications / trends |
| القلب | `cardiology-tools.js` | cardiology-profile / ecgs / echos |

---

### 3.3 الزيارات — `/clinics/visits`

| | |
|--|--|
| **JS** | `visits.js` |
| **API** | `/clinics/api/visits*` |
| **جدول** | `clinic_visit` |
| **ارتباط** | فتح مساحة الطبيب، ربط مريض/طبيب/اختصاص/فاتورة |

---

### 3.4 مساحة الطبيب — `/clinics/doctor/<visit_id>`

| | |
|--|--|
| **الغرض** | مسار الزيارة السريرية الكامل حتى الإكمال والفوترة |
| **صلاحية** | `clinics_clinical` |
| **جداول** | `clinic_visit`, `clinic_vital`, `clinic_diagnosis`, `clinic_prescription*`, `clinic_visit_field_value`, جداول الاختصاص |

**تبويبات**

| تبويب | متى يظهر | المحتوى | ارتباط |
|-------|----------|---------|--------|
| الزيارة | دائماً | شكوى، ملاحظات، علامات حيوية، تشخيص، متابعة | `clinic_vital`, diagnoses, followups |
| الفحص | إن وُجد قالب زيارة | نموذج ديناميكي حسب الاختصاص | `clinic_visit_template*` + قيم الحقول |
| العلاج | طب أسنان | خطة علاج أسنان | dental treatment plan |
| طب الأطفال | اختصاص pediatrics | نمو، لقاحات، تطور | pediatric tables |
| النسائية والتوليد | OB/GYN | حمل، ملاحظات حمل | pregnancy tables |
| الباطنية | internal_medicine | مزمن + أدوية + اتجاهات | chronic + medications |
| القلب والأوعية | cardiology | ملف قلبي، ECG، Echo | cardiology tables |
| الوصفة | دائماً | أدوية + قوالب + طباعة | `clinic_prescription*` |
| الفاتورة | دائماً | بنود علاج → إكمال | `clinic_invoice` / treatment-bill |

**حقول العلامات الحيوية (أمثلة)**

ضغط الدم · النبض · الحرارة · الوزن · الطول · السكر · SpO2 · أخرى حسب القالب

**إجراءات علوية:** إكمال وإصدار فاتورة · ملف المريض · قفز سريع للتبويب

---

## 4. الطبي (خارج مساحة الزيارة)

### 4.1 السجل الطبي — `/clinics/clinical`

| | |
|--|--|
| **JS** | `clinical.js` |
| **API** | `/clinics/api/clinical/*` |
| **تبويبات** | ملخص · خط زمني · زيارات · تشخيصات · أدوية · تحاليل · أشعة · مرفقات · علامات حيوية |
| **ارتباط** | بحث مريض ثم عرض مجمّع؛ مكمل لملف المريض |

---

### 4.2 التحاليل — `/clinics/labs`

| ميزة | حقول/محتوى | ارتباط |
|------|-------------|--------|
| كتالوج تحاليل | اسم، رمز، سعر… | `clinic_lab_test` |
| طلبات | مريض، زيارة، عناصر، حالة | `clinic_lab_order*` |
| نتائج | قيم/ملاحظات | تظهر في السجل والباطنية (اتجاهات) |

---

### 4.3 الأشعة — `/clinics/radiology`

| ميزة | ارتباط |
|------|--------|
| طلبات أشعة وحالاتها | `clinic_radiology_order` → السجل / ملف المريض |

---

### 4.4 الإجراءات — `/clinics/procedures`

| ميزة | ارتباط |
|------|--------|
| كتالوج إجراءات + ربط اختصاص | `clinic_procedure`, `clinic_procedure_specialty` |
| وصفة مخزون للإجراء | `clinic_procedure_recipe_item` → خصم مخزون عند التنفيذ |
| تنفيذ على زيارة | `clinic_visit_procedure` → فاتورة/مخزون |

---

### 4.5 المتابعات — `/clinics/followups`

| ميزة | ارتباط |
|------|--------|
| قائمة استحقاق، محاولات اتصال | `clinic_follow_up*` ← تُنشأ من مساحة الطبيب / السياسات |
| تفتح المريض أو الموعد | المرضى / المواعيد |

---

## 5. المالية

### 5.1 الفواتير والمدفوعات — `/clinics/billing`

| | |
|--|--|
| **JS** | `finance.js` + `finance-shared.js` |
| **API** | `/clinics/api/invoices`, payments, refunds |
| **جداول** | `clinic_invoice`, `clinic_invoice_item`, `clinic_payment` |

**الميزات وارتباطها**

| ميزة | ارتباط |
|------|--------|
| قائمة فواتير بفلاتر | زيارة / مريض / حالة السداد |
| تسجيل دفعة | طرق: نقدي، بطاقة، تحويل… |
| طباعة فاتورة | طابعات العيادة |
| كشف رصيد مريض | ملف المريض → المالية |

---

### 5.2 المصروفات — `/clinics/expenses`

| حقول شائعة | ارتباط |
|------------|--------|
| المبلغ، التصنيف، التاريخ، ملاحظة | `clinic_expense` → التقارير المالية |

---

### 5.3 الصندوق — `/clinics/cash`

| ميزة | ارتباط |
|------|--------|
| فتح/إغلاق جلسة صندوق | `clinic_cash_session` ↔ المدفوعات النقدية لليوم |

---

### 5.4 تسوية الأطباء — `/clinics/settlements`

| ميزة | ارتباط |
|------|--------|
| تسوية فترة لطبيب | `clinic_doctor_settlement` ↔ فواتير/إجراءات الطبيب · يُخفى غالباً في العيادة الفردية |

---

## 6. المخزون والمشتريات

### 6.1 المخزون — `/clinics/inventory`

| عرض فرعي | المسار | الغرض |
|----------|--------|-------|
| القائمة | `/clinics/inventory` | الأصناف والكميات |
| تفاصيل صنف | `/clinics/inventory/items/<id>` | بطاقة الصنف |
| الحركات | `/clinics/inventory/movements` | دخول/خروج |
| الدفعات | `/clinics/inventory/batches` | LOT / صلاحية |
| الصلاحية | `/clinics/inventory/expiry` | تنبيهات انتهاء |

**جداول:** `clinic_inventory_item`, `clinic_inventory_batch`, `clinic_inventory_movement`  

**ارتباط:** وصفات الإجراءات، المشتريات، التقارير

---

### 6.2 المشتريات — `/clinics/purchases*`

| شاشة | مسار | ارتباط |
|------|------|--------|
| قائمة | `/clinics/purchases` | فواتير شراء |
| جديدة | `/clinics/purchases/new` | مورد + بنود → مخزون |
| تعديل/تفاصيل | `/clinics/purchases/<id>` | نفس الفاتورة |
| تقارير | `/clinics/purchases/reports` | ملخصات |
| طباعة | قوالب `purchase_*_print.html` | ورق A4 |

---

### 6.3 الموردون — `/clinics/suppliers`

| ميزة | ارتباط |
|------|--------|
| بطاقة مورد + كشف حساب | `clinic_supplier` ↔ المشتريات والمدفوعات للمورد |

---

## 7. الإدارة

### 7.1 الأطباء — `/clinics/doctors` و `/clinics/doctors/<id>`

| ميزة | حقول/محتوى | ارتباط |
|------|-------------|--------|
| قائمة الأطباء | الاسم، اختصاص أساسي، تفعيل | `clinic_doctor` |
| ربط موظف HR | اختياري | موارد بشرية / إجازات |
| درج الملف | نظرة عامة · مالية سريرية · حضور وإجازات | schedules, settlements, time-off |
| اختصاصات متعددة | ربط | `clinic_doctor_specialty` |

---

### 7.2 الاختصاصات وقوالب الزيارة — `/clinics/specialties`

| | |
|--|--|
| **JS** | `specialty-builder.js` |
| **جداول** | `clinic_specialty`, `clinic_visit_template`, sections, fields |

**الميزات وارتباطها**

| ميزة | ارتباط |
|------|--------|
| تفعيل اختصاص للعيادة | يظهر في الحجز ومساحة الطبيب |
| بناء قالب (أقسام/حقول) | تبويب «الفحص» في الزيارة |
| أنواع حقول (نص، رقم، اختيار، `dental_chart`…) | قيم في `clinic_visit_field_value` |
| نشر/أرشفة قالب | إصدارات القالب على الزيارات السابقة تبقى ثابتة |

---

### 7.3 الخدمات — `/clinics/services`

| حقول | ارتباط |
|------|--------|
| الاسم، السعر، المدة، ربط اختصاص/أطباء | المواعيد، الفاتورة، الحجز العام |

---

### 7.4 جداول الدوام — `/clinics/schedules`

| ميزة | ارتباط |
|------|--------|
| أيام/ساعات الطبيب | توليد slots للمواعيد والحجز العام |
| إجازات / time-off | `clinic_doctor_time_off` يمنع الحجز |

---

### 7.5 الغرف — `/clinics/rooms`

| ميزة | ارتباط |
|------|--------|
| غرف العيادة | ربط اختياري بالمواعيد/الزيارات · أقل ظهوراً في العيادة الفردية |

---

### 7.6 الإعدادات — `/clinics/settings`

| مجموعة إعدادات | ارتباط |
|----------------|--------|
| بيانات العيادة / ترويسة فاتورة | الطباعة والفواتير |
| الحجز الإلكتروني، OTP، نص ترحيب | `/c/<slug>` + `clinic_settings` |
| رابط الحجز / QR | التواصل والحجوزات |

---

## 8. المزيد

### 8.1 المرفقات — `/clinics/attachments`

| ميزة | ارتباط |
|------|--------|
| مركز وثائق المرضى | `clinic_attachment` ↔ ملف المريض / السجل |

---

### 8.2 التواصل والحجوزات — `/clinics/communications`

| تبويب | محتوى | ارتباط |
|-------|--------|--------|
| صندوق الوارد | محادثات عامة | `clinic_conversation*` |
| الحجوزات | طلبات بانتظار الموافقة | `clinic_booking_request` → موعد |
| التذكيرات | رسائل مجدولة | إعدادات التواصل |
| رابط الحجز / QR | نشر الرابط العام | `/c/<slug>` |
| الإعدادات | مباشر/موافقة، شات، ملف عام | `clinic_settings` |

---

### 8.3 التقارير — `/clinics/reports`

| ميزة | ارتباط |
|------|--------|
| لوحة تقارير + رسوم + تصدير | `/clinics/api/reports/*` تجميع مواعيد/زيارات/مالية/مخزون |

---

## 9. الحجز العام (خارج الشريط)

### 9.1 حجز موعد — `/c/<slug>`

| خطوة المعالج | حقول | ارتباط |
|--------------|------|--------|
| اختيار طبيب | قائمة الأطباء الظاهرين | `clinic_doctor` + إعدادات عامة |
| خدمة | الخدمات المتاحة | `clinic_service` |
| وقت | slots | الجداول |
| بيانات المريض | اسم، هاتف، … + OTP إن فُعّل | مريض جديد أو موجود |
| تأكيد | رمز إدارة | `clinic_appointment` + tokens |

يمكن أيضاً وضع **محادثة** حسب الإعدادات.

### 9.2 إدارة الموعد — `/c/<slug>/manage/<token>`

| ميزة | ارتباط |
|------|--------|
| عرض / إعادة جدولة / إلغاء | نفس الموعد بدون دخول للنظام الداخلي |

---

## 10. أدوات الاختصاص (ليست صفحات شريط — داخل الطبيب + ملف المريض)

| الاختصاص | أين تظهر | ميزات رئيسية | جداول |
|----------|----------|--------------|-------|
| أسنان | تبويب علاج + مخطط في الفحص | أسنان، أسطح، خطة علاج، جلسات | `clinic_dental_*` |
| أطفال | تبويب أطفال | ملف، نمو (تاريخ فقط وليس WHO)، لقاحات، تطور | `clinic_pediatric_*` |
| نسائية/توليد | تبويب نسائية | دورة، حمل، LMP/EDD، ملاحظات حمل | `clinic_gynecology_*`, `clinic_pregnancy*` |
| باطنية | تبويب باطنية | أمراض مزمنة، أدوية حالية، اتجاهات حيوية/مختبر، مقارنة زيارات | `clinic_chronic_condition`, `clinic_patient_medication` |
| قلب | تبويب قلب | ملف قلبي، عوامل خطورة من السجل، ECG، Echo (إدخال يدوي) | `clinic_cardiology_*` |

**قاعدة منتج:** لا تُضاف كعناصر شريط جانبي منفصلة.

---

## 11. خريطة التدفق التشغيلي (ارتباط الصفحات)

```text
مريض (إنشاء/بحث)
   ↓
موعد (حجز / استقبال / حجز عام)
   ↓
وصول → طابور → شاشة انتظار
   ↓
زيارة → مساحة الطبيب (سريري + اختصاص + وصفة + فاتورة)
   ↓
إكمال → فاتورة → دفع (استقبال/مالية/صندوق)
   ↓
متابعة / مرفقات / تقارير
```

**المخزون يلتقي السريري عند:** تنفيذ إجراء بوصفة مواد.  
**المشتريات تغذي:** المخزون.  
**الجداول تغذي:** المواعيد والحجز العام.

---

## 12. الأدوار وما يرونه (ملخص)

| الدور | تركيز الشريط |
|-------|----------------|
| مالك | الكل تقريباً + إعدادات وتقارير ومالية |
| طبيب | زياراتي، مرضى، سريري، اختصارات مساحة الطبيب — يُخفى استقبال/إدارة ثقيلة |
| استقبال | استقبال، مواعيد، طابور، مرضى، فوترة أساسية |
| محاسب/مخزون | مالية، مشتريات، مخزون حسب الصلاحيات |

التفاصيل الدقيقة في `build_nav_matrix` داخل `modules/clinics/service_dashboard.py`.

---

## 13. ملفات المصدر المرجعية

| النوع | المسار |
|-------|--------|
| توجيه الصفحات | `modules/clinics/routes.py` (`PAGE_CONFIG`) |
| القائمة | `static/clinics/nav.js` + `templates/clinics/workspace.html` |
| الأوركسترا | `static/clinics/clinics.js` |
| الحجز العام | `modules/clinics/public_routes.py`, `templates/clinics/public_*.html` |
| النماذج | `modules/clinics/models.py` |

---

## 14. حدود معلنة (ليست ميزات مخفية)

راجع `docs/CLINICS_KNOWN_LIMITATIONS.md` — مثلاً: لا نسب WHO تلقائية، لا تفسير ECG آلي، لا محرك تفاعلات دوائية، لا نقاط مخاطر قلبية.

---

*نهاية التقرير. لأي صفحة تحتاج تفصيلاً أعمق لحقول نموذج واحد (مثلاً فاتورة الشراء سطراً بسطر) يمكن توسيع قسمها لاحقاً.*
