from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from datetime import datetime
from config import config

db            = SQLAlchemy()
migrate       = Migrate()
login_manager = LoginManager()
csrf          = CSRFProtect()
mail          = Mail()

login_manager.login_view              = 'auth.login'
login_manager.login_message_category  = 'info'


def create_app(config_name=None):
    if not config_name:
        import os
        config_name = os.environ.get('FLASK_CONFIG', 'production')
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    import os
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)

    # ── User loader — required by Flask-Login ─────────────────────────────────
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return User.query.get(int(user_id))

    # ── Context processor ─────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from app.utils.helpers import attachment_url
        from flask_login import current_user

        active_announcements = []
        admin_unread_count   = 0
        user_unread_count    = 0
        pending_actions_count = 0

        if current_user.is_authenticated:
            from app.models.announcement       import Announcement
            from app.models.admin_notification import AdminNotification
            from app.models.user_notification  import UserNotification
            from app.models.escalation import EscalationRequest
            from app.models.reassignment_request import ReassignmentRequest
            from app.models.reopen_request import ReopenRequest

            role = current_user.Role.value

            active_announcements = Announcement.query.filter(
                Announcement.IsActive == True,          # noqa: E712
                Announcement.TargetAudience.in_(['All', role])
            ).order_by(Announcement.CreatedAt.desc()).all()

            if role == 'Admin':
                admin_unread_count = AdminNotification.query.filter_by(
                    IsRead=False
                ).count()
                pending_actions_count = (
                    EscalationRequest.query.filter_by(Status='Pending').count()
                    + ReassignmentRequest.query.filter_by(Status='Pending').count()
                    + ReopenRequest.query.filter_by(Status='Pending').count()
                )

            user_unread_count = UserNotification.query.filter_by(
                UserId=current_user.UserId, IsRead=False
            ).count()

        return {
            'now'                 : datetime.utcnow(),
            'attachment_url'      : attachment_url,
            'active_announcements': active_announcements,
            'admin_unread_count'  : admin_unread_count,
            'user_unread_count'   : user_unread_count,
            'pending_actions_count': pending_actions_count,
            'realtime_enabled'    : bool(app.config.get('REALTIME_ENABLED', True)),
            'poll_interval_ms'    : max(5000, int(app.config.get('POLL_INTERVAL_SECONDS', 10)) * 1000),
            'poll_timeout_ms'     : max(2000, int(app.config.get('POLL_TIMEOUT_SECONDS', 8)) * 1000),
            'poll_max_backoff_ms' : max(10000, int(app.config.get('POLL_MAX_BACKOFF_SECONDS', 30)) * 1000),
        }

    # ── Blueprints ────────────────────────────────────────────────────────────
    from app.routes.auth          import auth_bp
    from app.routes.student       import student_bp
    from app.routes.staff         import staff_bp
    from app.routes.admin         import admin_bp
    from app.routes.notifications import notif_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(staff_bp,   url_prefix='/staff')
    app.register_blueprint(admin_bp,   url_prefix='/admin')
    app.register_blueprint(notif_bp,   url_prefix='/user')

    from app import models  # noqa: F401 — ensure all models are registered

    return app