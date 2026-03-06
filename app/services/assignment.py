"""
Ticket auto-assignment service.

Rules (in order):
1. Find all Staff in the ticket's department.
2. From those, collect "available" staff — fewer than 5 open tickets.
3. If available staff exist → assign to the one with the LEAST open tickets.
4. If no available staff → assign randomly from ALL staff in the department.
5. If the department has NO staff at all → leave StaffId as None (unassigned).
"""

import random
from app.models.user import User, RoleEnum
from app.models.ticket import Ticket, StatusEnum


ASSIGNMENT_LIMIT = 5   # max open tickets before a staff member is "busy"


def _open_ticket_count(staff_user: User) -> int:
    """Count active (non-closed) tickets assigned to a staff member."""
    return Ticket.query.filter(
        Ticket.StaffId == staff_user.UserId,
        ~Ticket.Status.in_([StatusEnum.Resolved, StatusEnum.Rejected])
    ).count()


def auto_assign_ticket(ticket: Ticket) -> User | None:
    """
    Determine which staff member to assign *ticket* to.
    Mutates ticket.StaffId and ticket.Status in-place.
    Returns the assigned User or None.
    """
    if ticket.DepartmentId is None:
        return None

    # All staff in this department
    dept_staff: list[User] = User.query.filter_by(
        Role=RoleEnum.Staff,
        DepartmentId=ticket.DepartmentId
    ).all()

    if not dept_staff:
        return None

    # Annotate each staff member with their current open-ticket load
    staff_with_load = [
        (member, _open_ticket_count(member))
        for member in dept_staff
    ]

    # Available = load < ASSIGNMENT_LIMIT
    available = [(m, load) for m, load in staff_with_load if load < ASSIGNMENT_LIMIT]

    if available:
        # Pick the least-loaded available staff member
        chosen, _ = min(available, key=lambda x: x[1])
    else:
        # No one is available — assign randomly from the whole department
        chosen = random.choice(dept_staff)

    ticket.StaffId = chosen.UserId
    ticket.Status  = StatusEnum.Assigned

    return chosen