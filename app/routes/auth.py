from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, timedelta
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import threading
import hashlib
import secrets
import socket
from werkzeug.security import generate_password_hash
from app import db
from app.models.user import User, RoleEnum
from app.models.ticket import Ticket
from app.models.pending_registration import PendingRegistration
from app.utils.helpers import log_audit
from app import mail

# Blueprint for authentication-related routes
auth_bp = Blueprint('auth', __name__)
STUDENT_EMAIL_DOMAIN = '@dut4life.ac.za'
STAFF_ADMIN_EMAIL_DOMAIN = '@dut.ac.za'


def _default_role_home() -> str:
    if not current_user.is_authenticated:
        return url_for('auth.login')
    if current_user.Role == RoleEnum.Student:
        return url_for('student.dashboard')
    if current_user.Role == RoleEnum.Staff:
        return url_for('staff.dashboard')
    if current_user.Role == RoleEnum.Admin:
        return url_for('admin.dashboard')
    return url_for('auth.index')


@auth_bp.route('/track-ticket')
@login_required
def track_ticket_global():
    ref = request.args.get('ref', '').strip().upper()
    if not ref:
        flash('Enter a tracking reference to search.', 'warning')
        return redirect(request.referrer or _default_role_home())

    ticket = Ticket.query.filter_by(TrackingRef=ref).first()
    if not ticket:
        flash(f'No ticket found for reference {ref}.', 'danger')
        return redirect(request.referrer or _default_role_home())

    if current_user.Role == RoleEnum.Student:
        if ticket.StudentId != current_user.UserId:
            flash('This ticket is not linked to your student account.', 'warning')
            return redirect(url_for('student.dashboard'))
        return redirect(url_for('student.view_ticket', ticket_id=ticket.TicketId))

    if current_user.Role == RoleEnum.Staff:
        if ticket.StaffId != current_user.UserId:
            flash('This ticket is not currently assigned to you.', 'warning')
            return redirect(url_for('staff.dashboard'))
        return redirect(url_for('staff.view_ticket', ticket_id=ticket.TicketId))

    if current_user.Role == RoleEnum.Admin:
        return redirect(url_for('admin.ticket_detail', ticket_id=ticket.TicketId))

    return redirect(_default_role_home())


def _password_requirement_error(password: str):
    if len(password) < 8:
        return 'Password must be at least 8 characters long.'
    if not any(c.isupper() for c in password):
        return 'Password must include at least one uppercase letter.'
    if not any(c.islower() for c in password):
        return 'Password must include at least one lowercase letter.'
    if not any(c.isdigit() for c in password):
        return 'Password must include at least one number.'
    if not any(not c.isalnum() for c in password):
        return 'Password must include at least one special character.'
    return None


def _required_domain_for_role(role: RoleEnum) -> str:
    return STUDENT_EMAIL_DOMAIN if role == RoleEnum.Student else STAFF_ADMIN_EMAIL_DOMAIN


def _email_matches_role_domain(email: str, role: RoleEnum) -> bool:
    return email.endswith(_required_domain_for_role(role))


def _token_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


def _build_reset_token(user: User) -> str:
    # Embed a password hash marker so old reset links become invalid after a password change.
    payload = {'uid': user.UserId, 'phm': user.PasswordHash[-16:]}
    return _token_serializer().dumps(payload, salt='password-reset')


def _resolve_reset_user(token: str):
    max_age = int(current_app.config.get('RESET_TOKEN_TTL_SECONDS', 3600))
    try:
        payload = _token_serializer().loads(token, salt='password-reset', max_age=max_age)
    except SignatureExpired:
        return None, 'This reset link has expired. Please request a new one.'
    except BadSignature:
        return None, 'This reset link is invalid. Please request a new one.'

    user = User.query.get(payload.get('uid'))
    if not user:
        return None, 'This reset link is invalid. Please request a new one.'

    if payload.get('phm') != user.PasswordHash[-16:]:
        return None, 'This reset link is no longer valid. Please request a new one.'

    return user, None


