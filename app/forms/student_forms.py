from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed
from wtforms import (
    StringField, TextAreaField, SelectField,
    SubmitField, IntegerField, MultipleFileField, BooleanField, HiddenField
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from app.utils.helpers import TICKET_CATEGORIES, CATEGORY_SUBCATEGORY_MAP

CATEGORY_CHOICES = [('', '— Select Category —')] + [(c, c) for c in TICKET_CATEGORIES]

_all_subs = sorted({s for subs in CATEGORY_SUBCATEGORY_MAP.values() for s in subs})
SUBCATEGORY_FILTER_CHOICES = [('', 'All Sub-Categories')] + [(s, s) for s in _all_subs]

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
    ('newest',      'Newest First'),
    ('oldest',      'Oldest First'),
    ('priority',    'Priority (High → Low)'),
    ('subcategory', 'Sub-Category (A–Z)'),
    ('title',       'Title (A–Z)'),
    ('id_asc',      'Ticket # (Low → High)'),
    ('id_desc',     'Ticket # (High → Low)'),
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


PRIORITY_FILTER_CHOICES = [
    ('', 'All Priorities'),
    ('High',   'High'),
    ('Medium', 'Medium'),
    ('Low',    'Low'),
]


class TicketFilterForm(FlaskForm):
    class Meta:
        csrf = False
    status       = SelectField('Status',       choices=STATUS_FILTER_CHOICES,      validators=[Optional()])
    priority     = SelectField('Priority',     choices=PRIORITY_FILTER_CHOICES,    validators=[Optional()])
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


class TicketCommentForm(FlaskForm):
    parent_comment_id = HiddenField('Parent Comment Id', validators=[Optional()])
    content = TextAreaField(
        'Comment',
        validators=[DataRequired(), Length(min=2, max=1000)],
        render_kw={"rows": 3, "placeholder": "Add your comment..."}
    )
    attachments = MultipleFileField(
        'Images (optional)',
        validators=[FileAllowed(['png', 'jpg', 'jpeg', 'gif', 'webp'], 'Only image files are allowed.')]
    )
    submit = SubmitField('Post Comment')


class SocialPreferenceForm(FlaskForm):
    suppress_social = BooleanField('Disable notifications for social votes and comments')
    submit = SubmitField('Save Preference')


class StudentLiveChatForm(FlaskForm):
    message = TextAreaField(
        'Message',
        validators=[DataRequired(), Length(min=1, max=2000)],
        render_kw={"rows": 2, "placeholder": "Type your message..."},
    )
    attachments = MultipleFileField(
        'Attachments (optional)',
        validators=[FileAllowed(ALLOWED_EXT, 'Only PDF, images, and Word documents.')],
    )
    submit = SubmitField('Send')