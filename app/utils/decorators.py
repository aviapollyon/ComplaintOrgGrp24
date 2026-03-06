from functools import wraps
from flask import abort
from flask_login import current_user
from app.models.user import RoleEnum


def role_required(*roles):
    """Decorator to restrict route access by user role."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.Role.value not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator