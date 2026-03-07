from flask_wtf import FlaskForm
from wtforms import TextAreaField, SelectField, SubmitField, StringField
from wtforms.validators import DataRequired, Length, Optional

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
    status = SelectField('New Status', choices=STATUS_CHOICES,
                         validators=[DataRequired()])
    comment = TextAreaField('Comment / Notes',
                            validators=[DataRequired(), Length(min=5, max=2000)],
                            render_kw={"rows": 4,
                                       "placeholder": "Describe the action taken..."})
    submit = SubmitField('Update Ticket')


class ResolveTicketForm(FlaskForm):
    resolution = TextAreaField('Resolution Details',
                               validators=[DataRequired(), Length(min=10, max=3000)],
                               render_kw={"rows": 5,
                                          "placeholder": "Describe how the issue was resolved..."})
    submit = SubmitField('Mark as Resolved')


class ReplyForm(FlaskForm):
    comment = TextAreaField('Message to Student',
                            validators=[DataRequired(), Length(min=5, max=2000)],
                            render_kw={"rows": 4,
                                       "placeholder": "Ask for more information or send a message..."})
    submit = SubmitField('Send Reply')


class StaffThreadReplyForm(FlaskForm):
    comment = TextAreaField('Reply',
                            validators=[DataRequired(), Length(min=2, max=2000)],
                            render_kw={"rows": 2,
                                       "placeholder": "Continue the conversation..."})
    submit = SubmitField('Reply')


class EscalationRequestForm(FlaskForm):
    target_dept = SelectField('Escalate To Department', coerce=int,
                              validators=[DataRequired()])
    reason      = TextAreaField('Reason for Escalation',
                                validators=[DataRequired(), Length(min=10, max=1000)],
                                render_kw={"rows": 4,
                                           "placeholder": "Explain why this ticket needs to be escalated..."})
    submit = SubmitField('Request Escalation')


class StaffTicketFilterForm(FlaskForm):
    class Meta:
        csrf = False

    status   = SelectField('Status',   choices=FILTER_STATUS_CHOICES,   validators=[Optional()])
    priority = SelectField('Priority', choices=FILTER_PRIORITY_CHOICES, validators=[Optional()])
    category = SelectField('Category', choices=FILTER_CATEGORY_CHOICES, validators=[Optional()])
    search   = StringField('Search',   validators=[Optional()],
                           render_kw={"placeholder": "Search title..."})