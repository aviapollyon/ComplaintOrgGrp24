
"""
Admin routes: manage users, tickets, departments, reports, and announcements.
This file contains all the Flask route handlers and helper functions for admin operations.
"""
import csv
import io
from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, Response
)
from flask_login import login_required, current_user
from app import db
from app.models.user             import User, RoleEnum
from app.models.ticket           import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update    import TicketUpdate, UpdateStatusEnum
from app.models.department       import Department
from app.models.announcement     import Announcement
from app.models.admin_notification import AdminNotification
from app.models.escalation       import EscalationRequest
from app.utils.decorators        import role_required
from app.forms.admin_forms       import (
    AddUserForm, EditUserForm,
    AdminTicketFilterForm, AdminUserFilterForm,
    ReassignTicketForm, ForceStatusForm,
    AddDepartmentForm, EditDepartmentForm,
    AnnouncementForm, EscalationReviewForm,
)


# Create a Flask Blueprint for admin-related routes
admin_bp = Blueprint('admin', __name__)




# Helper function to get department choices for forms.
# If include_blank is True, adds an 'All Departments' option at the top.
def _dept_choices(include_blank=True):
    depts   = Department.query.order_by(Department.Name).all()
    choices = [(d.DepartmentId, d.Name) for d in depts]
    if include_blank:
        choices.insert(0, (0, 'All Departments'))
    return choices




# Helper function to get staff choices for a department.
# Returns a list of (UserId, 'Full Name (N open)') for each staff member in the department.
def _staff_choices_for_dept(dept_id):
    staff = (User.query
             .filter_by(Role=RoleEnum.Staff, IsActive=True, DepartmentId=dept_id)
             .order_by(User.FullName).all())
    return [(s.UserId, f'{s.FullName} ({_open_count(s)} open)') for s in staff]




# Helper function to count open (not resolved/rejected) tickets for a staff user.
def _open_count(staff_user):
    return Ticket.query.filter(
        Ticket.StaffId == staff_user.UserId,
        ~Ticket.Status.in_([StatusEnum.Resolved, StatusEnum.Rejected])
    ).count()


#######################################################################
# ── DASHBOARD ─────────────────────────────────────────────────────────
#######################################################################


# Admin dashboard route: shows overall system stats, recent tickets, and department summaries.
@admin_bp.route('/dashboard')
@login_required
@role_required('Admin')
def dashboard():
    # Gather statistics for dashboard widgets (user/ticket counts by status)
    stats = {
        'total_users'  : User.query.filter_by(IsActive=True).count(),  # Active users
        'total_tickets': Ticket.query.count(),                         # All tickets
        'submitted'    : Ticket.query.filter_by(Status=StatusEnum.Submitted).count(),
        'assigned'     : Ticket.query.filter_by(Status=StatusEnum.Assigned).count(),
        'in_progress'  : Ticket.query.filter_by(Status=StatusEnum.InProgress).count(),
        'pending_info' : Ticket.query.filter_by(Status=StatusEnum.PendingInfo).count(),
        'resolved'     : Ticket.query.filter_by(Status=StatusEnum.Resolved).count(),
        'rejected'     : Ticket.query.filter_by(Status=StatusEnum.Rejected).count(),
    }

    # Get 10 most recent tickets for quick admin review
    recent_tickets = (Ticket.query
                      .order_by(Ticket.CreatedAt.desc())
                      .limit(10).all())

    # Build department-level stats: total, open, and resolved tickets per department
    departments = Department.query.order_by(Department.Name).all()
    dept_stats  = []
    for dept in departments:
        all_t  = Ticket.query.filter_by(DepartmentId=dept.DepartmentId).all()  # All tickets for dept
        open_t = [t for t in all_t
                  if t.Status not in (StatusEnum.Resolved, StatusEnum.Rejected)]  # Not closed
        dept_stats.append({
            'dept'    : dept,
            'total'   : len(all_t),
            'open'    : len(open_t),
            'resolved': sum(1 for t in all_t if t.Status == StatusEnum.Resolved),
        })

    # Count unread admin notifications for the bell icon
    unread_count = AdminNotification.query.filter_by(IsRead=False).count()

    # Render the dashboard template with all stats and lists
    return render_template(
        'admin/dashboard.html',
        stats=stats,
        recent_tickets=recent_tickets,
        dept_stats=dept_stats,
        unread_count=unread_count,
    )


# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
# Notifications route: View all admin notifications and mark them as read.
@admin_bp.route('/notifications')
@login_required
@role_required('Admin')
def notifications():
    # Automatically mark all unread notifications as read when this page is visited
    AdminNotification.query.filter_by(IsRead=False).update({'IsRead': True})
    db.session.commit()

    # Retrieve all notifications ordered by the newest first
    all_notifs = (AdminNotification.query
                  .order_by(AdminNotification.CreatedAt.desc())
                  .all())
    return render_template('admin/notifications.html', notifications=all_notifs)


# ── USERS ─────────────────────────────────────────────────────────────────────
# Users route: list and filter users.
@admin_bp.route('/users')
@login_required
@role_required('Admin')
def users():
    filter_form = AdminUserFilterForm(request.args)
    filter_form.department.choices = _dept_choices()

    # Start with a base query for all users
    query = User.query
    
    # Filter by user name or email (partial match search)
    if filter_form.search.data:
        s = f'%{filter_form.search.data}%'
        query = query.filter((User.FullName.ilike(s)) | (User.Email.ilike(s)))
        
    # Filter by user role (e.g. Student, Staff, Admin)
    if filter_form.role.data:
        try:
            query = query.filter(User.Role == RoleEnum(filter_form.role.data))
        except ValueError:
            pass
            
    # Filter by assigned department if appropriate
    if filter_form.department.data and filter_form.department.data != 0:
        query = query.filter(User.DepartmentId == filter_form.department.data)

    # Execute the query, sorting by name alphabetically
    users_list = query.order_by(User.FullName).all()
    return render_template('admin/users.html', users=users_list, filter_form=filter_form)


# Add User route: form to manually create a new user account.
@admin_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def add_user():
    form = AddUserForm()
    # Populate the department dropdown choices
    form.department.choices = [(0, '— None —')] + [
        (d.DepartmentId, d.Name)
        for d in Department.query.order_by(Department.Name).all()
    ]
    if form.validate_on_submit():
        # Prevent creating multiple users with the same email
        if User.query.filter_by(Email=form.email.data.strip().lower()).first():
            flash('Email already registered.', 'danger')
            return render_template('admin/user_form.html', form=form, edit=False)

        # Create the user object
        user = User(
            FullName     = form.full_name.data.strip(),
            Email        = form.email.data.strip().lower(),
            Role         = RoleEnum[form.role.data],
            DepartmentId = form.department.data if form.department.data != 0 else None,
            IsActive     = True,
        )
        # Hash the password and save the user
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'User {user.FullName} created.', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', form=form, edit=False)


