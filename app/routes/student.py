from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, current_app, send_from_directory
)
from flask_login import login_required, current_user
from datetime import datetime
import json, os

from app import db
from app.models.ticket import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update import TicketUpdate, UpdateStatusEnum
from app.models.attachment import Attachment
from app.models.department import Department
from app.utils.decorators import role_required
from app.utils.helpers import (
    get_priority_for_category,
    get_department_name_for_category,
    save_uploaded_file,
    allowed_file,
    CATEGORY_PRIORITY_MAP,
)
from app.forms.student_forms import (
    SubmitTicketForm, EditTicketForm, FeedbackForm,
    TicketFilterForm, StudentReplyForm
)
from app.services.assignment import auto_assign_ticket

student_bp = Blueprint('student', __name__)


# ─────────────────────────────────────────────
#  FILE SERVING  (works for both ticket & update attachments)
# ─────────────────────────────────────────────
@student_bp.route('/uploads/<path:filepath>')
@login_required
def serve_upload(filepath):
    """Serve uploaded files — only to users who own or are assigned to the ticket."""
    upload_root = current_app.config['UPLOAD_FOLDER']
    full_path   = os.path.join(upload_root, filepath)

    # Security: file must actually live inside UPLOAD_FOLDER
    if not os.path.abspath(full_path).startswith(os.path.abspath(upload_root)):
        abort(403)
    if not os.path.exists(full_path):
        abort(404)

    directory = os.path.dirname(full_path)
    filename  = os.path.basename(full_path)
    return send_from_directory(directory, filename)


# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────
@student_bp.route('/dashboard')
@login_required
@role_required('Student')
def dashboard():
    filter_form = TicketFilterForm(request.args)
    query = Ticket.query.filter_by(StudentId=current_user.UserId)

    if filter_form.status.data:
        try:
            query = query.filter(Ticket.Status == StatusEnum(filter_form.status.data))
        except ValueError:
            pass
    if filter_form.category.data:
        query = query.filter(Ticket.Category == filter_form.category.data)
    if filter_form.search.data:
        query = query.filter(Ticket.Title.ilike(f'%{filter_form.search.data}%'))

    tickets = query.order_by(Ticket.CreatedAt.desc()).all()
    all_tickets = Ticket.query.filter_by(StudentId=current_user.UserId).all()

    stats = {
        'total'          : len(all_tickets),
        'pending'        : sum(1 for t in all_tickets if t.Status == StatusEnum.Submitted),
        'in_progress'    : sum(1 for t in all_tickets if t.Status == StatusEnum.InProgress),
        'resolved'       : sum(1 for t in all_tickets if t.Status == StatusEnum.Resolved),
        'needs_feedback' : sum(1 for t in all_tickets if t.needs_feedback),
    }

    return render_template(
        'student/dashboard.html',
        tickets=tickets,
        filter_form=filter_form,
        stats=stats
    )


# ─────────────────────────────────────────────
#  SUBMIT TICKET
# ─────────────────────────────────────────────
@student_bp.route('/submit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def submit_ticket():
    form = SubmitTicketForm()

    if form.validate_on_submit():
        dept_name  = get_department_name_for_category(form.category.data)
        department = Department.query.filter_by(Name=dept_name).first()
        priority   = PriorityEnum[get_priority_for_category(form.category.data)]

        ticket = Ticket(
            Title        = form.title.data.strip(),
            Description  = form.description.data.strip(),
            Category     = form.category.data,
            Priority     = priority,
            Status       = StatusEnum.Submitted,
            StudentId    = current_user.UserId,
            DepartmentId = department.DepartmentId if department else None,
        )
        db.session.add(ticket)
        db.session.flush()

        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                filename, filepath = save_uploaded_file(file, ticket.TicketId)
                db.session.add(Attachment(
                    TicketId=ticket.TicketId, FileName=filename, FilePath=filepath
                ))

        assigned_to = auto_assign_ticket(ticket)

        db.session.add(TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment='Ticket submitted.', StatusChange=UpdateStatusEnum.Submitted,
        ))
        if assigned_to:
            db.session.add(TicketUpdate(
                TicketId=ticket.TicketId, UserId=current_user.UserId,
                Comment=(f'Ticket automatically assigned to {assigned_to.FullName} '
                         f'({department.Name if department else "Unknown Dept"}).'),
                StatusChange=UpdateStatusEnum.Assigned,
            ))
        else:
            db.session.add(TicketUpdate(
                TicketId=ticket.TicketId, UserId=current_user.UserId,
                Comment='No staff available in the responsible department. Pending manual assignment.',
            ))

        db.session.commit()
        flash(
            f'Complaint submitted as Ticket #{ticket.TicketId}'
            + (f' and assigned to {assigned_to.FullName}.' if assigned_to else '.'),
            'success'
        )
        return redirect(url_for('student.view_ticket', ticket_id=ticket.TicketId))

    return render_template(
        'student/submit_ticket.html',
        form=form,
        priority_map_json=json.dumps(CATEGORY_PRIORITY_MAP)
    )


# ─────────────────────────────────────────────
#  VIEW TICKET
# ─────────────────────────────────────────────
@student_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Student')
def view_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)

    # Top-level updates only — replies are loaded via the relationship
    updates = (ticket.updates
               .filter_by(ParentUpdateId=None)
               .order_by(TicketUpdate.CreatedAt.asc())
               .all())
    ticket_attachments = ticket.attachments.filter_by(UpdateId=None).all()
    feedback_form = FeedbackForm() if ticket.needs_feedback else None
    reply_form    = StudentReplyForm()

    return render_template(
        'student/view_ticket.html',
        ticket=ticket,
        updates=updates,
        ticket_attachments=ticket_attachments,
        feedback_form=feedback_form,
        reply_form=reply_form,
    )


