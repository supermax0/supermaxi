# تكوين بوت تيليجرام مع systemd

## 1. ضبط متغيرات البيئة في الخدمة

عدّل ملف الخدمة:

```bash
sudo nano /etc/systemd/system/finora.service
```

أضف داخل `[Service]` (أو استبدل القيم إذا كانت موجودة):

```ini
Environment="BOT_TOKEN=<ضع_توكن_البوت_هنا>"
Environment="OPENAI_API_KEY=<ضع_مفتاح_OpenAI_هنا>"
```

## 2. إعادة تحميل الخدمة وإعادة التشغيل

```bash
sudo systemctl daemon-reload
sudo systemctl restart finora
```

## 3. التحقق من السجلات

```bash
# متابعة السجلات مباشرة
sudo journalctl -u finora -f
```

عند وصول رسالة تيليجرام يجب أن ترى شيئاً مثل:

- `Telegram webhook: received update, keys=[...]`
- `Telegram webhook: chat_id=... has_text=True`
- `Telegram send OK: chat_id=...`

إذا ظهر تحذير مثل:

- `BOT_TOKEN / TELEGRAM_BOT_TOKEN not set` → تأكد من وجود `Environment="BOT_TOKEN=..."` في الخدمة.
- `OPENAI_API_KEY not set` → تأكد من وجود `Environment="OPENAI_API_KEY=..."` في الخدمة.

## 4. المسار المتوقع للرد

رسالة تيليجرام → `POST /telegram/webhook` → Flask يستقبل التحديث → توليد رد بالـ AI → إرسال الرد عبر `https://api.telegram.org/bot{BOT_TOKEN}/sendMessage`.
