from app import db
from datetime import datetime


class Department(db.Model):
    __tablename__ = 'departments'

    DepartmentId  = db.Column(db.Integer, primary_key=True)
    Name          = db.Column(db.String(120), unique=True, nullable=False)
    Description   = db.Column(db.String(300), nullable=True)
    CreatedAt     = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    users   = db.relationship('User',   backref='department', lazy='dynamic')
    tickets = db.relationship('Ticket', backref='department', lazy='dynamic')

    def __repr__(self):
        return f'<Department {self.Name}>'