from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort
)
from flask_login import login_required, current_user
from datetime import datetime

from app import db
from app.models.ticket import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update import TicketUpdate, UpdateStatusEnum
from app.models.department import Department
from app.models.escalation import EscalationRequest
from app.models.admin_notification import AdminNotification
from app.models.user import User
from app.utils.decorators import role_required
from app.forms.staff_forms import (
    UpdateTicketForm, ResolveTicketForm,
    ReplyForm, StaffThreadReplyForm,
    EscalationRequestForm, StaffTicketFilterForm
)


# Blueprint for staff-related routes
staff_bp = Blueprint('staff', __name__)


# Maps form status strings to their corresponding enums for ticket and update
_STATUS_MAP = {
    'In Progress': (StatusEnum.InProgress, UpdateStatusEnum.InProgress),
    'Rejected'   : (StatusEnum.Rejected,   UpdateStatusEnum.Rejected),
}


# ── DASHBOARD ────────────────────────────────────────────────────────────────

# Staff dashboard: shows tickets assigned to the current staff member, with filters and stats
@staff_bp.route('/dashboard')
@login_required
@role_required('Staff')
def dashboard():
    filter_form = StaffTicketFilterForm(request.args)  # Form for filtering tickets
    query = Ticket.query.filter_by(StaffId=current_user.UserId)  # Only tickets assigned to this staff

    # Apply filters if present
    if filter_form.status.data:
        try:
            query = query.filter(Ticket.Status == StatusEnum(filter_form.status.data))
        except ValueError:
            pass
    if filter_form.priority.data:
        try:
            query = query.filter(Ticket.Priority == PriorityEnum(filter_form.priority.data))
        except ValueError:
            pass
    if filter_form.category.data:
        query = query.filter(Ticket.Category == filter_form.category.data)

    tickets = query.order_by(Ticket.UpdatedAt.desc()).all()  # Filtered and sorted tickets
    all_assigned = Ticket.query.filter_by(StaffId=current_user.UserId).all()  # All assigned tickets

    # Find resolved tickets and calculate average resolution time
    resolved_tickets = [
        t for t in all_assigned
        if t.Status == StatusEnum.Resolved and t.ResolvedAt
    ]
    avg_resolution_hours = None
    if resolved_tickets:
        total_secs = sum(
            (t.ResolvedAt - t.CreatedAt).total_seconds()
            for t in resolved_tickets
        )
        avg_resolution_hours = round(total_secs / len(resolved_tickets) / 3600, 1)

    # Build stats for dashboard display
    stats = {
        'total'        : len(all_assigned),
        'in_progress'  : sum(1 for t in all_assigned if t.Status == StatusEnum.InProgress),
        'pending_info' : sum(1 for t in all_assigned if t.Status == StatusEnum.PendingInfo),
        'resolved'     : len(resolved_tickets),
        'overdue'      : sum(
            1 for t in all_assigned
            if t.Status not in (StatusEnum.Resolved, StatusEnum.Rejected)
            and (datetime.utcnow() - t.CreatedAt).days > 3
        ),
        'avg_hours': avg_resolution_hours,
    }

    # Render the dashboard template with tickets and stats
    return render_template(
        'staff/dashboard.html',
        tickets=tickets,
        filter_form=filter_form,
        stats=stats
    )


# ── VIEW TICKET ───────────────────────────────────────────────────────────────

# View details of a specific ticket assigned to staff
@staff_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Staff')
def view_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)  # Ensure staff owns this ticket
    # Get all top-level updates (not replies)
    updates = (ticket.updates
               .filter_by(ParentUpdateId=None)
               .order_by(TicketUpdate.CreatedAt.asc())
               .all())
    # Get attachments not linked to updates
    attachments = ticket.attachments.filter_by(UpdateId=None).all()

    # Forms for various staff actions
    update_form       = UpdateTicketForm()
    resolve_form      = ResolveTicketForm()
    reply_form        = ReplyForm()
    thread_reply_form = StaffThreadReplyForm()

    # Escalation form — all departments except the current one
    escalation_form = EscalationRequestForm()
    other_depts = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).order_by(Department.Name).all()
    escalation_form.target_dept.choices = [
        (d.DepartmentId, d.Name) for d in other_depts
    ]

    # Check if there is a pending escalation for this ticket
    pending_escalation = EscalationRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()

    # Render the ticket view template with all forms and data
    return render_template(
        'staff/view_ticket.html',
        ticket=ticket,
        updates=updates,
        attachments=attachments,
        update_form=update_form,
        resolve_form=resolve_form,
        reply_form=reply_form,
        thread_reply_form=thread_reply_form,
        escalation_form=escalation_form,
        pending_escalation=pending_escalation,
    )


# ── UPDATE STATUS ─────────────────────────────────────────────────────────────

# Update the status of a ticket (e.g., In Progress, Rejected)
@staff_bp.route('/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)  # Ensure staff owns this ticket
    form   = UpdateTicketForm()

    if form.validate_on_submit():
        # Map form status to enums
        mapping = _STATUS_MAP.get(form.status.data)
        if not mapping:
            flash('Invalid status selected.', 'danger')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        new_status, new_update_status = mapping
        ticket.Status    = new_status
        ticket.UpdatedAt = datetime.utcnow()

        # Log the status update in the ticket's timeline
        db.session.add(TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = form.comment.data.strip(),
            StatusChange  = new_update_status,
            IsReplyThread = False,
        ))
        db.session.commit()
        flash(f'Ticket status updated to "{form.status.data}".', 'success')
    else:
        flash('Please fill in all required fields.', 'danger')

    # Redirect back to the ticket view
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── RESOLVE ───────────────────────────────────────────────────────────────────

