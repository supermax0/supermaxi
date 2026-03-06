#!/bin/bash
# push_to_github.sh — رفع التحديثات إلى GitHub (Linux / Mac)
# الاستخدام: ./scripts/push_to_github.sh ["رسالة الـ commit"]

MSG="${1:-Update: sync latest changes}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

echo "Git status..."
git status

if [ -z "$(git status --porcelain)" ]; then
    echo "لا يوجد تغييرات لرفعها."
    exit 0
fi

echo ""
echo "Adding changes..."
git add -A
git reset HEAD -- .env 2>/dev/null || true
git status --short

echo ""
echo "Commit: $MSG"
git commit -m "$MSG" || { echo "فشل الـ commit أو لا تغييرات."; exit 0; }

echo ""
echo "Pushing to origin main..."
if git push origin main; then
    echo ""
    echo "تم رفع التحديثات إلى GitHub بنجاح."
else
    echo ""
    echo "فشل الـ push. تحقق من الربط والصلاحيات (git remote -v)."
    exit 1
fi
