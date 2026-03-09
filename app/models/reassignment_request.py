from app import db
from datetime import datetime


class ReassignmentRequest(db.Model):
    __tablename__ = 'reassignment_requests'

    RequestId     = db.Column(db.Integer, primary_key=True)
    TicketId      = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_reassign_req_ticket'),
        nullable=False
    )
    RequestedById = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_reassign_req_by'),
        nullable=False
    )
    TargetStaffId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_reassign_req_target'),
        nullable=False
    )
    Reason     = db.Column(db.Text,      nullable=False)
    Status     = db.Column(db.String(20), nullable=False, default='Pending')
    CreatedAt  = db.Column(db.DateTime,  default=datetime.utcnow)
    ResolvedAt = db.Column(db.DateTime,  nullable=True)

    ticket       = db.relationship('Ticket', foreign_keys=[TicketId],
                                   backref=db.backref('reassignment_requests', lazy='dynamic'))
    requested_by = db.relationship('User',   foreign_keys=[RequestedById],
                                   backref=db.backref('sent_reassignment_requests', lazy='dynamic'))
    target_staff = db.relationship('User',   foreign_keys=[TargetStaffId],
                                   backref=db.backref('received_reassignment_requests', lazy='dynamic'))

    def __repr__(self):
        return f'<ReassignmentRequest ticket={self.TicketId} status={self.Status}>'