# Mark a ticket as resolved and log the resolution
@staff_bp.route('/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@role_required('Staff')
def resolve_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)  # Ensure staff owns this ticket
    form   = ResolveTicketForm()

    if form.validate_on_submit():
        ticket.Status     = StatusEnum.Resolved
        ticket.ResolvedAt = datetime.utcnow()
        ticket.UpdatedAt  = datetime.utcnow()

        # Add a timeline update marking the ticket as resolved
        db.session.add(TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = f'[RESOLVED] {form.resolution.data.strip()}',
            StatusChange  = UpdateStatusEnum.Resolved,
            IsReplyThread = False,
        ))
        db.session.commit()
        flash('Ticket marked as resolved.', 'success')
    else:
        flash('Please provide resolution details.', 'danger')

    # Redirect back to the ticket view
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── REPLY TO STUDENT (sets Pending Info) ──────────────────────────────────────

# Reply to a student, setting the ticket status to Pending Info
@staff_bp.route('/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
@role_required('Staff')
def reply_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)  # Ensure staff owns this ticket
    form   = ReplyForm()

    if form.validate_on_submit():
        ticket.Status    = StatusEnum.PendingInfo
        ticket.UpdatedAt = datetime.utcnow()

        # Add a reply update and set as a reply thread
        update = TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = form.comment.data.strip(),
            StatusChange  = UpdateStatusEnum.PendingInfo,
            IsReplyThread = True,
        )
        db.session.add(update)
        db.session.commit()
        flash('Reply sent. Ticket status set to Pending Info.', 'success')
    else:
        flash('Message cannot be empty.', 'danger')

    # Redirect back to the ticket view
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── STAFF THREAD REPLY ────────────────────────────────────────────────────────

# Reply to a specific thread in a ticket (internal staff discussion)
@staff_bp.route('/ticket/<int:ticket_id>/thread-reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Staff')
def thread_reply(ticket_id, update_id):
    ticket = _get_staff_ticket(ticket_id)  # Ensure staff owns this ticket
    parent = TicketUpdate.query.get_or_404(update_id)  # Parent update to reply to

    # Only allow replies to valid reply threads
    if parent.TicketId != ticket_id:
        abort(403)
    if not parent.IsReplyThread:
        flash('Replies are only allowed on designated reply threads.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

    form = StaffThreadReplyForm()
    if form.validate_on_submit():
        # Add a reply to the thread
        reply = TicketUpdate(
            TicketId       = ticket_id,
            UserId         = current_user.UserId,
            Comment        = form.comment.data.strip(),
            ParentUpdateId = update_id,
            IsReplyThread  = False,
        )
        db.session.add(reply)
        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        flash('Reply added.', 'success')
    else:
        flash('Reply cannot be empty.', 'danger')

    # Redirect back to the ticket view
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── REQUEST ESCALATION ────────────────────────────────────────────────────────

# Request escalation of a ticket to another department
@staff_bp.route('/ticket/<int:ticket_id>/escalate', methods=['POST'])
@login_required
@role_required('Staff')
def request_escalation(ticket_id):
    ticket = _get_staff_ticket(ticket_id)  # Ensure staff owns this ticket
    form   = EscalationRequestForm()

    # List all departments except the current one for escalation
    other_depts = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).all()
    form.target_dept.choices = [(d.DepartmentId, d.Name) for d in other_depts]

    if form.validate_on_submit():
        # Only one pending escalation at a time
        existing = EscalationRequest.query.filter_by(
            TicketId=ticket_id, Status='Pending'
        ).first()
        if existing:
            flash('An escalation request is already pending for this ticket.', 'warning')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        target_dept = Department.query.get_or_404(form.target_dept.data)

        # Create the escalation request
        escalation = EscalationRequest(
            TicketId      = ticket_id,
            RequestedById = current_user.UserId,
            TargetDeptId  = form.target_dept.data,
            Reason        = form.reason.data.strip(),
            Status        = 'Pending',
        )
        db.session.add(escalation)

        # Log the escalation request in the ticket's timeline
        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = (
                f'[ESCALATION REQUESTED] Staff requested escalation to '
                f'{target_dept.Name}. Reason: {form.reason.data.strip()}'
            ),
            IsReplyThread = False,
        ))

        # Notify admin of the escalation request
        db.session.add(AdminNotification(
            Type     = 'escalation_request',
            Message  = (
                f'Ticket #{ticket_id} "{ticket.Title}" — {current_user.FullName} '
                f'requested escalation to {target_dept.Name}.'
            ),
            TicketId = ticket_id,
            IsRead   = False,
        ))

        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        flash('Escalation request submitted to admin.', 'success')
    else:
        flash('Please fill in all escalation fields.', 'danger')

    # Redirect back to the ticket view
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── HELPER ────────────────────────────────────────────────────────────────────

# Helper function to fetch a ticket and ensure it belongs to the current staff user
def _get_staff_ticket(ticket_id: int) -> Ticket:
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StaffId != current_user.UserId:
        abort(403)
    return ticket