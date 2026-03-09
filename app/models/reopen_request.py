from app import db
from datetime import datetime


class ReopenRequest(db.Model):
    __tablename__ = 'reopen_requests'

    RequestId  = db.Column(db.Integer, primary_key=True)
    TicketId   = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_reopen_ticket'),
        nullable=False
    )
    StudentId  = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_reopen_student'),
        nullable=False
    )
    Reason     = db.Column(db.Text,      nullable=False)
    Status     = db.Column(db.String(20), nullable=False, default='Pending')
    CreatedAt  = db.Column(db.DateTime,  default=datetime.utcnow)
    ResolvedAt = db.Column(db.DateTime,  nullable=True)

    ticket  = db.relationship('Ticket', foreign_keys=[TicketId],
                               backref=db.backref('reopen_requests', lazy='dynamic'))
    student = db.relationship('User',   foreign_keys=[StudentId],
                               backref=db.backref('reopen_requests', lazy='dynamic'))

    def __repr__(self):
        return f'<ReopenRequest ticket={self.TicketId} status={self.Status}>'