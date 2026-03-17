from datetime import datetime

from app import db
from app.models.user import RoleEnum


class PendingRegistration(db.Model):
    __tablename__ = 'pending_registrations'

    PendingId = db.Column(db.Integer, primary_key=True)
    FullName = db.Column(db.String(150), nullable=False)
    Email = db.Column(db.String(150), nullable=False, unique=True, index=True)
    PasswordHash = db.Column(db.String(256), nullable=False)
    Role = db.Column(db.Enum(RoleEnum), nullable=False, default=RoleEnum.Student)
    POPIAConsent = db.Column(db.Boolean, default=True, nullable=False)
    POPIAConsentAt = db.Column(db.DateTime, nullable=True)

    VerificationTokenHash = db.Column(db.String(64), nullable=False, index=True)
    VerificationExpiresAt = db.Column(db.DateTime, nullable=False)
    LastVerificationSentAt = db.Column(db.DateTime, nullable=True)
    ConsumedAt = db.Column(db.DateTime, nullable=True)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    UpdatedAt = db.Column(db.DateTime, default=datetime.utcnow,
                          onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<PendingRegistration {self.Email}>'