# Edit User route: form to update user details.
@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = EditUserForm(obj=user)
    
    # Populate the department dropdown choices
    form.department.choices = [(0, '— None —')] + [
        (d.DepartmentId, d.Name)
        for d in Department.query.order_by(Department.Name).all()
    ]

    # Handle GET request: Pre-fill the form with the user's existing data
    if request.method == 'GET':
        form.full_name.data  = user.FullName
        form.email.data      = user.Email
        form.role.data       = user.Role.value
        form.department.data = user.DepartmentId or 0

    # Handle POST request: Update user data if form is valid
    if form.validate_on_submit():
        # Make sure the updated email does not conflict with another existing user
        existing = User.query.filter(
            User.Email == form.email.data.strip().lower(),
            User.UserId != user_id
        ).first()
        if existing:
            flash('That email is already in use.', 'danger')
            return render_template('admin/user_form.html', form=form, edit=True, user=user)

        user.FullName     = form.full_name.data.strip()
        user.Email        = form.email.data.strip().lower()
        user.Role         = RoleEnum[form.role.data]
        user.DepartmentId = form.department.data if form.department.data != 0 else None
        user.UpdatedAt    = datetime.utcnow()
        db.session.commit()
        flash('User updated.', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', form=form, edit=True, user=user)


# Toggle User route: Activate or deactivate a user account.
@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@role_required('Admin')
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Ensure the admin does not deactivate their own account accidentally
    if user.UserId == current_user.UserId:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.users'))
        
    user.IsActive  = not user.IsActive
    user.UpdatedAt = datetime.utcnow()
    db.session.commit()
    
    state = 'reactivated' if user.IsActive else 'deactivated'
    flash(f'{user.FullName} has been {state}.', 'success')
    return redirect(url_for('admin.users'))


# User Detail route: View a user's details, including tickets assigned or submitted by them.
@admin_bp.route('/users/<int:user_id>')
@login_required
@role_required('Admin')
def user_detail(user_id):
    user = User.query.get_or_404(user_id)

    # Calculate metrics based on the user's role
    if user.Role == RoleEnum.Student:
        tickets = (user.submitted_tickets
                   .order_by(Ticket.CreatedAt.desc()).all())
        avg_turnaround = None
    elif user.Role == RoleEnum.Staff:
        tickets = (user.assigned_tickets
                   .order_by(Ticket.CreatedAt.desc()).all())
        # Average turnaround for resolved tickets by this staff member
        resolved = [t for t in tickets if t.Status == StatusEnum.Resolved and t.ResolvedAt]
        if resolved:
            avg_secs = sum(
                (t.ResolvedAt - t.CreatedAt).total_seconds()
                for t in resolved
            ) / len(resolved)
            avg_turnaround = round(avg_secs / 3600, 1)
        else:
            avg_turnaround = None
    else:
        # Admin generally doesn't have assigned/submitted tickets tracked here
        tickets        = []
        avg_turnaround = None

    return render_template(
        'admin/user_detail.html',
        user=user,
        tickets=tickets,
        avg_turnaround=avg_turnaround,
    )


# ── TICKETS ───────────────────────────────────────────────────────────────────
# Tickets route: List all tickets with filtering options.
@admin_bp.route('/tickets')
@login_required
@role_required('Admin')
def tickets():
    filter_form = AdminTicketFilterForm(request.args)
    filter_form.department.choices = _dept_choices()
    filter_form.staff.choices      = [(0, 'All Staff')] + [
        (s.UserId, s.FullName)
        for s in User.query.filter_by(Role=RoleEnum.Staff, IsActive=True)
                            .order_by(User.FullName).all()
    ]

    query = Ticket.query
    if filter_form.search.data:
        s = f'%{filter_form.search.data}%'
        query = query.filter(Ticket.Title.ilike(s))
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
    if filter_form.department.data and filter_form.department.data != 0:
        query = query.filter(Ticket.DepartmentId == filter_form.department.data)
    if filter_form.staff.data and filter_form.staff.data != 0:
        query = query.filter(Ticket.StaffId == filter_form.staff.data)

    tickets_list = query.order_by(Ticket.CreatedAt.desc()).all()
    return render_template('admin/tickets.html', tickets=tickets_list, filter_form=filter_form)

@admin_bp.route('/tickets/<int:ticket_id>')
@login_required
@role_required('Admin')
def ticket_detail(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    # Auto-dismiss admin notifications for this ticket
    AdminNotification.query.filter_by(
        TicketId=ticket_id, IsRead=False
    ).update({'IsRead': True})
    db.session.commit()


    updates     = (ticket.updates
                   .filter_by(ParentUpdateId=None)
                   .order_by(TicketUpdate.CreatedAt.asc())
                   .all())
    attachments = ticket.attachments.filter_by(UpdateId=None).all()

    reassign_form = ReassignTicketForm()
    reassign_form.staff_id.choices = _staff_choices_for_dept(ticket.DepartmentId)

    force_form = ForceStatusForm()

    pending_escalation = EscalationRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()

    escalation_form = EscalationReviewForm() if pending_escalation else None
    if escalation_form and pending_escalation:
        escalation_form.staff_id.choices = _staff_choices_for_dept(
            pending_escalation.TargetDeptId
        )

    return render_template(
        'admin/ticket_detail.html',
        ticket=ticket,
        updates=updates,
        attachments=attachments,
        reassign_form=reassign_form,
        force_form=force_form,
        pending_escalation=pending_escalation,
        escalation_form=escalation_form,
    )


# Reassign Ticket route: Admin shifts responsibility to a different staff member.
@admin_bp.route('/tickets/<int:ticket_id>/reassign', methods=['POST'])
@login_required
@role_required('Admin')
def reassign_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    form   = ReassignTicketForm()
    
    # Must explicitly re-populate choices so WTForms validation passes
    form.staff_id.choices = _staff_choices_for_dept(ticket.DepartmentId)

    if form.validate_on_submit():
        new_staff = User.query.get_or_404(form.staff_id.data)
        old_name  = ticket.staff.FullName if ticket.staff else 'Unassigned'

        # Apply standard reassignment attributes
        ticket.StaffId   = new_staff.UserId
        ticket.Status    = StatusEnum.Assigned
        ticket.UpdatedAt = datetime.utcnow()

        # Log this decision via a ticket update
        db.session.add(TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = (f'[ADMIN] Reassigned from {old_name} to {new_staff.FullName}.'),
            StatusChange  = UpdateStatusEnum.Assigned,
            IsReplyThread = False,
        ))
        db.session.commit()
        flash(f'Ticket reassigned to {new_staff.FullName}.', 'success')
    else:
        flash('Please select a staff member.', 'danger')

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))


