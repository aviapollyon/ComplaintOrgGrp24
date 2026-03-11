import os
from flask import current_app, url_for, request as _flask_request

# ── Category → SubCategories ──────────────────────────────────────────────────
CATEGORY_SUBCATEGORY_MAP: dict[str, list[str]] = {
    'Academic': [
        'Module Result / Mark',
        'Lecturer Conduct',
        'Course Material',
        'Timetable Issue',
        'Attendance',
        'Academic Appeals',
        'Other Academic',
    ],
    'Financial': [
        'NSFAS Allowance',
        'NSFAS Registration',
        'Fee Account Error',
        'Refund Request',
        'Bursary Payment',
        'Other Financial',
    ],
    'Examination': [
        'Timetable Clash',
        'Venue Issue',
        'Deferred Exam',
        'Supplementary Exam',
        'Aegrotat Application',
        'Results Query',
        'Other Examination',
    ],
    'Bursary & Funding': [
        'External Bursary',
        'DUT Scholarship',
        'Funding Allocation',
        'Funding Confirmation',
        'Other Bursary',
    ],
    'Registration': [
        'Module Add / Drop',
        'Registration Block',
        'Curriculum Change',
        'Late Registration',
        'Other Registration',
    ],
    'Facilities': [
        'Broken Equipment',
        'Maintenance Request',
        'Cleaning / Hygiene',
        'Electricity / Lighting',
        'Water Supply',
        'Heating / Cooling',
        'Other Facilities',
    ],
    'IT Support': [
        'Wi-Fi / Internet',
        'Student Email',
        'Blackboard / LMS',
        'Student Portal',
        'Computer Lab',
        'Printing',
        'Password / Access',
        'Other IT',
    ],
    'Accommodation': [
        'Room Transfer',
        'Maintenance / Repairs',
        'Noise Complaint',
        'Key / Lock Issue',
        'Water / Utilities',
        'Roommate Conflict',
        'Other Accommodation',
    ],
    'Health & Wellness': [
        'Counselling Referral',
        'Medical Assistance',
        'Mental Health Support',
        'Disability Support',
        'Other Health',
    ],
    'Library': [
        'Book / Resource Access',
        'Overdue Fine',
        'Printing Credits',
        'Database Access',
        'Other Library',
    ],
    'Transport': [
        'Shuttle / Bus',
        'Parking',
        'Route / Schedule',
        'Other Transport',
    ],
    'Administration': [
        'Transcript / Certificate',
        'Name / Record Change',
        'Proof of Registration',
        'Student Card',
        'Other Administration',
    ],
    'Student Conduct': [
        'Harassment',
        'Discrimination',
        'Bullying',
        'Academic Misconduct',
        'Other Conduct',
    ],
    'Other': [
        'General Enquiry',
        'Suggestion',
        'Other',
    ],
}

TICKET_CATEGORIES = list(CATEGORY_SUBCATEGORY_MAP.keys())

# ── Category → Priority ───────────────────────────────────────────────────────
CATEGORY_PRIORITY_MAP: dict[str, str] = {
    'Academic'          : 'High',
    'Financial'         : 'High',
    'Examination'       : 'High',
    'Bursary & Funding' : 'High',
    'Registration'      : 'High',
    'Facilities'        : 'Medium',
    'IT Support'        : 'Medium',
    'Accommodation'     : 'Medium',
    'Health & Wellness' : 'Medium',
    'Library'           : 'Low',
    'Transport'         : 'Low',
    'Administration'    : 'Low',
    'Student Conduct'   : 'Low',
    'Other'             : 'Low',
}

# ── Category → Department ─────────────────────────────────────────────────────
CATEGORY_DEPARTMENT_MAP: dict[str, str] = {
    'Academic'          : 'Academic Affairs',
    'Financial'         : 'Finance & Accounts',
    'Examination'       : 'Academic Affairs',
    'Bursary & Funding' : 'Finance & Accounts',
    'Registration'      : 'Student Administration',
    'Facilities'        : 'Facilities Management',
    'IT Support'        : 'Information Technology',
    'Accommodation'     : 'Student Housing',
    'Health & Wellness' : 'Student Administration',
    'Library'           : 'Information Technology',
    'Transport'         : 'Facilities Management',
    'Administration'    : 'Student Administration',
    'Student Conduct'   : 'Student Administration',
    'Other'             : 'Student Administration',
}

