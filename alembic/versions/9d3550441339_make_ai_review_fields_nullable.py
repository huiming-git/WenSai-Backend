"""make ai review fields nullable

Revision ID: 9d3550441339
Revises: e653cce7d20d
Create Date: 2026-04-25 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d3550441339"
down_revision: Union[str, Sequence[str], None] = "e653cce7d20d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.alter_column("score", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("content", existing_type=sa.Text(), nullable=True)
        batch_op.alter_column("recommendation", existing_type=sa.String(length=20), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE reviews SET score = 0 WHERE score IS NULL")
    op.execute("UPDATE reviews SET content = '' WHERE content IS NULL")
    op.execute("UPDATE reviews SET recommendation = 'minor_revision' WHERE recommendation IS NULL")
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.alter_column("recommendation", existing_type=sa.String(length=20), nullable=False)
        batch_op.alter_column("content", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column("score", existing_type=sa.Integer(), nullable=False)
