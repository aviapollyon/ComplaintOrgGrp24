from flask import Blueprint, render_template
from flask_login import login_required
from app.utils.decorators import role_required
from app.models.user import User
from app.models.ticket import Ticket

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/dashboard')
@login_required
@role_required('Admin')
def dashboard():
    total_users = User.query.count()
    total_tickets = Ticket.query.count()
    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           total_tickets=total_tickets)