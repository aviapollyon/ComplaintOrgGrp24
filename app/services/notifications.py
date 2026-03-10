import logging
import sys

from app import db
from app.models.user_notification import UserNotification

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def notify(user_id: int, title: str, message: str,
           notif_type: str = 'general', ticket_id: int = None):
    db.session.add(UserNotification(
        UserId   = user_id,
        Title    = title,
        Message  = message,
        Type     = notif_type,
        IsRead   = False,
        TicketId = ticket_id,
    ))


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
        mail.send(msg)
        logger.info('[EMAIL SENT] To: %s | Subject: %s', recipient_email, subject)
    except Exception as exc:
        logger.error(
            '[EMAIL ERROR] Failed to send to %s | Subject: %s | Error: %s',
            recipient_email, subject, exc, exc_info=True
        )
        print(f'[EMAIL ERROR] {exc}', file=sys.stderr, flush=True)


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
        f'{message}\n\nLog in to view your ticket: /student/dashboard',
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
            f'{message}\n\nLog in to manage this ticket: /staff/dashboard',
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
        f'{message}\n\nLog in to view the update: /student/dashboard',
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
        f'{message}\n\nLog in to reply: /student/dashboard',
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
            f'{message}\n\nLog in to view the reply: /staff/dashboard',
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
        f'{message}\n\nLog in to rate your experience: /student/dashboard',
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
        f'{message}\n\nLog in to view details: /student/dashboard',
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
        f'{message}\n\nLog in to view the update: /student/dashboard',
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
        f'{s_message}\n\nLog in to follow up: /student/dashboard',
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
            f'{st_message}\n\nLog in to manage this ticket: /staff/dashboard',
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
        f'{ns_message}\n\nLog in to manage this ticket: /staff/dashboard',
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
            f'{os_message}\n\nLog in to view your tickets: /staff/dashboard',
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
        f'{message}\n\nLog in to view the ticket: /staff/dashboard',
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
        f'{message}\n\nLog in to view your tickets: /student/dashboard',
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
        f'{message}\n\nLog in to view the ticket: /staff/dashboard',
    )