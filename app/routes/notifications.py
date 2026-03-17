import time

from flask import Blueprint, render_template, redirect, url_for, request, jsonify, Response, stream_with_context
from flask_login import login_required, current_user
from app import db
from app.models.user_notification import UserNotification
from app.models.admin_notification import AdminNotification
from app.models.user import RoleEnum
from app.services.realtime import wait_for_events, sse_frame

notif_bp = Blueprint('notif', __name__)


def _ticket_link_for_role(role: RoleEnum, ticket_id: int) -> str:
    if role == RoleEnum.Student:
        return url_for('student.view_ticket', ticket_id=ticket_id)
    if role == RoleEnum.Staff:
        return url_for('staff.view_ticket', ticket_id=ticket_id)
    if role == RoleEnum.Admin:
        return url_for('admin.ticket_detail', ticket_id=ticket_id)
    return '#'


def _serialize_user_notification(n: UserNotification):
    return {
        'notification_id': n.NotificationId,
        'title': n.Title,
        'message': n.Message,
        'type': n.Type,
        'is_read': bool(n.IsRead),
        'ticket_id': n.TicketId,
        'created_at': n.CreatedAt.isoformat() if n.CreatedAt else None,
        'ticket_link': _ticket_link_for_role(current_user.Role, n.TicketId) if n.TicketId else None,
    }


def _serialize_admin_notification(n: AdminNotification):
    return {
        'notification_id': n.NotificationId,
        'type': n.Type,
        'message': n.Message,
        'is_read': bool(n.IsRead),
        'ticket_id': n.TicketId,
        'created_at': n.CreatedAt.isoformat() if n.CreatedAt else None,
        'ticket_link': _ticket_link_for_role(current_user.Role, n.TicketId) if n.TicketId else None,
    }


@notif_bp.route('/notifications')
@login_required
def list_notifications():
    # Mark all as read when page is opened
    UserNotification.query.filter_by(
        UserId=current_user.UserId, IsRead=False
    ).update({'IsRead': True})
    db.session.commit()

    all_notifs = (UserNotification.query
                  .filter_by(UserId=current_user.UserId)
                  .order_by(UserNotification.CreatedAt.desc())
                  .limit(50).all())
    return render_template('notifications/list.html', notifications=all_notifs)


@notif_bp.route('/notifications/mark-read/<int:notif_id>', methods=['POST'])
@login_required
def mark_read(notif_id):
    n = UserNotification.query.get_or_404(notif_id)
    if n.UserId != current_user.UserId:
        return jsonify({'error': 'forbidden'}), 403
    n.IsRead = True
    db.session.commit()
    return redirect(request.referrer or url_for('notif.list_notifications'))


@notif_bp.route('/notifications/stream')
@login_required
def stream_notifications():
    uid = current_user.UserId
    role = current_user.Role
    last_user_arg = request.args.get('last_user_notif_id')
    last_admin_arg = request.args.get('last_admin_notif_id')

    if last_user_arg is None:
        last_user_id = db.session.query(db.func.max(UserNotification.NotificationId)).filter(
            UserNotification.UserId == uid
        ).scalar() or 0
    else:
        last_user_id = int(last_user_arg)

    if role == RoleEnum.Admin:
        if last_admin_arg is None:
            last_admin_id = db.session.query(db.func.max(AdminNotification.NotificationId)).scalar() or 0
        else:
            last_admin_id = int(last_admin_arg)
    else:
        last_admin_id = 0

    @stream_with_context
    def generate():
        nonlocal last_user_id, last_admin_id
        sequence = 0
        last_db_poll = 0.0

        while True:
            pushed = wait_for_events(uid, timeout_seconds=15)
            for event in pushed:
                sequence += 1
                yield sse_frame(event.get('type', 'notification'), event.get('payload', {}), str(sequence))

            now = time.monotonic()
            should_poll_db = (not pushed) and ((now - last_db_poll) >= 10)
            if should_poll_db:
                fresh_user = (UserNotification.query
                              .filter(UserNotification.UserId == uid,
                                      UserNotification.NotificationId > last_user_id)
                              .order_by(UserNotification.NotificationId.asc())
                              .limit(20)
                              .all())
                for n in fresh_user:
                    last_user_id = max(last_user_id, n.NotificationId)
                    sequence += 1
                    yield sse_frame('notification', _serialize_user_notification(n), str(sequence))

                if role == RoleEnum.Admin:
                    fresh_admin = (AdminNotification.query
                                   .filter(AdminNotification.NotificationId > last_admin_id)
                                   .order_by(AdminNotification.NotificationId.asc())
                                   .limit(20)
                                   .all())
                    for n in fresh_admin:
                        last_admin_id = max(last_admin_id, n.NotificationId)
                        sequence += 1
                        yield sse_frame('admin_notification', _serialize_admin_notification(n), str(sequence))

                last_db_poll = now

            sequence += 1
            yield sse_frame('heartbeat', {'ts': int(time.time())}, str(sequence))

    headers = {
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
    }
    return Response(generate(), mimetype='text/event-stream', headers=headers)