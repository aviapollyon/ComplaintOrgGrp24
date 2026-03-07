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
    # 'Pending' | 'Approved' | 'Rejected'

    CreatedAt  = db.Column(db.DateTime, default=datetime.utcnow)
    ResolvedAt = db.Column(db.DateTime, nullable=True)

    ticket       = db.relationship('Ticket',      backref='escalations',    foreign_keys=[TicketId])
    requested_by = db.relationship('User',        backref='escalations',    foreign_keys=[RequestedById])
    target_dept  = db.relationship('Department',  backref='escalations',    foreign_keys=[TargetDeptId])

    def __repr__(self):
        return f'<Escalation ticket={self.TicketId} status={self.Status}>'