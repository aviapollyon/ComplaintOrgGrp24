from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort
)
from flask_login import login_required, current_user
from datetime import datetime

from app import db
from app.models.ticket            import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update     import TicketUpdate, UpdateStatusEnum
from app.models.department        import Department
from app.models.escalation        import EscalationRequest
from app.models.reassignment_request import ReassignmentRequest
from app.models.admin_notification import AdminNotification
from app.models.user              import User, RoleEnum
from app.utils.decorators         import role_required
from app.services.notifications   import (
    notify_status_update, notify_staff_reply,
    notify_ticket_resolved, notify_ticket_rejected,
    notify_progress_update,
)
from app.forms.staff_forms import (
    UpdateTicketForm, ResolveTicketForm,
    ReplyForm, StaffThreadReplyForm,
    EscalationRequestForm, StaffReassignmentRequestForm,
    StaffTicketFilterForm,
)

staff_bp = Blueprint('staff', __name__)

_STATUS_MAP = {
    'In Progress': (StatusEnum.InProgress, UpdateStatusEnum.InProgress),
    'Rejected'   : (StatusEnum.Rejected,   UpdateStatusEnum.Rejected),
}


@staff_bp.route('/dashboard')
@login_required
@role_required('Staff')
def dashboard():
    from app.utils.sorting import apply_sort
    filter_form  = StaffTicketFilterForm(request.args)
    query        = Ticket.query.filter_by(StaffId=current_user.UserId)

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
    if filter_form.sub_category.data:
        query = query.filter(Ticket.SubCategory == filter_form.sub_category.data)
    if filter_form.search.data:
        s = filter_form.search.data.strip()
        from app import db as _db
        query = query.filter(
            _db.or_(
                Ticket.Title.ilike(f'%{s}%'),
                Ticket.TrackingRef.ilike(f'%{s}%'),
            )
        )

    query    = apply_sort(query, filter_form.sort.data or 'newest')
    page     = request.args.get('page', 1, type=int)
    from flask import current_app
    try:
        per_page = int(filter_form.per_page.data or current_app.config.get('TICKETS_PER_PAGE', 15))
    except (ValueError, TypeError):
        per_page = current_app.config.get('TICKETS_PER_PAGE', 15)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    tickets    = pagination.items

    all_assigned = Ticket.query.filter_by(StaffId=current_user.UserId).all()
    resolved_t   = [t for t in all_assigned
                    if t.Status == StatusEnum.Resolved and t.ResolvedAt]
    avg_hrs      = None
    if resolved_t:
        avg_hrs = round(
            sum((t.ResolvedAt - t.CreatedAt).total_seconds() for t in resolved_t)
            / len(resolved_t) / 3600, 1
        )

    # ── Flags ONLY for tickets assigned to THIS staff member ──────────────
    from app.models.ticket_flag import TicketFlag, FlaggedTicket
    my_ticket_ids = [t.TicketId for t in all_assigned]

    if my_ticket_ids:
        # Get flag IDs that contain at least one of this staff's tickets
        my_flag_ids = {
            ft.FlagId for ft in
            FlaggedTicket.query
            .filter(FlaggedTicket.TicketId.in_(my_ticket_ids))
            .all()
        }
        # Active flags scoped to this staff member only
        active_flags = TicketFlag.query.filter(
            TicketFlag.FlagId.in_(my_flag_ids),
            TicketFlag.Status == 'active'
        ).all() if my_flag_ids else []

        # Which of this staff's tickets are flagged
        flagged_ids = {
            ft.TicketId for ft in
            FlaggedTicket.query
            .filter(
                FlaggedTicket.TicketId.in_(my_ticket_ids),
                FlaggedTicket.FlagId.in_(my_flag_ids)
            ).all()
        } if my_flag_ids else set()
    else:
        active_flags = []
        flagged_ids  = set()

    stats = {
        'total'       : len(all_assigned),
        'in_progress' : sum(1 for t in all_assigned if t.Status == StatusEnum.InProgress),
        'pending_info': sum(1 for t in all_assigned if t.Status == StatusEnum.PendingInfo),
        'resolved'    : len(resolved_t),
        'overdue'     : sum(
            1 for t in all_assigned
            if t.Status not in (StatusEnum.Resolved, StatusEnum.Rejected)
            and (datetime.utcnow() - t.CreatedAt).days > 3
        ),
        'avg_hours': avg_hrs,
    }

    return render_template(
        'staff/dashboard.html',
        tickets=tickets,
        pagination=pagination,
        filter_form=filter_form,
        stats=stats,
        flagged_ticket_ids=flagged_ids,
        active_flags=active_flags,
    )


