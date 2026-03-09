from app import db
from datetime import datetime


class EscalationRequest(db.Model):
    __tablename__ = 'escalation_requests'

    EscalationId  = db.Column(db.Integer, primary_key=True)
    TicketId      = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_escalation_ticket_id'),
        nullable=False
    )
    RequestedById = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_escalation_requested_by'),
        nullable=False
    )
    TargetDeptId  = db.Column(
        db.Integer,
        db.ForeignKey('departments.DepartmentId', name='fk_escalation_dept_id'),
        nullable=False
    )
    Reason     = db.Column(db.Text,      nullable=False)
    Status     = db.Column(db.String(20), nullable=False, default='Pending')
    CreatedAt  = db.Column(db.DateTime,  default=datetime.utcnow)
    ResolvedAt = db.Column(db.DateTime,  nullable=True)

    # safe — none of these models define back_populates for these names
    ticket       = db.relationship('Ticket',     foreign_keys=[TicketId],
                                   backref=db.backref('escalations', lazy='dynamic'))
    requested_by = db.relationship('User',       foreign_keys=[RequestedById],
                                   backref=db.backref('sent_escalations', lazy='dynamic'))
    target_dept  = db.relationship('Department', foreign_keys=[TargetDeptId],
                                   backref=db.backref('escalation_targets', lazy='dynamic'))

    def __repr__(self):
        return f'<EscalationRequest ticket={self.TicketId} status={self.Status}>'