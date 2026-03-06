from flask_wtf import FlaskForm
from wtforms import TextAreaField, SelectField, SubmitField, StringField
from wtforms.validators import DataRequired, Length, Optional

# Resolved removed  — use dedicated Resolve panel
# Pending Info removed — auto-set when staff uses Reply to Student panel
STATUS_CHOICES = [
    ('In Progress', 'In Progress'),
    ('Rejected',    'Rejected'),
]

FILTER_STATUS_CHOICES = [
    ('', 'All Statuses'),
    ('Assigned',     'Assigned'),
    ('In Progress',  'In Progress'),
    ('Pending Info', 'Pending Info'),
    ('Resolved',     'Resolved'),
    ('Rejected',     'Rejected'),
]

FILTER_PRIORITY_CHOICES = [
    ('', 'All Priorities'),
    ('High',   'High'),
    ('Medium', 'Medium'),
    ('Low',    'Low'),
]

FILTER_CATEGORY_CHOICES = [
    ('', 'All Categories'),
    ('Academic',       'Academic'),
    ('Financial',      'Financial'),
    ('Facilities',     'Facilities'),
    ('IT Support',     'IT Support'),
    ('Accommodation',  'Accommodation'),
    ('Administration', 'Administration'),
    ('Other',          'Other'),
]


class UpdateTicketForm(FlaskForm):
    status = SelectField(
        'New Status',
        choices=STATUS_CHOICES,
        validators=[DataRequired()]
    )
    comment = TextAreaField(
        'Comment / Notes',
        validators=[DataRequired(), Length(min=5, max=2000)],
        render_kw={
            "rows": 4,
            "placeholder": "Describe the action taken..."
        }
    )
    submit = SubmitField('Update Ticket')


class ResolveTicketForm(FlaskForm):
    resolution = TextAreaField(
        'Resolution Details',
        validators=[DataRequired(), Length(min=10, max=3000)],
        render_kw={
            "rows": 5,
            "placeholder": "Describe how the issue was resolved..."
        }
    )
    submit = SubmitField('Mark as Resolved')


class ReplyForm(FlaskForm):
    """
    Staff reply to student.
    Posting this automatically sets ticket status to Pending Info.
    """
    comment = TextAreaField(
        'Message to Student',
        validators=[DataRequired(), Length(min=5, max=2000)],
        render_kw={
            "rows": 4,
            "placeholder": "Ask for more information or send a message..."
        }
    )
    submit = SubmitField('Send Reply')


class StaffThreadReplyForm(FlaskForm):
    """
    Staff reply inside an existing reply thread (their own or student's reply).
    No status change.
    """
    comment = TextAreaField(
        'Reply',
        validators=[DataRequired(), Length(min=2, max=2000)],
        render_kw={"rows": 2, "placeholder": "Continue the conversation..."}
    )
    submit = SubmitField('Reply')


class StaffTicketFilterForm(FlaskForm):
    class Meta:
        csrf = False

    status   = SelectField('Status',   choices=FILTER_STATUS_CHOICES,   validators=[Optional()])
    priority = SelectField('Priority', choices=FILTER_PRIORITY_CHOICES, validators=[Optional()])
    category = SelectField('Category', choices=FILTER_CATEGORY_CHOICES, validators=[Optional()])
    search   = StringField('Search',   validators=[Optional()],
                           render_kw={"placeholder": "Search title..."})