@staff_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Staff')
def view_ticket(ticket_id):
    from app.models.reassignment_request import ReassignmentRequest
    ticket  = _get_staff_ticket(ticket_id)
    updates = (ticket.updates
               .filter_by(ParentUpdateId=None)
               .order_by(TicketUpdate.CreatedAt.asc())
               .all())
    attachments       = ticket.attachments.filter_by(UpdateId=None).all()
    update_form       = UpdateTicketForm()
    resolve_form      = ResolveTicketForm()
    reply_form        = ReplyForm()
    thread_reply_form = StaffThreadReplyForm()

    escalation_form = EscalationRequestForm()
    other_depts     = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).order_by(Department.Name).all()
    escalation_form.target_dept.choices = [(d.DepartmentId, d.Name) for d in other_depts]
    pending_escalation = EscalationRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()

    reassign_form = StaffReassignmentRequestForm()
    dept_colleagues = User.query.filter(
        User.Role         == RoleEnum.Staff,
        User.IsActive     == True,           # noqa: E712
        User.DepartmentId == current_user.DepartmentId,
        User.UserId       != current_user.UserId,
    ).order_by(User.FullName).all()
    reassign_form.target_staff.choices = [(u.UserId, u.FullName) for u in dept_colleagues]
    pending_reassign = ReassignmentRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()

    locked_thread_ids = _get_locked_thread_ids(ticket)

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
        reassign_form=reassign_form,
        pending_reassign=pending_reassign,
        locked_thread_ids=locked_thread_ids,
    )


