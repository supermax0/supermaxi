# نظام الصلاحيات — FINORA

## النموذج
الصلاحية الفعلية لموظف **غير مدير عام**:

1. **منع فردي** (`deny`) — يغلب كل شيء (حتى الأدوار والافتراضات المدمجة للكاشير).
2. **سماح فردي** (`grant`) — يفتح الصلاحية حتى بلا دور.
3. **الأدوار** المعيّنة للموظف (`roles` ← `permissions`) — كما كان.

المدير العام (`role == "admin"`) يملك كل شيء ولا يُقيَّد بأي صف؛ محاولة تقييده تُرفض (400). إدارة الصلاحيات نفسها للمدير العام فقط ولا تُفوَّض.

## الملفات
| الملف | الدور |
|---|---|
| `models/employee_permission.py` | جدول `employee_permission_override` (صف واحد لكل موظف+صلاحية) |
| `utils/permission_overrides.py` | قراءة الاستثناءات (SAVEPOINT؛ جدول مفقود = لا استثناءات) |
| `utils/permission_checks.py::employee_can` و`Employee.has_permission` | تطبيق الاستثناءات في كل فحص |
| `routes/permissions.py` | `DEFAULT_PERMISSIONS` (الكتالوج بالتسميات) و`PERMISSION_GROUPS` (التجميع للعرض) |
| `utils/permission_admin.py` | الكتالوج، تفصيل الموظف ومصدر كل صلاحية، الاستثناءات، الأدوار، السجل |
| `modules/desktop_api/permissions.py` | `/api/v1/desktop/permissions/*` (مدير عام فقط، عدا `/me`) |
| `desktop/.../windows/permissions/` | نافذة «الصلاحيات والأدوار» |

## الصلاحيات المفوَّضة (كانت للمدير فقط)
`manage_branches` · `view_branch_reports` · `manage_branch_staff` · `run_branch_distribution` · `allocate_branch_expenses` · `merge_delivery_agents`
(الأخيرة تحتاج فوقها `view_shipping`). أرقام الفروع الحساسة (مبيعات/مخزون/نقد) تُحجب عمّن لا يملك `view_branch_reports`.

## إصلاحات أمنية ضمن هذا العمل
* **بوابة الدخول العامة كانت تُعفي كل مسار يبدأ بـ `/c`** (لبوابة المريض) فتفتح `/customers` و`/cash` و`/clinics` (~270 مساراً) للزائر دون دخول. صار التطابق على حدود المقطع (`_path_is_open` في `app.py`، ومثلها `app_server.py`).
* `/pos/search-customer` و`/pos/search-product` و`/pos/last-orders` تردّ 401 للزائر.
* ~70 اسم صلاحية يفحصها الكود لم تكن بالكتالوج (finance.\*، hr.\*، inventory.audit.\*، edit_current_stock، edit_product …) فكانت **للمدير حصراً عملياً**؛ سُجّلت كلها بتسميات عربية وصارت قابلة للمنح.

## الاختبارات
* `tests/test_permissions_system.py` — دلالات الاستثناء (منع>سماح>دور)، حماية المدير، التحقق، الأدوار، السجل، `/me`، وفرض كل إجراء مفوَّض (18 إجراء × [مدير/بلا صلاحية/سماح فردي/موظف آخر/منع فوق دور/إزالة الاستثناء]).
* `tests/test_permission_coverage.py` — يمشي على **كل مسار** في التطبيق: الزائر لا يصل إلا للعام، موظف بلا أي صلاحية لا يصل لأي سطح للسطح المكتب، «امنح الكل» يفتح كل شيء عدا إدارة الصلاحيات، «امنع الكل» يغلق كل شيء، ومراقبة (admin يصل لأكثر من 40 مساراً) تثبت أن المشي ذو معنى.
* `tests/test_permission_registry.py` — مسح ساكن للكود: أي اسم صلاحية يُفحص ولا يوجد بالكتالوج يُفشل الاختبار.
* واجهة: `permissions.test.tsx` (4).
