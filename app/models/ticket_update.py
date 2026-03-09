import enum
from app import db
from datetime import datetime


class UpdateStatusEnum(enum.Enum):
    Submitted   = 'Submitted'
    Assigned    = 'Assigned'
    InProgress  = 'In Progress'
    PendingInfo = 'Pending Info'
    Resolved    = 'Resolved'
    Rejected    = 'Rejected'


class TicketUpdate(db.Model):
    __tablename__ = 'ticket_updates'

    UpdateId       = db.Column(db.Integer, primary_key=True)
    TicketId       = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_updates_ticket_id'),
        nullable=False
    )
    UserId         = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_updates_user_id'),
        nullable=False
    )
    ParentUpdateId = db.Column(
        db.Integer,
        db.ForeignKey('ticket_updates.UpdateId', name='fk_updates_parent_id'),
        nullable=True
    )
    Comment       = db.Column(db.Text,    nullable=False)
    StatusChange  = db.Column(db.Enum(UpdateStatusEnum), nullable=True)
    IsReplyThread = db.Column(db.Boolean, nullable=False, default=False)
    CreatedAt     = db.Column(db.DateTime, default=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    ticket = db.relationship(
        'Ticket',
        back_populates='updates',
        foreign_keys=[TicketId]
    )
    author = db.relationship(
        'User',
        foreign_keys=[UserId]
    )
    replies = db.relationship(
        'TicketUpdate',
        foreign_keys=[ParentUpdateId],
        lazy='dynamic'
    )

    def __repr__(self):
        return f'<TicketUpdate #{self.UpdateId} ticket={self.TicketId}>'