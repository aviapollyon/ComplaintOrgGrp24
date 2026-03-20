import logging
import socket
import threading
import time

from flask import has_request_context, url_for

from app import db
from app.models.user_notification import UserNotification
from app.models.user import User, RoleEnum
from app.services.realtime import publish_user_event

logger = logging.getLogger(__name__)

_smtp_probe_lock = threading.Lock()
_smtp_probe_state = {
    'checked_at': 0.0,
    'is_reachable': None,
    'last_unreachable_warning_at': 0.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def notify(user_id: int, title: str, message: str,
           notif_type: str = 'general', ticket_id: int = None):
    notification = UserNotification(
        UserId   = user_id,
        Title    = title,
        Message  = message,
        Type     = notif_type,
        IsRead   = False,
        TicketId = ticket_id,
    )
    db.session.add(notification)
    publish_user_event(
        user_id,
        'notification',
        {
            'title': title,
            'message': message,
            'type': notif_type,
            'ticket_id': ticket_id,
            'ticket_link': _ticket_link_for_user(user_id, ticket_id) if ticket_id else None,
        },
    )


def _ticket_link_for_user(user_id: int, ticket_id: int) -> str:
    if not ticket_id:
        return ''

    # Seeding and background work may run with an app context but no request context.
    # In that case Flask cannot build endpoint URLs unless SERVER_NAME is configured.
    if not has_request_context():
        return ''

    user = User.query.get(user_id)
    if not user:
        return ''

    if user.Role == RoleEnum.Student:
        return url_for('student.view_ticket', ticket_id=ticket_id, _external=True)
    if user.Role == RoleEnum.Staff:
        return url_for('staff.view_ticket', ticket_id=ticket_id, _external=True)
    if user.Role == RoleEnum.Admin:
        return url_for('admin.ticket_detail', ticket_id=ticket_id, _external=True)
    return ''


def _dashboard_link_for_user(user_id: int) -> str:
    if not has_request_context():
        return ''

    user = User.query.get(user_id)
    if not user:
        return ''

    if user.Role == RoleEnum.Student:
        return url_for('student.dashboard', _external=True)
    if user.Role == RoleEnum.Staff:
        return url_for('staff.dashboard', _external=True)
    if user.Role == RoleEnum.Admin:
        return url_for('admin.dashboard', _external=True)
    return ''


def _email_body_with_link(message: str, user_id: int, ticket_id: int = None, action_text: str = 'Open link'):
    target = _ticket_link_for_user(user_id, ticket_id) if ticket_id else ''
    if not target:
        target = _dashboard_link_for_user(user_id)
    if not target:
        return message
    return f'{message}\n\n{action_text}: {target}'


def _notification_exists(user_id: int, notif_type: str, ticket_id: int) -> bool:
    return db.session.query(UserNotification.NotificationId).filter_by(
        UserId=user_id,
        Type=notif_type,
        TicketId=ticket_id,
    ).first() is not None


def _smtp_reachable() -> bool:
    from flask import current_app

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


def _smtp_reachable_cached() -> bool:
    from flask import current_app

    now = time.monotonic()
    probe_interval = float(current_app.config.get('MAIL_REACHABILITY_CACHE_SECONDS', 60))
    warning_cooldown = float(current_app.config.get('MAIL_UNREACHABLE_LOG_COOLDOWN_SECONDS', 300))

    with _smtp_probe_lock:
        cached = _smtp_probe_state['is_reachable']
        checked_at = _smtp_probe_state['checked_at']
        needs_probe = cached is None or (now - checked_at) >= probe_interval

    if needs_probe:
        is_reachable = _smtp_reachable()
        with _smtp_probe_lock:
            _smtp_probe_state['is_reachable'] = is_reachable
            _smtp_probe_state['checked_at'] = now
    else:
        is_reachable = bool(cached)

    if not is_reachable:
        with _smtp_probe_lock:
            last_warning_at = _smtp_probe_state['last_unreachable_warning_at']
            should_warn = (now - last_warning_at) >= warning_cooldown
            if should_warn:
                _smtp_probe_state['last_unreachable_warning_at'] = now

        if should_warn:
            logger.warning(
                '[EMAIL SKIPPED] SMTP host is unreachable (%s:%s). '
                'Skipping outbound email until connectivity recovers.',
                current_app.config.get('MAIL_SERVER'),
                current_app.config.get('MAIL_PORT'),
            )

    return is_reachable


def _send_email(recipient_email: str, subject: str, body: str):
    """
    Build a plain-text email and send it synchronously.
    Silently skips if the recipient address is empty.
    Logs a warning if MAIL_USERNAME is not configured.
    Logs an error (visible in Flask logs) if sending fails.
    """
    if not recipient_email or '@' not in recipient_email:
        return
    try:
        from flask import current_app
        from flask_mail import Message
        from app import mail

        if not _smtp_reachable_cached():
            return

        mail_username = current_app.config.get('MAIL_USERNAME', '')
        if not mail_username:
            logger.warning(
                '[EMAIL SKIPPED] MAIL_USERNAME is not configured. '
                'Set MAIL_USERNAME and MAIL_PASSWORD in your .env file to enable email.'
            )
            return

        msg = Message(
            subject    = f'[DUT Grievance Portal] {subject}',
            recipients = [recipient_email],
            body       = body,
        )

        app_obj = current_app._get_current_object()

        def _send_in_background(app, message, email_to, email_subject):
            try:
                with app.app_context():
                    mail.send(message)
                logger.info('[EMAIL SENT] To: %s | Subject: %s', email_to, email_subject)
            except Exception as bg_exc:
                logger.error(
                    '[EMAIL ERROR] Failed to send to %s | Subject: %s | Error: %s',
                    email_to, email_subject, bg_exc, exc_info=True
                )

        t = threading.Thread(
            target=_send_in_background,
            args=(app_obj, msg, recipient_email, subject),
            daemon=True,
        )
        t.start()
    except Exception as exc:
        logger.error(
            '[EMAIL ERROR] Failed to send to %s | Subject: %s | Error: %s',
            recipient_email, subject, exc, exc_info=True
        )


def _get_user_email(user_id: int) -> str:
    """Safely fetch a user's email. Returns '' if not found."""
    try:
        from app.models.user import User
        user = User.query.get(user_id)
        return (user.Email or '') if user else ''
    except Exception:  # noqa: BLE001
        return ''


def _send_admin_emails(subject: str, body: str):
    """Send an email to every active Admin user."""
    try:
        from app.models.user import User, RoleEnum
        admins = User.query.filter_by(Role=RoleEnum.Admin, IsActive=True).all()
        for admin in admins:
            if admin.Email:
                _send_email(admin.Email, subject, body)
    except Exception as exc:  # noqa: BLE001
        logger.error('[ADMIN EMAIL ERROR] %s', exc, exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# Public notification functions
# ─────────────────────────────────────────────────────────────────────────────

def notify_ticket_submitted(ticket):
    """Confirm submission to the student with their unique tracking reference."""
    ref = ticket.TrackingRef or f'#{ticket.TicketId}'
    title   = f'Complaint Submitted — Ref: {ref}'
    message = (f'Your complaint "{ticket.Title}" has been received and is '
               f'being reviewed. Your tracking reference is {ref}. '
               f'Keep this reference for all follow-up enquiries.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'ticket_submitted',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View your ticket'),
    )


def notify_ticket_assigned(ticket):
    if ticket.StaffId:
        title   = f'New Ticket Assigned — #{ticket.TicketId}'
        message = f'Ticket "{ticket.Title}" has been assigned to you.'
        notify(
            user_id    = ticket.StaffId,
            title      = title,
            message    = message,
            notif_type = 'ticket_assigned',
            ticket_id  = ticket.TicketId,
        )
        _send_email(
            _get_user_email(ticket.StaffId),
            title,
            _email_body_with_link(message, ticket.StaffId, ticket.TicketId, 'Open assigned ticket'),
        )


def notify_status_update(ticket, changed_by_user):
    ref     = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    title   = f'Ticket #{ticket.TicketId} Updated'
    message = (f'Your ticket "{ticket.Title}"{ref} status changed to '
               f'"{ticket.Status.value}" by {changed_by_user.FullName}.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View update'),
    )


