import os
from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, send_from_directory, current_app, jsonify
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.ticket        import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update import TicketUpdate, UpdateStatusEnum
from app.models.attachment    import Attachment
from app.models.department    import Department
from app.models.reopen_request import ReopenRequest
from app.models.admin_notification import AdminNotification
from app.models.user import User, RoleEnum
from app.models.ticket_vote import TicketVote
from app.models.ticket_comment import TicketComment
from app.models.comment_attachment import CommentAttachment
from app.models.comment_vote import CommentVote
from app.models.user_preference import UserPreference
from app.models.ticket_chat_message import TicketChatMessage
from app.models.ticket_chat_attachment import TicketChatAttachment
from app.models.ticket_chat_presence import TicketChatPresence
from app.models.escalation import EscalationRequest
from app.models.reassignment_request import ReassignmentRequest
from app.utils.decorators     import role_required
from app.utils.helpers        import (
    allowed_file,
    get_department_name_for_category, check_and_raise_flags,
    CATEGORY_SUBCATEGORY_MAP, attachment_url,
)
from app.utils.sorting        import apply_sort
from app.services.assignment  import auto_assign_ticket
from app.services.realtime import publish_user_event
from app.services.notifications import (
    notify_student_replied,
    notify_ticket_submitted,
    notify_social_vote,
    notify_social_comment,
    notify_live_chat_message,
)
from app.forms.student_forms  import (
    SubmitTicketForm, EditTicketForm, FeedbackForm,
    TicketFilterForm, StudentReplyForm, ReopenRequestForm,
    TicketCommentForm, SocialPreferenceForm, StudentLiveChatForm,
)

student_bp = Blueprint('student', __name__)

COMMENT_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
CHAT_BATCH_LIMIT = 40


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
    participants = {ticket.StudentId}
    if ticket.StaffId:
        participants.add(ticket.StaffId)
    participants.update(_chat_related_staff_ids(ticket))
    participants.update([u.UserId for u in User.query.filter_by(Role=RoleEnum.Admin, IsActive=True).all()])
    return {uid for uid in participants if uid}


def _chat_notification_targets(ticket: Ticket, sender_id: int) -> set[int]:
    participants = _chat_participant_ids(ticket)
    related_staff = _chat_related_staff_ids(ticket)
    recipients = {uid for uid in participants if uid != sender_id}
    blocked = {
        uid for uid in related_staff
        if uid not in {ticket.StaffId, ticket.StudentId} and uid != sender_id
    }
    return recipients - blocked


def _touch_chat_presence(ticket_id: int, user_id: int):
    presence = TicketChatPresence.query.filter_by(TicketId=ticket_id, UserId=user_id).first()
    if not presence:
        db.session.add(TicketChatPresence(TicketId=ticket_id, UserId=user_id, LastSeenAt=datetime.utcnow()))
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
            {'name': a.FileName, 'url': attachment_url(a)}
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
    return [
        {
            'user_id': user.UserId,
            'name': user.FullName,
            'role': user.Role.value,
            'is_online': bool(last_seen and last_seen.timestamp() >= cutoff),
        }
        for user, last_seen in participants
    ]


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
        'vote_count': ticket.vote_count,
        'comment_count': ticket.comment_count,
    }
    if extra:
        payload.update(extra)

    for uid in recipients:
        if uid:
            publish_user_event(uid, 'ticket_activity', payload)


def _resolve_view_mode(default='list'):
    mode = request.args.get('view', default, type=str).strip().lower()
    return mode if mode in ('list', 'compact') else default


@student_bp.route('/dashboard')
@login_required
@role_required('Student')
def dashboard():
    total_tickets = Ticket.query.filter_by(StudentId=current_user.UserId).count()
    unresolved_tickets = (Ticket.query
                          .filter_by(StudentId=current_user.UserId)
                          .filter(Ticket.Status.in_([
                              StatusEnum.Submitted,
                              StatusEnum.Assigned,
                              StatusEnum.InProgress,
                              StatusEnum.PendingInfo,
                          ]))
                          .count())

    return render_template(
        'student/dashboard.html',
        total_tickets=total_tickets,
        unresolved_tickets=unresolved_tickets,
    )


