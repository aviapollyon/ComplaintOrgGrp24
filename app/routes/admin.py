
"""
Admin routes: manage users, tickets, departments, reports, and announcements.
This file contains all the Flask route handlers and helper functions for admin operations.
"""
import csv
import io
import os
from datetime import datetime, timedelta
from collections import defaultdict
from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, Response, current_app, jsonify
)
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app import db
from app.models.user             import User, RoleEnum
from app.models.ticket           import Ticket, StatusEnum, PriorityEnum
from app.models.ticket_update    import TicketUpdate, UpdateStatusEnum
from app.models.department       import Department
from app.models.announcement     import Announcement
from app.models.admin_notification import AdminNotification
from app.models.escalation       import EscalationRequest
from app.models.reassignment_request import ReassignmentRequest
from app.models.reopen_request   import ReopenRequest
from app.models.ticket_comment   import TicketComment
from app.models.ticket_vote      import TicketVote
from app.models.ticket_flag      import TicketFlag, FlaggedTicket
from app.models.ticket_chat_message import TicketChatMessage
from app.models.ticket_chat_attachment import TicketChatAttachment
from app.models.ticket_chat_presence import TicketChatPresence
from app.utils.decorators        import role_required
from app.utils.helpers           import log_audit, allowed_file, attachment_url
from app.forms.admin_forms       import (
    AddUserForm, EditUserForm,
    AdminTicketFilterForm, AdminUserFilterForm,
    ReassignTicketForm, ForceStatusForm, ForcePriorityForm,
    AddDepartmentForm, EditDepartmentForm,
    AnnouncementForm, EscalationReviewForm,
)
from app.forms.student_forms import TicketCommentForm
from app.forms.staff_forms import LiveChatMessageForm
from app.services.notifications import notify_sla_breach, notify_live_chat_message
from app.services.realtime import publish_user_event


# Create a Flask Blueprint for admin-related routes
admin_bp = Blueprint('admin', __name__)
STUDENT_EMAIL_DOMAIN = '@dut4life.ac.za'
STAFF_ADMIN_EMAIL_DOMAIN = '@dut.ac.za'
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
    recipients = {uid for uid in _chat_participant_ids(ticket) if uid != sender_id}
    related_staff = _chat_related_staff_ids(ticket)
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


def _required_domain_for_role(role: RoleEnum) -> str:
    return STUDENT_EMAIL_DOMAIN if role == RoleEnum.Student else STAFF_ADMIN_EMAIL_DOMAIN


def _is_valid_domain_for_role(email: str, role: RoleEnum) -> bool:
    return email.endswith(_required_domain_for_role(role))




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
    pending_actions_count = (
        EscalationRequest.query.filter_by(Status='Pending').count()
        + ReassignmentRequest.query.filter_by(Status='Pending').count()
        + ReopenRequest.query.filter_by(Status='Pending').count()
    )

    # Render the dashboard template with all stats and lists
    return render_template(
        'admin/dashboard.html',
        stats=stats,
        recent_tickets=recent_tickets,
        dept_stats=dept_stats,
        unread_count=unread_count,
        pending_actions_count=pending_actions_count,
    )


@admin_bp.route('/pending-actions')
@login_required
@role_required('Admin')
def pending_actions():
    escalation_requests = (
        EscalationRequest.query
        .filter_by(Status='Pending')
        .order_by(EscalationRequest.CreatedAt.asc())
        .all()
    )
    reassignment_requests = (
        ReassignmentRequest.query
        .filter_by(Status='Pending')
        .order_by(ReassignmentRequest.CreatedAt.asc())
        .all()
    )
    reopen_requests = (
        ReopenRequest.query
        .filter_by(Status='Pending')
        .order_by(ReopenRequest.CreatedAt.asc())
        .all()
    )

    return render_template(
        'admin/pending_actions.html',
        escalation_requests=escalation_requests,
        reassignment_requests=reassignment_requests,
        reopen_requests=reopen_requests,
    )


@admin_bp.route('/recurring-issues')
@login_required
@role_required('Admin')
def recurring_issues():
    status = request.args.get('status', 'all', type=str)
    if status not in ('all', 'active', 'dismissed'):
        status = 'all'

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    if per_page not in (10, 15, 25, 50, 100):
        per_page = 15

    query = TicketFlag.query
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
                .filter(FlaggedTicket.FlagId.in_(flag_ids))
                .group_by(FlaggedTicket.FlagId)
                .all()
            )
        }

    return render_template(
        'admin/recurring_issues.html',
        flags=flags,
        pagination=pagination,
        status=status,
        linked_counts=linked_counts,
    )


