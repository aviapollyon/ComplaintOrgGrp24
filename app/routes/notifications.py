from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.user_notification import UserNotification

notif_bp = Blueprint('notif', __name__)


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