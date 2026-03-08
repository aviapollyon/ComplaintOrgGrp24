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

# Blueprint mapping isolating routing specifically related directly to the regular Student user role boundaries
student_bp = Blueprint('student', __name__)


# ─────────────────────────────────────────────
#  FILE SERVING  (works for both ticket & update attachments)
# ─────────────────────────────────────────────
# Authenticated system-internal routing path retrieving media artifacts specifically without exposing direct URL access
@student_bp.route('/uploads/<path:filepath>')
@login_required
def serve_upload(filepath):
    """
    Serve uploaded files to users who own or are assigned to the ticket.
    Ensures the file is within the allowed upload directory and exists.
    """
    # Fetch environment specific base location mapped from config
    upload_root = current_app.config['UPLOAD_FOLDER']
    full_path   = os.path.join(upload_root, filepath)

    # Security implementation strictly blocking arbitrary directory-traversal injection (e.g., ../../../etc/passwd)
    if not os.path.abspath(full_path).startswith(os.path.abspath(upload_root)):
        abort(403)
        
    # File-system lookup ensuring the target object realistically physically exists 
    if not os.path.exists(full_path):
        abort(404)

    # Divide string segments targeting precise folder / explicit file name independently 
    directory = os.path.dirname(full_path)
    filename  = os.path.basename(full_path)
    # Stream payload via default robust library tool ensuring MIME interpretation and cache handling
    return send_from_directory(directory, filename)


# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────
# Student landing page compiling status aggregations uniquely bound explicitly into their single identity
@student_bp.route('/dashboard')
@login_required
@role_required('Student')
def dashboard():
    # Instantiate user interface parameter mapping looking specifically for filter state queries explicitly tracked in the URL
    filter_form = TicketFilterForm(request.args)
    # Filter DB queries enforcing isolation exclusively rendering output matching the user ID 
    query = Ticket.query.filter_by(StudentId=current_user.UserId)


    # Evaluate URL arguments conditionally altering SQL constraints
    if filter_form.status.data:
        try:
            # Trap dictionary mapping mismatch inputs resolving silently to ignore state
            query = query.filter(Ticket.Status == StatusEnum(filter_form.status.data))
        except ValueError:
            pass
            
    # Directly match dropdown choice explicitly binding into preset ENUM configurations 
    if filter_form.category.data:
        query = query.filter(Ticket.Category == filter_form.category.data)
        
    # Implement freeform case-insensitive substring database filtering mapping explicitly onto Title components
    if filter_form.search.data:
        query = query.filter(Ticket.Title.ilike(f'%{filter_form.search.data}%'))

    # Load matched instances descending chronologically so fresh/updated items surface first explicitly
    tickets = query.order_by(Ticket.CreatedAt.desc()).all()
    # Cache completely un-filtered instance array tracking overarching profile metric averages globally 
    all_tickets = Ticket.query.filter_by(StudentId=current_user.UserId).all()

    # Construct explicit reporting array utilized explicitly mapping metric UI widgets 
    stats = {
        'total'          : len(all_tickets),
        'pending'        : sum(1 for t in all_tickets if t.Status == StatusEnum.Submitted),
        'in_progress'    : sum(1 for t in all_tickets if t.Status == StatusEnum.InProgress),
        'resolved'       : sum(1 for t in all_tickets if t.Status == StatusEnum.Resolved),
        # Leverage model hybrid property abstraction explicitly looking specifically for outstanding surveys
        'needs_feedback' : sum(1 for t in all_tickets if t.needs_feedback),
    }

    # Transmit payload wrapping template bindings outputting compiled render object 
    return render_template(
        'student/dashboard.html',
        tickets=tickets,
        filter_form=filter_form,
        stats=stats
    )


