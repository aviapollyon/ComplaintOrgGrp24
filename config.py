
# Configuration file for Flask application settings
import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present.
# Using an explicit path + override=True ensures the .env in the project
# root is always loaded, even if the app is launched from a different
# working directory, and that its values take precedence over any stale
# environment variables already set in the OS session.
_dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=_dotenv_path, override=True)

# Base directory of the project
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


# Main configuration class for all environments
class Config:
    # Secret key for session management and CSRF protection
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database configuration: use DATABASE_URL if set, otherwise SQLite in instance folder
    _database_url = os.environ.get('DATABASE_URL', '').strip()
    SQLALCHEMY_DATABASE_URI = _database_url or f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'grievance.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # File upload settings
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'app', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB max upload size
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx'}

    # Pagination
    TICKETS_PER_PAGE = 15
    USERS_PER_PAGE   = 20

    # Flask-Mail settings (configure via .env)
    MAIL_SERVER   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
    MAIL_PORT     = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS  = os.environ.get('MAIL_USE_TLS',  'true').lower() == 'true'
    MAIL_DEBUG    = os.environ.get('MAIL_DEBUG', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get(
        'MAIL_DEFAULT_SENDER',
        os.environ.get('MAIL_USERNAME', 'noreply@example.com')
    )
    # Flask-Mail: suppress in development when explicitly set
    MAIL_SUPPRESS_SEND = os.environ.get('MAIL_SUPPRESS_SEND', 'false').lower() == 'true'
    MAIL_CONNECT_TIMEOUT_SECONDS = int(os.environ.get('MAIL_CONNECT_TIMEOUT_SECONDS', 3))

    # Realtime is enabled by default; set REALTIME_ENABLED=false to disable explicitly.
    REALTIME_ENABLED = os.environ.get('REALTIME_ENABLED', 'true').lower() == 'true'
    POLL_INTERVAL_SECONDS = int(os.environ.get('POLL_INTERVAL_SECONDS', 10))
    POLL_TIMEOUT_SECONDS = int(os.environ.get('POLL_TIMEOUT_SECONDS', 8))
    POLL_MAX_BACKOFF_SECONDS = int(os.environ.get('POLL_MAX_BACKOFF_SECONDS', 30))
    POLL_BATCH_LIMIT = int(os.environ.get('POLL_BATCH_LIMIT', 20))
    CHAT_EMAIL_NOTIFY = os.environ.get('CHAT_EMAIL_NOTIFY', 'true').lower() == 'true'
    CHAT_EMAIL_COOLDOWN_SECONDS = int(os.environ.get('CHAT_EMAIL_COOLDOWN_SECONDS', 120))
    CHAT_ONLINE_WINDOW_SECONDS = int(os.environ.get('CHAT_ONLINE_WINDOW_SECONDS', 60))

    # Password reset
    RESET_TOKEN_TTL_SECONDS = int(os.environ.get('RESET_TOKEN_TTL_SECONDS', 3600))
    EMAIL_VERIFY_TOKEN_TTL_SECONDS = int(os.environ.get('EMAIL_VERIFY_TOKEN_TTL_SECONDS', 3600))
    EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS = int(
        os.environ.get('EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS', 60)
    )

    # Background SLA monitor
    SLA_MONITOR_ENABLED = os.environ.get('SLA_MONITOR_ENABLED', 'true').lower() == 'true'
    SLA_MONITOR_INTERVAL_SECONDS = int(os.environ.get('SLA_MONITOR_INTERVAL_SECONDS', 300))
    SLA_EMAIL_ENABLED = os.environ.get('SLA_EMAIL_ENABLED', 'true').lower() == 'false'


# Development environment configuration
class DevelopmentConfig(Config):
    DEBUG = True


# Production environment configuration
class ProductionConfig(Config):
    DEBUG = False


# Dictionary to select configuration by environment name
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}