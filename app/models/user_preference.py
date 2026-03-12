from app import db


class UserPreference(db.Model):
    __tablename__ = 'user_preferences'

    PreferenceId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_user_preferences_user_id'),
        nullable=False,
        unique=True,
        index=True,
    )
    SuppressSocialNotifications = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship('User', foreign_keys=[UserId])

    def __repr__(self):
        return f'<UserPreference User={self.UserId}>'
