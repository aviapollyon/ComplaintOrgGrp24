from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort
)
from flask_login import login_required, current_user
from datetime import datetime

from app import db
from app.models.ticket import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update import TicketUpdate, UpdateStatusEnum
from app.models.attachment import Attachment
from app.models.user import User
from app.utils.decorators import role_required
from app.utils.helpers import allowed_file, save_uploaded_file
from app.forms.staff_forms import (
    UpdateTicketForm, ResolveTicketForm,
    ReplyForm, StaffThreadReplyForm, StaffTicketFilterForm
)

staff_bp = Blueprint('staff', __name__)

_STATUS_MAP = {
    'In Progress': (StatusEnum.InProgress, UpdateStatusEnum.InProgress),
    'Rejected'   : (StatusEnum.Rejected,   UpdateStatusEnum.Rejected),
}


# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────
@staff_bp.route('/dashboard')
@login_required
@role_required('Staff')
def dashboard():
    filter_form = StaffTicketFilterForm(request.args)
    query = Ticket.query.filter_by(StaffId=current_user.UserId)

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

    tickets = query.order_by(Ticket.UpdatedAt.desc()).all()

    all_assigned = Ticket.query.filter_by(StaffId=current_user.UserId).all()
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
        'avg_hours'    : avg_resolution_hours,
    }

    return render_template(
        'staff/dashboard.html',
        tickets=tickets,
        filter_form=filter_form,
        stats=stats
    )


# ─────────────────────────────────────────────
#  VIEW TICKET
# ─────────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Staff')
def view_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    updates = (
        ticket.updates
        .filter_by(ParentUpdateId=None)
        .order_by(TicketUpdate.CreatedAt.asc())
        .all()
    )
    attachments  = ticket.attachments.filter_by(UpdateId=None).all()
    update_form  = UpdateTicketForm()
    resolve_form = ResolveTicketForm()
    reply_form   = ReplyForm()
    thread_reply_form = StaffThreadReplyForm()

    return render_template(
        'staff/view_ticket.html',
        ticket=ticket,
        updates=updates,
        attachments=attachments,
        update_form=update_form,
        resolve_form=resolve_form,
        reply_form=reply_form,
        thread_reply_form=thread_reply_form,
    )


# ─────────────────────────────────────────────
#  UPDATE STATUS
# ─────────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = UpdateTicketForm()

    if form.validate_on_submit():
        mapping = _STATUS_MAP.get(form.status.data)
        if not mapping:
            flash('Invalid status selected.', 'danger')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        new_status, new_update_status = mapping
        ticket.Status    = new_status
        ticket.UpdatedAt = datetime.utcnow()

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

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  RESOLVE
# ─────────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@role_required('Staff')
def resolve_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = ResolveTicketForm()

    if form.validate_on_submit():
        ticket.Status     = StatusEnum.Resolved
        ticket.ResolvedAt = datetime.utcnow()
        ticket.UpdatedAt  = datetime.utcnow()

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

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  REPLY TO STUDENT — auto sets Pending Info
# ─────────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
@role_required('Staff')
def reply_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = ReplyForm()

    if form.validate_on_submit():
        # Auto-set status to Pending Info
        ticket.Status    = StatusEnum.PendingInfo
        ticket.UpdatedAt = datetime.utcnow()

        update = TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = form.comment.data.strip(),
            StatusChange  = UpdateStatusEnum.PendingInfo,
            IsReplyThread = True,   # ← marks this as a threadable comment
        )
        db.session.add(update)
        db.session.commit()
        flash('Reply sent. Ticket status set to Pending Info.', 'success')
    else:
        flash('Message cannot be empty.', 'danger')

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  STAFF THREAD REPLY — reply inside an existing thread
# ─────────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>/thread-reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Staff')
def thread_reply(ticket_id, update_id):
    ticket = _get_staff_ticket(ticket_id)
    parent = TicketUpdate.query.get_or_404(update_id)

    if parent.TicketId != ticket_id:
        abort(403)
    if not parent.IsReplyThread:
        flash('Replies are only allowed on designated reply threads.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

    form = StaffThreadReplyForm()
    if form.validate_on_submit():
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

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────
def _get_staff_ticket(ticket_id: int) -> Ticket:
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StaffId != current_user.UserId:
        abort(403)
    return ticket