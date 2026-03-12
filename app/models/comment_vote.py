from datetime import datetime
from app import db


class CommentVote(db.Model):
    __tablename__ = 'comment_votes'
    __table_args__ = (
        db.UniqueConstraint('CommentId', 'UserId', name='uq_comment_vote_user_comment'),
    )

    VoteId = db.Column(db.Integer, primary_key=True)
    CommentId = db.Column(
        db.Integer,
        db.ForeignKey('ticket_comments.CommentId', name='fk_comment_votes_comment_id'),
        nullable=False,
        index=True,
    )
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_comment_votes_user_id'),
        nullable=False,
        index=True,
    )
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[UserId])
    comment = db.relationship('TicketComment', foreign_keys=[CommentId], back_populates='comment_votes')

    def __repr__(self):
        return f'<CommentVote Comment={self.CommentId} User={self.UserId}>'
