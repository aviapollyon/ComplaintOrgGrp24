from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from datetime import datetime
from config import config

db            = SQLAlchemy()
migrate       = Migrate()
login_manager = LoginManager()
csrf          = CSRFProtect()

login_manager.login_view             = 'auth.login'
login_manager.login_message_category = 'info'


def create_app(config_name='default'):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    import os
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    @app.context_processor
    def inject_globals():
        from app.utils.helpers import attachment_url
        return {
            'now'            : datetime.utcnow(),
            'attachment_url' : attachment_url,
        }

    from app.routes.auth    import auth_bp
    from app.routes.student import student_bp
    from app.routes.staff   import staff_bp
    from app.routes.admin   import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(staff_bp,   url_prefix='/staff')
    app.register_blueprint(admin_bp,   url_prefix='/admin')

    from app import models  # noqa: F401

    return app