@staff_bp.route('/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = UpdateTicketForm()
    if form.validate_on_submit():
        mapping = _STATUS_MAP.get(form.status.data)
        if not mapping:
            flash('Invalid status.', 'danger')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))
        new_status, new_update_status = mapping
        ticket.Status    = new_status
        ticket.UpdatedAt = datetime.utcnow()
        db.session.add(TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment=form.comment.data.strip(), StatusChange=new_update_status,
            IsReplyThread=False,
        ))
        if new_status == StatusEnum.InProgress:
            notify_progress_update(ticket, current_user)
        elif new_status == StatusEnum.Rejected:
            notify_ticket_rejected(ticket, current_user)
        else:
            notify_status_update(ticket, current_user)
        db.session.commit()
        flash(f'Status updated to "{form.status.data}".', 'success')
    else:
        flash('Please fill in all required fields.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


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
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment=f'[RESOLVED] {form.resolution.data.strip()}',
            StatusChange=UpdateStatusEnum.Resolved, IsReplyThread=False,
        ))
        notify_ticket_resolved(ticket, current_user)
        db.session.commit()
        flash('Ticket marked as resolved.', 'success')
    else:
        flash('Please provide resolution details.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


@staff_bp.route('/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
@role_required('Staff')
def reply_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = ReplyForm()
    if form.validate_on_submit():
        ticket.Status    = StatusEnum.PendingInfo
        ticket.UpdatedAt = datetime.utcnow()
        update = TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment=form.comment.data.strip(),
            StatusChange=UpdateStatusEnum.PendingInfo, IsReplyThread=True,
        )
        db.session.add(update)
        notify_staff_reply(ticket, current_user)
        db.session.commit()
        flash('Reply sent. Status set to Pending Info.', 'success')
    else:
        flash('Message cannot be empty.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


@staff_bp.route('/ticket/<int:ticket_id>/thread-reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Staff')
def thread_reply(ticket_id, update_id):
    ticket = _get_staff_ticket(ticket_id)
    parent = TicketUpdate.query.get_or_404(update_id)
    if parent.TicketId != ticket_id:
        abort(403)
    if not parent.IsReplyThread:
        flash('Replies only allowed on reply threads.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

    locked = _get_locked_thread_ids(ticket)
    if update_id in locked:
        flash('This thread has been closed after your progress update.', 'info')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

    form = StaffThreadReplyForm()
    if form.validate_on_submit():
        reply = TicketUpdate(
            TicketId=ticket_id, UserId=current_user.UserId,
            Comment=form.comment.data.strip(),
            ParentUpdateId=update_id, IsReplyThread=False,
        )
        db.session.add(reply)
        ticket.UpdatedAt = datetime.utcnow()
        notify_staff_reply(ticket, current_user)
        db.session.commit()
        flash('Reply added.', 'success')
    else:
        flash('Reply cannot be empty.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

def _get_locked_thread_ids(ticket: Ticket) -> set:
    locked  = set()
    threads = (ticket.updates
            .filter_by(IsReplyThread=True, ParentUpdateId=None)
            .all())
    for thread in threads:
        in_progress_after = (
            ticket.updates
            .filter(
                TicketUpdate.IsReplyThread  == False,               # noqa: E712
                TicketUpdate.ParentUpdateId == None,                # noqa: E712
                TicketUpdate.StatusChange   == UpdateStatusEnum.InProgress,
                TicketUpdate.CreatedAt      > thread.CreatedAt,
            )
            .first()
        )
        if in_progress_after:
            locked.add(thread.UpdateId)
    return locked

@staff_bp.route('/ticket/<int:ticket_id>/escalate', methods=['POST'])
@login_required
@role_required('Staff')
def request_escalation(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = EscalationRequestForm()
    other_depts = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).all()
    form.target_dept.choices = [(d.DepartmentId, d.Name) for d in other_depts]

    if form.validate_on_submit():
        if EscalationRequest.query.filter_by(TicketId=ticket_id, Status='Pending').first():
            flash('An escalation is already pending.', 'warning')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        target_dept = Department.query.get_or_404(form.target_dept.data)
        db.session.add(EscalationRequest(
            TicketId=ticket_id, RequestedById=current_user.UserId,
            TargetDeptId=form.target_dept.data,
            Reason=form.reason.data.strip(), Status='Pending',
        ))
        db.session.add(TicketUpdate(
            TicketId=ticket_id, UserId=current_user.UserId,
            Comment=(f'[ESCALATION REQUESTED] To {target_dept.Name}. '
                     f'Reason: {form.reason.data.strip()}'),
            IsReplyThread=False,
        ))
        db.session.add(AdminNotification(
            Type='escalation_request',
            Message=(f'Ticket #{ticket_id} "{ticket.Title}" — {current_user.FullName} '
                     f'requested escalation to {target_dept.Name}.'),
            TicketId=ticket_id, IsRead=False,
        ))
        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        from app.services.notifications import _send_admin_emails
        _send_admin_emails(
            f'Escalation Request — Ticket #{ticket_id}',
            (f'{current_user.FullName} has requested escalation of ticket '
             f'"#{ticket_id} {ticket.Title}" to {target_dept.Name}.\n\n'
             f'Reason: {form.reason.data.strip()}\n\n'
             f'Review it at: /admin/tickets/{ticket_id}'),
        )
        flash('Escalation request submitted.', 'success')
    else:
        flash('Please fill in all escalation fields.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── STAFF SELF-REASSIGNMENT REQUEST ──────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>/request-reassign', methods=['POST'])
@login_required
@role_required('Staff')
def request_reassignment(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = StaffReassignmentRequestForm()

    dept_colleagues = User.query.filter(
        User.Role         == RoleEnum.Staff,
        User.IsActive     == True,           # noqa: E712
        User.DepartmentId == current_user.DepartmentId,
        User.UserId       != current_user.UserId,
    ).all()
    form.target_staff.choices = [(u.UserId, u.FullName) for u in dept_colleagues]

    if form.validate_on_submit():
        if ReassignmentRequest.query.filter_by(
                TicketId=ticket_id, Status='Pending').first():
            flash('A reassignment request is already pending.', 'warning')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        target = User.query.get_or_404(form.target_staff.data)
        db.session.add(ReassignmentRequest(
            TicketId      = ticket_id,
            RequestedById = current_user.UserId,
            TargetStaffId = target.UserId,
            Reason        = form.reason.data.strip(),
            Status        = 'Pending',
        ))
        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = (f'[REASSIGNMENT REQUESTED] {current_user.FullName} '
                             f'requested reassignment to {target.FullName}. '
                             f'Reason: {form.reason.data.strip()}'),
            IsReplyThread = False,
        ))
        db.session.add(AdminNotification(
            Type     = 'reassignment_request',
            Message  = (f'Ticket #{ticket_id} "{ticket.Title}" — {current_user.FullName} '
                        f'requested reassignment to {target.FullName}.'),
            TicketId = ticket_id,
            IsRead   = False,
        ))
        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        from app.services.notifications import _send_admin_emails
        _send_admin_emails(
            f'Reassignment Request — Ticket #{ticket_id}',
            (f'{current_user.FullName} has requested reassignment of ticket '
             f'"#{ticket_id} {ticket.Title}" to {target.FullName}.\n\n'
             f'Reason: {form.reason.data.strip()}\n\n'
             f'Review it at: /admin/tickets/{ticket_id}'),
        )
        flash('Reassignment request submitted to admin.', 'success')
    else:
        flash('Please fill in all reassignment fields.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


def _get_staff_ticket(ticket_id: int) -> Ticket:
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StaffId != current_user.UserId:
        abort(403)
    return ticket