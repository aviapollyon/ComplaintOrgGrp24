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
from app.models.ticket_comment    import TicketComment
from app.models.ticket_flag       import TicketFlag, FlaggedTicket
from app.utils.decorators         import role_required
from app.utils.helpers            import CATEGORY_KEYWORDS, CATEGORY_SUBCATEGORY_MAP
from app.services.notifications   import (
    notify_status_update, notify_staff_reply,
    notify_ticket_resolved, notify_ticket_rejected,
    notify_progress_update, notify_sla_breach,
)
from app.services.realtime import publish_user_event
from app.forms.staff_forms import (
    UpdateTicketForm, ResolveTicketForm,
    ReplyForm, StaffThreadReplyForm,
    EscalationRequestForm, StaffReassignmentRequestForm,
    StaffTicketFilterForm, UpdatePriorityForm,
)

staff_bp = Blueprint('staff', __name__)


def _resolve_view_mode(default='list'):
    mode = request.args.get('view', default, type=str).strip().lower()
    return mode if mode in ('list', 'compact') else default


def _publish_ticket_activity(ticket: Ticket, action: str, actor_id: int, extra: dict = None):
    recipients = {ticket.StudentId, actor_id}
    if ticket.StaffId:
        recipients.add(ticket.StaffId)
    admin_ids = [u.UserId for u in User.query.filter_by(Role=RoleEnum.Admin, IsActive=True).all()]
    recipients.update(admin_ids)

    payload = {
        'ticket_id': ticket.TicketId,
        'action': action,
        'actor_id': actor_id,
        'status': ticket.Status.value if ticket.Status else None,
        'priority': ticket.Priority.value if ticket.Priority else None,
    }
    if extra:
        payload.update(extra)

    for uid in recipients:
        if uid:
            publish_user_event(uid, 'ticket_activity', payload)

_STATUS_MAP = {
    'In Progress': (StatusEnum.InProgress, UpdateStatusEnum.InProgress),
    'Rejected'   : (StatusEnum.Rejected,   UpdateStatusEnum.Rejected),
}


_HIGH_PRIORITY_KEYWORDS = {
    'harassment', 'assault', 'unsafe', 'threat', 'violence', 'discrimination',
    'abuse', 'emergency', 'medical', 'fraud', 'security', 'intimidation'
}
_MEDIUM_PRIORITY_KEYWORDS = {
    'wifi', 'registration', 'result', 'grade', 'exam', 'lecturer', 'blackboard',
    'payment', 'accommodation', 'transport', 'access', 'password', 'attendance'
}


def _suggest_priority(ticket: Ticket) -> str:
    text = f"{ticket.Title or ''} {ticket.Description or ''}".lower()
    if any(keyword in text for keyword in _HIGH_PRIORITY_KEYWORDS):
        return 'High'
    if any(keyword in text for keyword in _MEDIUM_PRIORITY_KEYWORDS):
        return 'Medium'

    keyword_hits = 0
    for words in CATEGORY_KEYWORDS.values():
        keyword_hits += sum(1 for word in words if word.lower() in text)
    if keyword_hits >= 3:
        return 'Medium'
    return 'Low'


def _priority_gate_blocked(ticket: Ticket) -> bool:
    return ticket.Priority is None