@admin_bp.route('/recurring-issues/<int:flag_id>/tickets')
@login_required
@role_required('Admin')
def recurring_issue_tickets(flag_id):
    flag = TicketFlag.query.get_or_404(flag_id)

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 15, type=int)
    if per_page not in (10, 15, 25, 50, 100):
        per_page = 15

    query = (
        Ticket.query
        .join(FlaggedTicket, FlaggedTicket.TicketId == Ticket.TicketId)
        .filter(FlaggedTicket.FlagId == flag.FlagId)
        .order_by(Ticket.CreatedAt.desc())
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return render_template(
        'admin/flagged_tickets.html',
        flag=flag,
        tickets=pagination.items,
        pagination=pagination,
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
    page       = request.args.get('page', 1, type=int)
    try:
        per_page = int(filter_form.per_page.data or current_app.config.get('USERS_PER_PAGE', 20))
    except (ValueError, TypeError):
        per_page = current_app.config.get('USERS_PER_PAGE', 20)
    pagination = query.order_by(User.FullName).paginate(page=page, per_page=per_page, error_out=False)
    users_list = pagination.items
    return render_template('admin/users.html', users=users_list, pagination=pagination, filter_form=filter_form)


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
        selected_role = RoleEnum[form.role.data]
        normalized_email = form.email.data.strip().lower()

        if not _is_valid_domain_for_role(normalized_email, selected_role):
            flash(
                f'{selected_role.value} accounts require an email ending with '
                f'{_required_domain_for_role(selected_role)}.',
                'danger'
            )
            return render_template('admin/user_form.html', form=form, edit=False)

        # Prevent creating multiple users with the same email
        if User.query.filter_by(Email=normalized_email).first():
            flash('Email already registered.', 'danger')
            return render_template('admin/user_form.html', form=form, edit=False)

        # Create the user object
        user = User(
            FullName     = form.full_name.data.strip(),
            Email        = normalized_email,
            Role         = selected_role,
            DepartmentId = form.department.data if form.department.data != 0 else None,
            IsActive     = True,
        )
        # Hash the password and save the user
        user.set_password(form.password.data)
        db.session.add(user)
        log_audit('user_created', target_type='user',
                  details=f'Created {user.Role.value} account: {user.Email}')
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
        selected_role = RoleEnum[form.role.data]
        normalized_email = form.email.data.strip().lower()

        if not _is_valid_domain_for_role(normalized_email, selected_role):
            flash(
                f'{selected_role.value} accounts require an email ending with '
                f'{_required_domain_for_role(selected_role)}.',
                'danger'
            )
            return render_template('admin/user_form.html', form=form, edit=True, user=user)

        # Make sure the updated email does not conflict with another existing user
        existing = User.query.filter(
            User.Email == normalized_email,
            User.UserId != user_id
        ).first()
        if existing:
            flash('That email is already in use.', 'danger')
            return render_template('admin/user_form.html', form=form, edit=True, user=user)

        user.FullName     = form.full_name.data.strip()
        user.Email        = normalized_email
        user.Role         = selected_role
        user.DepartmentId = form.department.data if form.department.data != 0 else None
        user.UpdatedAt    = datetime.utcnow()
        log_audit('user_updated', target_type='user', target_id=user_id,
                  details=f'Updated profile for {user.Email}')
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
    state = 'reactivated' if user.IsActive else 'deactivated'
    log_audit(f'user_{state}', target_type='user', target_id=user_id,
              details=f'{user.FullName} ({user.Email})')
    db.session.commit()
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
def _build_admin_ticket_query(filter_form):
    from app.utils.sorting import apply_sort

    query = Ticket.query
    if filter_form.search.data:
        s = f'%{filter_form.search.data}%'
        query = query.filter(
            db.or_(
                Ticket.Title.ilike(s),
                Ticket.TrackingRef.ilike(s),
            )
        )
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
    if filter_form.department.data and filter_form.department.data != 0:
        query = query.filter(Ticket.DepartmentId == filter_form.department.data)
    if filter_form.staff.data and filter_form.staff.data != 0:
        query = query.filter(Ticket.StaffId == filter_form.staff.data)

    return apply_sort(query, filter_form.sort.data or 'newest')


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

    query        = _build_admin_ticket_query(filter_form)
    page         = request.args.get('page', 1, type=int)
    try:
        per_page = int(filter_form.per_page.data or current_app.config.get('TICKETS_PER_PAGE', 15))
    except (ValueError, TypeError):
        per_page = current_app.config.get('TICKETS_PER_PAGE', 15)
    pagination   = query.paginate(page=page, per_page=per_page, error_out=False)
    tickets_list = pagination.items

    for t in tickets_list:
        if t.is_response_sla_overdue:
            notify_sla_breach(t, 'first_response')
        if t.is_resolution_sla_overdue:
            notify_sla_breach(t, 'resolution')
    db.session.commit()

    return render_template('admin/tickets.html', tickets=tickets_list,
                           pagination=pagination,
                           filter_form=filter_form)

@admin_bp.route('/tickets/<int:ticket_id>')
@login_required
@role_required('Admin')
def ticket_detail(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    if ticket.is_response_sla_overdue:
        notify_sla_breach(ticket, 'first_response')
    if ticket.is_resolution_sla_overdue:
        notify_sla_breach(ticket, 'resolution')
    db.session.commit()
    
    from app.models.reopen_request       import ReopenRequest
    from app.models.reassignment_request import ReassignmentRequest

    pending_reopen   = ReopenRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()
    pending_reassign = ReassignmentRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first()

    # add to render_template call:


    # Auto-dismiss admin notifications for this ticket
    AdminNotification.query.filter_by(
        TicketId=ticket_id, IsRead=False
    ).update({'IsRead': True})
    db.session.commit()


    updates     = (ticket.updates
                   .filter_by(ParentUpdateId=None)
                   .order_by(TicketUpdate.CreatedAt.asc())
                   .all())
    student_comments = (TicketComment.query
                        .filter_by(TicketId=ticket.TicketId, ParentCommentId=None)
                        .order_by(TicketComment.CreatedAt.desc())
                        .all())
    attachments = ticket.attachments.filter_by(UpdateId=None).all()

    reassign_form = ReassignTicketForm()
    reassign_form.staff_id.choices = _staff_choices_for_dept(ticket.DepartmentId)

    force_form = ForceStatusForm()

    priority_form = ForcePriorityForm()
    comment_form = TicketCommentForm()
    live_chat_form = LiveChatMessageForm()

    chat_messages = (TicketChatMessage.query
                     .filter_by(TicketId=ticket.TicketId)
                     .order_by(TicketChatMessage.ChatMessageId.asc())
                     .limit(100)
                     .all())
    chat_participants = _chat_participant_badges(ticket)

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
        student_comments=student_comments,
        attachments=attachments,
        reassign_form=reassign_form,
        force_form=force_form,
        priority_form=priority_form,
        comment_form=comment_form,
        live_chat_form=live_chat_form,
        pending_escalation=pending_escalation,
        escalation_form=escalation_form,
        pending_reopen=pending_reopen,
        pending_reassign=pending_reassign,
        chat_messages=chat_messages,
        chat_participants=chat_participants,
    )


@admin_bp.route('/tickets/<int:ticket_id>/chat/messages')
@login_required
@role_required('Admin')
def list_chat_messages(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

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


@admin_bp.route('/tickets/<int:ticket_id>/chat/send', methods=['POST'])
@login_required
@role_required('Admin')
def send_chat_message(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    if ticket.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
        flash('Live chat is closed for resolved or rejected tickets.', 'warning')
        return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id, _anchor='admin-livechat-pane'))

    form = LiveChatMessageForm()
    if not form.validate_on_submit():
        flash('Chat message must contain between 1 and 2000 characters.', 'danger')
        return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id, _anchor='admin-livechat-pane'))

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

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id, _anchor='admin-livechat-pane'))


@admin_bp.route('/tickets/<int:ticket_id>/chat/heartbeat', methods=['POST'])
@login_required
@role_required('Admin')
def chat_heartbeat(ticket_id):
    Ticket.query.get_or_404(ticket_id)
    _touch_chat_presence(ticket_id, current_user.UserId)
    db.session.commit()
    return jsonify({'ok': True})


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
        log_audit('ticket_reassigned', target_type='ticket', target_id=ticket_id,
                  details=f'{old_name} → {new_staff.FullName}')
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
        old_status = ticket.Status.value
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
        log_audit('ticket_status_changed', target_type='ticket', target_id=ticket_id,
                  details=f'Status: {old_status} → {new_status.value}')
        db.session.commit()
        flash(f'Status changed to "{new_status.value}".', 'success')
    else:
        flash('Please fill in all required fields.', 'danger')

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))


# Force Priority route: Admin overrides the ticket priority with an audit trail.
@admin_bp.route('/tickets/<int:ticket_id>/force-priority', methods=['POST'])
@login_required
@role_required('Admin')
def force_priority(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    form   = ForcePriorityForm()

    if form.validate_on_submit():
        try:
            new_priority = PriorityEnum(form.priority.data)
        except ValueError:
            flash('Invalid priority.', 'danger')
            return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))

        old_priority     = ticket.Priority.value if ticket.Priority else 'Not Set'
        ticket.Priority  = new_priority
        ticket.UpdatedAt = datetime.utcnow()

        db.session.add(TicketUpdate(
            TicketId      = ticket.TicketId,
            UserId        = current_user.UserId,
            Comment       = (f'[ADMIN PRIORITY OVERRIDE] Priority changed from '
                             f'{old_priority} to {new_priority.value}. '
                             f'Reason: {form.reason.data.strip()}'),
            IsReplyThread = False,
        ))
        log_audit('ticket_priority_changed', target_type='ticket', target_id=ticket_id,
                  details=f'Priority: {old_priority} → {new_priority.value}')
        db.session.commit()
        flash(f'Priority changed to "{new_priority.value}".', 'success')
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
        from app.services.notifications import notify_escalation_rejected
        requesting_staff = User.query.get(escalation.RequestedById)
        if requesting_staff:
            notify_escalation_rejected(ticket, requesting_staff)
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
    filter_form = AdminTicketFilterForm(request.args)
    filter_form.department.choices = _dept_choices()
    filter_form.staff.choices      = [(0, 'All Staff')] + [
        (s.UserId, s.FullName)
        for s in User.query.filter_by(Role=RoleEnum.Staff, IsActive=True)
                            .order_by(User.FullName).all()
    ]

    tickets_query = (_build_admin_ticket_query(filter_form)
                     .options(
                         joinedload(Ticket.department),
                         joinedload(Ticket.student),
                         joinedload(Ticket.staff),
                     ))

    max_rows = int(current_app.config.get('CSV_EXPORT_MAX_ROWS', 50000))
    row_count = tickets_query.count()
    if row_count > max_rows:
        flash(
            f'Export limit exceeded ({row_count} rows). Narrow filters to {max_rows} rows or fewer.',
            'warning',
        )
        return redirect(url_for('admin.tickets', **request.args.to_dict(flat=True)))

    tickets_list = tickets_query.all()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')

    # Generator method to build CSV rows lazily
    def generate():
        out = io.StringIO(newline='')
        w   = csv.writer(out)
        
        # Write the CSV Header Row
        w.writerow(['ID','Title','Category','Priority','Status','Department',
                    'Student','Assigned Staff','Submitted','Resolved At','Feedback Rating'])
        # Prefix BOM for Excel UTF-8 compatibility on Windows.
        yield '\ufeff' + out.getvalue()
        out.seek(0); out.truncate(0)
        
        # Write data rows
        for t in tickets_list:
            w.writerow([
                t.TicketId,
                t.Title,
                t.Category,
                t.Priority.value if t.Priority else 'Not Set',
                t.Status.value,
                t.department.Name if t.department else '',
                t.student.FullName if t.student else '',
                t.staff.FullName   if t.staff    else '',
                t.CreatedAt.strftime('%Y-%m-%d %H:%M UTC') if t.CreatedAt else '',
                t.ResolvedAt.strftime('%Y-%m-%d %H:%M UTC') if t.ResolvedAt else '',
                t.FeedbackRating or '',
            ])
            # Yield content chunk and reset memory buffer (StringIO) block
            yield out.getvalue()
            out.seek(0); out.truncate(0)

    # Return as directly downloadable file Streamed as comma separated payload
    return Response(generate(), headers={
        'Content-Disposition': f'attachment; filename=tickets_export_{timestamp}.csv',
        'Content-Type': 'text/csv; charset=utf-8',
        'Cache-Control': 'no-store',
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
    return render_template('admin/departments.html', dept_data=dept_data)


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

    now = datetime.utcnow()
    range_key = request.args.get('range', '365').strip().lower()
    start_raw = request.args.get('start_date', '').strip()
    end_raw = request.args.get('end_date', '').strip()

    preset_days = {'30': 30, '90': 90, '365': 365}
    if range_key in preset_days:
        window_start = (now - timedelta(days=preset_days[range_key])).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        window_end = now
    elif range_key == 'custom' and start_raw and end_raw:
        try:
            custom_start = datetime.strptime(start_raw, '%Y-%m-%d')
            custom_end = datetime.strptime(end_raw, '%Y-%m-%d') + timedelta(days=1)
            if custom_start >= custom_end:
                raise ValueError('invalid_range')
            window_start = custom_start
            window_end = custom_end
        except ValueError:
            flash('Invalid custom date range. Falling back to last 365 days.', 'warning')
            range_key = '365'
            window_start = (now - timedelta(days=365)).replace(hour=0, minute=0, second=0, microsecond=0)
            window_end = now
    else:
        range_key = '365'
        window_start = (now - timedelta(days=365)).replace(hour=0, minute=0, second=0, microsecond=0)
        window_end = now

    report_window_label = (
        f"{window_start.strftime('%d %b %Y')} - {(window_end - timedelta(seconds=1)).strftime('%d %b %Y')}"
    )
    report_window = [
        Ticket.CreatedAt >= window_start,
        Ticket.CreatedAt < window_end,
    ]

    departments = Department.query.order_by(Department.Name).all()
    closed_statuses = [StatusEnum.Resolved, StatusEnum.Rejected]

    months, monthly_created, monthly_resolved = [], [], []
    span_days = max(1, (window_end - window_start).days)
    if span_days <= 45:
        cursor = window_start
        while cursor < window_end:
            bucket_end = min(cursor + timedelta(days=1), window_end)
            months.append(cursor.strftime('%d %b'))
            monthly_created.append(Ticket.query.filter(Ticket.CreatedAt >= cursor, Ticket.CreatedAt < bucket_end).count())
            monthly_resolved.append(Ticket.query.filter(
                Ticket.ResolvedAt != None,  # noqa: E711
                Ticket.ResolvedAt >= cursor,
                Ticket.ResolvedAt < bucket_end,
            ).count())
            cursor = bucket_end
    else:
        cursor = window_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor < window_end:
            bucket_end = cursor + relativedelta(months=1)
            months.append(cursor.strftime('%b %Y'))
            monthly_created.append(Ticket.query.filter(Ticket.CreatedAt >= cursor, Ticket.CreatedAt < bucket_end).count())
            monthly_resolved.append(Ticket.query.filter(
                Ticket.ResolvedAt != None,  # noqa: E711
                Ticket.ResolvedAt >= cursor,
                Ticket.ResolvedAt < bucket_end,
            ).count())
            cursor = bucket_end

    total_tickets = Ticket.query.filter(*report_window).count()
    resolved_total = Ticket.query.filter(*report_window, Ticket.Status == StatusEnum.Resolved).count()
    open_total = Ticket.query.filter(*report_window, ~Ticket.Status.in_(closed_statuses)).count()
    high_priority_open = Ticket.query.filter(
        *report_window,
        Ticket.Priority == PriorityEnum.High,
        ~Ticket.Status.in_(closed_statuses),
    ).count()

    resolved_pairs = db.session.query(Ticket.CreatedAt, Ticket.ResolvedAt).filter(
        *report_window,
        Ticket.Status == StatusEnum.Resolved,
            Ticket.ResolvedAt != None,  # noqa: E711
    ).all()
    avg_resolution_hours = round(
        sum((r.ResolvedAt - r.CreatedAt).total_seconds() for r in resolved_pairs) / len(resolved_pairs) / 3600,
        1,
    ) if resolved_pairs else 0

    staff_response_ticket_ids = {
        ticket_id for (ticket_id,) in db.session.query(TicketUpdate.TicketId)
        .join(User, TicketUpdate.UserId == User.UserId)
        .join(Ticket, Ticket.TicketId == TicketUpdate.TicketId)
        .filter(User.Role == RoleEnum.Staff)
        .filter(*report_window)
        .distinct()
        .all()
    }
    open_rows = db.session.query(Ticket.TicketId, Ticket.DepartmentId, Ticket.CreatedAt).filter(
        *report_window,
        ~Ticket.Status.in_(closed_statuses)
    ).all()
    response_cutoff = now - relativedelta(hours=24)
    resolution_cutoff = now - relativedelta(hours=48)
    at_risk_start = now - relativedelta(hours=48)
    at_risk_end = now - relativedelta(hours=42)

    response_overdue = 0
    resolution_overdue = 0
    at_risk_resolution = 0
    response_overdue_by_dept = defaultdict(int)
    resolution_overdue_by_dept = defaultdict(int)
    at_risk_by_dept = defaultdict(int)
    open_by_dept = defaultdict(int)

    for row in open_rows:
        open_by_dept[row.DepartmentId] += 1
        if row.CreatedAt < resolution_cutoff:
            resolution_overdue += 1
            resolution_overdue_by_dept[row.DepartmentId] += 1
        elif at_risk_start <= row.CreatedAt < at_risk_end:
            at_risk_resolution += 1
            at_risk_by_dept[row.DepartmentId] += 1

        if row.CreatedAt < response_cutoff and row.TicketId not in staff_response_ticket_ids:
            response_overdue += 1
            response_overdue_by_dept[row.DepartmentId] += 1

    response_sla_met = max(0, open_total - response_overdue)
    resolution_sla_met = max(0, open_total - resolution_overdue)
    response_sla_rate = round((response_sla_met / open_total) * 100, 1) if open_total else 100.0
    resolution_sla_rate = round((resolution_sla_met / open_total) * 100, 1) if open_total else 100.0

    status_order = [
        StatusEnum.Submitted,
        StatusEnum.Assigned,
        StatusEnum.InProgress,
        StatusEnum.PendingInfo,
        StatusEnum.Resolved,
        StatusEnum.Rejected,
    ]
    status_map = {status.value: 0 for status in status_order}
    for status_value, count in db.session.query(Ticket.Status, db.func.count(Ticket.TicketId)).filter(
        *report_window
    ).group_by(Ticket.Status).all():
        status_map[status_value.value] = count
    status_labels = [s.value for s in status_order]
    status_counts = [status_map[s.value] for s in status_order]

    priority_order = [PriorityEnum.High, PriorityEnum.Medium, PriorityEnum.Low]
    priority_map = {priority.value: 0 for priority in priority_order}
    for priority_value, count in db.session.query(Ticket.Priority, db.func.count(Ticket.TicketId)).filter(
        *report_window,
        Ticket.Priority != None  # noqa: E711
    ).group_by(Ticket.Priority).all():
        priority_map[priority_value.value] = count
    priority_labels = [p.value for p in priority_order]
    priority_counts = [priority_map[p.value] for p in priority_order]

    escalation_counts = {'Pending': 0, 'Approved': 0, 'Rejected': 0}
    for status, count in db.session.query(EscalationRequest.Status, db.func.count(EscalationRequest.EscalationId)).filter(
        EscalationRequest.CreatedAt >= window_start,
        EscalationRequest.CreatedAt < window_end,
    ).group_by(EscalationRequest.Status).all():
        escalation_counts[status] = count

    reopen_counts = {'Pending': 0, 'Approved': 0, 'Rejected': 0}
    for status, count in db.session.query(ReopenRequest.Status, db.func.count(ReopenRequest.RequestId)).filter(
        ReopenRequest.CreatedAt >= window_start,
        ReopenRequest.CreatedAt < window_end,
    ).group_by(ReopenRequest.Status).all():
        reopen_counts[status] = count

    category_count_map = {cat: 0 for cat in TICKET_CATEGORIES}
    for category, count in db.session.query(Ticket.Category, db.func.count(Ticket.TicketId)).filter(
        *report_window
    ).group_by(Ticket.Category).all():
        if category in category_count_map:
            category_count_map[category] = count

    vote_count_map = defaultdict(int)
    for category, count in db.session.query(Ticket.Category, db.func.count(TicketVote.VoteId)).join(
        Ticket, Ticket.TicketId == TicketVote.TicketId
    ).filter(
        *report_window
    ).group_by(Ticket.Category).all():
        vote_count_map[category] = count

    comment_count_map = defaultdict(int)
    for category, count in db.session.query(Ticket.Category, db.func.count(TicketComment.CommentId)).join(
        Ticket, Ticket.TicketId == TicketComment.TicketId
    ).filter(
        *report_window
    ).group_by(Ticket.Category).all():
        comment_count_map[category] = count

    avg_rating_map = defaultdict(lambda: None)
    for category, avg_rating in db.session.query(Ticket.Category, db.func.avg(Ticket.FeedbackRating)).filter(
        *report_window,
        Ticket.FeedbackRating != None  # noqa: E711
    ).group_by(Ticket.Category).all():
        avg_rating_map[category] = round(float(avg_rating), 1) if avg_rating is not None else None

    categories = list(TICKET_CATEGORIES)
    category_counts = [category_count_map[cat] for cat in categories]

    top_categories = []
    for cat in categories:
        top_categories.append({
            'name': cat,
            'count': category_count_map[cat],
            'votes': vote_count_map[cat],
            'comments': comment_count_map[cat],
            'avg_rating': avg_rating_map[cat],
        })
    top_categories.sort(key=lambda x: x['count'], reverse=True)
    top_categories = [row for row in top_categories if row['count'] > 0][:10]

    dept_labels = [dept.Name for dept in departments]
    dept_resolved_map = defaultdict(int)
    for dept_id, count in db.session.query(Ticket.DepartmentId, db.func.count(Ticket.TicketId)).filter(
        *report_window,
        Ticket.Status == StatusEnum.Resolved
    ).group_by(Ticket.DepartmentId).all():
        dept_resolved_map[dept_id] = count

    dept_open = [open_by_dept[dept.DepartmentId] for dept in departments]
    dept_resolved = [dept_resolved_map[dept.DepartmentId] for dept in departments]

    dept_duration_totals = defaultdict(float)
    dept_duration_counts = defaultdict(int)
    for dept_id, created_at, resolved_at in db.session.query(
        Ticket.DepartmentId,
        Ticket.CreatedAt,
        Ticket.ResolvedAt,
    ).filter(
        *report_window,
        Ticket.Status == StatusEnum.Resolved,
        Ticket.ResolvedAt != None,  # noqa: E711
    ).all():
        if not created_at or not resolved_at:
            continue
        dept_duration_totals[dept_id] += (resolved_at - created_at).total_seconds()
        dept_duration_counts[dept_id] += 1

    dept_health = []
    for dept in departments:
        dept_id = dept.DepartmentId
        avg_hours = None
        if dept_duration_counts[dept_id]:
            avg_hours = round((dept_duration_totals[dept_id] / dept_duration_counts[dept_id]) / 3600, 1)

        dept_total_active = open_by_dept[dept_id]
        dept_response_rate = round(
            ((dept_total_active - response_overdue_by_dept[dept_id]) / dept_total_active) * 100,
            1,
        ) if dept_total_active else 100.0
        dept_resolution_rate = round(
            ((dept_total_active - resolution_overdue_by_dept[dept_id]) / dept_total_active) * 100,
            1,
        ) if dept_total_active else 100.0

        dept_health.append({
            'name': dept.Name,
            'resolved': dept_resolved_map[dept_id],
            'open': dept_total_active,
            'response_breaches': response_overdue_by_dept[dept_id],
            'resolution_breaches': resolution_overdue_by_dept[dept_id],
            'at_risk': at_risk_by_dept[dept_id],
            'avg_hours': avg_hours,
            'response_rate': dept_response_rate,
            'resolution_rate': dept_resolution_rate,
        })

    staff_list = User.query.options(joinedload(User.department)).filter_by(
        Role=RoleEnum.Staff,
        IsActive=True,
    ).order_by(User.FullName).all()

    assigned_map = defaultdict(int)
    for staff_id, count in db.session.query(Ticket.StaffId, db.func.count(Ticket.TicketId)).filter(
        *report_window,
        Ticket.StaffId != None  # noqa: E711
    ).group_by(Ticket.StaffId).all():
        assigned_map[staff_id] = count

    open_assigned_map = defaultdict(int)
    for staff_id, count in db.session.query(Ticket.StaffId, db.func.count(Ticket.TicketId)).filter(
        *report_window,
        Ticket.StaffId != None,  # noqa: E711
        ~Ticket.Status.in_(closed_statuses),
    ).group_by(Ticket.StaffId).all():
        open_assigned_map[staff_id] = count

    resolved_map = defaultdict(int)
    duration_totals = defaultdict(float)
    rating_totals = defaultdict(float)
    rating_counts = defaultdict(int)

    for staff_id, created_at, resolved_at, rating in db.session.query(
        Ticket.StaffId,
        Ticket.CreatedAt,
        Ticket.ResolvedAt,
        Ticket.FeedbackRating,
    ).filter(
        *report_window,
        Ticket.StaffId != None,  # noqa: E711
        Ticket.Status == StatusEnum.Resolved,
        Ticket.ResolvedAt != None,  # noqa: E711
    ).all():
        resolved_map[staff_id] += 1
        if created_at and resolved_at:
            duration_totals[staff_id] += (resolved_at - created_at).total_seconds()
        if rating is not None:
            rating_totals[staff_id] += rating
            rating_counts[staff_id] += 1

    staff_perf = []
    for staff in staff_list:
        assigned = assigned_map[staff.UserId]
        resolved = resolved_map[staff.UserId]
        avg_hours = round((duration_totals[staff.UserId] / resolved) / 3600, 1) if resolved else None
        avg_rating = round(rating_totals[staff.UserId] / rating_counts[staff.UserId], 1) if rating_counts[staff.UserId] else None
        resolution_rate = round((resolved / assigned) * 100, 1) if assigned else 0

        staff_perf.append({
            'staff': staff,
            'assigned': assigned,
            'open_assigned': open_assigned_map[staff.UserId],
            'resolved': resolved,
            'resolution_rate': resolution_rate,
            'avg_hours': avg_hours,
            'avg_rating': avg_rating,
        })

    staff_perf.sort(key=lambda row: (row['open_assigned'], row['assigned']), reverse=True)

    summary = {
        'total_tickets': total_tickets,
        'resolved_total': resolved_total,
        'open_total': open_total,
        'avg_resolution_hours': avg_resolution_hours,
        'high_priority_open': high_priority_open,
        'response_overdue': response_overdue,
        'resolution_overdue': resolution_overdue,
        'at_risk_resolution': at_risk_resolution,
        'response_sla_rate': response_sla_rate,
        'resolution_sla_rate': resolution_sla_rate,
    }

    report_checks = [
        {
            'label': 'Status Total Matches Ticket Total',
            'ok': sum(status_counts) == total_tickets,
            'detail': f"{sum(status_counts)} vs {total_tickets}",
        },
        {
            'label': 'Category Total Matches Ticket Total',
            'ok': sum(category_counts) == total_tickets,
            'detail': f"{sum(category_counts)} vs {total_tickets}",
        },
        {
            'label': 'Open+Resolved+Rejected Consistency',
            'ok': (open_total + status_map[StatusEnum.Resolved.value] + status_map[StatusEnum.Rejected.value]) == total_tickets,
            'detail': f"{open_total + status_map[StatusEnum.Resolved.value] + status_map[StatusEnum.Rejected.value]} vs {total_tickets}",
        },
    ]

    range_state = {
        'selected': range_key,
        'start_date': start_raw,
        'end_date': end_raw,
        'window_label': report_window_label,
    }

    return render_template(
        'admin/reports.html',
        now=now,
        range_state=range_state,
        report_checks=report_checks,
        summary=summary,
        months=months,
        month_created=monthly_created,
        month_resolved=monthly_resolved,
        status_labels=status_labels,
        status_counts=status_counts,
        priority_labels=priority_labels,
        priority_counts=priority_counts,
        categories=categories,
        category_counts=category_counts,
        top_categories=top_categories,
        dept_labels=dept_labels,
        dept_resolved=dept_resolved,
        dept_open=dept_open,
        dept_health=dept_health,
        staff_perf=staff_perf,
        escalation_counts=escalation_counts,
        reopen_counts=reopen_counts,
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
        ann = Announcement(
            Title=form.title.data.strip(), Message=form.message.data.strip(),
            TargetAudience=form.audience.data, CreatedBy=current_user.UserId, IsActive=True,
        )
        db.session.add(ann)
        log_audit('announcement_created', target_type='announcement',
                  details=f'Title: {form.title.data.strip()[:60]}')
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

# ── REOPEN TICKET ─────────────────────────────────────────────────────────────
@admin_bp.route('/tickets/<int:ticket_id>/reopen/review', methods=['POST'])
@login_required
@role_required('Admin')
def review_reopen(ticket_id):
    from app.models.reopen_request import ReopenRequest
    from app.services.notifications import notify_ticket_reopened

    ticket = Ticket.query.get_or_404(ticket_id)
    reopen = ReopenRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first_or_404()

    action = request.form.get('action')

    if action == 'approve':
        # Return ticket to the last assigned staff member
        last_staff_id = ticket.StaffId

        # Reopened tickets should collect fresh feedback after a new resolution cycle.
        ticket.FeedbackRating  = None
        ticket.FeedbackComment = None

        # Overwrite resolved timestamps
        ticket.Status     = StatusEnum.InProgress
        ticket.ResolvedAt = None
        ticket.UpdatedAt  = datetime.utcnow()

        reopen.Status     = 'Approved'
        reopen.ResolvedAt = datetime.utcnow()

        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = ('[ADMIN] Reopen request approved. '
                             'Ticket returned to assigned staff for further investigation.'),
            StatusChange  = UpdateStatusEnum.InProgress,
            IsReplyThread = False,
        ))
        notify_ticket_reopened(ticket, current_user)
        db.session.commit()
        flash('Ticket reopened and returned to staff.', 'success')

    elif action == 'reject':
        reopen.Status     = 'Rejected'
        reopen.ResolvedAt = datetime.utcnow()

        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = '[ADMIN] Reopen request rejected.',
            IsReplyThread = False,
        ))
        db.session.commit()
        from app.services.notifications import notify_reopen_rejected
        notify_reopen_rejected(ticket)
        db.session.commit()
        flash('Reopen request rejected.', 'info')
    else:
        flash('Invalid action.', 'danger')

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))


