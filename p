Create a button called "Fix All" in Finora Deploy Studio.

When the user clicks the button, the program must execute a full automatic repair
and deployment pipeline for a Flask + Gunicorn + Nginx server.

The tool already has these configuration fields:
- Server SSH (user@host)
- Server password
- Server project path
- Nginx service name
- Gunicorn bind
- Workers

Use those values dynamically.

When the button is clicked, the application must connect to the server via SSH
and run the following commands in order:

1) Navigate to the project directory
cd {SERVER_PROJECT_PATH}

2) Mark repository as safe
git config --global --add safe.directory {SERVER_PROJECT_PATH}

3) Update project from GitHub
git fetch origin
git reset --hard origin/main

4) Activate virtual environment if it exists
if [ -d "venv" ]; then source venv/bin/activate; fi

5) Install dependencies
if [ -f "requirements.txt" ]; then pip install -r requirements.txt; fi

6) Clean python cache
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} +

7) Clean static cache
rm -rf static/build || true

8) Kill old gunicorn processes
pkill -9 gunicorn || true
fuser -k 8000/tcp || true

9) Restart application service
systemctl restart finora

10) Restart nginx
systemctl restart {NGINX_SERVICE_NAME}

11) Check service status
systemctl status finora --no-pager

12) Verify gunicorn port
lsof -i :8000

The output of each command must be displayed live in the Terminal/Log Output panel.

If any command fails:
- capture the error
- attempt one automatic retry
- continue execution

When the process completes successfully,
display:

"System repaired and deployment completed successfully."

The Fix All button should therefore:
- update code
- repair git issues
- clean cache
- restart gunicorn
- restart nginx
- verify port status
- show logs in the terminal window