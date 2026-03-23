from datetime import datetime

from app import db


class TicketChatMessage(db.Model):
    __tablename__ = 'ticket_chat_messages'

    ChatMessageId = db.Column(db.Integer, primary_key=True)
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_chat_messages_ticket_id'),
        nullable=False,
        index=True,
    )
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_chat_messages_user_id'),
        nullable=False,
        index=True,
    )
    Message = db.Column(db.Text, nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    ticket = db.relationship(
        'Ticket',
        foreign_keys=[TicketId],
        backref=db.backref('chat_messages', lazy='dynamic'),
    )
    author = db.relationship(
        'User',
        foreign_keys=[UserId],
    )

    def __repr__(self):
        return f'<TicketChatMessage #{self.ChatMessageId} ticket={self.TicketId}>'