# ── REASSIGNMENT REQUEST REVIEW ───────────────────────────────────────────────
@admin_bp.route('/tickets/<int:ticket_id>/reassignment/review', methods=['POST'])
@login_required
@role_required('Admin')
def review_reassignment(ticket_id):
    from app.models.reassignment_request import ReassignmentRequest
    from app.services.notifications import notify_reassignment_approved

    ticket  = Ticket.query.get_or_404(ticket_id)
    req     = ReassignmentRequest.query.filter_by(
        TicketId=ticket_id, Status='Pending'
    ).first_or_404()
    action  = request.form.get('action')
    old_staff = ticket.staff

    if action == 'approve':
        new_staff        = User.query.get_or_404(req.TargetStaffId)
        ticket.StaffId   = new_staff.UserId
        ticket.Status    = StatusEnum.Assigned
        ticket.UpdatedAt = datetime.utcnow()

        req.Status     = 'Approved'
        req.ResolvedAt = datetime.utcnow()

        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = (f'[ADMIN] Reassignment approved. '
                             f'Ticket moved from {old_staff.FullName if old_staff else "Unassigned"} '
                             f'to {new_staff.FullName}.'),
            StatusChange  = UpdateStatusEnum.Assigned,
            IsReplyThread = False,
        ))
        notify_reassignment_approved(ticket, new_staff, old_staff)
        db.session.commit()
        flash(f'Ticket reassigned to {new_staff.FullName}.', 'success')

    elif action == 'reject':
        req.Status     = 'Rejected'
        req.ResolvedAt = datetime.utcnow()

        db.session.add(TicketUpdate(
            TicketId      = ticket_id,
            UserId        = current_user.UserId,
            Comment       = '[ADMIN] Reassignment request rejected.',
            IsReplyThread = False,
        ))
        db.session.commit()
        from app.services.notifications import notify_reassignment_rejected
        requesting_staff = User.query.get(req.RequestedById)
        if requesting_staff:
            notify_reassignment_rejected(ticket, requesting_staff)
            db.session.commit()
        flash('Reassignment request rejected.', 'info')
    else:
        flash('Invalid action.', 'danger')

    return redirect(url_for('admin.ticket_detail', ticket_id=ticket_id))


