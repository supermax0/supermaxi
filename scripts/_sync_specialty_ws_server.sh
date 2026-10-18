#!/bin/bash
set -e
APP=/var/www/finora/supermaxi
SRC=/tmp/specialty_ws_deploy
mkdir -p "$APP/static/clinics" "$APP/templates/clinics" "$APP/modules/clinics" "$APP/scripts"
cp "$SRC/doctor-specialty-packs.js" "$APP/static/clinics/"
cp "$SRC/doctor.js" "$APP/static/clinics/"
cp "$SRC/clinics.css" "$APP/static/clinics/"
cp "$SRC/workspace.html" "$APP/templates/clinics/"
cp "$SRC/service_specialties.py" "$APP/modules/clinics/"
cp "$SRC/seed_specialty_visit_templates.py" "$APP/scripts/"
sed -i 's/\r$//' "$APP/scripts/seed_specialty_visit_templates.py"
cd "$APP"
DISABLE_CLINICS_SCHEDULER=1 DISABLE_PUBLISHER_SCHEDULER=1 FINORA_DISABLE_SCHEDULERS=1 \
  ./venv/bin/python scripts/seed_specialty_visit_templates.py --slug ahnouri
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
ls -la "$APP/static/clinics/doctor-specialty-packs.js"
ls -la "$APP/static/clinics/doctor.js"
echo DEPLOY_OK
