import os
from flask import Flask


def get_app():
    app = Flask(__name__)

    app.config["FLASK_ADMIN_SWATCH"] = "flatly"
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("POSTGRES_DSN")
    app.url_map.strict_slashes = False

    return app
