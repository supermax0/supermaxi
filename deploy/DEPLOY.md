# نشر Finora على VPS (Ubuntu)

استخدم الخطوات التالية على خادم Ubuntu.

## 1. تحديث الخادم

```bash
sudo apt update
sudo apt upgrade -y
```

## 2. تثبيت المتطلبات

```bash
sudo apt install -y python3 python3-pip python3-venv nginx git
```

## 3. استنساخ المشروع

```bash
cd /root
git clone https://github.com/supermax0/supermaxi.git finora-saas
cd finora-saas
```

## 4. البيئة الافتراضية والاعتماديات

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

## 5. ملف البيئة (.env)

```bash
nano /root/finora-saas/.env
```

أضف على الأقل:

```
SECRET_KEY=your-secure-secret-key-here
FLASK_ENV=production
```

احفظ (Ctrl+O ثم Enter) واخرج (Ctrl+X).

## 6. نظام الخدمة (systemd)

```bash
sudo cp /root/finora-saas/deploy/finora.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start finora
sudo systemctl enable finora
sudo systemctl status finora
```

## 7. Nginx

عدّل النطاق في ملف الإعداد ثم انسخه وفعّله:

```bash
sudo sed -i 's/YOUR_DOMAIN/yourdomain.com/g' /root/finora-saas/deploy/nginx-finora.conf
sudo cp /root/finora-saas/deploy/nginx-finora.conf /etc/nginx/sites-available/finora
sudo ln -sf /etc/nginx/sites-available/finora /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 8. SSL (اختياري)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

**النتيجة:** تطبيق Finora يعمل خلف Nginx + Gunicorn، مع إمكانية تفعيل HTTPS عبر Certbot.

**تحديث التطبيق لاحقاً:**

```bash
cd /root/finora-saas
git pull
source venv/bin/activate
pip install -r requirements.txt
deactivate
sudo systemctl restart finora
```
