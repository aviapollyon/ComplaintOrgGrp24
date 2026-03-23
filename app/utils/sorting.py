from app.models.ticket import Ticket, PriorityEnum

_PRIORITY_ORDER = {
    PriorityEnum.High:   0,
    PriorityEnum.Medium: 1,
    PriorityEnum.Low:    2,
}


def apply_sort(query, sort_value: str):
    """
    Apply ordering to a Ticket SQLAlchemy query.
    sort_value matches the SORT_CHOICES values defined in forms.
    """
    if sort_value == 'oldest':
        return query.order_by(Ticket.UpdatedAt.asc(), Ticket.TicketId.asc())
    elif sort_value == 'priority':
        # SQLite-compatible CASE ordering
        from sqlalchemy import case
        priority_case = case(
            (Ticket.Priority == PriorityEnum.High,   0),
            (Ticket.Priority == PriorityEnum.Medium, 1),
            (Ticket.Priority == PriorityEnum.Low,    2),
            else_=3
        )
        return query.order_by(priority_case, Ticket.CreatedAt.desc())
    elif sort_value == 'title':
        return query.order_by(Ticket.Title.asc())
    elif sort_value == 'id_asc':
        return query.order_by(Ticket.TicketId.asc())
    elif sort_value == 'id_desc':
        return query.order_by(Ticket.TicketId.desc())
    elif sort_value == 'subcategory':
        return query.order_by(Ticket.SubCategory.asc(), Ticket.CreatedAt.desc())
    else:  # 'newest' is default
        return query.order_by(Ticket.UpdatedAt.desc(), Ticket.TicketId.desc())