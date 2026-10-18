#!/bin/bash
set -e
APP=/var/www/finora/supermaxi
SRC=/tmp/specialty_guides_deploy
mkdir -p "$APP/modules/clinics" "$APP/templates/clinics" "$APP/static/clinics"
cp "$SRC/specialty_guides.py" "$APP/modules/clinics/"
cp "$SRC/routes.py" "$APP/modules/clinics/"
cp "$SRC/specialty_guide.html" "$APP/templates/clinics/"
cp "$SRC/workspace.html" "$APP/templates/clinics/"
cp "$SRC/clinics.js" "$APP/static/clinics/"
cp "$SRC/clinics.css" "$APP/static/clinics/"
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
test -f "$APP/modules/clinics/specialty_guides.py" && echo GUIDES_OK
test -f "$APP/templates/clinics/specialty_guide.html" && echo TEMPLATE_OK
echo DEPLOY_OK