# Force Status route: Admins can forcibly alter the ticket stage without matching normal staff conditions.
@admin_bp.route('/tickets/<int:ticket_id>/force-status', methods=['POST'])
@login_required
@role_required('Admin')
def force_status(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    form   = ForceStatusForm()

    if form.validate_on_submit():
        try:
            new_status = StatusEnum(form.status.data)
        except ValueError:
            flash('Invalid status.', 'danger')
            return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))

        # Push the new status directly onto the db record
        ticket.Status    = new_status
        ticket.UpdatedAt = datetime.utcnow()
        if new_status == StatusEnum.Resolved and not ticket.ResolvedAt:
            ticket.ResolvedAt = datetime.utcnow()

        # Try to map ticket StatusEnum onto TicketUpdate statusEnum
        try:
            update_status = UpdateStatusEnum(form.status.data)
        except ValueError:
            update_status = None

        # Include an explicit message detailing an Admin Over-ride was used
        db.session.add(TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = f'[ADMIN OVERRIDE] {form.comment.data.strip()}',
            StatusChange  = update_status,
            IsReplyThread = False,
        ))
        db.session.commit()
        flash(f'Status changed to "{new_status.value}".', 'success')
    else:
        flash('Please fill in all required fields.', 'danger')

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))


# Review Escalation route: Handle when staff escalate an issue outside their scope/department.
@admin_bp.route('/tickets/<int:ticket_id>/escalation/review', methods=['POST'])
@login_required
@role_required('Admin')
def review_escalation(ticket_id):
    ticket     = Ticket.query.get_or_404(ticket_id)
    escalation = EscalationRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first_or_404()

    form = EscalationReviewForm()
    # Populate the dropdown options strictly for the target/target department
    form.staff_id.choices = _staff_choices_for_dept(escalation.TargetDeptId)

    # Determine whether the admin decided to 'approve' or 'reject'
    action = request.form.get('action')   # 'approve' or 'reject'

    if action == 'approve' and form.validate_on_submit():
        new_staff   = User.query.get_or_404(form.staff_id.data)
        target_dept = escalation.target_dept

        old_dept_name = ticket.department.Name if ticket.department else 'Unknown'

        # Move ticket to the new department and assign the chosen staff member
        ticket.DepartmentId = escalation.TargetDeptId
        ticket.StaffId      = new_staff.UserId
        ticket.Status       = StatusEnum.Assigned
        ticket.UpdatedAt    = datetime.utcnow()

        # Close out the escalation request as Approved
        escalation.Status     = 'Approved'
        escalation.ResolvedAt = datetime.utcnow()

        # Notify via the ticket system exactly what shifts occurred
        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = (
                f'[ADMIN] Escalation approved. Ticket moved from '
                f'{old_dept_name} to {target_dept.Name} '
                f'and assigned to {new_staff.FullName}.'
            ),
            StatusChange  = UpdateStatusEnum.Assigned,
            IsReplyThread = False,
        ))
        db.session.commit()
        flash(f'Escalation approved. Ticket assigned to {new_staff.FullName} '
              f'in {target_dept.Name}.', 'success')

    elif action == 'reject':
        # Leave ticket where it currently is, simply resolve the escalation as Rejected
        escalation.Status     = 'Rejected'
        escalation.ResolvedAt = datetime.utcnow()

        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = '[ADMIN] Escalation request rejected.',
            IsReplyThread = False,
        ))
        db.session.commit()
        flash('Escalation request rejected.', 'info')
    else:
        flash('Invalid escalation action.', 'danger')

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))


