"""Add ticket comment threads and image attachments

Revision ID: 9f3c2a1b4e6d
Revises: 312e87db970f
Create Date: 2026-03-20 09:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3c2a1b4e6d'
down_revision = '312e87db970f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ticket_comments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ParentCommentId', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_ticket_comments_ParentCommentId'), ['ParentCommentId'], unique=False)
        batch_op.create_foreign_key(
            'fk_ticket_comments_parent_comment_id',
            'ticket_comments',
            ['ParentCommentId'],
            ['CommentId'],
        )

    op.create_table(
        'comment_attachments',
        sa.Column('AttachmentId', sa.Integer(), nullable=False),
        sa.Column('CommentId', sa.Integer(), nullable=False),
        sa.Column('FileName', sa.String(length=255), nullable=False),
        sa.Column('FilePath', sa.String(length=500), nullable=False),
        sa.Column('UploadedAt', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['CommentId'], ['ticket_comments.CommentId'], name='fk_comment_attachments_comment_id'),
        sa.PrimaryKeyConstraint('AttachmentId'),
    )
    with op.batch_alter_table('comment_attachments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_comment_attachments_CommentId'), ['CommentId'], unique=False)


def downgrade():
    with op.batch_alter_table('comment_attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_comment_attachments_CommentId'))

    op.drop_table('comment_attachments')

    with op.batch_alter_table('ticket_comments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_ticket_comments_parent_comment_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_ticket_comments_ParentCommentId'))
        batch_op.drop_column('ParentCommentId')
