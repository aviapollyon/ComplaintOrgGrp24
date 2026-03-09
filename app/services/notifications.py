"""
Central notification service.
All in-app notifications for users are created through this module.
"""
from app import db
from app.models.user_notification import UserNotification


def notify(user_id: int, title: str, message: str,
           notif_type: str = 'general', ticket_id: int = None):
    """Create a UserNotification for a single user."""
    db.session.add(UserNotification(
        UserId   = user_id,
        Title    = title,
        Message  = message,
        Type     = notif_type,
        IsRead   = False,
        TicketId = ticket_id,
    ))


def notify_ticket_assigned(ticket):
    """Staff notified when a ticket is assigned to them."""
    if ticket.StaffId:
        notify(
            user_id    = ticket.StaffId,
            title      = f'New Ticket Assigned — #{ticket.TicketId}',
            message    = f'Ticket "{ticket.Title}" has been assigned to you.',
            notif_type = 'ticket_assigned',
            ticket_id  = ticket.TicketId,
        )


def notify_status_update(ticket, changed_by_user):
    """Student notified when ticket status changes."""
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Updated',
        message    = (f'Your ticket "{ticket.Title}" status changed to '
                      f'"{ticket.Status.value}" by {changed_by_user.FullName}.'),
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )


def notify_staff_reply(ticket, staff_user):
    """Student notified when staff sends a reply thread message."""
    notify(
        user_id    = ticket.StudentId,
        title      = f'Staff Replied — Ticket #{ticket.TicketId}',
        message    = (f'{staff_user.FullName} sent you a message on '
                      f'ticket "{ticket.Title}". Please check and reply.'),
        notif_type = 'new_reply',
        ticket_id  = ticket.TicketId,
    )


def notify_student_replied(ticket, student_user):
    """Staff notified when student replies to a thread."""
    if ticket.StaffId:
        notify(
            user_id    = ticket.StaffId,
            title      = f'Student Replied — Ticket #{ticket.TicketId}',
            message    = (f'{student_user.FullName} replied to your message on '
                          f'ticket "{ticket.Title}".'),
            notif_type = 'reply_received',
            ticket_id  = ticket.TicketId,
        )


def notify_ticket_resolved(ticket, staff_user):
    """Student notified when ticket is resolved."""
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Resolved',
        message    = (f'Your ticket "{ticket.Title}" has been resolved by '
                      f'{staff_user.FullName}. Please leave feedback.'),
        notif_type = 'ticket_resolved',
        ticket_id  = ticket.TicketId,
    )


def notify_ticket_rejected(ticket, actor):
    """Student notified when ticket is rejected."""
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Rejected',
        message    = f'Your ticket "{ticket.Title}" has been rejected by {actor.FullName}.',
        notif_type = 'ticket_rejected',
        ticket_id  = ticket.TicketId,
    )


def notify_progress_update(ticket, staff_user):
    """Student notified when staff adds a progress update (In Progress status)."""
    notify(
        user_id    = ticket.StudentId,
        title      = f'Progress Update — Ticket #{ticket.TicketId}',
        message    = (f'{staff_user.FullName} posted a progress update on '
                      f'ticket "{ticket.Title}".'),
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )