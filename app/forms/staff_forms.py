from flask_wtf import FlaskForm
from wtforms import TextAreaField, SelectField, SubmitField, StringField
from wtforms.validators import DataRequired, Length, Optional
from app.utils.helpers import TICKET_CATEGORIES, CATEGORY_SUBCATEGORY_MAP

_all_subs = sorted({s for subs in CATEGORY_SUBCATEGORY_MAP.values() for s in subs})
SUBCATEGORY_FILTER_CHOICES = [('', 'All Sub-Categories')] + [(s, s) for s in _all_subs]

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

SORT_CHOICES = [
    ('newest',      'Newest First'),
    ('oldest',      'Oldest First'),
    ('priority',    'Priority (High → Low)'),
    ('subcategory', 'Sub-Category (A–Z)'),
    ('title',       'Title (A–Z)'),
    ('id_asc',      'Ticket # ↑'),
    ('id_desc',     'Ticket # ↓'),
]


class UpdateTicketForm(FlaskForm):
    status  = SelectField('New Status', choices=STATUS_CHOICES,
                          validators=[DataRequired()])
    comment = TextAreaField('Comment / Notes',
                            validators=[DataRequired(), Length(min=5, max=2000)],
                            render_kw={"rows": 4,
                                       "placeholder": "Describe the action taken..."})
    submit  = SubmitField('Update Ticket')


class UpdatePriorityForm(FlaskForm):
    priority = SelectField(
        'Priority',
        choices=[('High', 'High'), ('Medium', 'Medium'), ('Low', 'Low')],
        validators=[DataRequired()]
    )
    reason = TextAreaField(
        'Reason for Priority Change',
        validators=[DataRequired(), Length(min=5, max=500)],
        render_kw={"rows": 3, "placeholder": "Why this priority level was selected..."}
    )
    submit = SubmitField('Update Priority')


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
                                render_kw={"rows": 4})
    submit = SubmitField('Request Escalation')


class StaffReassignmentRequestForm(FlaskForm):
    target_staff = SelectField('Reassign To', coerce=int,
                               validators=[DataRequired()])
    reason       = TextAreaField('Reason for Reassignment',
                                 validators=[DataRequired(), Length(min=10, max=1000)],
                                 render_kw={"rows": 3})
    submit = SubmitField('Request Reassignment')


class StaffTicketFilterForm(FlaskForm):
    class Meta:
        csrf = False
    status       = SelectField('Status',       choices=FILTER_STATUS_CHOICES,   validators=[Optional()])
    priority     = SelectField('Priority',     choices=FILTER_PRIORITY_CHOICES, validators=[Optional()])
    category     = SelectField(
        'Category',
        choices=[('', 'All Categories')] + [(c, c) for c in TICKET_CATEGORIES],
        validators=[Optional()]
    )
    sub_category = SelectField(
        'Sub-Category',
        choices=SUBCATEGORY_FILTER_CHOICES,
        validators=[Optional()]
    )
    search       = StringField('Search', validators=[Optional()],
                               render_kw={"placeholder": "Search title or ref..."})
    sort         = SelectField('Sort By', choices=SORT_CHOICES, validators=[Optional()])
    per_page     = SelectField('Per Page',
                               choices=[('10','10'),('15','15'),('25','25'),('50','50'),('100','100')],
                               default='15', validators=[Optional()])