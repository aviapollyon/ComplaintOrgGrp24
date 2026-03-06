from app import db
from datetime import datetime
import enum


class PriorityEnum(enum.Enum):
    Low    = 'Low'
    Medium = 'Medium'
    High   = 'High'


class StatusEnum(enum.Enum):
    Submitted   = 'Submitted'
    Assigned    = 'Assigned'
    InProgress  = 'In Progress'
    PendingInfo = 'Pending Info'
    Resolved    = 'Resolved'
    Rejected    = 'Rejected'


class Ticket(db.Model):
    __tablename__ = 'tickets'

    TicketId    = db.Column(db.Integer, primary_key=True)
    Title       = db.Column(db.String(255), nullable=False)
    Description = db.Column(db.Text, nullable=False)
    Category    = db.Column(db.String(100), nullable=False)
    Priority    = db.Column(db.Enum(PriorityEnum), nullable=False, default=PriorityEnum.Medium)
    Status      = db.Column(db.Enum(StatusEnum),   nullable=False, default=StatusEnum.Submitted)

    StudentId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_tickets_student_id'),
        nullable=False
    )
    StaffId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_tickets_staff_id'),
        nullable=True
    )
    DepartmentId = db.Column(
        db.Integer,
        db.ForeignKey('departments.DepartmentId', name='fk_tickets_department_id'),
        nullable=True
    )

    CreatedAt  = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ResolvedAt = db.Column(db.DateTime, nullable=True)

    FeedbackRating  = db.Column(db.Integer, nullable=True)
    FeedbackComment = db.Column(db.Text,    nullable=True)
    FeedbackAt      = db.Column(db.DateTime, nullable=True)

    updates     = db.relationship(
        'TicketUpdate', backref='ticket', lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='TicketUpdate.TicketId'
    )
    attachments = db.relationship(
        'Attachment', backref='ticket', lazy='dynamic',
        cascade='all, delete-orphan',
        foreign_keys='Attachment.TicketId'
    )

    @property
    def is_editable(self):
        return self.Status == StatusEnum.Submitted

    @property
    def is_withdrawable(self):
        return self.Status in (
            StatusEnum.Submitted, StatusEnum.Assigned,
            StatusEnum.InProgress, StatusEnum.PendingInfo
        )

    @property
    def needs_feedback(self):
        return self.Status == StatusEnum.Resolved and self.FeedbackRating is None

    def __repr__(self):
        return f'<Ticket #{self.TicketId} [{self.Status.value}]>'