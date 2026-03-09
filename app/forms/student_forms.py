from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import (
    StringField, TextAreaField, SelectField,
    SubmitField, IntegerField, MultipleFileField
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from app.utils.helpers import TICKET_CATEGORIES, CATEGORY_SUBCATEGORY_MAP

CATEGORY_CHOICES = [('', '— Select Category —')] + [(c, c) for c in TICKET_CATEGORIES]

ALLOWED_EXT = ['pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx']

STATUS_FILTER_CHOICES = [
    ('', 'All Statuses'),
    ('Submitted',    'Submitted'),
    ('Assigned',     'Assigned'),
    ('In Progress',  'In Progress'),
    ('Pending Info', 'Pending Info'),
    ('Resolved',     'Resolved'),
    ('Rejected',     'Rejected'),
]

SORT_CHOICES = [
    ('newest',   'Newest First'),
    ('oldest',   'Oldest First'),
    ('priority', 'Priority (High → Low)'),
    ('title',    'Title (A–Z)'),
    ('id_asc',   'Ticket # (Low → High)'),
    ('id_desc',  'Ticket # (High → Low)'),
]


class SubmitTicketForm(FlaskForm):
    title = StringField(
        'Title',
        validators=[DataRequired(), Length(min=5, max=255)],
        render_kw={"placeholder": "Brief summary of your complaint"}
    )
    category = SelectField(
        'Category',
        choices=CATEGORY_CHOICES,
        validators=[DataRequired()],
    )
    sub_category = SelectField(
        'Sub-Category',
        choices=[('', '— Select Category first —')],
        validators=[DataRequired()],
    )
    description = TextAreaField(
        'Description',
        validators=[DataRequired(), Length(min=20)],
        render_kw={"rows": 6, "placeholder": "Describe your grievance in detail..."}
    )
    attachments = MultipleFileField(
        'Attachments (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents.')]
    )
    submit = SubmitField('Submit Complaint')


class EditTicketForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=5, max=255)])
    category = SelectField(
        'Category',
        choices=CATEGORY_CHOICES,
        validators=[DataRequired()],
    )
    sub_category = SelectField(
        'Sub-Category',
        choices=[('', '— Select Category first —')],
        validators=[DataRequired()],
    )
    description = TextAreaField(
        'Description',
        validators=[DataRequired(), Length(min=20)],
        render_kw={"rows": 6}
    )
    attachments = MultipleFileField(
        'Add More Attachments (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents.')]
    )
    submit = SubmitField('Save Changes')


class FeedbackForm(FlaskForm):
    rating  = IntegerField('Rating', validators=[DataRequired(), NumberRange(min=1, max=5)])
    comment = TextAreaField('Comment (optional)',
                            validators=[Optional(), Length(max=1000)],
                            render_kw={"rows": 4, "placeholder": "Share your experience..."})
    submit  = SubmitField('Submit Feedback')


class TicketFilterForm(FlaskForm):
    class Meta:
        csrf = False
    status   = SelectField('Status',   choices=STATUS_FILTER_CHOICES, validators=[Optional()])
    category = SelectField(
        'Category',
        choices=[('', 'All Categories')] + [(c, c) for c in TICKET_CATEGORIES],
        validators=[Optional()]
    )
    search   = StringField('Search', validators=[Optional()],
                           render_kw={"placeholder": "Search title..."})
    sort     = SelectField('Sort By', choices=SORT_CHOICES, validators=[Optional()])


class StudentReplyForm(FlaskForm):
    comment = TextAreaField(
        'Your Reply',
        validators=[DataRequired(), Length(min=2, max=2000)],
        render_kw={"rows": 3, "placeholder": "Write your reply..."}
    )
    attachments = MultipleFileField(
        'Attach files (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents.')]
    )
    submit = SubmitField('Reply')


class ReopenRequestForm(FlaskForm):
    reason = TextAreaField(
        'Reason for Reopening',
        validators=[DataRequired(), Length(min=10, max=1000)],
        render_kw={"rows": 4,
                   "placeholder": "Explain why you believe this ticket should be reopened..."}
    )
    submit = SubmitField('Request Reopen')