@staff_bp.route('/recurring-issues')
@login_required
@role_required('Staff')
def recurring_issues():
    status = request.args.get('status', 'all', type=str)
    if status not in ('all', 'active', 'dismissed'):
        status = 'all'

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    if per_page not in (10, 15, 25, 50, 100):
        per_page = 15

    my_ticket_ids = [
        row[0] for row in db.session.query(Ticket.TicketId)
        .filter(Ticket.StaffId == current_user.UserId)
        .all()
    ]

    if not my_ticket_ids:
        return render_template(
            'staff/recurring_issues.html',
            flags=[],
            pagination=None,
            status=status,
            linked_counts={},
        )

    query = (
        TicketFlag.query
        .join(FlaggedTicket, FlaggedTicket.FlagId == TicketFlag.FlagId)
        .filter(FlaggedTicket.TicketId.in_(my_ticket_ids))
        .distinct()
    )
    if status != 'all':
        query = query.filter(TicketFlag.Status == status)

    query = query.order_by(
        TicketFlag.Status.asc(),
        TicketFlag.TicketCount.desc(),
        TicketFlag.UpdatedAt.desc(),
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    flags = pagination.items

    flag_ids = [f.FlagId for f in flags]
    linked_counts = {}
    if flag_ids:
        linked_counts = {
            row.FlagId: row.count
            for row in (
                db.session.query(
                    FlaggedTicket.FlagId,
                    db.func.count(FlaggedTicket.TicketId).label('count'),
                )
                .filter(
                    FlaggedTicket.FlagId.in_(flag_ids),
                    FlaggedTicket.TicketId.in_(my_ticket_ids),
                )
                .group_by(FlaggedTicket.FlagId)
                .all()
            )
        }

    return render_template(
        'staff/recurring_issues.html',
        flags=flags,
        pagination=pagination,
        status=status,
        linked_counts=linked_counts,
    )


@staff_bp.route('/recurring-issues/<int:flag_id>/tickets')
@login_required
@role_required('Staff')
def recurring_issue_tickets(flag_id):
    flag = TicketFlag.query.get_or_404(flag_id)

    allowed = (
        db.session.query(FlaggedTicket.Id)
        .join(Ticket, Ticket.TicketId == FlaggedTicket.TicketId)
        .filter(
            FlaggedTicket.FlagId == flag_id,
            Ticket.StaffId == current_user.UserId,
        )
        .first()
    )
    if not allowed:
        abort(403)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    if per_page not in (10, 15, 25, 50, 100):
        per_page = 15

    query = (
        Ticket.query
        .join(FlaggedTicket, FlaggedTicket.TicketId == Ticket.TicketId)
        .filter(
            FlaggedTicket.FlagId == flag.FlagId,
            Ticket.StaffId == current_user.UserId,
        )
        .order_by(Ticket.CreatedAt.desc())
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    view_mode = _resolve_view_mode('list')

    return render_template(
        'staff/flagged_tickets.html',
        flag=flag,
        tickets=pagination.items,
        pagination=pagination,
        view_mode=view_mode,
    )


@staff_bp.route('/flags/<int:flag_id>/dismiss', methods=['POST'])
@login_required
@role_required('Staff')
def dismiss_flag(flag_id):
    my_ticket_ids = [
        row[0] for row in db.session.query(Ticket.TicketId)
        .filter(Ticket.StaffId == current_user.UserId)
        .all()
    ]

    if not my_ticket_ids:
        abort(403)

    allowed = (
        db.session.query(FlaggedTicket.Id)
        .filter(
            FlaggedTicket.FlagId == flag_id,
            FlaggedTicket.TicketId.in_(my_ticket_ids),
        )
        .first()
    )
    if not allowed:
        abort(403)

    flag = TicketFlag.query.get_or_404(flag_id)
    if flag.Status != 'dismissed':
        flag.Status = 'dismissed'
        db.session.commit()
        flash(f'Flag for "{flag.Category} / {flag.Keyword}" dismissed.', 'info')
    else:
        flash('Flag is already dismissed.', 'info')

    next_url = request.form.get('next', '').strip()
    if next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('staff.recurring_issues'))


@staff_bp.route('/dashboard')
@login_required
@role_required('Staff')
def dashboard():
    from app.utils.sorting import apply_sort
    filter_form  = StaffTicketFilterForm(request.args)
    view_mode = _resolve_view_mode('list')
    query        = Ticket.query.filter_by(StaffId=current_user.UserId)
    selected_categories = [
        c for c in request.args.getlist('category')
        if c in CATEGORY_SUBCATEGORY_MAP
    ]
    if not selected_categories and filter_form.category.data:
        selected_categories = [filter_form.category.data]

    selected_subcategories = [s for s in request.args.getlist('sub_category') if s]
    if not selected_subcategories and filter_form.sub_category.data:
        selected_subcategories = [filter_form.sub_category.data]

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
    if selected_categories:
        query = query.filter(Ticket.Category.in_(selected_categories))
    if selected_subcategories:
        query = query.filter(Ticket.SubCategory.in_(selected_subcategories))
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

    for t in all_assigned:
        if t.is_response_sla_overdue:
            notify_sla_breach(t, 'first_response')
        if t.is_resolution_sla_overdue:
            notify_sla_breach(t, 'resolution')
    db.session.commit()

    resolved_t   = [t for t in all_assigned
                    if t.Status == StatusEnum.Resolved and t.ResolvedAt]
    avg_hrs      = None
    if resolved_t:
        avg_hrs = round(
            sum((t.ResolvedAt - t.CreatedAt).total_seconds() for t in resolved_t)
            / len(resolved_t) / 3600, 1
        )

    # ── Flags ONLY for tickets assigned to THIS staff member ──────────────
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
            row[0] for row in
            db.session.query(FlaggedTicket.TicketId)
            .join(TicketFlag, TicketFlag.FlagId == FlaggedTicket.FlagId)
            .filter(
                FlaggedTicket.TicketId.in_(my_ticket_ids),
                FlaggedTicket.FlagId.in_(my_flag_ids),
                TicketFlag.Status == 'active',
            ).all()
        } if my_flag_ids else set()

        ticket_active_flags = {}
        if my_flag_ids:
            rows = (
                db.session.query(FlaggedTicket.TicketId, TicketFlag.FlagId)
                .join(TicketFlag, TicketFlag.FlagId == FlaggedTicket.FlagId)
                .filter(
                    FlaggedTicket.TicketId.in_(my_ticket_ids),
                    TicketFlag.Status == 'active',
                )
                .all()
            )
            for ticket_id, flag_id in rows:
                ticket_active_flags.setdefault(ticket_id, []).append(flag_id)
    else:
        active_flags = []
        flagged_ids  = set()
        ticket_active_flags = {}

    suggested_priorities = {t.TicketId: _suggest_priority(t) for t in tickets}
    new_ticket_ids = {t.TicketId for t in all_assigned if t.Priority is None}

    stats = {
        'total'       : len(all_assigned),
        'in_progress' : sum(1 for t in all_assigned if t.Status == StatusEnum.InProgress),
        'pending_info': sum(1 for t in all_assigned if t.Status == StatusEnum.PendingInfo),
        'resolved'    : len(resolved_t),
        'overdue'     : sum(
            1 for t in all_assigned if t.is_response_sla_overdue or t.is_resolution_sla_overdue
        ),
        'avg_hours': avg_hrs,
        'new_tickets': len(new_ticket_ids),
    }

    category_options = list(CATEGORY_SUBCATEGORY_MAP.keys())
    if selected_categories:
        available_subcategories = sorted({
            s for c in selected_categories for s in CATEGORY_SUBCATEGORY_MAP.get(c, [])
        })
    else:
        available_subcategories = sorted({
            s for subs in CATEGORY_SUBCATEGORY_MAP.values() for s in subs
        })

    return render_template(
        'staff/dashboard.html',
        tickets=tickets,
        pagination=pagination,
        filter_form=filter_form,
        view_mode=view_mode,
        category_options=category_options,
        available_subcategories=available_subcategories,
        selected_categories=selected_categories,
        selected_subcategories=selected_subcategories,
        subcategory_map=CATEGORY_SUBCATEGORY_MAP,
        stats=stats,
        flagged_ticket_ids=flagged_ids,
        active_flags=active_flags,
        ticket_active_flags=ticket_active_flags,
        suggested_priorities=suggested_priorities,
        new_ticket_ids=new_ticket_ids,
    )


