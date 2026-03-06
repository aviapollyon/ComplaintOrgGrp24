from app import db
from datetime import datetime


class Attachment(db.Model):
    __tablename__ = 'attachments'

    AttachmentId = db.Column(db.Integer, primary_key=True)

    # One of these two will be set — ticket-level OR update-level attachment
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_attachments_ticket_id'),
        nullable=True      # nullable now — update attachments won't have this
    )
    UpdateId = db.Column(
        db.Integer,
        db.ForeignKey('ticket_updates.UpdateId', name='fk_attachments_update_id'),
        nullable=True      # set when attached to a specific thread reply
    )

    FileName   = db.Column(db.String(255), nullable=False)
    FilePath   = db.Column(db.String(500), nullable=False)
    UploadedAt = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Attachment {self.FileName}>'