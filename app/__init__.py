from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from datetime import datetime
from config import config

# ── EXTENSIONS & GLOBALS ──────────────────────────────────────────────────────
# Initialize Flask extensions globally but unbound to any specific app instance yet. 
# This architectural pattern (Application Factory) prevents circular imports and 
# allows creating multiple app instances (e.g., for testing).

# Handle database ORM (Object-Relational Mapping) interactions globally 
db            = SQLAlchemy()
# Handle database schema migrations (Alembic transitions) globally
migrate       = Migrate()
# Manage user authentication/session state tracking out of the box 
login_manager = LoginManager()
# Provide global Cross-Site Request Forgery security validation to all internal POST forms
csrf          = CSRFProtect()

# Configure the authentication redirect rules
# If a @login_required route is accessed without an active session, kick the user here
login_manager.login_view             = 'auth.login'
# The flash message severity category to use when rejecting access ('info' renders out blue usually)
login_manager.login_message_category = 'info'


# ── APPLICATION FACTORY ───────────────────────────────────────────────────────
def create_app(config_name='default'):
    """
    Core application factory generating the initialized Flask application instance.
    Loads settings, binds plugins, ensures necessary folder structures exist, 
    and registers all modular blueprints.
    """
    # Instantiate the Flask web application object 
    # Enable instance_relative_config so it inherently knows to look for instance/ local database structures 
    app = Flask(__name__, instance_relative_config=True)
    
    # Load standardized configuration classes dynamically using the mapping dictionary supplied in config.py
    app.config.from_object(config[config_name])

    import os
    # Dynamically verify and generate internal structural directories
    # `exist_ok=True` gracefully ignores the command if the folder already exists
    os.makedirs(app.instance_path, exist_ok=True)           # Internal DBs, isolated local secrets 
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) # Explicit file directory serving user static uploads

    # Bind the previously unassigned global extensions physically into this specific newly launched app object
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # ── CONTEXT PROCESSORS ────────────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        """
        Calculates and maps dynamic variables forcefully into every single rendered Jinja2 HTML template.
        Because this runs globally, the variables dumped structurally here are accessible on all pages.
        """
        # Import lazily (at runtime rather than top level) to avoid application circular imports
        from app.utils.helpers import attachment_url
        from flask_login import current_user

        # Initialize default empty payload capturing broadcast communications
        active_announcements = []
        
        # Only query for broadcasts if the user navigating the site is actively signed in 
        if current_user.is_authenticated:
            # Need to lazily import Announcement model so application factory bounds resolve properly
            from app.models.announcement import Announcement
            # Snag string-valued Enum output representing Role type ('Student', 'Staff', etc)
            role = current_user.Role.value
            
            # Fetch DB elements filtering explicitly by matching target bounds mapped to either global 'All' or specific role matching 
            active_announcements = Announcement.query.filter(
                Announcement.IsActive == True,  # noqa: E712
                # Targeting clause determining whether user visually sees the notification banner
                Announcement.TargetAudience.in_(['All', role])
            ).order_by(Announcement.CreatedAt.desc()).all()

        # Output payload dictionary packaging everything sent to Jinja Templates globally
        return {
            'now'                  : datetime.utcnow(),    # Synchronized global UTC time injected continuously
            'attachment_url'       : attachment_url,       # Utility translating raw paths safely for endpoints
            'active_announcements' : active_announcements, # Populated alerts ready for macro consumption
        }

    # ── BLUEPRINT REGISTRATION ────────────────────────────────────────────────
    # Map component-based routed logic blocks back onto the central server application
    from app.routes.auth    import auth_bp
    from app.routes.student import student_bp
    from app.routes.staff   import staff_bp
    from app.routes.admin   import admin_bp

    # Auth sits at the base root natively 
    app.register_blueprint(auth_bp)
    
    # Components use path-prefix mappings pushing sub-logic domains natively into explicit URI namespace folders
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(staff_bp,   url_prefix='/staff')
    app.register_blueprint(admin_bp,   url_prefix='/admin')

    # Lazily pre-load absolute models into namespace implicitly aiding Alembic finding tracked db tables initially 
    from app import models  # noqa: F401

    # End execution yielding completely populated, routing-mapped Flask instance to runtime launcher (`run.py`)
    return app