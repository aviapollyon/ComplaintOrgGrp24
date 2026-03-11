from app import db
from datetime import datetime


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    LogId      = db.Column(db.Integer, primary_key=True)
    ActorId    = db.Column(db.Integer,
                           db.ForeignKey('users.UserId', name='fk_audit_log_actor'),
                           nullable=True)
    Action     = db.Column(db.String(100), nullable=False)
    TargetType = db.Column(db.String(50),  nullable=True)
    TargetId   = db.Column(db.Integer,     nullable=True)
    Details    = db.Column(db.Text,        nullable=True)
    IPAddress  = db.Column(db.String(45),  nullable=True)
    CreatedAt  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    actor = db.relationship('User', foreign_keys=[ActorId], lazy='joined')

    def __repr__(self):
        return f'<AuditLog {self.Action} by actor={self.ActorId}>'