def notify_staff_reply(ticket, staff_user):
    ref     = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    title   = f'Staff Replied — Ticket #{ticket.TicketId}'
    message = (f'{staff_user.FullName} sent you a message on '
               f'ticket "{ticket.Title}"{ref}. Please check and reply.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'new_reply',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View and reply'),
    )


def notify_student_replied(ticket, student_user):
    if ticket.StaffId:
        title   = f'Student Replied — Ticket #{ticket.TicketId}'
        message = (f'{student_user.FullName} replied to your message on '
                   f'ticket "{ticket.Title}".')
        notify(
            user_id    = ticket.StaffId,
            title      = title,
            message    = message,
            notif_type = 'reply_received',
            ticket_id  = ticket.TicketId,
        )
        _send_email(
            _get_user_email(ticket.StaffId),
            title,
            _email_body_with_link(message, ticket.StaffId, ticket.TicketId, 'View student reply'),
        )


def notify_ticket_resolved(ticket, staff_user):
    ref     = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    title   = f'Ticket #{ticket.TicketId} Resolved'
    message = (f'Your ticket "{ticket.Title}"{ref} has been resolved by '
               f'{staff_user.FullName}. Please leave your feedback.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'ticket_resolved',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'Rate this ticket'),
    )


def notify_ticket_rejected(ticket, actor):
    ref     = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    title   = f'Ticket #{ticket.TicketId} Rejected'
    message = (f'Your ticket "{ticket.Title}"{ref} has been rejected by {actor.FullName}.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'ticket_rejected',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View details'),
    )


