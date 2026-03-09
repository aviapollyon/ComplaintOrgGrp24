from app import db
from datetime import datetime


class Announcement(db.Model):
    __tablename__ = 'announcements'

    AnnouncementId = db.Column(db.Integer, primary_key=True)
    Title          = db.Column(db.String(200), nullable=False)
    Message        = db.Column(db.Text,        nullable=False)
    TargetAudience = db.Column(db.String(20),  nullable=False, default='All')
    IsActive       = db.Column(db.Boolean,     nullable=False, default=True)
    CreatedAt      = db.Column(db.DateTime,    default=datetime.utcnow)
    CreatedBy      = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_announcements_created_by'),
        nullable=False
    )

    creator = db.relationship('User', foreign_keys=[CreatedBy])

    def __repr__(self):
        return f'<Announcement "{self.Title}">'