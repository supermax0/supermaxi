# نقطة دخول تطبيق الإنتاج (مثلاً: gunicorn wsgi:app)
from app import app

if __name__ == "__main__":
    app.run()
