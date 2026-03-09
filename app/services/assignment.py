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
    from app.services.notifications import notify_ticket_assigned

    if ticket.DepartmentId is None:
        db.session.add(AdminNotification(
            Type='unassigned_ticket',
            Message=(f'Ticket #{ticket.TicketId} "{ticket.Title}" could not be '
                     f'auto-assigned — no department mapped.'),
            TicketId=ticket.TicketId, IsRead=False,
        ))
        return None

    dept_staff: list[User] = User.query.filter_by(
        Role=RoleEnum.Staff,
        DepartmentId=ticket.DepartmentId,
        IsActive=True
    ).all()

    if not dept_staff:
        db.session.add(AdminNotification(
            Type='unassigned_ticket',
            Message=(f'Ticket #{ticket.TicketId} "{ticket.Title}" has no staff '
                     f'in its department and was left unassigned.'),
            TicketId=ticket.TicketId, IsRead=False,
        ))
        return None

    staff_with_load = [(m, _open_ticket_count(m)) for m in dept_staff]
    available       = [(m, l) for m, l in staff_with_load if l < ASSIGNMENT_LIMIT]
    chosen          = min(available, key=lambda x: x[1])[0] if available else random.choice(dept_staff)

    ticket.StaffId = chosen.UserId
    ticket.Status  = StatusEnum.Assigned

    # Notify the assigned staff member
    notify_ticket_assigned(ticket)

    return chosen