# ── DISMISS FLAG ──────────────────────────────────────────────────────────────
@admin_bp.route('/flags/<int:flag_id>/dismiss', methods=['POST'])
@login_required
@role_required('Admin')
def dismiss_flag(flag_id):
    flag = TicketFlag.query.get_or_404(flag_id)
    flag.Status = 'dismissed'
    db.session.commit()
    flash(f'Flag for "{flag.Category} / {flag.Keyword}" dismissed.', 'info')

    next_url = request.form.get('next', '').strip()
    if next_url.startswith('/'):
        return redirect(next_url)
    return redirect(url_for('admin.dashboard'))


# ── AUDIT LOGS ────────────────────────────────────────────────────────────────
@admin_bp.route('/audit-logs')
@login_required
@role_required('Admin')
def audit_logs():
    from app.models.audit_log import AuditLog
    from sqlalchemy.orm import aliased

    page     = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if per_page not in (10, 25, 50, 100):
        per_page = 25
    sort = request.args.get('sort', 'desc')
    if sort not in ('asc', 'desc'):
        sort = 'desc'

    action_q    = request.args.get('action', '').strip()
    actor_q     = request.args.get('actor', '').strip()
    target_type = request.args.get('target_type', '').strip()

    query = AuditLog.query

    if action_q:
        query = query.filter(AuditLog.Action.ilike(f'%{action_q}%'))
    if actor_q:
        # Use an aliased User to avoid clashing with the lazy='joined' auto-join
        # on the `actor` relationship, which would otherwise produce duplicate rows.
        ActorAlias = aliased(User)
        query = (query
                 .join(ActorAlias, AuditLog.ActorId == ActorAlias.UserId, isouter=True)
                 .filter(ActorAlias.FullName.ilike(f'%{actor_q}%')))
    if target_type:
        query = query.filter(AuditLog.TargetType == target_type)

    order_col = AuditLog.CreatedAt.asc() if sort == 'asc' else AuditLog.CreatedAt.desc()
    query     = query.order_by(order_col, AuditLog.LogId.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Distinct action names for filter dropdown
    raw_actions = db.session.query(AuditLog.Action).distinct().order_by(AuditLog.Action).all()
    all_actions = [a[0] for a in raw_actions]

    raw_types = db.session.query(AuditLog.TargetType).distinct().order_by(AuditLog.TargetType).all()
    all_types = [t[0] for t in raw_types if t[0]]

    return render_template(
        'admin/audit_logs.html',
        logs        = pagination.items,
        pagination  = pagination,
        all_actions = all_actions,
        all_types   = all_types,
        action_q    = action_q,
        actor_q     = actor_q,
        target_type = target_type,
        sort        = sort,
        per_page    = per_page,
    )