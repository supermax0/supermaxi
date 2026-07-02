ضع ملفات APK هنا ليعمل التحميل من صفحة الإعدادات:

1) finora-pos-webview.apk
   - نسخة WebView (مطابقة للموقع)

2) finora-pos-native.apk
   - نسخة Native Kotlin

3) finora-delivery-agent.apk
   - تطبيق بوابة المندوب (WebView)

يمكن تغيير الروابط من متغيرات البيئة:
- APP_WEBVIEW_APK_URL
- APP_NATIVE_APK_URL
- APP_DELIVERY_AGENT_APK_URL

مثال:
APP_WEBVIEW_APK_URL=/static/downloads/finora-pos-webview.apk
APP_NATIVE_APK_URL=/static/downloads/finora-pos-native.apk
APP_DELIVERY_AGENT_APK_URL=/static/downloads/finora-delivery-agent.apk

لبناء تطبيق المندوب:
  mobile\finora_delivery_agent_android\build_apk.ps1
