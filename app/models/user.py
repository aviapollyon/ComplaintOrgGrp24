from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import enum


class RoleEnum(enum.Enum):
    Student = 'Student'
    Staff   = 'Staff'
    Admin   = 'Admin'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    UserId       = db.Column(db.Integer, primary_key=True)
    FullName     = db.Column(db.String(150), nullable=False)
    Email        = db.Column(db.String(150), unique=True, nullable=False)
    PasswordHash = db.Column(db.String(256), nullable=False)
    Role         = db.Column(db.Enum(RoleEnum), nullable=False, default=RoleEnum.Student)
    IsActive     = db.Column(db.Boolean, default=True, nullable=False)

    DepartmentId = db.Column(
        db.Integer,
        db.ForeignKey('departments.DepartmentId', name='fk_users_department_id'),
        nullable=True
    )

    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submitted_tickets = db.relationship(
        'Ticket', foreign_keys='Ticket.StudentId',
        backref='student', lazy='dynamic'
    )
    assigned_tickets = db.relationship(
        'Ticket', foreign_keys='Ticket.StaffId',
        backref='staff', lazy='dynamic'
    )
    ticket_updates = db.relationship('TicketUpdate', backref='author', lazy='dynamic')

    def get_id(self):
        return str(self.UserId)

    def set_password(self, password):
        self.PasswordHash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.PasswordHash, password)

    # Flask-Login — deactivated users cannot log in
    @property
    def is_active(self):
        return self.IsActive

    def __repr__(self):
        return f'<User {self.Email} [{self.Role.value}]>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))