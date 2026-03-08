
# Configuration file for Flask application settings
import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

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