@staff_bp.route('/new-tickets')
@login_required
@role_required('Staff')
def new_tickets():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    if per_page not in (10, 15, 25, 50, 100):
        per_page = 15

    query = (
        Ticket.query
        .filter_by(StaffId=current_user.UserId)
        .filter(Ticket.Priority.is_(None))
        .order_by(Ticket.CreatedAt.desc())
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    tickets = pagination.items
    view_mode = _resolve_view_mode('list')

    suggested_priorities = {t.TicketId: _suggest_priority(t) for t in tickets}

    return render_template(
        'staff/new_tickets.html',
        tickets=tickets,
        pagination=pagination,
        view_mode=view_mode,
        suggested_priorities=suggested_priorities,
    )


@staff_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Staff')
def view_ticket(ticket_id):
    from app.models.reassignment_request import ReassignmentRequest
    ticket  = _get_staff_ticket(ticket_id)

    if ticket.is_response_sla_overdue:
        notify_sla_breach(ticket, 'first_response')
    if ticket.is_resolution_sla_overdue:
        notify_sla_breach(ticket, 'resolution')
    db.session.commit()

    updates = (ticket.updates
               .filter_by(ParentUpdateId=None)
               .order_by(TicketUpdate.CreatedAt.asc())
               .all())
    student_comments = (TicketComment.query
                        .filter_by(TicketId=ticket.TicketId)
                        .order_by(TicketComment.CreatedAt.desc())
                        .all())
    attachments       = ticket.attachments.filter_by(UpdateId=None).all()
    update_form       = UpdateTicketForm()
    priority_form     = UpdatePriorityForm()
    resolve_form      = ResolveTicketForm()
    reply_form        = ReplyForm()
    thread_reply_form = StaffThreadReplyForm()

    if ticket.Priority:
        priority_form.priority.data = ticket.Priority.value

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
        student_comments=student_comments,
        attachments=attachments,
        update_form=update_form,
        priority_form=priority_form,
        resolve_form=resolve_form,
        reply_form=reply_form,
        thread_reply_form=thread_reply_form,
        escalation_form=escalation_form,
        pending_escalation=pending_escalation,
        reassign_form=reassign_form,
        pending_reassign=pending_reassign,
        locked_thread_ids=locked_thread_ids,
        suggested_priority=_suggest_priority(ticket),
        priority_required=_priority_gate_blocked(ticket),
    )


