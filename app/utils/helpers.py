import os
from flask import current_app, url_for

CATEGORY_PRIORITY_MAP = {
    'Academic'       : 'High',
    'Financial'      : 'High',
    'Facilities'     : 'Medium',
    'IT Support'     : 'Medium',
    'Accommodation'  : 'Medium',
    'Administration' : 'Low',
    'Other'          : 'Low',
}

TICKET_CATEGORIES = list(CATEGORY_PRIORITY_MAP.keys())

CATEGORY_DEPARTMENT_MAP = {
    'Academic'       : 'Academic Affairs',
    'Financial'      : 'Finance & Accounts',
    'Facilities'     : 'Facilities Management',
    'IT Support'     : 'Information Technology',
    'Accommodation'  : 'Student Housing',
    'Administration' : 'Student Administration',
    'Other'          : 'Student Administration',
}


def get_priority_for_category(category: str) -> str:
    return CATEGORY_PRIORITY_MAP.get(category, 'Medium')


def get_department_name_for_category(category: str) -> str:
    return CATEGORY_DEPARTMENT_MAP.get(category, 'Student Administration')


def allowed_file(filename: str) -> bool:
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', set())
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def save_uploaded_file(file, ticket_id: int) -> tuple[str, str]:
    from werkzeug.utils import secure_filename
    filename  = secure_filename(file.filename)
    ticket_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], str(ticket_id))
    os.makedirs(ticket_dir, exist_ok=True)
    filepath = os.path.join(ticket_dir, filename)
    file.save(filepath)
    return filename, filepath


def attachment_url(attachment) -> str:
    """
    Return a URL that serves the attachment file.
    Strips the UPLOAD_FOLDER prefix so the path is relative to the upload root.
    """
    upload_root = current_app.config['UPLOAD_FOLDER']
    rel_path    = os.path.relpath(attachment.FilePath, upload_root)
    # Normalise to forward slashes for URL building
    rel_path    = rel_path.replace(os.sep, '/')
    return url_for('student.serve_upload', filepath=rel_path)