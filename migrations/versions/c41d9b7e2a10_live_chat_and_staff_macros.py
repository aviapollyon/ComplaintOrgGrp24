"""Add live chat and staff macros

Revision ID: c41d9b7e2a10
Revises: 9f3c2a1b4e6d
Create Date: 2026-03-23 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c41d9b7e2a10'
down_revision = '9f3c2a1b4e6d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'staff_macros',
        sa.Column('MacroId', sa.Integer(), nullable=False),
        sa.Column('UserId', sa.Integer(), nullable=False),
        sa.Column('Name', sa.String(length=120), nullable=False),
        sa.Column('MacroType', sa.String(length=80), nullable=False),
        sa.Column('Content', sa.Text(), nullable=False),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('UpdatedAt', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['UserId'], ['users.UserId'], name='fk_staff_macros_user_id'),
        sa.PrimaryKeyConstraint('MacroId'),
    )
    with op.batch_alter_table('staff_macros', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_staff_macros_UserId'), ['UserId'], unique=False)
        batch_op.create_index(batch_op.f('ix_staff_macros_Name'), ['Name'], unique=False)
        batch_op.create_index(batch_op.f('ix_staff_macros_MacroType'), ['MacroType'], unique=False)

    op.create_table(
        'ticket_chat_messages',
        sa.Column('ChatMessageId', sa.Integer(), nullable=False),
        sa.Column('TicketId', sa.Integer(), nullable=False),
        sa.Column('UserId', sa.Integer(), nullable=False),
        sa.Column('Message', sa.Text(), nullable=False),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['TicketId'], ['tickets.TicketId'], name='fk_chat_messages_ticket_id'),
        sa.ForeignKeyConstraint(['UserId'], ['users.UserId'], name='fk_chat_messages_user_id'),
        sa.PrimaryKeyConstraint('ChatMessageId'),
    )
    with op.batch_alter_table('ticket_chat_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ticket_chat_messages_TicketId'), ['TicketId'], unique=False)
        batch_op.create_index(batch_op.f('ix_ticket_chat_messages_UserId'), ['UserId'], unique=False)
        batch_op.create_index(batch_op.f('ix_ticket_chat_messages_CreatedAt'), ['CreatedAt'], unique=False)

    op.create_table(
        'ticket_chat_attachments',
        sa.Column('ChatAttachmentId', sa.Integer(), nullable=False),
        sa.Column('ChatMessageId', sa.Integer(), nullable=False),
        sa.Column('FileName', sa.String(length=255), nullable=False),
        sa.Column('FilePath', sa.String(length=500), nullable=False),
        sa.Column('UploadedAt', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ChatMessageId'], ['ticket_chat_messages.ChatMessageId'], name='fk_chat_attachments_message_id'),
        sa.PrimaryKeyConstraint('ChatAttachmentId'),
    )
    with op.batch_alter_table('ticket_chat_attachments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ticket_chat_attachments_ChatMessageId'), ['ChatMessageId'], unique=False)

    op.create_table(
        'ticket_chat_presence',
        sa.Column('PresenceId', sa.Integer(), nullable=False),
        sa.Column('TicketId', sa.Integer(), nullable=False),
        sa.Column('UserId', sa.Integer(), nullable=False),
        sa.Column('LastSeenAt', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['TicketId'], ['tickets.TicketId'], name='fk_chat_presence_ticket_id'),
        sa.ForeignKeyConstraint(['UserId'], ['users.UserId'], name='fk_chat_presence_user_id'),
        sa.PrimaryKeyConstraint('PresenceId'),
        sa.UniqueConstraint('TicketId', 'UserId', name='uq_chat_presence_ticket_user'),
    )
    with op.batch_alter_table('ticket_chat_presence', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ticket_chat_presence_TicketId'), ['TicketId'], unique=False)
        batch_op.create_index(batch_op.f('ix_ticket_chat_presence_UserId'), ['UserId'], unique=False)
        batch_op.create_index(batch_op.f('ix_ticket_chat_presence_LastSeenAt'), ['LastSeenAt'], unique=False)


def downgrade():
    with op.batch_alter_table('ticket_chat_presence', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ticket_chat_presence_LastSeenAt'))
        batch_op.drop_index(batch_op.f('ix_ticket_chat_presence_UserId'))
        batch_op.drop_index(batch_op.f('ix_ticket_chat_presence_TicketId'))
    op.drop_table('ticket_chat_presence')

    with op.batch_alter_table('ticket_chat_attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ticket_chat_attachments_ChatMessageId'))
    op.drop_table('ticket_chat_attachments')

    with op.batch_alter_table('ticket_chat_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ticket_chat_messages_CreatedAt'))
        batch_op.drop_index(batch_op.f('ix_ticket_chat_messages_UserId'))
        batch_op.drop_index(batch_op.f('ix_ticket_chat_messages_TicketId'))
    op.drop_table('ticket_chat_messages')

    with op.batch_alter_table('staff_macros', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_staff_macros_MacroType'))
        batch_op.drop_index(batch_op.f('ix_staff_macros_Name'))
        batch_op.drop_index(batch_op.f('ix_staff_macros_UserId'))
    op.drop_table('staff_macros')