def _send_password_reset_email(user: User, token: str):
    reset_link = url_for('auth.reset_password', token=token, _external=True)
    body = (
        f'Hello {user.FullName},\n\n'
        'We received a request to reset your DUT Grievance Portal password.\n\n'
        f'Reset your password: {reset_link}\n\n'
        f'This link expires in {int(current_app.config.get("RESET_TOKEN_TTL_SECONDS", 3600)) // 60} minutes.\n'
        'If you did not request this, you can ignore this message.\n'
    )
    try:
        if not _smtp_reachable():
            current_app.logger.error(
                'Password reset email not sent: SMTP host is unreachable (%s:%s).',
                current_app.config.get('MAIL_SERVER'),
                current_app.config.get('MAIL_PORT'),
            )
            return

        msg = Message(
            subject='[DUT Grievance Portal] Password Reset Request',
            recipients=[user.Email],
            body=body,
        )
        app_obj = current_app._get_current_object()

        def _send_in_background(app, message, email):
            try:
                with app.app_context():
                    mail.send(message)
            except Exception:
                app.logger.exception('Failed sending password reset email to %s', email)

        threading.Thread(
            target=_send_in_background,
            args=(app_obj, msg, user.Email),
            daemon=True,
        ).start()
    except Exception:
        current_app.logger.exception('Failed sending password reset email to %s', user.Email)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def _build_verification_token(pending: PendingRegistration) -> str:
    payload = {
        'pid': pending.PendingId,
        'thm': pending.VerificationTokenHash[-16:],
        'em': pending.Email,
    }
    return _token_serializer().dumps(payload, salt='email-verify')


def _smtp_reachable() -> bool:
    if bool(current_app.config.get('MAIL_SUPPRESS_SEND', False)):
        return True

    host = (current_app.config.get('MAIL_SERVER') or '').strip()
    port = int(current_app.config.get('MAIL_PORT', 587) or 587)
    if not host:
        return False

    timeout = float(current_app.config.get('MAIL_CONNECT_TIMEOUT_SECONDS', 3))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _send_verification_email(pending: PendingRegistration, token: str):
    verify_link = url_for('auth.verify_email', token=token, _external=True)
    body = (
        f'Hello {pending.FullName},\n\n'
        'Complete your DUT Grievance Portal registration by verifying your email address.\n\n'
        f'Verify your email: {verify_link}\n\n'
        f'This link expires in '
        f'{int(current_app.config.get("EMAIL_VERIFY_TOKEN_TTL_SECONDS", 3600)) // 60} minutes.\n\n'
        'If you did not request this registration, you can ignore this message.\n'
    )
    try:
        if not _smtp_reachable():
            current_app.logger.error(
                'Verification email not sent: SMTP host is unreachable (%s:%s).',
                current_app.config.get('MAIL_SERVER'),
                current_app.config.get('MAIL_PORT'),
            )
            return False

        msg = Message(
            subject='[DUT Grievance Portal] Verify Your Email',
            recipients=[pending.Email],
            body=body,
        )
        app_obj = current_app._get_current_object()

        def _send_in_background(app, message, email):
            try:
                with app.app_context():
                    mail.send(message)
            except Exception:
                app.logger.exception('Failed sending verification email to %s', email)

        threading.Thread(
            target=_send_in_background,
            args=(app_obj, msg, pending.Email),
            daemon=True,
        ).start()
        return True
    except Exception:
        current_app.logger.exception('Failed sending verification email to %s', pending.Email)
        return False


def _issue_pending_verification(full_name: str, email: str, password: str, role: RoleEnum):
    pending = PendingRegistration.query.filter_by(Email=email).first()
    if pending and pending.ConsumedAt is not None:
        db.session.delete(pending)
        db.session.flush()
        pending = None

    raw_secret = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_secret)
    ttl_seconds = int(current_app.config.get('EMAIL_VERIFY_TOKEN_TTL_SECONDS', 3600))
    now = datetime.utcnow()

    if not pending:
        pending = PendingRegistration(
            FullName=full_name,
            Email=email,
            PasswordHash=generate_password_hash(password),
            Role=role,
            POPIAConsent=True,
            POPIAConsentAt=now,
            VerificationTokenHash=token_hash,
            VerificationExpiresAt=now,
        )
        db.session.add(pending)
        db.session.flush()
    else:
        pending.FullName = full_name
        pending.PasswordHash = generate_password_hash(password)
        pending.Role = role
        pending.POPIAConsent = True
        pending.POPIAConsentAt = now
        pending.VerificationTokenHash = token_hash
        pending.ConsumedAt = None

    pending.VerificationExpiresAt = now + timedelta(seconds=ttl_seconds)
    pending.LastVerificationSentAt = now
    db.session.flush()

    token = _build_verification_token(pending)
    sent_ok = _send_verification_email(pending, token)
    return pending, sent_ok


def _resolve_pending_registration(token: str):
    max_age = int(current_app.config.get('EMAIL_VERIFY_TOKEN_TTL_SECONDS', 3600))
    try:
        payload = _token_serializer().loads(token, salt='email-verify', max_age=max_age)
    except SignatureExpired:
        return None, 'This verification link has expired. Please request a new one.'
    except BadSignature:
        return None, 'This verification link is invalid. Please request a new one.'

    pending = PendingRegistration.query.get(payload.get('pid'))
    if not pending:
        return None, 'This verification request no longer exists. Please register again.'
    if pending.ConsumedAt is not None:
        return None, 'This verification link has already been used. Please sign in.'
    if pending.Email != payload.get('em'):
        return None, 'This verification link is invalid. Please request a new one.'
    if payload.get('thm') != pending.VerificationTokenHash[-16:]:
        return None, 'This verification link is no longer valid. Please request a new one.'
    if pending.VerificationExpiresAt < datetime.utcnow():
        return None, 'This verification link has expired. Please request a new one.'
    return pending, None


