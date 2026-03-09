from app import db
from datetime import datetime


class Attachment(db.Model):
    __tablename__ = 'attachments'

    AttachmentId = db.Column(db.Integer, primary_key=True)
    TicketId     = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_attachments_ticket_id'),
        nullable=True
    )
    UpdateId     = db.Column(
        db.Integer,
        db.ForeignKey('ticket_updates.UpdateId', name='fk_attachments_update_id'),
        nullable=True
    )
    FileName     = db.Column(db.String(255), nullable=False)
    FilePath     = db.Column(db.String(500), nullable=False)
    UploadedAt   = db.Column(db.DateTime,    default=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    ticket = db.relationship(
        'Ticket',
        back_populates='attachments',
        foreign_keys=[TicketId]
    )
    update = db.relationship(
        'TicketUpdate',
        foreign_keys=[UpdateId],
        backref=db.backref('attachments', lazy='dynamic')
        # TicketUpdate does not define 'attachments' itself so backref is safe here
    )

    def __repr__(self):
        return f'<Attachment {self.FileName}>'