def notify_progress_update(ticket, staff_user):
    ref     = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    title   = f'Progress Update — Ticket #{ticket.TicketId}'
    message = (f'{staff_user.FullName} posted a progress update on '
               f'ticket "{ticket.Title}"{ref}.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View progress update'),
    )


def notify_sla_breach(ticket, breach_type: str):
    """Notify assigned staff and all admins when SLA thresholds are exceeded."""
    from flask import current_app
    from app.models.user import User, RoleEnum

    if breach_type not in ('first_response', 'resolution'):
        return

    if breach_type == 'first_response':
        notif_type = 'sla_first_response_breach'
        label = 'First Response (24h)'
    else:
        notif_type = 'sla_resolution_breach'
        label = 'Resolution (48h)'

    title = f'SLA Breach: {label} — Ticket #{ticket.TicketId}'
    message = (
        f'Ticket "{ticket.Title}" exceeded the {label} SLA threshold. '
        f'Reference: {ticket.TrackingRef or "N/A"}.'
    )
    send_sla_email = current_app.config.get('SLA_EMAIL_ENABLED', True)

    if ticket.StaffId and not _notification_exists(ticket.StaffId, notif_type, ticket.TicketId):
        notify(ticket.StaffId, title, message, notif_type, ticket.TicketId)
        if send_sla_email:
            _send_email(
                _get_user_email(ticket.StaffId),
                title,
                _email_body_with_link(message, ticket.StaffId, ticket.TicketId, 'Open ticket'),
            )

    admins = User.query.filter_by(Role=RoleEnum.Admin, IsActive=True).all()
    for admin in admins:
        if _notification_exists(admin.UserId, notif_type, ticket.TicketId):
            continue
        notify(admin.UserId, title, message, notif_type, ticket.TicketId)
        if send_sla_email:
            _send_email(
                admin.Email or '',
                title,
                _email_body_with_link(message, admin.UserId, ticket.TicketId, 'Open ticket'),
            )


def notify_social_vote(ticket, voter):
    from app.models.user_preference import UserPreference

    pref = UserPreference.query.filter_by(UserId=ticket.StudentId).first()
    if pref and pref.SuppressSocialNotifications:
        return

    title = f'New Support Vote — Ticket #{ticket.TicketId}'
    message = f'{voter.FullName} supported your ticket "{ticket.Title}".'
    notify(ticket.StudentId, title, message, 'ticket_vote', ticket.TicketId)
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View ticket'),
    )


def notify_social_comment(ticket, commenter):
    from app.models.user_preference import UserPreference

    pref = UserPreference.query.filter_by(UserId=ticket.StudentId).first()
    if pref and pref.SuppressSocialNotifications:
        return

    title = f'New Student Comment — Ticket #{ticket.TicketId}'
    message = f'{commenter.FullName} commented on your ticket "{ticket.Title}".'
    notify(ticket.StudentId, title, message, 'ticket_comment', ticket.TicketId)
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View ticket'),
    )