# Home/index route: redirect authenticated users to their dashboard, otherwise to login
@auth_bp.route('/')
def index():
    # Detect if user session is already authenticated via Flask-Login
    if current_user.is_authenticated:
        # Determine the user's explicit Role Enum property
        role = current_user.Role
        
        # Dispatch user correctly directly to their respective landing dashboards based on role
        if role == RoleEnum.Student:
            return redirect(url_for('student.dashboard'))  # Redirect standard submitters
        elif role == RoleEnum.Staff:
            return redirect(url_for('staff.dashboard'))    # Redirect resolvers
        elif role == RoleEnum.Admin:
            return redirect(url_for('admin.dashboard'))    # Redirect administrators
            
    # Default case when no session exists: Fallback directly to login screen
    return redirect(url_for('auth.login'))  


# Login route: handles GET (show form) and POST (process login)
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Eject already authenticated/signed-in users by pointing them back to the logic mapping above
    if current_user.is_authenticated:
        return redirect(url_for('auth.index')) 

    # Processing authentication attempt form payload
    if request.method == 'POST':
        # Retrieve credentials passed over in the form scope parameters
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        # Execute query looking for an identically-matching email on record 
        user     = User.query.filter_by(Email=email).first()

        # Check if the DB pulled up a user AND if their explicit hashed password check passes
        if user and user.check_password(password):
            # Terminate active attempts for accounts which have been revoked/disabled manually by Admin
            if not user.IsActive:
                flash(
                    'Your account has been deactivated. '
                    'Please contact the administrator for assistance.',
                    'danger'
                )
                # Redisplay the login page with the danger flash above
                return render_template('auth/login.html')

            # Issue Flask-Login persistent credential cookies/header state mappings 
            login_user(user)
            log_audit('user_login', target_type='user', target_id=user.UserId,
                      details=f'{user.Email} [{user.Role.value}]')
            db.session.commit()
            flash('Logged in successfully.', 'success')

            # Legacy users may still need to provide POPIA consent.
            if user.Role == RoleEnum.Student and not user.POPIAConsent:
                return redirect(url_for('auth.popia_consent'))
            
            # Send the authenticated person toward the dashboard distributor 
            return redirect(url_for('auth.index'))
        else:
            # Mask whether identifying the correct email failed or if the password was failed. Provide generic output. 
            flash('Invalid email or password.', 'danger')

    # Base state for rendering form on regular page navigations
    return render_template('auth/login.html')


