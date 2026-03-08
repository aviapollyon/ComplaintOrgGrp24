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
    # Detect if user session is already authenticated via Flask-Login
    if current_user.is_authenticated:
        # Determine the user's explicit Role Enum property
        role = current_user.Role
        
        # Dispatch user correctly directly to their respective landing dashboards based on role
        if role == RoleEnum.Student:
            return redirect(url_for('student.dashboard'))  # Redirect standard submitters
        elif role == RoleEnum.Staff:
            return redirect(url_for('staff.dashboard'))    # Redirect resolvers
        elif role == RoleEnum.Admin:
            return redirect(url_for('admin.dashboard'))    # Redirect administrators
            
    # Default case when no session exists: Fallback directly to login screen
    return redirect(url_for('auth.login'))  


# Login route: handles GET (show form) and POST (process login)
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Eject already authenticated/signed-in users by pointing them back to the logic mapping above
    if current_user.is_authenticated:
        return redirect(url_for('auth.index')) 

    # Processing authentication attempt form payload
    if request.method == 'POST':
        # Retrieve credentials passed over in the form scope parameters
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        # Execute query looking for an identically-matching email on record 
        user     = User.query.filter_by(Email=email).first()

        # Check if the DB pulled up a user AND if their explicit hashed password check passes
        if user and user.check_password(password):
            # Terminate active attempts for accounts which have been revoked/disabled manually by Admin
            if not user.IsActive:
                flash(
                    'Your account has been deactivated. '
                    'Please contact the administrator for assistance.',
                    'danger'
                )
                # Redisplay the login page with the danger flash above
                return render_template('auth/login.html')

            # Issue Flask-Login persistent credential cookies/header state mappings 
            login_user(user)
            flash('Logged in successfully.', 'success')
            
            # Send the authenticated person toward the dashboard distributor 
            return redirect(url_for('auth.index'))
        else:
            # Mask whether identifying the correct email failed or if the password was failed. Provide generic output. 
            flash('Invalid email or password.', 'danger')

    # Base state for rendering form on regular page navigations
    return render_template('auth/login.html')


# Registration route: handles GET (show form) and POST (process registration)
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Produce the active department directory layout list for population into registration UI dropdowns
    departments = Department.query.order_by(Department.Name).all()

    # Intercept new account building action requests 
    if request.method == 'POST':
        # Map raw data fields captured directly from the HTTP POST form structure
        full_name   = request.form.get('full_name', '').strip()
        email       = request.form.get('email', '').strip().lower()
        password    = request.form.get('password', '')
        role_str    = request.form.get('role', 'Student')
        dept_id_raw = request.form.get('department_id', '')

        # Collision query mapping check ensuring no duplicate emails enter the system
        if User.query.filter_by(Email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html', departments=departments)

        # Enforce valid mapping values into specific system Enums. Defaults to Student if hacked/broken input happens.
        try:
            role = RoleEnum[role_str]
        except KeyError:
            role = RoleEnum.Student

        # Transform string ID component of Department into exact numeric integer index, otherwise None/null map.
        dept_id = int(dept_id_raw) if dept_id_raw.isdigit() else None

        # Instantiate fresh user Object tracking directly aligning column mapping assignments
        user = User(
            FullName     = full_name,
            Email        = email,
            Role         = role,
            DepartmentId = dept_id,
        )
        
        # Invoke User Model functionality that permanently encrypts passwords behind werkzeug_security hashes   
        user.set_password(password)
        
        # Enter changes to the SQL Alchemy staging tracking layer + hard-commit SQL queries directly to DB file
        db.session.add(user)
        db.session.commit()

        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    # Deliver view-state render configuration for users navigating into the web portal registration area
    return render_template('auth/register.html', departments=departments)


# Logout route: logs out the current user
@auth_bp.route('/logout')
@login_required
def logout():
    # Invoke native library tool which erases login persistence sessions correctly securely
    logout_user()
    flash('You have been logged out.', 'info')
    
    # Dump back onto main authentication login access landing screen
    return redirect(url_for('auth.login'))