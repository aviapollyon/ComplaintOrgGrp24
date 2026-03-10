from flask_wtf import FlaskForm
from wtforms import (
    StringField, SelectField, SubmitField,
    TextAreaField, PasswordField
)
from wtforms.validators import DataRequired, Email, Length, Optional, EqualTo
from app.utils.helpers import TICKET_CATEGORIES, CATEGORY_SUBCATEGORY_MAP

_all_subs = sorted({s for subs in CATEGORY_SUBCATEGORY_MAP.values() for s in subs})
SUBCATEGORY_FILTER_CHOICES = [('', 'All Sub-Categories')] + [(s, s) for s in _all_subs]

ROLE_CHOICES = [
    ('Student', 'Student'),
    ('Staff',   'Staff'),
    ('Admin',   'Admin'),
]
AUDIENCE_CHOICES = [
    ('All',     'All Users'),
    ('Student', 'Students Only'),
    ('Staff',   'Staff Only'),
]
STATUS_CHOICES = [
    ('',             'All Statuses'),
    ('Submitted',    'Submitted'),
    ('Assigned',     'Assigned'),
    ('In Progress',  'In Progress'),
    ('Pending Info', 'Pending Info'),
    ('Resolved',     'Resolved'),
    ('Rejected',     'Rejected'),
]
PRIORITY_CHOICES = [
    ('',       'All Priorities'),
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


class AddUserForm(FlaskForm):
    full_name  = StringField('Full Name',  validators=[DataRequired(), Length(min=2, max=150)])
    email      = StringField('Email',      validators=[DataRequired(), Email()])
    password   = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm    = PasswordField('Confirm',  validators=[DataRequired(),
                               EqualTo('password', message='Passwords must match')])
    role       = SelectField('Role',       choices=ROLE_CHOICES, validators=[DataRequired()])
    department = SelectField('Department', coerce=int, validators=[Optional()])
    submit     = SubmitField('Create User')


class EditUserForm(FlaskForm):
    full_name  = StringField('Full Name',  validators=[DataRequired(), Length(min=2, max=150)])
    email      = StringField('Email',      validators=[DataRequired(), Email()])
    role       = SelectField('Role',       choices=ROLE_CHOICES, validators=[DataRequired()])
    department = SelectField('Department', coerce=int, validators=[Optional()])
    submit     = SubmitField('Save Changes')


class AdminTicketFilterForm(FlaskForm):
    class Meta:
        csrf = False
    search       = StringField('Search',       validators=[Optional()])
    status       = SelectField('Status',       choices=STATUS_CHOICES,   validators=[Optional()])
    priority     = SelectField('Priority',     choices=PRIORITY_CHOICES, validators=[Optional()])
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
    department   = SelectField('Department', coerce=int, validators=[Optional()])
    staff        = SelectField('Staff',      coerce=int, validators=[Optional()])
    sort         = SelectField('Sort By',    choices=SORT_CHOICES, validators=[Optional()])
    per_page     = SelectField('Per Page',
                               choices=[('10','10'),('15','15'),('25','25'),('50','50'),('100','100')],
                               default='15', validators=[Optional()])


class AdminUserFilterForm(FlaskForm):
    class Meta:
        csrf = False
    search     = StringField('Search',     validators=[Optional()])
    role       = SelectField('Role',
                             choices=[('', 'All Roles')] + ROLE_CHOICES,
                             validators=[Optional()])
    department = SelectField('Department', coerce=int, validators=[Optional()])
    per_page   = SelectField('Per Page',
                             choices=[('10','10'),('20','20'),('25','25'),('50','50'),('100','100')],
                             default='20', validators=[Optional()])


class ReassignTicketForm(FlaskForm):
    staff_id = SelectField('Reassign To', coerce=int, validators=[DataRequired()])
    submit   = SubmitField('Reassign')


class EscalationReviewForm(FlaskForm):
    staff_id = SelectField('Assign To (Target Dept)', coerce=int,
                           validators=[DataRequired()])
    submit   = SubmitField('Approve & Assign')


class ReassignmentReviewForm(FlaskForm):
    submit = SubmitField('Approve Reassignment')


class ReopenReviewForm(FlaskForm):
    submit = SubmitField('Approve Reopen')


class ForceStatusForm(FlaskForm):
    status  = SelectField('New Status', choices=STATUS_CHOICES[1:],
                          validators=[DataRequired()])
    comment = TextAreaField('Reason / Note',
                            validators=[DataRequired(), Length(min=5, max=1000)],
                            render_kw={"rows": 3, "placeholder": "Reason for override..."})
    submit  = SubmitField('Apply Status')


PRIORITY_OVERRIDE_CHOICES = [
    ('High',   'High'),
    ('Medium', 'Medium'),
    ('Low',    'Low'),
]


class ForcePriorityForm(FlaskForm):
    priority = SelectField('New Priority', choices=PRIORITY_OVERRIDE_CHOICES,
                           validators=[DataRequired()])
    reason   = TextAreaField('Reason',
                             validators=[DataRequired(), Length(min=5, max=500)],
                             render_kw={"rows": 2,
                                        "placeholder": "Reason for priority override..."})
    submit   = SubmitField('Apply Priority')


class AddDepartmentForm(FlaskForm):
    name        = StringField('Department Name',
                              validators=[DataRequired(), Length(min=2, max=120)])
    description = TextAreaField('Description',
                                validators=[Optional(), Length(max=300)],
                                render_kw={"rows": 3})
    submit      = SubmitField('Add Department')


class EditDepartmentForm(FlaskForm):
    name        = StringField('Department Name',
                              validators=[DataRequired(), Length(min=2, max=120)])
    description = TextAreaField('Description',
                                validators=[Optional(), Length(max=300)],
                                render_kw={"rows": 3})
    submit      = SubmitField('Save Changes')


class AnnouncementForm(FlaskForm):
    title    = StringField('Title',   validators=[DataRequired(), Length(min=3, max=200)])
    message  = TextAreaField('Message', validators=[DataRequired(), Length(min=10)],
                             render_kw={"rows": 5})
    audience = SelectField('Target Audience', choices=AUDIENCE_CHOICES,
                           validators=[DataRequired()])
    submit   = SubmitField('Post Announcement')