def notify_ticket_reopened(ticket, admin_user):
    """Staff and student both notified on reopen."""
    # Notify student
    s_title   = f'Ticket #{ticket.TicketId} Reopened'
    s_message = (f'Your reopen request for ticket "{ticket.Title}" '
                 f'has been approved by {admin_user.FullName}. '
                 f'It has been reassigned for further investigation.')
    notify(
        user_id    = ticket.StudentId,
        title      = s_title,
        message    = s_message,
        notif_type = 'ticket_reopened',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        s_title,
        _email_body_with_link(s_message, ticket.StudentId, ticket.TicketId, 'Follow up on ticket'),
    )
    # Notify staff
    if ticket.StaffId:
        st_title   = f'Ticket #{ticket.TicketId} Reopened'
        st_message = (f'Ticket "{ticket.Title}" has been reopened by admin '
                      f'and reassigned to you.')
        notify(
            user_id    = ticket.StaffId,
            title      = st_title,
            message    = st_message,
            notif_type = 'ticket_reopened',
            ticket_id  = ticket.TicketId,
        )
        _send_email(
            _get_user_email(ticket.StaffId),
            st_title,
            _email_body_with_link(st_message, ticket.StaffId, ticket.TicketId, 'Manage ticket'),
        )


def notify_reassignment_approved(ticket, new_staff, old_staff):
    """Old and new staff notified when a reassignment is approved."""
    ns_title   = f'Ticket #{ticket.TicketId} Assigned to You'
    ns_message = (f'Admin approved a reassignment. '
                  f'Ticket "{ticket.Title}" is now assigned to you.')
    notify(
        user_id    = new_staff.UserId,
        title      = ns_title,
        message    = ns_message,
        notif_type = 'ticket_assigned',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        new_staff.Email or '',
        ns_title,
        _email_body_with_link(ns_message, new_staff.UserId, ticket.TicketId, 'Manage ticket'),
    )
    if old_staff:
        os_title   = f'Ticket #{ticket.TicketId} Reassigned'
        os_message = (f'Your reassignment request for ticket "{ticket.Title}" '
                      f'was approved. It has been moved to '
                      f'{new_staff.FullName}.')
        notify(
            user_id    = old_staff.UserId,
            title      = os_title,
            message    = os_message,
            notif_type = 'status_update',
            ticket_id  = ticket.TicketId,
        )
        _send_email(
            old_staff.Email or '',
            os_title,
            _email_body_with_link(os_message, old_staff.UserId, ticket.TicketId, 'View ticket'),
        )


def notify_reassignment_rejected(ticket, requesting_staff):
    """Staff member who requested reassignment is notified of rejection."""
    title   = f'Reassignment Request Rejected — Ticket #{ticket.TicketId}'
    message = (f'Your reassignment request for ticket "{ticket.Title}" '
               f'has been rejected by admin. You remain assigned to this ticket.')
    notify(
        user_id    = requesting_staff.UserId,
        title      = title,
        message    = message,
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        requesting_staff.Email or '',
        title,
        _email_body_with_link(message, requesting_staff.UserId, ticket.TicketId, 'View ticket'),
    )


def notify_reopen_rejected(ticket):
    """Student is notified their reopen request was rejected."""
    title   = f'Reopen Request Rejected — Ticket #{ticket.TicketId}'
    message = (f'Your request to reopen ticket "{ticket.Title}" '
               f'has been reviewed and rejected by admin.')
    notify(
        user_id    = ticket.StudentId,
        title      = title,
        message    = message,
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        _get_user_email(ticket.StudentId),
        title,
        _email_body_with_link(message, ticket.StudentId, ticket.TicketId, 'View ticket'),
    )


def notify_escalation_rejected(ticket, requesting_staff):
    """Staff member who requested escalation is notified of rejection."""
    title   = f'Escalation Request Rejected — Ticket #{ticket.TicketId}'
    message = (f'Your escalation request for ticket "{ticket.Title}" '
               f'has been rejected by admin. The ticket remains in your department.')
    notify(
        user_id    = requesting_staff.UserId,
        title      = title,
        message    = message,
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )
    _send_email(
        requesting_staff.Email or '',
        title,
        _email_body_with_link(message, requesting_staff.UserId, ticket.TicketId, 'View ticket'),
    )