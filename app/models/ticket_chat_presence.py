from datetime import datetime

from app import db


class TicketChatPresence(db.Model):
    __tablename__ = 'ticket_chat_presence'

    PresenceId = db.Column(db.Integer, primary_key=True)
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_chat_presence_ticket_id'),
        nullable=False,
        index=True,
    )
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_chat_presence_user_id'),
        nullable=False,
        index=True,
    )
    LastSeenAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint('TicketId', 'UserId', name='uq_chat_presence_ticket_user'),
    )

    ticket = db.relationship('Ticket', foreign_keys=[TicketId])
    user = db.relationship('User', foreign_keys=[UserId])

    def __repr__(self):
        return f'<TicketChatPresence ticket={self.TicketId} user={self.UserId}>'