@student_bp.route('/my-complaints')
@login_required
@role_required('Student')
def my_complaints():
    filter_form = TicketFilterForm(request.args)
    view_mode = _resolve_view_mode('list')
    query       = Ticket.query.filter_by(StudentId=current_user.UserId)
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
        query = query.filter(
            db.or_(
                Ticket.Title.ilike(f'%{s}%'),
                Ticket.TrackingRef.ilike(f'%{s}%'),
            )
        )

    query       = apply_sort(query, filter_form.sort.data or 'newest')
    page        = request.args.get('page', 1, type=int)
    try:
        per_page = int(filter_form.per_page.data or current_app.config.get('TICKETS_PER_PAGE', 15))
    except (ValueError, TypeError):
        per_page = current_app.config.get('TICKETS_PER_PAGE', 15)
    pagination  = query.paginate(page=page, per_page=per_page, error_out=False)
    tickets     = pagination.items
    all_tickets = Ticket.query.filter_by(StudentId=current_user.UserId).all()

    stats = {
        'total'         : len(all_tickets),
        'pending'       : sum(1 for t in all_tickets if t.Status == StatusEnum.Submitted),
        'in_progress'   : sum(1 for t in all_tickets
                              if t.Status in (StatusEnum.InProgress,
                                              StatusEnum.Assigned,
                                              StatusEnum.PendingInfo)),
        'resolved'      : sum(1 for t in all_tickets if t.Status == StatusEnum.Resolved),
        'needs_feedback': sum(1 for t in all_tickets if t.needs_feedback),
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
        'student/my_complaints.html',
        tickets=tickets,
        pagination=pagination,
        filter_form=filter_form,
        stats=stats,
        view_mode=view_mode,
        category_options=category_options,
        available_subcategories=available_subcategories,
        selected_categories=selected_categories,
        selected_subcategories=selected_subcategories,
        subcategory_map=CATEGORY_SUBCATEGORY_MAP,
    )


