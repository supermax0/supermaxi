import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

print("Attempting to import app components...")

try:
    from extensions import db
    print("Extensions imported successfully.")
except Exception as e:
    print(f"FAILED to import extensions: {e}")

try:
    import routes.index
    print("Index route imported successfully.")
except Exception as e:
    print(f"FAILED to import index route: {e}")

try:
    import routes.superadmin
    print("Superadmin route imported successfully.")
except Exception as e:
    print(f"FAILED to import superadmin route: {e}")

try:
    from app import app
    print("App instance created successfully.")
except Exception as e:
    import traceback
    print(f"FAILED to create app instance: {e}")
    traceback.print_exc()

print("Diagnostic finished.")
