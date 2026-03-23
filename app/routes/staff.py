from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, jsonify, current_app
)
from flask_login import login_required, current_user
from datetime import datetime
import os

from app import db
from app.models.ticket            import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update     import TicketUpdate, UpdateStatusEnum
from app.models.ticket_chat_message import TicketChatMessage
from app.models.ticket_chat_attachment import TicketChatAttachment
from app.models.ticket_chat_presence import TicketChatPresence
from app.models.staff_macro       import StaffMacro
from app.models.department        import Department
from app.models.escalation        import EscalationRequest
from app.models.reassignment_request import ReassignmentRequest
from app.models.admin_notification import AdminNotification
from app.models.user              import User, RoleEnum
from app.models.ticket_comment    import TicketComment
from app.models.ticket_flag       import TicketFlag, FlaggedTicket
from app.utils.decorators         import role_required
from app.utils.helpers            import CATEGORY_KEYWORDS, CATEGORY_SUBCATEGORY_MAP, allowed_file, attachment_url
from app.services.notifications   import (
    notify_status_update, notify_staff_reply,
    notify_ticket_resolved, notify_ticket_rejected,
    notify_progress_update, notify_sla_breach, notify_live_chat_message,
)
from app.services.realtime import publish_user_event
from app.forms.staff_forms import (
    UpdateTicketForm, ResolveTicketForm,
    ReplyForm, StaffThreadReplyForm,
    EscalationRequestForm, StaffReassignmentRequestForm,
    StaffTicketFilterForm, UpdatePriorityForm,
    LiveChatMessageForm, StaffMacroForm,
)
from app.forms.student_forms import TicketCommentForm

staff_bp = Blueprint('staff', __name__)


def _resolve_view_mode(default='list'):
    mode = request.args.get('view', default, type=str).strip().lower()
    return mode if mode in ('list', 'compact') else default


def _ticket_action_redirect(ticket_id: int):
    referrer = (request.referrer or '').lower()
    if referrer.endswith(f'/staff/ticket/{ticket_id}/actions'):
        return redirect(url_for('staff.ticket_actions', ticket_id=ticket_id))
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


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
    'Pending Info': (StatusEnum.PendingInfo, UpdateStatusEnum.PendingInfo),
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


def _is_terminal_ticket_status(ticket: Ticket) -> bool:
    return ticket.Status in {StatusEnum.Resolved, StatusEnum.Rejected}


def _blocked_terminal_action_redirect(ticket: Ticket):
    if not _is_terminal_ticket_status(ticket):
        return None
    flash(f'Ticket is already {ticket.Status.value}. Actions are disabled.', 'warning')
    return _ticket_action_redirect(ticket.TicketId)


CHAT_BATCH_LIMIT = 40


def _save_update_attachments(update_id: int):
    for file in request.files.getlist('attachments'):
        if file and file.filename and allowed_file(file.filename):
            from werkzeug.utils import secure_filename

            upload_root = current_app.config['UPLOAD_FOLDER']
            update_dir = os.path.join(upload_root, f'update_{update_id}')
            os.makedirs(update_dir, exist_ok=True)

            filename = secure_filename(file.filename)
            filepath = os.path.join(update_dir, filename)
            file.save(filepath)
            from app.models.attachment import Attachment

            db.session.add(Attachment(UpdateId=update_id, FileName=filename, FilePath=filepath))


def _chat_related_staff_ids(ticket: Ticket) -> set[int]:
    related = set()

    reassign_rows = ReassignmentRequest.query.filter(
        ReassignmentRequest.TicketId == ticket.TicketId,
        db.or_(
            ReassignmentRequest.RequestedById.isnot(None),
            ReassignmentRequest.TargetStaffId.isnot(None),
        ),
    ).all()
    for row in reassign_rows:
        if row.RequestedById:
            related.add(row.RequestedById)
        if row.TargetStaffId:
            related.add(row.TargetStaffId)

    escalation_rows = EscalationRequest.query.filter(
        EscalationRequest.TicketId == ticket.TicketId,
        EscalationRequest.RequestedById.isnot(None),
    ).all()
    for row in escalation_rows:
        related.add(row.RequestedById)

    return related


