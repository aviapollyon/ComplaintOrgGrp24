
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
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'grievance.db')}"
    )
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
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get(
        'MAIL_DEFAULT_SENDER',
        os.environ.get('MAIL_USERNAME', 'noreply@example.com')
    )
    # Flask-Mail: only suppress if explicitly set to 'true' in env
    MAIL_SUPPRESS_SEND = os.environ.get('MAIL_SUPPRESS_SEND', 'false').lower() == 'true'


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