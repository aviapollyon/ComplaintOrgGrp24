from app import db


class Department(db.Model):
    __tablename__ = 'departments'

    DepartmentId = db.Column(db.Integer, primary_key=True)
    Name         = db.Column(db.String(120), nullable=False, unique=True)
    Description  = db.Column(db.Text, nullable=True)

    tickets = db.relationship(
        'Ticket',
        back_populates='department',
        foreign_keys='Ticket.DepartmentId'
    )

    def __repr__(self):
        return f'<Department {self.Name}>'