def _chat_participant_ids(ticket: Ticket) -> set[int]:
    participant_ids = {ticket.StudentId}
    if ticket.StaffId:
        participant_ids.add(ticket.StaffId)
    participant_ids.update(_chat_related_staff_ids(ticket))

    admin_ids = [u.UserId for u in User.query.filter_by(Role=RoleEnum.Admin, IsActive=True).all()]
    participant_ids.update(admin_ids)
    return {uid for uid in participant_ids if uid}


def _chat_notification_targets(ticket: Ticket, sender_id: int) -> tuple[set[int], set[int]]:
    participants = _chat_participant_ids(ticket)
    related_staff = _chat_related_staff_ids(ticket)

    recipients = {uid for uid in participants if uid != sender_id}
    notification_blocked = {
        uid for uid in related_staff
        if uid not in {ticket.StaffId, ticket.StudentId} and uid != sender_id
    }
    recipients -= notification_blocked
    return recipients, notification_blocked


def _can_access_chat(ticket: Ticket, user_id: int) -> bool:
    return user_id in _chat_participant_ids(ticket)


def _touch_chat_presence(ticket_id: int, user_id: int):
    presence = TicketChatPresence.query.filter_by(TicketId=ticket_id, UserId=user_id).first()
    if not presence:
        presence = TicketChatPresence(TicketId=ticket_id, UserId=user_id, LastSeenAt=datetime.utcnow())
        db.session.add(presence)
    else:
        presence.LastSeenAt = datetime.utcnow()


def _serialize_chat_message(message: TicketChatMessage) -> dict:
    return {
        'chat_message_id': message.ChatMessageId,
        'ticket_id': message.TicketId,
        'user_id': message.UserId,
        'author_name': message.author.FullName if message.author else 'Unknown',
        'author_role': message.author.Role.value if message.author and message.author.Role else 'Unknown',
        'message': message.Message,
        'created_at': message.CreatedAt.isoformat() if message.CreatedAt else None,
        'attachments': [
            {
                'name': a.FileName,
                'url': attachment_url(a),
            }
            for a in message.attachments.order_by(TicketChatAttachment.ChatAttachmentId.asc()).all()
        ],
    }


