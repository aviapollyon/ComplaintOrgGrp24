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


# Blueprint architecture layout explicitly enclosing routes specific to staff-level personnel actions
staff_bp = Blueprint('staff', __name__)


# Translation dictionary bridging string dropdown values directly to SQLAlchemy Enum mapped data types
# Used when translating POST data to database column insertions 
_STATUS_MAP = {
    'In Progress': (StatusEnum.InProgress, UpdateStatusEnum.InProgress),
    'Rejected'   : (StatusEnum.Rejected,   UpdateStatusEnum.Rejected),
}


# ── DASHBOARD ────────────────────────────────────────────────────────────────

# Staff dashboard view route: Main landing hub pulling metric aggregations and query results for assigned cases 
@staff_bp.route('/dashboard')
@login_required
@role_required('Staff')
def dashboard():
    # Instantiate WTForm processing URL parameters (GET queries via request.args) for filtering
    filter_form = StaffTicketFilterForm(request.args)  
    
    # Restrict raw search bounds exclusively to tickets explicitly bound to the logged-in staff worker ID
    query = Ticket.query.filter_by(StaffId=current_user.UserId)  

    # Injecting condition filters lazily prior to actual DB query execution
    if filter_form.status.data:
        try:
            # Type-cast the string data via StatusEnum wrapper to crash out on malicious or invalid payloads 
            query = query.filter(Ticket.Status == StatusEnum(filter_form.status.data))
        except ValueError:
            pass # Ignore invalid inputs safely without erroring user
            
    if filter_form.priority.data:
        try:
            query = query.filter(Ticket.Priority == PriorityEnum(filter_form.priority.data))
        except ValueError:
            pass
            
    if filter_form.category.data:
        # Match string enum explicitly on category taxonomy options map 
        query = query.filter(Ticket.Category == filter_form.category.data)

    # Finally perform .all() to compute data stream out of Database memory 
    tickets = query.order_by(Ticket.UpdatedAt.desc()).all()  
    
    # Establish total assigned payload completely independent from the currently set UI filter constraints 
    all_assigned = Ticket.query.filter_by(StaffId=current_user.UserId).all()  

    # Map out the history block checking specifically resolving criteria 
    resolved_tickets = [
        t for t in all_assigned
        if t.Status == StatusEnum.Resolved and t.ResolvedAt
    ]
    
    # Time delta metric block determining aggregate average execution speeds for closing work items 
    avg_resolution_hours = None
    if resolved_tickets:
        total_secs = sum(
            (t.ResolvedAt - t.CreatedAt).total_seconds()
            for t in resolved_tickets
        )
        avg_resolution_hours = round(total_secs / len(resolved_tickets) / 3600, 1)

    # Dictionary generating dashboard data-display KPI totals logic
    stats = {
        'total'        : len(all_assigned),
        'in_progress'  : sum(1 for t in all_assigned if t.Status == StatusEnum.InProgress),
        'pending_info' : sum(1 for t in all_assigned if t.Status == StatusEnum.PendingInfo),
        'resolved'     : len(resolved_tickets),
        # Extrapolate issue urgency evaluating standard date minus 3 total day time thresholds
        'overdue'      : sum(
            1 for t in all_assigned
            if t.Status not in (StatusEnum.Resolved, StatusEnum.Rejected)
            and (datetime.utcnow() - t.CreatedAt).days > 3
        ),
        'avg_hours': avg_resolution_hours,
    }

    # Transmit payload through Flask runtime renderer to paint user dashboard UI HTML file
    return render_template(
        'staff/dashboard.html',
        tickets=tickets,
        filter_form=filter_form,
        stats=stats
    )


# ── VIEW TICKET ───────────────────────────────────────────────────────────────

# Read-only and Action context route resolving Ticket detail records and populating multi-modal forms 
@staff_bp.route('/ticket/<int:ticket_id>')
@login_required
@role_required('Staff')
def view_ticket(ticket_id):
    # Verify exact security ownership (Does this Specific User Staff ID physically match the assigned ticket?)
    ticket = _get_staff_ticket(ticket_id)  
    
    # Strip nested thread-replies to fetch exactly primary, top-level chronological history update logs 
    updates = (ticket.updates
               .filter_by(ParentUpdateId=None)
               .order_by(TicketUpdate.CreatedAt.asc())
               .all())
               
    # Sift independent attachments off the base model without hitting nested update files
    attachments = ticket.attachments.filter_by(UpdateId=None).all()

    # Pre-render various WTForm instances passing CSRF tokens and mapping fields
    update_form       = UpdateTicketForm()
    resolve_form      = ResolveTicketForm()
    reply_form        = ReplyForm()
    thread_reply_form = StaffThreadReplyForm()

    # Special handling mapping choices dynamically onto the Escalation Request UI Form
    escalation_form = EscalationRequestForm()
    
    # Restrict escalation target choices specifically by hiding the currently bound department 
    other_depts = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).order_by(Department.Name).all()
    escalation_form.target_dept.choices = [
        (d.DepartmentId, d.Name) for d in other_depts
    ]

    # Pre-check database table checking to avoid duplicates 
    pending_escalation = EscalationRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()

    # Mount UI rendering engine packaging massive multi-form payload schema 
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