# Export Tickets route: Build and stream a CSV file containing comprehensive ticket reporting.
@admin_bp.route('/tickets/export')
@login_required
@role_required('Admin')
def export_tickets():
    # Grab all tickets, newest first
    tickets_list = Ticket.query.order_by(Ticket.CreatedAt.desc()).all()

    # Generator method to build CSV rows lazily
    def generate():
        out = io.StringIO()
        w   = csv.writer(out)
        
        # Write the CSV Header Row
        w.writerow(['ID','Title','Category','Priority','Status','Department',
                    'Student','Assigned Staff','Submitted','Resolved At','Feedback Rating'])
        
        # Write data rows
        for t in tickets_list:
            w.writerow([
                t.TicketId, t.Title, t.Category, t.Priority.value, t.Status.value,
                t.department.Name if t.department else '',
                t.student.FullName if t.student else '',
                t.staff.FullName   if t.staff    else '',
                t.CreatedAt.strftime('%Y-%m-%d %H:%M'),
                t.ResolvedAt.strftime('%Y-%m-%d %H:%M') if t.ResolvedAt else '',
                t.FeedbackRating or '',
            ])
            # Yield content chunk and reset memory buffer (StringIO) block
            yield out.getvalue()
            out.seek(0); out.truncate(0)

    # Return as directly downloadable file Streamed as comma separated payload
    return Response(generate(), headers={
        'Content-Disposition': 'attachment; filename=tickets_export.csv',
        'Content-Type': 'text/csv',
    })


# ── DEPARTMENTS ───────────────────────────────────────────────────────────────
# Departments Home route: View all org-departments and quick-stats on tickets/staff.
@admin_bp.route('/departments')
@login_required
@role_required('Admin')
def departments():
    depts     = Department.query.order_by(Department.Name).all()
    dept_data = []
    
    # Calculate aggregation statistics per department 
    for dept in depts:
        dept_data.append({
            'dept'        : dept,
            # Count the number of ACTIVE staff linked to this department
            'staff_count' : User.query.filter_by(Role=RoleEnum.Staff,
                                DepartmentId=dept.DepartmentId, IsActive=True).count(),
            # Count the amount of NON-RESOLVED, NON-REJECTED tickets (essentially, outstanding operations)
            'open_tickets': Ticket.query.filter(
                                Ticket.DepartmentId == dept.DepartmentId,
                                ~Ticket.Status.in_([StatusEnum.Resolved, StatusEnum.Rejected])
                            ).count(),
        })
    add_form = AddDepartmentForm()
    return render_template('admin/departments.html', dept_data=dept_data, add_form=add_form)


