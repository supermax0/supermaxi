ضع ملفات APK هنا ليعمل التحميل من صفحة الإعدادات:

1) finora-pos-webview.apk
   - نسخة WebView (مطابقة للموقع)

2) finora-pos-native.apk
   - نسخة Native Kotlin

3) finora-delivery-agent.apk
   - تطبيق بوابة المندوب (WebView)

4) finora-phone.apk
   - تطبيق Finora Phone (Companion CRM للمكالمات)

يمكن تغيير الروابط من متغيرات البيئة:
- APP_WEBVIEW_APK_URL
- APP_NATIVE_APK_URL
- APP_DELIVERY_AGENT_APK_URL
- APP_PHONE_APK_URL

مثال:
APP_WEBVIEW_APK_URL=/static/downloads/finora-pos-webview.apk
APP_NATIVE_APK_URL=/static/downloads/finora-pos-native.apk
APP_DELIVERY_AGENT_APK_URL=/static/downloads/finora-delivery-agent.apk
APP_PHONE_APK_URL=/static/downloads/finora-phone.apk

لبناء تطبيق المندوب:
  mobile\finora_delivery_agent_android\build_apk.ps1

لبناء تطبيق الهاتف (Field Test / staging):
  cd mobile\finora_phone
  flutter build apk --flavor staging --release --dart-define=FLAVOR=staging --dart-define=API_BASE_URL=https://YOUR_HOST --dart-define=TENANT_SLUG=YOUR_TENANT
  ثم انسخ الـ APK إلى static\downloads\finora-phone.apk
