from app import db
from datetime import datetime


class Announcement(db.Model):
    __tablename__ = 'announcements'

    AnnouncementId = db.Column(db.Integer, primary_key=True)
    Title          = db.Column(db.String(200), nullable=False)
    Message        = db.Column(db.Text, nullable=False)

    # 'All', 'Student', 'Staff'
    TargetAudience = db.Column(db.String(20), nullable=False, default='All')

    CreatedBy  = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_announcements_created_by'),
        nullable=False
    )
    CreatedAt  = db.Column(db.DateTime, default=datetime.utcnow)
    IsActive   = db.Column(db.Boolean, default=True, nullable=False)

    author = db.relationship('User', backref='announcements', foreign_keys=[CreatedBy])

    def __repr__(self):
        return f'<Announcement {self.AnnouncementId} [{self.TargetAudience}]>'