# Add Department route
@admin_bp.route('/departments/add', methods=['POST'])
@login_required
@role_required('Admin')
def add_department():
    form = AddDepartmentForm()
    if form.validate_on_submit():
        # Duplicate name guard check
        if Department.query.filter_by(Name=form.name.data.strip()).first():
            flash('A department with that name already exists.', 'danger')
        else:
            # Build and commit the new department model to the database
            db.session.add(Department(Name=form.name.data.strip(),
                                      Description=form.description.data.strip() or None))
            db.session.commit()
            flash('Department added.', 'success')
    else:
        flash('Please provide a valid department name.', 'danger')
    return redirect(url_for('admin.departments'))


# Edit Department route
@admin_bp.route('/departments/<int:dept_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def edit_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    form = EditDepartmentForm(obj=dept)
    
    # Pre-populate fields on GET request
    if request.method == 'GET':
        form.name.data        = dept.Name
        form.description.data = dept.Description
        
    if form.validate_on_submit():
        # Duplicate name guard check: Look for SAME name on a DIFFERENT dept ID
        conflict = Department.query.filter(
            Department.Name == form.name.data.strip(),
            Department.DepartmentId != dept_id
        ).first()
        
        if conflict:
            flash('Another department already has that name.', 'danger')
            return render_template('admin/dept_form.html', form=form, dept=dept)
            
        # Push changes onto record map
        dept.Name        = form.name.data.strip()
        dept.Description = form.description.data.strip() or None
        db.session.commit()
        flash('Department updated.', 'success')
        return redirect(url_for('admin.departments'))
        
    return render_template('admin/dept_form.html', form=form, dept=dept)


# Department Detail view: Drill in to look closely at connected users & tickets per dept.
@admin_bp.route('/departments/<int:dept_id>')
@login_required
@role_required('Admin')
def department_detail(dept_id):
    dept       = Department.query.get_or_404(dept_id)
    
    # Fetch purely the staff within this single specific department bounds
    staff_list = (User.query.filter_by(Role=RoleEnum.Staff, DepartmentId=dept_id)
                  .order_by(User.FullName).all())
                  
    # Extricate recent issue tickets tagged correctly against this specific body 
    tickets    = (Ticket.query.filter_by(DepartmentId=dept_id)
                  .order_by(Ticket.CreatedAt.desc()).all())
                  
    return render_template('admin/department_detail.html',
                           dept=dept, staff_list=staff_list, tickets=tickets)


# ── REPORTS ───────────────────────────────────────────────────────────────────
# Reports summary dashboard route: Analytics compiling historical trends for total issues & resolutions
@admin_bp.route('/reports')
@login_required
@role_required('Admin')
def reports():
    from dateutil.relativedelta import relativedelta
    from app.utils.helpers import TICKET_CATEGORIES

    departments = Department.query.order_by(Department.Name).all()
    today = datetime.utcnow()

    months, month_data = [], []
    
    # Iterate backwards through last 12 calendar months to build ticket volume metrics chart arrays
    for i in range(11, -1, -1):
        start = (today - relativedelta(months=i)).replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0)
        end   = start + relativedelta(months=1)
        months.append(start.strftime('%b %Y'))
        # Count creation within timeframe limits
        month_data.append(Ticket.query.filter(
            Ticket.CreatedAt >= start, Ticket.CreatedAt < end).count())

    # Build metric dataset for how each distinct Department is performing individually
    dept_labels, dept_resolved, dept_unresolved, dept_avg_times = [], [], [], []
    for dept in departments:
        total    = Ticket.query.filter_by(DepartmentId=dept.DepartmentId).count()
        resolved = Ticket.query.filter_by(DepartmentId=dept.DepartmentId,
                                          Status=StatusEnum.Resolved).count()
        dept_labels.append(dept.Name)
        dept_resolved.append(resolved)
        dept_unresolved.append(total - resolved)
        
        # Calculate metric average duration elapsed prior to Resolution outcome assignment
        rt = Ticket.query.filter(Ticket.DepartmentId == dept.DepartmentId,
                                 Ticket.Status == StatusEnum.Resolved,
                                 Ticket.ResolvedAt != None).all()  # noqa: E711
        dept_avg_times.append(
            round(sum((t.ResolvedAt - t.CreatedAt).total_seconds()
                      for t in rt) / len(rt) / 3600, 1) if rt else 0
        )

    # Static categorization breakdowns logic iteration over preset config choices
    category_counts = [Ticket.query.filter_by(Category=cat).count()
                       for cat in TICKET_CATEGORIES]

    # Individual breakdown dataset generation over user-staff assignment metric success and failure percentages 
    staff_list = User.query.filter_by(Role=RoleEnum.Staff, IsActive=True).all()
    staff_perf = []
    for s in staff_list:
        assigned   = Ticket.query.filter_by(StaffId=s.UserId).count()
        resolved_t = Ticket.query.filter(Ticket.StaffId == s.UserId,
                                         Ticket.Status == StatusEnum.Resolved,
                                         Ticket.ResolvedAt != None).all()  # noqa: E711
                                         
        # Tally metrics determining staff hourly throughput vs peer average output limits
        avg_hrs    = (round(sum((t.ResolvedAt - t.CreatedAt).total_seconds()
                               for t in resolved_t) / len(resolved_t) / 3600, 1)
                      if resolved_t else None)
        rated      = [t for t in resolved_t if t.FeedbackRating]
        
        # Determine average sentiment/satisfaction metric user-scoring outcome 
        avg_rating = (round(sum(t.FeedbackRating for t in rated) / len(rated), 1)
                      if rated else None)
                      
        staff_perf.append({'staff': s, 'assigned': assigned,
                           'resolved': len(resolved_t),
                           'avg_hours': avg_hrs, 'avg_rating': avg_rating})

    # Output highly complex variable package object out onto visual template framework
    return render_template(
        'admin/reports.html',
        months=months, month_data=month_data,
        dept_labels=dept_labels, dept_resolved=dept_resolved,
        dept_unresolved=dept_unresolved, dept_avg_times=dept_avg_times,
        categories=TICKET_CATEGORIES, category_counts=category_counts,
        staff_perf=staff_perf, departments=departments,
    )


