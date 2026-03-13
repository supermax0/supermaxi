from flask import Flask

from extensions import db
from config import DevelopmentConfig, ProductionConfig
from routes.publish_api import publish_api_bp
from routes.publish_ui import publish_ui_bp

import os


_env = (os.environ.get("FLASK_ENV") or "development").lower()

app = Flask(__name__)
app.config.from_object(ProductionConfig if _env == "production" else DevelopmentConfig)

db.init_app(app)

app.register_blueprint(publish_api_bp)
app.register_blueprint(publish_ui_bp)


if __name__ == "__main__":
  host = os.environ.get("FLASK_HOST", "0.0.0.0")
  port = int(os.environ.get("FLASK_PORT", "5010"))
  debug = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")
  app.run(host=host, port=port, debug=debug)

