import enum
from app import db
from datetime import datetime


class StatusEnum(enum.Enum):
    Submitted   = 'Submitted'
    Assigned    = 'Assigned'
    InProgress  = 'In Progress'
    PendingInfo = 'Pending Info'
    Resolved    = 'Resolved'
    Rejected    = 'Rejected'


class PriorityEnum(enum.Enum):
    High   = 'High'
    Medium = 'Medium'
    Low    = 'Low'


class Ticket(db.Model):
    __tablename__ = 'tickets'

    TicketId     = db.Column(db.Integer, primary_key=True)
    StudentId    = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_tickets_student_id'),
        nullable=False
    )
    StaffId      = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_tickets_staff_id'),
        nullable=True
    )
    DepartmentId = db.Column(
        db.Integer,
        db.ForeignKey('departments.DepartmentId', name='fk_tickets_department_id'),
        nullable=True
    )

    Title           = db.Column(db.String(255), nullable=False)
    Description     = db.Column(db.Text,        nullable=False)
    Category        = db.Column(db.String(100), nullable=False)
    SubCategory     = db.Column(db.String(100), nullable=True)
    Priority        = db.Column(db.Enum(PriorityEnum), nullable=False,
                                default=PriorityEnum.Medium)
    Status          = db.Column(db.Enum(StatusEnum), nullable=False,
                                default=StatusEnum.Submitted)
    CreatedAt       = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt       = db.Column(db.DateTime, default=datetime.utcnow,
                                onupdate=datetime.utcnow)
    ResolvedAt      = db.Column(db.DateTime, nullable=True)
    FeedbackRating  = db.Column(db.Integer,  nullable=True)
    FeedbackComment = db.Column(db.Text,     nullable=True)

    # ── Relationships — all use back_populates; NO backref= here ─────────────
    department = db.relationship(
        'Department',
        back_populates='tickets',
        foreign_keys=[DepartmentId]
    )
    student = db.relationship(
        'User',
        back_populates='submitted_tickets',
        foreign_keys=[StudentId]
    )
    staff = db.relationship(
        'User',
        back_populates='assigned_tickets',
        foreign_keys=[StaffId]
    )
    updates = db.relationship(
        'TicketUpdate',
        back_populates='ticket',
        lazy='dynamic',
        foreign_keys='TicketUpdate.TicketId'
    )
    attachments = db.relationship(
        'Attachment',
        back_populates='ticket',
        lazy='dynamic',
        foreign_keys='Attachment.TicketId'
    )

    @property
    def is_editable(self):
        return self.Status == StatusEnum.Submitted

    @property
    def is_withdrawable(self):
        return self.Status not in (StatusEnum.Resolved, StatusEnum.Rejected)

    @property
    def needs_feedback(self):
        return (self.Status == StatusEnum.Resolved
                and self.FeedbackRating is None)

    def __repr__(self):
        return f'<Ticket #{self.TicketId} [{self.Status.value}]>'