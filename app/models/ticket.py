import enum
from app import db
from datetime import datetime, timedelta
import uuid


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
    TrackingRef     = db.Column(db.String(20),  nullable=True, unique=True, index=True)
    Priority        = db.Column(db.Enum(PriorityEnum), nullable=True)
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
    ticket_votes = db.relationship(
        'TicketVote',
        back_populates='ticket',
        lazy='dynamic',
        foreign_keys='TicketVote.TicketId',
        cascade='all, delete-orphan',
    )
    ticket_comments = db.relationship(
        'TicketComment',
        back_populates='ticket',
        lazy='dynamic',
        foreign_keys='TicketComment.TicketId',
        cascade='all, delete-orphan',
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

    @property
    def vote_count(self):
        return self.ticket_votes.count()

    @property
    def comment_count(self):
        return self.ticket_comments.count()

    @property
    def first_response_due_at(self):
        return (self.CreatedAt or datetime.utcnow()) + timedelta(hours=24)

    @property
    def resolution_due_at(self):
        return (self.CreatedAt or datetime.utcnow()) + timedelta(hours=48)

    @property
    def has_staff_response(self):
        from app.models.user import RoleEnum
        for update in self.updates.all():
            if update.author and update.author.Role == RoleEnum.Staff:
                return True
        return False

    @property
    def is_response_sla_overdue(self):
        if self.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
            return False
        if self.has_staff_response:
            return False
        return datetime.utcnow() > self.first_response_due_at

    @property
    def is_resolution_sla_overdue(self):
        if self.Status in (StatusEnum.Resolved, StatusEnum.Rejected):
            return False
        return datetime.utcnow() > self.resolution_due_at

    def __repr__(self):
        return f'<Ticket #{self.TicketId} [{self.Status.value}]>'

    @staticmethod
    def generate_tracking_ref(ticket_id: int) -> str:
        """Returns a human-readable tracking ref like GRV-202603-00001234."""
        now = datetime.utcnow()
        return f"GRV-{now.strftime('%Y%m')}-{ticket_id:08d}"