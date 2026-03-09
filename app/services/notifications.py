from app import db
from app.models.user_notification import UserNotification


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


def notify_ticket_submitted(ticket):
    """Confirm submission to the student with their unique tracking reference."""
    ref = ticket.TrackingRef or f'#{ticket.TicketId}'
    notify(
        user_id    = ticket.StudentId,
        title      = f'Complaint Submitted — Ref: {ref}',
        message    = (f'Your complaint "{ticket.Title}" has been received and is '  
                      f'being reviewed. Your tracking reference is {ref}. '
                      f'Keep this reference for all follow-up enquiries.'),
        notif_type = 'ticket_submitted',
        ticket_id  = ticket.TicketId,
    )


def notify_ticket_assigned(ticket):
    if ticket.StaffId:
        notify(
            user_id    = ticket.StaffId,
            title      = f'New Ticket Assigned — #{ticket.TicketId}',
            message    = f'Ticket "{ticket.Title}" has been assigned to you.',
            notif_type = 'ticket_assigned',
            ticket_id  = ticket.TicketId,
        )


def notify_status_update(ticket, changed_by_user):
    ref = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Updated',
        message    = (f'Your ticket "{ticket.Title}"{ref} status changed to '
                      f'"{ticket.Status.value}" by {changed_by_user.FullName}.'),
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )


def notify_staff_reply(ticket, staff_user):
    ref = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    notify(
        user_id    = ticket.StudentId,
        title      = f'Staff Replied — Ticket #{ticket.TicketId}',
        message    = (f'{staff_user.FullName} sent you a message on '
                      f'ticket "{ticket.Title}"{ref}. Please check and reply.'),
        notif_type = 'new_reply',
        ticket_id  = ticket.TicketId,
    )


def notify_student_replied(ticket, student_user):
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
    ref = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Resolved',
        message    = (f'Your ticket "{ticket.Title}"{ref} has been resolved by '
                      f'{staff_user.FullName}. Please leave your feedback.'),
        notif_type = 'ticket_resolved',
        ticket_id  = ticket.TicketId,
    )


def notify_ticket_rejected(ticket, actor):
    ref = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Rejected',
        message    = (f'Your ticket "{ticket.Title}"{ref} has been rejected by {actor.FullName}.'),
        notif_type = 'ticket_rejected',
        ticket_id  = ticket.TicketId,
    )


def notify_progress_update(ticket, staff_user):
    ref = f' [Ref: {ticket.TrackingRef}]' if ticket.TrackingRef else ''
    notify(
        user_id    = ticket.StudentId,
        title      = f'Progress Update — Ticket #{ticket.TicketId}',
        message    = (f'{staff_user.FullName} posted a progress update on '
                      f'ticket "{ticket.Title}"{ref}.'),
        notif_type = 'status_update',
        ticket_id  = ticket.TicketId,
    )


def notify_ticket_reopened(ticket, admin_user):
    """Staff and student both notified on reopen."""
    # Notify student
    notify(
        user_id    = ticket.StudentId,
        title      = f'Ticket #{ticket.TicketId} Reopened',
        message    = (f'Your reopen request for ticket "{ticket.Title}" '
                      f'has been approved by {admin_user.FullName}. '
                      f'It has been reassigned for further investigation.'),
        notif_type = 'ticket_reopened',
        ticket_id  = ticket.TicketId,
    )
    # Notify staff
    if ticket.StaffId:
        notify(
            user_id    = ticket.StaffId,
            title      = f'Ticket #{ticket.TicketId} Reopened',
            message    = (f'Ticket "{ticket.Title}" has been reopened by admin '
                          f'and reassigned to you.'),
            notif_type = 'ticket_reopened',
            ticket_id  = ticket.TicketId,
        )


def notify_reassignment_approved(ticket, new_staff, old_staff):
    """Old and new staff notified when a reassignment is approved."""
    notify(
        user_id    = new_staff.UserId,
        title      = f'Ticket #{ticket.TicketId} Assigned to You',
        message    = (f'Admin approved a reassignment. '
                      f'Ticket "{ticket.Title}" is now assigned to you.'),
        notif_type = 'ticket_assigned',
        ticket_id  = ticket.TicketId,
    )
    if old_staff:
        notify(
            user_id    = old_staff.UserId,
            title      = f'Ticket #{ticket.TicketId} Reassigned',
            message    = (f'Your reassignment request for ticket "{ticket.Title}" '
                          f'was approved. It has been moved to '
                          f'{new_staff.FullName}.'),
            notif_type = 'status_update',
            ticket_id  = ticket.TicketId,
        )