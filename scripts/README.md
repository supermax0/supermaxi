# سكربتات المشروع

## رفع التحديثات إلى GitHub

### Windows (PowerShell)

```powershell
# من مجلد المشروع
.\scripts\push_to_github.ps1

# مع رسالة commit مخصصة
.\scripts\push_to_github.ps1 "إضافة ميزة X"
```

### Linux / Mac (Bash)

```bash
# من مجلد المشروع
chmod +x scripts/push_to_github.sh
./scripts/push_to_github.sh

# مع رسالة commit مخصصة
./scripts/push_to_github.sh "إضافة ميزة X"
```

السكربت يقوم بـ:

1. عرض حالة المستودع (`git status`)
2. إضافة كل التغييرات (`git add -A`) مع استثناء `.env` من الـ staging إن وُجد
3. تنفيذ commit بالرسالة المعطاة أو الافتراضية
4. رفع التغييرات إلى `origin main` (`git push origin main`)

تأكد من ضبط `origin` وفرع `main` قبل الاستخدام:

```bash
git remote -v
git branch
```
