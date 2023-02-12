from flask_cors import CORS
from opencdms_api.pygeoapi.app import BLUEPRINT as pygeoapi_blueprint
from opencdms_api.app import get_app
from flask_admin import Admin
from opencdms_api.admin import views as admin_views
from opencdms_api.db import db


app = get_app()
CORS(app)

with app.app_context():
    db.init_app(app)
    db.create_all()


app.register_blueprint(pygeoapi_blueprint, url_prefix="/oapi")
admin = Admin(app, name="OpenCDMS Admin Panel", template_mode="bootstrap3")

for view in admin_views:
    admin.add_views(view)