def _chat_participant_badges(ticket: Ticket) -> list[dict]:
    participants = (
        db.session.query(User, db.func.max(TicketChatPresence.LastSeenAt).label('last_seen'))
        .join(TicketChatMessage, TicketChatMessage.UserId == User.UserId)
        .outerjoin(
            TicketChatPresence,
            db.and_(
                TicketChatPresence.UserId == User.UserId,
                TicketChatPresence.TicketId == ticket.TicketId,
            ),
        )
        .filter(TicketChatMessage.TicketId == ticket.TicketId)
        .group_by(User.UserId)
        .order_by(User.FullName.asc())
        .all()
    )

    online_window = int(current_app.config.get('CHAT_ONLINE_WINDOW_SECONDS', 60))
    cutoff = datetime.utcnow().timestamp() - online_window
    badges = []
    for user, last_seen in participants:
        online = bool(last_seen and last_seen.timestamp() >= cutoff)
        badges.append({
            'user_id': user.UserId,
            'name': user.FullName,
            'role': user.Role.value,
            'is_online': online,
        })
    return badges


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

    def _format_minutes(minutes: int) -> str:
        total = max(int(minutes), 0)
        hours, mins = divmod(total, 60)
        if hours and mins:
            return f'{hours}h {mins}m'
        if hours:
            return f'{hours}h'
        return f'{mins}m'

    now = datetime.utcnow()
    sla_watchlist = []

    for t in all_assigned:
        if t.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
            continue

        first_due = t.first_response_due_at
        resolution_due = t.resolution_due_at

        if t.is_resolution_sla_overdue:
            overdue_min = int((now - resolution_due).total_seconds() // 60)
            sla_watchlist.append({
                'ticket': t,
                'level': 'resolution_overdue',
                'title': 'Resolution SLA breached',
                'time_text': f'Overdue by {_format_minutes(overdue_min)}',
                'sort_rank': 0,
                'sort_metric': -overdue_min,
            })
            continue

        if t.is_response_sla_overdue:
            overdue_min = int((now - first_due).total_seconds() // 60)
            sla_watchlist.append({
                'ticket': t,
                'level': 'response_overdue',
                'title': 'First response SLA breached',
                'time_text': f'Overdue by {_format_minutes(overdue_min)}',
                'sort_rank': 1,
                'sort_metric': -overdue_min,
            })
            continue

        first_response_remaining = float('inf')
        if not t.has_staff_response:
            first_response_remaining = (first_due - now).total_seconds() / 60
        resolution_remaining = (resolution_due - now).total_seconds() / 60

        if first_response_remaining <= resolution_remaining:
            due_minutes = int(max(first_response_remaining, 0))
            level = 'response_risk'
            title = 'First response SLA risk'
        else:
            due_minutes = int(max(resolution_remaining, 0))
            level = 'resolution_risk'
            title = 'Resolution SLA risk'

        sla_watchlist.append({
            'ticket': t,
            'level': level,
            'title': title,
            'time_text': f'Due in {_format_minutes(due_minutes)}',
            'sort_rank': 2,
            'sort_metric': due_minutes,
        })

    sla_watchlist.sort(key=lambda row: (row['sort_rank'], row['sort_metric']))

    if not sla_watchlist:
        fallback_tickets = sorted(all_assigned, key=lambda t: t.UpdatedAt or datetime.min, reverse=True)
        for t in fallback_tickets[:8]:
            label = 'Recently resolved' if t.Status == StatusEnum.Resolved else (
                'Recently rejected' if t.Status == StatusEnum.Rejected else 'Needs monitoring'
            )
            sla_watchlist.append({
                'ticket': t,
                'level': 'fallback',
                'title': label,
                'time_text': f'Updated {t.UpdatedAt.strftime("%d %b %Y %H:%M") if t.UpdatedAt else "recently"}',
                'sort_rank': 9,
                'sort_metric': 0,
            })

    if not sla_watchlist:
        sla_watchlist.append({
            'ticket': None,
            'level': 'empty',
            'title': 'No assigned tickets yet',
            'time_text': 'Tickets assigned to you will appear here.',
            'sort_rank': 10,
            'sort_metric': 0,
        })

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
        sla_watchlist=sla_watchlist,
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


@staff_bp.route('/reassigned-tickets')
@login_required
@role_required('Staff')
def reassigned_tickets():
    scope = request.args.get('scope', 'to_me', type=str).strip().lower()
    if scope not in ('to_me', 'from_me'):
        scope = 'to_me'

    user_id = current_user.UserId
    user_name = (current_user.FullName or '').strip()
    items = []

    approved_reassignments = (
        ReassignmentRequest.query
        .filter(ReassignmentRequest.Status == 'Approved')
        .order_by(ReassignmentRequest.ResolvedAt.desc(), ReassignmentRequest.RequestId.desc())
        .all()
    )
    for req in approved_reassignments:
        if scope == 'to_me' and req.TargetStaffId != user_id:
            continue
        if scope == 'from_me' and req.RequestedById != user_id:
            continue
        items.append({
            'ticket': req.ticket,
            'source': 'Reassignment',
            'resolved_at': req.ResolvedAt or req.CreatedAt,
            'from_staff': req.requested_by.FullName if req.requested_by else 'Unknown',
            'to_staff': req.target_staff.FullName if req.target_staff else 'Unknown',
            'note': req.Reason,
        })

    approved_escalations = (
        EscalationRequest.query
        .filter(EscalationRequest.Status == 'Approved')
        .order_by(EscalationRequest.ResolvedAt.desc(), EscalationRequest.EscalationId.desc())
        .all()
    )
    for esc in approved_escalations:
        assigned_to_me = False
        if esc.ticket and esc.ticket.StaffId == user_id:
            assigned_to_me = True
        elif user_name:
            assigned_to_me = TicketUpdate.query.filter(
                TicketUpdate.TicketId == esc.TicketId,
                TicketUpdate.StatusChange == UpdateStatusEnum.Assigned,
                TicketUpdate.Comment.ilike(f'%assigned to {user_name}%'),
            ).first() is not None

        if scope == 'to_me' and not assigned_to_me:
            continue
        if scope == 'from_me' and esc.RequestedById != user_id:
            continue

        target_name = esc.ticket.staff.FullName if esc.ticket and esc.ticket.staff else 'Unknown'
        items.append({
            'ticket': esc.ticket,
            'source': 'Escalation',
            'resolved_at': esc.ResolvedAt or esc.CreatedAt,
            'from_staff': esc.requested_by.FullName if esc.requested_by else 'Unknown',
            'to_staff': target_name,
            'note': esc.Reason,
        })

    items.sort(key=lambda row: row['resolved_at'] or datetime.min, reverse=True)

    return render_template(
        'staff/reassigned_tickets.html',
        scope=scope,
        items=items,
    )


@staff_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Staff')
def view_ticket(ticket_id):
    from app.models.reassignment_request import ReassignmentRequest
    ticket, access_mode = _get_staff_ticket_access(ticket_id)
    is_restricted_view = access_mode == 'restricted'

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
                        .filter_by(TicketId=ticket.TicketId, ParentCommentId=None)
                        .order_by(TicketComment.CreatedAt.desc())
                        .all())
    attachments       = ticket.attachments.filter_by(UpdateId=None).all()
    update_form       = UpdateTicketForm()
    priority_form     = UpdatePriorityForm()
    resolve_form      = ResolveTicketForm()
    reply_form        = ReplyForm()
    thread_reply_form = StaffThreadReplyForm()
    live_chat_form    = LiveChatMessageForm()
    comment_form      = TicketCommentForm()

    chat_messages = (TicketChatMessage.query
                     .filter_by(TicketId=ticket.TicketId)
                     .order_by(TicketChatMessage.ChatMessageId.asc())
                     .limit(100)
                     .all())
    chat_participants = _chat_participant_badges(ticket)

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
        live_chat_form=live_chat_form,
        comment_form=comment_form,
        chat_messages=chat_messages,
        chat_participants=chat_participants,
        escalation_form=escalation_form,
        pending_escalation=pending_escalation,
        reassign_form=reassign_form,
        pending_reassign=pending_reassign,
        locked_thread_ids=locked_thread_ids,
        suggested_priority=_suggest_priority(ticket),
        priority_required=_priority_gate_blocked(ticket),
        is_restricted_view=is_restricted_view,
    )


