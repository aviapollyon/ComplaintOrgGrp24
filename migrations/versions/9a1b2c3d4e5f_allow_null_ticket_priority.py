"""Allow null ticket priority

Revision ID: 9a1b2c3d4e5f
Revises: c487668a9f79
Create Date: 2026-03-17 13:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a1b2c3d4e5f'
down_revision = 'c487668a9f79'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.alter_column(
            'Priority',
            existing_type=sa.Enum('High', 'Medium', 'Low', name='priorityenum'),
            nullable=True,
        )


def downgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.alter_column(
            'Priority',
            existing_type=sa.Enum('High', 'Medium', 'Low', name='priorityenum'),
            nullable=False,
            existing_server_default=None,
        )
