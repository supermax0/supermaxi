@echo off
echo ===============================
echo FINORA WINDOWS REPAIR SCRIPT
echo ===============================

cd /d %~dp0

echo.
echo 1 - Checking Python
python --version
if %errorlevel% neq 0 (
    echo Python not found!
    pause
    exit
)

echo.
echo 2 - Checking venv

if exist venv\Scripts\python.exe (
    echo venv exists
) else (
    echo Creating new venv...
    python -m venv venv
)

echo.
echo 3 - Activating venv
call venv\Scripts\activate

echo.
echo 4 - Installing requirements

if exist requirements.txt (
    pip install -r requirements.txt
) else (
    pip install flask gunicorn sqlalchemy pandas openpyxl reportlab
)

echo.
echo 5 - Fixing start_flask paths

powershell -Command "(Get-Content start_flask.py) -replace 'venv/bin/python','venv/Scripts/python.exe' | Set-Content start_flask.py"

echo.
echo 6 - Testing Flask

python start_flask.py

echo.
echo ===============================
echo FINORA REPAIR FINISHED
echo ===============================

pause