from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User, RoleEnum
from app.models.department import Department

# Blueprint for authentication-related routes
auth_bp = Blueprint('auth', __name__)


# Home/index route: redirect authenticated users to their dashboard, otherwise to login
@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        role = current_user.Role
        if role == RoleEnum.Student:
            return redirect(url_for('student.dashboard'))  # Student dashboard
        elif role == RoleEnum.Staff:
            return redirect(url_for('staff.dashboard'))    # Staff dashboard
        elif role == RoleEnum.Admin:
            return redirect(url_for('admin.dashboard'))    # Admin dashboard
    return redirect(url_for('auth.login'))  # Not logged in: go to login


# Login route: handles GET (show form) and POST (process login)
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))  # Already logged in

    if request.method == 'POST':
        # Get form data
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(Email=email).first()

        # Check credentials
        if user and user.check_password(password):
            if not user.IsActive:
                flash(
                    'Your account has been deactivated. '
                    'Please contact the administrator for assistance.',
                    'danger'
                )
                return render_template('auth/login.html')

            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('auth.index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


# Registration route: handles GET (show form) and POST (process registration)
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    departments = Department.query.order_by(Department.Name).all()  # List of departments for dropdown

    if request.method == 'POST':
        # Get form data
        full_name   = request.form.get('full_name', '').strip()
        email       = request.form.get('email', '').strip().lower()
        password    = request.form.get('password', '')
        role_str    = request.form.get('role', 'Student')
        dept_id_raw = request.form.get('department_id', '')


        # Check if email is already registered
        if User.query.filter_by(Email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html', departments=departments)

        # Parse role from string, default to Student if invalid
        try:
            role = RoleEnum[role_str]
        except KeyError:
            role = RoleEnum.Student

        # Parse department ID if provided
        dept_id = int(dept_id_raw) if dept_id_raw.isdigit() else None

        # Create new user instance
        user = User(
            FullName     = full_name,
            Email        = email,
            Role         = role,
            DepartmentId = dept_id,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', departments=departments)


# Logout route: logs out the current user
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))