# Explicit POST router handling mapping of form status switches onto Model definitions
@staff_bp.route('/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required
@role_required('Staff')
def update_ticket(ticket_id):
    # Security ownership validation via custom helper 
    ticket = _get_staff_ticket(ticket_id)  
    form   = UpdateTicketForm()

    if form.validate_on_submit():
        # Validate dropdown maps accurately onto explicit application code structure enums
        mapping = _STATUS_MAP.get(form.status.data)
        if not mapping:
            flash('Invalid status selected.', 'danger')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        # Unpack mapping keys 
        new_status, new_update_status = mapping
        
        # Inject state onto primary entity reference 
        ticket.Status    = new_status
        ticket.UpdatedAt = datetime.utcnow()

        # Mount independent DB entity recording log metrics denoting what stage shifts happened
        db.session.add(TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = form.comment.data.strip(),
            StatusChange  = new_update_status,
            IsReplyThread = False,
        ))
        
        # Fire bulk write directly processing the state alterations instantly in PostgreSQL/SQLite
        db.session.commit()
        flash(f'Ticket status updated to "{form.status.data}".', 'success')
    else:
        # Failure fallback validation missing criteria loop 
        flash('Please fill in all required fields.', 'danger')

    # Force hard structural reroute forcing a pure clean browser reload 
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── RESOLVE ───────────────────────────────────────────────────────────────────

# Terminating route action closing out issue workflow loops 
@staff_bp.route('/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@role_required('Staff')
def resolve_ticket(ticket_id):
    # Standard identity check bounding loop ensuring staff authority matching ticket constraint 
    ticket = _get_staff_ticket(ticket_id)  
    form   = ResolveTicketForm()

    # Form verification ensuring resolution description matches character validation map 
    if form.validate_on_submit():
        # Inject standard Resolved state explicitly closing workflow loop calculations 
        ticket.Status     = StatusEnum.Resolved
        ticket.ResolvedAt = datetime.utcnow()
        ticket.UpdatedAt  = datetime.utcnow()

        # Commemorate final action mapping explicitly appending [RESOLVED] 
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

    # Redirect triggering updated dataset pull directly fetching newly closed ticket context UI
    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── REPLY TO STUDENT (sets Pending Info) ──────────────────────────────────────

# Communication route explicitly designed for requesting external student input  
@staff_bp.route('/ticket/<int:ticket_id>/reply', methods=['POST'])
@login_required
@role_required('Staff')
def reply_ticket(ticket_id):
    # Standard identity check bounding loop ensuring staff authority matching ticket constraint 
    ticket = _get_staff_ticket(ticket_id)  
    form   = ReplyForm()

    if form.validate_on_submit():
        # Inject standard PendingInfo state explicitly stalling workflow SLA targets until student replies 
        ticket.Status    = StatusEnum.PendingInfo
        ticket.UpdatedAt = datetime.utcnow()

        # Mount independent DB entity recording log metrics denoting what stage shifts happened, flagged for external reading
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

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── STAFF THREAD REPLY ────────────────────────────────────────────────────────

# Specific chained/nested child-route handling communication sub-threads isolated to staff comments
@staff_bp.route('/ticket/<int:ticket_id>/thread-reply/<int:update_id>', methods=['POST'])
@login_required
@role_required('Staff')
def thread_reply(ticket_id, update_id):
    ticket = _get_staff_ticket(ticket_id)  
    parent = TicketUpdate.query.get_or_404(update_id)  

    # Restrict operations to precisely matched ticket IDs rendering brute URL manipulation impossible
    if parent.TicketId != ticket_id:
        abort(403)
        
    # Block internal replies against primary static update chunks
    if not parent.IsReplyThread:
        flash('Replies are only allowed on designated reply threads.', 'warning')
        return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

    form = StaffThreadReplyForm()
    if form.validate_on_submit():
        # Instantiate dependent thread mapping implicitly inheriting parent's identifier 
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


# ── REQUEST ESCALATION ────────────────────────────────────────────────────────

# External organizational route offloading assigned staff target scope out onto higher or lateral bodies 
@staff_bp.route('/ticket/<int:ticket_id>/escalate', methods=['POST'])
@login_required
@role_required('Staff')
def request_escalation(ticket_id):
    ticket = _get_staff_ticket(ticket_id)  
    form   = EscalationRequestForm()

    # Pre-computation extracting full organization scope stripped of its native assignment limits
    other_depts = Department.query.filter(
        Department.DepartmentId != ticket.DepartmentId
    ).all()
    form.target_dept.choices = [(d.DepartmentId, d.Name) for d in other_depts]

    if form.validate_on_submit():
        # Pre-flight condition blocking subsequent identical action submissions flooding Administration queue 
        existing = EscalationRequest.query.filter_by(
            TicketId=ticket_id, Status='Pending'
        ).first()
        if existing:
            flash('An escalation request is already pending for this ticket.', 'warning')
            return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))

        target_dept = Department.query.get_or_404(form.target_dept.data)

        # Build persistent explicit tracking mechanism bridging ticket workflow into Administration review scope 
        escalation = EscalationRequest(
            TicketId      = ticket_id,
            RequestedById = current_user.UserId,
            TargetDeptId  = form.target_dept.data,
            Reason        = form.reason.data.strip(),
            Status        = 'Pending',
        )
        db.session.add(escalation)

        # Output standard timeline tag immediately noting staff request is out globally marking the event logic 
        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = (
                f'[ESCALATION REQUESTED] Staff requested escalation to '
                f'{target_dept.Name}. Reason: {form.reason.data.strip()}'
            ),
            IsReplyThread = False,
        ))

        # Hard push mapping UI bell alerts directly onto overarching systemic admin accounts mapping view loops 
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

    return redirect(url_for('staff.view_ticket', ticket_id=ticket_id))


# ── HELPER ────────────────────────────────────────────────────────────────────

# Utility validation extraction encapsulating duplicate redundant permission logic shared over many POST targets  
def _get_staff_ticket(ticket_id: int) -> Ticket:
    ticket = Ticket.query.get_or_404(ticket_id)
    # Immediately HTTP block anyone manually probing identifiers not scoped via assigned staff key column
    if ticket.StaffId != current_user.UserId:
        abort(403)
    return ticket