from app import db
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
    Email        = db.Column(db.String(150), nullable=False, unique=True)
    PasswordHash = db.Column(db.String(256), nullable=False)
    Role         = db.Column(db.Enum(RoleEnum), nullable=False,
                             default=RoleEnum.Student)
    DepartmentId = db.Column(
        db.Integer,
        db.ForeignKey('departments.DepartmentId', name='fk_users_department_id'),
        nullable=True
    )
    IsActive  = db.Column(db.Boolean, default=True,  nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt = db.Column(db.DateTime, default=datetime.utcnow,
                          onupdate=datetime.utcnow)
    POPIAConsent   = db.Column(db.Boolean, default=False, nullable=False)
    POPIAConsentAt = db.Column(db.DateTime, nullable=True)

    # ── Relationships — all back_populates; NO backref= ───────────────────────
    submitted_tickets = db.relationship(
        'Ticket',
        back_populates='student',
        foreign_keys='Ticket.StudentId',
        lazy='dynamic'
    )
    assigned_tickets = db.relationship(
        'Ticket',
        back_populates='staff',
        foreign_keys='Ticket.StaffId',
        lazy='dynamic'
    )
    department = db.relationship(
        'Department',
        foreign_keys=[DepartmentId]
    )

    def get_id(self):
        return str(self.UserId)

    def set_password(self, password: str):
        self.PasswordHash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.PasswordHash, password)

    def __repr__(self):
        return f'<User {self.Email} [{self.Role.value}]>'