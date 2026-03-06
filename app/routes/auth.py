from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User, RoleEnum
from app.models.department import Department

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        role = current_user.Role
        if role == RoleEnum.Student:
            return redirect(url_for('student.dashboard'))
        elif role == RoleEnum.Staff:
            return redirect(url_for('staff.dashboard'))
        elif role == RoleEnum.Admin:
            return redirect(url_for('admin.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(Email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('auth.index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    departments = Department.query.order_by(Department.Name).all()

    if request.method == 'POST':
        full_name   = request.form.get('full_name', '').strip()
        email       = request.form.get('email', '').strip().lower()
        password    = request.form.get('password', '')
        role_str    = request.form.get('role', 'Student')
        dept_id_raw = request.form.get('department_id', '')

        if User.query.filter_by(Email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html', departments=departments)

        try:
            role = RoleEnum[role_str]
        except KeyError:
            role = RoleEnum.Student

        dept_id = int(dept_id_raw) if dept_id_raw.isdigit() else None

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


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))