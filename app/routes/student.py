import os
from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, send_from_directory, current_app
)
from flask_login import login_required, current_user

from app import db
from app.models.ticket        import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update import TicketUpdate, UpdateStatusEnum
from app.models.attachment    import Attachment
from app.models.department    import Department
from app.models.reopen_request import ReopenRequest
from app.models.admin_notification import AdminNotification
from app.utils.decorators     import role_required
from app.utils.helpers        import (
    allowed_file, get_priority_for_category,
    get_department_name_for_category, check_and_raise_flags,
    CATEGORY_SUBCATEGORY_MAP,
)
from app.utils.sorting        import apply_sort
from app.services.assignment  import auto_assign_ticket
from app.services.notifications import notify_student_replied, notify_ticket_submitted
from app.forms.student_forms  import (
    SubmitTicketForm, EditTicketForm, FeedbackForm,
    TicketFilterForm, StudentReplyForm, ReopenRequestForm
)

student_bp = Blueprint('student', __name__)


@student_bp.route('/dashboard')
@login_required
@role_required('Student')
def dashboard():
    filter_form = TicketFilterForm(request.args)
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
    if filter_form.search.data:
        s = filter_form.search.data.strip()
        query = query.filter(
            db.or_(
                Ticket.Title.ilike(f'%{s}%'),
                Ticket.TrackingRef.ilike(f'%{s}%'),
            )
        )

    query       = apply_sort(query, filter_form.sort.data or 'newest')
    tickets     = query.all()
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
        tickets=tickets, filter_form=filter_form, stats=stats
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
        priority_str = get_priority_for_category(form.category.data)
        dept_name    = get_department_name_for_category(form.category.data)
        dept         = Department.query.filter_by(Name=dept_name).first()

        ticket = Ticket(
            StudentId    = current_user.UserId,
            DepartmentId = dept.DepartmentId if dept else None,
            Title        = form.title.data.strip(),
            Description  = form.description.data.strip(),
            Category     = form.category.data,
            SubCategory  = form.sub_category.data,
            Priority     = PriorityEnum[priority_str],
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
            f'Tracking reference: <strong>{ticket.TrackingRef}</strong>. '
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
    ticket             = _get_student_ticket(ticket_id)
    updates            = (ticket.updates
                          .filter_by(ParentUpdateId=None)
                          .order_by(TicketUpdate.CreatedAt.asc())
                          .all())
    ticket_attachments = ticket.attachments.filter_by(UpdateId=None).all()
    reply_form         = StudentReplyForm()
    feedback_form      = FeedbackForm()
    reopen_form        = ReopenRequestForm()

    pending_reopen = ReopenRequest.query.filter_by(
        TicketId=ticket_id, StudentId=current_user.UserId, Status='Pending'
    ).first()

    # Determine which reply threads are locked
    # A thread is locked if a staff InProgress update was posted AFTER the thread
    locked_thread_ids = _get_locked_thread_ids(ticket)

    return render_template(
        'student/view_ticket.html',
        ticket=ticket,
        updates=updates,
        ticket_attachments=ticket_attachments,
        reply_form=reply_form,
        feedback_form=feedback_form,
        reopen_form=reopen_form,
        pending_reopen=pending_reopen,
        locked_thread_ids=locked_thread_ids,
    )


@student_bp.route('/ticket/<int:ticket_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def edit_ticket(ticket_id):
    ticket = _get_student_ticket(ticket_id)
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
    ticket        = _get_student_ticket(ticket_id)
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
    ticket = _get_student_ticket(ticket_id)
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
    ticket = _get_student_ticket(ticket_id)
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
    ticket = _get_student_ticket(ticket_id)
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