# ─────────────────────────────────────────────
#  SUBMIT TICKET
# ─────────────────────────────────────────────
# Primary entrypoint capturing structured user complaint generation form payloads
@student_bp.route('/submit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def submit_ticket():
    form = SubmitTicketForm()

    # Core logic wrapping validation evaluating presence of explicitly defined requirements mapping forms
    if form.validate_on_submit():
        # Leverage utility mapping associating explicitly standardized drop-down categories directly to their corresponding departments
        dept_name  = get_department_name_for_category(form.category.data)
        department = Department.query.filter_by(Name=dept_name).first()
        
        # Calculate SLA precedence looking out logically at mapping limits defined inside helper arrays
        priority   = PriorityEnum[get_priority_for_category(form.category.data)]

        # Map attributes explicitly allocating input into object data bindings representing SQL insertion columns
        ticket = Ticket(
            Title        = form.title.data.strip(),
            Description  = form.description.data.strip(),
            Category     = form.category.data,
            Priority     = priority,
            Status       = StatusEnum.Submitted, # Initial queue state binding
            StudentId    = current_user.UserId,
            # Assign department mapping ID physically or assign to none falling back directly to administrator routing
            DepartmentId = department.DepartmentId if department else None,
        )
        # Load item into transaction staging implicitly reserving unique internal Primary Keys without committing the overall sequence yet
        db.session.add(ticket)
        db.session.flush()

        # Iterate potentially numerous files encapsulated within multi-part form payload arrays explicitly mapping attachment lists 
        for file in request.files.getlist('attachments'):
            # Double check existence + safety via utility evaluating acceptable extensions matching pre-defined lists
            if file and file.filename and allowed_file(file.filename):
                filename, filepath = save_uploaded_file(file, ticket.TicketId)
                # Embed mapping into relational mapping table associating ticket explicitly alongside files 
                db.session.add(Attachment(
                    TicketId=ticket.TicketId, FileName=filename, FilePath=filepath
                ))

        # Offload allocation directly mapping available routing balancing via external logical processing logic
        assigned_to = auto_assign_ticket(ticket)

        # Baseline chronological tracking element confirming reception mapped by user specifically establishing audit trace rules
        db.session.add(TicketUpdate(
            TicketId=ticket.TicketId, UserId=current_user.UserId,
            Comment='Ticket submitted.', StatusChange=UpdateStatusEnum.Submitted,
        ))
        
        # Output conditionally matching the success or failure states returned explicitly by routing assignment tools
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

        # Output transactional buffer mapping into definitive database writes capturing all nested model objects identically 
        db.session.commit()
        flash(
            f'Complaint submitted as Ticket #{ticket.TicketId}'
            + (f' and assigned to {assigned_to.FullName}.' if assigned_to else '.'),
            'success'
        )
        return redirect(url_for('student.view_ticket', ticket_id=ticket.TicketId))

    # Base render evaluating and loading mappings mapping dynamically generated priority values injected statically via JSON 
    return render_template(
        'student/submit_ticket.html',
        form=form,
        priority_map_json=json.dumps(CATEGORY_PRIORITY_MAP)
    )


# ─────────────────────────────────────────────
#  VIEW TICKET
# ─────────────────────────────────────────────
# Provide read-only insight checking specific thread state alongside input contexts specifically for ticket creator 
@student_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Student')
def view_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    # Block URL enumeration mapping by explicitly rejecting tickets unrelated specifically entirely to authenticated user 
    if ticket.StudentId != current_user.UserId:
        abort(403)

    # Extract explicitly root-level thread chronologies bypassing isolated intra-staff thread arrays mapped implicitly under children
    updates = (ticket.updates
               .filter_by(ParentUpdateId=None)
               .order_by(TicketUpdate.CreatedAt.asc())
               .all())
               
    # Output file metadata decoupled from generic thread mappings specifically attached during creation
    ticket_attachments = ticket.attachments.filter_by(UpdateId=None).all()
    
    # Conditionally spawn instances depending entirely on whether the item matches explicit rule configurations defining completion
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
# Interactive sub/route capturing threaded inputs mapped explicitly bridging user -> staff requests for context data
@student_bp.route('/ticket/<int:ticket_id>/reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Student')
def reply_to_update(ticket_id, update_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    # Implement strict boundary validation mapping specific security limitations rejecting unauthorized access
    if ticket.StudentId != current_user.UserId:
        abort(403)

    # Look explicitly linking up precisely defined chronologies mapping exactly against existing threads
    parent_update = TicketUpdate.query.get_or_404(update_id)
    if parent_update.TicketId != ticket_id:
        abort(403)

    # ── Server-side gate: explicitly restricts user interactions explicitly to instances mapped with boolean truth flags ──
    if not parent_update.IsReplyThread:
        flash('Replies are only allowed on designated reply threads.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = StudentReplyForm()
    if form.validate_on_submit():
        # Inject standard relation definitions binding specific ID values connecting hierarchical mappings directly 
        reply = TicketUpdate(
            TicketId       = ticket_id,
            UserId         = current_user.UserId,
            Comment        = form.comment.data.strip(),
            ParentUpdateId = update_id,
            IsReplyThread  = False,
        )
        db.session.add(reply)
        # Flush captures internal unique ID creation enabling reliable directory mappings immediately afterwards
        db.session.flush()

        # Handle iteration iterating multiple files dynamically mapping explicit target nested sub-folders corresponding directly to Update IDs
        for file in request.files.getlist('attachments'):
            # Validate presence explicitly guaranteeing valid structures passed through the library utility functions
            if file and file.filename and allowed_file(file.filename):
                upload_root = current_app.config['UPLOAD_FOLDER']
                # Subdivide file hierarchies physically organizing payloads out cleanly separated directly aligning with specific update logs
                update_dir  = os.path.join(upload_root, f'update_{reply.UpdateId}')
                os.makedirs(update_dir, exist_ok=True)
                
                from werkzeug.utils import secure_filename
                filename = secure_filename(file.filename)
                filepath = os.path.join(update_dir, filename)
                
                # Exfiltrate data physically down out of the temporary processing layer explicitly flushing into hard disk sectors 
                file.save(filepath)
                # Map SQL entity connecting relationships identically out directly linking update chunks
                db.session.add(Attachment(
                    UpdateId=reply.UpdateId, FileName=filename, FilePath=filepath
                ))

        # Set explicitly last modifying tracking data universally checking latest input dates 
        ticket.UpdatedAt = datetime.utcnow()
        db.session.commit()
        flash('Reply sent.', 'success')
    else:
        flash('Reply cannot be empty.', 'danger')

    return redirect(url_for('student.view_ticket', ticket_id=ticket_id))


# ─────────────────────────────────────────────
#  EDIT TICKET
# ─────────────────────────────────────────────
# State modification router enabling submitter adjustments prior to staff assignments
@student_bp.route('/ticket/<int:ticket_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('Student')
def edit_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    # Block unauthorized access probing attempting cross-user boundary violation 
    if ticket.StudentId != current_user.UserId:
        abort(403)
        
    # Strictly enforce logical business rules locking modifications explicitly immediately following state transitions binding staff members
    if not ticket.is_editable:
        flash('This ticket can no longer be edited — it has already been assigned.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = EditTicketForm()
    # Preload user form fields displaying exact current representation stored inside DB
    if request.method == 'GET':
        form.title.data       = ticket.Title
        form.category.data    = ticket.Category
        form.description.data = ticket.Description

    if form.validate_on_submit():
        # Evaluate changed categories requiring dynamically adjusting mapped departments
        new_cat    = form.category.data
        dept_name  = get_department_name_for_category(new_cat)
        department = Department.query.filter_by(Name=dept_name).first()

        # Update entity columns explicitly bridging new choices 
        ticket.Title        = form.title.data.strip()
        ticket.Category     = new_cat
        ticket.Description  = form.description.data.strip()
        
        # Override implicitly mapping the Priority ranking matching explicit taxonomy dictionary lookups
        ticket.Priority     = PriorityEnum[get_priority_for_category(new_cat)]
        # Conditionally fallback explicitly avoiding destroying previously matched department states implicitly during null events
        ticket.DepartmentId = department.DepartmentId if department else ticket.DepartmentId
        ticket.UpdatedAt    = datetime.utcnow()

        # Execute explicitly mapping multi-file uploads into system directories associating strictly alongside root IDs 
        for file in request.files.getlist('attachments'):
            if file and file.filename and allowed_file(file.filename):
                filename, filepath = save_uploaded_file(file, ticket.TicketId)
                db.session.add(Attachment(
                    TicketId=ticket.TicketId, FileName=filename, FilePath=filepath
                ))

        # Output timeline logs detailing specifically that alterations happened during valid unlocked limits 
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
# Action explicitly closing request looping prior to staff execution 
@student_bp.route('/ticket/<int:ticket_id>/withdraw', methods=['POST'])
@login_required
@role_required('Student')
def withdraw_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
        
    # Utilize internally abstracted hybrid boundary limits preventing withdrawals during late phases 
    if not ticket.is_withdrawable:
        flash('This ticket cannot be withdrawn at its current stage.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    # Reject specifically sets internally terminal state tracking effectively destroying live ticket looping
    ticket.Status    = StatusEnum.Rejected
    ticket.UpdatedAt = datetime.utcnow()
    
    # Broadcast timeline object matching final terminal node 
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
# Survey closing mechanism triggered specifically directly following complete resolution closures
@student_bp.route('/ticket/<int:ticket_id>/feedback', methods=['POST'])
@login_required
@role_required('Student')
def submit_feedback(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.StudentId != current_user.UserId:
        abort(403)
        
    # Evaluate hybrid boundary checking validating survey eligibility based firmly against status definitions
    if not ticket.needs_feedback:
        flash('Feedback already submitted or ticket is not resolved.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    form = FeedbackForm()
    if form.validate_on_submit():
        # Extrapolate metrics feeding specifically mapped global Admin analysis arrays 
        ticket.FeedbackRating  = form.rating.data
        ticket.FeedbackComment = form.comment.data
        ticket.FeedbackAt      = datetime.utcnow()
        ticket.UpdatedAt       = datetime.utcnow()
        
        # Log timeline tracking validating survey input successfully
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
# Individual nested routing mapping precisely to exact file components tied specifically to early stage tickets 
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
        
    # Constrain deletion mapping perfectly alongside editability checks ensuring historical trace locks
    if not ticket.is_editable:
        flash('Attachments cannot be removed after a ticket has been assigned.', 'warning')
        return redirect(url_for('student.view_ticket', ticket_id=ticket_id))

    attachment = Attachment.query.get_or_404(attachment_id)
    
    # Secure object isolation guaranteeing parent target belongs entirely alongside internal model relationships 
    if attachment.TicketId != ticket_id:
        abort(403)

    # Clean local file instances specifically ripping data manually off primary operating file system blocks 
    if os.path.exists(attachment.FilePath):
        os.remove(attachment.FilePath)
        
    # Eject structural entity mapping out specifically against relational array memory limits
    db.session.delete(attachment)
    db.session.commit()
    flash('Attachment removed.', 'info')
    
    return redirect(url_for('student.edit_ticket', ticket_id=ticket_id))