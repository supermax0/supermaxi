#!/bin/bash
set -euo pipefail
APP=/var/www/finora/supermaxi
cd "$APP"
export DISABLE_CLINICS_SCHEDULER=1
export DISABLE_PUBLISHER_SCHEDULER=1
export FINORA_DISABLE_SCHEDULERS=1
./venv/bin/python scripts/provision_dental_clinic.py \
  --slug ghadeer \
  --name "عيادة د. غدير للأسنان" \
  --owner "د. غدير" \
  --doctor-name "د. غدير" \
  --password "Ghadeer@Admin2026" \
  --doctor-password "Ghadeer@Doctor2026" \
  --reception-password "Ghadeer@Rec2026" \
  --trial-days 90
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
echo PROVISION_OK