# ── Keyword flagging ──────────────────────────────────────────────────────────
FLAG_THRESHOLD = 3

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    'Academic'          : ['result', 'mark', 'grade', 'module', 'lecturer',
                           'attendance', 'timetable', 'syllabus', 'fail'],
    'Financial'         : ['nsfas', 'fee', 'payment', 'invoice', 'statement',
                           'debit', 'charge', 'refund', 'allowance'],
    'Examination'       : ['exam', 'timetable', 'venue', 'clash', 'supplementary',
                           'deferred', 'aegrotat', 'results'],
    'Bursary & Funding' : ['bursary', 'scholarship', 'sponsor', 'funding',
                           'allocation', 'confirmation'],
    'Registration'      : ['register', 'registration', 'module', 'add', 'drop',
                           'curriculum', 'blocked', 'outstanding'],
    'Facilities'        : ['broken', 'maintenance', 'repair', 'toilet', 'water',
                           'electricity', 'lift', 'elevator', 'cleaning',
                           'air conditioning', 'heating'],
    'IT Support'        : ['wifi', 'wi-fi', 'internet', 'blackboard', 'email',
                           'password', 'login', 'access', 'laptop', 'printer',
                           'lab', 'portal', 'system'],
    'Accommodation'     : ['room', 'residence', 'noise', 'roommate', 'transfer',
                           'water', 'hot water', 'keys', 'lock', 'maintenance'],
    'Health & Wellness' : ['sick', 'mental health', 'counselling', 'injury',
                           'clinic', 'doctor', 'medication'],
    'Library'           : ['book', 'overdue', 'fine', 'printing', 'credit',
                           'resource', 'access', 'database'],
    'Transport'         : ['bus', 'shuttle', 'parking', 'route', 'schedule'],
    'Administration'    : ['transcript', 'certificate', 'letter', 'proof',
                           'document', 'record', 'id', 'name change'],
    'Student Conduct'   : ['harassment', 'bullying', 'discrimination', 'misconduct',
                           'complaint', 'code of conduct'],
    'Other'             : [],
}


def get_priority_for_category(category: str) -> str:
    return CATEGORY_PRIORITY_MAP.get(category, 'Medium')


def get_department_name_for_category(category: str) -> str:
    return CATEGORY_DEPARTMENT_MAP.get(category, 'Student Administration')


def get_subcategories_for_category(category: str) -> list[str]:
    return CATEGORY_SUBCATEGORY_MAP.get(category, ['Other'])


def allowed_file(filename: str) -> bool:
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', set())
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def save_uploaded_file(file, subfolder: str) -> tuple[str, str]:
    from app.services.storage import save_file
    return save_file(file, subfolder)


def attachment_url(attachment) -> str:
    if attachment.FilePath.startswith(('http://', 'https://')):
        return attachment.FilePath
    upload_root = current_app.config['UPLOAD_FOLDER']
    rel_path    = os.path.relpath(attachment.FilePath, upload_root)
    rel_path    = rel_path.replace(os.sep, '/')
    return url_for('student.serve_upload', filepath=rel_path)


def extract_keywords(text: str, category: str) -> list[str]:
    keywords   = CATEGORY_KEYWORDS.get(category, [])
    text_lower = text.lower()
    return [kw for kw in keywords if kw in text_lower]


def check_and_raise_flags(ticket) -> None:
    from app import db
    from app.models.ticket import Ticket
    from app.models.ticket_flag import TicketFlag, FlaggedTicket
    from app.models.admin_notification import AdminNotification

    combined  = f'{ticket.Title} {ticket.Description}'
    matched   = extract_keywords(combined, ticket.Category)

    for kw in matched:
        similar = Ticket.query.filter(
            Ticket.Category  == ticket.Category,
            Ticket.TicketId  != ticket.TicketId,
            (Ticket.Title.ilike(f'%{kw}%') |
             Ticket.Description.ilike(f'%{kw}%'))
        ).all()

        total_count = len(similar) + 1

        if total_count >= FLAG_THRESHOLD:
            existing = TicketFlag.query.filter_by(
                Category=ticket.Category,
                Keyword=kw,
                Status='active'
            ).first()

            if existing:
                existing.TicketCount = total_count
                already = FlaggedTicket.query.filter_by(
                    FlagId=existing.FlagId,
                    TicketId=ticket.TicketId
                ).first()
                if not already:
                    db.session.add(FlaggedTicket(
                        FlagId=existing.FlagId,
                        TicketId=ticket.TicketId
                    ))
            else:
                new_flag = TicketFlag(
                    Category=ticket.Category, Keyword=kw,
                    TicketCount=total_count, Status='active',
                )
                db.session.add(new_flag)
                db.session.flush()
                for t in similar + [ticket]:
                    db.session.add(FlaggedTicket(
                        FlagId=new_flag.FlagId,
                        TicketId=t.TicketId
                    ))
                db.session.add(AdminNotification(
                    Type    = 'recurring_issue',
                    Message = (
                        f'Recurring issue flagged: {total_count} tickets in category '
                        f'"{ticket.Category}" → subcategory concern around keyword '
                        f'"{kw}". This may indicate a systemic problem requiring attention.'
                    ),
                    TicketId = ticket.TicketId,
                    IsRead   = False,
                ))

def log_audit(action: str, target_type: str = None, target_id: int = None,
              details: str = None) -> None:
    """Record an administrative action in the audit log.
    Must be called within a request context; the db.session.commit() is
    left to the caller so it can be batched with other writes.
    """
    from app.models.audit_log import AuditLog
    from app import db
    from flask_login import current_user

    try:
        actor_id = current_user.UserId if current_user.is_authenticated else None
    except Exception:
        actor_id = None

    try:
        ip = _flask_request.remote_addr
    except Exception:
        ip = None

    entry = AuditLog(
        ActorId    = actor_id,
        Action     = action,
        TargetType = target_type,
        TargetId   = target_id,
        Details    = details,
        IPAddress  = ip,
    )
    db.session.add(entry)