from datetime import datetime
from app import db


class TicketVote(db.Model):
    __tablename__ = 'ticket_votes'
    __table_args__ = (
        db.UniqueConstraint('TicketId', 'UserId', name='uq_ticket_vote_user_ticket'),
    )

    VoteId = db.Column(db.Integer, primary_key=True)
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_ticket_votes_ticket_id'),
        nullable=False,
        index=True,
    )
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_ticket_votes_user_id'),
        nullable=False,
        index=True,
    )
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[UserId])
    ticket = db.relationship('Ticket', foreign_keys=[TicketId], back_populates='ticket_votes')

    def __repr__(self):
        return f'<TicketVote Ticket={self.TicketId} User={self.UserId}>'
