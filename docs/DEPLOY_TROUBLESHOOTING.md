# استكشاف أخطاء النشر (Finora)

## 1. Gunicorn لا يستمع على المنفذ 8000

**الأعراض:** السكربت يطبع `No process is listening on port 8000` أو `Address already in use`.

**ما الذي تفعله على السيرفر (SSH):**

```bash
# تحرير المنفذ وقتل أي gunicorn قديم
sudo pkill -9 gunicorn
sudo fuser -k 8000/tcp
sleep 2

# إعادة تشغيل الخدمة
sudo systemctl restart finora

# عرض آخر سطور السجل لمعرفة سبب فشل gunicorn (إن فشل)
sudo journalctl -u finora -n 50 --no-pager
```

**إن كان المنفذ ما زال مستخدماً:**  
تأكد أن الخدمة في systemd تستخدم الاسم الصحيح (مثلاً `finora` أو `supermaxi`). إن كانت الخدمة باسم آخر عدّل سكربت النشر لاستخدامه.

**إن كان gunicorn يتوقف فور البدء:**  
اقرأ مخرجات `journalctl` — غالباً خطأ استيراد (ImportError) أو خطأ في التطبيق. أصلح الخطأ في الكود ثم أعد النشر.

---

## 2. خطأ ERR_SSL_PROTOCOL_ERROR في المتصفح

**الأعراض:** عند فتح `https://finora.company/publish/dashboard` يظهر "This site can't provide a secure connection" و `ERR_SSL_PROTOCOL_ERROR`.

**السبب:** النطاق يُفتح عبر **HTTPS** بينما السيرفر (أو Nginx) غير مهيأ لـ SSL لهذا النطاق.

**حل مؤقت — استخدم HTTP:**  
جرّب فتح الرابط بدون `s` في `https`:

- **http://finora.company/publish/dashboard**

(يجب أن يكون Nginx أو الخادوم يخدم الموقع على المنفذ 80 دون إجبار HTTPS.)

**حل دائم — تفعيل SSL:**

1. تثبيت شهادة (مثلاً Let's Encrypt):
   ```bash
   sudo certbot --nginx -d finora.company
   ```
2. أو إعداد Nginx يدوياً لـ `finora.company` مع `ssl_certificate` و `ssl_certificate_key` ثم `sudo systemctl reload nginx`.

بعد تفعيل SSL يمكن استخدام **https://finora.company/publish/dashboard** بدون خطأ.
