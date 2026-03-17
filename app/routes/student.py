import os
from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, send_from_directory, current_app
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
from app.models.user import RoleEnum
from app.models.ticket_vote import TicketVote
from app.models.ticket_comment import TicketComment
from app.models.comment_vote import CommentVote
from app.models.user_preference import UserPreference
from app.utils.decorators     import role_required
from app.utils.helpers        import (
    allowed_file,
    get_department_name_for_category, check_and_raise_flags,
    CATEGORY_SUBCATEGORY_MAP,
)
from app.utils.sorting        import apply_sort
from app.services.assignment  import auto_assign_ticket
from app.services.notifications import (
    notify_student_replied,
    notify_ticket_submitted,
    notify_social_vote,
    notify_social_comment,
)
from app.forms.student_forms  import (
    SubmitTicketForm, EditTicketForm, FeedbackForm,
    TicketFilterForm, StudentReplyForm, ReopenRequestForm,
    TicketCommentForm, SocialPreferenceForm,
)

student_bp = Blueprint('student', __name__)


def _resolve_view_mode(default='list'):
    mode = request.args.get('view', default, type=str).strip().lower()
    return mode if mode in ('list', 'compact') else default


@student_bp.route('/dashboard')
@login_required
@role_required('Student')
def dashboard():
    filter_form = TicketFilterForm(request.args)
    view_mode = _resolve_view_mode('list')
    query       = Ticket.query.filter_by(StudentId=current_user.UserId)

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

    return render_template(
        'student/dashboard.html',
        tickets=tickets,
        pagination=pagination,
        filter_form=filter_form,
        stats=stats,
        view_mode=view_mode,
    )


@student_bp.route('/community')
@login_required
@role_required('Student')
def community():
    filter_form = TicketFilterForm(request.args)
    view_mode = _resolve_view_mode('compact')
    community_query = Ticket.query.filter(Ticket.StudentId != current_user.UserId)

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
    if filter_form.category.data:
        community_query = community_query.filter(Ticket.Category == filter_form.category.data)
    if filter_form.sub_category.data:
        community_query = community_query.filter(Ticket.SubCategory == filter_form.sub_category.data)
    if filter_form.search.data:
        s = filter_form.search.data.strip()
        community_query = community_query.filter(
            db.or_(
                Ticket.Title.ilike(f'%{s}%'),
                Ticket.TrackingRef.ilike(f'%{s}%'),
            )
        )

    community_query = apply_sort(community_query, filter_form.sort.data or 'newest')
    page = request.args.get('page', 1, type=int)
    try:
        per_page = int(filter_form.per_page.data or current_app.config.get('TICKETS_PER_PAGE', 15))
    except (ValueError, TypeError):
        per_page = current_app.config.get('TICKETS_PER_PAGE', 15)
    pagination = community_query.paginate(page=page, per_page=per_page, error_out=False)

    my_ticket_votes = {
        v.TicketId for v in TicketVote.query.filter_by(UserId=current_user.UserId).all()
    }

    return render_template(
        'student/community.html',
        tickets=pagination.items,
        pagination=pagination,
        my_ticket_votes=my_ticket_votes,
        filter_form=filter_form,
        view_mode=view_mode,
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
                        .filter_by(TicketId=ticket.TicketId)
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
    feedback_form      = FeedbackForm()
    reopen_form        = ReopenRequestForm()
    comment_form       = TicketCommentForm()

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
        feedback_form=feedback_form,
        reopen_form=reopen_form,
        comment_form=comment_form,
        pending_reopen=pending_reopen,
        locked_thread_ids=locked_thread_ids,
    )


@student_bp.route('/ticket/<int:ticket_id>/vote', methods=['POST'])
@login_required
@role_required('Student')
def vote_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if ticket.StudentId == current_user.UserId:
        flash('You cannot vote on your own ticket.', 'warning')
        return redirect(request.referrer or url_for('student.community'))

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
    return redirect(request.referrer or url_for('student.community'))


@student_bp.route('/ticket/<int:ticket_id>/comment', methods=['POST'])
@login_required
@role_required('Student')
def add_ticket_comment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    form = TicketCommentForm()

    detail_path = url_for('student.view_ticket', ticket_id=ticket_id)
    referrer = request.referrer or ''
    if request.form.get('from_detail') != '1' or detail_path not in referrer:
        flash('Open the ticket details page to comment.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    if ticket.StudentId == current_user.UserId:
        flash('Use the activity thread for your own ticket.', 'warning')
        return redirect(request.referrer or url_for('student.view_ticket', ticket_id=ticket_id))

    if form.validate_on_submit():
        db.session.add(TicketComment(
            TicketId=ticket_id,
            UserId=current_user.UserId,
            Content=form.content.data.strip(),
        ))
        notify_social_comment(ticket, current_user)

        db.session.commit()
        flash('Comment posted.', 'success')
    else:
        flash('Comment must be 2-500 characters.', 'danger')

    return redirect(request.referrer or url_for('student.view_ticket', ticket_id=ticket_id))


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
    except IntegrityError:
        db.session.rollback()
        flash('Upvote update failed, please try again.', 'danger')

    return redirect(request.referrer or url_for('student.community'))


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
        flash('Reply sent.', 'success')
    else:
        flash('Reply cannot be empty.', 'danger')

    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


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
        from app.services.notifications import _send_admin_emails
        _send_admin_emails(
            f'Reopen Request — Ticket #{ticket_id}',
            (f'Student {current_user.FullName} has requested reopening of ticket '
             f'"#{ticket_id} {ticket.Title}".\n\n'
             f'Reason: {form.reason.data.strip()}\n\n'
             f'Review it at: /admin/tickets/{ticket_id}'),
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