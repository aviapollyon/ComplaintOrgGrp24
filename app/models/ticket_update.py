from app import db
from datetime import datetime
import enum


class UpdateStatusEnum(enum.Enum):
    Submitted   = 'Submitted'
    Assigned    = 'Assigned'
    InProgress  = 'In Progress'
    PendingInfo = 'Pending Info'
    Resolved    = 'Resolved'
    Rejected    = 'Rejected'


class TicketUpdate(db.Model):
    __tablename__ = 'ticket_updates'

    UpdateId = db.Column(db.Integer, primary_key=True)
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_ticket_updates_ticket_id'),
        nullable=False
    )
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_ticket_updates_user_id'),
        nullable=False
    )

    Comment      = db.Column(db.Text, nullable=False)
    StatusChange = db.Column(db.Enum(UpdateStatusEnum), nullable=True)
    CreatedAt    = db.Column(db.DateTime, default=datetime.utcnow)

    # True only for comments posted via the "Reply to Student" panel.
    # These are the ONLY comments that get a reply thread box.
    IsReplyThread = db.Column(db.Boolean, default=False, nullable=False)

    # Allows updates to be linked together in a parent-child relationship
    ParentUpdateId = db.Column(
        db.Integer,
        db.ForeignKey('ticket_updates.UpdateId', name='fk_ticket_updates_parent_id'),
        nullable=True
    )

    replies = db.relationship(
        'TicketUpdate',
        backref=db.backref('parent', remote_side='[TicketUpdate.UpdateId]'),
        lazy='dynamic',
        foreign_keys='[TicketUpdate.ParentUpdateId]',
        order_by='TicketUpdate.CreatedAt.asc()'
    )
    attachments = db.relationship(
        'Attachment',
        backref='update',
        lazy='dynamic',
        foreign_keys='[Attachment.UpdateId]',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<TicketUpdate #{self.UpdateId} on Ticket #{self.TicketId}>'