from datetime import datetime

from app import db


class StaffMacro(db.Model):
    __tablename__ = 'staff_macros'

    MacroId = db.Column(db.Integer, primary_key=True)
    UserId = db.Column(
        db.Integer,
        db.ForeignKey('users.UserId', name='fk_staff_macros_user_id'),
        nullable=False,
        index=True,
    )
    Name = db.Column(db.String(120), nullable=False, index=True)
    MacroType = db.Column(db.String(80), nullable=False, index=True)
    Content = db.Column(db.Text, nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    UpdatedAt = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = db.relationship('User', foreign_keys=[UserId])

    def __repr__(self):
        return f'<StaffMacro {self.Name}>'
