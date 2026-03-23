from datetime import datetime

from app import db


class TicketChatAttachment(db.Model):
    __tablename__ = 'ticket_chat_attachments'

    ChatAttachmentId = db.Column(db.Integer, primary_key=True)
    ChatMessageId = db.Column(
        db.Integer,
        db.ForeignKey('ticket_chat_messages.ChatMessageId', name='fk_chat_attachments_message_id'),
        nullable=False,
        index=True,
    )
    FileName = db.Column(db.String(255), nullable=False)
    FilePath = db.Column(db.String(500), nullable=False)
    UploadedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    message = db.relationship(
        'TicketChatMessage',
        foreign_keys=[ChatMessageId],
        backref=db.backref('attachments', lazy='dynamic'),
    )

    def __repr__(self):
        return f'<TicketChatAttachment {self.FileName}>'
