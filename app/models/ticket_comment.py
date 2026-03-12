from datetime import datetime
from app import db


class TicketComment(db.Model):
    __tablename__ = 'ticket_comments'

    CommentId = db.Column(db.Integer, primary_key=True)
    TicketId = db.Column(
        db.Integer,
        db.ForeignKey('tickets.TicketId', name='fk_ticket_comments_ticket_id'),
        nullable=False,
        index=True,
    )
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_ticket_comments_user_id'),
        nullable=False,
        index=True,
    )
    Content = db.Column(db.Text, nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[UserId])
    ticket = db.relationship('Ticket', foreign_keys=[TicketId], back_populates='ticket_comments')
    comment_votes = db.relationship(
        'CommentVote',
        back_populates='comment',
        lazy='dynamic',
        foreign_keys='CommentVote.CommentId',
        cascade='all, delete-orphan',
    )

    @property
    def upvote_count(self):
        return self.comment_votes.count()

    def __repr__(self):
        return f'<TicketComment #{self.CommentId} Ticket={self.TicketId}>'
