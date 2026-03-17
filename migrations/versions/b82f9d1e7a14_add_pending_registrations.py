"""add pending registrations

Revision ID: b82f9d1e7a14
Revises: 9a1b2c3d4e5f
Create Date: 2026-03-17 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b82f9d1e7a14'
down_revision = '9a1b2c3d4e5f'
branch_labels = None
depends_on = None


role_enum = sa.Enum('Student', 'Staff', 'Admin', name='roleenum')


def upgrade():
    bind = op.get_bind()
    role_enum.create(bind, checkfirst=True)

    op.create_table(
        'pending_registrations',
        sa.Column('PendingId', sa.Integer(), nullable=False),
        sa.Column('FullName', sa.String(length=150), nullable=False),
        sa.Column('Email', sa.String(length=150), nullable=False),
        sa.Column('PasswordHash', sa.String(length=256), nullable=False),
        sa.Column('Role', role_enum, nullable=False),
        sa.Column('POPIAConsent', sa.Boolean(), nullable=False),
        sa.Column('POPIAConsentAt', sa.DateTime(), nullable=True),
        sa.Column('VerificationTokenHash', sa.String(length=64), nullable=False),
        sa.Column('VerificationExpiresAt', sa.DateTime(), nullable=False),
        sa.Column('LastVerificationSentAt', sa.DateTime(), nullable=True),
        sa.Column('ConsumedAt', sa.DateTime(), nullable=True),
        sa.Column('CreatedAt', sa.DateTime(), nullable=False),
        sa.Column('UpdatedAt', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('PendingId'),
        sa.UniqueConstraint('Email', name='uq_pending_registrations_email'),
    )
    op.create_index(op.f('ix_pending_registrations_Email'), 'pending_registrations', ['Email'], unique=False)
    op.create_index(op.f('ix_pending_registrations_VerificationTokenHash'), 'pending_registrations', ['VerificationTokenHash'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_pending_registrations_VerificationTokenHash'), table_name='pending_registrations')
    op.drop_index(op.f('ix_pending_registrations_Email'), table_name='pending_registrations')
    op.drop_table('pending_registrations')
