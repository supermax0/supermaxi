import subprocess
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

python_exe = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
app_file = os.path.join(BASE_DIR, "app.py")

subprocess.Popen([python_exe, app_file], cwd=BASE_DIR)
