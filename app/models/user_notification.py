from app import db
from datetime import datetime


class UserNotification(db.Model):
    __tablename__ = 'user_notifications'

    NotificationId = db.Column(db.Integer, primary_key=True)
    UserId         = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_user_notif_user_id'),
        nullable=False
    )
    Title    = db.Column(db.String(200), nullable=False)
    Message  = db.Column(db.String(500), nullable=False)
    # 'ticket_assigned' | 'status_update' | 'new_reply' | 'reply_received'
    # 'ticket_resolved' | 'ticket_rejected' | 'ticket_reopened' | 'escalation'
    Type     = db.Column(db.String(50),  nullable=False, default='general')
    IsRead   = db.Column(db.Boolean,     nullable=False, default=False)
    CreatedAt = db.Column(db.DateTime,   default=datetime.utcnow)

    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_user_notif_ticket_id'),
        nullable=True
    )

    user   = db.relationship('User',   backref='notifications',        foreign_keys=[UserId])
    ticket = db.relationship('Ticket', backref='user_notifications',   foreign_keys=[TicketId])

    def __repr__(self):
        return f'<UserNotification {self.Type} → User {self.UserId}>'