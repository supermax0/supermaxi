#!/bin/bash
set -e
APP=/var/www/finora/supermaxi
SRC=/tmp/appt_spec_deploy
cp "$SRC/clinics.js" "$SRC/clinics.css" "$APP/static/clinics/"
cp "$SRC/workspace.html" "$APP/templates/clinics/"
systemctl restart supermaxi
sleep 2
systemctl is-active supermaxi
echo DEPLOY_OK