@staff_bp.route('/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = UpdateTicketForm()
    if form.validate_on_submit():
        if _priority_gate_blocked(ticket) and form.status.data == 'In Progress':
            flash('Set ticket priority before moving status to In Progress.', 'warning')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

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
        _publish_ticket_activity(ticket, 'ticket_status_changed', current_user.UserId)
        flash(f'Status updated to "{form.status.data}".', 'success')
    else:
        flash('Please fill in all required fields.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


@staff_bp.route('/ticket/<int:ticket_id>/update-priority', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket_priority(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    form   = UpdatePriorityForm()
    if form.validate_on_submit():
        old_priority = ticket.Priority.value if ticket.Priority else 'Not Set'
        ticket.Priority = PriorityEnum(form.priority.data)
        ticket.UpdatedAt = datetime.utcnow()
        db.session.add(TicketUpdate(
            TicketId=ticket.TicketId,
            UserId=current_user.UserId,
            Comment=(
                f'[PRIORITY UPDATED] {old_priority} -> {form.priority.data}. '
                f'Reason: {form.reason.data.strip()}'
            ),
            IsReplyThread=False,
        ))
        db.session.commit()
        _publish_ticket_activity(ticket, 'ticket_priority_changed', current_user.UserId)
        flash(f'Priority updated to "{form.priority.data}".', 'success')
    else:
        flash('Please select a priority and provide a reason (min 5 characters).', 'danger')
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
        _publish_ticket_activity(ticket, 'ticket_resolved', current_user.UserId)
        flash('Ticket marked as resolved.', 'success')
    else:
        flash('Please provide resolution details.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


@staff_bp.route('/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
@role_required('Staff')
def reply_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    if _priority_gate_blocked(ticket):
        flash('Set ticket priority before posting internal activity updates.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

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
        _publish_ticket_activity(ticket, 'ticket_reply_added', current_user.UserId)
        flash('Reply sent. Status set to Pending Info.', 'success')
    else:
        flash('Message cannot be empty.', 'danger')
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


@staff_bp.route('/ticket/<int:ticket_id>/thread-reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Staff')
def thread_reply(ticket_id, update_id):
    ticket = _get_staff_ticket(ticket_id)
    if _priority_gate_blocked(ticket):
        flash('Set ticket priority before posting internal activity updates.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

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
        _publish_ticket_activity(ticket, 'ticket_thread_reply_added', current_user.UserId)
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
        _publish_ticket_activity(ticket, 'ticket_escalation_requested', current_user.UserId)
        from app.services.notifications import _send_admin_emails
        admin_ticket_url = url_for('admin.ticket_detail', ticket_id=ticket_id, _external=True)
        _send_admin_emails(
            f'Escalation Request — Ticket #{ticket_id}',
            (f'{current_user.FullName} has requested escalation of ticket '
             f'"#{ticket_id} {ticket.Title}" to {target_dept.Name}.\n\n'
             f'Reason: {form.reason.data.strip()}\n\n'
             f'Review it at: {admin_ticket_url}'),
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
        _publish_ticket_activity(ticket, 'ticket_reassignment_requested', current_user.UserId)
        from app.services.notifications import _send_admin_emails
        admin_ticket_url = url_for('admin.ticket_detail', ticket_id=ticket_id, _external=True)
        _send_admin_emails(
            f'Reassignment Request — Ticket #{ticket_id}',
            (f'{current_user.FullName} has requested reassignment of ticket '
             f'"#{ticket_id} {ticket.Title}" to {target.FullName}.\n\n'
             f'Reason: {form.reason.data.strip()}\n\n'
             f'Review it at: {admin_ticket_url}'),
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