# ── ANNOUNCEMENTS ─────────────────────────────────────────────────────────────
# Manage Announcements broadcast module globally alerting either staff, students, or both.
@admin_bp.route('/announcements', methods=['GET', 'POST'])
@login_required
@role_required('Admin')
def announcements():
    form = AnnouncementForm()
    if form.validate_on_submit():
        # Inject standard broadcast entity mapping the creator/target demographic parameters provided via modal
        db.session.add(Announcement(
            Title=form.title.data.strip(), Message=form.message.data.strip(),
            TargetAudience=form.audience.data, CreatedBy=current_user.UserId, IsActive=True,
        ))
        db.session.commit()
        flash('Announcement posted.', 'success')
        return redirect(url_for('admin.announcements'))

    # Load descending latest communication broadcasts globally tracking records onto grid list
    all_announcements = Announcement.query.order_by(Announcement.CreatedAt.desc()).all()
    return render_template('admin/announcements.html',
                           form=form, announcements=all_announcements)


# Hard Delete Announcements route target function mapping explicitly wiping legacy/mistaken message signals
@admin_bp.route('/announcements/<int:ann_id>/delete', methods=['POST'])
@login_required
@role_required('Admin')
def delete_announcement(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    # Physically excise from live db instance
    db.session.delete(ann)
    db.session.commit()
    flash('Announcement deleted.', 'info')
    return redirect(url_for('admin.announcements'))