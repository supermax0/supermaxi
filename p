You are a senior DevOps engineer.

Create a FULL production deployment script for a Flask SaaS project.

Project details:

Project path:
/var/www/finora/supermaxi

Stack:
Flask
Gunicorn
Python venv
Systemd service
Git

The script must be named:

deploy.sh

Goals of the script:

1. Pull latest code from Git
2. Activate virtual environment
3. Install new dependencies if requirements.txt changed
4. Run database migrations if they exist
5. Safely restart the application
6. Ensure port conflicts are cleaned
7. Log deployment output

Requirements:

The script must:

- Stop existing gunicorn processes safely
- Kill anything using port 8000
- Pull latest git code
- Activate the venv
- Install dependencies
- Restart systemd service "supermaxi"
- If service not running, start gunicorn manually

Use this configuration:

APP_DIR=/var/www/finora/supermaxi
VENV=$APP_DIR/venv
SERVICE=supermaxi
PORT=8000

Add colored console output for steps.

Example steps:

[1] Updating repository
[2] Installing dependencies
[3] Restarting service
[4] Deployment completed

Also create a log file:

/var/log/supermaxi_deploy.log

The script must be safe to run multiple times.

Add error handling.

After writing the script, also output the commands needed to:

- make the script executable
- run the script