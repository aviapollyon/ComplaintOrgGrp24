from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (
    StringField, TextAreaField, SelectField,
    SubmitField, IntegerField, MultipleFileField
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

CATEGORIES = [
    ('Academic',       'Academic'),
    ('Financial',      'Financial'),
    ('Facilities',     'Facilities'),
    ('IT Support',     'IT Support'),
    ('Accommodation',  'Accommodation'),
    ('Administration', 'Administration'),
    ('Other',          'Other'),
]

STATUS_FILTER_CHOICES = [
    ('', 'All Statuses'),
    ('Submitted',    'Submitted'),
    ('Assigned',     'Assigned'),
    ('In Progress',  'In Progress'),
    ('Pending Info', 'Pending Info'),
    ('Resolved',     'Resolved'),
    ('Rejected',     'Rejected'),
]

ALLOWED_EXT = ['pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx']
MAX_FILES    = 5
MAX_MB       = 5


class SubmitTicketForm(FlaskForm):
    title = StringField(
        'Title',
        validators=[DataRequired(), Length(min=5, max=255)],
        render_kw={"placeholder": "Brief summary of your complaint"}
    )
    category = SelectField('Category', choices=CATEGORIES, validators=[DataRequired()])
    description = TextAreaField(
        'Description',
        validators=[DataRequired(), Length(min=20)],
        render_kw={"rows": 6, "placeholder": "Describe your grievance in detail..."}
    )
    attachments = MultipleFileField(
        'Attachments (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents allowed.')]
    )
    submit = SubmitField('Submit Complaint')


class EditTicketForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=5, max=255)])
    category = SelectField('Category', choices=CATEGORIES, validators=[DataRequired()])
    description = TextAreaField(
        'Description',
        validators=[DataRequired(), Length(min=20)],
        render_kw={"rows": 6}
    )
    attachments = MultipleFileField(
        'Add More Attachments (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents allowed.')]
    )
    submit = SubmitField('Save Changes')


class FeedbackForm(FlaskForm):
    rating = IntegerField(
        'Rating (1–5)',
        validators=[DataRequired(), NumberRange(min=1, max=5)]
    )
    comment = TextAreaField(
        'Comment (optional)',
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 4, "placeholder": "Share your experience..."}
    )
    submit = SubmitField('Submit Feedback')


class TicketFilterForm(FlaskForm):
    class Meta:
        csrf = False

    status   = SelectField('Status',   choices=STATUS_FILTER_CHOICES, validators=[Optional()])
    category = SelectField(
        'Category',
        choices=[('', 'All Categories')] + CATEGORIES,
        validators=[Optional()]
    )
    search = StringField(
        'Search', validators=[Optional()],
        render_kw={"placeholder": "Search title..."}
    )


class StudentReplyForm(FlaskForm):
    comment = TextAreaField(
        'Your Reply',
        validators=[DataRequired(), Length(min=2, max=2000)],
        render_kw={"rows": 3, "placeholder": "Write your reply..."}
    )
    attachments = MultipleFileField(
        'Attach files (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents allowed.')]
    )
    submit = SubmitField('Reply')