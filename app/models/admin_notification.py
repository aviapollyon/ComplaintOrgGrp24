from app import db
from datetime import datetime


class AdminNotification(db.Model):
    __tablename__ = 'admin_notifications'

    NotificationId = db.Column(db.Integer, primary_key=True)

    # 'unassigned_ticket' | 'escalation_request'
    Type           = db.Column(db.String(50),  nullable=False)
    Message        = db.Column(db.String(500), nullable=False)
    IsRead         = db.Column(db.Boolean,     default=False, nullable=False)
    CreatedAt      = db.Column(db.DateTime,    default=datetime.utcnow)

    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_admin_notifications_ticket_id'),
        nullable=True
    )
    ticket = db.relationship('Ticket', backref='notifications', foreign_keys=[TicketId])

    def __repr__(self):
        return f'<AdminNotification {self.Type} ticket={self.TicketId}>'