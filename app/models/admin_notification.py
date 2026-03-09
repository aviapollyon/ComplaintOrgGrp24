from app import db
from datetime import datetime


class AdminNotification(db.Model):
    __tablename__ = 'admin_notifications'

    NotificationId = db.Column(db.Integer, primary_key=True)
    Type           = db.Column(db.String(50),  nullable=False)
    Message        = db.Column(db.String(500), nullable=False)
    IsRead         = db.Column(db.Boolean,     default=False, nullable=False)
    CreatedAt      = db.Column(db.DateTime,    default=datetime.utcnow)
    TicketId       = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_admin_notifications_ticket_id'),
        nullable=True
    )

    # safe — Ticket does not define a 'notifications' back_populates
    ticket = db.relationship(
        'Ticket',
        foreign_keys=[TicketId],
        backref=db.backref('admin_notifications', lazy='dynamic')
    )

    def __repr__(self):
        return f'<AdminNotification {self.Type} ticket={self.TicketId}>'