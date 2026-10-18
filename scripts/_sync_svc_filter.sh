#!/bin/bash
set -e
APP=/var/www/finora/supermaxi
SRC=/tmp/svc_filter_deploy
cp "$SRC/clinics.js" "$SRC/services.js" "$SRC/visits.js" "$APP/static/clinics/"
cp "$SRC/workspace.html" "$APP/templates/clinics/"
cp "$SRC/service.py" "$APP/modules/clinics/"
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
echo DEPLOY_OK