@staff_bp.route('/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    locked_redirect = _blocked_terminal_action_redirect(ticket)
    if locked_redirect:
        return locked_redirect

    form   = UpdateTicketForm()
    if form.validate_on_submit():
        if _priority_gate_blocked(ticket) and form.status.data == 'In Progress':
            flash('Set ticket priority before moving status to In Progress.', 'warning')
            return _ticket_action_redirect(ticket_id)

        mapping = _STATUS_MAP.get(form.status.data)
        if not mapping:
            flash('Invalid status.', 'danger')
            return _ticket_action_redirect(ticket_id)
        new_status, new_update_status = mapping
        ticket.Status    = new_status
        ticket.UpdatedAt = datetime.utcnow()
        update_row = TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment=form.comment.data.strip(), StatusChange=new_update_status,
            IsReplyThread=False,
        )
        db.session.add(update_row)
        db.session.flush()
        _save_update_attachments(update_row.UpdateId)
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
    return _ticket_action_redirect(ticket_id)


@staff_bp.route('/ticket/<int:ticket_id>/update-priority', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket_priority(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    locked_redirect = _blocked_terminal_action_redirect(ticket)
    if locked_redirect:
        return locked_redirect

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
    return _ticket_action_redirect(ticket_id)


@staff_bp.route('/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@role_required('Staff')
def resolve_ticket(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    locked_redirect = _blocked_terminal_action_redirect(ticket)
    if locked_redirect:
        return locked_redirect

    form   = ResolveTicketForm()
    if form.validate_on_submit():
        ticket.Status     = StatusEnum.Resolved
        ticket.ResolvedAt = datetime.utcnow()
        ticket.UpdatedAt  = datetime.utcnow()
        update_row = TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment=f'[RESOLVED] {form.resolution.data.strip()}',
            StatusChange=UpdateStatusEnum.Resolved, IsReplyThread=False,
        )
        db.session.add(update_row)
        db.session.flush()
        _save_update_attachments(update_row.UpdateId)
        notify_ticket_resolved(ticket, current_user)
        db.session.commit()
        _publish_ticket_activity(ticket, 'ticket_resolved', current_user.UserId)
        flash('Ticket marked as resolved.', 'success')
    else:
        flash('Please provide resolution details.', 'danger')
    return _ticket_action_redirect(ticket_id)


@staff_bp.route('/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
@role_required('Staff')
def reply_ticket(ticket_id):
    _get_staff_ticket(ticket_id)
    flash('Reply threads have moved to Live Chat. Use the Live Chat tab for staff-student conversation.', 'info')
    return _ticket_action_redirect(ticket_id)


@staff_bp.route('/ticket/<int:ticket_id>/thread-reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Staff')
def thread_reply(ticket_id, update_id):
    _get_staff_ticket_access(ticket_id)
    _ = update_id
    flash('Status Update reply threads are disabled for staff. Continue communication in Live Chat.', 'info')
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


@staff_bp.route('/ticket/<int:ticket_id>/actions')
@login_required
@role_required('Staff')
def ticket_actions(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    actions_locked = _is_terminal_ticket_status(ticket)

    update_form = UpdateTicketForm()
    priority_form = UpdatePriorityForm()
    resolve_form = ResolveTicketForm()

    if ticket.Priority:
        priority_form.priority.data = ticket.Priority.value

    escalation_form = EscalationRequestForm()
    other_depts = Department.query.filter(Department.DepartmentId != ticket.DepartmentId).order_by(Department.Name).all()
    escalation_form.target_dept.choices = [(d.DepartmentId, d.Name) for d in other_depts]
    pending_escalation = EscalationRequest.query.filter_by(TicketId=ticket_id, Status='Pending').first()

    reassign_form = StaffReassignmentRequestForm()
    dept_colleagues = User.query.filter(
        User.Role == RoleEnum.Staff,
        User.IsActive == True,  # noqa: E712
        User.DepartmentId == current_user.DepartmentId,
        User.UserId != current_user.UserId,
    ).order_by(User.FullName).all()
    reassign_form.target_staff.choices = [(u.UserId, u.FullName) for u in dept_colleagues]
    pending_reassign = ReassignmentRequest.query.filter_by(TicketId=ticket_id, Status='Pending').first()

    return render_template(
        'staff/ticket_actions.html',
        ticket=ticket,
        actions_locked=actions_locked,
        update_form=update_form,
        priority_form=priority_form,
        resolve_form=resolve_form,
        escalation_form=escalation_form,
        pending_escalation=pending_escalation,
        reassign_form=reassign_form,
        pending_reassign=pending_reassign,
        suggested_priority=_suggest_priority(ticket),
        priority_required=_priority_gate_blocked(ticket),
    )


@staff_bp.route('/ticket/<int:ticket_id>/chat/messages')
@login_required
@role_required('Staff')
def list_chat_messages(ticket_id):
    ticket, _ = _get_staff_ticket_access(ticket_id)
    if not _can_access_chat(ticket, current_user.UserId):
        abort(403)

    since_id = request.args.get('since_id', default=0, type=int)
    if since_id < 0:
        since_id = 0

    rows = (TicketChatMessage.query
            .filter(TicketChatMessage.TicketId == ticket_id,
                    TicketChatMessage.ChatMessageId > since_id)
            .order_by(TicketChatMessage.ChatMessageId.asc())
            .limit(CHAT_BATCH_LIMIT)
            .all())

    _touch_chat_presence(ticket_id, current_user.UserId)
    db.session.commit()

    next_since = since_id
    if rows:
        next_since = rows[-1].ChatMessageId

    return jsonify({
        'messages': [_serialize_chat_message(row) for row in rows],
        'participants': _chat_participant_badges(ticket),
        'next_since_id': next_since,
    })


@staff_bp.route('/ticket/<int:ticket_id>/chat/send', methods=['POST'])
@login_required
@role_required('Staff')
def send_chat_message(ticket_id):
    ticket, _ = _get_staff_ticket_access(ticket_id)
    if not _can_access_chat(ticket, current_user.UserId):
        abort(403)

    if ticket.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
        flash('Live chat is closed for resolved or rejected tickets.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id, _anchor='staff-livechat-pane'))

    form = LiveChatMessageForm()
    if not form.validate_on_submit():
        flash('Chat message must contain between 1 and 2000 characters.', 'danger')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id, _anchor='staff-livechat-pane'))

    message = TicketChatMessage(
        TicketId=ticket_id,
        UserId=current_user.UserId,
        Message=form.message.data.strip(),
    )
    db.session.add(message)
    db.session.flush()

    for file in request.files.getlist('attachments'):
        if file and file.filename and allowed_file(file.filename):
            from werkzeug.utils import secure_filename

            upload_root = current_app.config['UPLOAD_FOLDER']
            chat_dir = os.path.join(upload_root, f'chat_{message.ChatMessageId}')
            os.makedirs(chat_dir, exist_ok=True)

            filename = secure_filename(file.filename)
            filepath = os.path.join(chat_dir, filename)
            file.save(filepath)
            db.session.add(TicketChatAttachment(
                ChatMessageId=message.ChatMessageId,
                FileName=filename,
                FilePath=filepath,
            ))

    _touch_chat_presence(ticket_id, current_user.UserId)
    ticket.UpdatedAt = datetime.utcnow()

    recipients, _ = _chat_notification_targets(ticket, current_user.UserId)
    notify_live_chat_message(ticket, current_user, sorted(recipients))

    db.session.commit()

    payload = {
        'ticket_id': ticket.TicketId,
        'chat_message_id': message.ChatMessageId,
        'sender_id': current_user.UserId,
    }
    for uid in _chat_participant_ids(ticket):
        publish_user_event(uid, 'chat_message', payload)

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id, _anchor='staff-livechat-pane'))


@staff_bp.route('/ticket/<int:ticket_id>/chat/heartbeat', methods=['POST'])
@login_required
@role_required('Staff')
def chat_heartbeat(ticket_id):
    ticket, _ = _get_staff_ticket_access(ticket_id)
    if not _can_access_chat(ticket, current_user.UserId):
        abort(403)

    _touch_chat_presence(ticket_id, current_user.UserId)
    db.session.commit()
    return jsonify({'ok': True})


@staff_bp.route('/macros', methods=['GET', 'POST'])
@login_required
@role_required('Staff')
def macros():
    form = StaffMacroForm()
    if form.validate_on_submit():
        macro = StaffMacro(
            UserId=current_user.UserId,
            Name=form.name.data.strip(),
            MacroType=form.macro_type.data.strip(),
            Content=form.content.data.strip(),
        )
        db.session.add(macro)
        db.session.commit()
        flash('Macro saved.', 'success')
        return redirect(url_for('staff.macros'))

    q = request.args.get('q', '', type=str).strip()
    macros_query = StaffMacro.query.filter_by(UserId=current_user.UserId)
    if q:
        macros_query = macros_query.filter(
            db.or_(
                StaffMacro.Name.ilike(f'%{q}%'),
                StaffMacro.MacroType.ilike(f'%{q}%'),
                StaffMacro.Content.ilike(f'%{q}%'),
            )
        )

    macro_rows = macros_query.order_by(StaffMacro.UpdatedAt.desc()).all()
    return render_template('staff/macros.html', form=form, macros=macro_rows, query=q)


@staff_bp.route('/macros/<int:macro_id>/delete', methods=['POST'])
@login_required
@role_required('Staff')
def delete_macro(macro_id):
    macro = StaffMacro.query.get_or_404(macro_id)
    if macro.UserId != current_user.UserId:
        abort(403)
    db.session.delete(macro)
    db.session.commit()
    flash('Macro deleted.', 'success')
    return redirect(url_for('staff.macros'))


@staff_bp.route('/macros/search')
@login_required
@role_required('Staff')
def search_macros():
    q = request.args.get('q', '', type=str).strip()
    query = StaffMacro.query.filter_by(UserId=current_user.UserId)
    if q:
        query = query.filter(
            db.or_(
                StaffMacro.Name.ilike(f'%{q}%'),
                StaffMacro.MacroType.ilike(f'%{q}%'),
                StaffMacro.Content.ilike(f'%{q}%'),
            )
        )

    rows = query.order_by(StaffMacro.UpdatedAt.desc()).limit(30).all()
    return jsonify({
        'items': [
            {
                'macro_id': row.MacroId,
                'name': row.Name,
                'macro_type': row.MacroType,
                'content': row.Content,
            }
            for row in rows
        ]
    })

@staff_bp.route('/ticket/<int:ticket_id>/escalate', methods=['POST'])
@login_required
@role_required('Staff')
def request_escalation(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    locked_redirect = _blocked_terminal_action_redirect(ticket)
    if locked_redirect:
        return locked_redirect

    form   = EscalationRequestForm()
    other_depts = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).all()
    form.target_dept.choices = [(d.DepartmentId, d.Name) for d in other_depts]

    if form.validate_on_submit():
        if EscalationRequest.query.filter_by(TicketId=ticket_id, Status='Pending').first():
            flash('An escalation is already pending.', 'warning')
            return _ticket_action_redirect(ticket_id)

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
    return _ticket_action_redirect(ticket_id)


# ── STAFF SELF-REASSIGNMENT REQUEST ──────────────────────────────────────────
@staff_bp.route('/ticket/<int:ticket_id>/request-reassign', methods=['POST'])
@login_required
@role_required('Staff')
def request_reassignment(ticket_id):
    ticket = _get_staff_ticket(ticket_id)
    locked_redirect = _blocked_terminal_action_redirect(ticket)
    if locked_redirect:
        return locked_redirect

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
            return _ticket_action_redirect(ticket_id)

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
    return _ticket_action_redirect(ticket_id)


def _get_staff_ticket(ticket_id: int) -> Ticket:
    ticket, access_mode = _get_staff_ticket_access(ticket_id)
    if access_mode != 'full':
        abort(403)
    return ticket


def _get_staff_ticket_access(ticket_id: int):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StaffId == current_user.UserId:
        return ticket, 'full'
    if _staff_has_restricted_access(ticket):
        return ticket, 'restricted'
    abort(403)


def _staff_has_restricted_access(ticket: Ticket) -> bool:
    user_id = current_user.UserId

    participated = TicketUpdate.query.filter_by(
        TicketId=ticket.TicketId,
        UserId=user_id,
    ).first() is not None
    if participated:
        return True

    reassignment_link = ReassignmentRequest.query.filter(
        ReassignmentRequest.TicketId == ticket.TicketId,
        db.or_(
            ReassignmentRequest.RequestedById == user_id,
            ReassignmentRequest.TargetStaffId == user_id,
        ),
    ).first() is not None
    if reassignment_link:
        return True

    escalation_link = EscalationRequest.query.filter_by(
        TicketId=ticket.TicketId,
        RequestedById=user_id,
    ).first() is not None
    return escalation_link