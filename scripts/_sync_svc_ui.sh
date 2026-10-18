#!/bin/bash
set -e
APP=/var/www/finora/supermaxi
SRC=/tmp/svc_ui_deploy
cp "$SRC/services.js" "$SRC/clinics.css" "$APP/static/clinics/"
cp "$SRC/workspace.html" "$APP/templates/clinics/"
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
echo DEPLOY_OK
