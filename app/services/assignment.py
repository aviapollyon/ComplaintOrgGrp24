import random
from app.models.user import User, RoleEnum
from app.models.ticket import Ticket, StatusEnum

ASSIGNMENT_LIMIT = 5


def _open_ticket_count(staff_user: User) -> int:
    return Ticket.query.filter(
        Ticket.StaffId == staff_user.UserId,
        ~Ticket.Status.in_([StatusEnum.Resolved, StatusEnum.Rejected])
    ).count()


def auto_assign_ticket(ticket: Ticket) -> User | None:
    from app import db
    from app.models.admin_notification import AdminNotification

    if ticket.DepartmentId is None:
        _notify_admin(ticket, 'unassigned_ticket',
                      f'Ticket #{ticket.TicketId} "{ticket.Title}" could not be '
                      f'auto-assigned — no department mapped.')
        return None

    dept_staff: list[User] = User.query.filter_by(
        Role=RoleEnum.Staff,
        DepartmentId=ticket.DepartmentId,
        IsActive=True
    ).all()

    if not dept_staff:
        _notify_admin(ticket, 'unassigned_ticket',
                      f'Ticket #{ticket.TicketId} "{ticket.Title}" has no staff '
                      f'in its department and was left unassigned.')
        return None

    staff_with_load = [
        (member, _open_ticket_count(member))
        for member in dept_staff
    ]
    available = [(m, load) for m, load in staff_with_load if load < ASSIGNMENT_LIMIT]

    if available:
        chosen, _ = min(available, key=lambda x: x[1])
    else:
        chosen = random.choice(dept_staff)

    ticket.StaffId = chosen.UserId
    ticket.Status  = StatusEnum.Assigned
    return chosen


def _notify_admin(ticket: Ticket, notif_type: str, message: str):
    from app import db
    from app.models.admin_notification import AdminNotification
    db.session.add(AdminNotification(
        Type      = notif_type,
        Message   = message,
        TicketId  = ticket.TicketId,
        IsRead    = False,
    ))