# Registration route: handles GET (show form) and POST (process registration)
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Intercept new account building action requests 
    if request.method == 'POST':
        # Map raw data fields captured directly from the HTTP POST form structure
        full_name   = request.form.get('full_name', '').strip()
        email       = request.form.get('email', '').strip().lower()
        password    = request.form.get('password', '')
        role_raw    = request.form.get('role', 'Student').strip()
        popia_agree = request.form.get('popia_agree') == '1'

        if not full_name or not email or not password or not role_raw:
            flash('Please complete all required fields.', 'danger')
            return render_template('auth/register.html')

        if role_raw not in RoleEnum.__members__:
            flash('Please choose a valid role.', 'danger')
            return render_template('auth/register.html')

        role = RoleEnum[role_raw]
        required_domain = _required_domain_for_role(role)

        if not _email_matches_role_domain(email, role):
            flash(f'{role.value} registration requires an email ending with {required_domain}.', 'danger')
            return render_template('auth/register.html')

        password_error = _password_requirement_error(password)
        if password_error:
            flash(password_error, 'danger')
            return render_template('auth/register.html')

        if not popia_agree:
            flash('You must accept the POPIA compliance statement to create an account.', 'danger')
            return render_template('auth/register.html')

        # Collision query mapping check ensuring no duplicate emails enter the system
        if User.query.filter_by(Email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html')

        _, sent_ok = _issue_pending_verification(full_name, email, password, role)
        db.session.commit()

        if sent_ok:
            flash(
                'Verification email sent. Please click the link in your inbox to activate your account.',
                'info'
            )
        else:
            flash(
                'Registration saved, but email delivery is currently unavailable. '
                'Please try Resend Verification shortly or contact support.',
                'warning'
            )
        return redirect(url_for('auth.login'))

    # Deliver view-state render configuration for users navigating into the web portal registration area
    return render_template('auth/register.html')


@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    pending, error = _resolve_pending_registration(token)
    if error:
        flash(error, 'danger')
        if 'already been used' in error.lower():
            if current_user.is_authenticated:
                logout_user()
            return redirect(url_for('auth.login'))
        return redirect(url_for('auth.register'))

    if User.query.filter_by(Email=pending.Email).first():
        pending.ConsumedAt = datetime.utcnow()
        db.session.commit()
        flash('This email is already verified. You can sign in now.', 'info')
        return redirect(url_for('auth.login'))

    user = User(
        FullName=pending.FullName,
        Email=pending.Email,
        PasswordHash=pending.PasswordHash,
        Role=pending.Role,
        DepartmentId=None,
        POPIAConsent=bool(pending.POPIAConsent),
        POPIAConsentAt=pending.POPIAConsentAt,
        IsActive=True,
        CreatedAt=datetime.utcnow(),
        UpdatedAt=datetime.utcnow(),
    )
    pending.ConsumedAt = datetime.utcnow()
    db.session.add(user)
    db.session.commit()

    flash('Email verified. Your account is now active and ready to use.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Please provide your email to resend verification.', 'warning')
        return redirect(url_for('auth.register'))

    pending = PendingRegistration.query.filter_by(Email=email).first()
    if not pending or pending.ConsumedAt is not None or User.query.filter_by(Email=email).first():
        flash('If a pending registration exists for that email, a new verification link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    cooldown = int(current_app.config.get('EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS', 60))
    if pending.LastVerificationSentAt and (datetime.utcnow() - pending.LastVerificationSentAt).total_seconds() < cooldown:
        flash('Please wait before requesting another verification email.', 'warning')
        return redirect(url_for('auth.register'))

    raw_secret = secrets.token_urlsafe(32)
    pending.VerificationTokenHash = _hash_token(raw_secret)
    pending.VerificationExpiresAt = datetime.utcnow() + timedelta(
        seconds=int(current_app.config.get('EMAIL_VERIFY_TOKEN_TTL_SECONDS', 3600))
    )
    pending.LastVerificationSentAt = datetime.utcnow()
    db.session.flush()

    token = _build_verification_token(pending)
    sent_ok = _send_verification_email(pending, token)
    db.session.commit()

    if sent_ok:
        flash('Verification email re-sent. Check your inbox.', 'success')
    else:
        flash('Email delivery is currently unavailable. Please try again shortly.', 'warning')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(Email=email).first()
        if user and user.IsActive:
            token = _build_reset_token(user)
            _send_password_reset_email(user, token)

        # Return a generic response to avoid account enumeration.
        flash(
            'If an active account exists for that email, a password reset link has been sent.',
            'info',
        )
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        user_id = current_user.UserId
        user_email = current_user.Email
        logout_user()
        log_audit('user_logout', target_type='user', target_id=user_id,
                  details=f'Auto logout for password reset: {user_email}')
        db.session.commit()
        flash('You were signed out so you can reset your password securely.', 'info')

    user, error = _resolve_reset_user(token)
    if error:
        flash(error, 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', token=token)

        password_error = _password_requirement_error(password)
        if password_error:
            flash(password_error, 'danger')
            return render_template('auth/reset_password.html', token=token)

        user.set_password(password)
        user.UpdatedAt = datetime.utcnow()
        db.session.commit()
        flash('Your password has been reset. You can now sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


# Logout route: logs out the current user
@auth_bp.route('/logout')
@login_required
def logout():
    log_audit('user_logout', target_type='user', target_id=current_user.UserId,
              details=current_user.Email)
    db.session.commit()
    # Invoke native library tool which erases login persistence sessions correctly securely
    logout_user()
    flash('You have been logged out.', 'info')
    
    # Dump back onto main authentication login access landing screen
    return redirect(url_for('auth.login'))


# POPIA consent route: shown to students who have not yet given POPIA consent
@auth_bp.route('/popia-consent', methods=['GET', 'POST'])
@login_required
def popia_consent():
    # Only students need consent; redirect others away
    if current_user.Role != RoleEnum.Student:
        return redirect(url_for('auth.index'))

    # Already consented — skip
    if current_user.POPIAConsent:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        if request.form.get('popia_agree') == '1':
            current_user.POPIAConsent   = True
            current_user.POPIAConsentAt = datetime.utcnow()
            db.session.commit()
            flash('Thank you for confirming your POPIA consent.', 'success')
            return redirect(url_for('auth.index'))
        else:
            flash('You must tick the consent checkbox to proceed.', 'danger')

    return render_template('auth/popia_consent.html')