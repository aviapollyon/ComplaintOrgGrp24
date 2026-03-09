"""Add TrackingRef to tickets and POPIA consent to users

Revision ID: a1b2c3d4e5f6
Revises: c7c18cc8569f
Create Date: 2026-03-09 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'c7c18cc8569f'
branch_labels = None
depends_on = None


def upgrade():
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.add_column(sa.Column('TrackingRef', sa.String(length=20), nullable=True))
        batch_op.create_unique_constraint('uq_tickets_tracking_ref', ['TrackingRef'])
        batch_op.create_index('ix_tickets_tracking_ref', ['TrackingRef'], unique=True)

    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('POPIAConsent', sa.Boolean(), nullable=False,
                                      server_default='0'))
        batch_op.add_column(sa.Column('POPIAConsentAt', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('tickets') as batch_op:
        batch_op.drop_index('ix_tickets_tracking_ref')
        batch_op.drop_constraint('uq_tickets_tracking_ref', type_='unique')
        batch_op.drop_column('TrackingRef')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('POPIAConsentAt')
        batch_op.drop_column('POPIAConsent')