# ─────────────────────────────────────────────
#  STUDENT REPLY TO A STAFF COMMENT
# ─────────────────────────────────────────────
@student_bp.route('/ticket/<int:ticket_id>/reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Student')
def reply_to_update(ticket_id, update_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)

    parent_update = TicketUpdate.query.get_or_404(update_id)
    if parent_update.TicketId != ticket_id:
        abort(403)

    # ── Server-side gate: only IsReplyThread comments accept replies ──
    if not parent_update.IsReplyThread:
        flash('Replies are only allowed on designated reply threads.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = StudentReplyForm()
    if form.validate_on_submit():
        reply = TicketUpdate(
            TicketId       = ticket_id,
            UserId         = current_user.UserId,
            Comment        = form.comment.data.strip(),
            ParentUpdateId = update_id,
            IsReplyThread  = False,
        )
        db.session.add(reply)
        db.session.flush()

        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                upload_root = current_app.config['UPLOAD_FOLDER']
                update_dir  = os.path.join(upload_root, f'update_{reply.UpdateId}')
                os.makedirs(update_dir, exist_ok=True)
                from werkzeug.utils import secure_filename
                filename = secure_filename(file.filename)
                filepath = os.path.join(update_dir, filename)
                file.save(filepath)
                db.session.add(Attachment(
                    UpdateId=reply.UpdateId, FileName=filename, FilePath=filepath
                ))

        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        flash('Reply sent.', 'success')
    else:
        flash('Reply cannot be empty.', 'danger')

    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  EDIT TICKET
# ─────────────────────────────────────────────
@student_bp.route('/ticket/<int:ticket_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def edit_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
    if not ticket.is_editable:
        flash('This ticket can no longer be edited — it has already been assigned.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = EditTicketForm()
    if request.method == 'GET':
        form.title.data       = ticket.Title
        form.category.data    = ticket.Category
        form.description.data = ticket.Description

    if form.validate_on_submit():
        new_cat    = form.category.data
        dept_name  = get_department_name_for_category(new_cat)
        department = Department.query.filter_by(Name=dept_name).first()

        ticket.Title        = form.title.data.strip()
        ticket.Category     = new_cat
        ticket.Description  = form.description.data.strip()
        ticket.Priority     = PriorityEnum[get_priority_for_category(new_cat)]
        ticket.DepartmentId = department.DepartmentId if department else ticket.DepartmentId
        ticket.UpdatedAt    = datetime.utcnow()

        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                filename, filepath = save_uploaded_file(file, ticket.TicketId)
                db.session.add(Attachment(
                    TicketId=ticket.TicketId, FileName=filename, FilePath=filepath
                ))

        db.session.add(TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment='Student edited the ticket details.',
        ))
        db.session.commit()
        flash('Ticket updated successfully.', 'success')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    return render_template(
        'student/edit_ticket.html',
        form=form, ticket=ticket,
        priority_map_json=json.dumps(CATEGORY_PRIORITY_MAP),
    )


# ─────────────────────────────────────────────
#  WITHDRAW
# ─────────────────────────────────────────────
@student_bp.route('/ticket/<int:ticket_id>/withdraw', methods=['POST'])
@login_required
@role_required('Student')
def withdraw_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
    if not ticket.is_withdrawable:
        flash('This ticket cannot be withdrawn at its current stage.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    ticket.Status    = StatusEnum.Rejected
    ticket.UpdatedAt = datetime.utcnow()
    db.session.add(TicketUpdate(
        TicketId=ticket.TicketId, UserId=current_user.UserId,
        Comment='Ticket withdrawn by student.', StatusChange=UpdateStatusEnum.Rejected,
    ))
    db.session.commit()
    flash(f'Ticket #{ticket_id} has been withdrawn.', 'info')
    return redirect(url_for('student.dashboard'))


# ─────────────────────────────────────────────
#  FEEDBACK
# ─────────────────────────────────────────────
@student_bp.route('/ticket/<int:ticket_id>/feedback', methods=['POST'])
@login_required
@role_required('Student')
def submit_feedback(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
    if not ticket.needs_feedback:
        flash('Feedback already submitted or ticket is not resolved.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = FeedbackForm()
    if form.validate_on_submit():
        ticket.FeedbackRating  = form.rating.data
        ticket.FeedbackComment = form.comment.data
        ticket.FeedbackAt      = datetime.utcnow()
        ticket.UpdatedAt       = datetime.utcnow()
        db.session.add(TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment=f'Student submitted feedback — Rating: {form.rating.data}/5.',
        ))
        db.session.commit()
        flash('Thank you for your feedback!', 'success')
    else:
        flash('Invalid feedback. Please provide a rating between 1 and 5.', 'danger')

    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  DELETE ATTACHMENT
# ─────────────────────────────────────────────
@student_bp.route(
    '/ticket/<int:ticket_id>/attachment/<int:attachment_id>/delete',
    methods=['POST']
)
@login_required
@role_required('Student')
def delete_attachment(ticket_id, attachment_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
    if not ticket.is_editable:
        flash('Attachments cannot be removed after a ticket has been assigned.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    attachment = Attachment.query.get_or_404(attachment_id)
    if attachment.TicketId != ticket_id:
        abort(403)

    if os.path.exists(attachment.FilePath):
        os.remove(attachment.FilePath)
    db.session.delete(attachment)
    db.session.commit()
    flash('Attachment removed.', 'info')
    return redirect(url_for('student.edit_ticket', ticket_id=ticket_id))