@student_bp.route('/community')
@login_required
@role_required('Student')
def community():
    filter_form = TicketFilterForm(request.args)
    view_mode = _resolve_view_mode('compact')
    community_query = Ticket.query.filter(Ticket.StudentId != current_user.UserId)
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
            community_query = community_query.filter(
                Ticket.Status == StatusEnum(filter_form.status.data)
            )
        except ValueError:
            pass
    if filter_form.priority.data:
        try:
            community_query = community_query.filter(
                Ticket.Priority == PriorityEnum(filter_form.priority.data)
            )
        except ValueError:
            pass
    if selected_categories:
        community_query = community_query.filter(Ticket.Category.in_(selected_categories))
    if selected_subcategories:
        community_query = community_query.filter(Ticket.SubCategory.in_(selected_subcategories))
    if filter_form.search.data:
        s = filter_form.search.data.strip()
        community_query = community_query.filter(
            db.or_(
                Ticket.Title.ilike(f'%{s}%'),
                Ticket.TrackingRef.ilike(f'%{s}%'),
            )
        )

    base_sorted_query = apply_sort(community_query, filter_form.sort.data or 'newest')

    social_sort = request.args.get('social_sort', 'default', type=str).strip().lower()
    if social_sort not in ('default', 'votes', 'comments'):
        social_sort = 'default'

    if social_sort == 'votes':
        vote_count_sq = (
            db.select(db.func.count(TicketVote.VoteId))
            .where(TicketVote.TicketId == Ticket.TicketId)
            .correlate(Ticket)
            .scalar_subquery()
        )
        community_query = base_sorted_query.order_by(None).order_by(vote_count_sq.desc(), Ticket.UpdatedAt.desc())
    elif social_sort == 'comments':
        comment_count_sq = (
            db.select(db.func.count(TicketComment.CommentId))
            .where(TicketComment.TicketId == Ticket.TicketId)
            .correlate(Ticket)
            .scalar_subquery()
        )
        community_query = base_sorted_query.order_by(None).order_by(comment_count_sq.desc(), Ticket.UpdatedAt.desc())
    else:
        community_query = base_sorted_query
    page = request.args.get('page', 1, type=int)
    try:
        per_page = int(filter_form.per_page.data or current_app.config.get('TICKETS_PER_PAGE', 15))
    except (ValueError, TypeError):
        per_page = current_app.config.get('TICKETS_PER_PAGE', 15)
    pagination = community_query.paginate(page=page, per_page=per_page, error_out=False)

    my_ticket_votes = {
        v.TicketId for v in TicketVote.query.filter_by(UserId=current_user.UserId).all()
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

    social_sort_urls = {
        'default': _build_community_sort_url('default'),
        'votes': _build_community_sort_url('votes'),
        'comments': _build_community_sort_url('comments'),
    }

    return render_template(
        'student/community.html',
        tickets=pagination.items,
        pagination=pagination,
        my_ticket_votes=my_ticket_votes,
        filter_form=filter_form,
        social_sort=social_sort,
        social_sort_urls=social_sort_urls,
        view_mode=view_mode,
        category_options=category_options,
        available_subcategories=available_subcategories,
        selected_categories=selected_categories,
        selected_subcategories=selected_subcategories,
        subcategory_map=CATEGORY_SUBCATEGORY_MAP,
    )


@student_bp.route('/get-subcategories')
@login_required
def get_subcategories():
    """AJAX endpoint — returns JSON list of subcategories for a category."""
    from flask import jsonify
    cat  = request.args.get('category', '')
    subs = CATEGORY_SUBCATEGORY_MAP.get(cat, [])
    return jsonify(subs)


@student_bp.route('/track-ticket')
@login_required
@role_required('Student')
def track_ticket():
    """Look up a ticket by its tracking reference number."""
    ref = request.args.get('ref', '').strip().upper()
    if not ref:
        flash('Please enter a tracking reference number.', 'warning')
        return redirect(url_for('student.dashboard'))

    ticket = Ticket.query.filter_by(
        TrackingRef=ref,
        StudentId=current_user.UserId
    ).first()

    if ticket:
        return redirect(url_for('student.view_ticket', ticket_id=ticket.TicketId))

    flash(
        f'No ticket found for reference <strong>{ref}</strong>. '
        f'Please check the reference and try again.',
        'danger'
    )
    return redirect(url_for('student.dashboard'))


@student_bp.route('/submit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def submit_ticket():
    form = SubmitTicketForm()

    # Populate subcategory choices dynamically
    selected_cat = request.form.get('category', '')
    subs = CATEGORY_SUBCATEGORY_MAP.get(selected_cat, [])
    form.sub_category.choices = [('', '— Select Sub-Category —')] + [(s, s) for s in subs]

    if form.validate_on_submit():
        dept_name    = get_department_name_for_category(form.category.data)
        dept         = Department.query.filter_by(Name=dept_name).first()

        ticket = Ticket(
            StudentId    = current_user.UserId,
            DepartmentId = dept.DepartmentId if dept else None,
            Title        = form.title.data.strip(),
            Description  = form.description.data.strip(),
            Category     = form.category.data,
            SubCategory  = form.sub_category.data,
            # Staff sets final priority after investigation.
            Priority     = None,
            Status       = StatusEnum.Submitted,
            CreatedAt    = datetime.utcnow(),
            UpdatedAt    = datetime.utcnow(),
        )
        db.session.add(ticket)
        db.session.flush()

        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                from werkzeug.utils import secure_filename
                upload_root = current_app.config['UPLOAD_FOLDER']
                ticket_dir  = os.path.join(upload_root, str(ticket.TicketId))
                os.makedirs(ticket_dir, exist_ok=True)
                filename = secure_filename(file.filename)
                filepath = os.path.join(ticket_dir, filename)
                file.save(filepath)
                db.session.add(Attachment(
                    TicketId=ticket.TicketId, FileName=filename, FilePath=filepath
                ))

        auto_assign_ticket(ticket)
        db.session.flush()
        check_and_raise_flags(ticket)

        # Generate a unique tracking reference now that the ticket ID is available
        ticket.TrackingRef = ticket.generate_tracking_ref(ticket.TicketId)
        db.session.flush()

        # Notify student with their reference number
        notify_ticket_submitted(ticket)

        db.session.commit()
        _publish_ticket_activity(ticket, 'ticket_submitted', current_user.UserId)
        flash(
            f'Your complaint has been submitted. '
            f'Tracking reference: {ticket.TrackingRef}. '
            f'A confirmation notification has been sent to you.',
            'success'
        )
        return redirect(url_for('student.view_ticket', ticket_id=ticket.TicketId))

    return render_template('student/submit_ticket.html', form=form,
                           subcategory_map=CATEGORY_SUBCATEGORY_MAP)


@student_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Student')
def view_ticket(ticket_id):
    ticket = _get_student_ticket(ticket_id)
    is_owner = ticket.StudentId == current_user.UserId

    updates = []
    if is_owner:
        updates = (ticket.updates
                   .filter_by(ParentUpdateId=None)
                   .order_by(TicketUpdate.CreatedAt.asc())
                   .all())

    student_comments = (TicketComment.query
                        .filter_by(TicketId=ticket.TicketId, ParentCommentId=None)
                        .order_by(TicketComment.CreatedAt.desc())
                        .all())

    my_ticket_vote = TicketVote.query.filter_by(
        TicketId=ticket.TicketId,
        UserId=current_user.UserId,
    ).first()

    my_comment_votes = {
        v.CommentId for v in CommentVote.query.filter_by(UserId=current_user.UserId).all()
    }

    ticket_attachments = ticket.attachments.filter_by(UpdateId=None).all()
    reply_form         = StudentReplyForm()
    live_chat_form     = StudentLiveChatForm()
    feedback_form      = FeedbackForm()
    reopen_form        = ReopenRequestForm()
    comment_form       = TicketCommentForm()

    chat_messages = []
    chat_participants = []
    if is_owner:
        chat_messages = (TicketChatMessage.query
                         .filter_by(TicketId=ticket.TicketId)
                         .order_by(TicketChatMessage.ChatMessageId.asc())
                         .limit(100)
                         .all())
        chat_participants = _chat_participant_badges(ticket)

    pending_reopen = ReopenRequest.query.filter_by(
        TicketId=ticket_id, StudentId=current_user.UserId, Status='Pending'
    ).first()

    # Determine which reply threads are locked
    # A thread is locked if a staff InProgress update was posted AFTER the thread
    locked_thread_ids = _get_locked_thread_ids(ticket)

    return render_template(
        'student/view_ticket.html',
        ticket=ticket,
        is_owner=is_owner,
        updates=updates,
        student_comments=student_comments,
        my_ticket_vote=my_ticket_vote,
        my_comment_votes=my_comment_votes,
        ticket_attachments=ticket_attachments,
        reply_form=reply_form,
        live_chat_form=live_chat_form,
        feedback_form=feedback_form,
        reopen_form=reopen_form,
        comment_form=comment_form,
        pending_reopen=pending_reopen,
        locked_thread_ids=locked_thread_ids,
        chat_messages=chat_messages,
        chat_participants=chat_participants,
    )


@student_bp.route('/ticket/<int:ticket_id>/vote', methods=['POST'])
@login_required
@role_required('Student')
def vote_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if ticket.StudentId == current_user.UserId:
        flash('You cannot vote on your own ticket.', 'warning')
        return redirect(_safe_next_url() or request.referrer or url_for('student.community'))

    existing = TicketVote.query.filter_by(
        TicketId=ticket_id,
        UserId=current_user.UserId,
    ).first()

    if existing:
        db.session.delete(existing)
        flash('Your vote was removed.', 'info')
    else:
        db.session.add(TicketVote(TicketId=ticket_id, UserId=current_user.UserId))
        notify_social_vote(ticket, current_user)
        flash('Your vote was recorded.', 'success')

    db.session.commit()
    _publish_ticket_activity(ticket, 'ticket_vote_changed', current_user.UserId)
    return redirect(_safe_next_url() or request.referrer or url_for('student.community'))


@student_bp.route('/ticket/<int:ticket_id>/comment', methods=['POST'])
@login_required
def add_ticket_comment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    form = TicketCommentForm()

    if ticket.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
        flash('Student comments are closed for resolved or rejected tickets.', 'warning')
        return redirect(_safe_next_url() or request.referrer or _ticket_detail_url_for_current_user(ticket_id))

    if not _can_user_comment_on_ticket(ticket):
        abort(403)

    if form.validate_on_submit():
        parent_comment_id = _parse_parent_comment_id(form.parent_comment_id.data)
        if parent_comment_id:
            parent_comment = TicketComment.query.get_or_404(parent_comment_id)
            if parent_comment.TicketId != ticket_id:
                abort(403)

        comment = TicketComment(
            TicketId=ticket_id,
            UserId=current_user.UserId,
            ParentCommentId=parent_comment_id,
            Content=form.content.data.strip(),
        )
        db.session.add(comment)
        db.session.flush()

        saved_images = 0
        for file in request.files.getlist('attachments'):
            if not file or not file.filename:
                continue
            if not _is_allowed_comment_image(file.filename):
                flash('Only image files (png, jpg, jpeg, gif, webp) are allowed for comment uploads.', 'warning')
                continue
            from werkzeug.utils import secure_filename
            upload_root = current_app.config['UPLOAD_FOLDER']
            comment_dir = os.path.join(upload_root, f'comment_{comment.CommentId}')
            os.makedirs(comment_dir, exist_ok=True)
            filename = secure_filename(file.filename)
            filepath = os.path.join(comment_dir, filename)
            file.save(filepath)
            db.session.add(CommentAttachment(
                CommentId=comment.CommentId,
                FileName=filename,
                FilePath=filepath,
            ))
            saved_images += 1

        notify_social_comment(ticket, current_user)

        db.session.commit()
        _publish_ticket_activity(ticket, 'ticket_comment_added', current_user.UserId)
        if parent_comment_id and saved_images:
            flash('Reply posted with image attachment(s).', 'success')
        elif parent_comment_id:
            flash('Reply posted.', 'success')
        elif saved_images:
            flash('Comment posted with image attachment(s).', 'success')
        else:
            flash('Comment posted.', 'success')
    else:
        flash('Comment must be 2-1000 characters.', 'danger')

    return redirect(_safe_next_url() or request.referrer or _ticket_detail_url_for_current_user(ticket_id))


@student_bp.route('/comment/<int:comment_id>/upvote', methods=['POST'])
@login_required
@role_required('Student')
def upvote_comment(comment_id):
    comment = TicketComment.query.get_or_404(comment_id)

    existing = CommentVote.query.filter_by(
        CommentId=comment_id,
        UserId=current_user.UserId,
    ).first()

    if existing:
        db.session.delete(existing)
        flash('Comment upvote removed.', 'info')
    else:
        db.session.add(CommentVote(CommentId=comment_id, UserId=current_user.UserId))
        flash('Comment upvoted.', 'success')

    try:
        db.session.commit()
        ticket = Ticket.query.get(comment.TicketId)
        if ticket:
            _publish_ticket_activity(
                ticket,
                'comment_upvote_changed',
                current_user.UserId,
                {'comment_id': comment.CommentId, 'comment_author_id': comment.UserId},
            )
    except IntegrityError:
        db.session.rollback()
        flash('Upvote update failed, please try again.', 'danger')

    return redirect(_safe_next_url() or request.referrer or url_for('student.community'))


@student_bp.route('/settings/social', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def social_settings():
    pref = UserPreference.query.filter_by(UserId=current_user.UserId).first()
    if not pref:
        pref = UserPreference(UserId=current_user.UserId, SuppressSocialNotifications=False)
        db.session.add(pref)
        db.session.flush()

    form = SocialPreferenceForm()

    if request.method == 'GET':
        form.suppress_social.data = pref.SuppressSocialNotifications

    if form.validate_on_submit():
        pref.SuppressSocialNotifications = bool(form.suppress_social.data)
        db.session.commit()
        flash('Social notification preference updated.', 'success')
        return redirect(url_for('student.social_settings'))

    return render_template('student/social_settings.html', form=form)


@student_bp.route('/ticket/<int:ticket_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def edit_ticket(ticket_id):
    ticket = _get_owned_student_ticket(ticket_id)
    if not ticket.is_editable:
        flash('This ticket can no longer be edited.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = EditTicketForm(obj=ticket)
    selected_cat = request.form.get('category', ticket.Category)
    subs = CATEGORY_SUBCATEGORY_MAP.get(selected_cat, [])
    form.sub_category.choices = [('', '— Select Sub-Category —')] + [(s, s) for s in subs]

    if request.method == 'GET':
        form.title.data        = ticket.Title
        form.category.data     = ticket.Category
        form.sub_category.data = ticket.SubCategory
        form.description.data  = ticket.Description

    if form.validate_on_submit():
        ticket.Title       = form.title.data.strip()
        ticket.Category    = form.category.data
        ticket.SubCategory = form.sub_category.data
        ticket.Description = form.description.data.strip()
        ticket.UpdatedAt   = datetime.utcnow()

        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                from werkzeug.utils import secure_filename
                upload_root = current_app.config['UPLOAD_FOLDER']
                ticket_dir  = os.path.join(upload_root, str(ticket.TicketId))
                os.makedirs(ticket_dir, exist_ok=True)
                filename = secure_filename(file.filename)
                filepath = os.path.join(ticket_dir, filename)
                file.save(filepath)
                db.session.add(Attachment(
                    TicketId=ticket.TicketId, FileName=filename, FilePath=filepath
                ))

        db.session.commit()
        flash('Ticket updated.', 'success')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    return render_template('student/edit_ticket.html', form=form, ticket=ticket,
                           subcategory_map=CATEGORY_SUBCATEGORY_MAP)


@student_bp.route('/ticket/<int:ticket_id>/reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Student')
def reply_to_update(ticket_id, update_id):
    ticket        = _get_owned_student_ticket(ticket_id)
    parent_update = TicketUpdate.query.get_or_404(update_id)

    if parent_update.TicketId != ticket_id:
        abort(403)
    if not parent_update.IsReplyThread:
        flash('Replies are only allowed on reply threads.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    # Check if thread is locked
    locked = _get_locked_thread_ids(ticket)
    if update_id in locked:
        flash('This thread has been closed by staff after a progress update.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = StudentReplyForm()
    if form.validate_on_submit():
        reply = TicketUpdate(
            TicketId=ticket_id, UserId=current_user.UserId,
            Comment=form.comment.data.strip(),
            ParentUpdateId=update_id, IsReplyThread=False,
        )
        db.session.add(reply)
        db.session.flush()

        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                from werkzeug.utils import secure_filename
                upload_root = current_app.config['UPLOAD_FOLDER']
                update_dir  = os.path.join(upload_root, f'update_{reply.UpdateId}')
                os.makedirs(update_dir, exist_ok=True)
                filename = secure_filename(file.filename)
                filepath = os.path.join(update_dir, filename)
                file.save(filepath)
                db.session.add(Attachment(
                    UpdateId=reply.UpdateId, FileName=filename, FilePath=filepath
                ))

        notify_student_replied(ticket, current_user)
        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        _publish_ticket_activity(ticket, 'ticket_reply_added', current_user.UserId)
        flash('Reply sent.', 'success')
    else:
        flash('Reply cannot be empty.', 'danger')

    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


@student_bp.route('/ticket/<int:ticket_id>/chat/messages')
@login_required
@role_required('Student')
def list_chat_messages(ticket_id):
    ticket = _get_owned_student_ticket(ticket_id)

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

    next_since = rows[-1].ChatMessageId if rows else since_id
    return jsonify({
        'messages': [_serialize_chat_message(row) for row in rows],
        'participants': _chat_participant_badges(ticket),
        'next_since_id': next_since,
    })


@student_bp.route('/ticket/<int:ticket_id>/chat/send', methods=['POST'])
@login_required
@role_required('Student')
def send_chat_message(ticket_id):
    ticket = _get_owned_student_ticket(ticket_id)

    if ticket.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
        flash('Live chat is closed for resolved or rejected tickets.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id, _anchor='student-livechat-pane'))

    form = StudentLiveChatForm()

    if not form.validate_on_submit():
        flash('Chat message must contain between 1 and 2000 characters.', 'danger')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id, _anchor='student-livechat-pane'))

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

    recipients = _chat_notification_targets(ticket, current_user.UserId)
    notify_live_chat_message(ticket, current_user, sorted(recipients))

    db.session.commit()

    payload = {
        'ticket_id': ticket.TicketId,
        'chat_message_id': message.ChatMessageId,
        'sender_id': current_user.UserId,
    }
    for uid in _chat_participant_ids(ticket):
        publish_user_event(uid, 'chat_message', payload)

    return redirect(url_for('student.view_ticket', ticket_id=ticket_id, _anchor='student-livechat-pane'))


@student_bp.route('/ticket/<int:ticket_id>/chat/heartbeat', methods=['POST'])
@login_required
@role_required('Student')
def chat_heartbeat(ticket_id):
    _get_owned_student_ticket(ticket_id)
    _touch_chat_presence(ticket_id, current_user.UserId)
    db.session.commit()
    return jsonify({'ok': True})


@student_bp.route('/ticket/<int:ticket_id>/withdraw', methods=['POST'])
@login_required
@role_required('Student')
def withdraw_ticket(ticket_id):
    ticket = _get_owned_student_ticket(ticket_id)
    if not ticket.is_withdrawable:
        flash('This ticket cannot be withdrawn.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))
    ticket.Status    = StatusEnum.Rejected
    ticket.UpdatedAt = datetime.utcnow()
    db.session.add(TicketUpdate(
        TicketId=ticket_id, UserId=current_user.UserId,
        Comment='[WITHDRAWN] Student withdrew the complaint.',
        StatusChange=UpdateStatusEnum.Rejected, IsReplyThread=False,
    ))
    db.session.commit()
    _publish_ticket_activity(ticket, 'ticket_withdrawn', current_user.UserId)
    flash('Your complaint has been withdrawn.', 'info')
    return redirect(url_for('student.dashboard'))


@student_bp.route('/ticket/<int:ticket_id>/feedback', methods=['POST'])
@login_required
@role_required('Student')
def submit_feedback(ticket_id):
    ticket = _get_owned_student_ticket(ticket_id)
    form   = FeedbackForm()
    if form.validate_on_submit():
        ticket.FeedbackRating  = form.rating.data
        ticket.FeedbackComment = form.comment.data.strip() if form.comment.data else None
        db.session.commit()
        flash('Thank you for your feedback!', 'success')
    else:
        flash('Please provide a valid rating.', 'danger')
    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


@student_bp.route('/ticket/<int:ticket_id>/reopen', methods=['POST'])
@login_required
@role_required('Student')
def request_reopen(ticket_id):
    ticket = _get_owned_student_ticket(ticket_id)
    if ticket.Status not in (StatusEnum.Resolved, StatusEnum.Rejected):
        flash('Only resolved or rejected tickets can be reopened.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))
    existing = ReopenRequest.query.filter_by(
        TicketId=ticket_id, StudentId=current_user.UserId, Status='Pending'
    ).first()
    if existing:
        flash('A reopen request is already pending.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))
    form = ReopenRequestForm()
    if form.validate_on_submit():
        db.session.add(ReopenRequest(
            TicketId=ticket_id, StudentId=current_user.UserId,
            Reason=form.reason.data.strip(), Status='Pending',
        ))
        db.session.add(TicketUpdate(
            TicketId=ticket_id, UserId=current_user.UserId,
            Comment=f'[REOPEN REQUESTED] {form.reason.data.strip()}',
            IsReplyThread=False,
        ))
        db.session.add(AdminNotification(
            Type='reopen_request',
            Message=(f'Student {current_user.FullName} requested reopening of '
                     f'Ticket #{ticket_id} "{ticket.Title}".'),
            TicketId=ticket_id, IsRead=False,
        ))
        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        _publish_ticket_activity(ticket, 'ticket_reopen_requested', current_user.UserId)
        from app.services.notifications import _send_admin_emails
        admin_ticket_url = url_for('admin.ticket_detail', ticket_id=ticket_id, _external=True)
        _send_admin_emails(
            f'Reopen Request — Ticket #{ticket_id}',
            (f'Student {current_user.FullName} has requested reopening of ticket '
             f'"#{ticket_id} {ticket.Title}".\n\n'
             f'Reason: {form.reason.data.strip()}\n\n'
             f'Review it at: {admin_ticket_url}'),
        )
        flash('Reopen request submitted. Admin will review it shortly.', 'success')
    else:
        flash('Please provide a reason for reopening.', 'danger')
    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


@student_bp.route('/uploads/<path:filepath>')
@login_required
def serve_upload(filepath):
    upload_root = current_app.config['UPLOAD_FOLDER']
    return send_from_directory(upload_root, filepath)


# ── helpers ────���──────────────────────────────────────────────────────────────

def _get_student_ticket(ticket_id: int) -> Ticket:
    ticket = Ticket.query.get_or_404(ticket_id)
    if current_user.Role != RoleEnum.Student:
        abort(403)
    return ticket


def _get_owned_student_ticket(ticket_id: int) -> Ticket:
    ticket = _get_student_ticket(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
    return ticket




def _get_locked_thread_ids(ticket: Ticket) -> set[int]:
    """
    A reply thread is locked when a staff member posts an InProgress update
    AFTER the thread was opened, signalling information received and thread closed.
    Returns a set of UpdateIds that are locked.
    """
    locked = set()
    threads = (ticket.updates
               .filter_by(IsReplyThread=True, ParentUpdateId=None)
               .all())
    for thread in threads:
        # Find the latest InProgress update on this ticket after this thread
        in_progress_after = (
            ticket.updates
            .filter(
                TicketUpdate.IsReplyThread == False,    # noqa: E712
                TicketUpdate.ParentUpdateId == None,    # noqa: E712
                TicketUpdate.StatusChange == UpdateStatusEnum.InProgress,
                TicketUpdate.CreatedAt > thread.CreatedAt,
            )
            .first()
        )
        if in_progress_after:
            locked.add(thread.UpdateId)
    return locked


def _is_allowed_comment_image(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in COMMENT_IMAGE_EXTENSIONS


def _parse_parent_comment_id(raw_value: str | None) -> int | None:
    if isinstance(raw_value, list):
        values = [v for v in raw_value if v]
        raw_value = values[-1] if values else None
    if not raw_value:
        return None
    try:
        value = int(raw_value)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _can_user_comment_on_ticket(ticket: Ticket) -> bool:
    if current_user.Role == RoleEnum.Admin:
        return True
    if current_user.Role == RoleEnum.Staff:
        return ticket.StaffId == current_user.UserId
    if current_user.Role == RoleEnum.Student:
        return True
    return False


def _ticket_detail_url_for_current_user(ticket_id: int) -> str:
    if current_user.Role == RoleEnum.Admin:
        return url_for('admin.ticket_detail', ticket_id=ticket_id)
    if current_user.Role == RoleEnum.Staff:
        return url_for('staff.view_ticket', ticket_id=ticket_id)
    return url_for('student.view_ticket', ticket_id=ticket_id)


def _build_community_sort_url(social_sort: str) -> str:
    args = {}
    for key, values in request.args.lists():
        if key == 'social_sort':
            continue
        if key == 'page':
            continue
        args[key] = values if len(values) > 1 else values[0]
    args['social_sort'] = social_sort
    return url_for('student.community', **args)


def _safe_next_url() -> str | None:
    next_url = (request.form.get('next') or '').strip()
    if not next_url:
        return None
    if next_url.startswith('/'):
        return next_url
    return None