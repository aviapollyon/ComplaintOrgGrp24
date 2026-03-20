from datetime import datetime
from app import db


class CommentAttachment(db.Model):
    __tablename__ = 'comment_attachments'

    AttachmentId = db.Column(db.Integer, primary_key=True)
    CommentId = db.Column(
        db.Integer,
        db.ForeignKey('ticket_comments.CommentId', name='fk_comment_attachments_comment_id'),
        nullable=False,
        index=True,
    )
    FileName = db.Column(db.String(255), nullable=False)
    FilePath = db.Column(db.String(500), nullable=False)
    UploadedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    comment = db.relationship('TicketComment', back_populates='attachments')

    def __repr__(self):
        return f'<CommentAttachment {self.FileName}>'
