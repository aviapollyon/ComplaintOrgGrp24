from app import db
from datetime import datetime


class TicketFlag(db.Model):
    __tablename__ = 'ticket_flags'

    FlagId      = db.Column(db.Integer,  primary_key=True)
    Category    = db.Column(db.String(100), nullable=False)
    Keyword     = db.Column(db.String(100), nullable=False)
    TicketCount = db.Column(db.Integer,     nullable=False, default=0)
    Status      = db.Column(db.String(20),  nullable=False, default='active')
    CreatedAt   = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt   = db.Column(db.DateTime, default=datetime.utcnow,
                             onupdate=datetime.utcnow)

    flagged_tickets = db.relationship(
        'FlaggedTicket',
        backref='flag',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<TicketFlag {self.Category}/{self.Keyword} count={self.TicketCount}>'


class FlaggedTicket(db.Model):
    __tablename__ = 'flagged_tickets'

    Id       = db.Column(db.Integer, primary_key=True)
    FlagId   = db.Column(
        db.Integer,
        db.ForeignKey('ticket_flags.FlagId', name='fk_flagged_flag_id'),
        nullable=False
    )
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_flagged_ticket_id'),
        nullable=False
    )

    ticket = db.relationship('Ticket', foreign_keys=[TicketId])